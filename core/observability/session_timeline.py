"""Versioned session history backed by ``sessions.db:session_events``.

``SessionTimeline`` records immutable execution history. It is intentionally
separate from:

* ``SessionCheckpoint`` / ``messages`` — mutable resume state;
* ``hook_events`` — bounded runtime and policy telemetry;
* run-scoped ``events.jsonl`` — an optional portable projection.

The deprecated :class:`core.observability.transcript.SessionTranscript` remains
as a compatibility reader/writer for one release. New runtime code writes here.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import uuid
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from itertools import islice
from pathlib import Path
from typing import Any

from core.observability.redaction import redact_and_bound_text, redact_secrets

log = logging.getLogger(__name__)

SESSION_EVENT_SCHEMA_ID = "geode.session-event@1"
SESSION_EVENT_SCHEMA_VERSION = 1
SESSION_EVENT_COMPONENT = "session_events"
SESSION_EVENT_RETENTION_DAYS = 180

_CURRENT_SESSION_TIMELINE: ContextVar[SessionTimeline | None] = ContextVar(
    "geode_session_timeline",
    default=None,
)

_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "headers",
        "password",
        "secret",
        "token",
    }
)


class SessionEventKind(StrEnum):
    """Closed vocabulary for durable agent execution history."""

    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    TURN_COMPLETED = "turn.completed"
    VERIFICATION_CONTINUED = "verification.continued"
    VERIFICATION_EVIDENCE = "verification.evidence"
    VERIFICATION_PENDING = "verification.pending"
    USER_MESSAGE = "message.user"
    ASSISTANT_MESSAGE = "message.assistant"
    TOOL_CALLED = "tool.called"
    TOOL_COMPLETED = "tool.completed"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_STOPPED = "subagent.stopped"
    ARTIFACT_SAVED = "artifact.saved"
    USAGE_RECORDED = "usage.recorded"
    ERROR_RECORDED = "error.recorded"
    GUI_STEP = "gui.step"
    PREFLIGHT_RECORDED = "preflight.recorded"
    HANDOFF_TRIGGERED = "handoff.triggered"
    LEGACY_IMPORTED = "legacy.imported"


_CREATE_STORAGE_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS storage_schema (
    component  TEXT PRIMARY KEY,
    version    INTEGER NOT NULL,
    updated_at REAL NOT NULL
)
"""

_CREATE_SESSION_EVENTS_SQL = """\
CREATE TABLE IF NOT EXISTS session_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version     INTEGER NOT NULL,
    event_id           TEXT NOT NULL UNIQUE,
    occurred_at        REAL NOT NULL,
    session_id         TEXT NOT NULL,
    session_generation INTEGER NOT NULL DEFAULT 1,
    turn_id            TEXT NOT NULL DEFAULT '',
    call_id            TEXT NOT NULL DEFAULT '',
    parent_event_id    TEXT,
    kind               TEXT NOT NULL,
    role               TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT '',
    model              TEXT NOT NULL DEFAULT '',
    provider           TEXT NOT NULL DEFAULT '',
    payload_json       TEXT NOT NULL,
    payload_hash       TEXT NOT NULL,
    source             TEXT NOT NULL DEFAULT 'runtime'
)
"""

_CREATE_LEGACY_IMPORTS_SQL = """\
CREATE TABLE IF NOT EXISTS session_event_imports (
    source_digest TEXT PRIMARY KEY,
    source_path   TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    row_count     INTEGER NOT NULL,
    imported_at   REAL NOT NULL
)
"""

_SESSION_EVENT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events (session_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_session_events_turn "
    "ON session_events (session_id, turn_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_session_events_call "
    "ON session_events (session_id, call_id, id) WHERE call_id != ''",
    "CREATE INDEX IF NOT EXISTS idx_session_events_kind ON session_events (kind, occurred_at DESC)",
)


def ensure_session_event_schema(conn: sqlite3.Connection) -> None:
    """Create the additive v1 history schema and record component ownership."""
    conn.execute(_CREATE_STORAGE_SCHEMA_SQL)
    conn.execute(_CREATE_SESSION_EVENTS_SQL)
    conn.execute(_CREATE_LEGACY_IMPORTS_SQL)
    for statement in _SESSION_EVENT_INDEXES:
        conn.execute(statement)
    row = conn.execute(
        "SELECT version FROM storage_schema WHERE component = ?",
        (SESSION_EVENT_COMPONENT,),
    ).fetchone()
    if row is not None and int(row[0]) > SESSION_EVENT_SCHEMA_VERSION:
        raise RuntimeError(
            "sessions.db session-event schema is newer than this GEODE build: "
            f"{row[0]} > {SESSION_EVENT_SCHEMA_VERSION}"
        )
    if row is None:
        conn.execute(
            "INSERT INTO storage_schema (component, version, updated_at) VALUES (?, ?, ?)",
            (SESSION_EVENT_COMPONENT, SESSION_EVENT_SCHEMA_VERSION, time.time()),
        )
    elif int(row[0]) < SESSION_EVENT_SCHEMA_VERSION:
        conn.execute(
            "UPDATE storage_schema SET version = ?, updated_at = ? WHERE component = ?",
            (SESSION_EVENT_SCHEMA_VERSION, time.time(), SESSION_EVENT_COMPONENT),
        )


@dataclass(frozen=True, slots=True)
class SessionEventPolicy:
    """Bounds for one event payload and its optional JSONL projection."""

    max_payload_bytes: int = 256 * 1024
    max_string_chars: int = 100_000
    max_collection_items: int = 256
    max_depth: int = 12
    max_projection_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SessionEventWrite:
    """Validated input accepted by :class:`SessionEventStore`."""

    session_id: str
    kind: SessionEventKind
    occurred_at: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_generation: int = 1
    turn_id: str = ""
    call_id: str = ""
    parent_event_id: str | None = None
    role: str = ""
    status: str = ""
    model: str = ""
    provider: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "runtime"


@dataclass(frozen=True, slots=True)
class PersistedSessionEvent:
    """One decoded row from ``session_events``."""

    id: int
    schema_version: int
    event_id: str
    occurred_at: float
    session_id: str
    session_generation: int
    turn_id: str
    call_id: str
    parent_event_id: str | None
    kind: str
    role: str
    status: str
    model: str
    provider: str
    payload: dict[str, Any]
    payload_hash: str
    source: str
    corrupt_payload: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the portable ``geode.session-event@1`` representation."""
        return {
            "schema_id": SESSION_EVENT_SCHEMA_ID,
            "schema_version": self.schema_version,
            "ordinal": self.id,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "session_id": self.session_id,
            "session_generation": self.session_generation,
            "turn_id": self.turn_id,
            "call_id": self.call_id,
            "parent_event_id": self.parent_event_id,
            "kind": self.kind,
            "role": self.role,
            "status": self.status,
            "model": self.model,
            "provider": self.provider,
            "payload": self.payload,
            "payload_hash": self.payload_hash,
            "source": self.source,
            "corrupt_payload": self.corrupt_payload,
        }


class SessionEventStore:
    """Short-connection SQLite writer/reader for immutable session history."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        policy: SessionEventPolicy | None = None,
    ) -> None:
        if db_path is None:
            from core.memory.session_manager import _get_default_db_path

            resolved = _get_default_db_path()
        else:
            resolved = Path(db_path)
        self._db_path = resolved
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._policy = policy or SessionEventPolicy()
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            ensure_session_event_schema(conn)
            conn.commit()
        finally:
            conn.close()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def policy(self) -> SessionEventPolicy:
        return self._policy

    def append(self, event: SessionEventWrite) -> PersistedSessionEvent:
        """Append one event transactionally and return its stored form."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            persisted = self._append_on_connection(conn, event)
            conn.commit()
            return persisted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _append_on_connection(
        self,
        conn: sqlite3.Connection,
        event: SessionEventWrite,
    ) -> PersistedSessionEvent:
        event_id = event.event_id.strip()
        if not event_id or len(event_id) > 128:
            raise ValueError("session event_id must contain 1..128 characters")
        occurred_at = float(event.occurred_at)
        if not math.isfinite(occurred_at):
            raise ValueError("session event occurred_at must be finite")
        stored_session_id = _bounded_field(event.session_id, 256)
        if not stored_session_id:
            raise ValueError("session event requires a non-empty session_id")
        stored_turn_id = _bounded_field(event.turn_id, 256)
        stored_call_id = _bounded_field(event.call_id, 256)
        stored_parent_id = (
            _bounded_field(event.parent_event_id, 256) if event.parent_event_id else None
        )
        stored_role = _bounded_field(event.role, 32)
        stored_status = _bounded_field(event.status, 32)
        stored_model = _bounded_field(event.model, 256)
        stored_provider = _bounded_field(event.provider, 128)
        stored_source = _bounded_field(event.source, 64)
        if not stored_source:
            raise ValueError("session event requires a non-empty source")
        generation = max(1, int(event.session_generation))
        payload = bound_session_payload(event.payload, policy=self._policy)
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        payload_hash = sha256(payload_json.encode("utf-8")).hexdigest()
        cursor = conn.execute(
            """\
            INSERT INTO session_events (
                schema_version, event_id, occurred_at, session_id,
                session_generation, turn_id, call_id, parent_event_id,
                kind, role, status, model, provider, payload_json,
                payload_hash, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SESSION_EVENT_SCHEMA_VERSION,
                event_id,
                occurred_at,
                stored_session_id,
                generation,
                stored_turn_id,
                stored_call_id,
                stored_parent_id,
                event.kind.value,
                stored_role,
                stored_status,
                stored_model,
                stored_provider,
                payload_json,
                payload_hash,
                stored_source,
            ),
        )
        return PersistedSessionEvent(
            id=int(cursor.lastrowid or 0),
            schema_version=SESSION_EVENT_SCHEMA_VERSION,
            event_id=event_id,
            occurred_at=occurred_at,
            session_id=stored_session_id,
            session_generation=generation,
            turn_id=stored_turn_id,
            call_id=stored_call_id,
            parent_event_id=stored_parent_id,
            kind=event.kind.value,
            role=stored_role,
            status=stored_status,
            model=stored_model,
            provider=stored_provider,
            payload=payload,
            payload_hash=payload_hash,
            source=stored_source,
        )

    def read(
        self,
        session_id: str,
        *,
        after_id: int = 0,
        limit: int | None = None,
        turn_id: str | None = None,
        kinds: Sequence[SessionEventKind | str] | None = None,
    ) -> list[PersistedSessionEvent]:
        """Read one session in canonical SQLite order."""
        kind_values = (
            [item.value if isinstance(item, SessionEventKind) else str(item) for item in kinds]
            if kinds
            else None
        )
        encoded_kinds = json.dumps(kind_values) if kind_values is not None else None
        row_limit = max(0, int(limit)) if limit is not None else -1
        params: list[Any] = [
            session_id,
            max(0, int(after_id)),
            turn_id,
            turn_id,
            encoded_kinds,
            encoded_kinds,
            row_limit,
        ]
        conn = self._connect(read_only=True)
        try:
            rows = conn.execute(
                """\
                SELECT * FROM session_events
                WHERE session_id = ?
                  AND id > ?
                  AND (? IS NULL OR turn_id = ?)
                  AND (
                    ? IS NULL
                    OR kind IN (SELECT value FROM json_each(?))
                  )
                ORDER BY id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_session_event(row) for row in rows]

    def count(self, session_id: str) -> int:
        conn = self._connect(read_only=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM session_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0

    def last_touched_at(self, session_id: str) -> float | None:
        """Return the latest canonical event timestamp without loading the stream."""
        conn = self._connect(read_only=True)
        try:
            row = conn.execute(
                "SELECT MAX(occurred_at) FROM session_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def latest_generation(self, session_id: str) -> int:
        """Return the highest durable incarnation for one session."""
        conn = self._connect(read_only=True)
        try:
            row = conn.execute(
                "SELECT MAX(session_generation) FROM session_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        return max(0, int(row[0])) if row and row[0] is not None else 0

    def prune_terminal_sessions(
        self,
        *,
        retention_days: int = SESSION_EVENT_RETENTION_DAYS,
        now: float | None = None,
    ) -> int:
        """Prune only old sessions whose latest event is explicitly terminal.

        Checkpoint metadata has a shorter retention window and may already be
        gone, so eligibility is derived from the immutable stream itself. A
        stale but active session, including a session resumed after an earlier
        terminal generation, can therefore never be removed by this API.
        """
        cutoff = (time.time() if now is None else float(now)) - (
            max(0, int(retention_days)) * 86_400
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            eligible_rows = conn.execute(
                """\
                SELECT terminal.session_id
                FROM session_events AS terminal
                WHERE terminal.kind = ?
                  AND terminal.occurred_at < ?
                  AND terminal.id = (
                      SELECT MAX(latest.id)
                      FROM session_events AS latest
                      WHERE latest.session_id = terminal.session_id
                  )
                """,
                (SessionEventKind.SESSION_ENDED.value, cutoff),
            ).fetchall()
            session_ids = [str(row[0]) for row in eligible_rows]
            if not session_ids:
                conn.commit()
                return 0
            deleted = 0
            for session_id in session_ids:
                cursor = conn.execute(
                    "DELETE FROM session_events WHERE session_id = ?",
                    (session_id,),
                )
                deleted += max(0, int(cursor.rowcount))
            # An import receipt without its canonical rows would make the
            # pruned source permanently non-replayable. Delete both sides of
            # the idempotency contract in the same transaction.
            conn.executemany(
                "DELETE FROM session_event_imports WHERE session_id = ?",
                ((session_id,) for session_id in session_ids),
            )
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def import_legacy_jsonl(
        self,
        path: Path | str,
        *,
        session_id: str | None = None,
    ) -> int:
        """Idempotently import one legacy transcript without modifying it.

        The whole import and its digest receipt share one transaction.
        Deterministic UUIDv5 event ids make a retry safe even after an
        interrupted caller.
        """
        source = Path(path)
        raw = source.read_bytes()
        digest = sha256(raw).hexdigest()
        resolved_session_id = session_id or source.stem
        conn = self._connect()
        try:
            existing = conn.execute(
                """\
                SELECT row_count, session_id
                FROM session_event_imports
                WHERE source_digest = ?
                """,
                (digest,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != resolved_session_id:
                    raise ValueError(
                        "legacy source digest was already imported under a different session_id"
                    )
                return int(existing[0])
            conn.execute("BEGIN IMMEDIATE")
            imported = 0
            generations: dict[str, int] = {}
            for line_number, raw_line in enumerate(raw.splitlines(), start=1):
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict):
                    continue
                row_session_id = str(row.get("session_id") or resolved_session_id)
                current_generation = generations.get(row_session_id, 1)
                if str(row.get("event") or "") == "session_start":
                    current_generation = (
                        current_generation + 1 if row_session_id in generations else 1
                    )
                    generations[row_session_id] = current_generation
                event = _legacy_row_to_event(
                    row,
                    session_id=row_session_id,
                    session_generation=current_generation,
                    event_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            "geode:legacy-transcript:"
                            f"{row_session_id}:{line_number}:{sha256(raw_line).hexdigest()}",
                        )
                    ),
                    source_path=source,
                    source_digest=digest,
                    line_number=line_number,
                )
                try:
                    self._append_on_connection(conn, event)
                except sqlite3.IntegrityError:
                    continue
                imported += 1
            conn.execute(
                """\
                INSERT INTO session_event_imports
                    (source_digest, source_path, session_id, row_count, imported_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (digest, str(source), resolved_session_id, imported, time.time()),
            )
            conn.commit()
            return imported
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


class SessionTimeline:
    """High-level session recorder over :class:`SessionEventStore`."""

    def __init__(
        self,
        session_id: str,
        *,
        db_path: Path | str | None = None,
        projection_path: Path | str | None = None,
        session_generation: int = 1,
        policy: SessionEventPolicy | None = None,
    ) -> None:
        self._session_id = session_id
        self._session_generation = max(1, int(session_generation))
        self._turn_id = ""
        self._event_count = 0
        self._started_generation = 0
        self._record_failures = 0
        self._store = SessionEventStore(db_path, policy=policy)
        self._projection_explicit = projection_path is not None
        if projection_path is None:
            from core.observability.run_dir import resolve_sub_agent_path

            projection = resolve_sub_agent_path(session_id, "events.jsonl")
        else:
            projection = Path(projection_path)
        self._projection_path = projection
        self._projection_failed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    @property
    def projection_path(self) -> Path | None:
        return self._projection_path

    @property
    def projection_failed(self) -> bool:
        return self._projection_failed

    @property
    def record_failed(self) -> bool:
        return self._record_failures > 0

    @property
    def record_failures(self) -> int:
        return self._record_failures

    def bind_turn(self, turn_id: str, *, session_generation: int | None = None) -> None:
        self._turn_id = turn_id
        if session_generation is not None:
            self._session_generation = max(1, int(session_generation))

    def rebind(self, session_id: str, *, session_generation: int) -> None:
        """Rebind after resume so history follows the restored session id."""
        self._session_id = session_id
        self._session_generation = max(1, int(session_generation))
        self._turn_id = ""
        self._started_generation = 0
        if not self._projection_explicit:
            from core.observability.run_dir import resolve_sub_agent_path

            self._projection_path = resolve_sub_agent_path(session_id, "events.jsonl")

    def next_generation(self, session_id: str) -> int:
        """Allocate the next generation from durable history, not process state."""
        return max(self._session_generation, self._store.latest_generation(session_id)) + 1

    def record_session_start(self, *, model: str = "", provider: str = "anthropic") -> None:
        if self._started_generation == self._session_generation:
            return
        persisted = self._record(
            SessionEventKind.SESSION_STARTED,
            model=model,
            provider=provider,
            status="active",
        )
        if persisted is not None:
            self._started_generation = self._session_generation

    def record_session_end(
        self,
        *,
        status: str = "completed",
        duration_s: float = 0,
        total_cost: float = 0,
        rounds: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self._record(
            SessionEventKind.SESSION_ENDED,
            status=status,
            payload={
                "duration_s": round(duration_s, 3),
                "total_cost_usd": round(total_cost, 6),
                "rounds": rounds,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "record_failures": self._record_failures,
                "projection_failed": self._projection_failed,
            },
        )

    def record_user_message(self, text: str) -> None:
        self._record(
            SessionEventKind.USER_MESSAGE,
            role="user",
            payload={"content": text},
        )

    def record_assistant_message(self, text: str) -> None:
        self._record(
            SessionEventKind.ASSISTANT_MESSAGE,
            role="assistant",
            payload={"content": text},
        )

    def record_turn_complete(
        self,
        *,
        termination_reason: str,
        rounds: int,
        tool_call_count: int,
        error: str = "",
        failed: bool = False,
        successful: bool | None = None,
        verify: Mapping[str, Any] | None = None,
    ) -> None:
        """Persist the turn outcome without closing the session lifetime."""
        if successful is True:
            turn_status = "completed"
        elif error or failed:
            turn_status = "error"
        else:
            turn_status = "interrupted"
        self._record(
            SessionEventKind.TURN_COMPLETED,
            status=turn_status,
            payload={
                "termination_reason": termination_reason,
                "rounds": rounds,
                "tool_call_count": tool_call_count,
                "error": error,
                "failed": bool(failed),
                "successful": bool(successful),
                "verify": dict(verify) if verify is not None else None,
            },
        )

    def record_verification_continuation(
        self,
        instruction: str,
        *,
        root_turn_id: str,
        verify_attempt: int,
    ) -> None:
        """Persist an external verification control edge, never a user turn."""
        self._record(
            SessionEventKind.VERIFICATION_CONTINUED,
            role="policy",
            payload={
                "instruction": instruction,
                "root_turn_id": root_turn_id,
                "verify_attempt": max(0, int(verify_attempt)),
                "source": "post_verify_or_stop",
            },
        )

    def record_verification_evidence(
        self,
        references: Sequence[Mapping[str, Any]],
        *,
        root_turn_id: str,
        verify_attempt: int,
        policy_action: str,
    ) -> None:
        """Persist typed external-evidence joins for trajectory projection."""
        self._record(
            SessionEventKind.VERIFICATION_EVIDENCE,
            role="policy",
            payload={
                "references": [dict(reference) for reference in references],
                "root_turn_id": root_turn_id,
                "verify_attempt": max(0, int(verify_attempt)),
                "policy_action": policy_action,
            },
        )

    def record_verification_pending(
        self,
        *,
        candidate: str,
        root_turn_id: str,
        verify_attempt: int,
        references: Sequence[Mapping[str, Any]],
    ) -> None:
        """Persist an externally-owned delivery gate without exposing text."""
        candidate_bytes = candidate.encode("utf-8")
        self._record(
            SessionEventKind.VERIFICATION_PENDING,
            role="policy",
            status="pending",
            payload={
                "candidate_sha256": sha256(candidate_bytes).hexdigest(),
                "candidate_bytes": len(candidate_bytes),
                "root_turn_id": root_turn_id,
                "verify_attempt": max(0, int(verify_attempt)),
                "references": [dict(reference) for reference in references],
            },
        )

    def record_tool_call(
        self,
        tool: str,
        tool_input: dict[str, Any],
        call_id: str = "",
    ) -> None:
        self._record(
            SessionEventKind.TOOL_CALLED,
            call_id=call_id,
            payload={"tool": tool, "arguments": tool_input},
        )

    def record_tool_result(
        self,
        tool: str,
        status: str,
        summary: str = "",
        call_id: str = "",
        *,
        result: Any | None = None,
    ) -> None:
        self._record(
            SessionEventKind.TOOL_COMPLETED,
            call_id=call_id,
            status=status,
            payload={"tool": tool, "summary": summary, "result": result},
        )

    def record_vault_save(self, path: str, category: str) -> None:
        self._record(
            SessionEventKind.ARTIFACT_SAVED,
            payload={"path": path, "category": category},
        )

    def record_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        self._record(
            SessionEventKind.USAGE_RECORDED,
            model=model,
            payload={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost_usd, 6),
            },
        )

    def record_error(self, error_type: str, message: str) -> None:
        self._record(
            SessionEventKind.ERROR_RECORDED,
            status="error",
            payload={"error_type": error_type, "message": message},
        )

    def record_subagent_start(
        self,
        task_id: str,
        task_type: str = "",
        *,
        child_session_key: str = "",
        run_id: str = "",
    ) -> None:
        self._record(
            SessionEventKind.SUBAGENT_STARTED,
            call_id=run_id,
            payload={
                "task_id": task_id,
                "task_type": task_type,
                "child_session_key": child_session_key,
            },
        )

    def record_subagent_complete(
        self,
        task_id: str,
        status: str,
        summary: str = "",
        *,
        child_session_key: str = "",
        run_id: str = "",
    ) -> None:
        self._record(
            SessionEventKind.SUBAGENT_STOPPED,
            call_id=run_id,
            status=status,
            payload={
                "task_id": task_id,
                "summary": summary,
                "child_session_key": child_session_key,
            },
        )

    def record_lifecycle_event(
        self,
        *,
        event: str,
        payload: dict[str, Any] | None = None,
        level: str = "info",
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        **_legacy: Any,
    ) -> None:
        """Compatibility entry for the three typed runtime markers still used."""
        kind = {
            "gui_step": SessionEventKind.GUI_STEP,
            "task_preflight": SessionEventKind.PREFLIGHT_RECORDED,
            "handoff_triggered": SessionEventKind.HANDOFF_TRIGGERED,
        }.get(event)
        if kind is None:
            raise ValueError(f"unsupported session lifecycle event: {event!r}")
        body = dict(payload or {})
        body.update(
            {
                "level": level,
                "action": action or "",
                "entity_type": entity_type or "",
                "entity_id": entity_id or "",
            }
        )
        self._record(kind, payload=body)

    def read_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._store.read(self._session_id)
        return [row.as_dict() for row in rows[-max(0, limit) :]]

    def last_touched_at(self) -> float | None:
        return self._store.last_touched_at(self._session_id)

    def is_stale(self, threshold_s: float, *, now: float | None = None) -> bool:
        touched = self.last_touched_at()
        if touched is None:
            return False
        return ((time.time() if now is None else now) - touched) > threshold_s

    def _record(
        self,
        kind: SessionEventKind,
        *,
        call_id: str = "",
        role: str = "",
        status: str = "",
        model: str = "",
        provider: str = "",
        payload: dict[str, Any] | None = None,
    ) -> PersistedSessionEvent | None:
        try:
            persisted = self._store.append(
                SessionEventWrite(
                    session_id=self._session_id,
                    session_generation=self._session_generation,
                    turn_id=self._turn_id,
                    call_id=call_id,
                    kind=kind,
                    role=role,
                    status=status,
                    model=model,
                    provider=provider,
                    payload=payload or {},
                )
            )
        except Exception as exc:
            self._record_failures += 1
            log.warning(
                "Canonical session event write failed (session=%s kind=%s): %s",
                self._session_id,
                kind.value,
                exc,
            )
            return None
        self._event_count += 1
        self._append_projection(persisted)
        return persisted

    def _append_projection(self, event: PersistedSessionEvent) -> None:
        path = self._projection_path
        if path is None:
            return
        try:
            from core.memory.atomic_write import append_jsonl

            append_jsonl(path, _session_event_projection(event))
            if path.stat().st_size > self._store.policy.max_projection_bytes:
                from core.self_improving.loop.observe.run_timeline import (
                    compact_run_timeline,
                )

                compact_run_timeline(
                    path,
                    self._store.policy.max_projection_bytes,
                    session_id=event.session_id,
                    gen_tag="",
                    component="agentic_loop",
                    ordinal=event.id,
                )
        except (OSError, UnicodeError) as exc:
            self._projection_failed = True
            log.warning("Session event projection failed for %s: %s", path, exc)


def set_current_session_timeline(timeline: SessionTimeline | None) -> None:
    """Bind the active parent timeline for nested artifact/subagent producers."""
    _CURRENT_SESSION_TIMELINE.set(timeline)


def current_session_timeline() -> SessionTimeline | None:
    """Return the task-local canonical timeline, when an agent turn owns one."""
    return _CURRENT_SESSION_TIMELINE.get()


def bound_session_payload(
    payload: Mapping[str, Any],
    *,
    policy: SessionEventPolicy | None = None,
) -> dict[str, Any]:
    """Redact secrets and bound a session-history payload."""
    active = policy or SessionEventPolicy()
    bounded = _bounded_value(payload, active, depth=0)
    result = bounded if isinstance(bounded, dict) else {"value": bounded}
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    size = len(encoded.encode("utf-8"))
    if size <= active.max_payload_bytes:
        return result
    return {
        "_truncated": True,
        "original_bytes": size,
        "keys": list(result)[: active.max_collection_items],
        "payload_hash": sha256(encoded.encode("utf-8")).hexdigest(),
    }


def _bounded_value(value: Any, policy: SessionEventPolicy, *, depth: int) -> Any:
    if depth >= policy.max_depth:
        return {"_truncated": "max_depth"}
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return redact_and_bound_text(value, policy.max_string_chars)
    if isinstance(value, bytes | bytearray | memoryview):
        return {"_omitted_type": "bytes", "size": len(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        items = list(islice(value.items(), policy.max_collection_items))
        for raw_key, item in items:
            key = redact_and_bound_text(raw_key, 128)
            if key.lower() in _SENSITIVE_PAYLOAD_KEYS:
                result[key] = "<REDACTED>"
            else:
                result[key] = _bounded_value(item, policy, depth=depth + 1)
        if len(value) > policy.max_collection_items:
            result["_truncated_items"] = len(value) - policy.max_collection_items
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = list(islice(value, policy.max_collection_items))
        sequence_result = [_bounded_value(item, policy, depth=depth + 1) for item in items]
        if len(value) > policy.max_collection_items:
            sequence_result.append({"_truncated_items": len(value) - policy.max_collection_items})
        return sequence_result
    return {"_omitted_type": type(value).__name__}


def _bounded_field(value: Any, max_chars: int) -> str:
    """Bound a schema-constrained field without exceeding its declared max."""
    text = redact_secrets(str(value or ""))
    if len(text) <= max_chars:
        return text
    suffix = ":" + sha256(text.encode("utf-8")).hexdigest()[:16]
    return text[: max_chars - len(suffix)] + suffix


def _row_to_session_event(row: sqlite3.Row) -> PersistedSessionEvent:
    corrupt = False
    payload_json = str(row["payload_json"])
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        payload = {"_corrupt_payload": True}
        corrupt = True
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if not corrupt and sha256(payload_json.encode("utf-8")).hexdigest() != str(row["payload_hash"]):
        payload = {
            "_corrupt_payload": True,
            "_corrupt_reason": "payload_hash_mismatch",
        }
        corrupt = True
    return PersistedSessionEvent(
        id=int(row["id"]),
        schema_version=int(row["schema_version"]),
        event_id=str(row["event_id"]),
        occurred_at=float(row["occurred_at"]),
        session_id=str(row["session_id"]),
        session_generation=int(row["session_generation"]),
        turn_id=str(row["turn_id"]),
        call_id=str(row["call_id"]),
        parent_event_id=(
            str(row["parent_event_id"]) if row["parent_event_id"] is not None else None
        ),
        kind=str(row["kind"]),
        role=str(row["role"]),
        status=str(row["status"]),
        model=str(row["model"]),
        provider=str(row["provider"]),
        payload=payload,
        payload_hash=str(row["payload_hash"]),
        source=str(row["source"]),
        corrupt_payload=corrupt,
    )


def _legacy_row_to_event(
    row: dict[str, Any],
    *,
    session_id: str,
    session_generation: int,
    event_id: str,
    source_path: Path,
    source_digest: str,
    line_number: int,
) -> SessionEventWrite:
    legacy_kind = str(row.get("event") or "")
    kind = {
        "session_start": SessionEventKind.SESSION_STARTED,
        "session_end": SessionEventKind.SESSION_ENDED,
        "user_message": SessionEventKind.USER_MESSAGE,
        "assistant_message": SessionEventKind.ASSISTANT_MESSAGE,
        "tool_call": SessionEventKind.TOOL_CALLED,
        "tool_result": SessionEventKind.TOOL_COMPLETED,
        "subagent_start": SessionEventKind.SUBAGENT_STARTED,
        "subagent_complete": SessionEventKind.SUBAGENT_STOPPED,
        "vault_save": SessionEventKind.ARTIFACT_SAVED,
        "cost": SessionEventKind.USAGE_RECORDED,
        "error": SessionEventKind.ERROR_RECORDED,
        "gui_step": SessionEventKind.GUI_STEP,
        "task_preflight": SessionEventKind.PREFLIGHT_RECORDED,
        "handoff_triggered": SessionEventKind.HANDOFF_TRIGGERED,
    }.get(legacy_kind, SessionEventKind.LEGACY_IMPORTED)
    reserved = {
        "event",
        "ts",
        "seq",
        "session_id",
        "turn_id",
        "call_id",
        "model",
        "provider",
        "status",
        "text",
        "tool",
        "input",
        "summary",
    }
    payload = {key: value for key, value in row.items() if key not in reserved}
    payload["_legacy"] = {
        "event": legacy_kind,
        "line_number": line_number,
        "source_digest": source_digest,
        "source_path": str(source_path),
    }
    raw_timestamp = row.get("ts")
    try:
        occurred_at = (
            float(raw_timestamp) if raw_timestamp is not None else source_path.stat().st_mtime
        )
        if not math.isfinite(occurred_at):
            raise ValueError
    except (TypeError, ValueError):
        occurred_at = source_path.stat().st_mtime
        payload["_legacy"]["timestamp_invalid"] = True
    role = ""
    if kind is SessionEventKind.USER_MESSAGE:
        role = "user"
        payload = {"content": row.get("text", ""), **payload}
    elif kind is SessionEventKind.ASSISTANT_MESSAGE:
        role = "assistant"
        payload = {"content": row.get("text", ""), **payload}
    elif kind is SessionEventKind.TOOL_CALLED:
        raw_arguments = row.get("input")
        if isinstance(raw_arguments, dict):
            arguments = raw_arguments
        elif isinstance(raw_arguments, str):
            try:
                decoded = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {"_legacy_fragment": raw_arguments}
            else:
                arguments = decoded if isinstance(decoded, dict) else {"_value": decoded}
        else:
            arguments = {}
        payload = {
            "tool": str(row.get("tool") or ""),
            "arguments": arguments,
            **payload,
        }
    elif kind is SessionEventKind.TOOL_COMPLETED:
        payload = {
            "tool": str(row.get("tool") or ""),
            "summary": str(row.get("summary") or ""),
            **payload,
        }
    return SessionEventWrite(
        session_id=session_id,
        session_generation=session_generation,
        event_id=event_id,
        occurred_at=occurred_at,
        kind=kind,
        turn_id=str(row.get("turn_id") or ""),
        call_id=str(row.get("call_id") or ""),
        role=role,
        status=str(row.get("status") or ""),
        model=str(row.get("model") or ""),
        provider=str(row.get("provider") or ""),
        payload=payload,
        source="legacy_jsonl",
    )


def _session_event_projection(event: PersistedSessionEvent) -> dict[str, Any]:
    """Project canonical SQLite history into one ``geode.run-event@1`` row."""
    from core.self_improving.loop.observe.run_timeline import (
        RUN_EVENT_SCHEMA_ID,
        RUN_EVENT_SCHEMA_VERSION,
    )

    actor_type = event.role or (
        "tool" if event.kind == SessionEventKind.TOOL_COMPLETED else "agent"
    )
    return {
        "schema_id": RUN_EVENT_SCHEMA_ID,
        "schema_version": RUN_EVENT_SCHEMA_VERSION,
        "event_id": event.event_id,
        "occurred_at": event.occurred_at,
        "ts": event.occurred_at,
        "ordinal": event.id,
        "seq": event.id,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "call_id": event.call_id,
        "gen_tag": "",
        "component": "agentic_loop",
        "level": "error" if event.status == "error" else "info",
        "kind": event.kind,
        "event": event.kind,
        "actor_type": actor_type,
        "actor_id": event.session_id,
        "action": event.kind,
        "entity_type": "session",
        "entity_id": event.session_id,
        "task_id": "",
        "payload": {
            **event.payload,
            "session_generation": event.session_generation,
            "parent_event_id": event.parent_event_id,
            "role": event.role,
            "status": event.status,
            "model": event.model,
            "provider": event.provider,
            "source": event.source,
            "payload_hash": event.payload_hash,
        },
    }


__all__ = [
    "SESSION_EVENT_RETENTION_DAYS",
    "SESSION_EVENT_SCHEMA_ID",
    "SESSION_EVENT_SCHEMA_VERSION",
    "PersistedSessionEvent",
    "SessionEventKind",
    "SessionEventPolicy",
    "SessionEventStore",
    "SessionEventWrite",
    "SessionTimeline",
    "bound_session_payload",
    "current_session_timeline",
    "ensure_session_event_schema",
    "set_current_session_timeline",
]
