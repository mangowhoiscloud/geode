"""Tests for GAP 3: SessionManager (SQLite session index)."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from core.memory.session_manager import SessionManager, SessionMeta


@pytest.fixture()
def mgr(tmp_path: Path) -> SessionManager:
    db = tmp_path / "sessions.db"
    m = SessionManager(db_path=db)
    yield m  # type: ignore[misc]
    m.close()


@pytest.mark.parametrize("failure", ["pragma", "schema"])
def test_constructor_closes_connection_when_initialization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    opened: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def authorize(action: int, arg1: str | None, *_args: object) -> int:
        if (failure == "pragma" and action == sqlite3.SQLITE_PRAGMA and arg1 == "journal_mode") or (
            failure == "schema" and action == sqlite3.SQLITE_CREATE_TABLE and arg1 == "sessions"
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = original_connect(*args, **kwargs)
        conn.set_authorizer(authorize)
        opened.append(conn)
        return conn

    monkeypatch.setattr("core.memory.session_manager.sqlite3.connect", connect)
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        SessionManager(tmp_path / "failed.db")
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def _make_meta(
    session_id: str = "s1",
    status: str = "active",
    **kwargs: object,
) -> SessionMeta:
    now = time.time()
    return SessionMeta(
        session_id=session_id,
        created_at=kwargs.get("created_at", now),  # type: ignore[arg-type]
        updated_at=kwargs.get("updated_at", now),  # type: ignore[arg-type]
        status=status,
        model=kwargs.get("model", "claude-opus-4-6"),  # type: ignore[arg-type]
        provider=kwargs.get("provider", "anthropic"),  # type: ignore[arg-type]
        user_input=kwargs.get("user_input", "test input"),  # type: ignore[arg-type]
        round_count=kwargs.get("round_count", 3),  # type: ignore[arg-type]
        message_count=kwargs.get("message_count", 10),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("method", "args", "kwargs"),
    [
        ("get", ("s1",), {}),
        ("list_sessions", (), {}),
        ("list_sessions", (), {"status": "active"}),
        ("get_messages", ("s1",), {}),
        ("count_messages", ("s1",), {}),
        ("search_messages", ("context",), {}),
        ("list_context_artifacts", (), {}),
        ("search_context_artifacts", ("context",), {}),
        ("close", (), {}),
    ],
)
def test_reads_and_close_hold_connection_lock_through_fetch(
    mgr: SessionManager,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    """Guard the entire execute/fetch lifetime, not merely connection creation."""
    mgr.upsert(_make_meta())
    mgr.upsert_messages("s1", [{"role": "user", "content": "context", "seq": 0}])
    mgr.upsert_context_artifact(session_id="s1", kind="dream", content="context")
    connection = mgr._conn

    def locked_call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        assert mgr._lock.locked(), "shared connection operation is not serialized"
        return function(*args, **kwargs)

    def execute(*args: Any, **kwargs: Any) -> Mock:
        cursor = locked_call(connection.execute, *args, **kwargs)
        wrapped = Mock(wraps=cursor)
        for name in ("fetchone", "fetchall"):
            getattr(wrapped, name).side_effect = partial(locked_call, getattr(cursor, name))
        return wrapped

    wrapped = Mock(wraps=connection)
    wrapped.execute.side_effect = execute
    wrapped.close.side_effect = partial(locked_call, connection.close)
    with monkeypatch.context() as patch:
        patch.setattr(mgr, "_conn", wrapped)
        getattr(mgr, method)(*args, **kwargs)


class TestSessionManagerCRUD:
    """Basic CRUD operations."""

    def test_upsert_and_get(self, mgr: SessionManager) -> None:
        meta = _make_meta("s1")
        mgr.upsert(meta)
        loaded = mgr.get("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.status == "active"
        assert loaded.model == "claude-opus-4-6"

    def test_get_nonexistent_returns_none(self, mgr: SessionManager) -> None:
        assert mgr.get("nonexistent") is None

    def test_upsert_updates_existing(self, mgr: SessionManager) -> None:
        meta = _make_meta("s1", round_count=1)
        mgr.upsert(meta)

        updated = _make_meta("s1", round_count=5)
        mgr.upsert(updated)

        loaded = mgr.get("s1")
        assert loaded is not None
        assert loaded.round_count == 5

    def test_delete(self, mgr: SessionManager) -> None:
        mgr.upsert(_make_meta("s1"))
        assert mgr.delete("s1") is True
        assert mgr.get("s1") is None

    def test_delete_nonexistent(self, mgr: SessionManager) -> None:
        assert mgr.delete("nope") is False


class TestSessionManagerList:
    """list_sessions() query behavior."""

    def test_list_all(self, mgr: SessionManager) -> None:
        now = time.time()
        mgr.upsert(_make_meta("s1", updated_at=now - 10))
        mgr.upsert(_make_meta("s2", updated_at=now))
        mgr.upsert(_make_meta("s3", status="completed", updated_at=now - 5))

        result = mgr.list_sessions()
        assert len(result) == 3
        # Most recent first
        assert result[0].session_id == "s2"

    def test_list_by_status(self, mgr: SessionManager) -> None:
        mgr.upsert(_make_meta("s1", status="active"))
        mgr.upsert(_make_meta("s2", status="completed"))
        mgr.upsert(_make_meta("s3", status="active"))

        active = mgr.list_sessions(status="active")
        assert len(active) == 2
        assert all(s.status == "active" for s in active)

    def test_list_with_limit(self, mgr: SessionManager) -> None:
        for i in range(10):
            mgr.upsert(_make_meta(f"s{i}", updated_at=time.time() + i))
        result = mgr.list_sessions(limit=3)
        assert len(result) == 3


class TestSessionManagerCleanup:
    """cleanup() removes old/completed sessions."""

    def test_cleanup_removes_completed(self, mgr: SessionManager) -> None:
        mgr.upsert(_make_meta("s1", status="completed"))
        mgr.upsert(_make_meta("s2", status="active"))
        removed = mgr.cleanup()
        assert removed == 1
        assert mgr.get("s1") is None
        assert mgr.get("s2") is not None

    def test_cleanup_removes_old(self, mgr: SessionManager) -> None:
        old_time = time.time() - (100 * 3600)  # 100 hours ago
        mgr.upsert(_make_meta("s1", status="active", updated_at=old_time))
        mgr.upsert(_make_meta("s2", status="active"))
        removed = mgr.cleanup(max_age_hours=72)
        assert removed == 1
        assert mgr.get("s1") is None
        assert mgr.get("s2") is not None


class TestSessionCheckpointIntegration:
    """SessionCheckpoint.save() syncs to SQLite index."""

    def test_save_creates_index_entry(self, tmp_path: Path) -> None:
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        state = SessionState(
            session_id="test-session",
            model="claude-opus-4-6",
            provider="anthropic",
            user_input="hello world",
            round_idx=2,
            messages=[{"role": "user", "content": "hi"}],
        )
        cp.save(state)

        # Verify SQLite index was created
        db_path = tmp_path / "session" / "sessions.db"
        assert db_path.exists()

        mgr = SessionManager(db_path=db_path)
        meta = mgr.get("test-session")
        assert meta is not None
        assert meta.model == "claude-opus-4-6"
        assert meta.user_input == "hello world"
        assert meta.round_count == 2
        mgr.close()


class TestMessagesTable:
    """Phase 1a — messages table CRUD + idempotent upsert."""

    def test_messages_schema_and_indexes(self, mgr: SessionManager) -> None:
        cols = {row[1] for row in mgr._conn.execute("PRAGMA table_info(messages)").fetchall()}
        assert cols == {
            "id",
            "session_id",
            "seq",
            "role",
            "content",
            "tool_call_id",
            "tool_calls",
            "tool_name",
            "timestamp",
            "token_count",
            "finish_reason",
            "reasoning",
            "metadata",
        }
        index_names = {
            row[1]
            for row in mgr._conn.execute(
                "SELECT * FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_messages_session" in index_names
        assert "idx_messages_tool_name" in index_names

    def test_upsert_round_trip_string_content(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )
        loaded = mgr.get_messages("s1")
        assert [m["seq"] for m in loaded] == [0, 1]
        assert [m["role"] for m in loaded] == ["user", "assistant"]
        assert [m["content"] for m in loaded] == ["hi", "hello"]
        assert all("timestamp" in m for m in loaded)

    def test_upsert_round_trip_tool_use(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "search",
                            "input": {"q": "foo"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "content": "ok",
                        }
                    ],
                },
            ],
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["tool_name"] == "search"
        assert isinstance(loaded[0]["tool_calls"], list)
        assert loaded[0]["tool_calls"][0]["name"] == "search"
        assert loaded[1]["tool_call_id"] == "tu_1"

    def test_upsert_round_trip_thinking_block(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "let me think"},
                        {"type": "text", "text": "answer"},
                    ],
                }
            ],
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["reasoning"] == "let me think"

    def test_upsert_round_trip_openai_tool_calls(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "search",
                    "content": "result",
                },
            ],
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["tool_name"] == "search"
        assert loaded[0]["tool_calls"][0]["function"]["name"] == "search"
        assert loaded[0]["content"] is None
        assert loaded[1]["tool_call_id"] == "call_1"
        assert loaded[1]["tool_name"] == "search"

    def test_upsert_is_idempotent(self, mgr: SessionManager) -> None:
        msgs = [{"role": "user", "content": "first"}]
        mgr.upsert_messages("s1", msgs)
        mgr.upsert_messages("s1", msgs)
        assert mgr.count_messages("s1") == 1

    def test_upsert_overlapping_prefix_replaces(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [{"role": "user", "content": "a"}],
        )
        mgr.upsert_messages(
            "s1",
            [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ],
        )
        loaded = mgr.get_messages("s1")
        assert [m["content"] for m in loaded] == ["a", "b"]

    def test_upsert_shorter_list_removes_stale_rows(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"},
            ],
        )
        mgr.upsert_messages("s1", [{"role": "user", "content": "a"}])

        loaded = mgr.get_messages("s1")
        assert [m["content"] for m in loaded] == ["a"]
        assert mgr.count_messages("s1") == 1

    def test_upsert_corrects_edited_message(self, mgr: SessionManager) -> None:
        mgr.upsert_messages("s1", [{"role": "user", "content": "wrong"}])
        mgr.upsert_messages("s1", [{"role": "user", "content": "right"}])
        loaded = mgr.get_messages("s1")
        assert loaded[0]["content"] == "right"

    def test_upsert_skips_non_dict(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {"role": "user", "content": "ok"},
                "garbage",  # type: ignore[list-item]
                None,  # type: ignore[list-item]
            ],
        )
        loaded = mgr.get_messages("s1")
        assert len(loaded) == 1

    def test_per_session_isolation(self, mgr: SessionManager) -> None:
        mgr.upsert_messages("s1", [{"role": "user", "content": "a"}])
        mgr.upsert_messages("s2", [{"role": "user", "content": "b"}])
        assert mgr.count_messages("s1") == 1
        assert mgr.count_messages("s2") == 1
        assert mgr.get_messages("s1")[0]["content"] == "a"

    def test_delete_messages(self, mgr: SessionManager) -> None:
        mgr.upsert_messages("s1", [{"role": "user", "content": "x"}])
        assert mgr.delete_messages("s1") == 1
        assert mgr.count_messages("s1") == 0

    def test_default_timestamp_applied(self, mgr: SessionManager) -> None:
        ts = 1234567890.0
        mgr.upsert_messages(
            "s1",
            [{"role": "user", "content": "x"}],
            default_timestamp=ts,
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["timestamp"] == ts

    def test_per_message_timestamp_wins(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [{"role": "user", "content": "x", "timestamp": 42.0}],
            default_timestamp=999.0,
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["timestamp"] == 42.0

    def test_metadata_round_trip(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [{"role": "user", "content": "x", "metadata": {"tag": "demo"}}],
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["metadata"] == {"tag": "demo"}

    def test_finish_reason_and_token_count(self, mgr: SessionManager) -> None:
        mgr.upsert_messages(
            "s1",
            [
                {
                    "role": "assistant",
                    "content": "done",
                    "finish_reason": "stop",
                    "token_count": 42,
                }
            ],
        )
        loaded = mgr.get_messages("s1")
        assert loaded[0]["finish_reason"] == "stop"
        assert loaded[0]["token_count"] == 42


class TestSessionCheckpointDualWrite:
    """Phase 1a — SessionCheckpoint.save() mirrors messages into DB."""

    def test_save_mirrors_messages_to_db(self, tmp_path: Path) -> None:
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        state = SessionState(
            session_id="dual-1",
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )
        cp.save(state)

        db = tmp_path / "session" / "sessions.db"
        mgr = SessionManager(db_path=db)
        try:
            loaded = mgr.get_messages("dual-1")
            assert [m["content"] for m in loaded] == ["hi", "hello"]
        finally:
            mgr.close()

    def test_save_dual_write_keeps_json_when_db_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON checkpoint survives even when the DB mirror raises."""
        from core.memory import session_manager as _sm_mod
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        def _boom(self, *_a: object, **_kw: object) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr(_sm_mod.SessionManager, "upsert_messages", _boom)

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        state = SessionState(
            session_id="dual-fail",
            messages=[{"role": "user", "content": "still here"}],
        )
        cp.save(state)  # must not raise

        loaded_state = cp.load("dual-fail")
        assert loaded_state is not None
        assert loaded_state.messages == [{"role": "user", "content": "still here"}]

    def test_save_round_idempotent_against_db(self, tmp_path: Path) -> None:
        """Two consecutive saves with the same messages produce one row each."""
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        state = SessionState(session_id="idem", messages=msgs)
        cp.save(state)
        cp.save(state)

        db = tmp_path / "session" / "sessions.db"
        mgr = SessionManager(db_path=db)
        try:
            assert mgr.count_messages("idem") == 2
        finally:
            mgr.close()

    def test_save_appends_new_messages_into_db(self, tmp_path: Path) -> None:
        """Adding messages and re-saving extends the DB row set."""
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        cp.save(
            SessionState(
                session_id="grow",
                messages=[{"role": "user", "content": "1"}],
            )
        )
        cp.save(
            SessionState(
                session_id="grow",
                messages=[
                    {"role": "user", "content": "1"},
                    {"role": "assistant", "content": "2"},
                ],
            )
        )

        db = tmp_path / "session" / "sessions.db"
        mgr = SessionManager(db_path=db)
        try:
            loaded = mgr.get_messages("grow")
            assert [m["content"] for m in loaded] == ["1", "2"]
        finally:
            mgr.close()

    def test_save_empty_messages_removes_stale_db_rows(self, tmp_path: Path) -> None:
        """Re-saving an empty transcript keeps the DB mirror aligned with JSON."""
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        cp.save(
            SessionState(
                session_id="empty-now",
                messages=[{"role": "user", "content": "old"}],
            )
        )
        cp.save(SessionState(session_id="empty-now", messages=[]))

        db = tmp_path / "session" / "sessions.db"
        mgr = SessionManager(db_path=db)
        try:
            assert mgr.count_messages("empty-now") == 0
        finally:
            mgr.close()

    def test_sqlite_operational_error_logged_as_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A real sqlite failure surfaces as WARNING with exc_info — JSON survives."""
        import logging
        import sqlite3

        from core.memory import session_manager as _sm_mod
        from core.memory.session_checkpoint import SessionCheckpoint, SessionState

        def _raise(self, *_a: object, **_kw: object) -> int:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(_sm_mod.SessionManager, "upsert_messages", _raise)

        cp = SessionCheckpoint(session_dir=tmp_path / "session")
        with caplog.at_level(logging.WARNING, logger="core.memory.session_checkpoint"):
            cp.save(
                SessionState(
                    session_id="op-fail",
                    messages=[{"role": "user", "content": "still here"}],
                )
            )

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "Failed to mirror messages" in r.getMessage() and r.exc_info is not None
            for r in warnings
        ), "expected a WARNING with exc_info for the sqlite failure"

        loaded = cp.load("op-fail")
        assert loaded is not None
        assert loaded.messages == [{"role": "user", "content": "still here"}]
