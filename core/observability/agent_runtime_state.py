"""Per-agent cumulative runtime state — SQLite-backed.

PR-COMM-3 (2026-05-24, spec doc:
``docs/plans/2026-05-24-pr-comm-3-runtime-db-integration-audit.md``).

Mirrors paperclip's ``agent_runtime_state`` table: one row per agent_id
carrying the claude-cli sessionId for the next ``--resume``, cumulative
token / cost totals, and the last error. Plus a sibling ``run_lineage``
table that captures per-cycle retry / refinement chains for multi-cycle
agents (seed-generation, self-improving-loop).

Both tables live in the same ``sessions.db`` that ``SessionManager``
owns — see the audit doc §4 (Option A) for the rationale.

Writer functions are designed to be called from HookSystem handlers:

* :func:`record_agent_session_end` — fires on ``SESSION_ENDED`` for every
  AgenticLoop (REPL / gateway / sub-agent).
* :func:`record_subagent_completed` — fires on ``SUBAGENT_COMPLETED`` at
  the sub-agent dispatch layer, carries ``last_run_id`` linkage for
  cross-cycle continuity.
* :func:`accumulate_tokens_and_cost` — fires on ``LLM_CALL_ENDED``,
  accumulates per-call usage into the cumulative totals.

Failures are swallowed + warning-logged so a broken writer never blocks
the upstream hook trigger (same contract as
``activity_log._mirror_hook_to_active_transcript``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class AgentRuntimeState:
    """In-memory mirror of one ``agent_runtime_state`` row."""

    agent_id: str
    agent_kind: str = "subagent"
    component: str = "agentic_loop"
    adapter_type: str = ""
    claude_cli_session_id: str = ""
    last_run_id: str = ""
    last_run_status: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_input_tokens: int = 0
    total_cost_cents: int = 0
    last_error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class RunLineage:
    """In-memory mirror of one ``run_lineage`` row."""

    run_id: str
    component: str
    agent_id: str
    parent_run_id: str = ""
    root_run_id: str = ""
    status: str = "started"
    started_at: float = 0.0
    ended_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Singleton accessor — lazy + shared connection
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None
_DB_PATH: Path | None = None


def _get_conn() -> sqlite3.Connection | None:
    """Return the singleton ``sessions.db`` connection, or None on failure.

    Imports :class:`SessionManager` solely to trigger schema initialization
    (the constructor is the single SoT for both table sets — see PR-COMM-3
    audit doc §10 for the co-location decision). Subsequent reads/writes
    use a thin connection separate from ``SessionManager``'s so we don't
    contend on its ``_lock`` — sqlite3's WAL mode handles concurrent
    readers + writers safely.
    """
    global _CONN, _DB_PATH

    with _LOCK:
        if _CONN is not None:
            return _CONN
        try:
            from core.memory.session_manager import (
                SessionManager,
                _get_default_db_path,
            )

            # Trigger schema bootstrap (idempotent on existing DBs).
            SessionManager()
            _DB_PATH = _get_default_db_path()
            _CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
            _CONN.execute("PRAGMA journal_mode=WAL")
            return _CONN
        except Exception as exc:
            log.warning("agent_runtime_state: failed to open sessions.db: %s", exc)
            return None


def _reset_for_tests(db_path: Path | None = None) -> None:
    """Test-only — drop the cached connection so the next call rebuilds.

    Pytest fixtures swap ``_get_default_db_path`` via monkeypatch; this
    helper lets the test then force a fresh connection to the new path.
    """
    global _CONN, _DB_PATH
    with _LOCK:
        if _CONN is not None:
            with contextlib.suppress(Exception):
                _CONN.close()
        _CONN = None
        _DB_PATH = db_path


# ---------------------------------------------------------------------------
# Writers (called from HookSystem handlers)
# ---------------------------------------------------------------------------


def record_agent_session_end(
    *,
    agent_id: str,
    agent_kind: str = "subagent",
    component: str = "agentic_loop",
    adapter_type: str = "",
    claude_cli_session_id: str = "",
) -> None:
    """Upsert the ``agent_runtime_state`` row for a completed AgenticLoop.

    Fires on ``HookEvent.SESSION_ENDED`` from every AgenticLoop path
    (REPL / gateway / sub-agent). Preserves cumulative totals — the
    UPSERT only writes identity + session_id columns; totals are
    accumulated separately by :func:`accumulate_tokens_and_cost`.
    """
    conn = _get_conn()
    if conn is None or not agent_id:
        return
    now = time.time()
    try:
        with _LOCK:
            conn.execute(
                """\
                INSERT INTO agent_runtime_state
                    (agent_id, agent_kind, component, adapter_type,
                     claude_cli_session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    agent_kind            = excluded.agent_kind,
                    component             = excluded.component,
                    adapter_type          = excluded.adapter_type,
                    claude_cli_session_id = CASE
                        WHEN excluded.claude_cli_session_id != ''
                            THEN excluded.claude_cli_session_id
                        ELSE agent_runtime_state.claude_cli_session_id
                    END,
                    updated_at            = excluded.updated_at
                """,
                (
                    agent_id,
                    agent_kind,
                    component,
                    adapter_type,
                    claude_cli_session_id,
                    now,
                    now,
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("record_agent_session_end(%s) failed: %s", agent_id, exc)


def record_subagent_completed(
    *,
    agent_id: str,
    component: str,
    last_run_id: str,
    last_run_status: str,
    last_error: str = "",
) -> None:
    """Upsert ``agent_runtime_state`` with the last_run_id linkage.

    Fires on ``HookEvent.SUBAGENT_COMPLETED`` at the sub-agent dispatch
    layer. Sets ``agent_kind="subagent"`` automatically (this code path
    only runs for sub-agents); ``component`` comes from the
    ``RunTranscript.component`` SoT at dispatch time.
    """
    conn = _get_conn()
    if conn is None or not agent_id:
        return
    now = time.time()
    try:
        with _LOCK:
            conn.execute(
                """\
                INSERT INTO agent_runtime_state
                    (agent_id, agent_kind, component,
                     last_run_id, last_run_status, last_error,
                     created_at, updated_at)
                VALUES (?, 'subagent', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    component        = excluded.component,
                    last_run_id      = excluded.last_run_id,
                    last_run_status  = excluded.last_run_status,
                    last_error       = excluded.last_error,
                    updated_at       = excluded.updated_at
                """,
                (agent_id, component, last_run_id, last_run_status, last_error, now, now),
            )
            conn.commit()
    except Exception as exc:
        log.warning("record_subagent_completed(%s) failed: %s", agent_id, exc)


def accumulate_tokens_and_cost(
    *,
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Atomically add per-call usage to the cumulative totals.

    Fires on ``HookEvent.LLM_CALL_ENDED``. Creates a placeholder row if
    the agent_id is not yet known (the SESSION_ENDED upsert will fill
    in agent_kind / component later). ``cost_usd`` is rounded to cents
    via ``round(cost_usd * 100)`` so the column stays INTEGER (avoids
    float drift on cumulative sums).
    """
    conn = _get_conn()
    if conn is None or not agent_id:
        return
    cost_cents = round(cost_usd * 100)
    now = time.time()
    try:
        with _LOCK:
            conn.execute(
                """\
                INSERT INTO agent_runtime_state
                    (agent_id,
                     total_input_tokens, total_output_tokens,
                     total_cached_input_tokens, total_cost_cents,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    total_input_tokens        = total_input_tokens + excluded.total_input_tokens,
                    total_output_tokens       = total_output_tokens + excluded.total_output_tokens,
                    total_cached_input_tokens = total_cached_input_tokens
                                                + excluded.total_cached_input_tokens,
                    total_cost_cents          = total_cost_cents + excluded.total_cost_cents,
                    updated_at                = excluded.updated_at
                """,
                (
                    agent_id,
                    int(input_tokens),
                    int(output_tokens),
                    int(cached_input_tokens),
                    cost_cents,
                    now,
                    now,
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("accumulate_tokens_and_cost(%s) failed: %s", agent_id, exc)


def record_run_lineage(
    *,
    run_id: str,
    component: str,
    agent_id: str,
    parent_run_id: str = "",
    status: str = "started",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert (or update) a ``run_lineage`` row for a multi-cycle agent.

    ``root_run_id`` is auto-resolved from ``parent_run_id``: when the
    parent has its own ``root_run_id`` we propagate it; otherwise the
    parent IS the root. Top-level runs (no parent) point to themselves.
    """
    conn = _get_conn()
    if conn is None or not run_id:
        return
    now = time.time()

    if parent_run_id:
        try:
            row = conn.execute(
                "SELECT root_run_id FROM run_lineage WHERE run_id = ?",
                (parent_run_id,),
            ).fetchone()
            root_run_id = str(row[0]) if row else parent_run_id
        except Exception:
            root_run_id = parent_run_id
    else:
        root_run_id = run_id

    try:
        with _LOCK:
            conn.execute(
                """\
                INSERT INTO run_lineage
                    (run_id, component, agent_id, parent_run_id, root_run_id,
                     status, started_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status        = excluded.status,
                    metadata      = excluded.metadata
                """,
                (
                    run_id,
                    component,
                    agent_id,
                    parent_run_id,
                    root_run_id,
                    status,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("record_run_lineage(%s) failed: %s", run_id, exc)


def mark_run_ended(run_id: str, status: str) -> None:
    """Flip a ``run_lineage`` row's ``status`` + ``ended_at``."""
    conn = _get_conn()
    if conn is None or not run_id:
        return
    try:
        with _LOCK:
            conn.execute(
                "UPDATE run_lineage SET status = ?, ended_at = ? WHERE run_id = ?",
                (status, time.time(), run_id),
            )
            conn.commit()
    except Exception as exc:
        log.warning("mark_run_ended(%s) failed: %s", run_id, exc)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def get_agent_runtime_state(agent_id: str) -> AgentRuntimeState | None:
    """Fetch one agent's cumulative state; None if no row exists."""
    conn = _get_conn()
    if conn is None or not agent_id:
        return None
    try:
        row = conn.execute(
            """\
            SELECT agent_id, agent_kind, component, adapter_type,
                   claude_cli_session_id, last_run_id, last_run_status,
                   total_input_tokens, total_output_tokens,
                   total_cached_input_tokens, total_cost_cents,
                   last_error, created_at, updated_at
            FROM agent_runtime_state WHERE agent_id = ?
            """,
            (agent_id,),
        ).fetchone()
    except Exception as exc:
        log.warning("get_agent_runtime_state(%s) failed: %s", agent_id, exc)
        return None
    if row is None:
        return None
    return AgentRuntimeState(
        agent_id=str(row[0]),
        agent_kind=str(row[1]),
        component=str(row[2]),
        adapter_type=str(row[3]),
        claude_cli_session_id=str(row[4]),
        last_run_id=str(row[5]),
        last_run_status=str(row[6]),
        total_input_tokens=int(row[7]),
        total_output_tokens=int(row[8]),
        total_cached_input_tokens=int(row[9]),
        total_cost_cents=int(row[10]),
        last_error=str(row[11]),
        created_at=float(row[12]),
        updated_at=float(row[13]),
    )


def get_retry_chain(run_id: str) -> list[RunLineage]:
    """Return every run sharing this run's root, ordered by started_at.

    Useful for "show me every attempt at this seed-generation cycle"
    queries. When the run_id isn't in ``run_lineage`` yet, returns an
    empty list.
    """
    conn = _get_conn()
    if conn is None or not run_id:
        return []
    try:
        anchor = conn.execute(
            "SELECT root_run_id FROM run_lineage WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not anchor:
            return []
        root = str(anchor[0])
        rows = conn.execute(
            """\
            SELECT run_id, component, agent_id, parent_run_id, root_run_id,
                   status, started_at, ended_at, metadata
            FROM run_lineage
            WHERE root_run_id = ?
            ORDER BY started_at ASC
            """,
            (root,),
        ).fetchall()
    except Exception as exc:
        log.warning("get_retry_chain(%s) failed: %s", run_id, exc)
        return []
    out: list[RunLineage] = []
    for r in rows:
        try:
            meta = json.loads(str(r[8]) or "{}")
        except json.JSONDecodeError:
            meta = {}
        out.append(
            RunLineage(
                run_id=str(r[0]),
                component=str(r[1]),
                agent_id=str(r[2]),
                parent_run_id=str(r[3]),
                root_run_id=str(r[4]),
                status=str(r[5]),
                started_at=float(r[6]),
                ended_at=float(r[7]) if r[7] is not None else None,
                metadata=meta if isinstance(meta, dict) else {},
            )
        )
    return out


def get_root_run(run_id: str) -> str:
    """Return the root_run_id for a run, or the run_id itself if no row."""
    conn = _get_conn()
    if conn is None or not run_id:
        return run_id
    try:
        row = conn.execute(
            "SELECT root_run_id FROM run_lineage WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    except Exception as exc:
        log.warning("get_root_run(%s) failed: %s", run_id, exc)
        return run_id
    return str(row[0]) if row else run_id
