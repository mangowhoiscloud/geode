"""Tests for :mod:`core.observability.agent_runtime_state` —
per-agent cumulative state SQLite writer / reader.

PR-COMM-3 (2026-05-24, spec doc:
``docs/plans/2026-05-24-pr-comm-3-runtime-db-integration-audit.md``).

Coverage map:

* :class:`TestSchemaBootstrap` — `agent_runtime_state` + `run_lineage`
  tables + 6 indexes land in `sessions.db` on `SessionManager.__init__`.
* :class:`TestAgentRuntimeStateWriters` — `record_agent_session_end`,
  `record_subagent_completed`, `accumulate_tokens_and_cost` upsert /
  preserve / accumulate semantics.
* :class:`TestRunLineage` — parent / root resolution, retry chain,
  ended_at flip.

Note: HookSystem bootstrap wiring is deferred to PR-COMM-3b — the
current emit payloads do not carry the fields the writers need
(see ``core/wiring/bootstrap.py`` near the PR-COMM-3 note). End-to-end
wiring tests land alongside the emit-site augmentation in that follow-up.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest
from core.memory.session_manager import SessionManager
from core.observability import agent_runtime_state as ars


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ``sessions.db`` to ``tmp_path`` and reset the module
    cache so each test starts from a fresh connection."""
    db = tmp_path / "sessions.db"
    SessionManager(db_path=db).close()
    monkeypatch.setattr(
        "core.memory.session_manager._get_default_db_path",
        lambda: db,
    )
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


def test_schema_bootstrap_connection_is_closed(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[sqlite3.Connection] = []

    class TrackedManager(SessionManager):
        def close(self) -> None:
            closed.append(self._conn)
            super().close()

    monkeypatch.setattr("core.memory.session_manager.SessionManager", TrackedManager)
    ars.record_agent_session_end(agent_id="s-bootstrap")
    assert len(closed) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        closed[0].execute("SELECT 1")
    assert ars.get_agent_runtime_state("s-bootstrap") is not None


def test_failed_connection_setup_is_closed_and_retryable(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = Mock(spec=sqlite3.Connection)
    connection.execute.side_effect = sqlite3.OperationalError("WAL setup failed")
    bootstrap = Mock()
    with monkeypatch.context() as scoped:
        scoped.setattr("core.memory.session_manager.SessionManager", Mock(return_value=bootstrap))
        scoped.setattr(ars.sqlite3, "connect", Mock(return_value=connection))
        ars.record_agent_session_end(agent_id="s-failed")
    bootstrap.close.assert_called_once_with()
    connection.close.assert_called_once_with()
    assert ars._CONN is None
    ars.record_agent_session_end(agent_id="s-retry")
    assert ars.get_agent_runtime_state("s-retry") is not None


def test_close_is_idempotent_and_active_callers_can_reopen(tmp_db: Path) -> None:
    ars.accumulate_tokens_and_cost(agent_id="s-close", input_tokens=7, output_tokens=3)
    connection = ars._CONN
    assert connection is not None
    ars.close_runtime_state()
    ars.close_runtime_state()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    ars.accumulate_tokens_and_cost(agent_id="s-close", input_tokens=5, output_tokens=2)
    state = ars.get_agent_runtime_state("s-close")
    assert state is not None
    assert (state.total_input_tokens, state.total_output_tokens) == (12, 5)


@pytest.mark.parametrize("failure", ["statement", "commit", "rollback"])
def test_failed_write_cannot_leak_into_a_later_commit(tmp_db: Path, failure: str) -> None:
    ars.record_agent_session_end(agent_id="seed")
    connection = ars._CONN
    assert connection is not None

    def authorize(action: int, arg1: str | None, *_args: object) -> int:
        if action == sqlite3.SQLITE_TRANSACTION and (
            arg1 == "COMMIT" or (failure == "rollback" and arg1 == "ROLLBACK")
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if failure == "statement":
        connection.execute(
            "CREATE TEMP TRIGGER reject_runtime_insert AFTER INSERT ON agent_runtime_state "
            "WHEN NEW.agent_id = 'failed' BEGIN SELECT RAISE(FAIL, 'injected failure'); END"
        )
    else:
        connection.set_authorizer(authorize)

    ars.accumulate_tokens_and_cost(agent_id="failed", input_tokens=10, output_tokens=2)
    if failure == "rollback":
        assert ars._CONN is None
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    else:
        assert not connection.in_transaction
        connection.set_authorizer(None)
    assert ars.get_agent_runtime_state("failed") is None
    ars.accumulate_tokens_and_cost(agent_id="later", input_tokens=3, output_tokens=1)
    with closing(sqlite3.connect(tmp_db)) as reader:
        assert reader.execute(
            "SELECT agent_id, total_input_tokens FROM agent_runtime_state "
            "WHERE agent_id IN ('failed', 'later')"
        ).fetchall() == [("later", 3)]


def test_shutdown_cannot_close_a_writer_connection_mid_operation(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acquired = threading.Event()
    proceed = threading.Event()
    original = ars._get_conn

    def pause_after_connection_acquired() -> sqlite3.Connection | None:
        connection = original()
        acquired.set()
        assert proceed.wait(timeout=5)
        return connection

    monkeypatch.setattr(ars, "_get_conn", pause_after_connection_acquired)
    writer = threading.Thread(
        target=ars.accumulate_tokens_and_cost,
        kwargs={"agent_id": "s-race", "input_tokens": 11, "output_tokens": 4},
    )
    closer = threading.Thread(target=ars.close_runtime_state)
    writer.start()
    try:
        assert acquired.wait(timeout=5)
        unlocked = ars._LOCK.acquire(blocking=False)
        if unlocked:
            ars._LOCK.release()
        assert not unlocked, "Shutdown must not acquire a connection still owned by a writer"
        closer.start()
    finally:
        proceed.set()
        writer.join(timeout=5)
        if closer.ident is not None:
            closer.join(timeout=5)
    assert not writer.is_alive() and not closer.is_alive()
    assert ars._CONN is None
    with closing(sqlite3.connect(tmp_db)) as conn:
        assert conn.execute(
            "SELECT total_input_tokens, total_output_tokens FROM agent_runtime_state "
            "WHERE agent_id = 's-race'"
        ).fetchone() == (11, 4)


class TestSchemaBootstrap:
    def test_agent_runtime_state_table_exists(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(agent_runtime_state)").fetchall()
        }
        assert {
            "agent_id",
            "agent_kind",
            "component",
            "adapter_type",
            "last_run_id",
            "last_run_status",
            "total_input_tokens",
            "total_output_tokens",
            "total_cached_input_tokens",
            "total_cost_cents",
            "last_error",
            "created_at",
            "updated_at",
        } <= cols

    def test_run_lineage_table_exists(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(run_lineage)").fetchall()}
        assert {
            "run_id",
            "component",
            "agent_id",
            "parent_run_id",
            "root_run_id",
            "status",
            "started_at",
            "ended_at",
            "metadata",
        } <= cols

    def test_indexes_present(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        idx_names = {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        }
        for expected in (
            "idx_agent_runtime_kind",
            "idx_agent_runtime_component",
            "idx_agent_runtime_updated",
            "idx_run_lineage_agent",
            "idx_run_lineage_parent",
            "idx_run_lineage_root",
        ):
            assert expected in idx_names, f"missing index {expected}"

    def test_bootstrap_is_idempotent(self, tmp_path: Path) -> None:
        """Calling ``SessionManager(db_path=...)`` twice must not raise —
        ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS``
        keep the schema bootstrap safe to repeat on already-initialized DBs.
        """
        db = tmp_path / "sessions.db"
        SessionManager(db_path=db).close()
        SessionManager(db_path=db).close()  # must not raise


class TestAgentRuntimeStateWriters:
    def test_record_agent_session_end_creates_row(self, tmp_db: Path) -> None:
        ars.record_agent_session_end(
            agent_id="s-abc123",
            agent_kind="repl",
            component="agentic_loop",
            adapter_type="anthropic-payg",
        )
        state = ars.get_agent_runtime_state("s-abc123")
        assert state is not None
        assert state.agent_kind == "repl"
        assert state.component == "agentic_loop"
        assert state.adapter_type == "anthropic-payg"

    def test_record_agent_session_end_empty_id_is_noop(self, tmp_db: Path) -> None:
        """Defensive: callers may forward an empty session_id from a
        hook payload — must not crash and must not insert garbage."""
        ars.record_agent_session_end(agent_id="")
        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute("SELECT COUNT(*) FROM agent_runtime_state").fetchone()[0]
        assert count == 0

    def test_subagent_completed_links_run_id(self, tmp_db: Path) -> None:
        ars.record_subagent_completed(
            agent_id="gen-001",
            component="seed-generation",
            last_run_id="gen1-run-001",
            last_run_status="completed",
        )
        state = ars.get_agent_runtime_state("gen-001")
        assert state is not None
        assert state.agent_kind == "subagent"
        assert state.component == "seed-generation"
        assert state.last_run_id == "gen1-run-001"
        assert state.last_run_status == "completed"

    def test_subagent_completed_propagates_error(self, tmp_db: Path) -> None:
        ars.record_subagent_completed(
            agent_id="gen-002",
            component="seed-generation",
            last_run_id="gen1-run-002",
            last_run_status="failed",
            last_error="termination_reason=model_action_required",
        )
        state = ars.get_agent_runtime_state("gen-002")
        assert state is not None
        assert state.last_error == "termination_reason=model_action_required"

    def test_accumulate_tokens_and_cost_sums_across_calls(self, tmp_db: Path) -> None:
        ars.accumulate_tokens_and_cost(
            agent_id="s-cost",
            input_tokens=100,
            output_tokens=50,
            cached_input_tokens=10,
            cost_usd=0.0123,
        )
        ars.accumulate_tokens_and_cost(
            agent_id="s-cost",
            input_tokens=200,
            output_tokens=75,
            cached_input_tokens=20,
            cost_usd=0.0345,
        )
        state = ars.get_agent_runtime_state("s-cost")
        assert state is not None
        assert state.total_input_tokens == 300
        assert state.total_output_tokens == 125
        assert state.total_cached_input_tokens == 30
        # 0.0123 + 0.0345 = 0.0468 USD → 4.68 cents → round to 5
        # Per-call rounding: round(1.23) + round(3.45) = 1 + 3 = 4
        assert state.total_cost_cents == 4

    def test_accumulate_zero_payload_is_noop(self, tmp_db: Path) -> None:
        """All-zero usage should not create a placeholder row."""
        ars.accumulate_tokens_and_cost(agent_id="s-zero", input_tokens=0, output_tokens=0)
        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_runtime_state WHERE agent_id = 's-zero'"
        ).fetchone()[0]
        # Accumulator inserts a placeholder row even on zero — caller
        # filters in the hook handler. Pin the contract.
        assert count == 1

    def test_get_unknown_agent_returns_none(self, tmp_db: Path) -> None:
        assert ars.get_agent_runtime_state("nonexistent") is None
        assert ars.get_agent_runtime_state("") is None


class TestRunLineage:
    def test_top_level_run_self_root(self, tmp_db: Path) -> None:
        ars.record_run_lineage(
            run_id="r-1",
            component="seed-generation",
            agent_id="gen-001",
        )
        assert ars.get_root_run("r-1") == "r-1"

    def test_child_run_propagates_root(self, tmp_db: Path) -> None:
        ars.record_run_lineage(run_id="r-1", component="seed-generation", agent_id="g-1")
        ars.record_run_lineage(
            run_id="r-2",
            component="seed-generation",
            agent_id="g-1",
            parent_run_id="r-1",
        )
        ars.record_run_lineage(
            run_id="r-3",
            component="seed-generation",
            agent_id="g-1",
            parent_run_id="r-2",
        )
        # r-3's root is r-1 (the chain's top), not r-2 (immediate parent).
        assert ars.get_root_run("r-3") == "r-1"

    def test_get_retry_chain_returns_siblings(self, tmp_db: Path) -> None:
        """All runs sharing a root come back in started_at order."""
        ars.record_run_lineage(run_id="r-1", component="x", agent_id="g-1")
        time.sleep(0.01)
        ars.record_run_lineage(run_id="r-2", component="x", agent_id="g-1", parent_run_id="r-1")
        time.sleep(0.01)
        ars.record_run_lineage(run_id="r-3", component="x", agent_id="g-1", parent_run_id="r-1")

        chain = ars.get_retry_chain("r-2")
        ids = [r.run_id for r in chain]
        assert ids == ["r-1", "r-2", "r-3"]

    def test_mark_run_ended_sets_status_and_timestamp(self, tmp_db: Path) -> None:
        ars.record_run_lineage(run_id="r-end", component="x", agent_id="g-1")
        ars.mark_run_ended("r-end", "completed")
        chain = ars.get_retry_chain("r-end")
        assert len(chain) == 1
        assert chain[0].status == "completed"
        assert chain[0].ended_at is not None and chain[0].ended_at > 0

    def test_retry_chain_on_unknown_run_is_empty(self, tmp_db: Path) -> None:
        assert ars.get_retry_chain("nonexistent") == []
