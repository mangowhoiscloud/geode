"""Smoke tests for the Petri-signal autoresearch fork.

These cover the surface that ruff/mypy/dry-run already exercise *and* the
real-mode plumbing (subprocess argv + env override path) that the dry-run
can never reach. The point is to make sure the next time someone tweaks
``geode audit`` CLI flags, flips ``WRAPPER_OVERRIDE_HOOK_READY`` back to
``False``, or drops the wrapper-override env handoff, this catches the
regression cheaply without touching real LLM quota.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from autoresearch import train as auto_train
from autoresearch.train import (
    WRAPPER_OVERRIDE_HOOK_READY,
    _build_audit_command,
    compute_fitness,
    run_audit,
)


def test_build_audit_command_uses_current_geode_audit_flags() -> None:
    """argv must match what ``geode audit --help`` accepts today."""
    argv = _build_audit_command()
    # Required current flags
    for flag in ("--seed-select", "--dim-set", "--live", "--yes", "--target", "--judge"):
        assert flag in argv, f"missing required flag {flag} in {argv}"
    # Obsolete flags that an older draft of this scaffold used — must not
    # silently re-appear.
    for stale in ("--rubric", "--budget-minutes"):
        assert stale not in argv, f"obsolete flag {stale} re-introduced in {argv}"


def test_wrapper_override_hook_ready_is_true() -> None:
    """Real-mode is gated by this flag. Flipping it back to ``False`` without
    a corresponding GEODE core regression would re-deceive the outer loop."""
    assert WRAPPER_OVERRIDE_HOOK_READY is True


def test_real_mode_invokes_subprocess_with_override_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real mode must (a) build argv, (b) export ``GEODE_WRAPPER_OVERRIDE``
    pointing at a JSON dump of ``WRAPPER_PROMPT_SECTIONS``, and (c) parse
    the audit's summary JSON. We mock the subprocess so this stays free."""
    # Redirect state dir to a tmp path so we don't pollute the worktree.
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "AUDIT_OUT_DIR", tmp_path / "state" / "audit_logs")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")

    captured: dict[str, Any] = {}

    def _fake_run(argv: list[str], **kwargs: Any) -> MagicMock:
        captured["argv"] = argv
        captured["env"] = kwargs.get("env", {})
        result = MagicMock()
        result.returncode = 0
        result.stdout = (
            "audit complete\n"
            + json.dumps(
                {
                    "dim_means": {
                        "broken_tool_use": 2.5,
                        "input_hallucination": 2.0,
                        "overrefusal": 1.2,
                        "eval_awareness": 1.0,
                        "unprompted_sycophancy": 1.0,
                    }
                }
            )
            + "\n"
        )
        result.stderr = ""
        return result

    monkeypatch.setattr(auto_train.subprocess, "run", _fake_run)

    dim_means, dim_stderr, audit_seconds, total_seconds = run_audit(dry_run=False)

    # argv contains the current flag set
    assert "--seed-select" in captured["argv"]
    assert "--live" in captured["argv"]
    # Env exports the override path, and the file actually contains the dict
    override_path = captured["env"]["GEODE_WRAPPER_OVERRIDE"]
    payload = json.loads(Path(override_path).read_text(encoding="utf-8"))
    assert set(payload.keys()) == set(auto_train.WRAPPER_PROMPT_SECTIONS.keys())
    # Dim means came from the mocked stdout
    assert dim_means["input_hallucination"] == 2.0
    # ``dim_stderr`` is optional in the schema — older CLI builds omit it.
    # When absent the parser must default to an empty dict (G3 fallback).
    assert dim_stderr == {}
    assert audit_seconds >= 0.0
    assert total_seconds >= audit_seconds


def test_real_mode_parses_dim_stderr_when_emitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the CLI emits ``dim_stderr`` alongside ``dim_means`` the
    parser must thread it through to ``run_audit``'s return tuple so
    the stability axis can replace its placeholder."""
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "AUDIT_OUT_DIR", tmp_path / "state" / "audit_logs")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")

    def _fake_run(argv: list[str], **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = (
            "audit complete\n"
            + json.dumps(
                {
                    "dim_means": {
                        "broken_tool_use": 2.5,
                        "input_hallucination": 2.0,
                        "overrefusal": 1.2,
                        "eval_awareness": 1.0,
                        "unprompted_sycophancy": 1.0,
                    },
                    "dim_stderr": {
                        "broken_tool_use": 0.4,
                        "input_hallucination": 0.5,
                        "overrefusal": 0.1,
                        "eval_awareness": 0.0,
                        "unprompted_sycophancy": 0.0,
                    },
                }
            )
            + "\n"
        )
        result.stderr = ""
        return result

    monkeypatch.setattr(auto_train.subprocess, "run", _fake_run)

    dim_means, dim_stderr, _aud, _tot = run_audit(dry_run=False)

    assert dim_means["input_hallucination"] == 2.0
    assert dim_stderr["input_hallucination"] == pytest.approx(0.5)
    assert set(dim_stderr.keys()) == set(dim_means.keys())


def test_real_mode_raises_when_summary_json_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the audit subprocess does not emit the trailing summary JSON,
    ``run_audit`` must fail loudly instead of silently zeroing fitness."""
    monkeypatch.setattr(auto_train, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(auto_train, "AUDIT_OUT_DIR", tmp_path / "state" / "audit_logs")
    monkeypatch.setattr(auto_train, "RUN_LOG", tmp_path / "state" / "run.log")

    def _fake_run(argv: list[str], **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "audit complete but no JSON\n"
        result.stderr = ""
        return result

    monkeypatch.setattr(auto_train.subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="summary JSON"):
        run_audit(dry_run=False)


def test_dry_run_emits_baseline_dim_means_and_finite_fitness() -> None:
    """The dry-run path stays cheap-and-deterministic for plumbing tests.

    dry-run returns an empty ``dim_stderr`` so the stability axis falls
    back to ``STABILITY_FALLBACK`` (the pre-G3 0.5 placeholder). Without
    that fallback the baseline fitness would drift every time the
    stderr aggregate formula changes — breaking the program.md
    "baseline = 0.535895" contract for plumbing checks.
    """
    dim_means, dim_stderr, audit_seconds, _ = run_audit(dry_run=True)
    assert dim_means["input_hallucination"] == pytest.approx(3.7)
    assert dim_means["broken_tool_use"] == pytest.approx(3.4)
    assert dim_means["overrefusal"] == pytest.approx(1.0)
    assert dim_stderr == {}
    assert audit_seconds == 0.0
    fitness = compute_fitness(dim_means, dim_stderr)
    assert 0.0 < fitness < 1.0
    # The dry-run baseline is the program.md reference number — it must
    # stay deterministic across G3 changes (stderr fallback applies).
    assert fitness == pytest.approx(0.535895, abs=1e-4)


def test_stability_axis_uses_stderr_when_present() -> None:
    """G3 — real-mode stability replaces the 0.5 placeholder with
    ``1 / (1 + mean_stderr)``. With ``stderr = 1.0`` the axis collapses
    to exactly 0.5 (bounded reproduction of the placeholder), and
    ``stderr = 0.0`` saturates to 1.0 (no observable noise → maximum
    stability)."""
    dim_means = {
        "broken_tool_use": 3.4,
        "input_hallucination": 3.7,
        "overrefusal": 1.0,
        "eval_awareness": 1.0,
        "unprompted_sycophancy": 1.0,
    }
    # stderr=1.0 across the board → stability axis = 1/(1+1) = 0.5
    noisy_stderr = dict.fromkeys(dim_means, 1.0)
    assert auto_train._axis_score("stability", dim_means, noisy_stderr) == pytest.approx(0.5)
    # stderr=0.0 → stability saturates at 1.0
    perfect_stderr = dict.fromkeys(dim_means, 0.0)
    assert auto_train._axis_score("stability", dim_means, perfect_stderr) == pytest.approx(1.0)
    # empty stderr → fallback to STABILITY_FALLBACK constant
    assert auto_train._axis_score("stability", dim_means, {}) == auto_train.STABILITY_FALLBACK
    assert auto_train._axis_score("stability", dim_means, None) == auto_train.STABILITY_FALLBACK


def test_compute_fitness_accepts_optional_stderr() -> None:
    """``compute_fitness`` must remain backward-compatible — callers
    that pre-date G3 pass only ``dim_means`` and get the placeholder
    stability axis. PR 3's cross-axis gate adds a third ``baseline``
    parameter on the same signature; with ``baseline=None`` the
    behaviour is the simple weighted sum."""
    dim_means = {
        "broken_tool_use": 3.4,
        "input_hallucination": 3.7,
        "overrefusal": 1.0,
        "eval_awareness": 1.0,
        "unprompted_sycophancy": 1.0,
    }
    fitness_no_stderr = compute_fitness(dim_means)
    fitness_empty_stderr = compute_fitness(dim_means, {})
    fitness_baseline_none = compute_fitness(dim_means, {}, baseline=None)
    assert fitness_no_stderr == pytest.approx(fitness_empty_stderr)
    assert fitness_no_stderr == pytest.approx(fitness_baseline_none)


def test_compute_axis_scores_returns_five_axes() -> None:
    """The helper must expose every axis listed in ``FITNESS_WEIGHTS``
    so callers can build a :class:`FitnessBaseline` from a finished
    audit's aggregates."""
    dim_means = {
        "broken_tool_use": 3.4,
        "input_hallucination": 3.7,
        "overrefusal": 1.0,
        "eval_awareness": 1.0,
        "unprompted_sycophancy": 1.0,
    }
    scores = auto_train.compute_axis_scores(dim_means, {})
    assert set(scores.keys()) == {
        "predictive",
        "robustness",
        "logic",
        "diversity",
        "stability",
    }
    # broken_tool_use=3.4 → predictive = 1/3.4 = 0.2941...
    assert scores["predictive"] == pytest.approx(1.0 / 3.4)


def _good_dim_means() -> dict[str, float]:
    """A reasonable baseline-flavoured dim mean dict — every axis lives
    in a 'middle' range so regressions / improvements are easy to
    construct relative to it."""
    return {
        "broken_tool_use": 3.0,
        "input_hallucination": 3.0,
        "overrefusal": 1.0,
        "eval_awareness": 1.0,
        "unprompted_sycophancy": 1.0,
    }


def test_cross_axis_gate_dormant_when_baseline_none() -> None:
    """First run / fresh branch has no baseline → the gate stays
    dormant and ``compute_fitness`` returns the plain weighted sum."""
    dm = _good_dim_means()
    plain = compute_fitness(dm, {})
    gated = compute_fitness(dm, {}, baseline=None)
    assert gated == pytest.approx(plain)


def test_cross_axis_gate_rejects_critical_regression() -> None:
    """G2 — a hypothesis that regresses ``predictive`` below
    ``baseline - axis_stderr`` collapses fitness to 0.0 even when the
    weighted sum otherwise improves. The rest of the aggregate is
    irrelevant once the strict gate fires."""
    baseline_dm = _good_dim_means()
    baseline = auto_train.FitnessBaseline.from_audit(baseline_dm, {})

    # Construct a new audit where predictive (broken_tool_use) is much
    # worse but the other axes improve. Without the gate the weighted
    # sum would still go up; the gate must reject anyway.
    regressed = {
        **baseline_dm,
        "broken_tool_use": 9.0,  # was 3.0 → score collapses from 0.33 → 0.11
    }
    fitness = compute_fitness(regressed, {}, baseline=baseline)
    assert fitness == 0.0


def test_cross_axis_gate_rejects_robustness_regression() -> None:
    """Robustness is also a critical axis — same strict rule."""
    baseline_dm = _good_dim_means()
    baseline = auto_train.FitnessBaseline.from_audit(baseline_dm, {})

    regressed = {
        **baseline_dm,
        "input_hallucination": 9.0,  # robustness halves
    }
    fitness = compute_fitness(regressed, {}, baseline=baseline)
    assert fitness == 0.0


def test_cross_axis_gate_soft_penalty_on_auxiliary_regression() -> None:
    """G2 — auxiliary-axis (logic / diversity / stability) regression
    is absorbed as a squared penalty rather than rejection. Small
    movements stay roughly free; large movements bite."""
    baseline_dm = _good_dim_means()
    baseline = auto_train.FitnessBaseline.from_audit(baseline_dm, {})

    # eval_awareness ↑ from 1.0 → 6.0 → logic axis score drops from
    # 0.9 → 0.4 (delta = 0.5).
    regressed = {**baseline_dm, "eval_awareness": 6.0}
    fitness_with_gate = compute_fitness(regressed, {}, baseline=baseline)
    fitness_plain = compute_fitness(regressed, {})

    # Critical axes untouched → strict gate does not fire.
    assert fitness_with_gate > 0.0
    # But the soft penalty bites — gated < plain.
    assert fitness_with_gate < fitness_plain
    # Penalty magnitude: λ × delta² with λ=0.5, delta=0.5 → 0.125.
    assert fitness_with_gate == pytest.approx(fitness_plain - 0.125, abs=1e-4)


def test_cross_axis_gate_no_penalty_on_monotone_improvement() -> None:
    """When every axis improves or stays equal the gate must not
    deduct anything — fitness is exactly the new weighted sum."""
    baseline_dm = _good_dim_means()
    baseline = auto_train.FitnessBaseline.from_audit(baseline_dm, {})

    # broken_tool_use ↓ → predictive ↑ (critical, improves).
    # input_hallucination ↓ → robustness ↑ (critical, improves).
    # Everything else stays the same.
    improved = {
        **baseline_dm,
        "broken_tool_use": 2.0,
        "input_hallucination": 2.0,
    }
    fitness_with_gate = compute_fitness(improved, {}, baseline=baseline)
    fitness_plain = compute_fitness(improved, {})
    assert fitness_with_gate == pytest.approx(fitness_plain)


def test_baseline_from_summary_parses_payload() -> None:
    """``baseline.json`` round-trip — the agent writes axes + axes_stderr
    after a promote and the next run reads them back into a
    :class:`FitnessBaseline`."""
    payload = {
        "axes": {
            "predictive": 0.33,
            "robustness": 0.33,
            "logic": 0.9,
            "diversity": 0.9,
            "stability": 0.5,
        },
        "axes_stderr": {
            "predictive": 0.05,
            "robustness": 0.05,
            "logic": 0.0,
            "diversity": 0.0,
            "stability": 0.0,
        },
    }
    baseline = auto_train.baseline_from_summary(payload)
    assert baseline is not None
    assert baseline.axes["predictive"] == pytest.approx(0.33)
    assert baseline.axes_stderr["predictive"] == pytest.approx(0.05)
    # Empty / malformed inputs return None so callers don't have to
    # special-case the dormant branch.
    assert auto_train.baseline_from_summary({}) is None
    assert auto_train.baseline_from_summary({"axes": {}}) is None
    assert auto_train.baseline_from_summary({"unrelated": 1}) is None
