"""Prompt rebuilds preserve runtime hints after explicit state changes."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from core.agent.loop import _guards, _response
from core.agent.loop.agent_loop import AgenticLoop
from core.hooks import HookEvent, HookSystem


class _StubLoop:
    def __init__(self, *, prompt_dirty: bool = False) -> None:
        self._prompt_dirty = prompt_dirty
        self._last_plan_hint = ""
        self._plan_hint = ""
        self.build_calls = 0

    def _build_system_prompt(self) -> str:
        self.build_calls += 1
        return "REBUILT_PROMPT"


def _call_helper(
    stub: _StubLoop,
    system_prompt: str,
    hint: str | None,
    verification_hint: str | None = None,
) -> str:
    bound = AgenticLoop._sync_model_and_rebuild_prompt.__get__(stub, _StubLoop)
    with patch.object(_guards, "_consume_plan_hint", return_value=stub._plan_hint):
        return asyncio.run(bound(system_prompt, hint, verification_hint))


def test_unchanged_prompt_keeps_existing_hints_without_rebuilding() -> None:
    stub = _StubLoop()
    original = "ORIGINAL\nexisting hints"
    result = _call_helper(stub, original, "not appended again")
    assert result == original
    assert stub.build_calls == 0
    assert stub._prompt_dirty is False


def test_dirty_prompt_preserves_all_hints_and_rebuilds_only_once() -> None:
    stub = _StubLoop(prompt_dirty=True)
    stub._preflight_hint = "<geode_task_preflight>retained preflight</geode_task_preflight>"
    stub._plan_hint = "<plan>retained plan</plan>"
    reflection = "retained reflection"
    verification = "<verification_continuation>retained verification</verification_continuation>"
    result = _call_helper(stub, "ORIGINAL", reflection, verification)
    assert result.startswith("REBUILT_PROMPT")
    for hint in (stub._preflight_hint, stub._plan_hint, reflection, verification):
        assert result.count(hint) == 1
    assert stub._prompt_dirty is False
    assert stub._last_plan_hint == stub._plan_hint
    assert _call_helper(stub, result, reflection, verification) == result
    assert stub.build_calls == 1


@pytest.mark.parametrize("changed", [False, True])
def test_tool_graph_refresh_discards_only_stale_preflight_hint(changed: bool) -> None:
    from core.agent import capability_graph
    from core.llm.providers import anthropic

    stub = _StubLoop()
    stub._tools = [{"name": "computer"}]
    stub._mcp_manager = None
    stub._tool_registry = None
    stub._allowed_tool_names = None
    stub._bound_tool_plan = None
    stub._policy_sources = {}
    stub._capability_graph = {"visible_tools": ["computer"]}
    stub._preflight_hint = "<geode_task_preflight>recommend computer</geode_task_preflight>"
    new_graph = {"visible_tools": ["web_fetch"]} if changed else stub._capability_graph
    original_prompt = "ORIGINAL\n" + stub._preflight_hint

    with (
        patch.object(_response, "get_agentic_tools", return_value=[{"name": "web_fetch"}]),
        patch.object(capability_graph, "build_capability_graph", return_value=new_graph),
        patch.object(anthropic, "is_computer_use_enabled", return_value=False),
    ):
        _response.refresh_tools(stub)
    result = _call_helper(stub, original_prompt, None)

    if changed:
        assert result == "REBUILT_PROMPT"
        assert stub._preflight_hint == ""
    else:
        assert result == original_prompt
        assert "recommend computer" in stub._preflight_hint


def test_advisory_plan_progress_rebuilds_prompt_without_new_selection() -> None:
    stub = _StubLoop()
    stub._last_plan_hint = "<plan>old current step</plan>"
    stub._plan_hint = "<plan>new current step</plan>"
    stub.model = "claude-sonnet-5"
    stub._provider = "anthropic"
    stub._system_prompt_override = None
    stub._hooks = HookSystem()
    received = []

    async def capture(event, payload):
        received.append((event, payload))

    stub._hooks.register(HookEvent.PROMPT_ASSEMBLED, capture)
    result = _call_helper(stub, "ORIGINAL", None)
    assert stub.build_calls == 1
    assert "new current step" in result
    assert "old current step" not in result
    assert "None" not in result
    assert stub._last_plan_hint == stub._plan_hint
    assert len(received) == 1
    event, payload = received[0]
    assert event is HookEvent.PROMPT_ASSEMBLED
    assert payload["reason"] == "plan_progress"
    assert payload["prompt_len"] == len(result)
