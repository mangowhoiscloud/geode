"""Provider-agnostic agentic response normalization.

Normalizes LLM provider responses (Anthropic, OpenAI Chat Completions,
OpenAI Responses API) into a common format that AgenticLoop can process
without provider-specific code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolUseBlock:
    """A single tool-use request from the LLM."""

    id: str
    type: str = "tool_use"
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TextBlock:
    """A text content block from the LLM."""

    type: str = "text"
    text: str = ""


@dataclass(slots=True)
class ResponseUsage:
    """Token usage from an LLM response."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0


@dataclass
class AgenticResponse:
    """Provider-agnostic LLM response for the agentic loop.

    Normalizes Anthropic and OpenAI responses into a common format.
    The content list contains TextBlock and ToolUseBlock objects
    with the same attribute names (.type, .text, .name, .input, .id).

    ``codex_reasoning_items`` (v0.55.0): sidecar list of opaque
    Reasoning items extracted from a Codex Plus stream. Each entry is
    a dict with ``{type:"reasoning", encrypted_content, summary?, id?}``
    fit for re-injection into the next-turn ``input`` array. Present
    only on responses from ``CodexAgenticAdapter``; ``None`` for every
    other provider. Mirrors the Hermes Agent pattern at
    ``agent/codex_responses_adapter.py:228-246, 720-738`` — required
    for multi-turn reasoning continuity on gpt-5.x because
    ``store=False`` makes the server unable to resolve items by ID.
    """

    content: list[TextBlock | ToolUseBlock] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" or "tool_use"
    usage: ResponseUsage = field(default_factory=ResponseUsage)
    codex_reasoning_items: list[dict[str, Any]] | None = None
    # v0.57.0 R6 — reasoning summaries for the "live thinking..." UI
    # surface. Per-item granularity to avoid thread-local IPC writer
    # complexity (the streaming loop runs in ``asyncio.to_thread``).
    # Codex populates from ``reasoning.summary[].text``; Anthropic from
    # ``thinking`` content blocks. ``None`` when the call produced no
    # reasoning summary; never set by GLM/OpenAI Chat Completions.
    reasoning_summaries: list[str] | None = None


def inject_reasoning_replay(
    oai_messages: list[dict[str, Any]],
    anthropic_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject prior-turn ``codex_reasoning_items`` back into a Responses
    API ``input`` array.

    For every assistant entry in ``oai_messages``, look up the matching
    original Anthropic-format message and prepend any captured
    ``encrypted_content`` reasoning items immediately before the
    assistant entry. Strips ``id`` so the server can't 404 on item
    lookup — mirrors Hermes ``codex_responses_adapter.py:228-246``.

    Both lists must preserve order (one Anthropic message → ≥1 entries
    in oai_messages). Used by Codex Plus and PAYG OpenAI Responses
    adapters; without this, gpt-5.x loses reasoning state every turn
    when ``store=False`` (no server-side item resolution).
    """
    resp_input: list[dict[str, Any]] = []
    msg_iter = iter(anthropic_messages)
    current_msg: dict[str, Any] | None = next(msg_iter, None)
    for entry in oai_messages:
        if entry.get("role") == "system":
            # Adapter passes system via ``instructions`` kwarg, not input.
            continue
        entry_role = (
            entry.get("role")
            or ("assistant" if entry.get("type") in ("function_call",) else None)
            or ("user" if entry.get("type") == "function_call_output" else None)
        )
        while current_msg is not None and current_msg.get("role") != entry_role:
            current_msg = next(msg_iter, None)
        if (
            current_msg is not None
            and current_msg.get("role") == "assistant"
            and entry_role == "assistant"
        ):
            reasoning = current_msg.get("codex_reasoning_items")
            if isinstance(reasoning, list):
                for ri in reasoning:
                    if isinstance(ri, dict) and ri.get("encrypted_content"):
                        resp_input.append({k: v for k, v in ri.items() if k != "id"})
        resp_input.append(entry)
    return resp_input


def normalize_anthropic(response: Any) -> AgenticResponse:
    """Normalize an Anthropic SDK response to AgenticResponse."""
    blocks: list[TextBlock | ToolUseBlock] = []
    # v0.57.0 R6 — capture ``thinking`` block text into the reasoning
    # summary sidecar so the AgenticUI can render the "live thinking..."
    # surface. Mirrors the Codex normaliser pattern. Anthropic's
    # adaptive thinking with ``display:"summarized"`` (set in the
    # adapter since v0.56.0) produces visible summary text here.
    reasoning_summaries: list[str] = []
    for block in response.content:
        if block.type == "text":
            blocks.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                )
            )
        elif block.type == "thinking":
            _thinking_text = getattr(block, "thinking", "") or ""
            if _thinking_text:
                reasoning_summaries.append(_thinking_text)

    usage = ResponseUsage()
    if response.usage:
        # Anthropic Extended Thinking: thinking tokens tracked separately
        thinking_tok = 0
        if hasattr(response.usage, "thinking_tokens"):
            thinking_tok = response.usage.thinking_tokens or 0
        usage = ResponseUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=thinking_tok,
        )

    return AgenticResponse(
        content=blocks,
        stop_reason=response.stop_reason,
        usage=usage,
        reasoning_summaries=reasoning_summaries or None,
    )


def normalize_openai(response: Any) -> AgenticResponse:
    """Normalize an OpenAI SDK response to AgenticResponse."""
    choice = response.choices[0] if response.choices else None
    if choice is None:
        return AgenticResponse()

    blocks: list[TextBlock | ToolUseBlock] = []
    # v0.58.0 R2 — capture GLM ``message.reasoning_content`` (separate
    # from ``message.content``) into the R6 sidecar so the AgenticUI
    # surfaces it like Anthropic ``thinking`` blocks. GLM-4.5+ returns
    # this field when ``thinking={"type":"enabled"}`` is sent (see
    # ``core/llm/providers/glm.py``). Other Chat-Completions providers
    # (OpenAI legacy, etc.) leave it absent → sidecar stays None.
    reasoning_summaries: list[str] = []
    _glm_reasoning = getattr(choice.message, "reasoning_content", None)
    if isinstance(_glm_reasoning, str) and _glm_reasoning.strip():
        reasoning_summaries.append(_glm_reasoning)

    # Text content
    if choice.message.content:
        blocks.append(TextBlock(text=choice.message.content))

    # Tool calls
    has_tools = False
    if choice.message.tool_calls:
        has_tools = True
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append(
                ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                )
            )

    # Map finish_reason to Anthropic-style stop_reason
    stop_reason = "end_turn"
    if has_tools and choice.finish_reason == "tool_calls":
        stop_reason = "tool_use"

    usage = ResponseUsage()
    if response.usage:
        # OpenAI reasoning models: reasoning_tokens in completion_tokens_details
        thinking_tok = 0
        details = getattr(response.usage, "completion_tokens_details", None)
        if details is not None:
            thinking_tok = getattr(details, "reasoning_tokens", 0) or 0
        usage = ResponseUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
            thinking_tokens=thinking_tok,
        )

    return AgenticResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=usage,
        reasoning_summaries=reasoning_summaries or None,
    )


def normalize_openai_responses(response: Any) -> AgenticResponse:
    """Normalize an OpenAI Responses API response to AgenticResponse.

    The Responses API returns ``response.output`` — a list of heterogeneous
    output items (message, function_call, web_search_call, etc.).

    - ``message`` items contain text sub-blocks → TextBlock
    - ``function_call`` items → ToolUseBlock (GEODE tool invocations)
    - ``web_search_call`` items → skipped (server-side, transparent)

    v0.53.3 — usage is always extracted (even when ``output`` is empty)
    so cost/token telemetry survives the Codex Plus
    ``response.completed``-with-empty-output edge case. The CodexAgenticAdapter
    pre-populates ``response.output`` from accumulated
    ``response.output_item.done`` events before calling this normaliser
    (Codex Rust pattern — never trust ``Completed.output``).
    """
    blocks: list[TextBlock | ToolUseBlock] = []
    has_function_calls = False
    # v0.57.0 R6 — sidecar accumulator for the "live thinking..." UI surface.
    reasoning_summaries: list[str] = []
    # v0.55.0 — sidecar accumulator for Codex Plus encrypted reasoning.
    # Hermes pattern (codex_responses_adapter.py:720-738): capture every
    # ``reasoning`` item the server emits so the loop can echo it back
    # in the next-turn ``input`` array. Without this, multi-turn gpt-5.x
    # sessions lose reasoning state on every round (the encrypted blob
    # is opaque continuation state, not optional metadata).
    codex_reasoning_items: list[dict[str, Any]] = []

    output = getattr(response, "output", None) or []
    for item in output:
        item_type = getattr(item, "type", "")

        if item_type == "message":
            for sub in getattr(item, "content", []):
                sub_type = getattr(sub, "type", "")
                if sub_type == "output_text":
                    text = getattr(sub, "text", "")
                    if text:
                        blocks.append(TextBlock(text=text))

        elif item_type == "function_call":
            has_function_calls = True
            call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
            name = getattr(item, "name", "")
            arguments = getattr(item, "arguments", "{}")
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append(ToolUseBlock(id=call_id, name=name, input=args))

        elif item_type == "reasoning":
            # Capture for multi-turn replay. Skip if the encrypted blob
            # is missing — without it, replay can't resume reasoning
            # state and would just bloat the next request for nothing.
            encrypted = getattr(item, "encrypted_content", None)
            if not isinstance(encrypted, str) or not encrypted:
                # v0.57.0 R6 — even when the encrypted blob is missing,
                # capture the summary text for the UI surface (some
                # transient errors strip encrypted_content but keep
                # summary).
                summary_only = getattr(item, "summary", None)
                if isinstance(summary_only, list):
                    for part in summary_only:
                        _text = getattr(part, "text", None)
                        if isinstance(_text, str) and _text:
                            reasoning_summaries.append(_text)
                continue
            replay: dict[str, Any] = {"type": "reasoning", "encrypted_content": encrypted}
            item_id = getattr(item, "id", None)
            if isinstance(item_id, str) and item_id:
                replay["id"] = item_id
            summary = getattr(item, "summary", None)
            if isinstance(summary, list):
                serialised: list[dict[str, Any]] = []
                for part in summary:
                    text = getattr(part, "text", None)
                    if isinstance(text, str):
                        serialised.append({"type": "summary_text", "text": text})
                        # v0.57.0 R6 — also surface to UI sidecar
                        if text:
                            reasoning_summaries.append(text)
                replay["summary"] = serialised
            codex_reasoning_items.append(replay)

        # web_search_call, file_search_call, etc. → skip (server-side)

    stop_reason = "tool_use" if has_function_calls else "end_turn"

    usage = ResponseUsage()
    if hasattr(response, "usage") and response.usage is not None:
        # OpenAI Responses API: reasoning_tokens in output_tokens_details
        thinking_tok = 0
        details = getattr(response.usage, "output_tokens_details", None)
        if details is not None:
            thinking_tok = getattr(details, "reasoning_tokens", 0) or 0
        usage = ResponseUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
            thinking_tokens=thinking_tok,
        )

    if not blocks and (usage.output_tokens or 0) > (usage.thinking_tokens or 0):
        # The model produced visible output tokens but the normaliser
        # extracted no blocks. This is anomalous — most likely the
        # Codex Plus accumulator missed an item type, or a future
        # message sub-type. Surface as a single warning rather than
        # silently dropping a paid response.
        log.warning(
            "normalize_openai_responses: usage reports visible output "
            "(out=%d, reasoning=%d) but no content blocks extracted "
            "(items=%d, has_output_attr=%s)",
            usage.output_tokens,
            usage.thinking_tokens,
            len(output),
            hasattr(response, "output"),
        )

    return AgenticResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=usage,
        codex_reasoning_items=codex_reasoning_items or None,
        reasoning_summaries=reasoning_summaries or None,
    )
