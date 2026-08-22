"""R3.1 immutable-step and mutable-turn ownership contracts."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.loop.models import StepSnapshot, TerminationReason, TurnState
from core.agent.tool_executor import ToolExecutor
from core.hooks import (
    HookAction,
    HookCorrelation,
    HookDecision,
    HookName,
    HookRegistry,
    HookSystem,
    LlmCallRequest,
    MiddlewareRegistry,
)
from core.hooks.system import RuntimeEvent
from core.llm.adapters.base import AdapterCallResult, UsageSummary
from core.llm.adapters.registry import bootstrap_builtins
from core.tools.base import ToolContext
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
            config=AgenticLoopConfig(
                source="subscription",
                disable_settings_drift=True,
                session_id="session-1",
            ),
            model="gpt-5.6-luna",
            provider="openai",
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
        newer = bound.projected(())
        loop._bound_tool_plan = newer
        loop.executor._replace_bound_tool_plan(newer)
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
    assert context.bound_tool_plan is first.bound_tool_plan


def test_auxiliary_sampling_does_not_replace_turn_messages() -> None:
    class Adapter:
        name = "capture"
        provider = "openai"
        source = "subscription"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            return AdapterCallResult(text="ok", usage=UsageSummary())

    async def run() -> None:
        messages = [{"role": "user", "content": "physical turn"}]
        loop = AgenticLoop(
            ConversationContext(),
            ToolExecutor(action_handlers={}),
            config=AgenticLoopConfig(source="subscription", disable_settings_drift=True),
            model="gpt-5.6-luna",
            provider="openai",
            quiet=True,
        )
        loop._turn_id = "turn-1"
        loop._turn_state = TurnState(turn_id="turn-1", messages=messages)
        loop._new_adapter = Adapter()

        await loop._call_llm(
            "auxiliary",
            [{"role": "user", "content": "judge prompt"}],
            allow_tools=False,
        )

        assert loop._turn_state.messages is messages
        assert loop._turn_state.messages == [{"role": "user", "content": "physical turn"}]

    asyncio.run(run())


def test_sampling_snapshot_finalizes_the_middleware_route_for_tools() -> None:
    seen_contexts: list[ToolContext] = []

    def handler(**kwargs: Any) -> dict[str, bool]:
        seen_contexts.append(kwargs["_tool_context"])
        return {"ok": True}

    class OriginalAdapter:
        name = "original"
        provider = "openai"
        source = "subscription"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            raise AssertionError("middleware route was not used")

    class EffectiveAdapter:
        name = "effective"
        provider = "anthropic"
        source = "payg"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            return AdapterCallResult(
                text="",
                usage=UsageSummary(),
                stop_reason="tool_use",
                tool_uses=({"id": "call-1", "name": "ordinary", "input": {}},),
            )

    effective = EffectiveAdapter()

    class RouteMiddleware:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            return replace(
                request,
                adapter=effective,
                request=replace(request.request, model="middleware-model"),
            )

    async def run() -> StepSnapshot:
        middleware = MiddlewareRegistry()
        middleware.register_llm_request(RouteMiddleware(), name="route")
        executor = ToolExecutor(
            action_handlers={"ordinary": handler},
            middleware_registry=middleware,
        )
        loop = AgenticLoop(
            ConversationContext(),
            executor,
            config=AgenticLoopConfig(source="subscription", disable_settings_drift=True),
            model="initial-model",
            provider="openai",
            quiet=True,
        )
        loop._turn_id = "turn-1"
        loop._turn_state = TurnState(turn_id="turn-1")
        loop._new_adapter = OriginalAdapter()

        response = await loop._call_llm("system", [], round_idx=0)
        snapshot = loop._current_step_snapshot
        assert response is not None
        assert snapshot is not None
        loop._emit_cognitive = AsyncMock()
        loop._maybe_reflect = AsyncMock()
        await loop._run_cognitive_act_observe_cycle(response, 0, step_snapshot=snapshot)
        return snapshot

    snapshot = asyncio.run(run())

    assert (snapshot.model, snapshot.provider, snapshot.source, snapshot.adapter_name) == (
        "middleware-model",
        "anthropic",
        "payg",
        "effective",
    )
    assert len(seen_contexts) == 1
    context = seen_contexts[0]
    assert (context.model, context.provider, context.source, context.adapter_name) == (
        "middleware-model",
        "anthropic",
        "payg",
        "effective",
    )


def test_usage_is_charged_to_the_finalized_step_model() -> None:
    from core.llm.token_tracker import get_tracker, reset_tracker

    reset_tracker()
    loop = object.__new__(AgenticLoop)
    loop.model = "initial-model"
    loop._current_step_snapshot = StepSnapshot(
        step_id="turn-1:step-1",
        step_index=1,
        round_index=0,
        model="middleware-model",
        provider="anthropic",
        source="payg",
        adapter_name="effective",
        bound_tool_plan=None,
        time_budget_s=60.0,
        cost_budget_usd=1.0,
        cancellation=asyncio.Event(),
        correlation=HookCorrelation(),
    )
    loop._quiet = True
    loop._hooks = None

    loop._track_usage(SimpleNamespace(usage=UsageSummary(input_tokens=10)))

    assert get_tracker().accumulator.calls[-1].model == "middleware-model"


def test_tool_hooks_and_runtime_events_keep_step_correlation() -> None:
    public_correlations: list[HookCorrelation] = []
    runtime_payloads: list[dict[str, Any]] = []
    middleware_correlations: list[dict[str, Any]] = []

    def public_hook(invocation: Any) -> None:
        public_correlations.append(invocation.correlation)

    def runtime_hook(_event: RuntimeEvent, payload: dict[str, Any]) -> None:
        runtime_payloads.append(payload)

    class CaptureMiddleware:
        async def tool_request(self, request: Any) -> Any:
            middleware_correlations.append(dict(request.correlation))
            return request

    hooks = HookSystem()
    hooks.register(RuntimeEvent.TOOL_EXEC_STARTED, runtime_hook, name="capture")
    registry = HookRegistry()
    registry.register(HookName.PRE_TOOL_USE, public_hook, name="capture-pre")
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda invocation: (
            public_correlations.append(invocation.correlation)
            or HookDecision(action=HookAction.ALLOW)
        ),
        name="capture-permission",
    )
    middleware = MiddlewareRegistry()
    middleware.register_tool_request(CaptureMiddleware(), name="capture")
    executor = ToolExecutor(
        action_handlers={"create_goal": lambda **_kwargs: {"ok": True}},
        hooks=hooks,
        hook_registry=registry,
        middleware_registry=middleware,
    )
    context = ToolContext(
        session_id="session-1",
        turn_id="turn-1",
        step_id="turn-1:step-2",
        session_generation=3,
        verify_attempt=1,
        tool_call_id="call-1",
    )

    asyncio.run(
        executor.aexecute(
            "create_goal",
            {"objective": "bounded", "token_budget": 2_000},
            context=context,
        )
    )

    expected = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "step_id": "turn-1:step-2",
        "session_generation": 3,
        "verify_attempt": 1,
        "tool_call_id": "call-1",
    }
    assert len(public_correlations) == 2
    assert all(
        getattr(correlation, key) == value
        for correlation in public_correlations
        for key, value in expected.items()
    )
    assert all(middleware_correlations[0][key] == value for key, value in expected.items())
    assert all(runtime_payloads[0][key] == value for key, value in expected.items())


def test_terminal_result_records_the_closed_reason_on_the_active_turn() -> None:
    loop = object.__new__(AgenticLoop)
    loop._turn_id = "turn-1"
    loop._turn_state = TurnState(turn_id="turn-1")

    from core.agent.loop import _guards

    result = _guards._terminal_result(loop, TerminationReason.USER_CANCELLED, "stopped", rounds=1)

    assert result.termination_reason is TerminationReason.USER_CANCELLED
    assert loop._turn_state.termination_reason is TerminationReason.USER_CANCELLED
    assert loop._turn_state.cancellation.is_set()
