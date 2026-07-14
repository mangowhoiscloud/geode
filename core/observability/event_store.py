"""Bounded SQLite persistence for HookSystem operational events."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import islice
from pathlib import Path
from typing import Any

from core.hooks.catalog import EventRetentionClass
from core.hooks.system import COLLAPSED_EVENT_VALUES, LEGACY_EVENT_VALUES
from core.observability.redaction import redact_secrets

log = logging.getLogger(__name__)


def _event_filter_variants(event_filter: str) -> list[str]:
    """Expand an event filter with its legacy/canonical value siblings.

    ``LEGACY_EVENT_VALUES`` maps old stored value -> current enum value;
    a canonical filter gains its legacy spellings and a legacy filter
    gains the canonical one, so pre-rename SQLite rows keep matching.
    """
    variants = [event_filter]
    canonical = LEGACY_EVENT_VALUES.get(event_filter)
    if canonical is not None:
        variants.append(canonical)
    variants.extend(old for old, new in LEGACY_EVENT_VALUES.items() if new == event_filter)
    # Collapsed families (D2/D3): a canonical filter also returns the
    # pre-collapse per-state rows.
    variants.extend(COLLAPSED_EVENT_VALUES.get(event_filter, ()))
    return variants


# v2 (PR-HOOK-TAXONOMY, 2026-07-14): event vocabulary — tense-aligned
# values, collapsed D2/D3 families; readers use the alias/collapsed maps.
EVENT_SCHEMA_VERSION = 2

_CREATE_HOOK_EVENTS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS hook_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version      INTEGER NOT NULL,
    occurred_at         REAL NOT NULL,
    session_key         TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    event               TEXT NOT NULL,
    dispatch_mode       TEXT NOT NULL,
    status              TEXT NOT NULL,
    retention_class     TEXT NOT NULL,
    handler_count       INTEGER NOT NULL DEFAULT 0,
    handler_error_count INTEGER NOT NULL DEFAULT 0,
    blocked             INTEGER NOT NULL DEFAULT 0,
    block_reason        TEXT NOT NULL DEFAULT '',
    actor_type          TEXT NOT NULL,
    actor_id            TEXT NOT NULL,
    action              TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    task_id             TEXT,
    level               TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    payload_hash        TEXT NOT NULL
)
"""

_HOOK_EVENT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_hook_events_session ON hook_events "
    "(session_key, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hook_events_run ON hook_events (run_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_hook_events_event ON hook_events (event, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hook_events_action ON hook_events (action, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hook_events_retention ON hook_events "
    "(retention_class, occurred_at)",
)

_FORBIDDEN_PERSISTED_KEYS = frozenset(
    {
        "api_key",
        "args_preview",
        "authorization",
        "base64",
        "body",
        "cognitive_state",
        "comment",
        "content",
        "cookie",
        "detail",
        "error",
        "error_msg",
        "headers",
        "image",
        "input",
        "kwargs",
        "message",
        "messages",
        "outcome",
        "output",
        "password",
        "prompt",
        "query",
        "raw_input",
        "reason",
        "response",
        "result",
        "screenshot",
        "secret",
        "subject",
        "system_prompt",
        "text",
        "token",
        "tool_input",
        "user_input",
    }
)


def ensure_event_schema(conn: sqlite3.Connection) -> None:
    """Create the additive event table and indexes on ``conn``."""
    conn.execute(_CREATE_HOOK_EVENTS_TABLE_SQL)
    for statement in _HOOK_EVENT_INDEXES:
        conn.execute(statement)


@dataclass(frozen=True, slots=True)
class EventRetentionPolicy:
    """Storage bounds for one project-local event database."""

    high_volume_days: float = 7.0
    standard_days: float = 30.0
    audit_days: float = 180.0
    max_rows: int = 100_000
    prune_every: int = 256
    max_payload_bytes: int = 8 * 1024
    max_string_chars: int = 512
    max_collection_items: int = 32
    max_depth: int = 6

    def days_for(self, retention_class: EventRetentionClass) -> float:
        if retention_class is EventRetentionClass.HIGH_VOLUME:
            return self.high_volume_days
        if retention_class is EventRetentionClass.AUDIT:
            return self.audit_days
        return self.standard_days


@dataclass(frozen=True, slots=True)
class HookEventWrite:
    """Validated input envelope accepted by :class:`HookEventStore`."""

    occurred_at: float
    session_key: str
    run_id: str
    event: str
    dispatch_mode: str
    status: str
    retention_class: EventRetentionClass
    handler_count: int
    handler_error_count: int
    blocked: bool
    block_reason: str
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    task_id: str | None
    level: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersistedHookEvent:
    id: int
    schema_version: int
    occurred_at: float
    session_key: str
    run_id: str
    event: str
    dispatch_mode: str
    status: str
    retention_class: str
    handler_count: int
    handler_error_count: int
    blocked: bool
    block_reason: str
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    task_id: str | None
    level: str
    payload: dict[str, Any]
    payload_hash: str


class HookEventStore:
    """Thread-safe, bounded writer/reader over ``sessions.db:hook_events``.

    Connections are scoped to individual operations. Hook systems can be
    retained by application callbacks longer than their logical runtime; a
    persistent connection would turn that object retention into three leaked
    descriptors (database, WAL, and SHM). SQLite persists WAL mode in the
    database, so short connections preserve the concurrency contract without
    coupling descriptor lifetime to garbage collection.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        retention: EventRetentionPolicy | None = None,
    ) -> None:
        if db_path is None:
            from core.memory.session_manager import _get_default_db_path

            resolved_path = _get_default_db_path()
        else:
            resolved_path = Path(db_path)
        self._db_path = resolved_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._retention = retention or EventRetentionPolicy()
        self._lock = threading.Lock()
        self._writes_since_prune = 0
        self._closed = False
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            ensure_event_schema(conn)
            conn.commit()
        finally:
            conn.close()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def closed(self) -> bool:
        return self._closed

    def append(self, record: HookEventWrite) -> int:
        """Persist one bounded event and return its SQLite row id."""
        payload_json = _bounded_payload_json(record.payload, self._retention)
        payload_hash = sha256(payload_json.encode("utf-8")).hexdigest()
        with self._lock:
            self._assert_open_locked()
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """\
                    INSERT INTO hook_events (
                        schema_version, occurred_at, session_key, run_id, event,
                        dispatch_mode, status, retention_class, handler_count,
                        handler_error_count, blocked, block_reason, actor_type,
                        actor_id, action, entity_type, entity_id, task_id, level,
                        payload_json, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        EVENT_SCHEMA_VERSION,
                        float(record.occurred_at),
                        _bounded_text(record.session_key, 256),
                        _bounded_text(record.run_id, 256),
                        _bounded_text(record.event, 128),
                        _bounded_text(record.dispatch_mode, 32),
                        _bounded_text(record.status, 32),
                        record.retention_class.value,
                        max(0, int(record.handler_count)),
                        max(0, int(record.handler_error_count)),
                        int(record.blocked),
                        _bounded_text(record.block_reason, self._retention.max_string_chars),
                        _bounded_text(record.actor_type, 32),
                        _bounded_text(record.actor_id, 256),
                        _bounded_text(record.action, 128),
                        _bounded_text(record.entity_type, 64),
                        _bounded_text(record.entity_id, 256),
                        _bounded_text(record.task_id, 256) if record.task_id else None,
                        _bounded_text(record.level, 16),
                        payload_json,
                        payload_hash,
                    ),
                )
                self._writes_since_prune += 1
                if (
                    self._retention.prune_every > 0
                    and self._writes_since_prune >= self._retention.prune_every
                ):
                    self._prune_locked(conn, now=time.time())
                    self._writes_since_prune = 0
                conn.commit()
                return int(cursor.lastrowid or 0)
            finally:
                conn.close()

    def read(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        session_key: str | None = None,
        run_id: str | None = None,
        event_filter: str | None = None,
        status_filter: str | None = None,
        occurred_after: float | None = None,
        occurred_before: float | None = None,
    ) -> list[PersistedHookEvent]:
        """Read newest events with indexed filters.

        ``event_filter`` is alias-aware (PR-HOOK-TAXONOMY D5): filtering on
        a canonical event value also matches rows stored under its legacy
        pre-rename value (and vice versa), so history written before the
        NAME == VALUE.upper() alignment stays queryable.
        """
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("session_key", session_key),
            ("run_id", run_id),
            ("status", status_filter),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if event_filter is not None:
            variants = _event_filter_variants(event_filter)
            placeholders = ", ".join("?" for _variant in variants)
            clauses.append(f"event IN ({placeholders})")
            params.extend(variants)
        if occurred_after is not None:
            clauses.append("occurred_at >= ?")
            params.append(occurred_after)
        if occurred_before is not None:
            clauses.append("occurred_at <= ?")
            params.append(occurred_before)
        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(0, int(limit)), max(0, int(offset))))
        with self._lock:
            self._assert_open_locked()
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"""\
                    SELECT * FROM hook_events{where_sql}
                    ORDER BY occurred_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,  # noqa: S608 - clauses fixed above; values parameterized  # nosec B608
                    params,
                ).fetchall()
            finally:
                conn.close()
        return [_row_to_event(row) for row in rows]

    def count(self, *, session_key: str | None = None) -> int:
        with self._lock:
            self._assert_open_locked()
            conn = self._connect()
            try:
                if session_key is None:
                    row = conn.execute("SELECT COUNT(*) FROM hook_events").fetchone()
                else:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM hook_events WHERE session_key = ?",
                        (session_key,),
                    ).fetchone()
            finally:
                conn.close()
        return int(row[0]) if row else 0

    def prune(self, *, now: float | None = None) -> int:
        """Apply age buckets and the global row cap; return rows removed."""
        with self._lock:
            self._assert_open_locked()
            conn = self._connect()
            try:
                removed = self._prune_locked(
                    conn,
                    now=time.time() if now is None else now,
                )
                conn.commit()
                self._writes_since_prune = 0
                return removed
            finally:
                conn.close()

    def _prune_locked(self, conn: sqlite3.Connection, *, now: float) -> int:
        before = conn.total_changes
        for retention_class in (
            EventRetentionClass.HIGH_VOLUME,
            EventRetentionClass.STANDARD,
            EventRetentionClass.AUDIT,
        ):
            days = self._retention.days_for(retention_class)
            if days <= 0:
                continue
            cutoff = now - days * 86_400
            conn.execute(
                "DELETE FROM hook_events WHERE retention_class = ? AND occurred_at < ?",
                (retention_class.value, cutoff),
            )

        if self._retention.max_rows > 0:
            threshold = conn.execute(
                "SELECT id FROM hook_events ORDER BY id DESC LIMIT 1 OFFSET ?",
                (self._retention.max_rows - 1,),
            ).fetchone()
            if threshold is not None:
                conn.execute("DELETE FROM hook_events WHERE id < ?", (int(threshold[0]),))
        return conn.total_changes - before

    def clear(self) -> int:
        with self._lock:
            self._assert_open_locked()
            conn = self._connect()
            try:
                cursor = conn.execute("DELETE FROM hook_events")
                conn.commit()
                return max(0, int(cursor.rowcount))
            finally:
                conn.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _assert_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("HookEventStore is closed")


def _bounded_text(value: Any, max_chars: int) -> str:
    text = redact_secrets(str(value or ""))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…[truncated:{len(text) - max_chars}]"


def _bounded_payload_json(payload: dict[str, Any], policy: EventRetentionPolicy) -> str:
    bounded = bound_event_payload(payload, policy=policy)
    encoded = json.dumps(
        bounded,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    return encoded


def bound_event_payload(
    payload: Mapping[str, Any],
    *,
    policy: EventRetentionPolicy | None = None,
) -> dict[str, Any]:
    """Return a secret-redacted, structurally bounded payload copy."""
    active_policy = policy or EventRetentionPolicy()
    bounded = _bounded_value(payload, active_policy, depth=0)
    result = bounded if isinstance(bounded, dict) else {"value": bounded}
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    size = len(encoded.encode("utf-8"))
    if size <= active_policy.max_payload_bytes:
        return result
    return {
        "_truncated": True,
        "original_bytes": size,
        "keys": list(result)[: active_policy.max_collection_items],
    }


def _bounded_value(value: Any, policy: EventRetentionPolicy, *, depth: int) -> Any:
    if depth >= policy.max_depth:
        return {"_truncated": "max_depth"}
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _bounded_text(value, policy.max_string_chars)
    if isinstance(value, bytes | bytearray | memoryview):
        return {"_omitted_type": "bytes", "size": len(value)}
    if isinstance(value, Mapping):
        bounded: dict[str, Any] = {}
        redacted_fields: list[str] = []
        items = list(islice(value.items(), policy.max_collection_items))
        for raw_key, item in items:
            key = _bounded_text(raw_key, 128)
            if key.lower() in _FORBIDDEN_PERSISTED_KEYS:
                redacted_fields.append(key)
                continue
            bounded[key] = _bounded_value(item, policy, depth=depth + 1)
        if redacted_fields:
            bounded["_redacted_fields"] = sorted(redacted_fields)
        if len(value) > policy.max_collection_items:
            bounded["_truncated_items"] = len(value) - policy.max_collection_items
        return bounded
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = list(islice(value, policy.max_collection_items))
        bounded_items = [_bounded_value(item, policy, depth=depth + 1) for item in items]
        if len(value) > policy.max_collection_items:
            bounded_items.append({"_truncated_items": len(value) - policy.max_collection_items})
        return bounded_items
    return {"_omitted_type": type(value).__name__}


def _row_to_event(row: sqlite3.Row) -> PersistedHookEvent:
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        payload = {"_corrupt_payload": True}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return PersistedHookEvent(
        id=int(row["id"]),
        schema_version=int(row["schema_version"]),
        occurred_at=float(row["occurred_at"]),
        session_key=str(row["session_key"]),
        run_id=str(row["run_id"]),
        event=str(row["event"]),
        dispatch_mode=str(row["dispatch_mode"]),
        status=str(row["status"]),
        retention_class=str(row["retention_class"]),
        handler_count=int(row["handler_count"]),
        handler_error_count=int(row["handler_error_count"]),
        blocked=bool(row["blocked"]),
        block_reason=str(row["block_reason"]),
        actor_type=str(row["actor_type"]),
        actor_id=str(row["actor_id"]),
        action=str(row["action"]),
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        task_id=str(row["task_id"]) if row["task_id"] is not None else None,
        level=str(row["level"]),
        payload=payload,
        payload_hash=str(row["payload_hash"]),
    )


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "EventRetentionPolicy",
    "HookEventStore",
    "HookEventWrite",
    "PersistedHookEvent",
    "bound_event_payload",
    "ensure_event_schema",
]
