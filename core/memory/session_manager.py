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
from hashlib import sha256
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


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    """Durable synthesized context derived from session transcripts."""

    artifact_id: str
    session_id: str
    kind: str
    content: str
    source_start_seq: int | None = None
    source_end_seq: int | None = None
    token_count: int | None = None
    model: str = ""
    provider: str = ""
    metadata: dict[str, Any] | None = None
    created_at: float = 0.0
    updated_at: float = 0.0


_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id                  TEXT PRIMARY KEY,
    created_at                  REAL NOT NULL,
    updated_at                  REAL NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'active',
    model                       TEXT NOT NULL DEFAULT '',
    provider                    TEXT NOT NULL DEFAULT 'anthropic',
    user_input                  TEXT NOT NULL DEFAULT '',
    round_count                 INTEGER NOT NULL DEFAULT 0,
    message_count               INTEGER NOT NULL DEFAULT 0,
    handoff_state               TEXT NOT NULL DEFAULT '',
    handoff_platform            TEXT NOT NULL DEFAULT '',
    handoff_error               TEXT NOT NULL DEFAULT '',
    handoff_triggered_at        REAL NOT NULL DEFAULT 0.0,
    verify_pass_count           INTEGER NOT NULL DEFAULT 0,
    verify_fail_count           INTEGER NOT NULL DEFAULT 0,
    last_verify_passed          INTEGER NOT NULL DEFAULT 1,
    last_verify_mode            TEXT NOT NULL DEFAULT '',
    last_verify_effective_mode  TEXT NOT NULL DEFAULT '',
    last_verify_rubric_misses   TEXT NOT NULL DEFAULT '',
    last_verify_should_retry    INTEGER NOT NULL DEFAULT 0
)
"""

# Existing-DB migration: legacy schemas (pre PR-CL-BUDGET / PR-CL-A3) lack
# the handoff + verify columns. ``PRAGMA table_info`` is the SoT for
# present columns; we add only those that are missing. Idempotent on
# schemas already carrying the columns. Defaults match ``_CREATE_TABLE_SQL``
# so a fresh DB and a migrated DB produce identical rows. Boolean fields
# encoded as INTEGER (0 / 1) — SQLite has no native bool.
_HANDOFF_COLUMNS: tuple[tuple[str, str], ...] = (
    ("handoff_state", "TEXT NOT NULL DEFAULT ''"),
    ("handoff_platform", "TEXT NOT NULL DEFAULT ''"),
    ("handoff_error", "TEXT NOT NULL DEFAULT ''"),
    ("handoff_triggered_at", "REAL NOT NULL DEFAULT 0.0"),
)

_VERIFY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("verify_pass_count", "INTEGER NOT NULL DEFAULT 0"),
    ("verify_fail_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_verify_passed", "INTEGER NOT NULL DEFAULT 1"),
    ("last_verify_mode", "TEXT NOT NULL DEFAULT ''"),
    ("last_verify_effective_mode", "TEXT NOT NULL DEFAULT ''"),
    ("last_verify_rubric_misses", "TEXT NOT NULL DEFAULT ''"),
    ("last_verify_should_retry", "INTEGER NOT NULL DEFAULT 0"),
)

_CREATE_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at DESC)
"""

# PR-CL-BUDGET — handoff watcher polls ``handoff_state='pending'`` rows.
# Partial index keeps the lookup cheap when most rows have empty state.
_CREATE_HANDOFF_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_sessions_handoff_state
    ON sessions (handoff_state, handoff_triggered_at)
    WHERE handoff_state != ''
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

_CREATE_CONTEXT_ARTIFACTS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS context_artifacts (
    artifact_id      TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    kind             TEXT NOT NULL,
    source_start_seq INTEGER,
    source_end_seq   INTEGER,
    content          TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}',
    token_count      INTEGER,
    model            TEXT NOT NULL DEFAULT '',
    provider         TEXT NOT NULL DEFAULT '',
    content_hash     TEXT NOT NULL,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    UNIQUE(session_id, kind, source_start_seq, source_end_seq, content_hash)
)
"""

_CREATE_CONTEXT_ARTIFACTS_SESSION_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_context_artifacts_session
    ON context_artifacts (session_id, kind, updated_at DESC)
"""

_CREATE_CONTEXT_ARTIFACTS_KIND_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_context_artifacts_kind
    ON context_artifacts (kind, updated_at DESC)
"""

# PR-COMM-3 (2026-05-24) — per-agent cumulative state. Mirrors paperclip
# ``agent_runtime_state`` table (Anthropic-internal docs §session-state):
# one row per agent_id carrying the claude-cli sessionId for the next
# ``--resume``, cumulative token / cost totals, and the last error.
#
# Two extra columns split the cumulative state along orthogonal axes
# (see docs/plans/2026-05-24-pr-comm-3-runtime-db-integration-audit.md §9):
#
# * ``agent_kind`` — process origin: ``subagent`` / ``repl`` / ``gateway`` /
#   ``scheduler``. Answers "where was this loop spawned from" — quota
#   throttling separates origins.
# * ``component`` — GEODE subsystem: ``seed-generation`` /
#   ``self-improving-loop`` / ``petri-audit`` / ``autoresearch`` /
#   ``agentic_loop`` / ``serve`` / ``scheduler``. Answers "what is this
#   loop doing" — reuses ``RunTranscript.component`` SoT (no separate
#   enum).
#
# ``last_run_id`` is a soft FK into ``run_lineage`` for seed-generation
# style multi-cycle agents; empty string for REPL / gateway / one-shot
# spawns. Stored in the SAME sessions.db so cross-table joins
# (e.g. "what was this agent doing during session X") are local.
_CREATE_AGENT_RUNTIME_STATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS agent_runtime_state (
    agent_id                  TEXT PRIMARY KEY,
    agent_kind                TEXT NOT NULL DEFAULT 'subagent',
    component                 TEXT NOT NULL DEFAULT 'agentic_loop',
    adapter_type              TEXT NOT NULL DEFAULT '',
    claude_cli_session_id     TEXT NOT NULL DEFAULT '',
    last_run_id               TEXT NOT NULL DEFAULT '',
    last_run_status           TEXT NOT NULL DEFAULT '',
    total_input_tokens        INTEGER NOT NULL DEFAULT 0,
    total_output_tokens       INTEGER NOT NULL DEFAULT 0,
    total_cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_cents          INTEGER NOT NULL DEFAULT 0,
    last_error                TEXT NOT NULL DEFAULT '',
    session_resume_params     TEXT NOT NULL DEFAULT '{}',
    created_at                REAL NOT NULL,
    updated_at                REAL NOT NULL
)
"""

# PR-SESSION-RESUME-PARAMS (2026-05-25) — additive ALTER for legacy DBs
# that pre-date the column. Mirrors paperclip's ``sessionParams`` JSON
# blob (``packages/adapters/claude-local/src/server/execute.ts:592``) —
# a single TEXT column that carries every resume-context field
# (currently ``cwd``; future ``prompt_bundle_key`` / ``adapter_type`` /
# ``remote_id`` etc. can land in the same JSON without further ALTERs).
# Read-time the JSON is parsed once and validated against the current
# execution context (see
# ``core/agent/loop/agent_loop.py:_load_prior_session_id``); a mismatch
# forces a fresh session instead of a doomed ``--resume <id>`` against
# a cwd-pool that does not hold that session file.
_AGENT_RUNTIME_STATE_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_resume_params", "TEXT NOT NULL DEFAULT '{}'"),
)

_CREATE_AGENT_RUNTIME_KIND_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_agent_runtime_kind
    ON agent_runtime_state (agent_kind, updated_at DESC)
"""

_CREATE_AGENT_RUNTIME_COMPONENT_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_agent_runtime_component
    ON agent_runtime_state (component, updated_at DESC)
"""

_CREATE_AGENT_RUNTIME_UPDATED_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_agent_runtime_updated
    ON agent_runtime_state (updated_at DESC)
"""

_CREATE_AGENT_RUNTIME_SESSION_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_agent_runtime_session
    ON agent_runtime_state (claude_cli_session_id)
    WHERE claude_cli_session_id != ''
"""

# PR-COMM-3 (2026-05-24) — per-cycle run lineage for multi-cycle agents
# (seed-generation, self-improving-loop). One row per logical "run", with
# parent_run_id forming a retry / refinement chain (Karpathy P5 lineage
# tracking). Seed-gen-only today; REPL / gateway / one-shot agents
# leave this empty.
_CREATE_RUN_LINEAGE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS run_lineage (
    run_id          TEXT PRIMARY KEY,
    component       TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    parent_run_id   TEXT NOT NULL DEFAULT '',
    root_run_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'started',
    started_at      REAL NOT NULL,
    ended_at        REAL,
    metadata        TEXT NOT NULL DEFAULT '{}'
)
"""

_CREATE_RUN_LINEAGE_AGENT_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_run_lineage_agent
    ON run_lineage (agent_id, started_at DESC)
"""

_CREATE_RUN_LINEAGE_PARENT_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_run_lineage_parent
    ON run_lineage (parent_run_id)
    WHERE parent_run_id != ''
"""

_CREATE_RUN_LINEAGE_ROOT_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_run_lineage_root
    ON run_lineage (root_run_id, started_at)
"""

# Phase 1c (Hermes absorption, 2026-05-22) — full-text search indices over
# the messages table. ``content``, ``tool_name``, and ``tool_calls`` are
# all indexed so a single query surfaces text matches AND tool-name
# filters. ``content='messages'`` makes both FTS tables *external-content*
# (FTS5 fetches the indexed columns from the source table by rowid)
# so the underlying TEXT data isn't duplicated; the
# triggers below keep them in sync with the source messages table.
#
# unicode61 = baseline tokenizer (case + diacritic fold). Always
# created.
# trigram = substring-recall booster (Korean / Japanese partial words,
# identifier fragments). Requires SQLite 3.34+; gated by
# ``has_trigram_support`` at runtime.

_CREATE_MESSAGES_FTS_UNICODE_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, tool_name, tool_calls,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
)
"""

_CREATE_MESSAGES_FTS_TRIGRAM_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(
    content, tool_name, tool_calls,
    content='messages',
    content_rowid='id',
    tokenize='trigram'
)
"""

_CREATE_CONTEXT_ARTIFACTS_FTS_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS context_artifacts_fts USING fts5(
    content, kind, metadata,
    content='context_artifacts',
    content_rowid='rowid',
    tokenize='unicode61'
)
"""

_CONTEXT_ARTIFACTS_FTS_TRIGGERS_SQL = """\
CREATE TRIGGER IF NOT EXISTS context_artifacts_fts_after_insert
AFTER INSERT ON context_artifacts BEGIN
    INSERT INTO context_artifacts_fts(rowid, content, kind, metadata)
    VALUES (new.rowid, new.content, new.kind, new.metadata);
END;
CREATE TRIGGER IF NOT EXISTS context_artifacts_fts_after_delete
AFTER DELETE ON context_artifacts BEGIN
    INSERT INTO context_artifacts_fts(context_artifacts_fts, rowid, content, kind, metadata)
    VALUES ('delete', old.rowid, old.content, old.kind, old.metadata);
END;
CREATE TRIGGER IF NOT EXISTS context_artifacts_fts_after_update
AFTER UPDATE ON context_artifacts BEGIN
    INSERT INTO context_artifacts_fts(context_artifacts_fts, rowid, content, kind, metadata)
    VALUES ('delete', old.rowid, old.content, old.kind, old.metadata);
    INSERT INTO context_artifacts_fts(rowid, content, kind, metadata)
    VALUES (new.rowid, new.content, new.kind, new.metadata);
END;
"""


def _fts_trigger_block(fts_name: str) -> str:
    """Build the 3 INSERT/DELETE/UPDATE triggers for one FTS table.

    Generated rather than literal so the unicode61 and trigram tables
    share one source-of-truth without copy-paste drift. The trigger
    names embed ``fts_name`` for unambiguous SQL error messages.
    ``fts_name`` is sourced from a fixed allowlist (``messages_fts`` /
    ``messages_fts_trigram``); never operator input.
    """
    # fts_name is a hardcoded literal, not user input — S608/B608 safe to ignore.
    sql = f"""CREATE TRIGGER IF NOT EXISTS {fts_name}_after_insert AFTER INSERT ON messages BEGIN
    INSERT INTO {fts_name}(rowid, content, tool_name, tool_calls)
    VALUES (new.id, new.content, new.tool_name, new.tool_calls);
END;
CREATE TRIGGER IF NOT EXISTS {fts_name}_after_delete AFTER DELETE ON messages BEGIN
    INSERT INTO {fts_name}({fts_name}, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.id, old.content, old.tool_name, old.tool_calls);
END;
CREATE TRIGGER IF NOT EXISTS {fts_name}_after_update AFTER UPDATE ON messages BEGIN
    INSERT INTO {fts_name}({fts_name}, rowid, content, tool_name, tool_calls)
    VALUES ('delete', old.id, old.content, old.tool_name, old.tool_calls);
    INSERT INTO {fts_name}(rowid, content, tool_name, tool_calls)
    VALUES (new.id, new.content, new.tool_name, new.tool_calls);
END;"""  # noqa: S608  # nosec B608
    return sql


_FTS_TRIGGERS_UNICODE_SQL = _fts_trigger_block("messages_fts")
_FTS_TRIGGERS_TRIGRAM_SQL = _fts_trigger_block("messages_fts_trigram")


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
    content_str: str | None = None if content is None else json.dumps(content, ensure_ascii=False)

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
    finish_reason: str | None = finish_reason_raw if isinstance(finish_reason_raw, str) else None

    metadata_raw = msg.get("metadata")
    # PR-CODEX-MULTITURN-PHASE-PRESERVE fold (Sprint H follow-up,
    # 2026-05-26, Codex MCP HIGH catch) — fold the Codex sidecar keys
    # (``phase`` from ResponseOutputMessage attribution, and the
    # pre-existing ``codex_reasoning_items`` encrypted-reasoning replay
    # blobs) into ``metadata`` so a checkpoint/resume cycle preserves
    # them. The docstring already promised "unknown keys are folded
    # into metadata so nothing is lost" but the implementation only
    # ever read ``msg["metadata"]`` — the sidecar keys were silently
    # dropped on resume. ``_row_to_message`` mirrors this back so the
    # round-trip is symmetric.
    sidecar: dict[str, Any] = {}
    phase_raw = msg.get("phase")
    if isinstance(phase_raw, str) and phase_raw:
        sidecar["phase"] = phase_raw
    reasoning_items_raw = msg.get("codex_reasoning_items")
    if isinstance(reasoning_items_raw, (list, tuple)) and reasoning_items_raw:
        sidecar["codex_reasoning_items"] = list(reasoning_items_raw)

    merged_metadata: dict[str, Any] | list[Any] | None
    if sidecar:
        if isinstance(metadata_raw, dict):
            merged_metadata = {**metadata_raw, **sidecar}
        elif metadata_raw is None:
            merged_metadata = sidecar
        else:
            # Non-dict metadata (e.g. legacy list) — wrap so sidecar
            # keys still persist alongside the original payload.
            merged_metadata = {"_metadata": metadata_raw, **sidecar}
    else:
        merged_metadata = metadata_raw if isinstance(metadata_raw, (dict, list)) else None

    metadata_json: str | None = (
        json.dumps(merged_metadata, ensure_ascii=False)
        if isinstance(merged_metadata, (dict, list)) and merged_metadata
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


def _loads_json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


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
        # PR-CL-BUDGET + PR-CL-A3 — additive ALTER TABLE for handoff +
        # verify cols on legacy DBs. ``PRAGMA table_info`` is the SoT
        # for column presence; sqlite has no native ``ADD COLUMN IF NOT
        # EXISTS`` so we filter ourselves. ``BEGIN IMMEDIATE`` + commit
        # wraps the read+writes so concurrent startup processes can't
        # observe a half-migrated schema. The transaction is no-op-cheap
        # on fresh DBs where every column already exists.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing_cols = {
                str(r[1]) for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            for col_name, col_decl in (*_HANDOFF_COLUMNS, *_VERIFY_COLUMNS):
                if col_name not in existing_cols:
                    # col_name + col_decl sourced from a module-level constant — not user input.
                    self._conn.execute(f"ALTER TABLE sessions ADD COLUMN {col_name} {col_decl}")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        self._conn.execute(_CREATE_INDEX_SQL)
        self._conn.execute(_CREATE_HANDOFF_INDEX_SQL)
        self._conn.execute(_CREATE_MESSAGES_TABLE_SQL)
        self._conn.execute(_CREATE_MESSAGES_SESSION_INDEX_SQL)
        self._conn.execute(_CREATE_MESSAGES_TOOL_INDEX_SQL)
        self._conn.execute(_CREATE_CONTEXT_ARTIFACTS_TABLE_SQL)
        self._conn.execute(_CREATE_CONTEXT_ARTIFACTS_SESSION_INDEX_SQL)
        self._conn.execute(_CREATE_CONTEXT_ARTIFACTS_KIND_INDEX_SQL)
        # PR-COMM-3 (2026-05-24) — per-agent runtime state + per-run
        # lineage. Co-located in sessions.db rather than a separate
        # runtime.db so cross-table joins (agent → its messages → its
        # runs) stay local. ``IF NOT EXISTS`` keeps the bootstrap
        # idempotent on legacy DBs.
        self._conn.execute(_CREATE_AGENT_RUNTIME_STATE_TABLE_SQL)
        # PR-SESSION-RESUME-PARAMS (2026-05-25) — additive ALTER for legacy
        # DBs whose ``agent_runtime_state`` was created before the
        # ``session_resume_params`` column existed. Same pattern as the
        # PR-CL-BUDGET / PR-CL-A3 ``sessions`` table migration above.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing_agent_cols = {
                str(r[1])
                for r in self._conn.execute("PRAGMA table_info(agent_runtime_state)").fetchall()
            }
            for col_name, col_decl in _AGENT_RUNTIME_STATE_EXTRA_COLUMNS:
                if col_name not in existing_agent_cols:
                    # col_name + col_decl sourced from a module-level constant — not user input.
                    self._conn.execute(
                        f"ALTER TABLE agent_runtime_state ADD COLUMN {col_name} {col_decl}"
                    )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        self._conn.execute(_CREATE_AGENT_RUNTIME_KIND_INDEX_SQL)
        self._conn.execute(_CREATE_AGENT_RUNTIME_COMPONENT_INDEX_SQL)
        self._conn.execute(_CREATE_AGENT_RUNTIME_UPDATED_INDEX_SQL)
        self._conn.execute(_CREATE_AGENT_RUNTIME_SESSION_INDEX_SQL)
        self._conn.execute(_CREATE_RUN_LINEAGE_TABLE_SQL)
        self._conn.execute(_CREATE_RUN_LINEAGE_AGENT_INDEX_SQL)
        self._conn.execute(_CREATE_RUN_LINEAGE_PARENT_INDEX_SQL)
        self._conn.execute(_CREATE_RUN_LINEAGE_ROOT_INDEX_SQL)
        # Phase 1c (Hermes absorption, 2026-05-22) — FTS5 indices.
        # unicode61 is always created. trigram is probed at runtime and
        # skipped on SQLite builds that don't ship it; ``self._has_trigram``
        # records the outcome so ``search_messages`` can skip the trigram
        # branch instead of crashing.
        from core.memory.fts_query import has_trigram_support

        self._conn.executescript(_CREATE_MESSAGES_FTS_UNICODE_SQL)
        self._conn.executescript(_FTS_TRIGGERS_UNICODE_SQL)
        self._has_trigram = has_trigram_support(self._conn)
        if self._has_trigram:
            self._conn.executescript(_CREATE_MESSAGES_FTS_TRIGRAM_SQL)
            self._conn.executescript(_FTS_TRIGGERS_TRIGRAM_SQL)
        else:
            log.warning(
                "SQLite build lacks FTS5 trigram support; falling back to "
                "unicode61-only search. Substring recall (e.g. partial Korean "
                "words / identifier fragments) will be limited."
            )
        self._conn.executescript(_CREATE_CONTEXT_ARTIFACTS_FTS_SQL)
        self._conn.executescript(_CONTEXT_ARTIFACTS_FTS_TRIGGERS_SQL)
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
    # PR-CL-A3 — verify telemetry persistence (sessions table columns)
    # ------------------------------------------------------------------

    def upsert_verify_state(
        self,
        session_id: str,
        *,
        verify_pass_count: int,
        verify_fail_count: int,
        last_verify_passed: bool,
        last_verify_mode: str,
        last_verify_effective_mode: str,
        last_verify_rubric_misses: tuple[str, ...] | list[str],
        last_verify_should_retry: bool,
    ) -> bool:
        """Persist per-turn verify state to the ``sessions`` row.

        ``rubric_misses`` is JSON-serialised so the round-trip preserves
        the list shape (sqlite has no native list type). Returns ``True``
        when the row was updated (session exists), ``False`` when no row
        matched (caller hasn't run ``upsert(SessionMeta)`` yet — silent
        no-op so verify telemetry never breaks the run it observes).
        """
        misses_json = json.dumps(list(last_verify_rubric_misses), ensure_ascii=False)
        with self._lock:
            cursor = self._conn.execute(
                """\
                UPDATE sessions SET
                    verify_pass_count = ?,
                    verify_fail_count = ?,
                    last_verify_passed = ?,
                    last_verify_mode = ?,
                    last_verify_effective_mode = ?,
                    last_verify_rubric_misses = ?,
                    last_verify_should_retry = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (
                    int(verify_pass_count),
                    int(verify_fail_count),
                    1 if last_verify_passed else 0,
                    str(last_verify_mode),
                    str(last_verify_effective_mode),
                    misses_json,
                    1 if last_verify_should_retry else 0,
                    time.time(),
                    session_id,
                ),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def get_verify_state(self, session_id: str) -> dict[str, Any] | None:
        """Read the persisted verify state for a session. Returns None when
        the row is missing. Decodes ``last_verify_rubric_misses`` JSON back
        to a list."""
        row = self._conn.execute(
            """\
            SELECT verify_pass_count, verify_fail_count, last_verify_passed,
                   last_verify_mode, last_verify_effective_mode,
                   last_verify_rubric_misses, last_verify_should_retry
            FROM sessions WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        misses_raw = row[5] or ""
        try:
            misses = json.loads(misses_raw) if misses_raw else []
        except json.JSONDecodeError:
            misses = []
        return {
            "verify_pass_count": int(row[0]),
            "verify_fail_count": int(row[1]),
            "last_verify_passed": bool(row[2]),
            "last_verify_mode": str(row[3] or ""),
            "last_verify_effective_mode": str(row[4] or ""),
            "last_verify_rubric_misses": misses,
            "last_verify_should_retry": bool(row[6]),
        }

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
            timestamp = float(raw_ts) if isinstance(raw_ts, (int, float)) else ts_default
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

    def search_messages(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 20,
        prefer_trigram: bool = False,
    ) -> list[dict[str, Any]]:
        """Full-text search across mirrored messages. Returns row dicts.

        Args:
            query: Raw operator query string. Sanitised via
                :func:`core.memory.fts_query.sanitize_fts5_query` so
                hyphens / dots / quotes don't blow up FTS5's grammar.
            session_id: Optional scope filter — restrict to messages from
                a single session.
            limit: Cap on rows returned (default 20).
            prefer_trigram: When ``True`` AND the trigram index exists,
                query ``messages_fts_trigram`` instead of the unicode61
                index. Useful for substring-recall scenarios (partial
                Korean words, identifier fragments). Silently falls back
                to unicode61 when trigram isn't supported.

        Returns:
            Newest-first list of ``{seq, role, content, timestamp,
            session_id, message_id, snippet, score}`` dicts. ``snippet``
            is FTS5's highlighted context window. Empty list when the
            sanitised query is empty.
        """
        from core.memory.fts_query import sanitize_fts5_query

        clean = sanitize_fts5_query(query)
        if not clean:
            return []
        table = "messages_fts_trigram" if prefer_trigram and self._has_trigram else "messages_fts"
        # ``table`` is one of two hardcoded literals (no user input) so the
        # f-string composition is safe — S608/B608 false positive.
        sql = (
            f"SELECT m.session_id, m.id, m.seq, m.role, m.content, m.timestamp, "  # noqa: S608  # nosec B608
            f"snippet({table}, 0, '[', ']', '…', 16), bm25({table}) "
            f"FROM {table} JOIN messages m ON m.id = {table}.rowid "
            f"WHERE {table} MATCH ?"
        )
        params: list[Any] = [clean]
        if session_id is not None:
            sql += " AND m.session_id = ?"
            params.append(session_id)
        sql += " ORDER BY m.timestamp DESC LIMIT ?"
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("search_messages FTS5 query failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            session_id_val, msg_id, seq, role, content_raw, ts, snippet, score = r
            content: Any = None
            if content_raw is not None:
                try:
                    content = json.loads(content_raw)
                except json.JSONDecodeError:
                    content = content_raw
            out.append(
                {
                    "session_id": session_id_val,
                    "message_id": msg_id,
                    "seq": seq,
                    "role": role,
                    "content": content,
                    "timestamp": ts,
                    "snippet": snippet,
                    "score": score,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Durable context artifacts: compaction summaries, handoffs, dreams
    # ------------------------------------------------------------------

    def upsert_context_artifact(
        self,
        *,
        session_id: str,
        kind: str,
        content: str,
        artifact_id: str | None = None,
        source_start_seq: int | None = None,
        source_end_seq: int | None = None,
        token_count: int | None = None,
        model: str = "",
        provider: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> str:
        """Insert/update a synthesized long-context artifact.

        ``artifact_id`` is stable by default: session + kind + source range +
        content hash. Re-running a compaction/dream pass over the same source
        updates metadata/timestamps rather than duplicating rows.
        """
        now = time.time()
        created = created_at if created_at is not None else now
        clean_metadata = metadata or {}
        metadata_json = json.dumps(clean_metadata, ensure_ascii=False, sort_keys=True)
        content_hash = sha256(content.encode("utf-8", errors="replace")).hexdigest()
        resolved_id = (
            artifact_id
            or sha256(
                "|".join(
                    (
                        session_id,
                        kind,
                        str(source_start_seq if source_start_seq is not None else ""),
                        str(source_end_seq if source_end_seq is not None else ""),
                        content_hash,
                    )
                ).encode("utf-8")
            ).hexdigest()[:32]
        )
        with self._lock:
            self._conn.execute(
                """\
                INSERT INTO context_artifacts
                    (artifact_id, session_id, kind, source_start_seq, source_end_seq,
                     content, metadata, token_count, model, provider, content_hash,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    content          = excluded.content,
                    metadata         = excluded.metadata,
                    token_count      = excluded.token_count,
                    model            = excluded.model,
                    provider         = excluded.provider,
                    content_hash     = excluded.content_hash,
                    updated_at       = excluded.updated_at
                """,
                (
                    resolved_id,
                    session_id,
                    kind,
                    source_start_seq,
                    source_end_seq,
                    content,
                    metadata_json,
                    token_count,
                    model,
                    provider,
                    content_hash,
                    created,
                    now,
                ),
            )
            self._conn.commit()
        return resolved_id

    def list_context_artifacts(
        self,
        *,
        session_id: str | None = None,
        kinds: list[str] | tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[ContextArtifact]:
        """Return newest context artifacts, optionally filtered by session/kind."""
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""\
            SELECT artifact_id, session_id, kind, source_start_seq, source_end_seq,
                   content, metadata, token_count, model, provider, created_at, updated_at
            FROM context_artifacts
            {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,  # noqa: S608  # nosec B608 - placeholders are generated from a fixed count.
            (*params, max(1, int(limit))),
        ).fetchall()
        return [self._row_to_context_artifact(r) for r in rows]

    def search_context_artifacts(
        self,
        query: str,
        *,
        session_id: str | None = None,
        kinds: list[str] | tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """FTS5 search over synthesized context artifacts."""
        from core.memory.fts_query import sanitize_fts5_query

        clean = sanitize_fts5_query(query)
        if not clean:
            return []
        sql = (
            "SELECT a.artifact_id, a.session_id, a.kind, a.source_start_seq, "
            "a.source_end_seq, a.content, a.metadata, a.token_count, a.model, "
            "a.provider, a.created_at, a.updated_at, "
            "snippet(context_artifacts_fts, 0, '[', ']', '…', 16), "
            "bm25(context_artifacts_fts) "
            "FROM context_artifacts_fts JOIN context_artifacts a "
            "ON a.rowid = context_artifacts_fts.rowid "
            "WHERE context_artifacts_fts MATCH ?"
        )
        params: list[Any] = [clean]
        if session_id is not None:
            sql += " AND a.session_id = ?"
            params.append(session_id)
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            sql += f" AND a.kind IN ({placeholders})"
            params.extend(kinds)
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(1, int(limit)))
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            log.warning("search_context_artifacts FTS5 query failed: %s", exc)
            return []
        return [
            {
                "artifact_id": r[0],
                "session_id": r[1],
                "kind": r[2],
                "source_start_seq": r[3],
                "source_end_seq": r[4],
                "content": r[5],
                "metadata": _loads_json_object(r[6]),
                "token_count": r[7],
                "model": r[8],
                "provider": r[9],
                "created_at": r[10],
                "updated_at": r[11],
                "snippet": r[12],
                "score": r[13],
            }
            for r in rows
        ]

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
        # PR-CODEX-MULTITURN-PHASE-PRESERVE fold (Sprint H follow-up,
        # 2026-05-26) — un-fold the Codex sidecar keys (``phase``,
        # ``codex_reasoning_items``) that ``_extract_message_fields``
        # stashed into ``metadata`` on the way in. Without this
        # mirror the checkpoint/resume cycle silently drops the
        # phase semantic and the encrypted-reasoning replay blobs,
        # breaking multi-turn continuity on Codex gpt-5.x.
        metadata = msg.get("metadata")
        if isinstance(metadata, dict):
            for sidecar_key in ("phase", "codex_reasoning_items"):
                if sidecar_key in metadata:
                    msg[sidecar_key] = metadata[sidecar_key]
        return msg

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    @staticmethod
    def _row_to_context_artifact(row: tuple) -> ContextArtifact:  # type: ignore[type-arg]
        return ContextArtifact(
            artifact_id=str(row[0]),
            session_id=str(row[1]),
            kind=str(row[2]),
            source_start_seq=int(row[3]) if row[3] is not None else None,
            source_end_seq=int(row[4]) if row[4] is not None else None,
            content=str(row[5]),
            metadata=_loads_json_object(row[6]),
            token_count=int(row[7]) if row[7] is not None else None,
            model=str(row[8] or ""),
            provider=str(row[9] or ""),
            created_at=float(row[10] or 0.0),
            updated_at=float(row[11] or 0.0),
        )

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
