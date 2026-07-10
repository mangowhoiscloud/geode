"""SQLite-backed CognitiveState store.

Persists the latest cognitive snapshot per session plus an append-only
cognitive event stream. ``SessionCheckpoint`` uses this as the DB-first
resume source; ``state.json`` keeps a compatibility cache.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    """Resolve SessionManager's canonical database without a second cache."""
    from core.memory.session_manager import _get_default_db_path as resolve_default_db_path

    return resolve_default_db_path()


_CREATE_LATEST_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS cognitive_states (
    session_id TEXT PRIMARY KEY,
    updated_at REAL NOT NULL,
    snapshot   TEXT NOT NULL
)
"""

_CREATE_EVENTS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS cognitive_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    phase      TEXT NOT NULL,
    timestamp  REAL NOT NULL,
    snapshot   TEXT NOT NULL
)
"""

_CREATE_EVENTS_SESSION_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_cognitive_events_session
    ON cognitive_events (session_id, id)
"""


@dataclass(frozen=True)
class CognitiveEvent:
    """One persisted cognitive event snapshot."""

    id: int
    session_id: str
    phase: str
    timestamp: float
    snapshot: dict[str, Any]


class CognitiveStateStore:
    """Central persistence surface for cognitive loop state."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _get_default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(_CREATE_LATEST_TABLE_SQL)
            self._conn.execute(_CREATE_EVENTS_TABLE_SQL)
            self._conn.execute(_CREATE_EVENTS_SESSION_INDEX_SQL)
            self._conn.commit()

    def save_latest(
        self,
        session_id: str,
        snapshot: dict[str, Any],
        *,
        updated_at: float | None = None,
    ) -> None:
        """Upsert the latest cognitive snapshot for ``session_id``."""
        if not session_id:
            return
        ts = updated_at if updated_at is not None else time.time()
        blob = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """\
                INSERT INTO cognitive_states (session_id, updated_at, snapshot)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    snapshot   = excluded.snapshot
                """,
                (session_id, ts, blob),
            )
            self._conn.commit()

    def load_latest(self, session_id: str) -> dict[str, Any] | None:
        """Return the latest snapshot for ``session_id`` if present."""
        row = self._conn.execute(
            "SELECT snapshot FROM cognitive_states WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row[0]))
        except json.JSONDecodeError:
            log.warning("cognitive state snapshot is not valid JSON; session=%s", session_id)
            return None
        return payload if isinstance(payload, dict) else None

    def append_event(
        self,
        session_id: str,
        phase: str,
        snapshot: dict[str, Any],
        *,
        timestamp: float | None = None,
    ) -> int:
        """Append one cognitive event and update the latest snapshot."""
        if not session_id:
            return 0
        ts = timestamp if timestamp is not None else time.time()
        blob = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with self._lock:
            cursor = self._conn.execute(
                """\
                INSERT INTO cognitive_events (session_id, phase, timestamp, snapshot)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, phase, ts, blob),
            )
            self._conn.execute(
                """\
                INSERT INTO cognitive_states (session_id, updated_at, snapshot)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    snapshot   = excluded.snapshot
                """,
                (session_id, ts, blob),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)

    def recent_events(self, session_id: str, *, limit: int = 20) -> list[CognitiveEvent]:
        """Return recent events for ``session_id`` newest-first."""
        rows = self._conn.execute(
            """\
            SELECT id, session_id, phase, timestamp, snapshot
            FROM cognitive_events
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, max(0, limit)),
        ).fetchall()
        events: list[CognitiveEvent] = []
        for row in rows:
            try:
                snapshot = json.loads(str(row[4]))
            except json.JSONDecodeError:
                log.warning("cognitive event snapshot is not valid JSON; id=%s", row[0])
                continue
            if not isinstance(snapshot, dict):
                continue
            events.append(
                CognitiveEvent(
                    id=int(row[0]),
                    session_id=str(row[1]),
                    phase=str(row[2]),
                    timestamp=float(row[3]),
                    snapshot=snapshot,
                )
            )
        return events

    def event_count(self, session_id: str) -> int:
        """Return the number of persisted cognitive events for ``session_id``."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM cognitive_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else 0


__all__ = ["CognitiveEvent", "CognitiveStateStore"]
