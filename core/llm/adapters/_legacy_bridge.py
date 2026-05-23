"""Translation between the new :class:`LLMAdapter` Protocol and the legacy
``AgenticResponse`` shape consumed by :class:`AgenticLoop`.

Used by ``AgenticLoop._call_llm`` when an explicit ``source`` is set: the loop
builds an :class:`AdapterCallRequest`, calls ``adapter.acomplete``, and feeds
the result back through :func:`agentic_response_from_adapter_result` so the
downstream tool-use / cost / observability pipeline keeps the same data
shape.

This bridge is intentionally minimal — it does NOT replicate the full
``AgenticLLMPort.agentic_call`` (retry, failover, streaming) surface. Those
behaviours stay in the legacy adapter for callers that don't set ``source``.
The new path is an opt-in alternative; once every in-tree caller has migrated
(v1.0.0), the bridge + legacy path are removed together.
"""

from __future__ import annotations

import json
from typing import Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    ToolSpec,
)
from core.llm.agentic_response import (
    AgenticResponse,
    ResponseUsage,
    TextBlock,
    ToolUseBlock,
)


def build_adapter_request(
    *,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: dict[str, str] | str,
    max_tokens: int,
    temperature: float,
    thinking_budget: int,
    effort: str,
) -> AdapterCallRequest:
    """Translate AgenticLoop's call-site args → :class:`AdapterCallRequest`.

    ``messages`` arrive in Anthropic shape (``[{"role": ..., "content": ...}, ...]``).
    We map ``role="tool"`` entries (added during multi-turn tool-use) into the
    adapter-neutral :class:`Message(tool_use_id=...)` form; adapter
    implementations re-encode for their provider.

    ``tools`` arrive in Anthropic shape (``[{"name": ..., "description": ...,
    "input_schema": ...}]``) and translate directly to :class:`ToolSpec`.
    """
    adapter_messages: list[Message] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        tool_use_id = m.get("tool_use_id")
        adapter_messages.append(Message(role=role, content=content, tool_use_id=tool_use_id))
    adapter_tools: list[ToolSpec] = [
        ToolSpec(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("input_schema", {}),
        )
        for t in tools
    ]
    return AdapterCallRequest(
        model=model,
        messages=adapter_messages,
        system_prompt=system,
        tools=adapter_tools,
        tool_choice=tool_choice,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_budget=thinking_budget,
        effort=effort,
    )


def agentic_response_from_adapter_result(result: AdapterCallResult) -> AgenticResponse:
    """Translate :class:`AdapterCallResult` → legacy :class:`AgenticResponse`.

    The new adapter call returns a flat ``(text, usage, stop_reason,
    tool_uses, raw_response)`` envelope; the legacy ``AgenticResponse`` is a
    list of typed content blocks plus normalised usage. We rebuild the
    content list — text block first (when non-empty), then one
    :class:`ToolUseBlock` per tool_use entry — so ``ToolCallProcessor`` and
    the rest of the loop see the same shape they did under the legacy
    adapter.
    """
    blocks: list[TextBlock | ToolUseBlock] = []
    if result.text:
        blocks.append(TextBlock(type="text", text=result.text))
    for tu in result.tool_uses:
        input_field = tu.get("input", {})
        if isinstance(input_field, str):
            # Adapters that surface ``arguments`` as a JSON string (OpenAI)
            # — parse to dict so the executor's signature stays uniform.
            try:
                input_field = json.loads(input_field) if input_field else {}
            except json.JSONDecodeError:
                input_field = {"_raw": input_field}
        blocks.append(
            ToolUseBlock(
                id=str(tu.get("id", "")),
                type="tool_use",
                name=str(tu.get("name", "")),
                input=input_field if isinstance(input_field, dict) else {},
            )
        )
    usage = ResponseUsage(
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cached_input_tokens,
    )
    return AgenticResponse(
        content=blocks,
        stop_reason=_translate_stop_reason(result.stop_reason),
        usage=usage,
    )


def _translate_stop_reason(stop: str) -> str:
    """Map provider-flavoured stop reasons → AgenticLoop's two-value enum.

    Legacy ``AgenticResponse.stop_reason`` is one of ``"tool_use"`` /
    ``"end_turn"``. Provider strings map as follows:

    - Anthropic ``"tool_use"`` → ``"tool_use"``
    - OpenAI ``"tool_calls"`` → ``"tool_use"``
    - Codex ``"completed"`` / Anthropic ``"end_turn"`` / OpenAI ``"stop"`` /
      anything else → ``"end_turn"``
    """
    if stop in ("tool_use", "tool_calls"):
        return "tool_use"
    return "end_turn"


__all__ = [
    "agentic_response_from_adapter_result",
    "build_adapter_request",
]
