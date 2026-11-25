"""Observe one actual adapter dispatch, independently of caller interpretation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from core.hooks.dispatch import fire_hook_async
from core.hooks.system import HookEvent, RuntimeEventBus
from core.llm.adapters.base import EmptyModelOutputError
from core.llm.errors import LLMResponseValidationError

log = logging.getLogger(__name__)


def resolve_llm_correlation(correlation: Mapping[str, Any]) -> dict[str, Any]:
    """Allocate missing call/attempt identity before any call join point."""
    call_id = correlation.get("llm_call_id") or f"llm-{uuid.uuid4().hex}"
    return {
        **correlation,
        "llm_call_id": call_id,
        "llm_attempt_id": correlation.get("llm_attempt_id") or f"{call_id}:attempt-1",
    }


# Providers echo an alias with a dated snapshot suffix (gpt-5.5-2026-01-01,
# claude-sonnet-4-5-20250929); that is the requested model, not a substitute.
_SNAPSHOT_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


def route_check(requested: str, served: str | None) -> str:
    """Classify one attempt's served model as ``match``, ``mismatch`` or ``unobserved``.

    A relay namespace (``openai/gpt-5.5``) is ignored only when the request
    itself named no namespace.
    """
    if not served:
        return "unobserved"

    def normalize(model: str) -> str:
        model = _SNAPSHOT_SUFFIX.sub("", model)
        return model if "/" in requested else model.rsplit("/", 1)[-1]

    return "match" if normalize(served) == normalize(requested) else "mismatch"


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _request_identity(request: Any) -> dict[str, Any]:
    """Digest the policy-shaping request parts; bodies never enter the record."""
    if request is None:
        return {}
    system_prompt = getattr(request, "system_prompt", "") or ""
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in getattr(request, "tools", ()) or ()
    ]
    return {
        "system_prompt_sha256": (
            hashlib.sha256(system_prompt.encode("utf-8")).hexdigest() if system_prompt else None
        ),
        "tool_schema_sha256": _sha256_json(tools) if tools else None,
        "temperature_requested": getattr(request, "temperature", None),
    }


def _call_validity(model: str, result: Any) -> dict[str, Any]:
    """Mark the attempt invalid when the provider served a different model."""
    check = route_check(model, getattr(result, "response_model", None))
    return {
        "route_check": check,
        "validity": {"match": "valid", "mismatch": "invalid"}.get(check),
        "invalid_reason": "route_contamination" if check == "mismatch" else None,
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
    counters["cache_write_1h_tokens"] = getattr(usage, "cache_write_1h_tokens", None)
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
                    **(
                        {"cache_creation_1h_tokens": counters["cache_write_1h_tokens"]}
                        if counters["cache_write_1h_tokens"] is not None
                        else {}
                    ),
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
                "system_fingerprint",
                "routing_strategy",
                "routing_attempt",
                "request_image_receipt",
            )
            if (value := getattr(result, key, None))
        },
        **(getattr(result, "request_params", None) or {}),
        **_call_validity(model, result),
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
    request: Any = None,
) -> T:
    """Record a dispatch attempt, not every internal SDK retry or semantic success.

    Call only at the physical terminal, after middleware transforms. Missing IDs
    get fresh identities; supplied main-loop retry identities remain unchanged.
    No request content or returned text is copied: an optional adapter
    ``request`` contributes only system-prompt and tool-schema digests. Without
    an explicit estimator, cost is provider-reported only; missing cost stays
    unknown.
    """
    metadata = {
        **resolve_llm_correlation(correlation),
        "model": model,
        "provider": provider,
        "adapter": adapter,
        "purpose": purpose,
        "source": source,
        "effort": effort,
        **_request_identity(request),
    }
    started_at = time.monotonic()
    await fire_hook_async(hooks, HookEvent.LLM_CALL_STARTED, metadata)
    try:
        result = await call()
    except BaseException as exc:
        completed = (
            exc.completed_result
            if isinstance(exc, (EmptyModelOutputError, LLMResponseValidationError))
            else None
        )
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
