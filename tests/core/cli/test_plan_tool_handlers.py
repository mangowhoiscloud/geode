from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from core.cli import tool_handlers
from core.cli.tool_handlers.plan import _build_plan_handlers


class InMemoryPlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, Any] = {}
        self._order: list[str] = []

    def put(self, plan: Any) -> None:
        if plan.plan_id not in self._plans:
            self._order.append(plan.plan_id)
        self._plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> Any | None:
        return self._plans.get(plan_id)

    def keys(self) -> list[str]:
        return list(self._order)

    def list_all(self) -> list[Any]:
        return [self._plans[key] for key in self._order]

    def __len__(self) -> int:
        return len(self._plans)


@pytest.fixture
def plan_handlers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store = InMemoryPlanStore()
    monkeypatch.setattr(tool_handlers, "_PLAN_STORE", store)
    return _build_plan_handlers(force_dry=True)


def test_create_plan_requires_goal_or_subject(plan_handlers: dict[str, Any]) -> None:
    result = plan_handlers["create_plan"]()

    assert result["clarification_needed"] is True
    assert result["missing"] == ["goal"]


def test_update_plan_is_non_persistent_progress_surface(
    plan_handlers: dict[str, Any],
) -> None:
    result = plan_handlers["update_plan"](
        explanation="repo change",
        plan=[
            {"step": "Inspect plan UX", "status": "completed"},
            {"step": "Patch router prompt", "status": "in_progress"},
            {"step": "Run focused tests", "status": "pending"},
        ],
    )

    assert result["status"] == "ok"
    assert result["action"] == "update_plan"
    assert result["counts"] == {"pending": 1, "in_progress": 1, "completed": 1}
    assert (
        result["hint"] == "Progress plan updated. Continue with the task; no approval is required."
    )

    listed = plan_handlers["list_plans"]()
    assert listed["count"] == 0


def test_update_plan_rejects_unknown_status(plan_handlers: dict[str, Any]) -> None:
    result = plan_handlers["update_plan"](
        plan=[{"step": "Patch", "status": "blocked"}],
    )

    assert "Invalid plan status" in result["error"]


def test_update_plan_keeps_non_linear_checklist_display_only(
    plan_handlers: dict[str, Any],
) -> None:
    result = plan_handlers["update_plan"](
        plan=[
            {"step": "Inspect", "status": "pending"},
            {"step": "Patch", "status": "pending"},
        ],
    )

    assert result["status"] == "ok"
    assert result["runtime_plan_synced"] is False


def test_update_plan_advances_matching_runtime_advisory_plan(
    plan_handlers: dict[str, Any],
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import (
        current_session_metrics,
        session_metrics_scope,
    )

    plan = Plan(
        steps=(
            PlanStep(id="s1", description="Inspect plan wiring"),
            PlanStep(id="s2", description="Patch shared boundary"),
            PlanStep(id="s3", description="Run focused tests"),
        )
    )
    with session_metrics_scope(session_id="progress-sync"):
        metrics = current_session_metrics()
        metrics.set_active_plan(plan)
        metrics.record_step_attempt()

        result = plan_handlers["update_plan"](
            plan=[
                {"step": "Inspect plan wiring", "status": "completed"},
                {"step": "Patch shared boundary", "status": "in_progress"},
                {"step": "Run focused tests", "status": "pending"},
            ],
        )

        assert result["runtime_plan_synced"] is True
        assert result["runtime_plan_advanced"] is True
        assert result["runtime_plan_current"] == 1
        assert result["runtime_plan_id"] == plan.plan_id
        assert result["runtime_plan_revision"] == 0
        assert result["runtime_plan_done"] is False
        assert metrics.active_plan.current == 1
        assert metrics.active_plan.completed == (0,)
        assert metrics.replan_attempts_on_current_step == 0

        completed = plan_handlers["update_plan"](
            plan=[
                {"step": "Inspect plan wiring", "status": "completed"},
                {"step": "Patch shared boundary", "status": "completed"},
                {"step": "Run focused tests", "status": "completed"},
            ],
        )
        assert completed["runtime_plan_synced"] is True
        assert completed["runtime_plan_advanced"] is True
        assert metrics.active_plan.done is True
        assert metrics.active_plan.completed == (0, 1, 2)
        assert completed["runtime_plan_done"] is True


def test_update_plan_records_observed_progress_edge(
    plan_handlers: dict[str, Any],
    tmp_path: Path,
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import (
        current_session_metrics,
        session_metrics_scope,
    )
    from core.observability.session_timeline import (
        SessionEventStore,
        SessionTimeline,
        set_current_session_timeline,
    )

    plan = Plan(steps=(PlanStep(id="s1", description="Inspect evidence"),))
    timeline = SessionTimeline("progress-edge", db_path=tmp_path / "sessions.db")
    set_current_session_timeline(timeline)
    try:
        with session_metrics_scope(session_id="progress-edge"):
            current_session_metrics().set_active_plan(plan)
            result = plan_handlers["update_plan"](
                plan=[{"step": "Inspect evidence", "status": "completed"}],
            )
    finally:
        set_current_session_timeline(None)

    assert result["runtime_plan_done"] is True
    [event] = SessionEventStore(timeline.db_path).read("progress-edge")
    assert event.kind == "plan.completed"
    assert event.payload["plan_id"] == plan.plan_id
    assert event.payload["changed_step_ids"] == ["s1"]


def test_update_plan_keeps_different_checklist_display_only(
    plan_handlers: dict[str, Any],
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.observability.session_metrics import (
        current_session_metrics,
        session_metrics_scope,
    )

    plan = Plan(steps=(PlanStep(id="s1", description="Internal step"),))
    with session_metrics_scope(session_id="progress-mismatch"):
        metrics = current_session_metrics()
        metrics.set_active_plan(plan)

        result = plan_handlers["update_plan"](
            plan=[{"step": "Visible-only step", "status": "in_progress"}],
        )

        assert result["runtime_plan_synced"] is False
        assert result["runtime_plan_advanced"] is False
        assert metrics.active_plan is plan


def test_update_plan_runtime_sync_survives_tool_executor_thread_bridge(
    plan_handlers: dict[str, Any],
) -> None:
    from core.agent.plan import Plan, PlanStep
    from core.agent.tool_executor import ToolExecutor
    from core.observability.session_metrics import (
        current_session_metrics,
        session_metrics_scope,
    )

    plan = Plan(steps=(PlanStep(id="s1", description="Observe completion"),))
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
                {"plan": [{"step": "s1: Observe completion", "status": "completed"}]},
            )
        )

        assert result["runtime_plan_synced"] is True
        assert metrics.active_plan.done is True
        assert metrics.active_plan.completed == (0,)


def test_create_list_approve_and_latest_fallback(plan_handlers: dict[str, Any]) -> None:
    created = plan_handlers["create_plan"](goal="ship release", steps=["build", "test"])

    assert created["status"] == "ok"
    assert created["action"] == "plan"
    assert created["step_count"] == 2

    listed = plan_handlers["list_plans"]()
    assert listed["count"] == 1
    assert listed["plans"][0]["plan_id"] == created["plan_id"]

    approved = plan_handlers["approve_plan"]()
    assert approved["status"] == "ok"
    assert approved["approved"] is True
    assert approved["executed"] is False
    assert approved["checkpoint_status"] == "approved"
    assert approved["plan_id"] == created["plan_id"]


def test_reject_modify_and_missing_plan_paths(plan_handlers: dict[str, Any]) -> None:
    assert plan_handlers["reject_plan"]()["error"] == "No plan to reject."
    assert plan_handlers["modify_plan"]()["error"] == "No plan to modify."

    created = plan_handlers["create_plan"](subject="subject-1", steps=["one", "two"])
    modified = plan_handlers["modify_plan"](
        plan_id=created["plan_id"],
        remove_steps=["step_1"],
    )
    rejected = plan_handlers["reject_plan"](plan_id=created["plan_id"], reason="pause")

    assert modified["status"] == "ok"
    assert modified["step_count"] == 1
    assert rejected == {
        "status": "ok",
        "action": "reject_plan",
        "plan_id": created["plan_id"],
        "reason": "pause",
    }


def test_dangerously_skip_permissions_does_not_fabricate_plan_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryPlanStore()
    monkeypatch.setattr(tool_handlers, "_PLAN_STORE", store)
    monkeypatch.setattr("core.config.settings.dangerously_skip_permissions", True)
    handlers = _build_plan_handlers(force_dry=True)

    result = handlers["create_plan"](goal="review before proceeding")

    assert result["checkpoint_status"] == "presented"
    assert result["approved"] is False
    assert result["executed"] is False
    assert "auto_executed" not in result
