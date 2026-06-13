"""Unit tests for :mod:`core.agent.handoff` — DB-backed handoff state machine.

Verifies the 5-state machine (NONE → PENDING → RUNNING → COMPLETED/FAILED):
- atomic CAS for ``request_handoff`` (no double-trigger)
- ``get_handoff`` returns snapshot, None when session missing
- Migration: legacy DB without handoff cols → ALTER TABLE adds them
- ``SessionManager`` __init__ runs the migration idempotently

Pattern modeled on hermes-agent ``sessions`` table CAS helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from core.agent.handoff import (
    HandoffState,
    get_handoff,
    request_handoff,
)
from core.memory.session_manager import SessionManager, SessionMeta


@pytest.fixture
def manager(tmp_path: Path) -> SessionManager:
    """Fresh SessionManager backed by a per-test SQLite DB."""
    db_path = tmp_path / "sessions.db"
    return SessionManager(db_path=db_path)


def _seed_session(manager: SessionManager, session_id: str) -> None:
    """Helper — insert a baseline session row so handoff CAS can flip it."""
    manager.upsert(
        SessionMeta(
            session_id=session_id,
            created_at=1.0,
            updated_at=1.0,
            status="active",
            model="claude-opus-4-7",
        )
    )


def test_handoff_state_str_enum_values() -> None:
    """Enum values match the DB TEXT column convention."""
    assert HandoffState.NONE.value == ""
    assert HandoffState.PENDING.value == "pending"
    assert HandoffState.RUNNING.value == "running"
    assert HandoffState.COMPLETED.value == "completed"
    assert HandoffState.FAILED.value == "failed"


def test_request_handoff_pending(manager: SessionManager) -> None:
    """Empty state → PENDING via CAS."""
    _seed_session(manager, "s1")
    ok = request_handoff(manager._conn, session_id="s1", platform="slack")
    assert ok is True
    snapshot = get_handoff(manager._conn, session_id="s1")
    assert snapshot is not None
    assert snapshot.state is HandoffState.PENDING
    assert snapshot.platform == "slack"
    assert snapshot.triggered_at > 0.0


def test_request_handoff_idempotent_on_pending(manager: SessionManager) -> None:
    """Second request when already PENDING returns False (CAS fails)."""
    _seed_session(manager, "s2")
    assert request_handoff(manager._conn, session_id="s2", platform="x") is True
    assert request_handoff(manager._conn, session_id="s2", platform="y") is False
    snapshot = get_handoff(manager._conn, session_id="s2")
    assert snapshot is not None
    assert snapshot.platform == "x"  # First write wins.


def test_get_handoff_missing_session(manager: SessionManager) -> None:
    """Unknown session_id returns None, not an exception."""
    assert get_handoff(manager._conn, session_id="ghost") is None


def test_legacy_db_migration_adds_columns(tmp_path: Path) -> None:
    """Pre-PR-CL-BUDGET DB lacking handoff cols → SessionManager.__init__
    runs ALTER TABLE so the new cols exist on next open."""
    db_path = tmp_path / "legacy.db"
    # Hand-craft a legacy schema *without* the four handoff columns.
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            model TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'anthropic',
            user_input TEXT NOT NULL DEFAULT '',
            round_count INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO sessions (session_id, created_at, updated_at)
        VALUES ('legacy-row', 1.0, 1.0);
        """
    )
    conn.commit()
    conn.close()

    # Open via SessionManager — migration must run idempotently.
    mgr = SessionManager(db_path=db_path)
    cols = {row[1] for row in mgr._conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "handoff_state" in cols
    assert "handoff_platform" in cols
    assert "handoff_error" in cols
    assert "handoff_triggered_at" in cols

    # Existing row keeps its data + default-empty handoff state.
    snapshot = get_handoff(mgr._conn, session_id="legacy-row")
    assert snapshot is not None
    assert snapshot.state is HandoffState.NONE
    assert snapshot.platform == ""


def test_migration_idempotent_on_second_open(tmp_path: Path) -> None:
    """Re-opening a DB that already has the columns is a no-op."""
    db_path = tmp_path / "twice.db"
    SessionManager(db_path=db_path)
    # Second open must not raise (no duplicate ADD COLUMN).
    mgr2 = SessionManager(db_path=db_path)
    assert mgr2._conn.execute("PRAGMA table_info(sessions)").fetchall() is not None
