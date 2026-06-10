"""PR-COMM-3c — _persist_session_id / _load_prior_session_id SQLite
migration tests.

PR-V (#1588) introduced ``<run_dir>/sub_agents/<task_id>/session.json``
as the on-disk cache for the claude-cli sessionId the next
``--resume`` should use. PR-COMM-3 (#1593) + PR-COMM-3b (#1594) landed
the SQLite ``agent_runtime_state.claude_cli_session_id`` column and
wired the SESSION_ENDED hook handler to populate it.

PR-COMM-3c flips ``_persist_session_id`` to dual-write (SQLite primary
+ file fallback) and ``_load_prior_session_id`` to SQLite-first read.
The legacy file path is retained for 1-release grace so existing
on-disk caches still resume cleanly during the transition; scheduled
for deletion in v0.99.54.

Coverage map:

* :class:`TestSqlitePrimaryRead` — SQLite has the value, file has a
  stale value → reader returns SQLite.
* :class:`TestFileFallbackRead` — SQLite empty, file has a value →
  reader returns the file value (legacy deploys unaffected).
* :class:`TestDualWrite` — single persist call lands in BOTH stores
  with the same value.
* :class:`TestEmptySessionIdNoop` — empty emitted_session_id touches
  neither store (preserves prior cached values for cross-cycle resume
  when a non-claude-cli adapter ran in the middle).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_sessions_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect sessions.db to tmp_path + reset module-level cache."""
    from core.memory.session_manager import SessionManager
    from core.observability import agent_runtime_state as ars

    db = tmp_path / "sessions.db"
    SessionManager(db_path=db)
    monkeypatch.setattr("core.memory.session_manager._get_default_db_path", lambda: db)
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


class TestSqlitePrimaryRead:
    """SQLite is the authoritative source — when both stores have a
    value, the reader returns the SQLite value (the file is a fallback
    for legacy on-disk caches only)."""

    def test_sqlite_wins_over_file(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _load_prior_session_id
        from core.observability.agent_runtime_state import record_agent_session_end
        from core.observability.run_dir import run_dir_scope

        task_id = "gen-sqlite-primary"

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            # Stale file value — simulates a legacy deploy that wrote
            # session.json before the SQLite writer landed.
            session_path = Path(tmp) / "sub_agents" / task_id / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(json.dumps({"claude_cli_session_id": "stale-file-value"}))

            # SQLite carries the current value.
            record_agent_session_end(agent_id=task_id, claude_cli_session_id="current-sqlite-value")

            assert _load_prior_session_id(task_id) == "current-sqlite-value"


class TestFileFallbackRead:
    """SQLite-miss falls back to session.json so existing on-disk
    caches keep working through the 1-release grace window."""

    def test_file_fallback_when_sqlite_empty(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _load_prior_session_id
        from core.observability.run_dir import run_dir_scope

        task_id = "gen-file-fallback"

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            session_path = Path(tmp) / "sub_agents" / task_id / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(json.dumps({"claude_cli_session_id": "legacy-only-value"}))
            # SQLite has no row — fallback path triggers.
            assert _load_prior_session_id(task_id) == "legacy-only-value"

    def test_both_empty_returns_empty(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _load_prior_session_id

        # No run_dir scope, no SQLite row — fresh-session fallback.
        assert _load_prior_session_id("unknown-task") == ""


class TestDualWrite:
    """``_persist_session_id`` writes the value to both stores in one
    call so subsequent reads see consistent state regardless of which
    backend the reader prefers."""

    def test_persist_lands_in_sqlite(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _persist_session_id
        from core.observability.agent_runtime_state import get_agent_runtime_state
        from core.observability.run_dir import run_dir_scope

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            _persist_session_id("gen-dual-1", "cli-dual-001")
            state = get_agent_runtime_state("gen-dual-1")
            assert state is not None
            assert state.claude_cli_session_id == "cli-dual-001"

    def test_persist_lands_in_file(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _persist_session_id
        from core.observability.run_dir import run_dir_scope

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            _persist_session_id("gen-dual-2", "cli-dual-002")
            session_path = Path(tmp) / "sub_agents" / "gen-dual-2" / "session.json"
            assert session_path.exists()
            data = json.loads(session_path.read_text())
            assert data["claude_cli_session_id"] == "cli-dual-002"

    def test_persist_outside_run_dir_still_writes_sqlite(self, tmp_path: Path) -> None:
        """REPL / gateway path has no run_dir scope so the file write
        no-ops, but the SQLite write must still land — that's the
        whole point of the migration."""
        from core.agent.loop.agent_loop import _persist_session_id
        from core.observability.agent_runtime_state import get_agent_runtime_state

        # No run_dir_scope here — simulates REPL / gateway.
        _persist_session_id("repl-no-rundir", "cli-repl-001")
        state = get_agent_runtime_state("repl-no-rundir")
        assert state is not None
        assert state.claude_cli_session_id == "cli-repl-001"


class TestEmptySessionIdNoop:
    """Empty ``emitted_session_id`` (non-claude-cli adapters) must NOT
    touch either store — preserves prior cached values when a
    different adapter ran in the middle of a cross-cycle chain."""

    def test_empty_does_not_clear_sqlite(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _load_prior_session_id, _persist_session_id

        _persist_session_id("gen-noop-1", "cli-original")
        _persist_session_id("gen-noop-1", "")  # noop
        assert _load_prior_session_id("gen-noop-1") == "cli-original"

    def test_empty_does_not_clear_file(self, tmp_path: Path) -> None:
        from core.agent.loop.agent_loop import _persist_session_id
        from core.observability.run_dir import run_dir_scope

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            _persist_session_id("gen-noop-2", "cli-original")
            _persist_session_id("gen-noop-2", "")
            session_path = Path(tmp) / "sub_agents" / "gen-noop-2" / "session.json"
            data = json.loads(session_path.read_text())
            assert data["claude_cli_session_id"] == "cli-original"


class TestSqliteFailureFallsBackToFile:
    """Even if the SQLite layer is broken (DB locked, permission
    denied), the file fallback keeps reads working — defensive
    contract that the dual-write earns."""

    def test_load_falls_back_when_sqlite_read_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.agent.loop.agent_loop import _load_prior_session_id
        from core.observability.run_dir import run_dir_scope

        task_id = "gen-fallback-on-error"

        with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
            session_path = Path(tmp) / "sub_agents" / task_id / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(json.dumps({"claude_cli_session_id": "file-survivor"}))

            def _boom(_agent_id: str) -> None:
                raise RuntimeError("simulated SQLite outage")

            monkeypatch.setattr(
                "core.observability.agent_runtime_state.get_agent_runtime_state",
                _boom,
            )

            assert _load_prior_session_id(task_id) == "file-survivor"
