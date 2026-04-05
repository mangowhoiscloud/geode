"""LLM fallback infrastructure — CircuitBreaker + retry with backoff.

Shared by all providers (Anthropic, OpenAI, GLM).
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

from core.config import settings

log = logging.getLogger(__name__)

# Failover configuration — sourced from settings with backward-compat defaults
MAX_RETRIES = settings.llm_max_retries
RETRY_BASE_DELAY = settings.llm_retry_base_delay
RETRY_MAX_DELAY = settings.llm_retry_max_delay


def _is_auth_error(exc: Exception) -> bool:
    """Check if exception is an authentication/401 error from any provider."""
    try:
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            return True
    except ImportError:
        pass
    # OpenAI AuthenticationError
    exc_name = type(exc).__name__
    return exc_name == "AuthenticationError" or "401" in str(exc)[:50]


def _try_oauth_refresh(provider_label: str) -> bool:
    """Attempt OAuth token refresh for managed profiles + reset clients.

    Returns True if a token was refreshed and clients were reset.
    """
    try:
        from core.runtime_wiring.infra import get_profile_rotator

        rotator = get_profile_rotator()
        if not rotator:
            return False

        provider = "anthropic" if "LLM" in provider_label else "openai"
        profile = rotator.resolve(provider)
        if not profile or not profile.managed_by:
            return False

        # claude-code OAuth disabled (Anthropic ToS violation)
        if profile.managed_by == "codex-cli":
            from core.gateway.auth.codex_cli_oauth import (
                refresh_codex_cli_token,
            )
            from core.llm.providers.openai import reset_openai_client

            if refresh_codex_cli_token(profile):
                reset_openai_client()
                return True
    except Exception as exc:
        log.debug("OAuth refresh failed: %s", exc)
    return False


class CircuitBreaker:
    """Thread-safe circuit breaker for LLM API calls.

    Used in ThreadPoolExecutor contexts (sub-agent MAX_CONCURRENT=5),
    so all state mutations are protected by a threading.Lock.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._last_failure: float = 0.0
        self._state: str = "closed"  # closed, open, half-open

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure = time.time()
            if self._failures >= self._threshold:
                self._state = "open"
                log.warning(
                    "Circuit breaker OPEN after %d failures (threshold=%d)",
                    self._failures,
                    self._threshold,
                )

    def record_success(self) -> None:
        with self._lock:
            prev_state = self._state
            self._failures = 0
            self._state = "closed"
            if prev_state == "half-open":
                log.info("Circuit breaker CLOSED (recovered from half-open)")

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if time.time() - self._last_failure > self._recovery_timeout:
                    self._state = "half-open"
                    log.info("Circuit breaker HALF-OPEN (cooldown expired, testing)")
                    return True
                return False
            return True  # half-open: allow one attempt


def retry_with_backoff_generic(
    fn: Any,
    *,
    model: str,
    fallback_models: list[str],
    circuit_breaker: CircuitBreaker,
    retryable_errors: tuple[type[Exception], ...],
    bad_request_error: type[Exception] | None = None,
    billing_message: str = "API billing/credit error.",
    max_retries: int = MAX_RETRIES,
    retry_base_delay: float = RETRY_BASE_DELAY,
    retry_max_delay: float = RETRY_MAX_DELAY,
    provider_label: str = "LLM",
    on_retry: Any | None = None,
) -> Any:
    """Generic retry with exponential backoff + model fallback + circuit breaker.

    Shared by Anthropic (``_retry_with_backoff``) and OpenAI
    (``OpenAIAdapter._retry_with_backoff``) to eliminate DRY violation.

    Stage 1: Retry same model with exponential backoff.
    Stage 2: On persistent failure, try fallback models.
    Stage 3: Circuit breaker prevents calls when API is down.

    Args:
        fn: Callable accepting ``model`` keyword argument.
        model: Primary model name.
        fallback_models: Ordered fallback model chain.
        circuit_breaker: CircuitBreaker instance for this provider.
        retryable_errors: Tuple of exception types that trigger retry.
        bad_request_error: Exception type for bad-request errors (e.g.
            ``anthropic.BadRequestError``, ``openai.BadRequestError``).
            If None, bad-request handling is skipped.
        billing_message: Error message for billing/credit errors.
        max_retries: Per-model retry count.
        retry_base_delay: Base delay in seconds.
        retry_max_delay: Max delay cap in seconds.
        provider_label: Label for log messages (e.g. "LLM", "OpenAI").
    """
    if not circuit_breaker.can_execute():
        raise RuntimeError(
            f"Circuit breaker is open — {provider_label} API calls are temporarily blocked. "
            "Too many consecutive failures detected."
        )

    models_to_try = [model] + [m for m in fallback_models if m != model]

    # C2: filter out fallback models that exceed cost ratio limit
    from core.config import settings as _cfg

    if _cfg.llm_max_fallback_cost_ratio > 0 and len(models_to_try) > 1:
        from core.llm.token_tracker import MODEL_PRICING

        primary_price = MODEL_PRICING.get(model)
        if primary_price and primary_price.input > 0:
            filtered = [model]
            for fb_model in models_to_try[1:]:
                fb_price = MODEL_PRICING.get(fb_model)
                if fb_price and fb_price.input > 0:
                    ratio = fb_price.input / primary_price.input
                    if ratio > _cfg.llm_max_fallback_cost_ratio:
                        log.warning(
                            "C2: fallback %s→%s cost ratio %.1fx exceeds limit %.1fx — skipping",
                            model,
                            fb_model,
                            ratio,
                            _cfg.llm_max_fallback_cost_ratio,
                        )
                        continue
                filtered.append(fb_model)
            models_to_try = filtered

    last_error: Exception | None = None
    t0_retry = time.monotonic()

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            try:
                result = fn(model=current_model)
                circuit_breaker.record_success()
                return result
            except retryable_errors as exc:
                last_error = exc
                delay = random.uniform(0, min(retry_base_delay * (2**attempt), retry_max_delay))
                elapsed = time.monotonic() - t0_retry
                log.warning(
                    "%s call failed (model=%s, attempt=%d/%d): %s. Retrying in %.1fs",
                    provider_label,
                    current_model,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    delay,
                )
                if on_retry is not None:
                    import contextlib

                    with contextlib.suppress(Exception):
                        on_retry(
                            model=current_model,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_s=delay,
                            elapsed_s=elapsed,
                            error_type=type(exc).__name__,
                        )
                time.sleep(delay)
            except Exception as exc:
                if bad_request_error is not None and isinstance(exc, bad_request_error):
                    error_msg = str(exc)
                    if "billing" in error_msg.lower() or "credit" in error_msg.lower():
                        from core.llm.errors import BillingError

                        raise BillingError(billing_message) from exc
                    if any(
                        k in error_msg.lower()
                        for k in ("token", "context", "prompt exceeds", "max length")
                    ):
                        log.error(
                            "Context overflow detected (model=%s): %s",
                            current_model,
                            error_msg,
                        )
                # C1+C2: OAuth 401 auto-refresh — re-read token + reset client + 1 retry
                if _is_auth_error(exc) and attempt == 0:
                    refreshed = _try_oauth_refresh(provider_label)
                    if refreshed:
                        log.info(
                            "OAuth token refreshed for %s, retrying",
                            provider_label,
                        )
                        continue  # retry with refreshed token
                raise

        if model_idx < len(models_to_try) - 1:
            next_model = models_to_try[model_idx + 1]
            log.warning(
                "All retries exhausted for model=%s. Falling back to %s",
                current_model,
                next_model,
            )

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    circuit_breaker.record_failure()
    log.error("All %s models and retries exhausted. Last error: %s", provider_label, last_error)
    raise last_error
