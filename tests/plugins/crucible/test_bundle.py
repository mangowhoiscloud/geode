from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from plugins.crucible.bundle import PromotionBundle
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import (
    EXPERIMENT_SCHEMA,
    ContractError,
    ExperimentContract,
    Mutation,
    TaskUnit,
    task_pack_sha256,
)
from plugins.crucible.evidence import EVIDENCE_SCHEMA, EvidenceEnvelope, ResourceUsage
from plugins.crucible.promotion import PromotionVerdict, decide
from plugins.crucible.ref_journal import (
    RefIntent,
    RefReceipt,
    commit_ref_update,
    persist_intent,
)
from plugins.crucible.supervisor import RECORD_SCHEMA, CandidateProposal

CAMPAIGN_ID = "bundle-test"
ATTEMPT_ID = "0001-test"
ZERO_SHA = "0" * 40
GIT = shutil.which("git")
assert GIT is not None


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed Git executable and test-owned argv
        [GIT, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(path: Path) -> tuple[str, str, str]:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "crucible-test")
    _git(path, "config", "user.email", "crucible-test@localhost")
    commits: list[str] = []
    tracked = path / "tracked.txt"
    for index in range(3):
        tracked.write_text(f"revision {index}\n", encoding="utf-8")
        _git(path, "add", "tracked.txt")
        _git(path, "commit", "-qm", f"revision {index}")
        commits.append(_git(path, "rev-parse", "HEAD"))
    return commits[0], commits[1], commits[2]


def _contract(baseline_sha: str, candidate_sha: str) -> ExperimentContract:
    tasks = tuple(
        TaskUnit(
            task_id=f"task-{index}",
            family_id=f"family-{index}",
            content_sha256=f"{index:064x}",
        )
        for index in range(1, 5)
    )
    mutation = Mutation(surface="core/agent/verify.py", hypothesis="fewer misses")
    return ExperimentContract.from_mapping(
        {
            "schema": EXPERIMENT_SCHEMA,
            "name": "promotion-bundle-test",
            "stage": "train",
            "champion_ref": (f"refs/crucible/baselines/{CAMPAIGN_ID}/{ATTEMPT_ID}"),
            "baseline_sha": baseline_sha,
            "candidate_sha": candidate_sha,
            "evaluator_sha256": "a" * 64,
            "harness_sha256": "b" * 64,
            "task_pack_sha256": task_pack_sha256(tasks),
            "agent_route": "openai-subscription-gpt-5.4-high",
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
            "mutations": [mutation.to_dict()],
            "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
            "promotion": {
                "method": "paired_bootstrap.v2",
                "primary_metric": "reward",
                "materiality_pp": 0.1,
                "minimum_candidate_mean": 0.7,
                "minimum_tasks": 4,
                "minimum_families": 4,
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
    )


def _evidence(
    contract: ExperimentContract,
    *,
    arm: str,
    reward: float,
) -> EvidenceEnvelope:
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    return EvidenceEnvelope.from_mapping(
        {
            "schema": EVIDENCE_SCHEMA,
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": ("c" if arm == "baseline" else "d") * 64,
            "execution_status": "complete",
            "usage": {
                "wall_seconds": 10.0,
                "calls": 10,
                "tokens": 1_000,
                "cost_usd": 1.0,
            },
            "rows": [
                {
                    "task_id": task_id,
                    "trial": trial,
                    "status": "completed",
                    "termination_reason": "user_stop",
                    "metrics": {"reward": reward},
                    "checks": {"safety": True},
                }
                for task_id in contract.task_ids
                for trial in range(contract.trials_per_task)
            ],
        }
    )


def _request(contract: ExperimentContract) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "crucible.proposal-request.v3",
        "campaign_id": CAMPAIGN_ID,
        "config_id": "8" * 64,
        "attempt_id": ATTEMPT_ID,
        "iteration": 1,
        "parent_sha": contract.baseline_sha,
        "allowed_surfaces": [contract.mutation.surface],
        "feedback": None,
        "remaining_budget": {
            "wall_seconds": 100.0,
            "calls": 100,
            "tokens": 10_000,
            "cost_usd": 10.0,
        },
    }
    return {**payload, "request_id": _canonical_hash(payload)}


def _candidate(
    contract: ExperimentContract,
    *,
    request_id: str,
) -> CandidateProposal:
    return CandidateProposal(
        attempt_id=ATTEMPT_ID,
        request_id=request_id,
        parent_sha=contract.baseline_sha,
        candidate_sha=contract.candidate_sha,
        mutation=contract.mutation,
        usage=ResourceUsage(0.5, 1, 20, 0.01),
    )


def _record(
    contract: ExperimentContract,
    verdict: PromotionVerdict,
    candidate: CandidateProposal,
) -> dict[str, Any]:
    usage = verdict.usage + candidate.usage
    payload: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "timestamp": "2026-07-10T00:00:00+00:00",
        "component": "plugins.crucible.supervisor",
        "kind": "train_attempt",
        "campaign_id": CAMPAIGN_ID,
        "attempt_id": ATTEMPT_ID,
        "previous_record_id": None,
        "proposal_id": candidate.proposal_id,
        "contract_id": contract.contract_id,
        "verdict_id": verdict.verdict_id,
        "candidate_ref": f"refs/crucible/candidates/{CAMPAIGN_ID}/{ATTEMPT_ID}",
        "baseline_ref": f"refs/crucible/baselines/{CAMPAIGN_ID}/{ATTEMPT_ID}",
        "outcome": "KEEP",
        "reasons": list(verdict.reasons),
        "search_head_before": contract.baseline_sha,
        "search_head_after": contract.candidate_sha,
        "usage": usage.to_dict(),
        "wall_seconds": usage.wall_seconds,
    }
    return {**payload, "record_id": _canonical_hash(payload)}


def _rehash(payload: Mapping[str, Any], id_field: str) -> dict[str, Any]:
    canonical = {key: value for key, value in payload.items() if key != id_field}
    return {**canonical, id_field: _canonical_hash(canonical)}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True)
class _Attempt:
    repository: Path
    directory: Path
    contract: ExperimentContract
    baseline: EvidenceEnvelope
    candidate_evidence: EvidenceEnvelope
    verdict: PromotionVerdict
    request: dict[str, Any]
    candidate: CandidateProposal
    record: dict[str, Any]
    receipt: RefReceipt
    witness_ref: str
    third_sha: str


def _attempt(tmp_path: Path, *, applied: bool = True) -> _Attempt:
    repository = tmp_path / "repo"
    baseline_sha, candidate_sha, third_sha = _repository(repository)
    contract = _contract(baseline_sha, candidate_sha)
    baseline = _evidence(contract, arm="baseline", reward=0.4)
    candidate_evidence = _evidence(contract, arm="candidate", reward=0.8)
    verdict = decide(contract, baseline, candidate_evidence)
    assert verdict.verdict == "KEEP"
    request = _request(contract)
    candidate = _candidate(contract, request_id=str(request["request_id"]))
    record = _record(contract, verdict, candidate)
    directory = tmp_path / "attempt"
    directory.mkdir()
    artifacts = {
        "request.json": request,
        "candidate.json": candidate.to_dict(),
        "contract.json": contract.to_dict(),
        "baseline.attested.json": baseline.to_dict(),
        "candidate.attested.json": candidate_evidence.to_dict(),
        "verdict.json": verdict.to_dict(),
        "record.json": record,
    }
    for name, payload in artifacts.items():
        _write_json(directory / name, payload)

    ref = f"refs/crucible/search/{CAMPAIGN_ID}"
    subject_id = str(record["record_id"])
    witness_ref = f"refs/crucible/applied/{CAMPAIGN_ID}/{subject_id}"
    _git(repository, "update-ref", ref, baseline_sha, ZERO_SHA)
    intent = RefIntent(
        ref=ref,
        expected_old_sha=baseline_sha,
        new_sha=candidate_sha,
        subject_id=subject_id,
        witness_ref=witness_ref,
    )
    intent_path = directory / "search-ref.intent.json"
    receipt_path = directory / "search-ref.receipt.json"
    if applied:
        receipt = commit_ref_update(
            repository,
            intent,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )
    else:
        persist_intent(intent_path, intent)
        receipt = RefReceipt.from_intent(intent)
        _write_json(receipt_path, receipt.to_dict())
    return _Attempt(
        repository=repository,
        directory=directory,
        contract=contract,
        baseline=baseline,
        candidate_evidence=candidate_evidence,
        verdict=verdict,
        request=request,
        candidate=candidate,
        record=record,
        receipt=receipt,
        witness_ref=witness_ref,
        third_sha=third_sha,
    )


def _rebind_record_and_journal(
    attempt: _Attempt,
    *,
    proposal_id: str,
) -> None:
    record = deepcopy(attempt.record)
    record["proposal_id"] = proposal_id
    record = _rehash(record, "record_id")
    _write_json(attempt.directory / "record.json", record)
    intent = RefIntent(
        ref=f"refs/crucible/search/{CAMPAIGN_ID}",
        expected_old_sha=attempt.contract.baseline_sha,
        new_sha=attempt.contract.candidate_sha,
        subject_id=str(record["record_id"]),
        witness_ref=(f"refs/crucible/applied/{CAMPAIGN_ID}/{record['record_id']}"),
    )
    assert intent.witness_ref is not None
    _git(
        attempt.repository,
        "update-ref",
        intent.witness_ref,
        attempt.contract.candidate_sha,
        ZERO_SHA,
    )
    _write_json(attempt.directory / "search-ref.intent.json", intent.to_dict())
    _write_json(
        attempt.directory / "search-ref.receipt.json",
        RefReceipt.from_intent(intent).to_dict(),
    )


def test_build_from_attempt_binds_applied_canonical_train_keep_chain(
    tmp_path: Path,
) -> None:
    attempt = _attempt(tmp_path)

    bundle = PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)

    assert bundle.train_contract_id == attempt.contract.contract_id
    assert bundle.train_baseline_evidence_id == attempt.baseline.evidence_id
    assert bundle.train_candidate_evidence_id == attempt.candidate_evidence.evidence_id
    assert bundle.train_verdict_id == attempt.verdict.verdict_id
    assert bundle.train_record_id == attempt.record["record_id"]
    assert bundle.train_ref_receipt_id == attempt.receipt.receipt_id
    assert bundle.train_search_ref == f"refs/crucible/search/{CAMPAIGN_ID}"
    assert bundle.train_task_pack_sha256 == attempt.contract.task_pack_sha256
    assert _git(attempt.repository, "rev-parse", attempt.witness_ref) == bundle.candidate_sha
    loaded = PromotionBundle.from_mapping(bundle.to_dict())
    assert loaded == bundle
    assert hash(loaded) == hash(bundle)
    assert loaded.bundle_id == bundle.bundle_id


def test_bundle_id_tampering_fails_closed(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    payload = PromotionBundle.build_from_attempt(
        attempt.repository,
        attempt.directory,
    ).to_dict()
    payload["bundle_id"] = "0" * 64

    with pytest.raises(ContractError, match="bundle_id"):
        PromotionBundle.from_mapping(payload)


def test_fabricated_receipt_and_target_without_witness_are_not_authority(
    tmp_path: Path,
) -> None:
    attempt = _attempt(tmp_path, applied=False)
    _git(
        attempt.repository,
        "update-ref",
        f"refs/crucible/search/{CAMPAIGN_ID}",
        attempt.contract.candidate_sha,
        attempt.contract.baseline_sha,
    )

    with pytest.raises(ContractError, match="applied witness is stale"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_missing_applied_witness_invalidates_bundle_rebuild(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    _git(
        attempt.repository,
        "update-ref",
        "-d",
        attempt.witness_ref,
        attempt.contract.candidate_sha,
    )

    with pytest.raises(ContractError, match="applied witness is stale"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_drifted_applied_witness_invalidates_bundle_rebuild(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    _git(
        attempt.repository,
        "update-ref",
        attempt.witness_ref,
        attempt.third_sha,
        attempt.contract.candidate_sha,
    )

    with pytest.raises(ContractError, match="applied witness is stale"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_current_search_ref_drift_invalidates_bundle_rebuild(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    _git(
        attempt.repository,
        "update-ref",
        f"refs/crucible/search/{CAMPAIGN_ID}",
        attempt.third_sha,
        attempt.contract.candidate_sha,
    )

    with pytest.raises(ContractError, match=r"receipt is stale|observed"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


@pytest.mark.parametrize("mode", ["missing", "unknown", "rehashed"])
def test_supervisor_record_is_strict_even_when_rehashed(
    tmp_path: Path,
    mode: str,
) -> None:
    attempt = _attempt(tmp_path)
    record = deepcopy(attempt.record)
    if mode == "missing":
        del record["component"]
    elif mode == "unknown":
        record["authority"] = "release"
    else:
        record["component"] = "plugins.other.supervisor"
        record = _rehash(record, "record_id")
    _write_json(attempt.directory / "record.json", record)

    with pytest.raises(ContractError, match=r"record|supervisor"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_supervisor_record_candidate_fingerprint_ref_must_match(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    record = deepcopy(attempt.record)
    record["candidate_fingerprint"] = "a" * 64
    record["candidate_fingerprint_ref"] = "refs/crucible/candidate-fingerprints/" + "b" * 64
    record = _rehash(record, "record_id")
    _write_json(attempt.directory / "record.json", record)

    with pytest.raises(ContractError, match="candidate_fingerprint_ref does not match"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_negative_direct_evidence_usage_fails_canonical_rebuild(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    baseline = attempt.baseline.to_dict()
    usage = baseline["usage"]
    assert isinstance(usage, dict)
    usage["wall_seconds"] = -1.0
    baseline = _rehash(baseline, "evidence_id")
    _write_json(attempt.directory / "baseline.attested.json", baseline)

    with pytest.raises(ContractError, match=r"usage.wall_seconds.*greater than"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_missing_candidate_proposal_lineage_fails_closed(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    (attempt.directory / "candidate.json").unlink()

    with pytest.raises(ContractError, match=r"candidate|read"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_candidate_proposal_requires_persisted_proposal_id(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    candidate = attempt.candidate.to_dict()
    del candidate["proposal_id"]
    _write_json(attempt.directory / "candidate.json", candidate)

    with pytest.raises(ContractError, match=r"candidate proposal.*fields|proposal_id"):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("attempt_id", "other-attempt", "attempt"),
        ("parent_sha", None, "parent"),
        ("candidate_sha", None, "candidate"),
        (
            "mutation",
            {"surface": "core/agent/other.py", "hypothesis": "different change"},
            "mutation",
        ),
    ],
)
def test_rehashed_candidate_lineage_cannot_change_the_train_chain(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    attempt = _attempt(tmp_path)
    candidate = attempt.candidate.to_dict()
    if field in {"parent_sha", "candidate_sha"}:
        value = attempt.third_sha
    candidate[field] = value
    candidate = _rehash(candidate, "proposal_id")
    _write_json(attempt.directory / "candidate.json", candidate)
    _rebind_record_and_journal(
        attempt,
        proposal_id=str(candidate["proposal_id"]),
    )

    with pytest.raises(ContractError, match=message):
        PromotionBundle.build_from_attempt(attempt.repository, attempt.directory)


def test_bundle_cli_accepts_repository_attempt_and_writes_once(tmp_path: Path) -> None:
    attempt = _attempt(tmp_path)
    output = tmp_path / "bundle.json"
    argv = [
        "bundle",
        str(attempt.repository),
        str(attempt.directory),
        "--output",
        str(output),
    ]

    assert crucible_main(argv) == 0
    assert PromotionBundle.from_mapping(json.loads(output.read_text(encoding="utf-8")))
    assert crucible_main(argv) == 2
