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
        from core.lifecycle.container import get_profile_rotator

        rotator = get_profile_rotator()
        if not rotator:
            return False

        provider = "anthropic" if "LLM" in provider_label else "openai"
        profile = rotator.resolve(provider)
        if not profile or not profile.managed_by:
            return False

        # claude-code OAuth disabled (Anthropic ToS violation)
        if profile.managed_by == "codex-cli":
            from core.auth.codex_cli_oauth import (
                refresh_codex_cli_token,
            )
            from core.llm.providers.openai import reset_openai_client

            if refresh_codex_cli_token(profile):
                reset_openai_client()
                return True
    except Exception as exc:
        log.debug("OAuth refresh failed: %s", exc)
    return False


def _resolve_rotator_provider(provider_label: str) -> str:
    """Map provider_label (e.g. 'LLM', 'OpenAI', 'GLM') to rotator provider name."""
    label = provider_label.lower()
    if label in ("llm", "anthropic"):
        return "anthropic"
    if label in ("openai",):
        return "openai"
    if label in ("glm", "zhipuai"):
        return "glm"
    return label


def _notify_success(provider: str) -> None:
    """Notify ProfileRotator of LLM call success (non-blocking)."""
    try:
        from core.llm.credentials import notify_llm_success

        notify_llm_success(provider)
    except Exception:
        log.debug("Profile notify_success failed for %s", provider, exc_info=True)


def _notify_failure(provider: str, exc: Exception) -> None:
    """Notify ProfileRotator of LLM call failure (non-blocking)."""
    try:
        from core.llm.credentials import notify_llm_failure

        notify_llm_failure(provider, exc)
    except Exception:
        log.debug("Profile notify_failure failed for %s", provider, exc_info=True)


def _resolve_plan_for_billing_error(model: str) -> dict[str, str]:
    """Resolve Plan metadata for a model so BillingError carries context.

    v0.53.0 — used to render plan-aware quota-exhausted panels. Returns
    ``provider``, ``plan_id``, ``plan_display_name``, ``upgrade_url``.
    Empty values when routing fails (caller falls back to generic msg).
    """
    try:
        from core.auth.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is None:
            return {}
        plan = target.plan
        return {
            "provider": plan.provider,
            "plan_id": plan.id,
            "plan_display_name": plan.display_name,
            "upgrade_url": plan.upgrade_url or "",
        }
    except Exception:
        log.debug("Plan resolution for billing error failed", exc_info=True)
        return {}


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

    # Resolve provider name for rotator notification (strip "LLM"/"OpenAI" labels)
    _provider_for_rotator = _resolve_rotator_provider(provider_label)

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            try:
                result = fn(model=current_model)
                circuit_breaker.record_success()
                _notify_success(_provider_for_rotator)
                return result
            except retryable_errors as exc:
                # v0.52.2 — short-circuit billing-fatal errors. RateLimitError
                # with code=1113 (GLM "Insufficient balance") or
                # insufficient_quota (OpenAI) cannot be cured by waiting; the
                # 5×exp-backoff retry loop wastes ~40s per failure across all
                # fallback models for an error that needs user action.
                from core.llm.errors import (
                    BillingError,
                    extract_billing_message,
                    is_billing_fatal,
                )

                if is_billing_fatal(exc):
                    msg = extract_billing_message(exc)
                    log.error(
                        "Billing-fatal error on %s (model=%s) — no retry: %s",
                        provider_label,
                        current_model,
                        msg,
                    )
                    # v0.53.0 — attach plan context so the UI can render a
                    # plan-aware quota-exhausted panel.
                    plan_meta = _resolve_plan_for_billing_error(current_model)
                    raise BillingError(
                        msg or billing_message,
                        provider=plan_meta.get("provider", ""),
                        plan_id=plan_meta.get("plan_id", ""),
                        plan_display_name=plan_meta.get("plan_display_name", ""),
                        upgrade_url=plan_meta.get("upgrade_url", ""),
                    ) from exc
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
                    # v0.52.6 — short-circuit "Unsupported parameter" /
                    # "Invalid value" 400-class errors. Same backend will
                    # reject every retry with the same body; the v0.52.5
                    # incident burned 30s on Codex's
                    # ``Unsupported parameter: max_output_tokens`` before
                    # the circuit breaker tripped. Re-raise so the
                    # outer except (non-retryable_errors) catches and
                    # surfaces the original message.
                    from core.llm.errors import is_request_fatal

                    if is_request_fatal(exc):
                        log.error(
                            "Request-fatal 400 on %s (model=%s) — no retry: %s",
                            provider_label,
                            current_model,
                            str(exc)[:200],
                        )
                        raise
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
    _notify_failure(_provider_for_rotator, last_error)
    log.error("All %s models and retries exhausted. Last error: %s", provider_label, last_error)
    raise last_error
