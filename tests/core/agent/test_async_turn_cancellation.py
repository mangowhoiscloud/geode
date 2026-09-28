"""Async cancellation closes the admitted turn through its existing lifecycle owner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.loop.models import TerminationReason, TurnState
from core.agent.tool_executor import ToolExecutor
from core.llm.adapters.registry import bootstrap_builtins
from core.tools.plan import bind_tool_plan, compile_tool_plan


@pytest.mark.parametrize("established", [None, TerminationReason.NATURAL])
def test_cancelled_arun_finalizes_once_without_overwriting_terminal(monkeypatch, established):
    async def run():
        bootstrap_builtins()
        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(bound_tool_plan=bind_tool_plan(compile_tool_plan((), ()), {})),
            config=AgenticLoopConfig(source="subscription", session_id="cancel-session"),
            model="gpt-5.6-luna",
            provider="openai",
            quiet=True,
        )
        loop._turn_id = "cancel-turn"
        loop._turn_state = TurnState(turn_id=loop._turn_id, termination_reason=established)
        loop._tool_processor.tool_log.append({"name": "already_completed", "input": {}})
        loop._timeline = Mock()
        loop._evidence_ledger = Mock()
        loop._save_checkpoint = Mock()
        loop._hooks = None
        started = asyncio.Event()

        async def pending(*_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("core.agent.loop._goal.run", pending)
        task = asyncio.create_task(loop.arun("request"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        if established is not None:
            assert loop._turn_state.termination_reason == established
            loop._evidence_ledger.append_final.assert_not_called()
            assert not loop._turn_state.cancellation.is_set()
        else:
            assert loop._turn_state.termination_reason == TerminationReason.USER_CANCELLED
            assert loop._turn_state.cancellation.is_set()
            loop._evidence_ledger.append_final.assert_called_once()
            result = loop._evidence_ledger.append_final.call_args.kwargs["result"]
            assert result.termination_reason == TerminationReason.USER_CANCELLED
            assert result.tool_calls == [{"name": "already_completed", "input": {}}]
            assert result.error is None
            loop._save_checkpoint.assert_called_once_with("request", round_idx=0)
            turn_record = loop._timeline.record_turn_complete.call_args.kwargs
            assert turn_record["successful"] is False
            assert turn_record["failed"] is False

    asyncio.run(run())


def test_cancel_cleanup_failure_preserves_cancelled_error(monkeypatch):
    from types import SimpleNamespace

    from core.llm.adapters.registry import active_registry_snapshot

    async def run():
        owner = object.__new__(AgenticLoop)
        owner._adapter_registry_snapshot = active_registry_snapshot()
        owner._turn_id = "turn"
        owner._turn_state = TurnState(turn_id="turn")
        owner._session_id = "session"
        owner._tool_processor = SimpleNamespace(tool_log=[])
        owner._afinalize_and_return = AsyncMock(side_effect=OSError("disk full"))
        error = asyncio.CancelledError("cancelled by caller")
        monkeypatch.setattr("core.agent.loop._goal.run", AsyncMock(side_effect=error))
        with pytest.raises(asyncio.CancelledError) as caught:
            await owner.arun("request")
        assert caught.value is error
        owner._afinalize_and_return.assert_awaited_once()

    asyncio.run(run())
