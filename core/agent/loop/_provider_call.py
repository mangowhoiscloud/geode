"""Provider request assembly and durable adapter-session state."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Set
from dataclasses import replace
from typing import Any

from core.hooks import HookEvent, LlmCallRequest
from core.llm.adapters.base import AdapterCallRequest, EmptyModelOutputError
from core.llm.adapters.translation import agentic_response_from_adapter_result
from core.llm.agentic_response import AgenticResponse
from core.tools.plan import BoundToolPlan

from . import _context

log = logging.getLogger(__name__)


def _validate_bound_request_rewrite(
    original: AdapterCallRequest,
    effective: AdapterCallRequest,
) -> None:
    """Fail closed when middleware widens or relabels a bound tool request."""
    if (
        effective.tool_plan_hash != original.tool_plan_hash
        or effective.tool_plan_generation != original.tool_plan_generation
    ):
        raise ValueError("LLM middleware cannot change bound tool plan identity")

    if effective.tools != original.tools:
        raise ValueError("LLM middleware cannot change bound tool specs")
    if effective.deferred_tool_names != original.deferred_tool_names:
        raise ValueError("LLM middleware cannot change bound deferred tools")
    if effective.allowed_tool_names != original.allowed_tool_names:
        raise ValueError("LLM middleware cannot change bound tool allowlist")
    if effective.denied_tool_names != original.denied_tool_names:
        raise ValueError("LLM middleware cannot change bound tool denylist")
    if effective.executable_tool_names != original.executable_tool_names:
        raise ValueError("LLM middleware cannot change bound executable tools")


_FAIL_FAST_VALUES = frozenset({"1", "true", "yes", "on"})
_FAIL_FAST_RETRY_DELAY_S = 1.0
_FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS = 3


def _fail_fast_adapter_errors_enabled() -> bool:
    return (
        os.environ.get("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "").strip().lower()
        in _FAIL_FAST_VALUES
    )


async def _acomplete_with_fail_fast_pre_execution_retry(
    adapter: Any,
    request: Any,
    *,
    on_retry: Callable[[Exception, int, int], Awaitable[None]] | None = None,
    complete: Callable[[Any, Any], Awaitable[Any]] | None = None,
) -> Any:
    """Retry bounded pre-execution failures without reopening completed tool work.

    Normal AgenticLoop calls already retry after ``_call_llm`` returns
    ``None``. Strict evaluator routes instead raise adapter errors immediately
    so infrastructure cannot become semantic output. Preserve that boundary
    while giving a connection-class stream failure one same-adapter retry. An
    empty completed response gets at most three total attempts because repeated
    GPT-5.4 subscription empties have occurred at the previous two-attempt
    boundary. Every attempt uses the identical request before tool execution.
    """

    async def invoke() -> Any:
        if complete is not None:
            return await complete(adapter, request)
        return await adapter.acomplete(request)

    try:
        return await invoke()
    except Exception as exc:
        if not _fail_fast_adapter_errors_enabled():
            raise
        from core.llm.adapters.dispatch import _is_connection_transient

        if isinstance(exc, EmptyModelOutputError):
            empty_errors = [exc]
            for attempt in range(2, _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS + 1):
                log.warning(
                    "AgenticLoop: fail-fast empty model output (%s); "
                    "retrying the same adapter (attempt %d/%d)",
                    type(empty_errors[-1]).__name__,
                    attempt,
                    _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS,
                )
                if on_retry is not None:
                    await on_retry(
                        empty_errors[-1],
                        attempt,
                        _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS,
                    )
                await asyncio.sleep(_FAIL_FAST_RETRY_DELAY_S * (attempt - 1))
                try:
                    result = await invoke()
                except EmptyModelOutputError as retry_error:
                    empty_errors.append(retry_error)
                    if attempt == _FAIL_FAST_EMPTY_OUTPUT_MAX_ATTEMPTS:
                        retry_error.include_actionable_attempts(empty_errors[:-1])
                        raise
                    continue
                for empty_error in empty_errors:
                    empty_error.mark_recovered()
                return result
            raise AssertionError("bounded empty-output retry loop did not terminate") from exc
        if not _is_connection_transient(exc):
            raise
        log.warning(
            "AgenticLoop: fail-fast transport error (%s); retrying the same adapter once",
            type(exc).__name__,
        )
        if on_retry is not None:
            await on_retry(exc, 2, 2)
        await asyncio.sleep(_FAIL_FAST_RETRY_DELAY_S)
        return await invoke()


async def _prepare_request(
    loop: Any,
    system: str,
    messages: list[dict[str, Any]],
    *,
    round_idx: int,
    model: str | None,
    response_schema: dict[str, Any] | None,
    allow_tools: bool,
) -> tuple[AdapterCallRequest, Any, dict[str, Any], str, str, str, str]:
    """Freeze one request after policy middleware and bind its step."""
    effective_model = model or loop.model
    # Shared list — in-place pruning must persist into later rounds.
    await _context.check_context_overflow(loop, system, messages)
    step_snapshot = loop._open_step_snapshot(
        round_idx=round_idx,
        model=effective_model,
        allow_tools=allow_tools,
    )

    # WRAP_UP: force text-only when approaching limits
    wrap_up = False
    if loop.max_rounds > 0:
        remaining = loop.max_rounds - round_idx
        wrap_up = remaining <= loop.WRAP_UP_HEADROOM
    if not wrap_up and loop._time_budget_s > 0:
        import time as _time

        remaining_time = loop._time_budget_s - (_time.monotonic() - loop._loop_start_time)
        wrap_up = remaining_time <= loop._WRAP_UP_TIME_HEADROOM_S
    tool_choice: dict[str, str] = (
        {"type": "none"} if wrap_up or not allow_tools else {"type": "auto"}
    )

    # Adaptive compute — context-proportional caps; the only adaptive
    # case left is wrap-up (overthinking exits the loop instead).
    from core.config import settings as _settings
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    ctx_window = MODEL_CONTEXT_WINDOW.get(effective_model, 200_000)

    adaptive_max_tokens = loop.max_tokens
    adaptive_thinking = loop._thinking_budget
    adaptive_effort = loop._effort
    if wrap_up:
        # wrap-up: minimal budget (0.5% of window, floor 4096)
        adaptive_max_tokens = max(4096, min(loop.max_tokens, ctx_window // 200))
        adaptive_thinking = 0
        adaptive_effort = "low"

    # config-driven temperature (1.0 default)
    loop_temperature = _settings.temperature_agent_loop

    # build the adapter-neutral request, then translate back to
    # AgenticResponse so the rest of the loop is unchanged
    from core.llm.adapters.translation import (
        build_adapter_request,
    )

    session_allowed_tools = (
        frozenset(loop._allowed_tool_names) if loop._allowed_tool_names is not None else None
    )

    request_tools: list[dict[str, Any]] | BoundToolPlan
    if not allow_tools:
        request_tools = []
    elif step_snapshot.bound_tool_plan is not None:
        request_tools = step_snapshot.bound_tool_plan
    else:
        request_tools = loop._tools
    raw_denied_tools: Any = getattr(loop.executor, "_denied_tools", frozenset())
    executor_denied_tools = (
        frozenset(raw_denied_tools) if isinstance(raw_denied_tools, Set) else frozenset()
    )
    raw_executable_tools: Any = ()
    if allow_tools:
        if step_snapshot.bound_tool_plan is not None:
            raw_executable_tools = getattr(
                loop.executor,
                "_bound_allowed_tools",
                (),
            )
        else:
            raw_executable_tools = getattr(loop.executor, "_handlers", ())
    executor_executable_tools = (
        frozenset(raw_executable_tools)
        if isinstance(raw_executable_tools, (Mapping, Set))
        else frozenset()
    )
    req = build_adapter_request(
        model=effective_model,
        system=system,
        messages=messages,
        tools=request_tools,
        transient_tools=(
            list(loop._transient_tools)
            if allow_tools and step_snapshot.bound_tool_plan is not None
            else None
        ),
        transient_deferred_tool_names=(
            loop._transient_deferred_tool_names
            if allow_tools and step_snapshot.bound_tool_plan is not None
            else ()
        ),
        tool_choice=tool_choice,
        max_tokens=adaptive_max_tokens,
        temperature=loop_temperature,
        thinking_budget=adaptive_thinking,
        effort=adaptive_effort,
        allowed_tool_names=session_allowed_tools,
        denied_tool_names=executor_denied_tools,
        executable_tool_names=executor_executable_tools,
        response_schema=(response_schema if response_schema is not None else loop._response_schema),
    )
    import uuid as _uuid

    llm_call_id = f"llm-{step_snapshot.step_id}-{_uuid.uuid4().hex[:8]}"
    correlation = {
        "session_id": step_snapshot.correlation.session_id,
        "turn_id": step_snapshot.correlation.turn_id,
        "step_id": step_snapshot.step_id,
        "session_generation": step_snapshot.correlation.session_generation,
        "verify_attempt": step_snapshot.correlation.verify_attempt,
        "llm_call_id": llm_call_id,
        "llm_attempt_id": "",
    }
    bound_request = req
    original_adapter = loop._new_adapter
    llm_request = await loop._middleware_registry.llm_request(
        LlmCallRequest(
            adapter=original_adapter,
            request=req,
            correlation=correlation,
        )
    )
    if step_snapshot.bound_tool_plan is not None and llm_request.adapter is not original_adapter:
        raise ValueError("LLM middleware cannot change a bound request adapter")
    call_adapter = llm_request.adapter
    req = llm_request.request
    if step_snapshot.bound_tool_plan is not None:
        _validate_bound_request_rewrite(bound_request, req)
    if session_allowed_tools is not None and step_snapshot.bound_tool_plan is None:
        effective_allowed = session_allowed_tools
        if req.allowed_tool_names is not None:
            effective_allowed &= req.allowed_tool_names
        req = replace(
            req,
            allowed_tool_names=effective_allowed,
            tools=tuple(tool for tool in req.tools if tool.name in effective_allowed),
            deferred_tool_names=tuple(
                name for name in req.deferred_tool_names if name in effective_allowed
            ),
        )
    elif session_allowed_tools is not None and (
        req.allowed_tool_names != session_allowed_tools
        or any(tool.name not in session_allowed_tools for tool in req.tools)
    ):
        raise ValueError("bound tool request escaped its pre-filtered allowlist")
    effective_model = req.model
    adapter_name = getattr(call_adapter, "name", "<unknown>")
    effective_provider = getattr(call_adapter, "provider", loop._provider)
    effective_source = getattr(call_adapter, "source", loop._source)
    step_snapshot = replace(
        step_snapshot,
        model=effective_model,
        provider=str(effective_provider),
        source=str(effective_source),
        adapter_name=str(adapter_name),
    )
    loop._current_step_snapshot = step_snapshot
    loop._tool_processor.bind_step(step_snapshot)
    return (
        req,
        call_adapter,
        correlation,
        effective_model,
        llm_call_id,
        str(effective_provider),
        str(adapter_name),
    )


async def call_llm(
    loop: Any,
    system: str,
    messages: list[dict[str, Any]],
    *,
    round_idx: int = 0,
    model: str | None = None,
    response_schema: dict[str, Any] | None = None,
    allow_tools: bool = True,
) -> AgenticResponse | None:
    """Multi-provider LLM call via :class:`LLMAdapter` (P1 Gateway pattern).

    Delegates to ``loop._new_adapter.acomplete()`` (provider-specific
    conversion, retry, failover). Returns a normalized
    ``AgenticResponse`` or None on failure. Raises ``UserCancelledError``
    on Ctrl+C (caught by ``arun()``). Optional ``model`` overrides the
    request model for one call without mutating ``loop.model``. Optional
    ``response_schema`` overrides the loop-level schema for this call only.
    ``allow_tools=False`` keeps auxiliary planner / judge calls on their
    structured text contract instead of inheriting the action tool surface.

    The context-overflow check mutates the shared messages list in place,
    so it must run before the adapter request is assembled.
    """
    (
        req,
        call_adapter,
        correlation,
        effective_model,
        llm_call_id,
        effective_provider,
        adapter_name,
    ) = await _prepare_request(
        loop,
        system,
        messages,
        round_idx=round_idx,
        model=model,
        response_schema=response_schema,
        allow_tools=allow_tools,
    )
    llm_attempt_number = 0

    async def _complete_attempt(adapter: Any, request: Any) -> Any:
        nonlocal llm_attempt_number
        llm_attempt_number += 1
        attempt_correlation = {
            **correlation,
            "llm_attempt_id": f"{llm_call_id}:attempt-{llm_attempt_number}",
        }
        current = LlmCallRequest(
            adapter=adapter,
            request=request,
            correlation=attempt_correlation,
        )

        async def terminal(effective: LlmCallRequest) -> Any:
            import time as _llm_call_time

            from core.hooks.dispatch import fire_hook_async

            started_at = _llm_call_time.monotonic()
            active_adapter = effective.adapter
            active_request = effective.request
            active_name = getattr(active_adapter, "name", "<unknown>")
            active_provider = getattr(active_adapter, "provider", effective_provider)
            await fire_hook_async(
                loop._hooks,
                HookEvent.LLM_CALL_STARTED,
                {
                    **attempt_correlation,
                    "model": active_request.model,
                    "provider": active_provider,
                    "adapter": active_name,
                },
            )
            try:
                attempt_result = await active_adapter.acomplete(active_request)
            except BaseException as exc:
                await fire_hook_async(
                    loop._hooks,
                    HookEvent.LLM_CALL_ENDED,
                    {
                        **attempt_correlation,
                        "model": active_request.model,
                        "provider": active_provider,
                        "adapter": active_name,
                        "latency_ms": (_llm_call_time.monotonic() - started_at) * 1_000,
                        "error": str(exc) or type(exc).__name__,
                    },
                )
                raise

            usage = getattr(attempt_result, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            cached_input_tokens = int(getattr(usage, "cached_input_tokens", 0) or 0)
            reasoning_tokens = int(getattr(usage, "reasoning_tokens", 0) or 0)
            cache_write_tokens = int(getattr(usage, "cache_write_tokens", 0) or 0)
            try:
                from core.llm.token_tracker import calculate_cost

                cost_usd = float(
                    calculate_cost(
                        active_request.model,
                        input_tokens,
                        output_tokens,
                        cache_creation_tokens=cache_write_tokens,
                        cache_read_tokens=cached_input_tokens,
                    )
                )
            except Exception:
                log.warning(
                    "calculate_cost failed for model=%s — recording cost_usd=0.0 "
                    "(cost limiter will under-count this call)",
                    active_request.model,
                    exc_info=True,
                )
                cost_usd = 0.0
            await fire_hook_async(
                loop._hooks,
                HookEvent.LLM_CALL_ENDED,
                {
                    **attempt_correlation,
                    "model": active_request.model,
                    "provider": active_provider,
                    "adapter": active_name,
                    "latency_ms": (_llm_call_time.monotonic() - started_at) * 1_000,
                    "error": None,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cached_input_tokens": cached_input_tokens,
                        "reasoning_tokens": reasoning_tokens,
                        "cache_write_tokens": cache_write_tokens,
                    },
                    "cost_usd": cost_usd,
                },
            )
            return attempt_result

        return await loop._middleware_registry.llm_execution(current, terminal)

    async def _on_fail_fast_pre_execution_retry(
        exc: Exception,
        attempt: int,
        max_attempts: int,
    ) -> None:
        loop._pre_execution_retry_errors.append(type(exc).__name__)
        if loop._hooks:
            try:
                await loop._hooks.trigger_async(
                    HookEvent.LLM_CALL_RETRIED,
                    {
                        **correlation,
                        "llm_attempt_id": f"{llm_call_id}:attempt-{attempt}",
                        "model": effective_model,
                        "provider": effective_provider,
                        "adapter": adapter_name,
                        "error_type": type(exc).__name__,
                        "delay_s": _FAIL_FAST_RETRY_DELAY_S,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
            except Exception:
                log.debug("LLM_CALL_RETRIED hook trigger failed", exc_info=True)

    try:
        result = await _acomplete_with_fail_fast_pre_execution_retry(
            call_adapter,
            req,
            on_retry=_on_fail_fast_pre_execution_retry,
            complete=_complete_attempt,
        )
    except Exception as exc:
        error_detail = str(exc) or type(exc).__name__
        loop._last_llm_error = error_detail
        log.warning(
            "AgenticLoop: adapter.acomplete failed (adapter=%s): %s",
            adapter_name,
            error_detail,
        )
        if _fail_fast_adapter_errors_enabled():
            raise
        response = None
    else:
        response = agentic_response_from_adapter_result(result)

    if response is None:
        adapter_err = getattr(call_adapter, "_last_error", None)
        if adapter_err:
            loop._last_llm_error = str(adapter_err)
        elif not loop._last_llm_error:
            loop._last_llm_error = f"All {loop._provider} models exhausted"

    # surface reasoning summaries to AgenticUI per finished item
    if response is not None and not loop._quiet:
        summaries = getattr(response, "reasoning_summaries", None) or []
        for summary in summaries:
            if not summary:
                continue
            from core.ui.agentic_ui import emit_reasoning_summary

            emit_reasoning_summary(loop._provider, loop.model, summary)

    return response


__all__ = [
    "_acomplete_with_fail_fast_pre_execution_retry",
    "call_llm",
]
