"""Observe one actual adapter dispatch, independently of caller interpretation."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from core.hooks.dispatch import fire_hook_async
from core.hooks.system import HookEvent, RuntimeEventBus
from core.llm.adapters.base import EmptyModelOutputError

log = logging.getLogger(__name__)


def resolve_llm_correlation(correlation: Mapping[str, Any]) -> dict[str, Any]:
    """Allocate missing call/attempt identity before any call join point."""
    call_id = correlation.get("llm_call_id") or f"llm-{uuid.uuid4().hex}"
    return {
        **correlation,
        "llm_call_id": call_id,
        "llm_attempt_id": correlation.get("llm_attempt_id") or f"{call_id}:attempt-1",
    }


def _completed_attempt_payload(
    result: Any, model: str, *, cost_estimator: Callable[..., float] | None = None
) -> dict[str, Any]:
    """Project only completed-response accounting and bounded route evidence."""
    if result is None:
        return {}
    usage = getattr(result, "usage", None)
    counters: dict[str, int | None] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "cache_write_tokens",
    ):
        count = int(getattr(usage, key, 0) or 0)
        counters[key] = count if getattr(usage, f"{key}_present", False) or count > 0 else None
    reported_cost = getattr(usage, "reported_cost_usd", None)
    input_tokens, output_tokens = counters["input_tokens"], counters["output_tokens"]
    cost_usd = None
    try:
        if reported_cost is not None:
            cost_usd = float(reported_cost)
        elif cost_estimator is not None and input_tokens is not None and output_tokens is not None:
            cost_usd = float(
                cost_estimator(
                    model,
                    input_tokens,
                    output_tokens,
                    cache_creation_tokens=counters["cache_write_tokens"] or 0,
                    cache_read_tokens=counters["cached_input_tokens"] or 0,
                )
            )
    except Exception:
        log.warning(
            "calculate_cost failed for model=%s; cost remains unknown", model, exc_info=True
        )
    return {
        "usage": counters,
        "cost_usd": cost_usd,
        **{
            key: value
            for key in (
                "response_id",
                "response_model",
                "response_provider",
                "routing_strategy",
                "routing_attempt",
                "request_image_receipt",
            )
            if (value := getattr(result, key, None))
        },
    }


async def observe_llm_call[T](
    call: Callable[[], Awaitable[T]],
    *,
    hooks: RuntimeEventBus | None,
    correlation: Mapping[str, Any],
    model: str,
    provider: str,
    adapter: str,
    purpose: str,
    source: str | None = None,
    effort: str | None = None,
    cost_estimator: Callable[..., float] | None = None,
) -> T:
    """Record a dispatch attempt, not every internal SDK retry or semantic success.

    Call only at the physical terminal, after middleware transforms. Missing IDs
    get fresh identities; supplied main-loop retry identities remain unchanged.
    No request content or returned text is inspected or copied. Without an
    explicit estimator, cost is provider-reported only; missing cost stays unknown.
    """
    metadata = {
        **resolve_llm_correlation(correlation),
        "model": model,
        "provider": provider,
        "adapter": adapter,
        "purpose": purpose,
        "source": source,
        "effort": effort,
    }
    started_at = time.monotonic()
    await fire_hook_async(hooks, HookEvent.LLM_CALL_STARTED, metadata)
    try:
        result = await call()
    except BaseException as exc:
        completed = exc.completed_result if isinstance(exc, EmptyModelOutputError) else None
        try:
            await fire_hook_async(
                hooks,
                HookEvent.LLM_CALL_ENDED,
                {
                    **metadata,
                    "latency_ms": (time.monotonic() - started_at) * 1_000,
                    "error": type(exc).__name__,
                    "error_type": type(exc).__name__,
                    **_completed_attempt_payload(completed, model, cost_estimator=cost_estimator),
                },
            )
        except BaseException:
            log.warning("Failed to record LLM failure; preserving original exception")
        raise
    await fire_hook_async(
        hooks,
        HookEvent.LLM_CALL_ENDED,
        {
            **metadata,
            "latency_ms": (time.monotonic() - started_at) * 1_000,
            "error": None,
            **_completed_attempt_payload(result, model, cost_estimator=cost_estimator),
        },
    )
    return result
