from __future__ import annotations

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
    monkeypatch.setattr("core.config.settings.plan_auto_execute", False)
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
    assert approved["executed"] is True
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


def test_create_plan_auto_execute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryPlanStore()
    monkeypatch.setattr(tool_handlers, "_PLAN_STORE", store)
    monkeypatch.setattr("core.config.settings.plan_auto_execute", True)
    handlers = _build_plan_handlers(force_dry=True)

    result = handlers["create_plan"](goal="auto run")

    assert result["status"] == "ok"
    assert result["auto_executed"] is True
    assert result["execution_result"]["completed_steps"] == 1


def test_dangerously_skip_permissions_auto_executes_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--dangerously-skip-permissions bypasses the plan-approval stop even when
    ``plan_auto_execute`` is off (plan → action directly)."""
    store = InMemoryPlanStore()
    monkeypatch.setattr(tool_handlers, "_PLAN_STORE", store)
    monkeypatch.setattr("core.config.settings.plan_auto_execute", False)
    monkeypatch.setattr("core.config.settings.dangerously_skip_permissions", True)
    handlers = _build_plan_handlers(force_dry=True)

    result = handlers["create_plan"](goal="skip and run")

    assert result["auto_executed"] is True
    assert result["execution_mode"] == "auto"


def test_no_skip_keeps_plan_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit review checkpoints still stop when auto-execute is disabled."""
    store = InMemoryPlanStore()
    monkeypatch.setattr(tool_handlers, "_PLAN_STORE", store)
    monkeypatch.setattr("core.config.settings.plan_auto_execute", False)
    monkeypatch.setattr("core.config.settings.dangerously_skip_permissions", False)
    handlers = _build_plan_handlers(force_dry=True)

    result = handlers["create_plan"](goal="wait for approval")

    assert result["execution_mode"] == "manual"
    assert "auto_executed" not in result
