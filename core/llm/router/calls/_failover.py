"""Async model failover loop for AgenticLoop.

``call_with_failover`` iterates a model chain, applying per-model retry
with exponential backoff and policy filtering. Non-retryable errors
propagate immediately so the caller adapter can record ``last_error``.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from core.config import is_model_allowed
from core.hooks.system import HookEvent
from core.llm.router._hooks import _fire_hook

# v0.88.0 — RETRYABLE_ERRORS / NON_RETRYABLE_ERRORS are lazy-resolved
# inside ``call_with_failover`` so the cold-start path through
# ``core.llm.router.calls._failover`` no longer triggers the 248 ms
# anthropic SDK import.  The ``providers.anthropic.__getattr__`` lookup
# is paid once on first failover dispatch, well after CLI bootstrap.

log = logging.getLogger(__name__)


async def call_with_failover(
    models: list[str],
    call_fn: Any,
    *,
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    retry_max_delay: float | None = None,
) -> tuple[Any | None, str | None]:
    """Execute an async LLM call with model failover chain.

    Iterates through the ``models`` list. For each model, retries on
    retryable errors (rate-limit, timeout, connection, server errors)
    with exponential backoff. If all retries for a model are exhausted,
    moves to the next model in the chain.

    Non-retryable errors (e.g. AuthenticationError) cause immediate failure
    without trying further models.

    Args:
        models: Ordered list of model names to try.
        call_fn: Async callable ``(model: str) -> response``.
        max_retries: Per-model retry count (default: settings.llm_max_retries).
        retry_base_delay: Base delay in seconds (default: settings.llm_retry_base_delay).
        retry_max_delay: Max delay cap in seconds (default: settings.llm_retry_max_delay).

    Returns:
        A tuple of ``(response, model_used)``. On complete failure,
        returns ``(None, None)``.
    """
    import asyncio as _asyncio

    # v0.88.0 — defer anthropic SDK load until first failover.  Module-level
    # tuple imports used to pull 248 ms anthropic graph at startup via
    # ``providers.anthropic.__getattr__``.
    from core.llm.fallback import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY
    from core.llm.providers.anthropic import (
        NON_RETRYABLE_ERRORS as _NON_RETRYABLE_ERRORS,
    )
    from core.llm.providers.anthropic import (
        RETRYABLE_ERRORS as _RETRYABLE_ERRORS,
    )

    _max_retries = max_retries if max_retries is not None else MAX_RETRIES
    _base_delay = retry_base_delay if retry_base_delay is not None else RETRY_BASE_DELAY
    _max_delay = retry_max_delay if retry_max_delay is not None else RETRY_MAX_DELAY

    # Filter models by policy (GAP 2: model-policy.toml governance)
    allowed_models = [m for m in models if is_model_allowed(m)]
    if not allowed_models:
        log.error("Failover: all models blocked by policy: %s", models)
        return None, None

    last_error: Exception | None = None
    _t0_failover = time.monotonic()

    for model_idx, current_model in enumerate(allowed_models):
        for attempt in range(_max_retries):
            try:
                result = await call_fn(current_model)
                return result, current_model
            except _NON_RETRYABLE_ERRORS as exc:
                # Context overflow → re-raise so adapter can set last_error
                error_msg = str(exc).lower()
                if "token" in error_msg or "context" in error_msg:
                    log.warning(
                        "Context overflow on model=%s: %s — propagating to adapter",
                        current_model,
                        type(exc).__name__,
                    )
                    raise
                # Other non-retryable: re-raise so adapter can set last_error
                log.warning(
                    "Non-retryable error on model=%s: %s — propagating to adapter",
                    current_model,
                    type(exc).__name__,
                )
                raise
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                wait = random.uniform(0, min(_base_delay * (2**attempt), _max_delay))
                _elapsed = time.monotonic() - _t0_failover
                log.debug(
                    "Failover: model=%s attempt=%d/%d error=%s, retrying in %.1fs",
                    current_model,
                    attempt + 1,
                    _max_retries,
                    type(exc).__name__,
                    wait,
                )
                # Emit LLM_CALL_RETRY for UX (elapsed timer + interrupt hint).
                # The legacy string "retry_wait" was silently swallowed by
                # ``fire_hook`` since no enum member named "RETRY_WAIT" exists —
                # routing to LLM_CALL_RETRY matches the payload semantics
                # (model + attempt + max_retries + delay_s + elapsed_s + error_type)
                # and unblocks any handler that listens to LLM_CALL_RETRY.
                _fire_hook(
                    HookEvent.LLM_CALL_RETRIED,
                    {
                        "model": current_model,
                        "attempt": attempt + 1,
                        "max_retries": _max_retries,
                        "delay_s": wait,
                        "elapsed_s": _elapsed,
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt < _max_retries - 1:
                    await _asyncio.sleep(wait)
            except Exception as exc:
                # Unexpected error: log and move on to next model
                last_error = exc
                log.debug(
                    "Failover: unexpected error on model=%s: %s",
                    current_model,
                    exc,
                )
                break  # break retry loop, try next model

        # All retries exhausted for this model
        if model_idx < len(allowed_models) - 1:
            next_model = allowed_models[model_idx + 1]
            log.info(
                "Failover: model=%s exhausted, falling back to %s",
                current_model,
                next_model,
            )

    log.error(
        "Failover: all models exhausted. Last error: %s",
        last_error,
    )
    return None, None
