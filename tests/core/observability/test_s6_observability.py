"""S-6 observability sprint guards (2026-06-11).

Pins the audit fixes: the sessions.jsonl row carries the run's
SessionMetrics payload (``to_session_row`` had zero production callers),
the run-scoped metrics instance is identity-seeded at train start, the
scheduler JSONL tail has one home, the
SessionMetrics/LatencyMetrics namespace collision is resolved, and the
entry-point logging switchboard behaves per mode.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 1. sessions.jsonl carries metrics (HIGH finding)
# ---------------------------------------------------------------------------


def test_train_session_index_merges_metrics_row() -> None:
    """train.py's registry append must spread the SessionMetrics row.

    Source-level pin: the write-only ``to_session_row()`` regression was
    invisible to unit tests (the method itself was tested); what broke was
    the CALL. Assert the call site exists and spreads into ``extra``.
    """
    src = (REPO_ROOT / "core" / "self_improving" / "train.py").read_text(encoding="utf-8")
    assert "to_session_row()" in src, "metrics row no longer persisted to sessions.jsonl"
    call_block = src[src.index("_metrics_row = current_session_metrics().to_session_row()") :]
    call_block = call_block[: call_block.index(")\n\n")]
    assert "**_metrics_row" in call_block, "metrics row not merged into the extra payload"


def test_train_seeds_session_metrics_identity() -> None:
    """The run-scoped SessionMetrics is identity-seeded at main() start."""
    src = (REPO_ROOT / "core" / "self_improving" / "train.py").read_text(encoding="utf-8")
    assert "set_current_session_metrics(" in src
    seed_block = src[src.index("set_current_session_metrics(") :][:400]
    for ident in ("session_id=session_id", "gen_tag=gen_tag", 'component="autoresearch"'):
        assert ident in seed_block, f"identity field missing from seed: {ident}"


def test_metrics_row_identity_keys_do_not_clobber() -> None:
    """to_session_row identity keys are stripped before the extra merge."""
    from core.observability import SessionMetrics

    row = SessionMetrics(session_id="s", gen_tag="g", component="c").to_session_row()
    for key in ("session_id", "gen_tag", "component", "started_at"):
        assert key in row  # produced by the method...
    src = (REPO_ROOT / "core" / "self_improving" / "train.py").read_text(encoding="utf-8")
    assert "_metrics_row.pop(_identity_key, None)" in src  # ...and stripped at merge


# ---------------------------------------------------------------------------
# 2. scheduler run log — one module
# ---------------------------------------------------------------------------


def test_scheduler_run_log_has_single_home() -> None:
    from core.observability.run_log import JobRunLog

    assert JobRunLog.__module__ == "core.observability.run_log"
    # The two pre-fold module paths remain gone (no shim grace).
    assert not (REPO_ROOT / "core" / "orchestration" / "run_log.py").exists()
    assert not (REPO_ROOT / "core" / "scheduler" / "run_log.py").exists()


def test_job_run_log_prune_honors_live_class_attrs(tmp_path: Path) -> None:
    """Pre-fold contract: tests/operators mutate MAX_BYTES/MAX_LINES on the
    instance after construction and prune must honor the live values."""
    from core.observability.run_log import JobRunLog

    job_log = JobRunLog(log_dir=tmp_path)
    job_log.MAX_BYTES = 100
    job_log.MAX_LINES = 3
    for i in range(20):
        job_log.append("j1", {"i": i, "padding": "x" * 50})
    assert len(job_log.get_runs("j1", limit=999)) == 3
    assert job_log.prune("j1") == 0


# ---------------------------------------------------------------------------
# 3. namespace collision resolved
# ---------------------------------------------------------------------------


def test_session_metrics_name_is_unique() -> None:
    from core.observability.session_metrics import SessionMetrics
    from core.orchestration.metrics import LatencyMetrics

    assert SessionMetrics is not LatencyMetrics
    import core.orchestration.metrics as orch_metrics

    assert not hasattr(orch_metrics, "SessionMetrics"), (
        "orchestration must not re-grow a SessionMetrics twin"
    )


# ---------------------------------------------------------------------------
# 4. logging switchboard
# ---------------------------------------------------------------------------


@pytest.fixture()
def _restore_root_handlers():
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])


def test_configure_logging_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _restore_root_handlers
) -> None:
    from core.observability import logging_config

    monkeypatch.setattr(logging_config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setitem(
        logging_config._MODE_SPECS,
        "mcp",
        (tmp_path / "logs" / "mcp.log", logging_config._FILE_FORMAT),
    )

    logging_config.configure_logging("mcp")
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == tmp_path / "logs" / "mcp.log"

    # re-configuring must not stack handlers (double-log guard)
    logging_config.configure_logging("mcp")
    assert len(logging.getLogger().handlers) == 2  # stream + file


def test_configure_logging_rejects_unknown_mode(_restore_root_handlers) -> None:
    from core.observability.logging_config import configure_logging

    with pytest.raises(ValueError, match="unknown logging mode"):
        configure_logging("bogus")


def test_every_entry_point_uses_switchboard() -> None:
    """No entry point regresses to ad-hoc basicConfig."""
    entry_points = {
        "core/cli/typer_serve.py": '"serve"',
        "core/mcp_server.py": '"mcp"',
        "core/agent/worker.py": '"worker"',
        "core/self_improving/campaign.py": '"campaign"',
    }
    for rel_path, mode_literal in entry_points.items():
        src = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert re.search(r"configure_logging\(\s*" + re.escape(mode_literal), src), (
            f"{rel_path} no longer routes through configure_logging({mode_literal})"
        )
