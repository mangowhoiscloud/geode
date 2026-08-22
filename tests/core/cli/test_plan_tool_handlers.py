"""Tests for the single advisory ``update_plan`` handler."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from core.cli.tool_handlers.plan import _build_plan_handlers


@pytest.fixture
def plan_handlers() -> dict[str, Any]:
    return dict(_build_plan_handlers())


def test_update_plan_is_the_only_plan_tool(plan_handlers: dict[str, Any]) -> None:
    assert set(plan_handlers) == {"update_plan"}


def test_update_plan_validates_and_renders_progress(plan_handlers: dict[str, Any]) -> None:
    result = plan_handlers["update_plan"](
        explanation="repo change",
        plan=[
            {"step": "Inspect", "status": "completed"},
            {"step": "Patch", "status": "in_progress"},
            {"step": "Verify", "status": "pending"},
        ],
    )
    assert result["status"] == "ok"
    assert result["counts"] == {"pending": 1, "in_progress": 1, "completed": 1}
    assert result["runtime_plan_synced"] is False

    invalid = plan_handlers["update_plan"](plan=[{"step": "Patch", "status": "blocked"}])
    assert "Invalid plan status" in invalid["error"]


def test_update_plan_advances_only_matching_linear_plan(plan_handlers: dict[str, Any]) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import current_session_metrics, session_metrics_scope

    plan = Plan(
        steps=(
            PlanStep("s1", "Inspect", "Evidence inspected"),
            PlanStep("s2", "Patch", "Patch applied"),
        )
    )
    with session_metrics_scope(session_id="progress-sync"):
        metrics = current_session_metrics()
        metrics.set_active_plan(plan)
        result = plan_handlers["update_plan"](
            plan=[
                {"step": "Inspect", "status": "completed"},
                {"step": "Patch", "status": "in_progress"},
            ]
        )
        assert result["runtime_plan_synced"] is True
        assert result["runtime_plan_advanced"] is True
        assert metrics.active_plan.current == 1

        mismatch = plan_handlers["update_plan"](
            plan=[{"step": "Different", "status": "in_progress"}]
        )
        assert mismatch["runtime_plan_synced"] is False
        assert metrics.active_plan.current == 1


@pytest.mark.parametrize(
    "statuses",
    [
        ("pending", "completed"),
        ("in_progress", "in_progress"),
    ],
)
def test_update_plan_does_not_sync_nonlinear_exact_matches(
    plan_handlers: dict[str, Any],
    statuses: tuple[str, str],
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import current_session_metrics, session_metrics_scope

    active = Plan(
        steps=(
            PlanStep("s1", "Inspect", "Evidence inspected"),
            PlanStep("s2", "Patch", "Patch applied"),
        )
    )
    with session_metrics_scope(session_id="nonlinear-progress"):
        metrics = current_session_metrics()
        metrics.set_active_plan(active)
        result = plan_handlers["update_plan"](
            plan=[
                {"step": "Inspect", "status": statuses[0]},
                {"step": "Patch", "status": statuses[1]},
            ]
        )
        assert result["runtime_plan_synced"] is False
        assert metrics.active_plan.current == 0


def test_update_plan_records_observed_progress_edge(
    plan_handlers: dict[str, Any], tmp_path: Path
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import current_session_metrics, session_metrics_scope
    from core.observability.session_timeline import (
        SessionEventStore,
        SessionTimeline,
        set_current_session_timeline,
    )

    plan = Plan(steps=(PlanStep("s1", "Inspect", "Evidence inspected"),))
    timeline = SessionTimeline("progress-edge", db_path=tmp_path / "sessions.db")
    set_current_session_timeline(timeline)
    try:
        with session_metrics_scope(session_id="progress-edge"):
            current_session_metrics().set_active_plan(plan)
            result = plan_handlers["update_plan"](plan=[{"step": "Inspect", "status": "completed"}])
    finally:
        set_current_session_timeline(None)

    assert result["runtime_plan_done"] is True
    [event] = SessionEventStore(timeline.db_path).read("progress-edge")
    assert event.kind == "plan.completed"
    assert event.payload["changed_step_ids"] == ["s1"]


def test_update_plan_context_survives_executor_thread_bridge(
    plan_handlers: dict[str, Any],
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.agent.tool_executor import ToolExecutor
    from core.observability.session_metrics import current_session_metrics, session_metrics_scope

    plan = Plan(steps=(PlanStep("s1", "Observe", "Observation recorded"),))
    executor = ToolExecutor(
        action_handlers={"update_plan": plan_handlers["update_plan"]},
        auto_approve=True,
    )
    with session_metrics_scope(session_id="progress-thread-bridge"):
        metrics = current_session_metrics()
        metrics.set_active_plan(plan)
        result = asyncio.run(
            executor.aexecute(
                "update_plan",
                {"plan": [{"step": "s1: Observe", "status": "completed"}]},
            )
        )
        assert result["runtime_plan_synced"] is True
        assert metrics.active_plan.done is True


def test_update_plan_rolls_back_when_runtime_checkpoint_fails(
    plan_handlers: dict[str, Any],
) -> None:
    from types import SimpleNamespace

    from core.agent.plan import Plan, PlanStep
    from core.cli.session_state import set_current_loop
    from core.observability.session_metrics import current_session_metrics, session_metrics_scope

    active = Plan(steps=(PlanStep("s1", "Inspect", "Evidence inspected"),))
    loop = SimpleNamespace(_save_checkpoint=lambda *_args, **_kwargs: False)
    set_current_loop(loop)
    try:
        with session_metrics_scope(session_id="progress-checkpoint-fail"):
            metrics = current_session_metrics()
            metrics.set_active_plan(active)
            metrics.replan_attempts_on_current_step = 2
            result = plan_handlers["update_plan"](plan=[{"step": "Inspect", "status": "completed"}])
            assert "checkpoint failed" in result["error"]
            assert metrics.active_plan is active
            assert metrics.replan_attempts_on_current_step == 2
    finally:
        set_current_loop(None)
