"""SessionManager — SQLite-backed session index for fast query/filter/sort.

GAP 3: Replaces file-based session scanning with a proper database index.
Uses SQLite WAL mode for concurrent read access from REPL + sub-agents.

The session metadata lives in the ``sessions`` table; Phase 1a (Hermes
absorption) introduces a ``messages`` table that mirrors the JSON message
log produced by :class:`SessionCheckpoint`. Until Phase 1b flips the SoT,
the JSON files remain authoritative — DB rows are an idempotent mirror.
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

# Default resolves to ~/.geode/projects/{id}/sessions/sessions.db
# with fallback to .geode/session/sessions.db
_DEFAULT_DB_PATH: Path | None = None


def _get_default_db_path() -> Path:
    global _DEFAULT_DB_PATH
    if _DEFAULT_DB_PATH is None:
        from core.paths import resolve_sessions_dir

        _DEFAULT_DB_PATH = resolve_sessions_dir() / "sessions.db"
    return _DEFAULT_DB_PATH


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

# Phase 1a (Hermes absorption) — messages table mirroring SessionCheckpoint
# JSON. ``seq`` preserves intra-session order; ``id`` is the autoincrement
# rowid that Phase 1c's FTS5 contentless index will attach to.
_CREATE_MESSAGES_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT,
    tool_call_id  TEXT,
    tool_calls    TEXT,
    tool_name     TEXT,
    timestamp     REAL NOT NULL,
    token_count   INTEGER,
    finish_reason TEXT,
    reasoning     TEXT,
    metadata      TEXT,
    UNIQUE(session_id, seq)
)
"""

_CREATE_MESSAGES_SESSION_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, seq)
"""

_CREATE_MESSAGES_TOOL_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_messages_tool_name ON messages (tool_name)
"""


def _extract_message_fields(msg: dict[str, Any]) -> dict[str, Any]:
    """Extract structured columns from a chat message dict.

    Handles both Anthropic-style ``content: list[block]`` (with
    ``tool_use`` / ``tool_result`` / ``thinking`` blocks) and OpenAI-style
    top-level ``tool_calls`` / ``tool_call_id`` / ``name`` fields. Unknown
    keys (other than the well-known structural ones) are folded into
    ``metadata`` so nothing is lost on the round-trip.
    """
    role = str(msg.get("role", ""))
    content = msg.get("content")

    # ``content`` is always JSON-serialised so the round-trip is type-safe;
    # ``None`` stays ``NULL`` in the column.
    content_str: str | None = (
        None if content is None else json.dumps(content, ensure_ascii=False)
    )

    tool_call_id: str | None = None
    tool_calls_json: str | None = None
    tool_name: str | None = None
    reasoning: str | None = None

    if isinstance(content, list):
        tool_uses: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tool_uses.append(
                    {
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "input": block.get("input"),
                    }
                )
                if tool_name is None:
                    name = block.get("name")
                    if isinstance(name, str):
                        tool_name = name
            elif btype == "tool_result" and tool_call_id is None:
                tid = block.get("tool_use_id")
                if isinstance(tid, str):
                    tool_call_id = tid
            elif btype == "thinking" and reasoning is None:
                think = block.get("thinking")
                if isinstance(think, str):
                    reasoning = think
        if tool_uses:
            tool_calls_json = json.dumps(tool_uses, ensure_ascii=False)

    raw_tool_calls = msg.get("tool_calls")
    if raw_tool_calls and tool_calls_json is None:
        tool_calls_json = json.dumps(raw_tool_calls, ensure_ascii=False)
        if isinstance(raw_tool_calls, list) and raw_tool_calls:
            first = raw_tool_calls[0]
            if isinstance(first, dict):
                fn = first.get("function")
                if isinstance(fn, dict):
                    fname = fn.get("name")
                    if isinstance(fname, str) and tool_name is None:
                        tool_name = fname

    raw_tcid = msg.get("tool_call_id")
    if isinstance(raw_tcid, str) and tool_call_id is None:
        tool_call_id = raw_tcid
    raw_name = msg.get("name")
    if isinstance(raw_name, str) and tool_name is None and role == "tool":
        tool_name = raw_name

    raw_reasoning = msg.get("reasoning")
    if isinstance(raw_reasoning, str) and reasoning is None:
        reasoning = raw_reasoning

    token_count_raw = msg.get("token_count")
    token_count: int | None = (
        int(token_count_raw) if isinstance(token_count_raw, (int, float)) else None
    )
    finish_reason_raw = msg.get("finish_reason")
    finish_reason: str | None = (
        finish_reason_raw if isinstance(finish_reason_raw, str) else None
    )

    metadata_raw = msg.get("metadata")
    metadata_json: str | None = (
        json.dumps(metadata_raw, ensure_ascii=False)
        if isinstance(metadata_raw, (dict, list)) and metadata_raw
        else None
    )

    return {
        "role": role,
        "content": content_str,
        "tool_call_id": tool_call_id,
        "tool_calls": tool_calls_json,
        "tool_name": tool_name,
        "token_count": token_count,
        "finish_reason": finish_reason,
        "reasoning": reasoning,
        "metadata": metadata_json,
    }


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
        self._db_path = db_path or _get_default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_CREATE_INDEX_SQL)
        self._conn.execute(_CREATE_MESSAGES_TABLE_SQL)
        self._conn.execute(_CREATE_MESSAGES_SESSION_INDEX_SQL)
        self._conn.execute(_CREATE_MESSAGES_TOOL_INDEX_SQL)
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

    # ------------------------------------------------------------------
    # Phase 1a: messages mirror (dual-write target)
    # ------------------------------------------------------------------

    def upsert_messages(
        self,
        session_id: str,
        messages: list[Any],
        default_timestamp: float | None = None,
    ) -> int:
        """Mirror a session's full message list into the ``messages`` table.

        Rows are keyed by ``(session_id, seq)`` and updated in place, so
        repeated calls with overlapping prefixes are idempotent. Returns
        the number of rows written.

        Until Phase 1b the JSON checkpoint remains SoT — this mirror exists
        so Phase 1c (FTS5) and Phase 1d (cross-project search) have a
        structured target to attach to. The caller (SessionCheckpoint)
        catches any error and logs WARN; we still raise here so test
        failures surface.
        """
        ts_default = default_timestamp if default_timestamp is not None else time.time()
        rows: list[tuple[Any, ...]] = []
        valid_seqs: list[int] = []
        valid_seq_set: set[int] = set()
        for seq, msg in enumerate(messages):
            # Runtime defence — REPL transcripts occasionally splice in
            # placeholder entries (``None`` / ``str``) that the declared
            # ``list[dict[str, Any]]`` signature doesn't catch.
            if not isinstance(msg, dict):
                continue
            valid_seqs.append(seq)
            valid_seq_set.add(seq)
            fields = _extract_message_fields(msg)
            raw_ts = msg.get("timestamp")
            timestamp = (
                float(raw_ts) if isinstance(raw_ts, (int, float)) else ts_default
            )
            rows.append(
                (
                    session_id,
                    seq,
                    fields["role"],
                    fields["content"],
                    fields["tool_call_id"],
                    fields["tool_calls"],
                    fields["tool_name"],
                    timestamp,
                    fields["token_count"],
                    fields["finish_reason"],
                    fields["reasoning"],
                    fields["metadata"],
                )
            )
        with self._lock:
            if rows:
                self._conn.executemany(
                    """\
                    INSERT INTO messages
                        (session_id, seq, role, content, tool_call_id, tool_calls,
                         tool_name, timestamp, token_count, finish_reason, reasoning,
                         metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, seq) DO UPDATE SET
                        role          = excluded.role,
                        content       = excluded.content,
                        tool_call_id  = excluded.tool_call_id,
                        tool_calls    = excluded.tool_calls,
                        tool_name     = excluded.tool_name,
                        timestamp     = excluded.timestamp,
                        token_count   = excluded.token_count,
                        finish_reason = excluded.finish_reason,
                        reasoning     = excluded.reasoning,
                        metadata      = excluded.metadata
                    """,
                    rows,
                )
            if valid_seqs:
                existing_seqs = self._conn.execute(
                    "SELECT seq FROM messages WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
                stale_seqs = [
                    int(row[0]) for row in existing_seqs if int(row[0]) not in valid_seq_set
                ]
                for stale_seq in stale_seqs:
                    self._conn.execute(
                        "DELETE FROM messages WHERE session_id = ? AND seq = ?",
                        (session_id, stale_seq),
                    )
            else:
                self._conn.execute(
                    "DELETE FROM messages WHERE session_id = ?",
                    (session_id,),
                )
            self._conn.commit()
        return len(rows)

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch all messages for ``session_id`` in ``seq`` order."""
        rows = self._conn.execute(
            """\
            SELECT seq, role, content, tool_call_id, tool_calls, tool_name,
                   timestamp, token_count, finish_reason, reasoning, metadata
            FROM messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def count_messages(self, session_id: str) -> int:
        """Return the number of mirrored messages for ``session_id``."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def delete_messages(self, session_id: str) -> int:
        """Remove all mirrored messages for ``session_id``. Returns count."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return cursor.rowcount

    @staticmethod
    def _row_to_message(row: tuple) -> dict[str, Any]:  # type: ignore[type-arg]
        msg: dict[str, Any] = {
            "seq": row[0],
            "role": row[1],
            "timestamp": row[6],
        }
        if row[2] is not None:
            try:
                msg["content"] = json.loads(row[2])
            except json.JSONDecodeError:
                msg["content"] = row[2]
        else:
            msg["content"] = None
        if row[3]:
            msg["tool_call_id"] = row[3]
        if row[4]:
            try:
                msg["tool_calls"] = json.loads(row[4])
            except json.JSONDecodeError:
                msg["tool_calls"] = row[4]
        if row[5]:
            msg["tool_name"] = row[5]
        if row[7] is not None:
            msg["token_count"] = row[7]
        if row[8]:
            msg["finish_reason"] = row[8]
        if row[9]:
            msg["reasoning"] = row[9]
        if row[10]:
            try:
                msg["metadata"] = json.loads(row[10])
            except json.JSONDecodeError:
                msg["metadata"] = row[10]
        return msg

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
