from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.agent.cognitive_state_ctx import reset_tool_call_id, set_session_id, set_tool_call_id
from core.cli.tool_handlers.goal import _build_goal_handlers
from core.memory.goals import GoalStore
from core.observability.session_timeline import (
    SessionEventStore,
    SessionTimeline,
    set_current_session_timeline,
)
from core.tools.base import ToolContext


def test_goal_handlers_use_active_session_and_record_control_edges(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    timeline = SessionTimeline("s-goal", db_path=db_path, projection_path=tmp_path / "events.jsonl")
    handlers = _build_goal_handlers(GoalStore(db_path))
    loop = SimpleNamespace(_prompt_dirty=False)
    set_session_id("s-goal")
    set_current_session_timeline(timeline)
    try:
        token = set_tool_call_id("goal-create")
        try:
            created = handlers["create_goal"](
                objective="Ship verified change",
                token_budget=200,
                _tool_context=ToolContext(agent_loop=loop),
            )
        finally:
            reset_tool_call_id(token)
        fetched = handlers["get_goal"]()
        token = set_tool_call_id("goal-complete")
        try:
            completed = handlers["update_goal"](
                status="complete",
                _tool_context=ToolContext(agent_loop=loop),
            )
        finally:
            reset_tool_call_id(token)
    finally:
        set_current_session_timeline(None)
        set_session_id("")

    assert created["goal"]["status"] == "active"
    assert created["goal_status"] == "active"
    assert fetched["goal"]["goal_id"] == created["goal"]["goal_id"]
    assert fetched["goal_status"] == "active"
    assert completed["goal"]["status"] == "complete"
    assert loop._prompt_dirty is True
    events = SessionEventStore(db_path).read("s-goal")
    assert [event.kind for event in events] == ["goal.created", "goal.updated"]
    assert [event.call_id for event in events] == ["goal-create", "goal-complete"]
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


def test_get_goal_reports_explicit_empty_state(tmp_path: Path) -> None:
    handlers = _build_goal_handlers(GoalStore(tmp_path / "sessions.db"))
    set_session_id("s-empty")
    try:
        result = handlers["get_goal"]()
    finally:
        set_session_id("")

    assert result == {"status": "ok", "goal_status": "empty", "goal": None}
