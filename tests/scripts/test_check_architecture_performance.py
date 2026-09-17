"""Tests for the independent architecture performance ratchet."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import check_architecture_performance as checker

EXPECTED_METRICS = {
    "event_persist_us",
    "first_turn_ms",
    "import_cold_start_ms",
    "mcp_first_call_ms",
    "mcp_warm_call_ms",
    "runtime_create_shutdown_ms",
    "runtime_peak_kib",
    "tool_descriptor_bytes",
    "tool_dispatch_us",
    "tool_plan_build_ms",
    "tool_plan_peak_kib",
    "tool_plan_refresh_ms",
    "tool_registry_entries",
}


def _write_baseline(path: Path, *, maximum: float = 10.0) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metrics": {
                    "probe_ms": {
                        "unit": "ms",
                        "observed": 2.0,
                        "maximum": maximum,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_load_baseline_validates_the_committed_schema(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)

    assert checker.load_baseline(baseline) == {
        "probe_ms": {"unit": "ms", "observed": 2.0, "maximum": 10.0}
    }


def test_committed_baseline_covers_every_r7_3_metric() -> None:
    baseline = checker.load_baseline()

    assert set(baseline) == EXPECTED_METRICS


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2, "metrics": {}},
        {"schema_version": 1, "metrics": {}},
        {
            "schema_version": 1,
            "metrics": {"probe": {"unit": "ms", "observed": 11, "maximum": 10}},
        },
    ],
)
def test_load_baseline_rejects_invalid_or_self_exceeding_rows(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(mutation), encoding="utf-8")

    with pytest.raises(checker.PerformanceBaselineError):
        checker.load_baseline(baseline)


def test_compare_measurements_fails_each_metric_independently() -> None:
    baseline = {
        "fast": {"unit": "ms", "observed": 1.0, "maximum": 2.0},
        "slow": {"unit": "ms", "observed": 1.0, "maximum": 2.0},
    }

    errors = checker.compare_measurements({"fast": 0.1, "slow": 2.1}, baseline)

    assert errors == ["slow: 2.100 ms exceeds 2.000 ms"]


def test_compare_measurements_rejects_metric_set_drift() -> None:
    baseline = {"expected": {"unit": "ms", "observed": 1.0, "maximum": 2.0}}

    errors = checker.compare_measurements({"unexpected": 1.0}, baseline)

    assert errors == ["missing metrics: expected", "unexpected metrics: unexpected"]


def test_probe_mode_rejects_direct_unisolated_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("_GEODE_ARCHITECTURE_PERFORMANCE_PROBE", raising=False)

    assert checker.main(["--probe"]) == 2


def test_collect_preserves_raw_samples_and_median(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    values = iter([70.125, 470.54, 169.573])

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"first_turn_ms": next(values)}), stderr=""
        )

    monkeypatch.setattr(checker.subprocess, "run", run_probe)

    assert checker.collect_measurements() == {"first_turn_ms": 169.573}
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        'performance sample 1/3: {"first_turn_ms": 70.125}',
        'performance sample 2/3: {"first_turn_ms": 470.54}',
        'performance sample 3/3: {"first_turn_ms": 169.573}',
    ]


@pytest.mark.parametrize("returncode", [0, 2])
def test_collect_preserves_bounded_redacted_stderr_without_masking_child_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], returncode: int
) -> None:
    secret = "sk-" + "x" * 24

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["probe"],
            returncode=returncode,
            stdout='{"first_turn_ms": 1.0}',
            stderr=f"warning: {secret}\n" + "x" * 5000,
        )

    monkeypatch.setattr(checker.subprocess, "run", run_probe)

    if returncode:
        with pytest.raises(subprocess.CalledProcessError):
            checker.collect_measurements(samples=1)
    else:
        assert checker.collect_measurements(samples=1) == {"first_turn_ms": 1.0}
    output = capsys.readouterr()
    assert secret not in output.err
    assert "[REDACTED]" in output.err
    assert "[truncated:" in output.err
    assert len(output.err) < 4200
    assert len(output.err.splitlines()) == 1
    assert bool(output.out) is (returncode == 0)


def test_check_still_fails_over_budget_with_raw_evidence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"probe_ms": 11.0}', stderr=""
        )

    monkeypatch.setattr(checker.subprocess, "run", run_probe)

    assert checker.main(["--check", "--baseline", str(baseline)]) == 1
    output = capsys.readouterr()
    assert 'performance sample 3/3: {"probe_ms": 11.0}' in output.out
    assert "probe_ms: 11.000 ms exceeds 10.000 ms" in output.err
    assert "architecture performance OK" not in output.out


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), 0, -1, True, "1", None]
)
@pytest.mark.parametrize("field", ["observed", "maximum"])
def test_baseline_rejects_non_finite_or_non_positive_values(
    tmp_path: Path, field: str, value: object
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    data = json.loads(path.read_text())
    data["metrics"]["probe_ms"][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(checker.PerformanceBaselineError, match="positive finite"):
        checker.load_baseline(path)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_baseline_requires_integer_schema_identity(tmp_path: Path, version: object) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    data = json.loads(path.read_text())
    data["schema_version"] = version
    path.write_text(json.dumps(data))
    with pytest.raises(checker.PerformanceBaselineError, match="schema_version"):
        checker.load_baseline(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 0, -1, True])
def test_compare_rejects_invalid_measurements(value: float) -> None:
    baseline = {"probe_ms": {"unit": "ms", "observed": 1.0, "maximum": 2.0}}
    errors = checker.compare_measurements({"probe_ms": value}, baseline)
    assert errors == ["probe_ms must be a positive finite number"]


@pytest.mark.parametrize("row", [{"probe_ms": float("nan")}, {"probe_ms": -1}, {}, [], None])
def test_invalid_sample_cannot_be_hidden_by_a_passing_median(
    monkeypatch: pytest.MonkeyPatch,
    row: object,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)
    samples = iter([{"probe_ms": 1.0}, row, {"probe_ms": 1.0}])

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(next(samples)), "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    assert checker.main(["--check", "--baseline", str(path)]) == 1
    output = capsys.readouterr()
    assert "architecture performance OK" not in output.out
    assert "architecture performance check failed" in output.err


def test_check_reports_unexpected_metric_without_rendering_key_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "baseline.json"
    _write_baseline(path)

    def run_probe(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, '{"unexpected_ms": 1.0}', "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    assert checker.main(["--check", "--baseline", str(path)]) == 1
    output = capsys.readouterr()
    assert "missing metrics: probe_ms" in output.err
    assert "unexpected metrics: unexpected_ms" in output.err
    assert "architecture performance OK" not in output.out


@pytest.mark.parametrize("diagnostic", [False, True])
def test_profile_flag_is_only_used_for_unscored_diagnostics(
    monkeypatch: pytest.MonkeyPatch, diagnostic: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    commands: list[list[str]] = []

    def run_probe(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"first_turn_ms": 1.0}', "")

    monkeypatch.setattr(checker.subprocess, "run", run_probe)
    checker.collect_measurements(samples=1, diagnostic=diagnostic)
    assert ("--profile-first-turn" in commands[0]) is diagnostic
    assert capsys.readouterr().out.startswith("diagnostic" if diagnostic else "performance")


def test_diagnose_never_reports_acceptance_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[dict[str, object]] = []

    def collect(**kwargs: Any) -> dict[str, float]:
        seen.append(kwargs)
        return {"first_turn_ms": 9999.0}

    monkeypatch.setattr(checker, "collect_measurements", collect)
    assert checker.main(["--diagnose"]) == 0
    assert seen == [{"samples": 1, "diagnostic": True}]
    output = capsys.readouterr().out
    assert "Diagnostic only" in output
    assert "architecture performance OK" not in output
