"""R3.1 immutable-step and mutable-turn ownership contracts."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.loop.models import StepSnapshot, TerminationReason, TurnState
from core.agent.tool_executor import ToolExecutor
from core.hooks import HookCorrelation
from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.llm.adapters.registry import bootstrap_builtins
from core.tools.plan import (
    BoundToolPlan,
    ExecutionBinding,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _bound_plan(handler: Any) -> BoundToolPlan:
    plan = compile_tool_plan(
        ((ToolSpec("ordinary", "Ordinary", {"type": "object"}), "test[0]"),),
        (ExecutionBinding("ordinary", "test"),),
    )
    return bind_tool_plan(plan, {"ordinary": handler})


def test_step_snapshot_is_frozen_and_turn_state_is_the_mutable_accumulator() -> None:
    cancellation = asyncio.Event()
    turn = TurnState(
        turn_id="turn-1",
        messages=[{"role": "user", "content": "hello"}],
        plan_hint="inspect",
        cancellation=cancellation,
    )
    step = StepSnapshot(
        step_id="step-1",
        step_index=1,
        round_index=0,
        model="gpt-5.6-luna",
        provider="openai",
        source="subscription",
        adapter_name="codex",
        bound_tool_plan=None,
        time_budget_s=60.0,
        cost_budget_usd=1.0,
        cancellation=cancellation,
        correlation=HookCorrelation(session_id="session-1", turn_id="turn-1"),
    )

    with pytest.raises(FrozenInstanceError):
        step.__setattr__("model", "changed")
    turn.round_index += 1
    turn.retry_count += 1
    turn.termination_reason = TerminationReason.NATURAL
    assert (turn.round_index, turn.retry_count, turn.termination_reason) == (
        1,
        1,
        TerminationReason.NATURAL,
    )
    assert step.cancellation is turn.cancellation


def test_one_sampling_snapshot_reaches_its_tool_context_and_retries_are_monotone() -> None:
    seen_contexts: list[Any] = []

    def handler(**kwargs: Any) -> dict[str, bool]:
        seen_contexts.append(kwargs["_tool_context"])
        return {"ok": True}

    class Adapter:
        name = "capture"
        provider = "openai"
        source = "subscription"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            return AdapterCallResult(
                text="",
                usage=UsageSummary(),
                stop_reason="tool_use",
                tool_uses=({"id": "call-1", "name": "ordinary", "input": {}},),
            )

    async def run() -> tuple[StepSnapshot, StepSnapshot, Any]:
        bootstrap_builtins()
        bound = _bound_plan(handler)
        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(bound_tool_plan=bound),
            model="gpt-5.6-luna",
            provider="openai",
            source="subscription",
            disable_settings_drift=True,
            session_id="session-1",
            quiet=True,
        )
        loop._turn_id = "turn-1"
        loop._turn_state = TurnState(
            turn_id="turn-1",
            messages=[{"role": "user", "content": "use it"}],
        )
        loop._new_adapter = Adapter()

        response = await loop._call_llm("system", loop._turn_state.messages, round_idx=0)
        first = loop._current_step_snapshot
        assert response is not None
        assert first is not None
        assert loop._tool_processor._step_snapshot is first

        loop.model = "gpt-5.5"
        await loop._call_llm("system", loop._turn_state.messages, round_idx=0)
        second = loop._current_step_snapshot
        assert second is not None
        loop._emit_cognitive = AsyncMock()
        loop._maybe_reflect = AsyncMock()
        await loop._run_cognitive_act_observe_cycle(
            response,
            0,
            step_snapshot=first,
        )
        return first, second, bound

    first, second, bound = asyncio.run(run())

    assert first.bound_tool_plan is bound
    assert first.step_index == 1
    assert second.step_index == 2
    assert first.round_index == second.round_index == 0
    assert first.step_id != second.step_id
    assert first.model == "gpt-5.6-luna"
    assert second.model == "gpt-5.5"
    assert first.cancellation is second.cancellation
    assert len(seen_contexts) == 1
    context = seen_contexts[0]
    assert context.step_id == first.step_id
    assert context.tool_plan_hash == first.tool_plan_hash == bound.content_hash
    assert context.tool_plan_generation == first.tool_plan_generation == bound.generation
    assert context.cancellation is first.cancellation


def test_terminal_result_records_the_closed_reason_on_the_active_turn() -> None:
    loop = object.__new__(AgenticLoop)
    loop._turn_id = "turn-1"
    loop._turn_state = TurnState(turn_id="turn-1")

    result = loop._terminal_result(TerminationReason.USER_CANCELLED, "stopped", rounds=1)

    assert result.termination_reason is TerminationReason.USER_CANCELLED
    assert loop._turn_state.termination_reason is TerminationReason.USER_CANCELLED
    assert loop._turn_state.cancellation.is_set()
