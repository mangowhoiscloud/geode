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
