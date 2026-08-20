"""Translation tests — AgenticLoop ↔ :class:`LLMAdapter` round-trip.

Pins the contract between :meth:`LLMAdapter.acomplete` and the
``AgenticResponse`` consumed by the agentic loop. Regression here means
the Path-B route silently drops tool_use blocks or mangles message
content during the round trip.

PR-MAINPATH-67 (2026-05-24) — file renamed from
``test_legacy_bridge.py`` after the bridge module was inlined into
:mod:`core.llm.adapters.translation`.
"""

from __future__ import annotations

import pytest
from core.llm.adapters.base import AdapterCallResult, ToolSpec, UsageSummary
from core.llm.adapters.translation import (
    agentic_response_from_adapter_result,
    build_adapter_request,
)
from core.tools.plan import (
    ExecutionBinding,
    bind_tool_plan,
    compile_tool_plan,
)


def _bound_plan():
    specs = (
        ToolSpec(
            name="eager",
            description="eager tool",
            input_schema={"type": "object", "properties": {"items": {"type": "array"}}},
        ),
        ToolSpec(
            name="deferred",
            description="deferred tool",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        ),
    )
    plan = compile_tool_plan(
        ((spec, "test") for spec in specs),
        (ExecutionBinding(spec.name, "test") for spec in specs),
        deferred_tools=frozenset({"deferred"}),
    )
    return bind_tool_plan(plan, {spec.name: lambda: None for spec in specs})


def test_build_request_translates_user_message() -> None:
    req = build_adapter_request(
        model="claude-haiku-4-5",
        system="Mode: helpful assistance.",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
        allowed_tool_names=frozenset({"search"}),
        denied_tool_names=frozenset({"computer"}),
        executable_tool_names=frozenset({"search"}),
    )
    assert req.model == "claude-haiku-4-5"
    assert req.system_prompt == "Mode: helpful assistance."
    assert len(req.messages) == 1
    assert req.messages[0].role == "user"
    assert req.messages[0].content == "hi"
    assert req.tool_choice == "auto"
    assert req.allowed_tool_names == frozenset({"search"})
    assert req.denied_tool_names == frozenset({"computer"})
    assert req.executable_tool_names == frozenset({"search"})


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
    assert req.deferred_tool_names == ()
    assert req.tool_plan_hash == ""
    assert req.tool_plan_generation == 0


def test_build_request_uses_bound_plan_specs_and_identity() -> None:
    bound = _bound_plan()

    req = build_adapter_request(
        model="m",
        system="",
        messages=[{"role": "user", "content": "x"}],
        tools=bound,
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )

    assert tuple(tool.name for tool in req.tools) == ("eager", "deferred")
    assert req.tools[0] is bound.ordered_specs[0]
    assert req.tools[1] is bound.ordered_specs[1]
    assert req.deferred_tool_names == ("deferred",)
    assert req.tool_plan_hash == bound.content_hash
    assert req.tool_plan_generation == bound.generation


def test_bound_request_appends_transient_tools_without_changing_plan_identity() -> None:
    bound = _bound_plan()
    transient = [
        {
            "name": "mcp_search",
            "description": "transient MCP tool",
            "input_schema": {"type": "object"},
        },
        {
            "name": "mcp_fetch",
            "description": "second transient MCP tool",
            "input_schema": {"type": "object"},
        },
    ]

    req = build_adapter_request(
        model="m",
        system="",
        messages=[],
        tools=bound,
        transient_tools=transient,
        transient_deferred_tool_names=("mcp_fetch", "mcp_search"),
        tool_choice="auto",
        max_tokens=4096,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )

    assert tuple(tool.name for tool in req.tools) == (
        "eager",
        "deferred",
        "mcp_search",
        "mcp_fetch",
    )
    assert req.deferred_tool_names == ("deferred", "mcp_search", "mcp_fetch")
    assert req.tool_plan_hash == bound.content_hash


def test_bound_request_rejects_duplicate_transient_name() -> None:
    with pytest.raises(ValueError, match="duplicate transient tool spec: eager"):
        build_adapter_request(
            model="m",
            system="",
            messages=[],
            tools=_bound_plan(),
            transient_tools=[{"name": "eager", "description": "shadow", "input_schema": {}}],
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.0,
            thinking_budget=0,
            effort="medium",
        )


def test_bound_request_rejects_unknown_transient_deferred_name() -> None:
    with pytest.raises(
        ValueError,
        match="transient deferred metadata references unknown tools: stale_mcp",
    ):
        build_adapter_request(
            model="m",
            system="",
            messages=[],
            tools=_bound_plan(),
            transient_tools=[{"name": "current_mcp", "description": "current", "input_schema": {}}],
            transient_deferred_tool_names=("stale_mcp",),
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.0,
            thinking_budget=0,
            effort="medium",
        )


def test_bound_request_rejects_duplicate_transient_deferred_name() -> None:
    with pytest.raises(ValueError, match="duplicate transient deferred tool name"):
        build_adapter_request(
            model="m",
            system="",
            messages=[],
            tools=_bound_plan(),
            transient_tools=[{"name": "current_mcp", "description": "current", "input_schema": {}}],
            transient_deferred_tool_names=("current_mcp", "current_mcp"),
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.0,
            thinking_budget=0,
            effort="medium",
        )


def test_legacy_request_rejects_transient_second_authority() -> None:
    with pytest.raises(ValueError, match="transient tool metadata requires a BoundToolPlan"):
        build_adapter_request(
            model="m",
            system="",
            messages=[],
            tools=[],
            transient_tools=[],
            tool_choice="auto",
            max_tokens=4096,
            temperature=0.0,
            thinking_budget=0,
            effort="medium",
        )


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
    """Adapter usage maps onto the loop's existing detailed usage fields."""
    result = AdapterCallResult(
        text="ok",
        usage=UsageSummary(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=80,
            reasoning_tokens=12,
            cache_write_tokens=5,
        ),
        stop_reason="end_turn",
    )
    resp = agentic_response_from_adapter_result(result)
    assert resp.usage.cache_read_tokens == 80
    assert resp.usage.thinking_tokens == 12
    assert resp.usage.cache_creation_tokens == 5
    assert resp.usage.input_tokens == 100
