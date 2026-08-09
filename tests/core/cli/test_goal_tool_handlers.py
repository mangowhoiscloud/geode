from __future__ import annotations

from pathlib import Path

from core.agent.cognitive_state_ctx import set_session_id
from core.cli.tool_handlers.goal import _build_goal_handlers
from core.memory.goals import GoalStore
from core.observability.session_timeline import (
    SessionEventStore,
    SessionTimeline,
    set_current_session_timeline,
)


def test_goal_handlers_use_active_session_and_record_control_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    timeline = SessionTimeline("s-goal", db_path=db_path, projection_path=tmp_path / "events.jsonl")
    handlers = _build_goal_handlers(GoalStore(db_path))
    set_session_id("s-goal")
    set_current_session_timeline(timeline)
    try:
        created = handlers["create_goal"](objective="Ship verified change", token_budget=200)
        fetched = handlers["get_goal"]()
        completed = handlers["update_goal"](status="complete")
    finally:
        set_current_session_timeline(None)
        set_session_id("")

    assert created["goal"]["status"] == "active"
    assert fetched["goal"]["goal_id"] == created["goal"]["goal_id"]
    assert completed["goal"]["status"] == "complete"
    events = SessionEventStore(db_path).read("s-goal")
    assert [event.kind for event in events] == ["goal.created", "goal.updated"]
    assert "objective" not in events[0].payload
    assert len(events[0].payload["objective_sha256"]) == 64


def test_update_goal_rejects_model_owned_pause(tmp_path: Path) -> None:
    handlers = _build_goal_handlers(GoalStore(tmp_path / "sessions.db"))
    set_session_id("s-goal")
    try:
        handlers["create_goal"](objective="Persist")
        result = handlers["update_goal"](status="paused")
    finally:
        set_session_id("")

    assert "error" in result
