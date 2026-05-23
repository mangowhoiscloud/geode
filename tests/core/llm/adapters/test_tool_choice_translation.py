"""Anthropic adapter ``tool_choice`` translation invariants.

Codex MCP 2026-05-23 MEDIUM 1: the loop emits ``{"type": "none"}`` during
wrap-up to forbid tool calls. Without explicit translation, the SDK silently
allows tool use and the wrap-up safety net is defeated.
"""

from __future__ import annotations

import pytest
from core.llm.adapters._anthropic_common import build_create_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec


def _req(tool_choice: object = "auto") -> AdapterCallRequest:
    return AdapterCallRequest(
        model="claude-haiku-4-5",
        messages=[Message(role="user", content="x")],
        system_prompt="",
        tools=[ToolSpec(name="t", description="", input_schema={"type": "object"})],
        tool_choice=tool_choice,  # type: ignore[arg-type]
        max_tokens=4096,
    )


@pytest.mark.parametrize(
    ("loop_choice", "expected"),
    [
        ("auto", {"type": "auto"}),
        ("any", {"type": "any"}),
        ("none", {"type": "none"}),  # wrap-up safety net
        ("required", {"type": "any"}),
    ],
)
def test_string_tool_choice_translates(loop_choice: str, expected: dict[str, str]) -> None:
    kwargs = build_create_kwargs(_req(tool_choice=loop_choice))
    assert kwargs["tool_choice"] == expected


def test_dict_tool_choice_passes_through() -> None:
    """A dict from the loop (e.g. ``{"type": "tool", "name": "X"}``) survives."""
    forced = {"type": "tool", "name": "X"}
    kwargs = build_create_kwargs(_req(tool_choice=forced))
    assert kwargs["tool_choice"] == forced


def test_unknown_string_tool_choice_omitted() -> None:
    """Unrecognised literal → no ``tool_choice`` key, Anthropic default applies."""
    kwargs = build_create_kwargs(_req(tool_choice="garbage"))
    assert "tool_choice" not in kwargs


def test_no_tools_no_tool_choice() -> None:
    """When the request carries no tools, ``tool_choice`` is also omitted."""
    req = AdapterCallRequest(
        model="claude-haiku-4-5",
        messages=[Message(role="user", content="x")],
        tools=(),
        tool_choice="none",  # would normally translate, but no tools → skip
        max_tokens=4096,
    )
    kwargs = build_create_kwargs(req)
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
