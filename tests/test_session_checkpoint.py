"""Tests for SessionCheckpoint — C3 layer session persistence."""

from __future__ import annotations

import time

from core.cli.session_checkpoint import (
    CHECKPOINT_MAX_MESSAGES,
    SessionCheckpoint,
    SessionState,
)


class TestSessionState:
    def test_default_values(self):
        state = SessionState(session_id="s1")
        assert state.status == "active"
        assert state.provider == "anthropic"
        assert state.round_idx == 0
        assert state.messages == []


class TestSessionCheckpoint:
    def test_save_and_load(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        state = SessionState(
            session_id="test-1",
            model="claude-opus-4-6",
            round_idx=3,
            messages=[{"role": "user", "content": "hello"}],
            user_input="hello",
        )
        cp.save(state)

        loaded = cp.load("test-1")
        assert loaded is not None
        assert loaded.session_id == "test-1"
        assert loaded.model == "claude-opus-4-6"
        assert loaded.round_idx == 3
        assert len(loaded.messages) == 1
        assert loaded.user_input == "hello"

    def test_load_nonexistent(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        assert cp.load("nonexistent") is None

    def test_message_trimming(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        state = SessionState(session_id="trim-test", messages=messages)
        cp.save(state)

        loaded = cp.load("trim-test")
        assert loaded is not None
        assert len(loaded.messages) == CHECKPOINT_MAX_MESSAGES
        # Should keep most recent
        assert loaded.messages[-1]["content"] == "msg 49"

    def test_mark_completed(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        state = SessionState(session_id="done-test")
        cp.save(state)
        cp.mark_completed("done-test")

        loaded = cp.load("done-test")
        assert loaded is not None
        assert loaded.status == "completed"

    def test_list_resumable(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="active-1", status="active"))
        cp.save(SessionState(session_id="paused-1", status="paused"))
        cp.save(SessionState(session_id="done-1", status="completed"))

        resumable = cp.list_resumable()
        ids = [s.session_id for s in resumable]
        assert "active-1" in ids
        assert "paused-1" in ids
        assert "done-1" not in ids

    def test_cleanup_completed(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="keep"))
        cp.save(SessionState(session_id="remove"))
        cp.mark_completed("remove")

        removed = cp.cleanup()
        assert removed == 1
        assert cp.load("keep") is not None
        assert cp.load("remove") is None

    def test_cleanup_old(self, tmp_path):
        import json

        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="old"))
        # Manually backdate the checkpoint
        state_file = tmp_path / "session" / "old" / "state.json"
        data = json.loads(state_file.read_text())
        data["updated_at"] = time.time() - 100 * 3600  # 100h ago
        state_file.write_text(json.dumps(data))

        removed = cp.cleanup(max_age_hours=72)
        assert removed == 1

    def test_active_json_pointer(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="s1"))

        active_file = tmp_path / "session" / "active.json"
        assert active_file.exists()

        import json

        data = json.loads(active_file.read_text())
        assert data["session_id"] == "s1"

    def test_active_cleared_on_complete(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="s1"))
        cp.mark_completed("s1")

        active_file = tmp_path / "session" / "active.json"
        assert not active_file.exists()

    def test_overwrite_checkpoint(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="s1", round_idx=1))
        cp.save(SessionState(session_id="s1", round_idx=5))

        loaded = cp.load("s1")
        assert loaded is not None
        assert loaded.round_idx == 5

    def test_tool_log_saved(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        state = SessionState(
            session_id="tools-test",
            tool_log=[{"name": "search", "result": "ok"}],
        )
        cp.save(state)

        loaded = cp.load("tools-test")
        assert loaded is not None
        assert len(loaded.tool_log) == 1
        assert loaded.tool_log[0]["name"] == "search"
