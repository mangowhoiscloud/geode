import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import ContractError
from plugins.crucible.runtime_forecast import forecast_runtime, load_runtime_pilot


def _pilot(rates: list[float], *, evaluator: str = "a" * 64) -> dict[str, object]:
    return {
        "schema": "crucible.runtime-pilot.v1",
        "accounting_method": "sum-finalized-simulation-elapsed.v1",
        "evaluator_sha256": evaluator,
        "harness_sha256": "b" * 64,
        "assay_config_sha256": "c" * 64,
        "agent_route": "agent-route",
        "user_route": "user-route",
        "blocks": [
            {
                "samples": [
                    {"outcome": "complete", "wall_seconds": rate - 1.0},
                    {"outcome": "complete", "wall_seconds": rate},
                ]
            }
            for rate in rates
        ],
    }


def _record(payload: dict[str, object]) -> tuple[str, dict[str, object]]:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def _forecast(
    *,
    matching_target_cycle_count: int = 0,
) -> dict:
    return forecast_runtime(
        (
            _record(_pilot([200.0] * 6)),
            _record(_pilot([400.0] * 6)),
        ),
        target_family_count=9,
        tasks_per_family=1,
        trials_per_task=3,
        matching_target_cycle_count=matching_target_cycle_count,
        simulations=1_000,
        seed=20260713,
        confidence=0.95,
        coverages=(0.95, 0.99),
        experiment_overhead_seconds=600.0,
        campaign_overhead_seconds=1_000.0,
    )


def test_forecast_separates_model_based_blocks_from_target_cycles() -> None:
    report = _forecast()

    assert report["schema"] == "crucible.runtime-forecast.v1"
    assert report["source_pilots"]["campaign_cluster_count"] == 2
    assert report["pilot"]["usable_block_count"] == 12
    assert report["design"]["paired_row_count"] == 54
    assert report["sampling"]["distribution_evaluation"] == "exact_multinomial"
    assert report["sampling"]["possible_composition_count"] == 4_004
    assert 10_800.0 <= report["target_cycle_row_wall_seconds"]["mean_seconds"] <= 21_600.0

    p95, p99 = report["model_based_block_plans"]
    assert p95["required_independent_blocks"] == 59
    assert 1.0 - 0.95**58 < 0.95 <= 1.0 - 0.95**59
    assert p95["additional_blocks"] == 47
    assert p95["optimistic_additional_full_cycles"] == 6
    assert p99["required_independent_blocks"] == 299
    assert 1.0 - 0.99**298 < 0.95 <= 1.0 - 0.99**299
    assert p99["additional_blocks"] == 287
    assert p99["optimistic_additional_full_cycles"] == 32

    cycle_p95, cycle_p99 = report["distribution_free_target_cycle_plans"]
    assert cycle_p95["required_independent_target_cycles"] == 59
    assert cycle_p95["additional_target_cycles"] == 59
    assert cycle_p99["required_independent_target_cycles"] == 299
    assert cycle_p99["additional_target_cycles"] == 299


def test_forecast_is_deterministic_and_counts_matching_target_cycles() -> None:
    first = _forecast(matching_target_cycle_count=2)
    second = _forecast(matching_target_cycle_count=2)

    assert first == second
    p95, p99 = first["distribution_free_target_cycle_plans"]
    assert p95["additional_target_cycles"] == 57
    assert p99["additional_target_cycles"] == 297


def test_forecast_falls_back_to_deterministic_monte_carlo() -> None:
    report = forecast_runtime(
        (_record(_pilot([float(value) for value in range(2, 22)])),),
        target_family_count=9,
        tasks_per_family=1,
        trials_per_task=3,
        matching_target_cycle_count=0,
        simulations=1_000,
        seed=20260713,
        confidence=0.95,
        coverages=(0.95, 0.99),
        experiment_overhead_seconds=0.0,
        campaign_overhead_seconds=0.0,
    )

    assert report["sampling"]["distribution_evaluation"] == "deterministic_monte_carlo"
    assert report["sampling"]["possible_composition_count"] > 200_000
    assert report["sampling"]["evaluated_draw_count"] == 1_000


def test_forecast_rejects_duplicate_or_mismatched_pilots() -> None:
    first = _record(_pilot([100.0] * 6))
    with pytest.raises(ContractError, match="duplicate pilot digests"):
        forecast_runtime(
            (first, first),
            target_family_count=9,
            tasks_per_family=1,
            trials_per_task=3,
            matching_target_cycle_count=0,
            simulations=1_000,
            seed=1,
            confidence=0.95,
            coverages=(0.95, 0.99),
            experiment_overhead_seconds=0.0,
            campaign_overhead_seconds=0.0,
        )

    changed = deepcopy(_pilot([200.0] * 6))
    changed["evaluator_sha256"] = "d" * 64
    with pytest.raises(ContractError, match="bindings differ: evaluator_sha256"):
        forecast_runtime(
            (first, _record(changed)),
            target_family_count=9,
            tasks_per_family=1,
            trials_per_task=3,
            matching_target_cycle_count=0,
            simulations=1_000,
            seed=1,
            confidence=0.95,
            coverages=(0.95, 0.99),
            experiment_overhead_seconds=0.0,
            campaign_overhead_seconds=0.0,
        )


def test_runtime_forecast_cli_writes_the_digest_bound_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pilot_paths: list[Path] = []
    for index, rates in enumerate(([200.0] * 6, [400.0] * 6), start=1):
        path = tmp_path / f"pilot-{index}.json"
        path.write_text(json.dumps(_pilot(rates)), encoding="utf-8")
        pilot_paths.append(path)
    output = tmp_path / "forecast.json"

    code = crucible_main(
        [
            "runtime-forecast",
            "--pilot",
            str(pilot_paths[0]),
            "--pilot",
            str(pilot_paths[1]),
            "--target-family-count",
            "9",
            "--trials-per-task",
            "3",
            "--matching-target-cycle-count",
            "0",
            "--simulations",
            "1000",
            "--seed",
            "20260713",
            "--experiment-overhead-seconds",
            "600",
            "--campaign-overhead-seconds",
            "1000",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert printed == saved
    assert saved["runtime_forecast_id"]
    assert saved["source_pilots"]["sha256"] == sorted(
        hashlib.sha256(path.read_bytes()).hexdigest() for path in pilot_paths
    )


def test_runtime_pilot_loader_rejects_a_symlink(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot.json"
    pilot.write_text(json.dumps(_pilot([100.0])), encoding="utf-8")
    link = tmp_path / "pilot-link.json"
    link.symlink_to(pilot)

    with pytest.raises(ContractError, match="must be a regular file"):
        load_runtime_pilot(link)
