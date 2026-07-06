"""Translation between :class:`LLMAdapter` and AgenticLoop's call surface.

Used by :meth:`core.agent.loop.agent_loop.AgenticLoop._call_llm`: the loop
builds an :class:`AdapterCallRequest`, calls :meth:`LLMAdapter.acomplete`,
and feeds the result back through :func:`agentic_response_from_adapter_result`
so the downstream tool-use / cost / observability pipeline keeps the same
data shape.

PR-MAINPATH-67 (2026-05-24) — extracted from the deleted ``_legacy_bridge``
module after the legacy ``AgenticLLMPort.agentic_call`` fallback branch
was removed; this is now the sole call-site for both helpers.
"""

from __future__ import annotations

import json
import logging
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

log = logging.getLogger(__name__)


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
    resume_session_id: str = "",
    response_schema: dict[str, Any] | None = None,
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
        # A2 (v0.99.44) — Codex reasoning items are attached to the SPECIFIC
        # assistant turn that emitted them so the adapter can replay each
        # blob at the correct ordinal position when rebuilding the
        # next-turn ``input`` array. Flattening into a single
        # provider_options tuple would lose the per-turn association the
        # legacy ``inject_reasoning_replay`` walker depends on (Codex MCP
        # A2 BLOCKER 3).
        reasoning_items: tuple[dict[str, Any], ...] = ()
        output_items: tuple[dict[str, Any], ...] = ()
        phase: str = ""
        if role == "assistant":
            raw = m.get("codex_reasoning_items")
            if isinstance(raw, list):
                reasoning_items = tuple(item for item in raw if isinstance(item, dict))
            raw_output = m.get("codex_output_items")
            if isinstance(raw_output, list):
                output_items = tuple(item for item in raw_output if isinstance(item, dict))
            # PR-CODEX-MULTITURN-PHASE-PRESERVE (Sprint H follow-up,
            # 2026-05-26) — forward the per-message phase attribution
            # the AgenticLoop persisted from a prior Codex response so
            # multi-turn replay carries the
            # ``Literal["commentary", "final_answer"]`` semantic to the
            # next ``EasyInputMessageParam.phase``.
            phase_raw = m.get("phase")
            if isinstance(phase_raw, str):
                phase = phase_raw
        adapter_messages.append(
            Message(
                role=role,
                content=content,
                tool_use_id=tool_use_id,
                codex_reasoning_items=reasoning_items,
                codex_output_items=output_items,
                phase=phase,
            )
        )
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
        resume_session_id=resume_session_id,
        response_schema=response_schema,
    )


def agentic_response_from_adapter_result(result: AdapterCallResult) -> AgenticResponse:
    """Translate :class:`AdapterCallResult` → :class:`AgenticResponse`.

    :meth:`LLMAdapter.acomplete` returns a flat ``(text, usage, stop_reason,
    tool_uses, raw_response)`` envelope; :class:`AgenticResponse` is a list
    of typed content blocks plus normalised usage. We rebuild the content
    list — text block first (when non-empty), then one
    :class:`ToolUseBlock` per tool_use entry — so ``ToolCallProcessor`` and
    the rest of the loop see the canonical shape.
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
    # A2 (v0.99.44) — Codex encrypted reasoning replay + reasoning summaries
    # forwarded. AgenticLoop's next-turn input builder reads
    # ``codex_reasoning_items`` and prepends them so gpt-5.x ``store=False``
    # multi-turn doesn't lose chain of thought. ``reasoning_summaries`` feeds
    # the live "thinking..." UI surface (``emit_reasoning_summary``).
    codex_reasoning_items = (
        [dict(item) for item in result.reasoning_items] if result.reasoning_items else None
    )
    reasoning_summaries = list(result.reasoning_summaries) if result.reasoning_summaries else None
    codex_output_items = (
        [dict(item) for item in result.codex_output_items] if result.codex_output_items else None
    )
    return AgenticResponse(
        content=blocks,
        stop_reason=_translate_stop_reason(result.stop_reason, bool(result.tool_uses)),
        usage=usage,
        codex_reasoning_items=codex_reasoning_items,
        codex_output_items=codex_output_items,
        reasoning_summaries=reasoning_summaries,
        assistant_phase=result.assistant_phase,
    )


def _translate_stop_reason(stop: str, has_tool_uses: bool) -> str:
    """Map provider-flavoured stop reasons → AgenticLoop's two-value enum.

    :attr:`AgenticResponse.stop_reason` is one of ``"tool_use"`` /
    ``"end_turn"``. **Content is the source of truth** —
    ``has_tool_uses`` decides single-handedly, the provider string is
    only consulted to log adapter extraction bugs.

    PR-CODEX-STOP-REASON-TOOL-USE (2026-05-28) original case — the Codex
    backend at ``chatgpt.com/backend-api/codex`` returns
    ``status="completed"`` for EVERY successful response, regardless of
    whether the model emitted ``function_call`` items. Without the
    content-first gate the agent loop terminates the turn (treating the
    response as ``"end_turn"``), appends the assistant message with
    ``tool_use`` blocks BUT skips tool execution, and the next turn's
    input carries a ``function_call`` with no matching
    ``function_call_output`` — the Codex backend rejects with ``"No
    tool output found for function call call_XXXX"`` 400.

    Frontier-pattern alignment (2026-05-28 audit of paperclip
    ``codex-local/src/ui/parse-stdout.ts:194`` + hermes
    ``agent/codex_responses_adapter.py:1034``): both derive the terminal
    flag from the actual presence of tool/function-call items in the
    response payload. We mirror that invariant — provider string never
    wins on its own.

    The mirror-case anti-pattern (provider says ``"tool_use"`` / ``"tool_calls"``
    but ``tool_uses`` is empty) typically means the adapter failed to
    populate ``AdapterCallResult.tool_uses``. We log a WARN with the
    incoming string and terminate the turn — preventing an agent-loop
    spin that has no tool to execute, and surfacing the underlying
    extraction bug for the next maintainer.
    """
    if has_tool_uses:
        return "tool_use"
    if stop in ("tool_use", "tool_calls"):
        log.warning(
            "translate_stop_reason: provider sent stop_reason=%r but "
            "AdapterCallResult.tool_uses is empty — treating as 'end_turn'. "
            "Likely cause: the adapter that produced this result did not "
            "extract tool_use blocks from the response. Frontier pattern: "
            "tool extraction must populate tool_uses before this bridge runs.",
            stop,
        )
    return "end_turn"


__all__ = [
    "agentic_response_from_adapter_result",
    "build_adapter_request",
]
