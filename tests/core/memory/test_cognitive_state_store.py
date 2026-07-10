"""Tests for the centralized CognitiveStateStore."""

from __future__ import annotations

from core.memory.cognitive_state_store import CognitiveStateStore


def test_save_and_load_latest(tmp_path):
    store = CognitiveStateStore(tmp_path / "sessions.db")
    try:
        store.save_latest("s1", {"goal": "ship", "round_count": 2}, updated_at=10.0)

        snapshot = store.load_latest("s1")

        assert snapshot == {"goal": "ship", "round_count": 2}
    finally:
        store.close()


def test_append_event_updates_latest_and_preserves_event_stream(tmp_path):
    store = CognitiveStateStore(tmp_path / "sessions.db")
    try:
        first_id = store.append_event(
            "s1",
            "cognitive_plan",
            {"goal": "ship", "round_count": 1},
            timestamp=10.0,
        )
        second_id = store.append_event(
            "s1",
            "cognitive_reflect",
            {"goal": "ship", "round_count": 2, "confidence": 0.7},
            timestamp=11.0,
        )

        assert first_id > 0
        assert second_id > first_id
        assert store.load_latest("s1") == {
            "goal": "ship",
            "round_count": 2,
            "confidence": 0.7,
        }
        events = store.recent_events("s1")
        assert [event.phase for event in events] == ["cognitive_reflect", "cognitive_plan"]
        assert events[0].snapshot["confidence"] == 0.7
        assert store.event_count("s1") == 2
    finally:
        store.close()


def test_bootstrap_cognitive_hook_records_to_store(tmp_path, monkeypatch):
    from core.hooks.system import HookEvent
    from core.wiring.bootstrap import build_hooks

    db_path = tmp_path / "sessions.db"
    monkeypatch.setattr("core.memory.session_manager._get_default_db_path", lambda: db_path)

    hooks, _event_store, _metrics = build_hooks(
        session_key="test-session",
        run_id="run-1",
        log_dir=tmp_path / "logs",
    )

    hooks.trigger(
        HookEvent.COGNITIVE_PLAN,
        {"session_id": "s1", "cognitive_state": {"goal": "centralize"}},
    )

    store = CognitiveStateStore(db_path)
    try:
        assert store.load_latest("s1") == {"goal": "centralize"}
        events = store.recent_events("s1")
        assert len(events) == 1
        assert events[0].phase == "cognitive_plan"
    finally:
        store.close()
