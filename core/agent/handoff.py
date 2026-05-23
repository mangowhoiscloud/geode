"""Hand-off state machine — DB-backed pending/running/completed/failed.

Adapted from hermes-agent's `sessions` table handoff_state pattern
(`~/workspace/hermes-agent/hermes_state.py:218-220` + `gateway/run.py:
3712-3766` watcher). Three differences vs. the upstream port:

1. **Automatic trigger** — hermes fires on a user `/handoff <platform>`
   slash command. GEODE fires automatically when the wall-clock budget
   crosses T-10min (see :mod:`core.agent.budget`). Operator decision
   recorded in memory: ``project_budget_handoff_decision`` (2026-05-23).

2. **Artifact reuse** — hermes replays the entire `messages` table
   transcript via a synthetic turn. GEODE re-uses :class:`SessionTranscript`
   + :class:`SessionMetrics` (Tier 1 + Tier 2 already present after
   PR-SESSION-METRICS #1531). No new artifact format introduced.

3. **No platform routing** — hermes routes the handoff to a target
   chat platform (Slack / etc.). In this PR scope, the platform field
   is recorded for diagnostics but the handoff is *graceful exit only*
   (the successor invocation is out of scope; a future PR can extend
   the watcher to re-spawn).

State machine::

    None ─request_handoff()─► PENDING
                                  │
                                  │ claim_handoff()
                                  ▼
                              RUNNING
                                  │
                       ┌──────────┴──────────┐
                       │                     │
                       ▼                     ▼
                  COMPLETED              FAILED

Schema lives in :mod:`core.memory.session_manager` (3 ALTER TABLE
columns on the existing ``sessions`` table — additive, no rename).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "Handoff",
    "HandoffState",
    "claim_handoff",
    "complete_handoff",
    "fail_handoff",
    "get_handoff",
    "list_pending_handoffs",
    "request_handoff",
]


class HandoffState(StrEnum):
    """Five terminal states for a session handoff.

    :class:`StrEnum` (Python 3.11+) lets the value be written to SQLite
    TEXT columns directly (sqlite3 uses ``__str__``). The ``NONE``
    sentinel exists so callers can compare ``state == HandoffState.NONE``
    instead of ``state is None``.
    """

    NONE = ""  # No handoff requested
    PENDING = "pending"  # Trigger fired, waiting for claim
    RUNNING = "running"  # Watcher claimed, processing
    COMPLETED = "completed"  # Hand-off artifact persisted, session can exit
    FAILED = "failed"  # Hand-off attempt errored — error column populated


@dataclass(frozen=True, slots=True)
class Handoff:
    """Snapshot of the handoff record for one session."""

    session_id: str
    state: HandoffState
    platform: str = ""
    error: str = ""
    triggered_at: float = 0.0


def request_handoff(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    platform: str = "",
    triggered_at: float | None = None,
) -> bool:
    """Mark a session as handoff-pending. Atomic CAS — only flips
    ``handoff_state`` from ``NONE``/empty to ``PENDING``; returns False if
    the session row already has a non-empty handoff state (already
    pending / running / completed / failed). Idempotent on the empty
    state.

    Caller must ensure the session row exists (created by SessionManager
    via :meth:`upsert`); we don't auto-create here because the schema
    has NOT NULL columns that need real values.
    """
    ts = triggered_at if triggered_at is not None else time.time()
    cursor = conn.execute(
        """\
        UPDATE sessions
        SET handoff_state = ?, handoff_platform = ?, handoff_triggered_at = ?
        WHERE session_id = ?
          AND (handoff_state IS NULL OR handoff_state = '')
        """,
        (HandoffState.PENDING.value, platform, ts, session_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def claim_handoff(conn: sqlite3.Connection, *, session_id: str) -> bool:
    """Atomic CAS PENDING → RUNNING claim. Returns True if the watcher
    successfully claimed this row, False if another watcher beat it or
    the row isn't pending."""
    cursor = conn.execute(
        """\
        UPDATE sessions
        SET handoff_state = ?
        WHERE session_id = ? AND handoff_state = ?
        """,
        (HandoffState.RUNNING.value, session_id, HandoffState.PENDING.value),
    )
    conn.commit()
    return cursor.rowcount > 0


def complete_handoff(conn: sqlite3.Connection, *, session_id: str) -> bool:
    """Mark a claimed handoff as COMPLETED. Returns True iff state was
    RUNNING (idempotent on COMPLETED — returns False without raising)."""
    cursor = conn.execute(
        """\
        UPDATE sessions
        SET handoff_state = ?
        WHERE session_id = ? AND handoff_state = ?
        """,
        (HandoffState.COMPLETED.value, session_id, HandoffState.RUNNING.value),
    )
    conn.commit()
    return cursor.rowcount > 0


def fail_handoff(conn: sqlite3.Connection, *, session_id: str, error: str) -> bool:
    """Mark a handoff as FAILED with an error message. Returns True iff
    state was RUNNING. Truncates the error string at 500 chars (matches
    hermes ``handoff_error`` TEXT column convention)."""
    safe_error = (error or "")[:500]
    cursor = conn.execute(
        """\
        UPDATE sessions
        SET handoff_state = ?, handoff_error = ?
        WHERE session_id = ? AND handoff_state = ?
        """,
        (HandoffState.FAILED.value, safe_error, session_id, HandoffState.RUNNING.value),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_handoff(conn: sqlite3.Connection, *, session_id: str) -> Handoff | None:
    """Read the current handoff snapshot for a session. Returns None when
    the session row is missing (not a handoff-state thing — that's a
    different concern)."""
    row = conn.execute(
        """\
        SELECT session_id, handoff_state, handoff_platform, handoff_error,
               handoff_triggered_at
        FROM sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    state_raw = row[1] or ""
    try:
        state = HandoffState(state_raw)
    except ValueError:
        log.warning(
            "Unknown handoff_state value %r for session %s; treating as NONE",
            state_raw,
            session_id,
        )
        state = HandoffState.NONE
    return Handoff(
        session_id=str(row[0]),
        state=state,
        platform=str(row[2] or ""),
        error=str(row[3] or ""),
        triggered_at=float(row[4] or 0.0),
    )


def list_pending_handoffs(conn: sqlite3.Connection, *, limit: int = 50) -> list[Handoff]:
    """Watcher-side reader — return all PENDING rows ordered by
    ``triggered_at`` so the oldest pending claim is processed first."""
    rows = conn.execute(
        """\
        SELECT session_id, handoff_state, handoff_platform, handoff_error,
               handoff_triggered_at
        FROM sessions
        WHERE handoff_state = ?
        ORDER BY handoff_triggered_at ASC
        LIMIT ?
        """,
        (HandoffState.PENDING.value, limit),
    ).fetchall()
    out: list[Handoff] = []
    for r in rows:
        out.append(
            Handoff(
                session_id=str(r[0]),
                state=HandoffState.PENDING,
                platform=str(r[2] or ""),
                error=str(r[3] or ""),
                triggered_at=float(r[4] or 0.0),
            )
        )
    return out


def handoff_summary(handoff: Handoff | None) -> dict[str, Any]:
    """JSON-friendly summary used in HANDOFF hook payloads + transcript
    rows. Empty dict when handoff is None or NONE state."""
    if handoff is None or handoff.state is HandoffState.NONE:
        return {}
    return {
        "session_id": handoff.session_id,
        "state": handoff.state.value,
        "platform": handoff.platform,
        "error": handoff.error,
        "triggered_at": handoff.triggered_at,
    }
