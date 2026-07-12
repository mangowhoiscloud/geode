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
from plugins.crucible.promotion import PromotionVerdict, decide, promotion_reachability

BASELINE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40


def _contract_payload(*, stage: str = "train") -> dict[str, object]:
    tasks = tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}") for index in range(1, 5)
    )
    payload: dict[str, object] = {
        "schema": "crucible.experiment.v3",
        "name": "paired-core-promotion",
        "stage": stage,
        "champion_ref": "refs/heads/develop",
        "baseline_sha": BASELINE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "evaluator_sha256": "a" * 64,
        "harness_sha256": "b" * 64,
        "task_pack_sha256": task_pack_sha256(tasks, 1),
        "agent_route": "candidate-agent-route",
        "user_route": "tau2-user_simulator-fixed-user",
        "tasks": [task.to_dict() for task in tasks],
        "trials_per_task": 1,
        "assay_config": {
            "schema": "crucible.tau2-assay.v1",
            "domain": "mock",
            "user": {
                "implementation": "user_simulator",
                "runtime_owner": "evaluator",
            },
        },
        "mutations": [{"surface": "core/agent/verify.py", "hypothesis": "fewer misses"}],
        "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
        "promotion": {
            "method": "paired_bootstrap.v2",
            "primary_metric": "reward",
            "materiality_pp": 0.1,
            "minimum_candidate_mean": 0.7,
            "minimum_families": 4,
            "minimum_tasks": 4,
            "confidence_level": 0.95,
            "bootstrap_samples": 1_000,
        },
        "budget": {
            "max_wall_seconds": 100.0,
            "max_calls": 100,
            "max_tokens": 10_000,
            "max_cost_usd": 10.0,
            "max_changed_lines": 100,
        },
        "vetoes": ["budget", "infra_clean", "safety", "task_coverage"],
    }
    if stage == "test":
        payload["parent_contract_id"] = "f" * 64
    return payload


def _contract(*, stage: str = "train") -> ExperimentContract:
    return ExperimentContract.from_mapping(_contract_payload(stage=stage))


def _evidence(
    contract: ExperimentContract,
    *,
    arm: str,
    rewards: list[float],
    execution_status: str = "complete",
    safety: bool = True,
    calls: int = 10,
    omit_last: bool = False,
) -> EvidenceEnvelope:
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    pairs = [
        (task_id, trial)
        for task_id in contract.task_ids
        for trial in range(contract.trials_per_task)
    ]
    rows = [
        {
            "task_id": task_id,
            "trial": trial,
            "status": "completed",
            "termination_reason": "user_stop",
            "metrics": {"reward": reward},
            "checks": {"safety": safety},
        }
        for (task_id, trial), reward in zip(pairs, rewards, strict=True)
    ]
    if omit_last:
        rows.pop()
    payload: dict[str, object] = {
        "schema": "crucible.evidence.v3",
        "contract_id": contract.contract_id,
        "arm": arm,
        "revision_sha": revision,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "raw_artifact_sha256": ("c" if arm == "baseline" else "d") * 64,
        "execution_status": execution_status,
        "usage": {
            "wall_seconds": 10.0,
            "calls": calls,
            "tokens": 1_000,
            "cost_usd": 1.0,
        },
        "rows": rows,
    }
    if execution_status == "invalid":
        payload["failure_class"] = "route_contamination"
    return EvidenceEnvelope.from_mapping(payload)


def test_train_keep_has_no_core_promotion_authority() -> None:
    contract = _contract()
    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(contract, arm="candidate", rewards=[0.8] * 4),
    )

    assert verdict.verdict == "KEEP"
    assert verdict.promotion_authority == "none"
    assert verdict.paired_improvement == pytest.approx(0.4)
    assert verdict.improvement_lower_bound == pytest.approx(0.4)


def test_test_keep_stays_authority_neutral_until_lineage_is_bound() -> None:
    contract = _contract(stage="test")
    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(contract, arm="candidate", rewards=[0.8] * 4),
    )

    assert verdict.verdict == "KEEP"
    assert verdict.promotion_authority == "none"


def test_metric_floor_and_safety_veto_cannot_be_averaged_away() -> None:
    contract = _contract()
    low_metric = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.6] * 4),
        _evidence(contract, arm="candidate", rewards=[0.65] * 4),
    )
    unsafe = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(contract, arm="candidate", rewards=[1.0] * 4, safety=False),
    )

    assert low_metric.verdict == "REJECT"
    assert "candidate_below_absolute_floor" in low_metric.reasons
    assert "improvement_below_materiality" in low_metric.reasons
    assert unsafe.verdict == "REJECT"
    assert dict(unsafe.vetoes)["safety"] is False


def test_budget_overrun_rejects_otherwise_strong_candidate() -> None:
    contract = _contract()
    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4, calls=60),
        _evidence(contract, arm="candidate", rewards=[0.8] * 4, calls=60),
    )

    assert verdict.verdict == "REJECT"
    assert verdict.reasons == ("budget_exceeded",)
    assert dict(verdict.vetoes)["budget"] is False


def test_incomplete_or_contaminated_evidence_is_invalid_not_rejected() -> None:
    contract = _contract()
    incomplete = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(contract, arm="candidate", rewards=[0.8] * 4, omit_last=True),
    )
    contaminated = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(
            contract,
            arm="candidate",
            rewards=[0.8] * 4,
            execution_status="invalid",
        ),
    )

    assert incomplete.verdict == "INVALID"
    assert "task_coverage_incomplete" in incomplete.reasons
    assert contaminated.verdict == "INVALID"
    assert "infrastructure_contamination" in contaminated.reasons


def test_evidence_identity_and_canonical_id_fail_closed() -> None:
    contract = _contract()
    evidence = _evidence(contract, arm="candidate", rewards=[0.8] * 4)
    payload = evidence.to_dict()
    payload["contract_id"] = "e" * 64
    payload.pop("evidence_id")
    wrong_contract = EvidenceEnvelope.from_mapping(payload)

    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        wrong_contract,
    )
    assert verdict.verdict == "INVALID"
    assert verdict.reasons[0].startswith("identity_mismatch:")

    tampered = deepcopy(evidence.to_dict())
    tampered["evidence_id"] = "f" * 64
    with pytest.raises(ContractError, match="evidence_id"):
        EvidenceEnvelope.from_mapping(tampered)


def test_verdict_round_trip_rejects_tampered_id() -> None:
    contract = _contract()
    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.4] * 4),
        _evidence(contract, arm="candidate", rewards=[0.8] * 4),
    )

    assert PromotionVerdict.from_mapping(verdict.to_dict()) == verdict
    tampered = verdict.to_dict()
    tampered["verdict_id"] = "f" * 64
    with pytest.raises(ContractError, match="verdict_id"):
        PromotionVerdict.from_mapping(tampered)

    impossible_authority = verdict.to_dict()
    impossible_authority.pop("verdict_id")
    impossible_authority["promotion_authority"] = "sealed_test"
    with pytest.raises(ContractError, match="must be 'none'"):
        PromotionVerdict.from_mapping(impossible_authority)


def test_bootstrap_is_family_clustered_and_independent_of_candidate_identity() -> None:
    payload = _contract_payload()
    payload["trials_per_task"] = 2
    raw_tasks = payload["tasks"]
    assert isinstance(raw_tasks, list)
    tasks = tuple(TaskUnit.from_mapping(item) for item in raw_tasks)
    payload["task_pack_sha256"] = task_pack_sha256(tasks, 2)
    first = ExperimentContract.from_mapping(payload)
    second_payload = deepcopy(payload)
    second_payload["candidate_sha"] = "3" * 40
    second = ExperimentContract.from_mapping(second_payload)
    baseline_rewards = [0.2, 0.4] * 4
    candidate_rewards = [0.7, 0.9] * 4

    first_verdict = decide(
        first,
        _evidence(first, arm="baseline", rewards=baseline_rewards),
        _evidence(first, arm="candidate", rewards=candidate_rewards),
    )
    second_verdict = decide(
        second,
        _evidence(second, arm="baseline", rewards=baseline_rewards),
        _evidence(second, arm="candidate", rewards=candidate_rewards),
    )

    assert first_verdict.pair_count == 8
    assert first_verdict.task_count == 4
    assert first_verdict.family_count == 4
    assert first_verdict.trials_per_task == 2
    assert first_verdict.improvement_lower_bound == second_verdict.improvement_lower_bound


def test_reachability_prunes_only_a_mathematically_impossible_baseline() -> None:
    payload = _contract_payload()
    tasks = tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}") for index in range(1, 7)
    )
    payload["tasks"] = [task.to_dict() for task in tasks]
    payload["task_pack_sha256"] = task_pack_sha256(tasks)
    promotion = deepcopy(payload["promotion"])
    assert isinstance(promotion, dict)
    promotion.update(
        {
            "materiality_pp": 0.25,
            "minimum_tasks": 6,
            "minimum_families": 6,
            "confidence_level": 0.885,
            "bootstrap_samples": 10_000,
        }
    )
    payload["promotion"] = promotion
    contract = ExperimentContract.from_mapping(payload)

    unreachable = promotion_reachability(
        contract,
        _evidence(contract, arm="baseline", rewards=[1.0] * 5 + [0.0]),
        metric_ceiling=1.0,
    )
    reachable = promotion_reachability(
        contract,
        _evidence(contract, arm="baseline", rewards=[1.0] * 4 + [0.0] * 2),
        metric_ceiling=1.0,
    )

    assert unreachable.reachable is False
    assert unreachable.paired_improvement_ceiling == pytest.approx(1 / 6)
    assert unreachable.reasons == (
        "improvement_ceiling_below_materiality",
        "confidence_ceiling_not_positive",
    )
    assert reachable.reachable is True
    assert reachable.reasons == ()


def test_many_tasks_in_one_family_are_one_inference_unit() -> None:
    payload = _contract_payload()
    tasks = tuple(
        TaskUnit(f"task-{index}", "shared-family", f"{index:064x}") for index in range(1, 21)
    )
    payload["tasks"] = [task.to_dict() for task in tasks]
    payload["task_pack_sha256"] = task_pack_sha256(tasks)
    promotion = deepcopy(payload["promotion"])
    assert isinstance(promotion, dict)
    promotion["minimum_tasks"] = 20
    promotion["minimum_families"] = 2
    payload["promotion"] = promotion
    contract = ExperimentContract.from_mapping(payload)

    verdict = decide(
        contract,
        _evidence(contract, arm="baseline", rewards=[0.2] * 20),
        _evidence(contract, arm="candidate", rewards=[0.9] * 20),
    )

    assert verdict.verdict == "REJECT"
    assert verdict.task_count == 20
    assert verdict.family_count == 1
    assert "insufficient_families" in verdict.reasons


def test_packaged_cli_writes_once_and_returns_verdict_exit_code(tmp_path: Path) -> None:
    contract = _contract()
    contract_path = tmp_path / "contract.json"
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    verdict_path = tmp_path / "verdict.json"
    contract_path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    baseline_path.write_text(
        json.dumps(_evidence(contract, arm="baseline", rewards=[0.4] * 4).to_dict()),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(_evidence(contract, arm="candidate", rewards=[0.8] * 4).to_dict()),
        encoding="utf-8",
    )

    args = [
        "score",
        str(contract_path),
        "--baseline",
        str(baseline_path),
        "--candidate",
        str(candidate_path),
        "--output",
        str(verdict_path),
    ]
    assert crucible_main(args) == 0
    assert json.loads(verdict_path.read_text())["verdict"] == "KEEP"
    assert crucible_main(args) == 2


def test_standalone_score_cannot_reopen_a_sealed_test(tmp_path: Path) -> None:
    contract = _contract(stage="test")
    contract_path = tmp_path / "test-contract.json"
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    contract_path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    baseline_path.write_text(
        json.dumps(_evidence(contract, arm="baseline", rewards=[0.4] * 4).to_dict()),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(_evidence(contract, arm="candidate", rewards=[0.8] * 4).to_dict()),
        encoding="utf-8",
    )

    assert (
        crucible_main(
            [
                "score",
                str(contract_path),
                "--baseline",
                str(baseline_path),
                "--candidate",
                str(candidate_path),
            ]
        )
        == 2
    )
