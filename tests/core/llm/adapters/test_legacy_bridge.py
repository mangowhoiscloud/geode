"""Legacy bridge tests — AgenticLoop ↔ LLMAdapter translation.

Pins the contract between the new ``LLMAdapter.acomplete`` surface and the
legacy ``AgenticResponse`` consumed by the agentic loop. Regression here
means the v0.99.40 Follow-up A path silently drops tool_use blocks or
mangles message content during the round trip.
"""

from __future__ import annotations

from core.llm.adapters._legacy_bridge import (
    agentic_response_from_adapter_result,
    build_adapter_request,
)
from core.llm.adapters.base import AdapterCallResult, UsageSummary


def test_build_request_translates_user_message() -> None:
    req = build_adapter_request(
        model="claude-haiku-4-5",
        system="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )
    assert req.model == "claude-haiku-4-5"
    assert req.system_prompt == "You are helpful."
    assert len(req.messages) == 1
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "hi"
    assert req.tool_choice == "auto"


def test_build_request_carries_tool_use_id_for_tool_messages() -> None:
    """Multi-turn tool messages carry tool_use_id so the adapter can re-encode."""
    req = build_adapter_request(
        model="m",
        system="",
        messages=[
            {"role": "user", "content": "calc 1+1"},
            {"role": "tool", "content": "2", "tool_use_id": "tu_123"},
        ],
        tools=[],
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )
    assert req.messages[1].role == "tool"
    assert req.messages[1].tool_use_id == "tu_123"


def test_build_request_translates_tools() -> None:
    req = build_adapter_request(
        model="m",
        system="",
        messages=[{"role": "user", "content": "x"}],
        tools=[
            {"name": "search", "description": "web", "input_schema": {"type": "object"}},
        ],
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )
    assert len(req.tools) == 1
    assert req.tools[0].name == "search"
    assert req.tools[0].description == "web"
    assert req.tools[0].input_schema == {"type": "object"}


def test_response_translation_text_only() -> None:
    """A text-only AdapterCallResult → AgenticResponse with a single TextBlock."""
    from core.llm.agentic_response import TextBlock

    result = AdapterCallResult(
        text="hello world",
        usage=UsageSummary(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    resp = agentic_response_from_adapter_result(result)
    assert len(resp.content) == 1
    block = resp.content[0]
    assert isinstance(block, TextBlock)
    assert block.text == "hello world"
    assert resp.stop_reason == "end_turn"
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5


def test_response_translation_tool_use_block() -> None:
    """Tool uses produce ToolUseBlock entries in order after the text block."""
    from core.llm.agentic_response import ToolUseBlock

    result = AdapterCallResult(
        text="calling tool",
        usage=UsageSummary(),
        stop_reason="tool_use",
        tool_uses=({"id": "tu_1", "name": "search", "input": {"q": "geode"}},),
    )
    resp = agentic_response_from_adapter_result(result)
    assert len(resp.content) == 2
    assert resp.content[0].type == "text"
    block = resp.content[1]
    assert isinstance(block, ToolUseBlock)
    assert block.id == "tu_1"
    assert block.name == "search"
    assert block.input == {"q": "geode"}
    assert resp.stop_reason == "tool_use"


def test_response_translation_parses_string_input() -> None:
    """OpenAI-style tool calls with stringified JSON arguments parse cleanly."""
    from core.llm.agentic_response import ToolUseBlock

    result = AdapterCallResult(
        text="",
        usage=UsageSummary(),
        stop_reason="tool_calls",
        tool_uses=({"id": "tc_1", "name": "lookup", "input": '{"key": "val"}'},),
    )
    resp = agentic_response_from_adapter_result(result)
    # tool_calls → tool_use translation
    assert resp.stop_reason == "tool_use"
    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.input == {"key": "val"}


def test_response_translation_handles_malformed_string_input() -> None:
    """Malformed stringified args don't crash — wrapped in ``_raw`` for inspection."""
    from core.llm.agentic_response import ToolUseBlock

    result = AdapterCallResult(
        text="",
        usage=UsageSummary(),
        stop_reason="tool_use",
        tool_uses=({"id": "tc_x", "name": "x", "input": "{not json"},),
    )
    resp = agentic_response_from_adapter_result(result)
    block = resp.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.input == {"_raw": "{not json"}


def test_response_translation_drops_empty_text() -> None:
    """Empty text → no TextBlock prepended (tool-only response)."""
    result = AdapterCallResult(
        text="",
        usage=UsageSummary(),
        stop_reason="tool_use",
        tool_uses=({"id": "tu_only", "name": "t", "input": {}},),
    )
    resp = agentic_response_from_adapter_result(result)
    assert len(resp.content) == 1
    assert resp.content[0].type == "tool_use"


def test_response_translation_carries_cache_tokens() -> None:
    """``cached_input_tokens`` from the adapter usage maps to ``cache_read_tokens``."""
    result = AdapterCallResult(
        text="ok",
        usage=UsageSummary(input_tokens=100, output_tokens=20, cached_input_tokens=80),
        stop_reason="end_turn",
    )
    resp = agentic_response_from_adapter_result(result)
    assert resp.usage.cache_read_tokens == 80
    assert resp.usage.input_tokens == 100
