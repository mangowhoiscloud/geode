"""Async model failover loop for AgenticLoop.

``call_with_failover`` iterates a model chain, applying per-model retry
with exponential backoff and policy filtering. Non-retryable errors
propagate immediately so the caller adapter can record ``last_error``.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.system import HookEvent
from core.llm.fallback import (
    RetryAttempt,
    RetryPolicy,
    auxiliary_retry_policy,
    run_with_retry_policy,
)
from core.llm.router._hooks import _fire_hook

log = logging.getLogger(__name__)


async def call_with_failover(
    models: list[str],
    call_fn: Any,
    *,
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    retry_max_delay: float | None = None,
    policy: RetryPolicy | None = None,
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
        max_retries: Legacy name for total attempts per model, including the
            initial call (default: settings.llm_max_retries).
        retry_base_delay: Base delay in seconds (default: settings.llm_retry_base_delay).
        retry_max_delay: Max delay cap in seconds (default: settings.llm_retry_max_delay).

    Returns:
        A tuple of ``(response, model_used)``. On complete failure,
        returns ``(None, None)``.
    """
    if policy is not None and any(
        value is not None for value in (max_retries, retry_base_delay, retry_max_delay)
    ):
        raise ValueError("pass either policy or legacy retry overrides, not both")
    resolved_policy = policy or auxiliary_retry_policy(
        max_attempts=max_retries,
        base_delay_s=retry_base_delay,
        max_delay_s=retry_max_delay,
    )
    if not resolved_policy.filter_models:
        raise ValueError("call_with_failover requires model filtering")

    def _emit_retry(event: RetryAttempt) -> None:
        _fire_hook(
            HookEvent.LLM_CALL_RETRIED,
            {
                **event.payload(),
                "max_retries": event.max_attempts,
                "error_type": event.error_type,
            },
        )

    outcome = await run_with_retry_policy(
        models,
        call_fn,
        policy=resolved_policy,
        on_retry=_emit_retry,
    )
    if not outcome.succeeded:
        log.error("Failover: all models exhausted. Last error: %s", outcome.last_error)
    return outcome.value, outcome.model
