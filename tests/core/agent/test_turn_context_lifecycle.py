"""The physical turn restores attribution after observation, failure, and cancellation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core.agent import cognitive_state_ctx as ctx
from core.agent.cognitive_state import CognitiveState
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, AgenticResult, _lifecycle, _phases
from core.agent.tool_executor import ToolExecutor
from core.llm.adapters import dispatch


def _loop() -> AgenticLoop:
    return AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={}, auto_approve=True),
        config=AgenticLoopConfig(source="payg"),
        provider="anthropic",
        quiet=True,
    )


def _attempt(name: str) -> None:
    dispatch._fire_attempt(dispatch.AdapterAttempt(name, "anthropic", "payg", "text", "success", 0))


def _attribution() -> tuple[Any, ...]:
    return (
        ctx.get_cognitive_state(),
        ctx.get_session_id(),
        ctx.get_turn_id(),
        ctx.get_parent_session_key(),
        ctx.get_parent_session_id(),
        ctx.get_tool_call_id(),
    )


@pytest.mark.parametrize("exit_kind", ["success", "error", "cancel"])
def test_physical_turn_restores_context_and_retains_final_usage(
    monkeypatch: pytest.MonkeyPatch, exit_kind: str
) -> None:
    loop = _loop()
    loop._session_id = "inner-session"
    loop._turn_id = "inner-turn"
    failure = (
        asyncio.CancelledError("cancelled") if exit_kind == "cancel" else RuntimeError("failed")
    )
    terminal = AgenticResult(text="done", termination_reason="natural")
    payloads: list[dict[str, Any]] = []

    async def prepare(current: AgenticLoop, text: str, **_: Any) -> AgenticResult:
        await current._emit_session_start_signals(text)
        _attempt("inner")
        ctx.set_tool_call_id("inner-tool")
        if exit_kind != "success":
            raise failure
        ended, _, _ = _lifecycle._final_hook_payloads(current, terminal, text)
        payloads.append(ended)
        assert ctx.get_session_id() == "inner-session"
        return terminal

    monkeypatch.setattr(_phases, "prepare_input", prepare)

    async def scenario() -> None:
        ctx.set_cognitive_state(CognitiveState())
        ctx.set_session_id("outer-session")
        ctx.set_turn_id("outer-turn")
        ctx.set_parent_session_key("outer-parent-key")
        ctx.set_parent_session_id("outer-parent")
        ctx.set_tool_call_id("outer-tool")
        outer = _attribution()
        dispatch.begin_session_adapter_tracking()
        _attempt("outer")
        if exit_kind == "success":
            assert await loop.arun("task") is terminal
        else:
            with pytest.raises(type(failure)) as caught:
                await loop.arun("task")
            assert caught.value is failure
        assert _attribution() == outer
        assert dispatch.get_session_adapter_usage() == {"outer": {"success": 1}}

    asyncio.run(scenario())
    if exit_kind == "success":
        assert payloads[0]["adapter_usage"] == {"inner": {"success": 1}}


def test_nested_turn_restores_parent_then_restores_unbound_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, child = _loop(), _loop()
    parent._session_id, child._session_id = "parent", "child"
    terminal = AgenticResult(text="done", termination_reason="natural")
    ended: dict[str, dict[str, Any]] = {}

    async def prepare(current: AgenticLoop, text: str, **_: Any) -> AgenticResult:
        await current._emit_session_start_signals(text)
        _attempt(current._session_id)
        if current is parent:
            before = _attribution()
            await child.arun("nested")
            assert _attribution() == before
            assert dispatch.get_session_adapter_usage() == {"parent": {"success": 1}}
        ended[current._session_id], _, _ = _lifecycle._final_hook_payloads(current, terminal, text)
        return terminal

    monkeypatch.setattr(_phases, "prepare_input", prepare)

    async def scenario() -> None:
        before = _attribution()
        await parent.arun("task")
        assert _attribution() == before
        assert dispatch.get_session_adapter_usage() == {}
        # Reusing the same object starts a fresh counter and restores again.
        await parent.arun("another task")
        assert _attribution() == before

    asyncio.run(scenario())
    assert ended["parent"]["adapter_usage"] == {"parent": {"success": 1}}
    assert ended["child"]["adapter_usage"] == {"child": {"success": 1}}
