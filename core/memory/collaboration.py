"""Durable control state for depth-one sub-agent collaboration.

The tables here are mutable projections.  Child messages and append-only
session events remain the rollout and replay source.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.observability.redaction import redact_and_bound_text
from core.observability.session_timeline import bound_session_payload

_OWNER_ID = f"{os.getpid()}:{time.time_ns()}"
_ACTIVE_STATUSES = frozenset({"pending", "running"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "timeout", "interrupted"})
_MESSAGE_KINDS = frozenset({"message", "completion"})
_RETENTION_SECONDS = 7 * 24 * 60 * 60
_MAX_TERMINAL_RUNS = 200
_MAX_UNREAD_PER_RECIPIENT = 1_000
_MAX_CONSUMED_MESSAGES = 1_000

_RUNS_SQL = """\
CREATE TABLE IF NOT EXISTS collaboration_runs (
    task_id            TEXT PRIMARY KEY,
    parent_session_id  TEXT NOT NULL,
    task_type          TEXT NOT NULL DEFAULT '',
    role               TEXT NOT NULL DEFAULT '',
    model              TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL,
    generation         INTEGER NOT NULL DEFAULT 1,
    summary            TEXT NOT NULL DEFAULT '',
    error              TEXT NOT NULL DEFAULT '',
    owner_id           TEXT NOT NULL,
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
)
"""

_MAILBOX_SQL = """\
CREATE TABLE IF NOT EXISTS collaboration_mailbox (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_session_id     TEXT NOT NULL,
    recipient_session_id  TEXT NOT NULL,
    kind                  TEXT NOT NULL,
    payload_json          TEXT NOT NULL,
    created_at            REAL NOT NULL,
    consumed_at           REAL
)
"""


def _owner_process_alive(owner_id: str) -> bool:
    """Return whether a local owner PID still exists."""
    try:
        pid = int(owner_id.partition(":")[0])
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True, slots=True)
class CollaborationRun:
    task_id: str
    parent_session_id: str
    task_type: str
    role: str
    model: str
    source: str
    status: str
    generation: int
    summary: str
    error: str
    owner_id: str
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        public = asdict(self)
        public.pop("owner_id")
        return public


@dataclass(frozen=True, slots=True)
class CollaborationMessage:
    id: int
    sender_session_id: str
    recipient_session_id: str
    kind: str
    payload: dict[str, Any]
    created_at: float


def ensure_collaboration_schema(conn: sqlite3.Connection) -> None:
    """Create the additive collaboration tables and their bounded indexes."""
    conn.execute(_RUNS_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collaboration_runs_parent "
        "ON collaboration_runs (parent_session_id, updated_at DESC)"
    )
    conn.execute(_MAILBOX_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collaboration_mailbox_unread "
        "ON collaboration_mailbox (recipient_session_id, id) WHERE consumed_at IS NULL"
    )


class CollaborationStore:
    """Short-connection store sharing the project-local ``sessions.db``."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from core.paths import resolve_sessions_dir

            db_path = resolve_sessions_dir() / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def owner_id(self) -> str:
        return _OWNER_ID

    def begin_run(
        self,
        *,
        task_id: str,
        parent_session_id: str,
        task_type: str,
        role: str = "",
        model: str = "",
        source: str = "",
        resume: bool = False,
    ) -> CollaborationRun:
        """Create generation one, or reopen a terminal run as N+1."""
        if not task_id or not parent_session_id:
            raise ValueError("task_id and parent_session_id are required")
        now = time.time()
        with self._transaction() as conn:
            self._prune_locked(conn, now)
            existing = conn.execute(
                "SELECT * FROM collaboration_runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if resume:
                if existing is None or str(existing["parent_session_id"]) != parent_session_id:
                    raise ValueError("Unknown child task for this parent session")
                if str(existing["status"]) in _ACTIVE_STATUSES:
                    raise ValueError("Child task is already running")
                generation = int(existing["generation"]) + 1
                conn.execute(
                    """UPDATE collaboration_runs SET
                           task_type = ?, role = ?, model = ?, source = ?,
                           status = 'pending', generation = ?, summary = '', error = '',
                           owner_id = ?, updated_at = ?
                       WHERE task_id = ? AND parent_session_id = ?""",
                    (
                        task_type,
                        role,
                        model,
                        source,
                        generation,
                        _OWNER_ID,
                        now,
                        task_id,
                        parent_session_id,
                    ),
                )
            else:
                if existing is not None:
                    raise ValueError(f"Duplicate child task_id: {task_id}")
                conn.execute(
                    """INSERT INTO collaboration_runs
                           (task_id, parent_session_id, task_type, role, model, source,
                            status, generation, owner_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?)""",
                    (
                        task_id,
                        parent_session_id,
                        task_type,
                        role,
                        model,
                        source,
                        _OWNER_ID,
                        now,
                        now,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM collaboration_runs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - transaction invariant
            raise RuntimeError("Collaboration run was not persisted")
        return self._run_from_row(row)

    def mark_running(self, parent_session_id: str, task_id: str, generation: int) -> bool:
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE collaboration_runs
                   SET status = 'running', updated_at = ?
                   WHERE task_id = ? AND parent_session_id = ?
                     AND generation = ? AND status = 'pending' AND owner_id = ?""",
                (time.time(), task_id, parent_session_id, generation, _OWNER_ID),
            )
            return cursor.rowcount == 1

    def finish_run(
        self,
        *,
        parent_session_id: str,
        task_id: str,
        generation: int,
        status: str,
        summary: str = "",
        error: str = "",
    ) -> bool:
        """Fix one terminal state and enqueue its parent completion atomically."""
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Invalid terminal collaboration status: {status}")
        bounded_summary = redact_and_bound_text(summary, 4_000)
        bounded_error = redact_and_bound_text(error, 2_000)
        now = time.time()
        with self._transaction() as conn:
            cursor = conn.execute(
                """UPDATE collaboration_runs
                   SET status = ?, summary = ?, error = ?, updated_at = ?
                   WHERE task_id = ? AND parent_session_id = ? AND generation = ?
                     AND status IN ('pending', 'running')""",
                (
                    status,
                    bounded_summary,
                    bounded_error,
                    now,
                    task_id,
                    parent_session_id,
                    generation,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._insert_message(
                conn,
                sender_session_id=task_id,
                recipient_session_id=parent_session_id,
                kind="completion",
                payload={
                    "task_id": task_id,
                    "status": status,
                    "generation": generation,
                    "summary": bounded_summary,
                    "error": bounded_error,
                },
                created_at=now,
            )
            self._prune_locked(conn, now)
            return True

    def get_run(self, parent_session_id: str, task_id: str) -> CollaborationRun | None:
        self.recover_stale(parent_session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM collaboration_runs WHERE parent_session_id = ? AND task_id = ?",
                (parent_session_id, task_id),
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def list_runs(self, parent_session_id: str, *, limit: int = 50) -> list[CollaborationRun]:
        self.recover_stale(parent_session_id)
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM collaboration_runs
                   WHERE parent_session_id = ? ORDER BY updated_at DESC LIMIT ?""",
                (parent_session_id, max(1, min(limit, 200))),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def append_message(
        self,
        *,
        sender_session_id: str,
        recipient_session_id: str,
        kind: str,
        payload: dict[str, Any],
    ) -> int:
        if kind not in _MESSAGE_KINDS:
            raise ValueError(f"Invalid collaboration message kind: {kind}")
        if not sender_session_id or not recipient_session_id:
            raise ValueError("sender and recipient session ids are required")
        with self._transaction() as conn:
            return self._insert_message(
                conn,
                sender_session_id=sender_session_id,
                recipient_session_id=recipient_session_id,
                kind=kind,
                payload=payload,
                created_at=time.time(),
            )

    def drain_mailbox(
        self,
        recipient_session_id: str,
        *,
        limit: int = 50,
    ) -> list[CollaborationMessage]:
        """Claim unread items in id order with transactional at-most-once delivery."""
        if not recipient_session_id:
            return []
        with self._transaction() as conn:
            self._recover_stale_locked(conn, recipient_session_id)
            rows = conn.execute(
                """SELECT id, sender_session_id, recipient_session_id, kind,
                          payload_json, created_at
                   FROM collaboration_mailbox
                   WHERE recipient_session_id = ? AND consumed_at IS NULL
                   ORDER BY id ASC LIMIT ?""",
                (recipient_session_id, max(1, min(limit, 200))),
            ).fetchall()
            if rows:
                consumed_at = time.time()
                conn.executemany(
                    "UPDATE collaboration_mailbox SET consumed_at = ? WHERE id = ?",
                    [(consumed_at, int(row["id"])) for row in rows],
                )
                self._prune_locked(conn, consumed_at)
        messages: list[CollaborationMessage] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                payload = {"_invalid_payload": True}
            messages.append(
                CollaborationMessage(
                    id=int(row["id"]),
                    sender_session_id=str(row["sender_session_id"]),
                    recipient_session_id=str(row["recipient_session_id"]),
                    kind=str(row["kind"]),
                    payload=payload if isinstance(payload, dict) else {"value": payload},
                    created_at=float(row["created_at"]),
                )
            )
        return messages

    def recover_stale(self, parent_session_id: str) -> int:
        """Turn prior-process active rows into observable interrupted terminals."""
        if not parent_session_id:
            return 0
        with self._transaction() as conn:
            return self._recover_stale_locked(conn, parent_session_id)

    def _recover_stale_locked(self, conn: sqlite3.Connection, parent_session_id: str) -> int:
        rows = conn.execute(
            """SELECT task_id, generation, owner_id FROM collaboration_runs
               WHERE parent_session_id = ? AND status IN ('pending', 'running')
                 AND owner_id != ?""",
            (parent_session_id, _OWNER_ID),
        ).fetchall()
        now = time.time()
        recovered = 0
        for row in rows:
            if _owner_process_alive(str(row["owner_id"])):
                continue
            task_id = str(row["task_id"])
            generation = int(row["generation"])
            conn.execute(
                """UPDATE collaboration_runs
                   SET status = 'interrupted', error = ?, updated_at = ?
                   WHERE task_id = ? AND generation = ? AND status IN ('pending', 'running')""",
                ("Owning runtime exited before completion", now, task_id, generation),
            )
            self._insert_message(
                conn,
                sender_session_id=task_id,
                recipient_session_id=parent_session_id,
                kind="completion",
                payload={
                    "task_id": task_id,
                    "status": "interrupted",
                    "generation": generation,
                    "summary": "",
                    "error": "Owning runtime exited before completion",
                },
                created_at=now,
            )
            recovered += 1
        return recovered

    @staticmethod
    def _insert_message(
        conn: sqlite3.Connection,
        *,
        sender_session_id: str,
        recipient_session_id: str,
        kind: str,
        payload: dict[str, Any],
        created_at: float,
    ) -> int:
        bounded = bound_session_payload(payload)
        cursor = conn.execute(
            """INSERT INTO collaboration_mailbox
                   (sender_session_id, recipient_session_id, kind, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                sender_session_id,
                recipient_session_id,
                kind,
                json.dumps(bounded, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                created_at,
            ),
        )
        conn.execute(
            """DELETE FROM collaboration_mailbox WHERE id IN (
                   SELECT id FROM collaboration_mailbox
                   WHERE recipient_session_id = ? AND consumed_at IS NULL
                   ORDER BY id DESC LIMIT -1 OFFSET ?
               )""",
            (recipient_session_id, _MAX_UNREAD_PER_RECIPIENT),
        )
        return int(cursor.lastrowid or 0)

    @staticmethod
    def _prune_locked(conn: sqlite3.Connection, now: float) -> None:
        cutoff = now - _RETENTION_SECONDS
        conn.execute(
            """DELETE FROM collaboration_runs
               WHERE status NOT IN ('pending', 'running') AND updated_at < ?""",
            (cutoff,),
        )
        conn.execute(
            """DELETE FROM collaboration_runs WHERE task_id IN (
                   SELECT task_id FROM collaboration_runs
                   WHERE status NOT IN ('pending', 'running')
                   ORDER BY updated_at DESC LIMIT -1 OFFSET ?
               )""",
            (_MAX_TERMINAL_RUNS,),
        )
        conn.execute(
            "DELETE FROM collaboration_mailbox WHERE consumed_at IS NOT NULL AND consumed_at < ?",
            (cutoff,),
        )
        conn.execute(
            """DELETE FROM collaboration_mailbox WHERE id IN (
                   SELECT id FROM collaboration_mailbox WHERE consumed_at IS NOT NULL
                   ORDER BY consumed_at DESC LIMIT -1 OFFSET ?
               )""",
            (_MAX_CONSUMED_MESSAGES,),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> CollaborationRun:
        return CollaborationRun(
            task_id=str(row["task_id"]),
            parent_session_id=str(row["parent_session_id"]),
            task_type=str(row["task_type"]),
            role=str(row["role"]),
            model=str(row["model"]),
            source=str(row["source"]),
            status=str(row["status"]),
            generation=int(row["generation"]),
            summary=str(row["summary"]),
            error=str(row["error"]),
            owner_id=str(row["owner_id"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            ensure_collaboration_schema(conn)
            conn.commit()
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
