"""LLM fallback infrastructure — CircuitBreaker + retry with backoff.

Shared by all providers (Anthropic, OpenAI, GLM).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.config import settings

log = logging.getLogger(__name__)

# Failover configuration — sourced from settings with backward-compat defaults
MAX_RETRIES = settings.llm_max_retries
RETRY_BASE_DELAY = settings.llm_retry_base_delay
RETRY_MAX_DELAY = settings.llm_retry_max_delay


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
    last_error: Exception | None = None

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            try:
                result = fn(model=current_model)
                circuit_breaker.record_success()
                return result
            except retryable_errors as exc:
                last_error = exc
                delay = min(retry_base_delay * (2**attempt), retry_max_delay)
                log.warning(
                    "%s call failed (model=%s, attempt=%d/%d): %s. Retrying in %.1fs",
                    provider_label,
                    current_model,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
            except Exception as exc:
                if bad_request_error is not None and isinstance(exc, bad_request_error):
                    error_msg = str(exc)
                    if "billing" in error_msg.lower() or "credit" in error_msg.lower():
                        from core.llm.errors import BillingError

                        raise BillingError(billing_message) from exc
                    if "token" in error_msg.lower() or "context" in error_msg.lower():
                        log.error(
                            "Context overflow detected (model=%s): %s",
                            current_model,
                            error_msg,
                        )
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
