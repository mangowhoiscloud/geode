"""Actual provider wire projections from one immutable bound tool plan."""

from __future__ import annotations

from unittest.mock import patch

from core.llm.adapters._anthropic_common import build_create_kwargs
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.translation import build_adapter_request
from core.llm.providers.anthropic import _TOOL_SEARCH_TOOL
from core.tools.plan import (
    BoundToolPlan,
    ExecutionBinding,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _noop() -> None:
    return None


def _bound_plan() -> BoundToolPlan:
    names = ("eager", *(f"deferred_{index:02d}" for index in range(16)))
    specs = tuple(
        ToolSpec(
            name=name,
            description=f"{name} description",
            input_schema={
                "type": "object",
                "properties": {"items": {"type": "array", "default": []}},
            },
        )
        for name in names
    )
    plan = compile_tool_plan(
        ((spec, "test") for spec in specs),
        (ExecutionBinding(spec.name, "test") for spec in specs),
        deferred_tools=frozenset(names[1:]),
    )
    return bind_tool_plan(plan, dict.fromkeys(names, _noop))


def _request(model: str, *, transient_name: str = "mcp_transient"):
    return build_adapter_request(
        model=model,
        system="Mode: test.",
        messages=[{"role": "user", "content": "hi"}],
        tools=_bound_plan(),
        transient_tools=[
            {
                "name": transient_name,
                "description": "transient description",
                "input_schema": {"type": "object"},
            }
        ],
        transient_deferred_tool_names=(transient_name,),
        tool_choice="auto",
        max_tokens=512,
        temperature=0.0,
        thinking_budget=0,
        effort="medium",
    )


def _anthropic_function(name: str, *, deferred: bool) -> dict:
    tool = {
        "name": name,
        "description": f"{name} description",
        "input_schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "default": []}},
        },
    }
    if deferred:
        tool["defer_loading"] = True
    return tool


def _openai_function(name: str, *, deferred: bool) -> dict:
    tool = {
        "type": "function",
        "name": name,
        "description": f"{name} description",
        "parameters": {
            "type": "object",
            "properties": {"items": {"type": "array", "default": []}},
        },
    }
    if deferred:
        tool["defer_loading"] = True
    return tool


def test_anthropic_wire_preserves_plan_order_shape_and_transient_boundary() -> None:
    req = _request("claude-opus-4-8")
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=False):
        tools = build_create_kwargs(req)["tools"]

    expected = [
        dict(_TOOL_SEARCH_TOOL),
        _anthropic_function("eager", deferred=False),
        *(_anthropic_function(f"deferred_{index:02d}", deferred=True) for index in range(16)),
        {
            "name": "mcp_transient",
            "description": "transient description",
            "input_schema": {"type": "object"},
            "defer_loading": True,
        },
    ]
    assert tools == expected


def test_openai_wire_preserves_plan_order_shape_and_transient_boundary() -> None:
    req = _request("gpt-5.5")
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=False):
        tools = build_responses_kwargs(req, backend="platform", adapter_name="openai-payg")["tools"]

    expected = [
        _openai_function("eager", deferred=False),
        *(_openai_function(f"deferred_{index:02d}", deferred=True) for index in range(16)),
        {
            "type": "function",
            "name": "mcp_transient",
            "description": "transient description",
            "parameters": {"type": "object"},
            "defer_loading": True,
        },
        {"type": "tool_search"},
    ]
    assert tools == expected


def test_anthropic_refreshed_mcp_overlay_replaces_deferred_wire_member() -> None:
    before_req = _request("claude-opus-4-8", transient_name="mcp_before")
    after_req = _request("claude-opus-4-8", transient_name="mcp_after")
    assert before_req.tool_plan_hash == after_req.tool_plan_hash
    assert before_req.deferred_tool_names[-1] == "mcp_before"
    assert after_req.deferred_tool_names[-1] == "mcp_after"
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=False):
        before = build_create_kwargs(before_req)["tools"]
        after = build_create_kwargs(after_req)["tools"]

    assert "mcp_before" in [tool["name"] for tool in before if tool.get("defer_loading")]
    assert "mcp_before" not in [tool["name"] for tool in after]
    assert [tool["name"] for tool in after if tool.get("defer_loading")][-1] == "mcp_after"


def test_openai_refreshed_mcp_overlay_replaces_deferred_wire_member() -> None:
    before_req = _request("gpt-5.5", transient_name="mcp_before")
    after_req = _request("gpt-5.5", transient_name="mcp_after")
    assert before_req.tool_plan_hash == after_req.tool_plan_hash
    assert before_req.deferred_tool_names[-1] == "mcp_before"
    assert after_req.deferred_tool_names[-1] == "mcp_after"
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=False):
        before = build_responses_kwargs(
            before_req,
            backend="platform",
            adapter_name="openai-payg",
        )["tools"]
        after = build_responses_kwargs(
            after_req,
            backend="platform",
            adapter_name="openai-payg",
        )["tools"]

    assert "mcp_before" in [tool["name"] for tool in before if tool.get("defer_loading")]
    assert "mcp_before" not in [tool.get("name") for tool in after]
    assert [tool["name"] for tool in after if tool.get("defer_loading")][-1] == "mcp_after"
