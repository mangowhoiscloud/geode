"""scripts/refresh_published_state.py rebuilds the published snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evolve.crucible.publication import CRUCIBLE_ATTEMPTS_NAME
from evolve.scaffold_search.publication import (
    CAMPAIGN_PROGRESS_NAME,
    GEN0_FITNESS_STDERR_NAME,
    PUBLISHED_BASELINE_NAME,
    parse_campaign_progress_log,
)
from scripts import refresh_published_state as refresh

_LOG = (
    "2026-05-31T06:00:00Z campaign start: n=1 k=1 arms=['gate'] dry_run=False\n"
    "2026-05-31T06:01:00Z gen-0 baseline repeat 1/1: held_out=0.8 fitness=0.6 source=m\n"
    "2026-05-31T06:02:00Z arm 'gate' cycle 1/1: fitness_after=0.7 fitness_delta=+0.0100 "
    "held_out=0.9 promote guard=ok (ok)\n"
)


def _runtime(root: Path) -> Path:
    root.mkdir()
    (root / "baseline.json").write_text(
        json.dumps({"ts_utc": "2026-06-01T00:00:00Z", "raw": {"eval_archive": "/Users/a/x.eval"}}),
        encoding="utf-8",
    )
    (root / "campaign-progress.log").write_text(_LOG, encoding="utf-8")
    snapshot = root / refresh.GEN0_SNAPSHOT_BASELINE
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"ts_utc": "t", "raw": {"fitness_stderr": 0.02}}', encoding="utf-8")
    return root


def test_refresh_rebuilds_every_snapshot_from_runtime_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = _runtime(tmp_path / "runtime")
    ledger = tmp_path / "campaigns" / "c1" / "state" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"kind": "train_attempt", "outcome": "KEEP", "usage": {"tokens": 5}}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "published"
    argv = ["--runtime-dir", str(runtime), "--crucible-campaigns-dir", str(tmp_path / "campaigns")]

    assert refresh.main([*argv, "--out", str(out)]) == 0
    assert "written" in capsys.readouterr().out
    assert refresh.main([*argv, "--out", str(out)]) == 0
    assert "written" not in capsys.readouterr().out

    baseline = json.loads((out / PUBLISHED_BASELINE_NAME).read_text(encoding="utf-8"))
    assert baseline["baseline"]["raw"]["eval_archive"] == "x.eval"
    progress = json.loads((out / CAMPAIGN_PROGRESS_NAME).read_text(encoding="utf-8"))
    assert progress == parse_campaign_progress_log(_LOG)
    gen0 = json.loads((out / GEN0_FITNESS_STDERR_NAME).read_text(encoding="utf-8"))
    assert gen0["fitness_stderr"] == 0.02
    attempts = (out / CRUCIBLE_ATTEMPTS_NAME).read_text(encoding="utf-8").splitlines()
    assert [json.loads(row)["campaign_id"] for row in attempts] == ["c1"]


def test_missing_sources_are_reported_and_leave_published_files_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    out = tmp_path / "published"
    out.mkdir()
    (out / PUBLISHED_BASELINE_NAME).write_text("previous\n", encoding="utf-8")

    code = refresh.main(
        [
            "--runtime-dir",
            str(runtime),
            "--crucible-campaigns-dir",
            str(tmp_path / "absent"),
            "--out",
            str(out),
        ]
    )

    assert code == 0
    report = capsys.readouterr().out
    assert report.count("missing source") == 4
    assert sorted(p.name for p in out.iterdir()) == [PUBLISHED_BASELINE_NAME]
    assert (out / PUBLISHED_BASELINE_NAME).read_text(encoding="utf-8") == "previous\n"


def test_malformed_runtime_source_fails_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "baseline.json").write_text("{not json", encoding="utf-8")
    out = tmp_path / "published"

    code = refresh.main(["--runtime-dir", str(runtime), "--out", str(out)])

    assert code == 2
    assert "unreadable JSON" in capsys.readouterr().err
    assert not out.exists()
