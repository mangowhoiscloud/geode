"""DSPy optimize wrapper — M1 / M2 / M3 / M10 gate tests.

The live path (DSPy lazy import) is exercised via monkeypatch — no
real ``dspy`` install needed for the test suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from plugins.petri_audit.optimize import (
    DEFAULT_COMPILE_USD_CAP,
    PER_COMPILE_USD_ESTIMATE,
    OptimizeError,
    OptimizeReport,
    compile_id_for,
    optimize_prompt,
)

# ---------------------------------------------------------------------------
# M1 — judge ≠ generator family
# ---------------------------------------------------------------------------


def test_optimize_rejects_same_family(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    with pytest.raises(OptimizeError, match="M1 violation"):
        optimize_prompt(
            judge="claude-haiku-4-5-20251001",
            generator="claude-opus-4-7",  # both anthropic
            eval_log_path=log,
            output_dir=tmp_path,
        )


def test_optimize_rejects_unknown_family(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    with pytest.raises(OptimizeError, match="M1 family check needs"):
        optimize_prompt(
            judge="mystery-judge",
            generator="claude-opus-4-7",
            eval_log_path=log,
            output_dir=tmp_path,
        )


def test_optimize_accepts_cross_family(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    report = optimize_prompt(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        output_dir=tmp_path,
        dry_run=True,
    )
    assert isinstance(report, OptimizeReport)
    assert report.judge_family == "anthropic"
    assert report.generator_family == "openai"
    assert any("M1 ok" in n for n in report.notes)


# ---------------------------------------------------------------------------
# M3 — budget gate
# ---------------------------------------------------------------------------


def test_optimize_rejects_zero_budget(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    with pytest.raises(OptimizeError, match="max_compile_usd must be > 0"):
        optimize_prompt(
            judge="claude-haiku-4-5-20251001",
            generator="gpt-5.4",
            eval_log_path=log,
            output_dir=tmp_path,
            max_compile_usd=0.0,
        )


def test_optimize_rejects_below_floor(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    with pytest.raises(OptimizeError, match="M3 budget too low"):
        optimize_prompt(
            judge="claude-haiku-4-5-20251001",
            generator="gpt-5.4",
            eval_log_path=log,
            output_dir=tmp_path,
            max_compile_usd=PER_COMPILE_USD_ESTIMATE - 1.0,
        )


# ---------------------------------------------------------------------------
# M10 — compile_id deterministic
# ---------------------------------------------------------------------------


def test_compile_id_changes_with_inputs(tmp_path: Path) -> None:
    log = tmp_path / "a.eval"
    log.write_bytes(b"hello")
    a = compile_id_for(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        seed=42,
    )
    b = compile_id_for(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        seed=43,  # different seed
    )
    assert a != b
    # And both have the YYYYMMDDTHHMMSSZ-<10 hex> shape.
    for cid in (a, b):
        ts, _, suffix = cid.partition("-")
        assert ts.endswith("Z") and len(ts) == 16
        assert len(suffix) == 10


# ---------------------------------------------------------------------------
# Dry-run path — no DSPy import, no file write
# ---------------------------------------------------------------------------


def test_dry_run_returns_plan_without_dspy(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    report = optimize_prompt(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        output_dir=tmp_path,
        dry_run=True,
    )
    assert report.dry_run is True
    assert report.aborted is False
    assert "PR-only" in report.next_step
    assert "M2" in report.next_step
    # Output file is NOT yet created on dry-run.
    assert not report.output_path.exists()
    assert report.estimated_usd == PER_COMPILE_USD_ESTIMATE


def test_dry_run_default_cap(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    report = optimize_prompt(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        output_dir=tmp_path,
    )
    assert report.estimated_usd_cap == DEFAULT_COMPILE_USD_CAP


# ---------------------------------------------------------------------------
# Live path — mocked DSPy import
# ---------------------------------------------------------------------------


def test_live_missing_eval_log_raises(tmp_path: Path) -> None:
    with pytest.raises(OptimizeError, match="eval log not found"):
        optimize_prompt(
            judge="claude-haiku-4-5-20251001",
            generator="gpt-5.4",
            eval_log_path=tmp_path / "missing.eval",
            output_dir=tmp_path,
            dry_run=False,
        )


def test_live_without_reason_extra_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"data")
    monkeypatch.setitem(sys.modules, "dspy", None)
    with pytest.raises(OptimizeError, match=r"\[reason\] extra"):
        optimize_prompt(
            judge="claude-haiku-4-5-20251001",
            generator="gpt-5.4",
            eval_log_path=log,
            output_dir=tmp_path,
            dry_run=False,
        )


def test_live_writes_artefact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"sample-data")
    fake_dspy = SimpleNamespace(__version__="3.1.2")
    monkeypatch.setitem(sys.modules, "dspy", fake_dspy)

    report = optimize_prompt(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        output_dir=tmp_path / "out",
        dry_run=False,
    )

    assert report.dry_run is False
    assert report.aborted is False
    assert report.output_path.exists()
    payload = json.loads(report.output_path.read_text())
    assert payload["compile_id"] == report.compile_id
    assert payload["judge_family"] == "anthropic"
    assert payload["generator_family"] == "openai"
    assert payload["dspy_version"] == "3.1.2"
    assert payload["seed"] == 42


# ---------------------------------------------------------------------------
# Report serialisation
# ---------------------------------------------------------------------------


def test_report_to_dict_round_trip(tmp_path: Path) -> None:
    log = tmp_path / "fake.eval"
    log.write_bytes(b"")
    report = optimize_prompt(
        judge="claude-haiku-4-5-20251001",
        generator="gpt-5.4",
        eval_log_path=log,
        output_dir=tmp_path,
    )
    d = report.to_dict()
    expected_keys = {
        "compile_id",
        "judge",
        "generator",
        "judge_family",
        "generator_family",
        "output_path",
        "estimated_usd",
        "estimated_usd_cap",
        "dry_run",
        "aborted",
        "next_step",
        "notes",
    }
    assert set(d.keys()) == expected_keys
