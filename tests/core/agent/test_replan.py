"""Advisory Plan and evidence-triggered Cognitive Loop tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.plan import (
    Plan,
    PlanStep,
    parse_replan_response,
    plan_async,
    render_plan_for_prompt,
    replan_async,
    replan_response_schema,
    should_replan,
)
from core.agent.verify import verify_turn
from core.observability.session_metrics import current_session_metrics, session_metrics_scope


@pytest.fixture(autouse=True)
def reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEODE_REPLAN_ENABLED", raising=False)
    monkeypatch.delenv("GEODE_REPLAN_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("GEODE_VERIFY_MODE", raising=False)


def _plan(*step_ids: str, current: int = 0) -> Plan:
    return Plan(
        steps=tuple(
            PlanStep(step_id, f"do {step_id}", f"finished {step_id}") for step_id in step_ids
        ),
        current=current,
    )


def _result(text: str) -> AgenticResult:
    return AgenticResult(text=text, tool_calls=[], rounds=1, termination_reason="natural")


def test_plan_is_immutable_and_contains_no_execution_graph_metadata() -> None:
    step = PlanStep("s1", "Inspect", "Evidence inspected")
    plan = Plan(steps=(step,))
    assert PlanStep.__dataclass_params__.frozen is True
    payload = plan.to_dict()
    assert payload["steps"] == [
        {"id": "s1", "description": "Inspect", "expected_outcome": "Evidence inspected"}
    ]
    assert not (
        {"tool_name", "tool_args", "depends_on", "dependencies"} & payload["steps"][0].keys()
    )


def test_plan_progress_and_abandon_are_bookkeeping_only() -> None:
    plan = _plan("s1", "s2")
    progressed = plan.complete_and_advance(1)
    assert progressed.current == 1
    assert progressed.completed == (0,)
    abandoned = progressed.abandon_and_advance()
    assert abandoned.done is True
    assert abandoned.abandoned == (1,)
    with pytest.raises(ValueError):
        plan.complete_and_advance(3)


def test_render_plan_states_advisory_observation_contract() -> None:
    rendered = render_plan_for_prompt(_plan("s1", "s2"))
    assert "<plan>" in rendered
    assert "advisory intent, not an execution graph" in rendered
    assert "Choose the next action from current observations" in rendered
    assert render_plan_for_prompt(_plan("s1", current=1)) == ""


def test_replan_triggers_only_from_observed_evidence() -> None:
    plan = _plan("s1")
    assert (
        should_replan(
            round_idx=0,
            plan=plan,
            verify_failed=True,
            verify_should_retry=True,
        )
        == "verify_fail"
    )
    assert (
        should_replan(
            round_idx=3,
            plan=plan,
            verify_failed=False,
            verify_should_retry=False,
            low_confidence=True,
        )
        == "low_confidence"
    )
    assert (
        should_replan(
            round_idx=10_000,
            plan=plan,
            verify_failed=False,
            verify_should_retry=False,
        )
        is None
    )


def test_replan_requires_retryable_failure_and_respects_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan("s1")
    assert (
        should_replan(
            round_idx=0,
            plan=plan,
            verify_failed=True,
            verify_should_retry=False,
        )
        is None
    )
    monkeypatch.setenv("GEODE_REPLAN_ENABLED", "false")
    assert (
        should_replan(
            round_idx=0,
            plan=plan,
            verify_failed=True,
            verify_should_retry=True,
        )
        is None
    )


def test_plan_schema_and_parser_reject_execution_metadata() -> None:
    schema = replan_response_schema()
    step_schema = schema["properties"]["steps"]["items"]
    assert set(step_schema["properties"]) == {"id", "description", "expected_outcome"}
    assert step_schema["additionalProperties"] is False

    parsed = parse_replan_response(
        '{"steps":[{"id":"s1","description":"Inspect","expected_outcome":"Evidence"}],'
        '"reasoning":"observable first"}'
    )
    assert parsed == ([PlanStep("s1", "Inspect", "Evidence")], "observable first")
    assert (
        parse_replan_response(
            '{"steps":[{"id":"s1","description":"Inspect",'
            '"expected_outcome":"Evidence","tool_name":"read_file"}],'
            '"reasoning":"invalid execution metadata"}'
        )
        is None
    )
    assert parse_replan_response("not json") is None
    assert parse_replan_response('{"steps":[],"reasoning":"x"}') is None


def test_plan_async_disables_tools_and_applies_sil_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "core.agent.decomposition_policy._load_decomposition_policy_override",
        lambda **_kwargs: {"prefix": "SIL policy"},
    )

    async def call_llm(system: str, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        captured.update(system=system, messages=messages, **kwargs)
        return SimpleNamespace(
            text=(
                '{"steps":[{"id":"s1","description":"Inspect",'
                '"expected_outcome":"Evidence"}],"reasoning":"selected"}'
            )
        )

    loop = SimpleNamespace(
        _call_llm=call_llm,
        _policy_sources={},
        model="gpt-test",
    )
    plan = asyncio.run(plan_async(loop, "Inspect the runtime"))
    assert plan is not None
    assert captured["system"].startswith("SIL policy")
    assert captured["allow_tools"] is False
    assert "Available tools" not in captured["messages"][0]["content"]


def test_replan_async_preserves_identity_and_uses_tools_off_schema() -> None:
    captured: dict[str, Any] = {}

    async def call_llm(_system: str, _messages: list[dict[str, str]], **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            text=(
                '{"steps":[{"id":"r1","description":"Repair",'
                '"expected_outcome":"Failure resolved"}],"reasoning":"failure first"}'
            )
        )

    prior = _plan("s1")
    loop = SimpleNamespace(_call_llm=call_llm, _policy_sources={}, model="gpt-test")
    revised = asyncio.run(
        replan_async(
            loop, plan=prior, turn_result=SimpleNamespace(text="failed"), trigger="verify_fail"
        )
    )
    assert revised is not None
    assert revised.plan_id == prior.plan_id
    assert revised.revision == 1
    assert captured["allow_tools"] is False


def test_low_confidence_replan_is_edge_triggered(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.agent import plan as plan_module
    from core.agent.cognitive_state import CognitiveState
    from core.agent.loop.agent_loop import AgenticLoop

    observed: list[bool] = []

    def fake_should_replan(**kwargs: Any) -> str | None:
        low = bool(kwargs["low_confidence"])
        observed.append(low)
        return "low_confidence" if low else None

    async def failed_replan(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(plan_module, "should_replan", fake_should_replan)
    monkeypatch.setattr(plan_module, "replan_async", failed_replan)
    state = CognitiveState()
    stub = SimpleNamespace(cognitive_state=state, _low_confidence_replan_armed=True)
    bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
    with session_metrics_scope():
        for confidence in (0.2, 0.2, 0.9, 0.2):
            state.confidence = confidence
            asyncio.run(bound(1))
    assert observed == [True, False, False, True]


def test_verify_expected_outcome_feeds_retryable_replan_evidence() -> None:
    plan = Plan(steps=(PlanStep("s1", "Search", "arxiv paper found"),))
    with session_metrics_scope(session_id="verify-plan"):
        current_session_metrics().set_active_plan(plan)
        mismatch = verify_turn(_result("unrelated output"))
        assert "step_expected_mismatch" in mismatch.rubric_misses
        assert mismatch.should_retry is True
        matched = verify_turn(_result("The arxiv paper was found"))
        assert "step_expected_mismatch" not in matched.rubric_misses


def test_maybe_replan_installs_verify_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.agent import plan as plan_module
    from core.agent.loop.agent_loop import AgenticLoop

    revised = Plan(steps=(PlanStep("r1", "Repair", "Resolved"),), revision=1)

    async def fake_replan(*_args: Any, **_kwargs: Any) -> Plan:
        return revised

    monkeypatch.setattr(plan_module, "replan_async", fake_replan)
    with session_metrics_scope(session_id="verify-replan"):
        metrics = current_session_metrics()
        metrics.set_active_plan(_plan("s1"))
        metrics.last_verify_passed = False
        metrics.last_verify_should_retry = True
        stub = SimpleNamespace(
            _tool_processor=SimpleNamespace(tool_log=[]),
            _verify_attempt_results=[SimpleNamespace(text="failed candidate")],
            _prompt_dirty=False,
        )
        bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
        asyncio.run(bound(0, failure_context="missing receipt"))
        assert stub._prompt_dirty is True
        assert metrics.active_plan is revised
        assert metrics.last_replan_trigger == "verify_fail"


def test_verify_replan_abandons_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent import plan as plan_module
    from core.agent.loop.agent_loop import AgenticLoop

    monkeypatch.setenv("GEODE_REPLAN_MAX_ATTEMPTS", "1")
    planner_calls = 0

    async def fake_replan(*_args: Any, **_kwargs: Any) -> Plan:
        nonlocal planner_calls
        planner_calls += 1
        return _plan("s1", "s2")

    monkeypatch.setattr(plan_module, "replan_async", fake_replan)
    with session_metrics_scope(session_id="bounded-replan"):
        metrics = current_session_metrics()
        metrics.set_active_plan(_plan("s1", "s2"), reset_attempts=True)
        stub = SimpleNamespace(_tool_processor=SimpleNamespace(tool_log=[]), _prompt_dirty=False)
        bound = AgenticLoop._maybe_replan_async.__get__(stub, SimpleNamespace)
        for _ in range(2):
            metrics.last_verify_passed = False
            metrics.last_verify_should_retry = True
            asyncio.run(bound(0))
        assert planner_calls == 1
        assert metrics.active_plan.current == 1
        assert metrics.active_plan.abandoned == (0,)
