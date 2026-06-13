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

PR-LOOP-PRUNE (2026-06-13): the watcher-side API (claim / complete /
fail / list_pending / handoff_summary) and its reserved HookEvents
(HANDOFF_COMPLETED / HANDOFF_FAILED) were deleted — no watcher exists,
so none of it had a production caller since PR-CL-BUDGET
(reserve-without-emit rule). What remains is the minimal write+read
pair: ``request_handoff`` (loop fires it once at the T-10min budget
threshold) and ``get_handoff`` (row inspection — keeps the persisted
contract readable so the table is not write-only). Rebuild the watcher
API in the same PR that builds the watcher; the RUNNING/COMPLETED/
FAILED enum states stay because persisted rows may carry them.

Schema lives in :mod:`core.memory.session_manager` (3 ALTER TABLE
columns on the existing ``sessions`` table — additive, no rename).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger(__name__)

__all__ = [
    "Handoff",
    "HandoffState",
    "get_handoff",
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
