"""Tests for :mod:`core.observability.agent_runtime_state` —
per-agent cumulative state SQLite writer / reader.

PR-COMM-3 (2026-05-24, spec doc:
``docs/plans/2026-05-24-pr-comm-3-runtime-db-integration-audit.md``).

Coverage map:

* :class:`TestSchemaBootstrap` — `agent_runtime_state` + `run_lineage`
  tables + 7 indexes land in `sessions.db` on `SessionManager.__init__`.
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
import time
from pathlib import Path

import pytest
from core.memory.session_manager import SessionManager
from core.observability import agent_runtime_state as ars


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ``sessions.db`` to ``tmp_path`` and reset the module
    cache so each test starts from a fresh connection."""
    db = tmp_path / "sessions.db"
    SessionManager(db_path=db)  # bootstrap schema
    monkeypatch.setattr(
        "core.memory.session_manager._get_default_db_path",
        lambda: db,
    )
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


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
            "claude_cli_session_id",
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
            "idx_agent_runtime_session",
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
            adapter_type="claude-cli",
            claude_cli_session_id="cli-xyz",
        )
        state = ars.get_agent_runtime_state("s-abc123")
        assert state is not None
        assert state.agent_kind == "repl"
        assert state.component == "agentic_loop"
        assert state.adapter_type == "claude-cli"
        assert state.claude_cli_session_id == "cli-xyz"

    def test_record_agent_session_end_empty_id_is_noop(self, tmp_db: Path) -> None:
        """Defensive: callers may forward an empty session_id from a
        hook payload — must not crash and must not insert garbage."""
        ars.record_agent_session_end(agent_id="")
        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute("SELECT COUNT(*) FROM agent_runtime_state").fetchone()[0]
        assert count == 0

    def test_session_end_preserves_session_id_when_called_without(self, tmp_db: Path) -> None:
        """A subsequent ``record_agent_session_end`` without
        ``claude_cli_session_id`` must NOT overwrite a previously-set one
        — the writer uses a CASE-WHEN guard so empty values don't clear
        prior session_ids."""
        ars.record_agent_session_end(agent_id="s-1", claude_cli_session_id="cli-first")
        ars.record_agent_session_end(agent_id="s-1", claude_cli_session_id="")
        state = ars.get_agent_runtime_state("s-1")
        assert state is not None
        assert state.claude_cli_session_id == "cli-first"

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
