"""``call_llm_with_tools`` — tool-use loop with provider-aware routing."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from core.hooks.system import HookEvent
from core.llm.provider_dispatch import (
    _cross_provider_dispatch,
    _get_provider_client,
)
from core.llm.providers.anthropic import get_anthropic_client
from core.llm.providers.anthropic import (
    retry_with_backoff as _retry_with_backoff,
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


def call_llm_with_tools(
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
    """LLM call with tool-use loop and provider-aware routing.

    Supports cross-provider fallback when enabled.
    """
    from core.config import settings

    target_model = model or settings.model
    provider = _route_provider(target_model)

    def _dispatch(p: str, m: str) -> ToolUseResult:
        _fire_hook(
            HookEvent.LLM_CALL_STARTED,
            {"model": m, "provider": p, "function": "call_llm_with_tools"},
        )
        t0_tools = time.monotonic()

        try:
            if p != "anthropic":
                from core.llm.providers.openai import OpenAIAdapter

                adapter = OpenAIAdapter(default_model=m)
                if p == "glm":
                    from core.llm.providers import openai as _openai_provider

                    orig_get = _openai_provider._get_openai_client

                    def _glm_client_override() -> Any:
                        return _get_provider_client("glm")

                    _openai_provider._get_openai_client = _glm_client_override
                    try:
                        oai_result: ToolUseResult = adapter.generate_with_tools(
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
                        _openai_provider._get_openai_client = orig_get
                    tools_result = oai_result
                else:
                    oai_result2: ToolUseResult = adapter.generate_with_tools(
                        system,
                        user,
                        tools=tools,
                        tool_executor=tool_executor,
                        model=m,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        max_tool_rounds=max_tool_rounds,
                    )
                    tools_result = oai_result2
            else:
                client = get_anthropic_client()
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

                    def _do_call(
                        *,
                        model: str,
                        _tc: dict[str, str] | None = tool_choice,
                    ) -> Any:
                        return client.messages.create(  # type: ignore[call-overload]
                            model=model,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            system=system_cached,
                            messages=messages,
                            tools=tools_for_api,
                            tool_choice=_tc,
                        )

                    response = _retry_with_backoff(_do_call, model=m)

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
                            tool_output: dict[str, Any] = tool_executor(tool_name, **tool_input)
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
                    "function": "call_llm_with_tools",
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
                "function": "call_llm_with_tools",
                "latency_ms": elapsed_ms_total,
                "error": None,
            },
        )
        return tools_result

    return _cross_provider_dispatch(provider, target_model, _dispatch, "call_llm_with_tools")


__all__ = ["call_llm_with_tools", "get_anthropic_client"]
