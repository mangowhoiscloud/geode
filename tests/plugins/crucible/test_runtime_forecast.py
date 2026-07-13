import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import (
    ContractError,
    ExperimentContract,
    TaskUnit,
    task_pack_sha256,
)
from plugins.crucible.runtime_forecast import forecast_runtime, load_runtime_pilot
from plugins.crucible.runtime_identity import runtime_regime, runtime_regime_id

from tests.plugins.crucible.test_promotion import _contract


def _target_contract() -> ExperimentContract:
    base = _contract(stage="train").to_dict()
    base.pop("contract_id")
    tasks = tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}") for index in range(1, 10)
    )
    base.update(
        {
            "evaluator_sha256": "a" * 64,
            "harness_sha256": "b" * 64,
            "agent_route": "agent-route",
            "user_route": "user-route",
            "tasks": [task.to_dict() for task in tasks],
            "trials_per_task": 3,
            "task_pack_sha256": task_pack_sha256(tasks, 3),
            "assay_config": {"schema": "fixture.v1", "timeout": None},
        }
    )
    return ExperimentContract.from_mapping(base)


def _contract_with_wall(contract: ExperimentContract, wall_seconds: float) -> ExperimentContract:
    payload = contract.to_dict()
    payload.pop("contract_id")
    payload["budget"] = {**payload["budget"], "max_wall_seconds": wall_seconds}
    return ExperimentContract.from_mapping(payload)


def _pilot(
    rates: list[float],
    *,
    contract: ExperimentContract | None = None,
    evaluator: str | None = None,
    matching_cycle: bool = False,
    source_contract_id: str | None = None,
) -> dict[str, object]:
    target = contract or _target_contract()
    payload: dict[str, object] = {
        "schema": "crucible.runtime-pilot.v2" if matching_cycle else "crucible.runtime-pilot.v1",
        "accounting_method": "sum-finalized-simulation-elapsed.v1",
        "evaluator_sha256": evaluator or target.evaluator_sha256,
        "harness_sha256": target.harness_sha256,
        "assay_config_sha256": target.assay_config_sha256,
        "agent_route": target.agent_route,
        "user_route": target.user_route,
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
    if matching_cycle:
        observed = sum(rate * 2.0 - 1.0 for rate in rates)
        payload.update(
            {
                "source_contract_id": source_contract_id or target.contract_id,
                "source_runtime_receipt_id": "f" * 64,
                "runtime_regime": runtime_regime(target),
                "runtime_regime_id": runtime_regime_id(target),
                "cycle_observation": {
                    "status": "complete",
                    "observed_active_wall_seconds": observed,
                    "observed_evaluator_wall_seconds": observed,
                    "active_wall_seconds": observed,
                    "completed_evaluator_wall_seconds": observed,
                    "complete_sample_count": len(rates) * 2,
                    "right_censored_sample_count": 0,
                    "infrastructure_failure_sample_count": 0,
                },
            }
        )
    return payload


def _record(payload: dict[str, object]) -> tuple[str, dict[str, object]]:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def _forecast(
    *,
    matching_target_cycles: bool = False,
) -> dict:
    contract = _target_contract()
    return forecast_runtime(
        (
            _record(
                _pilot(
                    [200.0] * 6,
                    contract=contract,
                    matching_cycle=matching_target_cycles,
                    source_contract_id="d" * 64,
                )
            ),
            _record(
                _pilot(
                    [400.0] * 6,
                    contract=contract,
                    matching_cycle=matching_target_cycles,
                    source_contract_id="e" * 64,
                )
            ),
        ),
        target_contract=contract,
        simulations=1_000,
        seed=20260713,
        confidence=0.95,
        coverages=(0.95, 0.99),
        experiment_overhead_seconds=600.0,
        campaign_overhead_seconds=1_000.0,
    )


def test_forecast_uses_blocks_for_points_but_only_cycles_for_wilks() -> None:
    report = _forecast()

    assert report["schema"] == "crucible.runtime-forecast.v2"
    assert report["source_pilots"]["campaign_cluster_count"] == 2
    assert report["pilot"]["usable_block_count"] == 12
    assert report["design"]["paired_row_count"] == 54
    assert report["sampling"]["distribution_evaluation"] == "exact_multinomial"
    assert report["sampling"]["possible_composition_count"] == 4_004
    assert 10_800.0 <= report["model_based_target_cycle_active_seconds"]["mean_seconds"] <= 21_600.0
    p95_marker, p99_marker = report["model_based_planning_markers"]
    assert p95_marker["planning_only"] is True
    assert p95_marker["distribution_free"] is False
    assert p95_marker["confidence_bound"] is None
    assert p99_marker["class"] == "model_based_transferred_predictive_quantile"

    assert "model_based_block_plans" not in report

    cycle_p95, cycle_p99 = report["distribution_free_target_cycle_plans"]
    assert cycle_p95["required_independent_target_cycles"] == 59
    assert cycle_p95["additional_target_cycles"] == 59
    assert cycle_p95["confidence_qualified"] is False
    assert cycle_p95["evaluator_wall_upper_tolerance_bound_seconds"] is None
    assert 1.0 - 0.95**58 < 0.95 <= 1.0 - 0.95**59
    assert cycle_p99["required_independent_target_cycles"] == 299
    assert cycle_p99["additional_target_cycles"] == 299
    assert 1.0 - 0.99**298 < 0.95 <= 1.0 - 0.99**299


def test_forecast_is_deterministic_and_counts_matching_target_cycles() -> None:
    first = _forecast(matching_target_cycles=True)
    second = _forecast(matching_target_cycles=True)

    assert first == second
    p95, p99 = first["distribution_free_target_cycle_plans"]
    assert p95["additional_target_cycles"] == 57
    assert p99["additional_target_cycles"] == 297


def test_wilks_upper_bound_uses_only_the_max_of_59_matching_cycle_walls() -> None:
    target = _target_contract()
    pilots = tuple(
        _record(
            _pilot(
                [float(100 + index % 3)] * 6,
                contract=target,
                matching_cycle=True,
                source_contract_id=f"{index + 1:064x}",
            )
        )
        for index in range(59)
    )

    report = forecast_runtime(
        pilots,
        target_contract=target,
        simulations=1_000,
        seed=20260713,
        confidence=0.95,
        coverages=(0.95,),
        experiment_overhead_seconds=600.0,
        campaign_overhead_seconds=1_000.0,
    )

    plan = report["distribution_free_target_cycle_plans"][0]
    assert plan["confidence_qualified"] is True
    assert plan["observed_matching_target_cycles"] == 59
    assert plan["observed_sample_max_evaluator_wall_seconds"] == 1_218.0
    assert plan["evaluator_wall_upper_tolerance_bound_seconds"] == 1_218.0
    assert plan["experiment_wall_upper_tolerance_bound_seconds"] == 1_818
    assert plan["campaign_wall_upper_tolerance_bound_seconds"] == 2_818


def test_forecast_does_not_count_censored_or_different_wall_cycles() -> None:
    target = _target_contract()
    censored = _pilot(
        [200.0] * 6,
        contract=target,
        matching_cycle=True,
        source_contract_id="d" * 64,
    )
    first_sample = censored["blocks"][0]["samples"][0]
    first_sample["outcome"] = "right_censored"
    first_sample["censoring"] = {
        "kind": "right",
        "limit_seconds": first_sample["wall_seconds"],
        "reason": "semantic_timeout",
    }
    observation = censored["cycle_observation"]
    observation["status"] = "right_censored"
    observation["complete_sample_count"] -= 1
    observation["right_censored_sample_count"] = 1
    observation["right_censoring_lower_bound_seconds"] = observation["observed_active_wall_seconds"]
    observation["right_censoring_evaluator_wall_lower_bound_seconds"] = observation[
        "observed_evaluator_wall_seconds"
    ]
    observation.pop("active_wall_seconds")
    observation.pop("completed_evaluator_wall_seconds")

    other_wall = _contract_with_wall(target, target.budget.max_wall_seconds + 1.0)
    transferred = _pilot(
        [300.0] * 6,
        contract=other_wall,
        matching_cycle=True,
        source_contract_id="e" * 64,
    )
    report = forecast_runtime(
        (_record(censored), _record(transferred)),
        target_contract=target,
        simulations=1_000,
        seed=20260713,
        confidence=0.95,
        coverages=(0.95,),
        experiment_overhead_seconds=0.0,
        campaign_overhead_seconds=0.0,
    )

    assert report["design"]["matching_target_cycle_count"] == 0
    assert report["pilot"]["right_censored_sample_count"] == 1
    assert report["source_pilots"]["matching_target_cycle_sha256"] == []


def test_forecast_falls_back_to_deterministic_monte_carlo() -> None:
    contract = _target_contract()
    report = forecast_runtime(
        (_record(_pilot([float(value) for value in range(2, 22)], contract=contract)),),
        target_contract=contract,
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
    contract = _target_contract()
    first = _record(_pilot([100.0] * 6, contract=contract))
    with pytest.raises(ContractError, match="duplicate pilot digests"):
        forecast_runtime(
            (first, first),
            target_contract=contract,
            simulations=1_000,
            seed=1,
            confidence=0.95,
            coverages=(0.95, 0.99),
            experiment_overhead_seconds=0.0,
            campaign_overhead_seconds=0.0,
        )

    changed = deepcopy(_pilot([200.0] * 6, contract=contract))
    changed["evaluator_sha256"] = "d" * 64
    with pytest.raises(ContractError, match="bindings differ from target: evaluator_sha256"):
        forecast_runtime(
            (first, _record(changed)),
            target_contract=contract,
            simulations=1_000,
            seed=1,
            confidence=0.95,
            coverages=(0.95, 0.99),
            experiment_overhead_seconds=0.0,
            campaign_overhead_seconds=0.0,
        )

    same_cycle_first = _record(
        _pilot(
            [100.0] * 6,
            contract=contract,
            matching_cycle=True,
            source_contract_id="d" * 64,
        )
    )
    same_cycle_second = _record(
        _pilot(
            [101.0] * 6,
            contract=contract,
            matching_cycle=True,
            source_contract_id="d" * 64,
        )
    )
    with pytest.raises(ContractError, match="duplicate source_contract_id"):
        forecast_runtime(
            (same_cycle_first, same_cycle_second),
            target_contract=contract,
            simulations=1_000,
            seed=1,
            confidence=0.95,
            coverages=(0.95,),
            experiment_overhead_seconds=0.0,
            campaign_overhead_seconds=0.0,
        )


def test_runtime_forecast_cli_writes_the_digest_bound_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = _target_contract()
    contract_path = tmp_path / "target-contract.json"
    contract_path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    pilot_paths: list[Path] = []
    for index, rates in enumerate(([200.0] * 6, [400.0] * 6), start=1):
        path = tmp_path / f"pilot-{index}.json"
        path.write_text(json.dumps(_pilot(rates, contract=contract)), encoding="utf-8")
        pilot_paths.append(path)
    output = tmp_path / "forecast.json"

    code = crucible_main(
        [
            "runtime-forecast",
            "--pilot",
            str(pilot_paths[0]),
            "--pilot",
            str(pilot_paths[1]),
            "--target-contract",
            str(contract_path),
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
