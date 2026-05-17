"""Async tool-use loop with provider-aware routing."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from typing import Any, cast

from core.hooks.system import HookEvent
from core.llm.providers.anthropic import get_async_anthropic_client
from core.llm.providers.anthropic import (
    retry_with_backoff_async as _retry_with_backoff_async,
)
from core.llm.providers.anthropic import (
    system_with_cache as _system_with_cache,
)
from core.llm.router._hooks import _fire_hook
from core.llm.router._usage import _record_response_usage
from core.llm.router.models import ToolCallRecord, ToolUseResult
from core.llm.token_tracker import LLMUsage

from ._route import _route_provider

log = logging.getLogger(__name__)


async def _run_tool_executor_async(
    tool_executor: Callable[..., Any],
    tool_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Run sync or async tool executors without blocking the event loop."""
    if inspect.iscoroutinefunction(tool_executor):
        raw = await tool_executor(tool_name, **tool_input)
    else:
        raw = await asyncio.to_thread(tool_executor, tool_name, **tool_input)

    if inspect.isawaitable(raw):
        raw = await raw
    return raw if isinstance(raw, dict) else {"result": raw}


async def call_llm_with_tools_async(
    system: str,
    user: str,
    *,
    tools: list[dict[str, Any]],
    tool_executor: Any,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    max_tool_rounds: int = 5,
) -> ToolUseResult:
    """Async LLM call with tool-use loop and provider-aware routing."""
    from core.config import settings

    target_model = model or settings.model
    provider = _route_provider(target_model)

    async def _dispatch(p: str, m: str) -> ToolUseResult:
        _fire_hook(
            HookEvent.LLM_CALL_STARTED,
            {"model": m, "provider": p, "function": "call_llm_with_tools_async"},
        )
        t0_tools = time.monotonic()

        try:
            if p != "anthropic":
                from core.llm.providers.openai import OpenAIAdapter

                adapter = OpenAIAdapter(default_model=m)
                if p == "glm":
                    from core.llm.providers import openai as _openai_provider
                    from core.llm.providers.glm import _get_async_glm_client

                    orig_get = _openai_provider._get_async_openai_client

                    def _glm_client_override() -> Any:
                        return _get_async_glm_client()

                    _openai_provider._get_async_openai_client = _glm_client_override
                    try:
                        tools_result = await adapter.agenerate_with_tools(
                            system,
                            user,
                            tools=tools,
                            tool_executor=tool_executor,
                            model=m,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            max_tool_rounds=max_tool_rounds,
                        )
                    finally:
                        _openai_provider._get_async_openai_client = orig_get
                else:
                    tools_result = await adapter.agenerate_with_tools(
                        system,
                        user,
                        tools=tools,
                        tool_executor=tool_executor,
                        model=m,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        max_tool_rounds=max_tool_rounds,
                    )
            else:
                client = get_async_anthropic_client()
                system_cached = _system_with_cache(system)

                all_tool_calls: list[ToolCallRecord] = []
                all_usage: list[LLMUsage] = []
                messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

                cached_tools: list[dict[str, Any]] = []
                for i, tool in enumerate(tools):
                    tool_copy = dict(tool)
                    if i == len(tools) - 1:
                        tool_copy["cache_control"] = {"type": "ephemeral"}
                    cached_tools.append(tool_copy)
                tools_for_api = cached_tools

                for round_idx in range(max_tool_rounds):
                    is_last_round = round_idx == max_tool_rounds - 1
                    tool_choice: dict[str, str] | None = (
                        {"type": "none"} if is_last_round else {"type": "auto"}
                    )

                    async def _do_call(
                        *,
                        model: str,
                        _tc: dict[str, str] | None = tool_choice,
                    ) -> Any:
                        response = client.messages.create(  # type: ignore[call-overload]
                            model=model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            system=system_cached,
                            messages=messages,
                            tools=tools_for_api,
                            tool_choice=_tc,
                        )
                        if inspect.isawaitable(response):
                            return await response
                        return response

                    response = await _retry_with_backoff_async(_do_call, model=m)

                    usage = _record_response_usage(response, m, label="tools")
                    if usage is not None:
                        all_usage.append(usage)

                    if response.stop_reason != "tool_use":
                        text = ""
                        for block in response.content:
                            if hasattr(block, "text"):
                                text += block.text
                        tools_result = ToolUseResult(
                            text=text,
                            tool_calls=all_tool_calls,
                            usage=all_usage,
                            rounds=round_idx + 1,
                        )
                        break

                    assistant_content = response.content
                    tool_result_blocks: list[dict[str, Any]] = []

                    for block in assistant_content:
                        if block.type != "tool_use":
                            continue
                        tool_name = block.name
                        tool_input = block.input
                        t0_tool = time.time()
                        try:
                            tool_output = await _run_tool_executor_async(
                                tool_executor, tool_name, tool_input
                            )
                        except Exception as exc:
                            log.warning("Tool '%s' execution failed: %s", tool_name, exc)
                            from core.auth.scrub import scrub_credentials

                            tool_output = {"error": scrub_credentials(str(exc))}
                        elapsed_ms_tool = (time.time() - t0_tool) * 1000

                        all_tool_calls.append(
                            ToolCallRecord(
                                tool_name=tool_name,
                                tool_input=tool_input,
                                tool_result=tool_output,
                                duration_ms=elapsed_ms_tool,
                            )
                        )
                        tool_result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_output),
                            }
                        )

                    messages.append({"role": "assistant", "content": assistant_content})
                    messages.append({"role": "user", "content": tool_result_blocks})
                else:
                    tools_result = ToolUseResult(
                        text="",
                        tool_calls=all_tool_calls,
                        usage=all_usage,
                        rounds=max_tool_rounds,
                    )
        except Exception as exc:
            elapsed_ms_total = (time.monotonic() - t0_tools) * 1000
            _fire_hook(
                HookEvent.LLM_CALL_ENDED,
                {
                    "model": m,
                    "provider": p,
                    "function": "call_llm_with_tools_async",
                    "latency_ms": elapsed_ms_total,
                    "error": str(exc),
                },
            )
            raise

        elapsed_ms_total = (time.monotonic() - t0_tools) * 1000
        _fire_hook(
            HookEvent.LLM_CALL_ENDED,
            {
                "model": m,
                "provider": p,
                "function": "call_llm_with_tools_async",
                "latency_ms": elapsed_ms_total,
                "error": None,
            },
        )
        return cast(ToolUseResult, tools_result)

    providers: list[tuple[str, str]] = [(provider, target_model)]
    if settings.llm_cross_provider_failover:
        from core.llm.provider_dispatch import _get_fallback_chain

        for p in settings.llm_cross_provider_order:
            if p != provider:
                chain = _get_fallback_chain(p)
                if chain:
                    providers.append((p, chain[0]))

    last_exc: Exception | None = None
    t0 = time.perf_counter()
    for idx, (provider_name, provider_model) in enumerate(providers):
        try:
            return await _dispatch(provider_name, provider_model)
        except Exception as exc:
            last_exc = exc
            if idx < len(providers) - 1:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                next_provider, next_model = providers[idx + 1]
                log.warning(
                    "Cross-provider fallback: %s(%s) -> %s(%s) [%s] after %.0fms",
                    provider_name,
                    provider_model,
                    next_provider,
                    next_model,
                    "call_llm_with_tools_async",
                    elapsed_ms,
                )
                _fire_hook(
                    HookEvent.FALLBACK_CROSS_PROVIDER,
                    {
                        "from_provider": provider_name,
                        "to_provider": next_provider,
                        "from_model": provider_model,
                        "to_model": next_model,
                        "function": "call_llm_with_tools_async",
                        "error": str(exc),
                        "elapsed_ms": round(elapsed_ms, 1),
                        "attempt": idx,
                    },
                )
                continue
            raise

    assert last_exc is not None
    raise last_exc


__all__ = ["call_llm_with_tools_async"]
