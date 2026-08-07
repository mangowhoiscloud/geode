"""PR-Q — ``run_dir_scope`` redirects every observability writer into
the per-cycle directory.

Verifies the consolidation contract: when an orchestrator binds a
run_dir, the four writers (RunTimeline / SessionTimeline /
WorkerResult / IsolatedRunner stderr) all land their output under
``<run_dir>/`` instead of the legacy ``~/.geode/<bucket>/`` global pools.

Outside an active scope every writer falls back to its legacy global
path so gateway / REPL / ad-hoc CLI / unrelated tests are unaffected.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def test_resolve_sub_agent_path_unbound_returns_none() -> None:
    from core.observability.run_dir import get_active_run_dir, resolve_sub_agent_path

    assert get_active_run_dir() is None
    assert resolve_sub_agent_path("task-x", "result.json") is None


def test_run_dir_scope_binds_and_restores() -> None:
    from core.observability.run_dir import get_active_run_dir, run_dir_scope

    assert get_active_run_dir() is None
    with tempfile.TemporaryDirectory() as tmp:
        with run_dir_scope(tmp) as bound_path:
            assert get_active_run_dir() == Path(tmp)
            assert bound_path == Path(tmp)
        # Scope exit restores prior (= None) binding.
        assert get_active_run_dir() is None


def test_resolve_sub_agent_path_inside_scope() -> None:
    from core.observability.run_dir import resolve_sub_agent_path, run_dir_scope

    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        result_path = resolve_sub_agent_path("task-A", "result.json")
        assert result_path is not None
        assert result_path == Path(tmp) / "sub_agents" / "task-A" / "result.json"
        # Parent dir auto-created so writers don't each duplicate mkdir.
        assert result_path.parent.is_dir()


def test_session_timeline_projects_into_run_dir() -> None:
    """SessionTimeline projects portable events beside child outputs."""
    from core.observability.run_dir import run_dir_scope
    from core.observability.session_timeline import SessionTimeline

    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        tx = SessionTimeline("s-redir01", db_path=Path(tmp) / "sessions.db")
        expected_file = Path(tmp) / "sub_agents" / "s-redir01" / "events.jsonl"
        assert tx.projection_path == expected_file
        tx.record_session_start(model="gpt-5.6")
        assert expected_file.exists()
        event_row = json.loads(expected_file.read_text().splitlines()[0])
        assert event_row["kind"] == "session.started"


def test_session_timeline_explicit_projection_overrides_run_dir() -> None:
    """Caller-supplied projection path wins over the active run_dir."""
    from core.observability.run_dir import run_dir_scope
    from core.observability.session_timeline import SessionTimeline

    with (
        tempfile.TemporaryDirectory() as run_dir_tmp,
        tempfile.TemporaryDirectory() as explicit_dir_tmp,
        run_dir_scope(run_dir_tmp),
    ):
        projection_path = Path(explicit_dir_tmp) / "events.jsonl"
        tx = SessionTimeline(
            "s-explicit01",
            db_path=Path(run_dir_tmp) / "sessions.db",
            projection_path=projection_path,
        )
        assert tx.projection_path == projection_path


def test_save_result_backup_redirects_into_run_dir() -> None:
    """worker.py ``_save_result_backup`` reads the active run_dir."""
    from core.agent.worker import WorkerResult, _save_result_backup
    from core.observability.run_dir import run_dir_scope

    result = WorkerResult(task_id="t-rdcheck", success=True, output="hello")
    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        _save_result_backup(result)
        expected = Path(tmp) / "sub_agents" / "t-rdcheck" / "result.json"
        assert expected.exists()
        data = json.loads(expected.read_text())
        assert data["task_id"] == "t-rdcheck"
        assert data["output"] == "hello"


def test_save_result_backup_legacy_pool_when_unbound() -> None:
    """Outside a scope ``_save_result_backup`` still writes to the
    legacy ``~/.geode/workers/`` pool — gateway / REPL / tests are
    unaffected by the consolidation."""
    from unittest.mock import patch

    from core.agent.worker import WorkerResult, _save_result_backup

    result = WorkerResult(task_id="t-legacy01", success=True, output="ok")
    with tempfile.TemporaryDirectory() as fake_global:
        fake_global_path = Path(fake_global)
        with patch("core.agent.worker.WORKER_DIR", fake_global_path):
            _save_result_backup(result)
            assert (fake_global_path / "t-legacy01.result.json").exists()
            # NOT under sub_agents/
            assert not (fake_global_path / "sub_agents").exists()


def test_isolated_runner_save_stderr_redirects_into_run_dir() -> None:
    """``IsolatedRunner._save_stderr`` reads the active run_dir."""
    from core.observability.run_dir import run_dir_scope
    from core.orchestration.isolated_execution import IsolatedRunner

    with tempfile.TemporaryDirectory() as tmp, run_dir_scope(tmp):
        IsolatedRunner._save_stderr("sess-err01", b"sample stderr bytes\n")
        expected = Path(tmp) / "sub_agents" / "sess-err01" / "stderr.log"
        assert expected.exists()
        assert expected.read_bytes() == b"sample stderr bytes\n"


def test_run_dir_env_constant() -> None:
    """``RUN_DIR_ENV`` is the canonical env var name the cross-process
    bridge uses. Pinning the constant prevents accidental rename."""
    from core.observability.run_dir import RUN_DIR_ENV

    assert RUN_DIR_ENV == "GEODE_RUN_DIR"
