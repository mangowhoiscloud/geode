"""Tests for GAP 3: SessionManager (SQLite session index)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from core.memory.session_manager import SessionManager, SessionMeta


@pytest.fixture()
def mgr(tmp_path: Path) -> SessionManager:
    db = tmp_path / "sessions.db"
    m = SessionManager(db_path=db)
    yield m  # type: ignore[misc]
    m.close()


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
        from core.cli.session_checkpoint import SessionCheckpoint, SessionState

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
