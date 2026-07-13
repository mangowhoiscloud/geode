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
from plugins.crucible.evidence import EvidenceEnvelope
from plugins.crucible.runtime_budget import audit_runtime_budget, runtime_pilot_block_rates
from plugins.crucible.runtime_identity import (
    canonical_runtime_hash,
    runtime_design_from_parts,
    runtime_regime_from_parts,
    runtime_regime_id,
)
from plugins.crucible.runtime_pilot import build_runtime_pilot
from plugins.crucible.runtime_receipt import SharedRuntimeDeadline

from tests.plugins.crucible.test_promotion import _contract, _evidence


def _runtime_receipt(
    tmp_path: Path,
    contract: ExperimentContract,
    *,
    infrastructure_invalid: bool = False,
    wall_seconds: float | None = None,
) -> Path:
    deadline = SharedRuntimeDeadline(
        contract,
        contract.budget.max_wall_seconds if wall_seconds is None else wall_seconds,
    )
    baseline = deadline.begin_arm("baseline")
    deadline.finish_arm(baseline, "complete")
    candidate = deadline.begin_arm("candidate")
    deadline.finish_arm(candidate, "invalid" if infrastructure_invalid else "complete")
    path = tmp_path / "runtime.receipt.json"
    deadline.write(path, "infrastructure_invalid" if infrastructure_invalid else "complete")
    return path


def _tasks(count: int = 9) -> tuple[TaskUnit, ...]:
    return tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}")
        for index in range(1, count + 1)
    )


def _pilot(
    tmp_path: Path,
    *,
    assay_config: dict[str, object],
    block_samples: list[list[tuple[str, float]]] | None = None,
    agent_route: str = "agent-route",
    user_route: str = "user-route",
    tasks: tuple[TaskUnit, ...] | None = None,
    trials_per_task: int = 3,
    stage: str = "train",
    evaluator_sha256: str = "a" * 64,
    harness_sha256: str = "b" * 64,
    experiment_wall_seconds: float = 27_000.0,
) -> tuple[Path, str]:
    selected_tasks = tasks or _tasks()
    samples = block_samples or [[("complete", 500.0)] for _index in range(9)]
    bindings = {
        "evaluator_sha256": evaluator_sha256,
        "harness_sha256": harness_sha256,
        "assay_config_sha256": hashlib.sha256(
            json.dumps(
                assay_config,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "agent_route": agent_route,
        "user_route": user_route,
    }
    design = runtime_design_from_parts(
        tasks=selected_tasks,
        trials_per_task=trials_per_task,
        task_pack_sha256=task_pack_sha256(selected_tasks, trials_per_task),
    )
    regime = runtime_regime_from_parts(
        stage=stage,
        bindings=bindings,
        design=design,
        experiment_wall_seconds=experiment_wall_seconds,
    )
    has_infrastructure = any(
        outcome == "infrastructure_failure" for block in samples for outcome, _seconds in block
    )
    has_censoring = any(
        outcome in {"right_censored", "semantic_timeout"}
        for block in samples
        for outcome, _seconds in block
    )
    cycle_status = (
        "infrastructure_invalid"
        if has_infrastructure
        else "right_censored"
        if has_censoring
        else "complete"
    )
    observed_active_wall = sum(seconds for block in samples for _outcome, seconds in block)
    cycle_observation: dict[str, object] = {
        "status": cycle_status,
        "observed_active_wall_seconds": observed_active_wall,
        "observed_evaluator_wall_seconds": observed_active_wall,
        "complete_sample_count": sum(
            outcome == "complete" for block in samples for outcome, _seconds in block
        ),
        "right_censored_sample_count": sum(
            outcome in {"right_censored", "semantic_timeout"}
            for block in samples
            for outcome, _seconds in block
        ),
        "infrastructure_failure_sample_count": sum(
            outcome == "infrastructure_failure" for block in samples for outcome, _seconds in block
        ),
    }
    if cycle_status == "complete":
        cycle_observation["active_wall_seconds"] = observed_active_wall
        cycle_observation["completed_evaluator_wall_seconds"] = observed_active_wall
    elif cycle_status == "right_censored":
        cycle_observation["right_censoring_lower_bound_seconds"] = observed_active_wall
        cycle_observation["right_censoring_evaluator_wall_lower_bound_seconds"] = (
            observed_active_wall
        )

    def sample_payload(outcome: str, seconds: float) -> dict[str, object]:
        normalized = "right_censored" if outcome == "semantic_timeout" else outcome
        result: dict[str, object] = {"outcome": normalized, "wall_seconds": seconds}
        if normalized == "right_censored":
            result["censoring"] = {
                "kind": "right",
                "limit_seconds": seconds,
                "reason": "semantic_timeout",
            }
        return result

    payload = {
        "schema": "crucible.runtime-pilot.v2",
        "accounting_method": "sum-finalized-simulation-elapsed.v1",
        **bindings,
        "source_contract_id": "d" * 64,
        "source_runtime_receipt_id": "e" * 64,
        "runtime_regime": regime,
        "runtime_regime_id": canonical_runtime_hash(regime),
        "cycle_observation": cycle_observation,
        "blocks": [
            {"samples": [sample_payload(outcome, seconds) for outcome, seconds in block]}
            for block in samples
        ],
    }
    path = tmp_path / "runtime-pilot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _specification(
    pilot: Path,
    digest: str,
    *,
    minimum_usable_blocks: int = 4,
) -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "pilot_file": str(pilot),
        "pilot_sha256": digest,
        "source": "opaque completed campaign runtime pilot",
        "simulations": 1_000,
        "seed": 20260713,
        "admission_quantile": 0.99,
        "headroom_ratio": 0.0,
        "experiment_overhead_seconds": 0.0,
        "campaign_overhead_seconds": 1_000.0,
        "minimum_usable_blocks": minimum_usable_blocks,
    }


def _audit(
    tmp_path: Path,
    *,
    experiment_wall: float,
    campaign_wall: float,
    block_samples: list[list[tuple[str, float]]] | None = None,
) -> dict:
    assay = {"schema": "fixture.v1", "timeout_seconds": 600}
    pilot, digest = _pilot(
        tmp_path,
        assay_config=assay,
        block_samples=block_samples,
        experiment_wall_seconds=experiment_wall,
    )
    return audit_runtime_budget(
        tasks=(tasks := _tasks()),
        trials_per_task=3,
        task_pack_sha256=task_pack_sha256(tasks, 3),
        stage="train",
        evaluator_sha256="a" * 64,
        harness_sha256="b" * 64,
        agent_route="agent-route",
        user_route="user-route",
        assay_config=assay,
        configured_experiment_wall_seconds=experiment_wall,
        configured_campaign_wall_seconds=campaign_wall,
        specification=_specification(pilot, digest),
        basis_root=tmp_path,
    )


def _ceiling_specification(
    *,
    experiment_overhead_seconds: float = 600.0,
    campaign_overhead_seconds: float = 1_000.0,
    cleanup_grace_seconds: float = 0.0,
) -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "mode": "contract_ceiling",
        "source": "frozen assay timeout ceiling",
        "experiment_overhead_seconds": experiment_overhead_seconds,
        "campaign_overhead_seconds": campaign_overhead_seconds,
        "cleanup_grace_seconds": cleanup_grace_seconds,
    }


def _ceiling_audit(
    *,
    task_count: int,
    trials_per_task: int,
    experiment_wall: float,
    campaign_wall: float | None,
    experiment_overhead_seconds: float = 600.0,
    campaign_overhead_seconds: float = 1_000.0,
    cleanup_grace_seconds: float = 0.0,
) -> dict:
    return audit_runtime_budget(
        tasks=(tasks := _tasks(task_count)),
        trials_per_task=trials_per_task,
        task_pack_sha256=task_pack_sha256(tasks, trials_per_task),
        stage="train",
        evaluator_sha256="a" * 64,
        harness_sha256="b" * 64,
        agent_route="agent-route",
        user_route="user-route",
        assay_config={"schema": "fixture.v1", "timeout": 600.0},
        configured_experiment_wall_seconds=experiment_wall,
        configured_campaign_wall_seconds=campaign_wall,
        specification=_ceiling_specification(
            experiment_overhead_seconds=experiment_overhead_seconds,
            campaign_overhead_seconds=campaign_overhead_seconds,
            cleanup_grace_seconds=cleanup_grace_seconds,
        ),
        basis_root=Path("."),
    )


def _operational_deadline_specification(
    *,
    campaign_overhead_seconds: float = 1_000.0,
) -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v2",
        "mode": "operational_deadline",
        "source": "preregistered experiment-wide wall budget",
        "campaign_overhead_seconds": campaign_overhead_seconds,
        "cleanup_grace_seconds": 0.0,
        "risk_acceptance": "nonzero_clean_timeout",
    }


def _operational_deadline_audit(
    *,
    experiment_wall: float = 33_000.0,
    campaign_wall: float | None = 34_000.0,
    timeout: object = None,
) -> dict:
    return audit_runtime_budget(
        tasks=(tasks := _tasks()),
        trials_per_task=3,
        task_pack_sha256=task_pack_sha256(tasks, 3),
        stage="train",
        evaluator_sha256="a" * 64,
        harness_sha256="b" * 64,
        agent_route="agent-route",
        user_route="user-route",
        assay_config={"schema": "fixture.v1", "timeout": timeout},
        configured_experiment_wall_seconds=experiment_wall,
        configured_campaign_wall_seconds=campaign_wall,
        specification=_operational_deadline_specification(),
        basis_root=Path("."),
    )


def _verified_arm(
    tmp_path: Path,
    *,
    arm: str,
    timeout_index: int | None = None,
    infrastructure_index: int | None = None,
) -> tuple[Path, EvidenceEnvelope]:
    contract = _contract(stage="test")
    raw = {
        "simulations": [
            {
                "task_id": task_id,
                "trial": 0,
                "duration": float(index + 1) * 10.0,
            }
            for index, task_id in enumerate(contract.task_ids)
        ]
    }
    results = tmp_path / f"{arm}.raw.json"
    results.write_text(json.dumps(raw), encoding="utf-8")
    evidence = _evidence(contract, arm=arm, rewards=[1.0] * 4)
    payload = evidence.to_dict()
    payload.pop("evidence_id")
    payload["raw_artifact_sha256"] = hashlib.sha256(results.read_bytes()).hexdigest()
    rows = payload["rows"]
    assert isinstance(rows, list)
    if timeout_index is not None:
        rows[timeout_index]["termination_reason"] = "timeout"
    if infrastructure_index is not None:
        rows[infrastructure_index]["status"] = "infrastructure_error"
        rows[infrastructure_index]["failure_class"] = "tau2_infrastructure_error"
        payload["execution_status"] = "invalid"
        payload["failure_class"] = "tau2_infrastructure_error"
    return results, EvidenceEnvelope.from_mapping(payload)


def test_runtime_audit_admits_the_9x3_500_second_row_envelope(tmp_path: Path) -> None:
    report = _audit(tmp_path, experiment_wall=27_000, campaign_wall=28_000)

    assert report["passes"] is True
    assert report["design"]["paired_row_count"] == 54
    assert report["admission"] == {
        "required_experiment_wall_seconds": 27_000,
        "configured_experiment_wall_seconds": 27_000.0,
        "experiment_passes": True,
        "required_campaign_wall_seconds": 28_000,
        "configured_campaign_wall_seconds": 28_000.0,
        "campaign_passes": True,
    }
    encoded = str(report)
    assert "task-1" not in encoded
    assert "family-1" not in encoded
    assert str(tmp_path) not in encoded


def test_contract_ceiling_admits_bootstrap_campaign_without_a_pilot() -> None:
    report = _ceiling_audit(
        task_count=9,
        trials_per_task=3,
        experiment_wall=33_000,
        campaign_wall=34_000,
    )

    assert report["passes"] is True
    assert report["method"] == "bounded-process-termination-envelope.v2"
    assert report["ceiling"] == {
        "timeout_seconds_per_row": 600.0,
        "paired_row_ceiling_seconds": 32_400.0,
        "experiment_overhead_seconds": 600.0,
        "cleanup_grace_seconds": 0.0,
        "campaign_overhead_seconds": 1_000.0,
        "guarantee": "process_termination_only",
        "clean_completion_guaranteed": False,
    }
    assert report["admission"]["required_experiment_wall_seconds"] == 33_000
    assert report["admission"]["required_campaign_wall_seconds"] == 34_000
    assert "pilot_sha256" not in report


def test_operational_deadline_admits_rows_with_explicit_clean_timeout_risk() -> None:
    report = _operational_deadline_audit()

    assert report["passes"] is True
    assert report["method"] == "operator-selected-deadline.v1"
    assert report["operational_deadline"] == {
        "timeout_seconds_per_row": None,
        "experiment_wall_seconds": 33_000.0,
        "cleanup_grace_seconds": 0.0,
        "campaign_overhead_seconds": 1_000.0,
        "risk_acceptance": "nonzero_clean_timeout",
        "statistical_confidence_bound": None,
        "contract_ceiling_seconds": None,
    }
    assert report["admission"]["required_experiment_wall_seconds"] == 33_000.0
    assert report["admission"]["required_campaign_wall_seconds"] == 34_000


def test_operational_deadline_rejects_a_hidden_row_timeout() -> None:
    with pytest.raises(ContractError, match=r"requires assay_config\.timeout=null"):
        _operational_deadline_audit(timeout=600.0)


def test_operational_deadline_rejects_short_campaign_wall() -> None:
    report = _operational_deadline_audit(campaign_wall=33_999.0)

    assert report["passes"] is False
    assert report["admission"]["experiment_passes"] is True
    assert report["admission"]["campaign_passes"] is False


def test_contract_ceiling_rejects_zero_overhead_campaign_budget() -> None:
    report = _ceiling_audit(
        task_count=9,
        trials_per_task=3,
        experiment_wall=32_400,
        campaign_wall=32_400,
    )

    assert report["passes"] is False
    assert report["admission"]["experiment_passes"] is False
    assert report["admission"]["campaign_passes"] is False


def test_contract_ceiling_sizes_the_6x2_sealed_experiment() -> None:
    report = _ceiling_audit(
        task_count=6,
        trials_per_task=2,
        experiment_wall=15_000,
        campaign_wall=None,
        campaign_overhead_seconds=0.0,
    )

    assert report["passes"] is True
    assert report["design"]["paired_row_count"] == 24
    assert report["admission"]["required_experiment_wall_seconds"] == 15_000


def test_contract_ceiling_accounts_for_cleanup_as_a_separate_term() -> None:
    report = _ceiling_audit(
        task_count=1,
        trials_per_task=1,
        experiment_wall=1_810,
        campaign_wall=1_810,
        experiment_overhead_seconds=600.0,
        campaign_overhead_seconds=0.0,
        cleanup_grace_seconds=10.0,
    )

    assert report["passes"] is True
    assert report["ceiling"]["paired_row_ceiling_seconds"] == 1_200.0
    assert report["ceiling"]["cleanup_grace_seconds"] == 10.0
    assert report["admission"]["required_experiment_wall_seconds"] == 1_810


def test_legacy_fixed_wall_mode_is_rejected_instead_of_relabelled() -> None:
    specification = _operational_deadline_specification()
    specification["mode"] = "fixed_experiment_wall"

    with pytest.raises(ContractError, match="superseded by operational_deadline"):
        audit_runtime_budget(
            tasks=(tasks := _tasks()),
            trials_per_task=3,
            task_pack_sha256=task_pack_sha256(tasks, 3),
            stage="train",
            evaluator_sha256="a" * 64,
            harness_sha256="b" * 64,
            agent_route="agent-route",
            user_route="user-route",
            assay_config={"schema": "fixture.v1", "timeout": None},
            configured_experiment_wall_seconds=33_000.0,
            configured_campaign_wall_seconds=34_000.0,
            specification=specification,
            basis_root=Path("."),
        )


def test_runtime_pilot_writer_projects_verified_rows_without_identities(tmp_path: Path) -> None:
    contract = _contract(stage="test")
    baseline_results, baseline_evidence = _verified_arm(
        tmp_path,
        arm="baseline",
        timeout_index=1,
    )
    candidate_results, candidate_evidence = _verified_arm(
        tmp_path,
        arm="candidate",
        infrastructure_index=2,
    )

    pilot = build_runtime_pilot(
        contract,
        runtime_receipt_path=_runtime_receipt(
            tmp_path,
            contract,
            infrastructure_invalid=True,
        ),
        baseline_results_path=baseline_results,
        baseline_evidence=baseline_evidence,
        candidate_results_path=candidate_results,
        candidate_evidence=candidate_evidence,
    )

    assert len(pilot["blocks"]) == 4
    assert pilot["schema"] == "crucible.runtime-pilot.v2"
    assert pilot["blocks"][1]["samples"][0]["outcome"] == "right_censored"
    assert pilot["blocks"][1]["samples"][0]["censoring"]["kind"] == "right"
    assert pilot["cycle_observation"]["status"] == "infrastructure_invalid"
    assert pilot["blocks"][2]["samples"][1]["outcome"] == "infrastructure_failure"
    encoded = str(pilot)
    assert "task-1" not in encoded
    assert "family-1" not in encoded


def test_runtime_pilot_cli_writes_the_digest_basis(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = _contract(stage="test")
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    baseline_results, baseline_evidence = _verified_arm(tmp_path, arm="baseline")
    candidate_results, candidate_evidence = _verified_arm(tmp_path, arm="candidate")
    baseline_evidence_path = tmp_path / "baseline.evidence.json"
    candidate_evidence_path = tmp_path / "candidate.evidence.json"
    baseline_evidence_path.write_text(json.dumps(baseline_evidence.to_dict()), encoding="utf-8")
    candidate_evidence_path.write_text(json.dumps(candidate_evidence.to_dict()), encoding="utf-8")
    runtime_receipt = _runtime_receipt(tmp_path, contract)
    output = tmp_path / "runtime-pilot.json"

    code = crucible_main(
        [
            "runtime-pilot",
            str(contract_path),
            "--runtime-receipt",
            str(runtime_receipt),
            "--baseline-results",
            str(baseline_results),
            "--baseline-evidence",
            str(baseline_evidence_path),
            "--candidate-results",
            str(candidate_results),
            "--candidate-evidence",
            str(candidate_evidence_path),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text(encoding="utf-8"))


def test_runtime_pilot_uses_the_receipts_effective_wall_for_regime_identity(
    tmp_path: Path,
) -> None:
    contract = _contract(stage="test")
    baseline_results, baseline_evidence = _verified_arm(tmp_path, arm="baseline")
    candidate_results, candidate_evidence = _verified_arm(tmp_path, arm="candidate")

    pilot = build_runtime_pilot(
        contract,
        runtime_receipt_path=_runtime_receipt(tmp_path, contract, wall_seconds=80.0),
        baseline_results_path=baseline_results,
        baseline_evidence=baseline_evidence,
        candidate_results_path=candidate_results,
        candidate_evidence=candidate_evidence,
    )

    assert pilot["runtime_regime"]["execution"]["experiment_wall_seconds"] == 80.0
    assert pilot["runtime_regime_id"] == runtime_regime_id(
        contract,
        experiment_wall_seconds=80.0,
    )
    assert pilot["runtime_regime_id"] != runtime_regime_id(contract)


def test_runtime_audit_rejects_the_inherited_18k_19k_budget(tmp_path: Path) -> None:
    report = _audit(tmp_path, experiment_wall=18_000, campaign_wall=19_000)

    assert report["passes"] is False
    assert report["admission"]["experiment_passes"] is False
    assert report["admission"]["campaign_passes"] is False


def test_runtime_pilot_counts_censoring_without_treating_it_as_an_exact_duration(
    tmp_path: Path,
) -> None:
    samples = [
        [("complete", 100.0)],
        [("semantic_timeout", 600.0)],
        [("complete", 200.0), ("infrastructure_failure", 2.0)],
        [("complete", 300.0)],
        [("infrastructure_failure", 1.0)],
    ]
    assay = {"schema": "fixture.v1", "timeout_seconds": 600}
    pilot_path, _digest = _pilot(tmp_path, assay_config=assay, block_samples=samples)
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    first_rates, first = runtime_pilot_block_rates(pilot)
    second_rates, second = runtime_pilot_block_rates(pilot)

    assert (first_rates, first) == (second_rates, second)
    assert first_rates == [100.0, 300.0]
    assert first == {
        "block_count": 5,
        "usable_block_count": 2,
        "complete_sample_count": 3,
        "right_censored_sample_count": 1,
        "right_censored_block_count": 1,
        "infrastructure_sample_count_excluded": 2,
        "infrastructure_block_count_excluded": 2,
    }


def test_runtime_audit_rejects_a_phantom_pilot_digest(tmp_path: Path) -> None:
    assay = {"schema": "fixture.v1"}
    pilot, digest = _pilot(tmp_path, assay_config=assay)
    specification = deepcopy(_specification(pilot, digest))
    specification["pilot_sha256"] = "c" * 64

    with pytest.raises(ContractError, match="does not match pilot_sha256"):
        audit_runtime_budget(
            tasks=(tasks := _tasks()),
            trials_per_task=3,
            task_pack_sha256=task_pack_sha256(tasks, 3),
            stage="train",
            evaluator_sha256="a" * 64,
            harness_sha256="b" * 64,
            agent_route="agent-route",
            user_route="user-route",
            assay_config=assay,
            configured_experiment_wall_seconds=27_000,
            configured_campaign_wall_seconds=28_000,
            specification=specification,
            basis_root=tmp_path,
        )


def test_runtime_audit_rejects_a_pilot_from_another_evaluator(tmp_path: Path) -> None:
    assay = {"schema": "fixture.v1"}
    pilot, digest = _pilot(tmp_path, assay_config=assay)

    with pytest.raises(ContractError, match="evaluator_sha256 does not match"):
        audit_runtime_budget(
            tasks=(tasks := _tasks()),
            trials_per_task=3,
            task_pack_sha256=task_pack_sha256(tasks, 3),
            stage="train",
            evaluator_sha256="d" * 64,
            harness_sha256="b" * 64,
            agent_route="agent-route",
            user_route="user-route",
            assay_config=assay,
            configured_experiment_wall_seconds=27_000,
            configured_campaign_wall_seconds=28_000,
            specification=_specification(pilot, digest),
            basis_root=tmp_path,
        )


def test_runtime_audit_cli_accepts_a_sealed_test_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    contract = _contract(stage="test")
    contract_path = tmp_path / "sealed-contract.json"
    contract_path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    pilot, digest = _pilot(
        tmp_path,
        assay_config=contract.assay_config,
        block_samples=[[("complete", 10.0)] for _index in range(4)],
        agent_route=contract.agent_route,
        user_route=contract.user_route,
        tasks=contract.tasks,
        trials_per_task=contract.trials_per_task,
        stage=contract.stage,
        evaluator_sha256=contract.evaluator_sha256,
        harness_sha256=contract.harness_sha256,
        experiment_wall_seconds=contract.budget.max_wall_seconds,
    )
    specification = _specification(pilot, digest)
    specification["campaign_overhead_seconds"] = 0.0
    spec_path = tmp_path / "runtime-spec.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    output = tmp_path / "runtime-report.json"

    code = crucible_main(
        [
            "runtime-audit",
            str(contract_path),
            "--spec",
            str(spec_path),
            "--output",
            str(output),
        ]
    )

    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert printed == saved
    assert saved["passes"] is True
    assert saved["admission"]["required_experiment_wall_seconds"] == 80
    assert saved["admission"]["configured_campaign_wall_seconds"] is None
    assert "task-1" not in str(saved)
