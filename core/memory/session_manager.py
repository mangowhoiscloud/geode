"""SessionManager — SQLite-backed session index for fast query/filter/sort.

GAP 3: Replaces file-based session scanning with a proper database index.
Uses SQLite WAL mode for concurrent read access from REPL + sub-agents.

The session *data* (messages, tool logs) remains in JSON files managed by
SessionCheckpoint. This module only indexes metadata for fast lookup.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(".geode") / "session" / "sessions.db"


@dataclass
class SessionMeta:
    """Lightweight session metadata for index queries."""

    session_id: str
    created_at: float
    updated_at: float
    status: str  # active | paused | completed | error
    model: str = ""
    provider: str = "anthropic"
    user_input: str = ""
    round_count: int = 0
    message_count: int = 0


_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    model        TEXT NOT NULL DEFAULT '',
    provider     TEXT NOT NULL DEFAULT 'anthropic',
    user_input   TEXT NOT NULL DEFAULT '',
    round_count  INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at DESC)
"""


class SessionManager:
    """SQLite-backed session index.

    Usage::

        mgr = SessionManager()
        mgr.upsert(SessionMeta(session_id="s1", ...))
        meta = mgr.get("s1")
        recent = mgr.list_sessions(status="active", limit=10)
        mgr.cleanup(max_age_hours=72)
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_CREATE_INDEX_SQL)
        self._conn.commit()

    def upsert(self, meta: SessionMeta) -> None:
        """Insert or update session metadata."""
        with self._lock:
            self._conn.execute(
                """\
                INSERT INTO sessions
                    (session_id, created_at, updated_at, status, model, provider,
                     user_input, round_count, message_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at    = excluded.updated_at,
                    status        = excluded.status,
                    model         = excluded.model,
                    provider      = excluded.provider,
                    user_input    = excluded.user_input,
                    round_count   = excluded.round_count,
                    message_count = excluded.message_count
                """,
                (
                    meta.session_id,
                    meta.created_at,
                    meta.updated_at,
                    meta.status,
                    meta.model,
                    meta.provider,
                    meta.user_input,
                    meta.round_count,
                    meta.message_count,
                ),
            )
            self._conn.commit()

    def get(self, session_id: str) -> SessionMeta | None:
        """Fetch a single session by ID."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_meta(row)

    def list_sessions(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SessionMeta]:
        """List sessions, optionally filtered by status, ordered by updated_at desc."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_meta(r) for r in rows]

    def delete(self, session_id: str) -> bool:
        """Delete a session from the index. Returns True if deleted."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def cleanup(self, max_age_hours: float = 72.0) -> int:
        """Remove completed/old sessions. Returns count removed."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE status = 'completed' OR updated_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    @staticmethod
    def _row_to_meta(row: tuple) -> SessionMeta:  # type: ignore[type-arg]
        return SessionMeta(
            session_id=row[0],
            created_at=row[1],
            updated_at=row[2],
            status=row[3],
            model=row[4],
            provider=row[5],
            user_input=row[6],
            round_count=row[7],
            message_count=row[8],
        )
