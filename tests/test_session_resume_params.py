"""PR-SESSION-RESUME-PARAMS (2026-05-25) — paperclip-aligned cwd-paired
resume-context tests.

Smoke 12 (v0.99.54) surfaced a stale-session bug: claude-cli's
session storage is cwd-keyed (``~/.claude/projects/<cwd-slug>/``),
so a UUID stored in SQLite from cwd A produces "No conversation
found" when ``_load_prior_session_id`` returns it for a worker
running in cwd B. The fix mirrors paperclip's
``claudeSessionCwdMatchesExecutionTarget`` from
``packages/adapters/claude-local/src/server/execute.ts:592``: a
paired ``cwd`` field stored alongside the session_id, and a
read-time ``path.resolve()`` equality gate.

This file tests:
1. ``_saved_cwd_matches_current`` resolve-equality helper.
2. ``record_agent_session_end`` round-trips
   ``session_resume_params={"cwd": ...}``.
3. ``get_agent_runtime_state`` returns the parsed dict.
4. ``_load_prior_session_id`` returns "" on cwd mismatch (the
   smoke 12 regression scenario) and the saved id on cwd match.
5. Legacy rows with empty ``session_resume_params`` skip the gate
   (back-compat — pre-fix DBs / direct-call surfaces).
6. ``_persist_session_id`` writes the cwd into both SQLite and
   the session.json file fallback when ``get_task_isolated_cwd()``
   is bound.
"""

from __future__ import annotations

import json

import pytest

# ────────────────────── _saved_cwd_matches_current ────────────────────────────


def test_match_helper_returns_true_when_both_empty() -> None:
    """Legacy direct-call surface — neither side has a cwd to compare."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    assert _saved_cwd_matches_current("", "") is True


def test_match_helper_returns_true_when_stored_empty_legacy_row() -> None:
    """Pre-fix SQLite rows have empty ``session_resume_params`` →
    no cwd recorded → gate skips so resume goes through (back-compat)."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    assert _saved_cwd_matches_current("", "/Users/u/wkspc/sub_agents/x/cwd") is True


def test_match_helper_returns_true_when_current_empty_direct_call() -> None:
    """Direct-call surface (no per-task isolation) — current cwd is empty,
    so the gate skips. This preserves the original PR-V behaviour."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    assert _saved_cwd_matches_current("/Users/u/wkspc/sub_agents/x/cwd", "") is True


def test_match_helper_returns_true_on_equal_paths() -> None:
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    p = "/Users/u/wkspc/sub_agents/x/cwd"
    assert _saved_cwd_matches_current(p, p) is True


def test_match_helper_returns_false_on_different_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The smoke 12 scenario — saved cwd != current cwd → fresh session."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    a = tmp_path / "sub_agents" / "proximity" / "cwd"
    b = tmp_path / "sub_agents" / "critic" / "cwd"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert _saved_cwd_matches_current(str(a), str(b)) is False


def test_match_helper_normalises_trailing_slash(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``path.resolve()`` strips trailing slashes; the gate must too."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    d = tmp_path / "real-cwd"
    d.mkdir()
    assert _saved_cwd_matches_current(f"{d}/", str(d)) is True


def test_match_helper_normalises_dotdot(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``a/b/../c`` and ``a/c`` resolve to the same absolute path."""
    from core.agent.loop.agent_loop import _saved_cwd_matches_current

    base = tmp_path / "a" / "c"
    base.mkdir(parents=True)
    raw = f"{tmp_path}/a/b/../c"
    assert _saved_cwd_matches_current(str(base), raw) is True


# ────────────────────── SQLite round-trip ─────────────────────────────────────


def _isolated_db(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Point the runtime-state singleton at a fresh tmp DB per test.

    Mirrors ``tests/test_agent_runtime_state.py:tmp_db`` exactly:
    bootstrap schema via ``SessionManager(db_path=...)``, monkeypatch
    the canonical resolver, then reset the agent_runtime_state cached
    connection so the next ``_get_conn()`` rebuilds against the tmp
    path.
    """
    from core.memory.session_manager import SessionManager

    from core.observability import agent_runtime_state as ars

    db_path = tmp_path / "sessions.db"
    SessionManager(db_path=db_path)
    monkeypatch.setattr(
        "core.memory.session_manager._get_default_db_path",
        lambda: db_path,
    )
    ars._reset_for_tests(db_path=db_path)


def test_record_agent_session_end_round_trips_resume_params(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _isolated_db(monkeypatch, tmp_path)
    from core.observability.agent_runtime_state import (
        get_agent_runtime_state,
        record_agent_session_end,
    )

    record_agent_session_end(
        agent_id="proximity-gen1-test",
        claude_cli_session_id="uuid-aaa",
        session_resume_params={"cwd": "/Users/u/wkspc/sub_agents/proximity/cwd"},
    )
    state = get_agent_runtime_state("proximity-gen1-test")
    assert state is not None
    assert state.claude_cli_session_id == "uuid-aaa"
    assert state.session_resume_params == {"cwd": "/Users/u/wkspc/sub_agents/proximity/cwd"}


def test_record_agent_session_end_legacy_path_empty_params(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """When caller passes no resume_params (REPL / gateway) the stored
    blob is empty (``{}``) and the reader's gate skips."""
    _isolated_db(monkeypatch, tmp_path)
    from core.observability.agent_runtime_state import (
        get_agent_runtime_state,
        record_agent_session_end,
    )

    record_agent_session_end(
        agent_id="repl-session-x",
        claude_cli_session_id="uuid-bbb",
    )
    state = get_agent_runtime_state("repl-session-x")
    assert state is not None
    assert state.session_resume_params == {}


def test_record_agent_session_end_preserves_resume_params_across_upserts(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """First call sets cwd. Second call with empty resume_params (e.g.
    a token-only update) must NOT wipe the previously stored cwd."""
    _isolated_db(monkeypatch, tmp_path)
    from core.observability.agent_runtime_state import (
        get_agent_runtime_state,
        record_agent_session_end,
    )

    record_agent_session_end(
        agent_id="agent-preserve",
        claude_cli_session_id="uuid-ccc",
        session_resume_params={"cwd": "/tmp/cwd-1"},  # noqa: S108
    )
    # Second upsert without resume_params (mimics an unrelated update path).
    record_agent_session_end(
        agent_id="agent-preserve",
        claude_cli_session_id="uuid-ccc",
    )
    state = get_agent_runtime_state("agent-preserve")
    assert state is not None
    assert state.session_resume_params == {"cwd": "/tmp/cwd-1"}  # noqa: S108


def test_get_agent_runtime_state_graceful_on_malformed_json(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Operator hand-edits or legacy non-JSON content must NOT crash —
    the reader degrades to ``{}`` so the gate skips."""
    _isolated_db(monkeypatch, tmp_path)
    from core.observability.agent_runtime_state import get_agent_runtime_state

    from core.observability import agent_runtime_state as ars

    conn = ars._get_conn()
    assert conn is not None
    import time as _t

    now = _t.time()
    conn.execute(
        """INSERT INTO agent_runtime_state
            (agent_id, claude_cli_session_id, session_resume_params,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
        ("agent-malformed", "uuid-ddd", "this-is-not-json", now, now),
    )
    conn.commit()
    state = get_agent_runtime_state("agent-malformed")
    assert state is not None
    assert state.session_resume_params == {}  # graceful degrade
    # ``claude_cli_session_id`` still loaded correctly.
    assert state.claude_cli_session_id == "uuid-ddd"


# ────────────────────── _load_prior_session_id integration ────────────────────


def test_load_prior_session_id_returns_id_on_cwd_match(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _load_prior_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import record_agent_session_end

    cwd = tmp_path / "match-cwd"
    cwd.mkdir()
    record_agent_session_end(
        agent_id="agent-match",
        claude_cli_session_id="uuid-eee",
        session_resume_params={"cwd": str(cwd)},
    )
    set_task_isolated_cwd(cwd)
    try:
        assert _load_prior_session_id("agent-match") == "uuid-eee"
    finally:
        set_task_isolated_cwd(None)


def test_load_prior_session_id_returns_empty_on_cwd_mismatch(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """Smoke 12 regression — saved cwd differs from current per-task cwd
    → return "" so adapter starts a fresh session instead of resuming
    against a pool that doesn't hold the session file."""
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _load_prior_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import record_agent_session_end

    saved_cwd = tmp_path / "smoke-11-cwd"
    current_cwd = tmp_path / "smoke-12-cwd"
    saved_cwd.mkdir()
    current_cwd.mkdir()
    record_agent_session_end(
        agent_id="proximity-stale",
        claude_cli_session_id="uuid-fff",
        session_resume_params={"cwd": str(saved_cwd)},
    )
    set_task_isolated_cwd(current_cwd)
    try:
        assert _load_prior_session_id("proximity-stale") == ""
    finally:
        set_task_isolated_cwd(None)


def test_load_prior_session_id_returns_id_on_legacy_empty_params(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """Pre-PR-SESSION-RESUME-PARAMS rows have empty params → gate skips
    → resume id returned (back-compat preserved)."""
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _load_prior_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import record_agent_session_end

    record_agent_session_end(
        agent_id="legacy-agent",
        claude_cli_session_id="uuid-ggg",
    )
    set_task_isolated_cwd(tmp_path / "any-cwd")
    (tmp_path / "any-cwd").mkdir()
    try:
        assert _load_prior_session_id("legacy-agent") == "uuid-ggg"
    finally:
        set_task_isolated_cwd(None)


def test_load_prior_session_id_returns_id_on_direct_call_no_isolation(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """No per-task isolation bound (REPL / gateway / one-shot) → current
    cwd is empty → gate skips → resume id returned."""
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _load_prior_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import record_agent_session_end

    record_agent_session_end(
        agent_id="repl-x",
        claude_cli_session_id="uuid-hhh",
        session_resume_params={"cwd": "/some/saved/cwd"},
    )
    set_task_isolated_cwd(None)
    assert _load_prior_session_id("repl-x") == "uuid-hhh"


# ────────────────────── _persist_session_id end-to-end ────────────────────────


def test_persist_session_id_writes_cwd_to_sqlite_and_file(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """When ``get_task_isolated_cwd()`` returns a bound cwd, the writer
    paths (SQLite primary + session.json fallback) BOTH carry the
    paired cwd. Symmetric with the reader's gate."""
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _persist_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import get_agent_runtime_state
    from core.observability.run_dir import set_active_run_dir

    set_active_run_dir(tmp_path)
    task_cwd = tmp_path / "sub_agents" / "evolver-test" / "cwd"
    task_cwd.mkdir(parents=True)
    set_task_isolated_cwd(task_cwd)
    try:
        _persist_session_id("evolver-test", "uuid-iii")
    finally:
        set_task_isolated_cwd(None)
        set_active_run_dir(None)

    # SQLite primary
    state = get_agent_runtime_state("evolver-test")
    assert state is not None
    assert state.claude_cli_session_id == "uuid-iii"
    assert state.session_resume_params.get("cwd") == str(task_cwd)

    # session.json file fallback
    session_json = tmp_path / "sub_agents" / "evolver-test" / "session.json"
    assert session_json.exists()
    payload = json.loads(session_json.read_text(encoding="utf-8"))
    assert payload["claude_cli_session_id"] == "uuid-iii"
    assert payload["cwd"] == str(task_cwd)


def test_persist_session_id_omits_cwd_when_isolation_unset(  # type: ignore[no-untyped-def]
    monkeypatch, tmp_path
) -> None:
    """No per-task isolation → ``cwd`` field omitted from both writers
    (back-compat — legacy callers / REPL / gateway)."""
    _isolated_db(monkeypatch, tmp_path)
    from core.agent.loop.agent_loop import _persist_session_id
    from core.agent.task_isolation import set_task_isolated_cwd
    from core.observability.agent_runtime_state import get_agent_runtime_state
    from core.observability.run_dir import set_active_run_dir

    set_active_run_dir(tmp_path)
    set_task_isolated_cwd(None)
    _persist_session_id("repl-no-isolation", "uuid-jjj")
    set_active_run_dir(None)

    state = get_agent_runtime_state("repl-no-isolation")
    assert state is not None
    assert state.claude_cli_session_id == "uuid-jjj"
    assert "cwd" not in state.session_resume_params

    session_json = tmp_path / "sub_agents" / "repl-no-isolation" / "session.json"
    if session_json.exists():
        payload = json.loads(session_json.read_text(encoding="utf-8"))
        assert "cwd" not in payload


# ────────────────────── Migration sanity ──────────────────────────────────────


def test_schema_carries_session_resume_params_column(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Fresh DB must include the new column from
    ``_CREATE_AGENT_RUNTIME_STATE_TABLE_SQL``."""
    _isolated_db(monkeypatch, tmp_path)
    from core.observability import agent_runtime_state as ars

    conn = ars._get_conn()
    assert conn is not None
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(agent_runtime_state)").fetchall()}
    assert "session_resume_params" in cols


def test_alter_table_adds_column_to_legacy_db(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Simulate a legacy DB: create the table without the new column,
    then re-open through SessionManager and verify the migration ALTER
    fired."""
    db_path = tmp_path / "legacy.db"
    import sqlite3

    legacy = sqlite3.connect(str(db_path))
    legacy.execute(
        """CREATE TABLE agent_runtime_state (
            agent_id TEXT PRIMARY KEY,
            agent_kind TEXT NOT NULL DEFAULT 'subagent',
            component TEXT NOT NULL DEFAULT 'agentic_loop',
            adapter_type TEXT NOT NULL DEFAULT '',
            claude_cli_session_id TEXT NOT NULL DEFAULT '',
            last_run_id TEXT NOT NULL DEFAULT '',
            last_run_status TEXT NOT NULL DEFAULT '',
            total_input_tokens INTEGER NOT NULL DEFAULT 0,
            total_output_tokens INTEGER NOT NULL DEFAULT 0,
            total_cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            total_cost_cents INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )"""
    )
    legacy.commit()
    legacy.close()

    # Re-open via SessionManager → migration runs.
    from core.memory.session_manager import SessionManager

    SessionManager(db_path)
    check = sqlite3.connect(str(db_path))
    cols = {str(r[1]) for r in check.execute("PRAGMA table_info(agent_runtime_state)").fetchall()}
    check.close()
    assert "session_resume_params" in cols


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
