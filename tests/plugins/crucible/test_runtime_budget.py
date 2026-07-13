import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import ContractError, TaskUnit
from plugins.crucible.evidence import EvidenceEnvelope
from plugins.crucible.runtime_budget import audit_runtime_budget
from plugins.crucible.runtime_pilot import build_runtime_pilot

from tests.plugins.crucible.test_promotion import _contract, _evidence


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
) -> tuple[Path, str]:
    samples = block_samples or [[("complete", 500.0)] for _index in range(9)]
    payload = {
        "schema": "crucible.runtime-pilot.v1",
        "accounting_method": "sum-finalized-simulation-elapsed.v1",
        "evaluator_sha256": "a" * 64,
        "harness_sha256": "b" * 64,
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
        "blocks": [
            {
                "samples": [
                    {"outcome": outcome, "wall_seconds": seconds} for outcome, seconds in block
                ]
            }
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
        "schema": "crucible.runtime-budget-spec.v1",
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
    pilot, digest = _pilot(tmp_path, assay_config=assay, block_samples=block_samples)
    return audit_runtime_budget(
        tasks=_tasks(),
        trials_per_task=3,
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
) -> dict[str, object]:
    return {
        "schema": "crucible.runtime-budget-spec.v1",
        "mode": "contract_ceiling",
        "source": "frozen assay timeout ceiling",
        "headroom_ratio": 0.0,
        "experiment_overhead_seconds": experiment_overhead_seconds,
        "campaign_overhead_seconds": campaign_overhead_seconds,
    }


def _ceiling_audit(
    *,
    task_count: int,
    trials_per_task: int,
    experiment_wall: float,
    campaign_wall: float | None,
    experiment_overhead_seconds: float = 600.0,
    campaign_overhead_seconds: float = 1_000.0,
) -> dict:
    return audit_runtime_budget(
        tasks=_tasks(task_count),
        trials_per_task=trials_per_task,
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
        ),
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
    assert report["method"] == "contract-timeout-ceiling.v1"
    assert report["ceiling"] == {
        "timeout_seconds_per_row": 600.0,
        "paired_row_ceiling_seconds": 32_400.0,
        "experiment_overhead_seconds": 600.0,
        "headroom_ratio": 0.0,
        "campaign_overhead_seconds": 1_000.0,
    }
    assert report["admission"]["required_experiment_wall_seconds"] == 33_000
    assert report["admission"]["required_campaign_wall_seconds"] == 34_000
    assert "pilot_sha256" not in report


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
        baseline_results_path=baseline_results,
        baseline_evidence=baseline_evidence,
        candidate_results_path=candidate_results,
        candidate_evidence=candidate_evidence,
    )

    assert len(pilot["blocks"]) == 4
    assert pilot["blocks"][1]["samples"][0]["outcome"] == "semantic_timeout"
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
    output = tmp_path / "runtime-pilot.json"

    code = crucible_main(
        [
            "runtime-pilot",
            str(contract_path),
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


def test_runtime_audit_rejects_the_inherited_18k_19k_budget(tmp_path: Path) -> None:
    report = _audit(tmp_path, experiment_wall=18_000, campaign_wall=19_000)

    assert report["passes"] is False
    assert report["admission"]["experiment_passes"] is False
    assert report["admission"]["campaign_passes"] is False


def test_runtime_audit_is_deterministic_and_keeps_semantic_timeouts(
    tmp_path: Path,
) -> None:
    samples = [
        [("complete", 100.0)],
        [("semantic_timeout", 600.0)],
        [("complete", 200.0), ("infrastructure_failure", 2.0)],
        [("complete", 300.0)],
        [("infrastructure_failure", 1.0)],
    ]
    first = _audit(
        tmp_path,
        experiment_wall=100_000,
        campaign_wall=101_000,
        block_samples=samples,
    )
    second = _audit(
        tmp_path,
        experiment_wall=100_000,
        campaign_wall=101_000,
        block_samples=samples,
    )

    assert first == second
    assert first["pilot"] == {
        "block_count": 5,
        "usable_block_count": 4,
        "complete_sample_count": 3,
        "semantic_timeout_sample_count": 1,
        "infrastructure_sample_count_excluded": 2,
    }
    assert first["bootstrap"]["maximum_seconds"] <= 54 * 600


def test_runtime_audit_rejects_a_phantom_pilot_digest(tmp_path: Path) -> None:
    assay = {"schema": "fixture.v1"}
    pilot, digest = _pilot(tmp_path, assay_config=assay)
    specification = deepcopy(_specification(pilot, digest))
    specification["pilot_sha256"] = "c" * 64

    with pytest.raises(ContractError, match="does not match pilot_sha256"):
        audit_runtime_budget(
            tasks=_tasks(),
            trials_per_task=3,
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
            tasks=_tasks(),
            trials_per_task=3,
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
