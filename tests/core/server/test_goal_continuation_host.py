from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.memory.goals import GoalStore
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.observability.session_metrics import current_session_metrics
from core.orchestration.goal_continuation import GoalContinuationHost
from core.orchestration.lane_queue import LaneQueue, SessionLane
from core.server.supervised.services import SessionMode


class _Loop:
    def __init__(self) -> None:
        self.model = "current-model"
        self.restored: Any = None
        self.updated_model = ""
        self.trigger = ""

    def restore_from_checkpoint(self, state: Any) -> None:
        self.restored = state

    async def update_model_async(self, model: str) -> None:
        self.updated_model = model

    async def acontinue_goal(self, *, trigger: str) -> Any:
        self.trigger = trigger
        return SimpleNamespace(termination_reason="natural")


class _Services:
    def __init__(self, lanes: LaneQueue) -> None:
        self.lane_queue = lanes
        self.created: list[tuple[SessionMode, dict[str, Any], _Loop]] = []
        self.metric_scopes: list[tuple[Any, str]] = []

    def create_session(self, mode: SessionMode, **kwargs: Any) -> tuple[object, _Loop]:
        metrics = current_session_metrics()
        self.metric_scopes.append((metrics, metrics.session_id))
        loop = _Loop()
        self.created.append((mode, kwargs, loop))
        return object(), loop


def _setup(tmp_path: Path, *, session_id: str = "s-goal") -> tuple[Any, ...]:
    checkpoint = SessionCheckpoint(session_dir=tmp_path)
    checkpoint.save(
        SessionState(
            session_id=session_id,
            status="active",
            model="persisted-model",
            messages=[{"role": "user", "content": "original request"}],
        )
    )
    goals = GoalStore(tmp_path / "sessions.db")
    goals.create(session_id, "Finish the durable objective")
    lanes = LaneQueue()
    lanes.set_session_lane(SessionLane(max_sessions=8))
    lanes.add_lane("global", max_concurrent=2)
    services = _Services(lanes)
    host = GoalContinuationHost(
        services,
        checkpoint,
        session_mode=SessionMode.DAEMON,
        time_budget_s=30.0,
        gateway_system_suffix="gateway rules",
        gateway_max_turns=7,
    )
    return host, services, checkpoint, goals, lanes


def test_restart_host_restores_once_and_waits_for_state_change(tmp_path: Path) -> None:
    host, services, _checkpoint, goals, _lanes = _setup(
        tmp_path,
        session_id="s-gw-test",
    )

    assert asyncio.run(host.continue_next_if_idle()) == "s-gw-test"
    mode, kwargs, loop = services.created[0]
    assert mode is SessionMode.DAEMON
    assert kwargs["session_id"] == "s-gw-test"
    assert kwargs["system_suffix"] == "gateway rules"
    assert kwargs["conversation"].max_turns == 7
    assert [
        (message["role"], message["content"]) for message in kwargs["conversation"].messages
    ] == [("user", "original request")]
    assert loop.restored.session_id == "s-gw-test"
    assert loop.updated_model == "persisted-model"
    assert loop.trigger == "serve_idle"

    assert asyncio.run(host.continue_next_if_idle()) is None
    goal = goals.get("s-gw-test")
    assert goal is not None
    goals.account(
        "s-gw-test",
        goal_id=goal.goal_id,
        tokens=1,
        elapsed_seconds=0.1,
    )
    assert asyncio.run(host.continue_next_if_idle()) == "s-gw-test"
    assert len(services.created) == 2
    assert services.metric_scopes[0][1] == "s-gw-test"
    assert services.metric_scopes[0][0] is not services.metric_scopes[1][0]


def test_foreground_lane_defers_hosted_goal(tmp_path: Path) -> None:
    host, services, _checkpoint, _goals, lanes = _setup(tmp_path)

    async def scenario() -> None:
        async with lanes.acquire_all_async("foreground", ["session", "global"]):
            assert await host.continue_next_if_idle() is None
        assert await host.continue_next_if_idle() == "s-goal"

    asyncio.run(scenario())
    assert len(services.created) == 1


def test_missing_or_terminal_checkpoint_is_not_retried(tmp_path: Path) -> None:
    checkpoint = SessionCheckpoint(session_dir=tmp_path)
    goals = GoalStore(tmp_path / "sessions.db")
    goals.create("s-missing", "Do not spin")
    lanes = LaneQueue()
    lanes.set_session_lane(SessionLane(max_sessions=8))
    lanes.add_lane("global", max_concurrent=2)
    services = _Services(lanes)
    host = GoalContinuationHost(
        services,
        checkpoint,
        session_mode=SessionMode.DAEMON,
        time_budget_s=30.0,
    )

    assert asyncio.run(host.continue_next_if_idle()) is None
    assert asyncio.run(host.continue_next_if_idle()) is None
    assert services.created == []

    state_dir = tmp_path / "s-missing"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("{broken", encoding="utf-8")
    goal = goals.get("s-missing")
    assert goal is not None
    goals.account(
        "s-missing",
        goal_id=goal.goal_id,
        tokens=1,
        elapsed_seconds=0.1,
    )
    assert asyncio.run(host.continue_next_if_idle()) is None
    assert services.created == []

    checkpoint.save(SessionState(session_id="s-missing", status="active"))
    checkpoint.mark_completed("s-missing")
    goal = goals.get("s-missing")
    assert goal is not None
    goals.account(
        "s-missing",
        goal_id=goal.goal_id,
        tokens=1,
        elapsed_seconds=0.1,
    )
    assert asyncio.run(host.continue_next_if_idle()) is None
    assert services.created == []


def test_transient_host_failure_retries_same_goal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host, services, _checkpoint, _goals, _lanes = _setup(tmp_path)
    original = services.create_session
    calls = 0

    def flaky_create(mode: SessionMode, **kwargs: Any) -> tuple[object, _Loop]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient setup failure")
        return original(mode, **kwargs)

    monkeypatch.setattr(services, "create_session", flaky_create)

    with pytest.raises(RuntimeError, match="transient setup failure"):
        asyncio.run(host.continue_next_if_idle())
    assert asyncio.run(host.continue_next_if_idle()) == "s-goal"
