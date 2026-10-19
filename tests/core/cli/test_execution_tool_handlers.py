"""schedule_job / trigger_event handlers report real owner outcomes (S1, S5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from core.cli.tool_handlers.execution import _build_execution_handlers
from core.scheduler import SchedulerService
from core.scheduler.triggers import TriggerConfig, TriggerManager, TriggerType


@pytest.fixture
def svc(tmp_path: Path) -> SchedulerService:
    return SchedulerService(
        trigger_manager=TriggerManager(),
        store_path=tmp_path / "scheduled_tasks.json",
        log_dir=tmp_path / "logs",
        on_job_fired=lambda *_args: None,
        enable_jitter=False,
    )


def _handlers(svc: Any) -> dict[str, Any]:
    return dict(_build_execution_handlers(svc))


@pytest.mark.parametrize(
    ("kwargs", "missing"),
    [
        ({"sub_action": "create", "action": "do it"}, ["expression"]),
        ({"sub_action": "create", "expression": "every 5 minutes"}, ["action"]),
        ({"sub_action": "delete"}, ["target_id"]),
        ({"sub_action": "enable"}, ["target_id"]),
        ({"sub_action": "disable"}, ["target_id"]),
        ({"sub_action": "run"}, ["target_id"]),
    ],
)
def test_malformed_schedule_mutation_never_falls_back_to_list(
    svc: SchedulerService, kwargs: dict[str, str], missing: list[str]
) -> None:
    result = _handlers(svc)["schedule_job"](**kwargs)
    assert result.get("status") != "ok"
    assert result["clarification_needed"] is True
    assert result["missing"] == missing
    assert "jobs" not in result and "templates" not in result
    assert svc.list_jobs(include_disabled=True) == []


@pytest.mark.parametrize("sub_action", ["create", "delete", "run", "list"])
def test_missing_scheduler_is_a_dependency_error(sub_action: str) -> None:
    result = _handlers(None)["schedule_job"](
        sub_action=sub_action, target_id="j", expression="every 5 minutes", action="x"
    )
    assert result["status"] == "error"
    assert result["error"] == "Scheduler not available"


def test_unknown_schedule_sub_action_is_rejected(svc: SchedulerService) -> None:
    result = _handlers(svc)["schedule_job"](sub_action="purge")
    assert result["status"] == "error"


def test_schedule_lifecycle_uses_durable_commands(svc: SchedulerService, tmp_path: Path) -> None:
    schedule_job = _handlers(svc)["schedule_job"]
    created = schedule_job(sub_action="create", expression="every 5 minutes", action="ping")
    assert created["status"] == "ok"
    job_id = created["job_id"]
    # Persisted by the command itself, readable by an independent instance.
    other = SchedulerService(store_path=tmp_path / "scheduled_tasks.json", log_dir=tmp_path / "l")
    other.load()
    assert other.get_job(job_id) is not None

    assert schedule_job(sub_action="disable", target_id=job_id)["status"] == "ok"
    status = schedule_job(sub_action="status", target_id=job_id)
    assert status["job"]["enabled"] is False

    run = schedule_job(sub_action="run", target_id=job_id)
    assert run["status"] == "ok" and run["run_status"] == "dispatched" and run["run_id"]
    again = schedule_job(sub_action="run", target_id=job_id)
    assert again["status"] == "error" and again["run_status"] == "skipped"

    assert schedule_job(sub_action="delete", target_id=job_id)["status"] == "ok"
    for sub_action in ("delete", "enable", "run", "status"):
        gone = schedule_job(sub_action=sub_action, target_id=job_id)
        assert gone["status"] == "error", sub_action
        assert "not found" in gone["error"].lower()


def test_trigger_list_and_fire_reach_the_real_manager(svc: SchedulerService) -> None:
    calls: list[dict[str, Any]] = []
    manager = svc.trigger_manager
    assert manager is not None
    manager.register(
        TriggerConfig(trigger_id="nightly", trigger_type=TriggerType.MANUAL, callback=calls.append)
    )
    trigger_event = _handlers(svc)["trigger_event"]

    listed = trigger_event()
    assert listed["status"] == "ok"
    assert [t["trigger_id"] for t in listed["triggers"]] == ["nightly"]

    fired = trigger_event(sub_action="fire", event_name="nightly")
    assert fired["status"] == "ok"
    assert len(calls) == 1
    assert manager.stats.fired == 1


def test_trigger_failures_are_never_ok(svc: SchedulerService) -> None:
    manager = svc.trigger_manager
    assert manager is not None
    manager.register(TriggerConfig(trigger_id="noop", trigger_type=TriggerType.MANUAL))
    manager.register(
        TriggerConfig(
            trigger_id="boom",
            trigger_type=TriggerType.MANUAL,
            callback=lambda _data: 1 / 0,
        )
    )
    manager.register(
        TriggerConfig(
            trigger_id="off",
            trigger_type=TriggerType.MANUAL,
            callback=lambda _data: None,
            enabled=False,
        )
    )
    trigger_event = _handlers(svc)["trigger_event"]
    for name in ("missing", "noop", "boom", "off"):
        result = trigger_event(sub_action="fire", event_name=name)
        assert result["status"] == "error", name
    assert trigger_event(sub_action="fire")["clarification_needed"] is True
    assert trigger_event(sub_action="explode")["status"] == "error"
    assert _handlers(None)["trigger_event"]()["status"] == "error"


def test_composed_tool_plan_wires_the_runtime_trigger_manager(tmp_path: Path) -> None:
    from core.tools.composition import compose_tool_plan

    manager = TriggerManager()
    calls: list[Any] = []
    manager.register(
        TriggerConfig(trigger_id="t", trigger_type=TriggerType.MANUAL, callback=calls.append)
    )
    svc = SchedulerService(
        trigger_manager=manager,
        store_path=tmp_path / "scheduled_tasks.json",
        log_dir=tmp_path / "logs",
    )
    bound, _transient = compose_tool_plan(scheduler_service=svc)
    result = bound.handlers["trigger_event"](sub_action="fire", event_name="t")
    assert result["status"] == "ok"
    assert len(calls) == 1
