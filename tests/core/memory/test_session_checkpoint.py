"""Tests for SessionCheckpoint — C3 layer session persistence."""

from __future__ import annotations

import time

from core.memory.session_checkpoint import (
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
        assert state.cognitive_state == {}


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

    def test_cognitive_state_snapshot_saved_and_loaded(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        cognitive_state = {
            "goal": "understand loop",
            "subgoals": ["inspect checkpoint"],
            "observations": ["tools: read -> 1 tool result(s)"],
            "hypotheses": ["checkpoint should be resume SoT"],
            "confidence": 0.82,
            "last_action": "tools: read",
            "last_observation": "1 tool result(s)",
            "round_count": 3,
        }
        cp.save(SessionState(session_id="cog-1", cognitive_state=cognitive_state))

        loaded = cp.load("cog-1")

        assert loaded is not None
        assert loaded.cognitive_state == cognitive_state

    def test_cognitive_state_load_prefers_db_over_json_cache(self, tmp_path):
        from core.memory.cognitive_state_store import CognitiveStateStore

        root = tmp_path / "session"
        cp = SessionCheckpoint(root)
        cp.save(SessionState(session_id="cog-db", cognitive_state={"goal": "json"}))

        store = CognitiveStateStore(root / "sessions.db")
        try:
            store.save_latest("cog-db", {"goal": "db"}, updated_at=123.0)
        finally:
            store.close()

        loaded = cp.load("cog-db")

        assert loaded is not None
        assert loaded.cognitive_state == {"goal": "db"}

    def test_legacy_checkpoint_without_cognitive_state_loads_empty_snapshot(self, tmp_path):
        import json

        session_dir = tmp_path / "session" / "legacy-cog"
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(
            json.dumps({"session_id": "legacy-cog", "status": "active"}),
            encoding="utf-8",
        )

        cp = SessionCheckpoint(tmp_path / "session")
        loaded = cp.load("legacy-cog")

        assert loaded is not None
        assert loaded.cognitive_state == {}

    def test_load_nonexistent(self, tmp_path):
        cp = SessionCheckpoint(tmp_path / "session")
        assert cp.load("nonexistent") is None

    def test_no_trim_full_history_preserved(self, tmp_path):
        """Phase 1b — JSON trim removed. The SoT is now the SQLite
        ``messages`` table which holds the *full* conversation, and the
        JSON hot cache is also kept untrimmed so old offline tooling still
        works on long sessions."""
        cp = SessionCheckpoint(tmp_path / "session")
        messages = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        state = SessionState(session_id="trim-test", messages=messages)
        cp.save(state)

        loaded = cp.load("trim-test")
        assert loaded is not None
        assert len(loaded.messages) == 50, "full history must survive — no trim"
        # Both the first and last message survive (in-order).
        assert loaded.messages[0]["content"] == "msg 0"
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

    def test_computer_screenshots_are_omitted_from_checkpoint_cache(self, tmp_path):
        import json

        cp = SessionCheckpoint(tmp_path / "session")
        state = SessionState(
            session_id="computer-redact",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu1",
                            "content": [
                                {"type": "text", "text": '{"result":"success"}'},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": "BASE64DATA",
                                    },
                                },
                            ],
                        }
                    ],
                }
            ],
            tool_log=[
                {
                    "tool": "computer",
                    "result": {
                        "result": "success",
                        "screenshot": "BASE64DATA",
                        "observation": {"screenshot_sha256": "abc"},
                    },
                }
            ],
        )

        cp.save(state)

        session_dir = tmp_path / "session" / "computer-redact"
        messages_raw = (session_dir / "messages.json").read_text(encoding="utf-8")
        tools_raw = (session_dir / "tools.json").read_text(encoding="utf-8")
        assert "BASE64DATA" not in messages_raw
        assert "BASE64DATA" not in tools_raw
        assert "screenshot_omitted" in tools_raw
        assert "image_omitted" in messages_raw

        loaded = cp.load("computer-redact")
        assert loaded is not None
        assert "BASE64DATA" not in json.dumps(
            {"messages": loaded.messages, "tool_log": loaded.tool_log}
        )
        assert loaded.tool_log[0]["result"]["screenshot_omitted"] is True

    def test_personal_tool_inputs_and_results_are_omitted_everywhere(self, tmp_path):
        import json

        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(
            SessionState(
                session_id="personal-redact",
                messages=[
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "google-call",
                                "name": "gmail_search",
                                "input": {"query": "from:private@example.com"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "google-call",
                                "content": "private mailbox body",
                            }
                        ],
                    },
                ],
                tool_log=[
                    {
                        "tool": "gmail_search",
                        "input": {"query": "from:private@example.com"},
                        "result": {"messages": [{"body": "private mailbox body"}]},
                    }
                ],
            )
        )

        session_dir = tmp_path / "session" / "personal-redact"
        persisted = (
            (session_dir / "messages.json").read_text(encoding="utf-8")
            + (session_dir / "tools.json").read_text(encoding="utf-8")
            + (tmp_path / "session" / "sessions.db").read_bytes().decode("utf-8", errors="ignore")
        )
        assert "private@example.com" not in persisted
        assert "private mailbox body" not in persisted
        assert "_personal_data_omitted" in persisted

        loaded = cp.load("personal-redact")
        assert loaded is not None
        restored = json.dumps({"messages": loaded.messages, "tool_log": loaded.tool_log})
        assert "private@example.com" not in restored
        assert "private mailbox body" not in restored
        assert "_personal_data_omitted" in restored


class TestPhase1bDbFirst:
    """Phase 1b — load() reads messages from the SQLite SoT first; JSON is a
    fallback for pre-migration sessions and dual-write race losers."""

    def test_load_reads_messages_from_db_after_save(self, tmp_path):
        """Round-trsubject: save() writes to DB, load() reads from DB."""
        cp = SessionCheckpoint(tmp_path / "session")
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        cp.save(SessionState(session_id="db-1", messages=messages))

        loaded = cp.load("db-1")
        assert loaded is not None
        assert len(loaded.messages) == 2
        contents = [m["content"] for m in loaded.messages]
        assert contents == ["hello", "world"]

    def test_load_falls_back_to_json_when_db_empty(self, tmp_path):
        """Pre-Phase-1a sessions only have ``messages.json``. The DB-first
        load() must transparently fall back to the JSON cache so legacy
        sessions keep resuming when no DB exists yet."""
        import json

        session_dir = tmp_path / "session" / "legacy-1"
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(
            json.dumps({"session_id": "legacy-1", "status": "active"}),
            encoding="utf-8",
        )
        (session_dir / "messages.json").write_text(
            json.dumps([{"role": "user", "content": "from json only"}]),
            encoding="utf-8",
        )

        cp = SessionCheckpoint(tmp_path / "session")
        loaded = cp.load("legacy-1")
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0]["content"] == "from json only"

    def test_load_falls_back_to_json_when_existing_db_has_no_session_rows(self, tmp_path):
        """Legacy sessions can share a project DB with newer sessions. An
        empty row set for a session unknown to the DB must still fall back
        to ``messages.json``."""
        import json

        from core.memory.session_manager import SessionManager

        root = tmp_path / "session"
        mgr = SessionManager(db_path=root / "sessions.db")
        try:
            mgr.upsert_messages("other-session", [{"role": "user", "content": "db"}])
        finally:
            mgr.close()

        session_dir = root / "legacy-2"
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(
            json.dumps({"session_id": "legacy-2", "status": "active"}),
            encoding="utf-8",
        )
        (session_dir / "messages.json").write_text(
            json.dumps([{"role": "user", "content": "legacy json"}]),
            encoding="utf-8",
        )

        cp = SessionCheckpoint(root)
        loaded = cp.load("legacy-2")
        assert loaded is not None
        assert [m["content"] for m in loaded.messages] == ["legacy json"]

    def test_empty_db_result_does_not_resurrect_stale_json(self, tmp_path):
        """If a DB-first empty save succeeds and the later JSON cache write
        fails, load() must treat the empty DB row set as authoritative."""
        import json

        from core.memory.session_manager import SessionManager

        root = tmp_path / "session"
        cp = SessionCheckpoint(root)
        cp.save(
            SessionState(
                session_id="empty-now",
                messages=[{"role": "user", "content": "stale json"}],
            )
        )

        state_file = root / "empty-now" / "state.json"
        msg_file = root / "empty-now" / "messages.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["updated_at"] = time.time() + 60
        state_file.write_text(json.dumps(data), encoding="utf-8")

        mgr = SessionManager(db_path=root / "sessions.db")
        try:
            mgr.upsert_messages("empty-now", [])
            assert mgr.count_messages("empty-now") == 0
        finally:
            mgr.close()
        assert "stale json" in msg_file.read_text(encoding="utf-8")

        loaded = cp.load("empty-now")
        assert loaded is not None
        assert loaded.messages == []

    def test_save_writes_to_db_before_json_so_db_is_authoritative(self, tmp_path):
        """Phase 1b SoT contract — when save() returns, the DB row count
        for the session matches the in-memory message count, regardless
        of whether the JSON write succeeded or not."""
        cp = SessionCheckpoint(tmp_path / "session")
        cp.save(SessionState(session_id="sot-1", messages=[{"role": "user", "content": "x"}]))

        from core.memory.session_manager import SessionManager

        mgr = SessionManager(db_path=tmp_path / "session" / "sessions.db")
        try:
            assert mgr.count_messages("sot-1") == 1
        finally:
            mgr.close()
