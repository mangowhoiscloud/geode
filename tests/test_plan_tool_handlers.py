from __future__ import annotations

from typing import Any

import pytest
from core.cli.tool_handlers.plan import _build_plan_handlers

from core.cli import tool_handlers


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
