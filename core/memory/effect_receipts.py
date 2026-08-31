"""Durable admission receipts for effectful tool operations."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.memory.sqlite_store import short_sqlite_connection
from core.observability.session_timeline import SessionEventPolicy, bound_session_payload

_RETENTION_SECONDS = 30 * 24 * 60 * 60
_MAX_COMMITTED_RECEIPTS = 2_000
_MAX_UNCERTAIN_RECEIPTS = 500
_RESULT_POLICY = SessionEventPolicy(
    max_payload_bytes=32 * 1024,
    max_string_chars=12_000,
    max_collection_items=128,
    max_depth=8,
)

_CREATE_EFFECT_RECEIPTS_SQL = """\
CREATE TABLE IF NOT EXISTS effect_receipts (
    operation_id        TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    tool_call_id        TEXT NOT NULL,
    tool_name           TEXT NOT NULL,
    effect              TEXT NOT NULL,
    argument_fingerprint TEXT NOT NULL,
    personal_data       INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL CHECK (status IN ('prepared', 'committed')),
    result_json         TEXT NOT NULL DEFAULT '',
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
)
"""


def ensure_effect_receipt_schema(conn: sqlite3.Connection) -> None:
    """Create the additive effect-receipt projection."""
    conn.execute(_CREATE_EFFECT_RECEIPTS_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_effect_receipts_session "
        "ON effect_receipts (session_id, updated_at DESC)"
    )


def effect_operation_id(session_id: str, tool_call_id: str) -> str:
    """Return the stable logical ID issued for one runtime tool operation."""
    if not session_id or not tool_call_id:
        return ""
    identity = f"geode://sessions/{session_id}/tool-calls/{tool_call_id}"
    return f"op-{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"


class EffectAdmissionKind(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class EffectAdmission:
    kind: EffectAdmissionKind
    result: dict[str, Any] | None = None


class EffectReceiptCapacityError(RuntimeError):
    """The bounded unresolved-receipt budget is exhausted."""


def _argument_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"tool_name": tool_name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


class EffectReceiptStore:
    """Short-connection store sharing the project-local ``sessions.db``."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            from core.paths import resolve_sessions_dir

            db_path = resolve_sessions_dir() / "sessions.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def admit(
        self,
        *,
        operation_id: str,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        effect: str,
        arguments: dict[str, Any],
        personal_data: bool,
    ) -> EffectAdmission:
        """Atomically admit, replay, reject, or quarantine one operation."""
        if not operation_id or not session_id or not tool_name:
            raise ValueError("operation_id, session_id, and tool_name are required")
        fingerprint = _argument_fingerprint(tool_name, arguments)
        now = time.time()
        with short_sqlite_connection(
            self._db_path, ensure_effect_receipt_schema, immediate=True
        ) as conn:
            self._prune_committed_locked(conn, now)
            row = conn.execute(
                "SELECT * FROM effect_receipts WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is not None:
                matches = (
                    str(row["session_id"]) == session_id
                    and str(row["tool_name"]) == tool_name
                    and str(row["effect"]) == effect
                    and str(row["argument_fingerprint"]) == fingerprint
                    and bool(row["personal_data"]) is personal_data
                )
                if not matches:
                    return EffectAdmission(EffectAdmissionKind.CONFLICT)
                if str(row["status"]) == "committed":
                    result = json.loads(str(row["result_json"]))
                    if not isinstance(result, dict):
                        raise RuntimeError("committed effect receipt result is not an object")
                    return EffectAdmission(EffectAdmissionKind.REPLAY, result)
                return EffectAdmission(EffectAdmissionKind.UNCERTAIN)

            unresolved = conn.execute(
                "SELECT COUNT(*) FROM effect_receipts WHERE status = 'prepared'"
            ).fetchone()
            if unresolved is not None and int(unresolved[0]) >= _MAX_UNCERTAIN_RECEIPTS:
                raise EffectReceiptCapacityError(
                    "effect receipt capacity exhausted; reconcile uncertain operations"
                )
            conn.execute(
                """INSERT INTO effect_receipts
                       (operation_id, session_id, tool_call_id, tool_name, effect,
                        argument_fingerprint, personal_data, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)""",
                (
                    operation_id,
                    session_id,
                    tool_call_id,
                    tool_name,
                    effect,
                    fingerprint,
                    int(personal_data),
                    now,
                    now,
                ),
            )
        return EffectAdmission(EffectAdmissionKind.NEW)

    def commit(self, operation_id: str, result: dict[str, Any]) -> None:
        """Commit one bounded result after the terminal handler returns."""
        durable = bound_session_payload(result, policy=_RESULT_POLICY)
        encoded = json.dumps(
            durable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with short_sqlite_connection(
            self._db_path, ensure_effect_receipt_schema, immediate=True
        ) as conn:
            updated = conn.execute(
                """UPDATE effect_receipts
                   SET status = 'committed', result_json = ?, updated_at = ?
                   WHERE operation_id = ? AND status = 'prepared'""",
                (encoded, time.time(), operation_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("effect receipt is missing or already committed")

    @staticmethod
    def _prune_committed_locked(conn: sqlite3.Connection, now: float) -> None:
        conn.execute(
            "DELETE FROM effect_receipts WHERE status = 'committed' AND updated_at < ?",
            (now - _RETENTION_SECONDS,),
        )
        conn.execute(
            """DELETE FROM effect_receipts WHERE operation_id IN (
                   SELECT operation_id FROM effect_receipts
                   WHERE status = 'committed'
                   ORDER BY updated_at DESC LIMIT -1 OFFSET ?
               )""",
            (_MAX_COMMITTED_RECEIPTS,),
        )
