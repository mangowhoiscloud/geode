from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import plugins.crucible.sealed as sealed_module
import pytest
from plugins.crucible.artifacts import write_exclusive_json
from plugins.crucible.bundle import PromotionBundle
from plugins.crucible.contract import (
    EXPERIMENT_SCHEMA,
    ContractError,
    ExperimentContract,
    TaskUnit,
    task_pack_sha256,
)
from plugins.crucible.evidence import EVIDENCE_SCHEMA, EvidenceEnvelope, ResourceUsage
from plugins.crucible.promotion import decide
from plugins.crucible.ref_journal import (
    RefIntent,
    RefReceipt,
    commit_ref_update,
    persist_intent,
)
from plugins.crucible.ref_journal import commit_ref_update as real_commit_ref_update
from plugins.crucible.runtime_receipt import SharedRuntimeDeadline, runtime_artifact_bindings
from plugins.crucible.sealed import (
    CorePromotionDecision,
    SealedError,
    SealedInfrastructureError,
    SealedPlan,
    SealedSupervisor,
)
from plugins.crucible.supervisor import PROPOSAL_SCHEMA, RECORD_SCHEMA, REQUEST_SCHEMA

_GIT = shutil.which("git")
if _GIT is None:  # pragma: no cover - test environment precondition
    raise RuntimeError("git is required for sealed tests")
GIT: str = _GIT
ZERO_SHA = "0" * 40


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(  # noqa: S603 - fixed Git executable and test-owned argv
        [GIT, *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if check:
        result.check_returncode()
    return result.stdout.strip()


def _repository(path: Path) -> tuple[str, str, str]:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "sealed-test")
    _git(path, "config", "user.email", "sealed-test@localhost")
    commits: list[str] = []
    tracked = path / "tracked.txt"
    for index in range(3):
        tracked.write_text(f"revision {index}\n", encoding="utf-8")
        _git(path, "add", "tracked.txt")
        _git(path, "commit", "-qm", f"revision {index}")
        commits.append(_git(path, "rev-parse", "HEAD"))
    return commits[0], commits[1], commits[2]


def _tasks(prefix: str) -> tuple[TaskUnit, ...]:
    return tuple(
        TaskUnit(
            task_id=f"{prefix}-task-{index}",
            family_id=f"{prefix}-family-{index}",
            content_sha256=hashlib.sha256(f"{prefix}-content-{index}".encode()).hexdigest(),
        )
        for index in range(4)
    )


def _contract(
    *,
    stage: Literal["train", "test"],
    baseline_sha: str,
    candidate_sha: str,
    tasks: tuple[TaskUnit, ...],
    champion_ref: str,
    parent_contract_id: str | None = None,
) -> ExperimentContract:
    payload: dict[str, object] = {
        "schema": EXPERIMENT_SCHEMA,
        "name": "one-shot-sealed-test",
        "stage": stage,
        "champion_ref": champion_ref,
        "baseline_sha": baseline_sha,
        "candidate_sha": candidate_sha,
        "evaluator_sha256": "a" * 64,
        "harness_sha256": "b" * 64,
        "task_pack_sha256": task_pack_sha256(tasks),
        "agent_route": "openai-subscription-gpt-5.4-high",
        "user_route": "tau2-user-simulator-fixed",
        "tasks": [task.to_dict() for task in tasks],
        "trials_per_task": 1,
        "assay_config": {
            "schema": "crucible.tau2-assay.v1",
            "domain": "fixture",
            "user": {
                "implementation": "user_simulator",
                "runtime_owner": "evaluator",
            },
        },
        "mutations": [
            {
                "surface": "core/agent/verify.py",
                "hypothesis": "fewer misses",
            }
        ],
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
            "max_tokens": 100_000,
            "max_cost_usd": 10.0,
            "max_changed_lines": 100,
        },
        "vetoes": ["budget", "infra_clean", "safety", "task_coverage"],
    }
    if parent_contract_id is not None:
        payload["parent_contract_id"] = parent_contract_id
    return ExperimentContract.from_mapping(payload)


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _Fixture:
    repository: Path
    parent: ExperimentContract
    test: ExperimentContract
    bundle: PromotionBundle
    plan: SealedPlan
    state: Path
    train_attempt: Path


def _fixture(
    tmp_path: Path,
    *,
    candidate: str | None = None,
    state_name: str = "state",
    suffix: str = "1",
) -> _Fixture:
    repository = tmp_path / "repo"
    if repository.exists():
        baseline = _git(repository, "rev-list", "--max-parents=0", "HEAD")
        commits = _git(repository, "rev-list", "--reverse", "HEAD").splitlines()
        default_candidate = commits[1]
    else:
        baseline, default_candidate, _third = _repository(repository)
    candidate_sha = candidate or default_candidate
    campaign_id = f"sealed-{suffix}"
    attempt_id = "0001-test"
    baseline_ref = f"refs/crucible/baselines/{campaign_id}/{attempt_id}"
    candidate_ref = f"refs/crucible/candidates/{campaign_id}/{attempt_id}"
    search_ref = f"refs/crucible/search/{campaign_id}"
    parent = _contract(
        stage="train",
        baseline_sha=baseline,
        candidate_sha=candidate_sha,
        tasks=_tasks("train"),
        champion_ref=baseline_ref,
    )
    test = _contract(
        stage="test",
        baseline_sha=baseline,
        candidate_sha=candidate_sha,
        tasks=_tasks("sealed"),
        champion_ref=baseline_ref,
        parent_contract_id=parent.contract_id,
    )

    train_attempt = tmp_path / f"train-attempt-{suffix}"
    train_attempt.mkdir()
    baseline_evidence = _evidence(
        parent,
        arm="baseline",
        reward=0.2,
        raw_sha256=hashlib.sha256(b"train-baseline").hexdigest(),
    )
    candidate_evidence = _evidence(
        parent,
        arm="candidate",
        reward=0.9,
        raw_sha256=hashlib.sha256(b"train-candidate").hexdigest(),
    )
    verdict = decide(parent, baseline_evidence, candidate_evidence)
    assert verdict.verdict == "KEEP"
    request_payload: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "campaign_id": campaign_id,
        "config_id": "c" * 64,
        "attempt_id": attempt_id,
        "iteration": 1,
        "parent_sha": baseline,
        "allowed_surfaces": [parent.mutation.surface],
        "feedback": None,
        "remaining_budget": {
            "wall_seconds": 100.0,
            "calls": 100,
            "tokens": 100_000,
            "cost_usd": 10.0,
        },
    }
    request = {**request_payload, "request_id": _canonical_hash(request_payload)}
    proposal_usage = ResourceUsage(1.0, 1, 100, 0.1)
    proposal_payload: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "attempt_id": attempt_id,
        "request_id": request["request_id"],
        "parent_sha": baseline,
        "candidate_sha": candidate_sha,
        "mutation": parent.mutation.to_dict(),
        "usage": proposal_usage.to_dict(),
    }
    proposal = {**proposal_payload, "proposal_id": _canonical_hash(proposal_payload)}
    record_usage = verdict.usage + proposal_usage
    record_payload: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "timestamp": "2026-07-10T00:00:00+00:00",
        "component": "plugins.crucible.supervisor",
        "kind": "train_attempt",
        "campaign_id": campaign_id,
        "attempt_id": attempt_id,
        "previous_record_id": None,
        "proposal_id": proposal["proposal_id"],
        "contract_id": parent.contract_id,
        "verdict_id": verdict.verdict_id,
        "candidate_ref": candidate_ref,
        "baseline_ref": baseline_ref,
        "outcome": "KEEP",
        "reasons": [],
        "search_head_before": baseline,
        "search_head_after": candidate_sha,
        "usage": record_usage.to_dict(),
        "wall_seconds": record_usage.wall_seconds,
    }
    record = {**record_payload, "record_id": _canonical_hash(record_payload)}
    for name, payload in (
        ("contract.json", parent.to_dict()),
        ("baseline.attested.json", baseline_evidence.to_dict()),
        ("candidate.attested.json", candidate_evidence.to_dict()),
        ("verdict.json", verdict.to_dict()),
        ("request.json", request),
        ("candidate.json", proposal),
        ("record.json", record),
    ):
        write_exclusive_json(train_attempt / name, payload)

    _git(repository, "update-ref", baseline_ref, baseline, ZERO_SHA)
    _git(repository, "update-ref", candidate_ref, candidate_sha, ZERO_SHA)
    _git(repository, "update-ref", search_ref, baseline, ZERO_SHA)
    commit_ref_update(
        repository,
        RefIntent(
            ref=search_ref,
            expected_old_sha=baseline,
            new_sha=candidate_sha,
            subject_id=str(record["record_id"]),
            witness_ref=f"refs/crucible/applied/{campaign_id}/{record['record_id']}",
        ),
        intent_path=train_attempt / "search-ref.intent.json",
        receipt_path=train_attempt / "search-ref.receipt.json",
    )
    bundle = PromotionBundle.build_from_attempt(repository, train_attempt)
    plan = SealedPlan(
        bundle_id=bundle.bundle_id,
        test_contract_id=test.contract_id,
        test_task_pack_sha256=test.task_pack_sha256,
        baseline_sha=baseline,
        candidate_sha=candidate_sha,
        eligible_ref=f"refs/crucible/eligible/sealed-{suffix}",
        expected_old_sha=ZERO_SHA,
        max_infra_retries=0,
        wall_timeout_seconds=30.0,
    )
    return _Fixture(
        repository=repository,
        parent=parent,
        test=test,
        bundle=bundle,
        plan=plan,
        state=tmp_path / state_name,
        train_attempt=train_attempt,
    )


def _evidence(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    reward: float,
    raw_sha256: str,
    contract_id: str | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope.from_mapping(
        {
            "schema": EVIDENCE_SCHEMA,
            "contract_id": contract_id or contract.contract_id,
            "arm": arm,
            "revision_sha": (
                contract.baseline_sha if arm == "baseline" else contract.candidate_sha
            ),
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": raw_sha256,
            "execution_status": "complete",
            "usage": {
                "wall_seconds": 5.0,
                "calls": 4,
                "tokens": 1_000,
                "cost_usd": 0.0,
            },
            "rows": [
                {
                    "task_id": task_id,
                    "trial": 0,
                    "status": "completed",
                    "termination_reason": "user_stop",
                    "metrics": {"reward": reward},
                    "checks": {"safety": True},
                }
                for task_id in contract.task_ids
            ],
        }
    )


class _Evaluator:
    def __init__(
        self,
        outcomes: list[str],
        *,
        on_call: Callable[[Path, int], None] | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.on_call = on_call

    def evaluate(
        self,
        plan: SealedPlan,
        contract: ExperimentContract,
        *,
        attempt_number: int,
        evaluation_dir: Path,
        timeout: float,
    ) -> Path:
        del timeout
        self.calls += 1
        if self.on_call is not None:
            self.on_call(evaluation_dir, attempt_number)
        outcome = self.outcomes[self.calls - 1]
        if outcome == "infra":
            raise SealedInfrastructureError("provider_unavailable")
        if outcome == "crash":
            raise RuntimeError("simulated process death after burn")

        baseline_raw = evaluation_dir / "baseline.raw.json"
        candidate_raw = evaluation_dir / "candidate.raw.json"
        baseline_raw.write_text(f"baseline-{attempt_number}\n", encoding="utf-8")
        candidate_raw.write_text(f"candidate-{attempt_number}\n", encoding="utf-8")
        baseline_sha = hashlib.sha256(baseline_raw.read_bytes()).hexdigest()
        candidate_sha = hashlib.sha256(candidate_raw.read_bytes()).hexdigest()
        if outcome == "REJECT":
            baseline_reward, candidate_reward = 0.8, 0.1
        else:
            baseline_reward, candidate_reward = 0.2, 0.9
        wrong_contract = "f" * 64 if outcome == "wrong_identity" else None
        baseline = _evidence(
            contract,
            arm="baseline",
            reward=baseline_reward,
            raw_sha256=baseline_sha,
            contract_id=wrong_contract,
        )
        candidate = _evidence(
            contract,
            arm="candidate",
            reward=candidate_reward,
            raw_sha256=candidate_sha,
            contract_id=wrong_contract,
        )
        baseline_path = evaluation_dir / "baseline.json"
        candidate_path = evaluation_dir / "candidate.json"
        baseline_path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")
        candidate_path.write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
        if outcome == "raw_tamper":
            candidate_raw.write_text("tampered\n", encoding="utf-8")
        runtime_receipt = evaluation_dir / "runtime.receipt.json"
        deadline = SharedRuntimeDeadline(contract, contract.budget.max_wall_seconds)
        baseline_clock = deadline.begin_arm("baseline")
        deadline.finish_arm(
            baseline_clock,
            "complete",
            measurement_source="full_cache" if outcome == "cached_receipt" else "fresh",
        )
        if outcome == "screened_receipt":
            deadline.record_synthetic_arm("candidate", "screened")
        else:
            candidate_clock = deadline.begin_arm("candidate")
            deadline.finish_arm(
                candidate_clock,
                "complete",
                measurement_source="full_cache" if outcome == "cached_receipt" else "fresh",
            )
        deadline.write(
            runtime_receipt,
            "complete",
            artifacts=runtime_artifact_bindings(baseline, candidate),
        )
        response: dict[str, object] = {
            "schema": "crucible.sealed-evaluation.v2",
            "plan_id": plan.plan_id,
            "contract_id": contract.contract_id,
            "attempt_number": attempt_number,
            "baseline": baseline_path.name,
            "candidate": candidate_path.name,
            "baseline_raw": baseline_raw.name,
            "candidate_raw": candidate_raw.name,
            "runtime_receipt": runtime_receipt.name,
        }
        if outcome == "feedback":
            response["feedback"] = {"failed_task_ids": [contract.task_ids[0]]}
        response_path = evaluation_dir / "response.json"
        response_path.write_text(json.dumps(response), encoding="utf-8")
        return response_path


def _supervisor(
    fixture: _Fixture,
    evaluator: _Evaluator,
    *,
    state: Path | None = None,
) -> SealedSupervisor:
    return SealedSupervisor(
        repository=fixture.repository,
        state_dir=state or fixture.state,
        plan=fixture.plan,
        train_attempt_dir=fixture.train_attempt,
        test_contract=fixture.test,
        evaluator=evaluator,
    )


def test_plan_and_decision_are_canonical_and_authority_neutral(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator(["KEEP"])
    decision = _supervisor(fixture, evaluator).run()
    plan = fixture.plan

    assert SealedPlan.from_mapping(plan.to_dict()) == plan
    assert CorePromotionDecision.from_mapping(decision.to_dict()) == decision
    assert decision.release_authority == "none"
    tampered_plan = deepcopy(plan.to_dict())
    tampered_plan["candidate_sha"] = "f" * 40
    with pytest.raises(SealedError, match="plan_id"):
        SealedPlan.from_mapping(tampered_plan)
    tampered_decision = deepcopy(decision.to_dict())
    tampered_decision["release_authority"] = "release"
    with pytest.raises(SealedError, match="release_authority"):
        CorePromotionDecision.from_mapping(tampered_decision)


def test_nonzero_infrastructure_retry_budget_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(SealedError, match="must be zero"):
        replace(fixture.plan, max_infra_retries=1)


def test_burns_precede_evaluator_and_keep_publishes_only_private_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    holder: dict[str, SealedSupervisor] = {}

    def assert_burned(evaluation_dir: Path, attempt_number: int) -> None:
        supervisor = holder["supervisor"]
        assert attempt_number == 1
        assert supervisor.global_claim_path.exists()
        assert supervisor.global_burn_path.exists()
        assert evaluation_dir.parent == supervisor.global_attempt_dir

    evaluator = _Evaluator(["KEEP"], on_call=assert_burned)
    supervisor = _supervisor(fixture, evaluator)
    holder["supervisor"] = supervisor
    observed_decision_before_cas = False

    def traced_commit(
        repository: Path,
        intent: RefIntent,
        *,
        intent_path: Path,
        receipt_path: Path,
    ) -> RefReceipt:
        nonlocal observed_decision_before_cas
        assert supervisor.decision_path.exists()
        assert supervisor.global_decision_path.exists()
        observed_decision_before_cas = True
        return real_commit_ref_update(
            repository,
            intent,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    monkeypatch.setattr(sealed_module, "commit_ref_update", traced_commit)
    decision = supervisor.run()

    assert decision.decision == "ELIGIBLE"
    assert decision.release_authority == "none"
    assert observed_decision_before_cas
    assert (
        _git(fixture.repository, "rev-parse", fixture.plan.eligible_ref)
        == fixture.plan.candidate_sha
    )
    assert supervisor.publication_receipt_path.exists()


def test_reject_is_terminal_never_reruns_or_publishes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator(["REJECT"])
    supervisor = _supervisor(fixture, evaluator)

    first = supervisor.run()
    second = supervisor.run()

    assert first == second
    assert first.decision == "REJECT"
    assert first.reasons == ("sealed_reject",)
    assert evaluator.calls == 1
    assert (
        _git(
            fixture.repository,
            "rev-parse",
            "--verify",
            "--quiet",
            fixture.plan.eligible_ref,
            check=False,
        )
        == ""
    )
    assert not supervisor.publication_receipt_path.exists()


def test_infrastructure_failure_is_terminal_and_never_retries(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator(["infra", "KEEP"])
    supervisor = _supervisor(fixture, evaluator)

    first = supervisor.run()
    second = supervisor.run()

    assert first == second
    assert first.decision == "INVALID"
    assert first.reasons == ("provider_unavailable",)
    assert first.attempts_consumed == 1
    assert evaluator.calls == 1


def test_orphaned_global_burn_is_terminal_after_local_state_deletion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    crashing = _Evaluator(["crash"])
    first_supervisor = _supervisor(fixture, crashing)

    with pytest.raises(RuntimeError, match="simulated process death"):
        first_supervisor.run()

    assert first_supervisor.global_burn_path.exists()
    assert not (first_supervisor.global_attempt_dir / "invalid.json").exists()
    shutil.rmtree(fixture.state)
    resumed = _Evaluator(["KEEP"])
    decision = _supervisor(fixture, resumed).run()

    assert decision.decision == "INVALID"
    assert decision.reasons == ("orphaned_after_burn",)
    assert decision.attempts_consumed == 1
    assert resumed.calls == 0
    invalid = json.loads((first_supervisor.global_attempt_dir / "invalid.json").read_text())
    assert invalid["failure_class"] == "orphaned_after_burn"


def test_invalid_verdict_recovers_terminal_class_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator(["wrong_identity"])
    supervisor = _supervisor(fixture, evaluator)
    real_write_invalid = SealedSupervisor._write_invalid

    def crash_before_invalid(self: SealedSupervisor, failure: str) -> object:
        assert failure == "evidence_identity_invalid"
        raise RuntimeError("simulated process death after verdict")

    monkeypatch.setattr(SealedSupervisor, "_write_invalid", crash_before_invalid)
    with pytest.raises(RuntimeError, match="simulated process death after verdict"):
        supervisor.run()
    monkeypatch.setattr(SealedSupervisor, "_write_invalid", real_write_invalid)
    resumed = _Evaluator(["KEEP"])

    decision = _supervisor(fixture, resumed).run()

    assert decision.decision == "INVALID"
    assert decision.reasons == ("evidence_identity_invalid",)
    assert evaluator.calls == 1
    assert resumed.calls == 0


@pytest.mark.parametrize("outcome", ["feedback", "raw_tamper", "wrong_identity"])
def test_protocol_tamper_is_terminal_and_never_spends_retry(
    tmp_path: Path,
    outcome: str,
) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator([outcome])
    supervisor = _supervisor(fixture, evaluator)

    decision = supervisor.run()

    assert decision.decision == "INVALID"
    assert decision.attempts_consumed == 1
    assert evaluator.calls == 1
    assert not supervisor.publication_receipt_path.exists()
    if outcome in {"feedback", "raw_tamper"}:
        detail = json.loads((supervisor.global_attempt_dir / "error.json").read_text())
        assert detail["schema"] == "crucible.sealed-operator-error.v1"
        assert detail["message"]
        assert decision.reasons == ("artifact_validation_failed",)


@pytest.mark.parametrize("outcome", ["cached_receipt", "screened_receipt"])
def test_sealed_receipt_requires_two_fresh_measured_arms(
    tmp_path: Path,
    outcome: str,
) -> None:
    fixture = _fixture(tmp_path)
    evaluator = _Evaluator([outcome])

    decision = _supervisor(fixture, evaluator).run()

    assert decision.decision == "INVALID"
    assert decision.reasons == ("artifact_validation_failed",)
    assert evaluator.calls == 1


def test_global_terminal_rebuilds_deleted_local_state_without_rerun(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first_evaluator = _Evaluator(["REJECT"])
    first = _supervisor(fixture, first_evaluator).run()
    shutil.rmtree(fixture.state)
    resumed = _Evaluator(["KEEP"])

    second = _supervisor(fixture, resumed).run()

    assert second == first
    assert second.decision == "REJECT"
    assert resumed.calls == 0
    assert (fixture.state / "decision.json").exists()


def test_global_decision_is_recomputed_from_attested_verdict(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first_supervisor = _supervisor(fixture, _Evaluator(["REJECT"]))
    decision = first_supervisor.run()
    tampered = replace(decision, decision="ELIGIBLE", reasons=())
    first_supervisor.global_decision_path.write_text(
        json.dumps(tampered.to_dict()),
        encoding="utf-8",
    )
    resumed = _Evaluator(["KEEP"])

    with pytest.raises(SealedError, match="recomputed terminal decision"):
        _supervisor(fixture, resumed).run()

    assert resumed.calls == 0


def test_git_attestation_survives_consistent_json_rewrite_and_deletion(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    supervisor = _supervisor(fixture, _Evaluator(["REJECT"]))
    rejected = supervisor.run()
    assert rejected.decision == "REJECT"
    assert _git(fixture.repository, "rev-parse", supervisor.attestation_ref)

    forged_baseline = _evidence(
        fixture.test,
        arm="baseline",
        reward=0.2,
        raw_sha256=hashlib.sha256(b"forged-baseline").hexdigest(),
    )
    forged_candidate = _evidence(
        fixture.test,
        arm="candidate",
        reward=0.9,
        raw_sha256=hashlib.sha256(b"forged-candidate").hexdigest(),
    )
    forged_verdict = decide(fixture.test, forged_baseline, forged_candidate)
    assert forged_verdict.verdict == "KEEP"
    forged_decision = replace(rejected, decision="ELIGIBLE", reasons=())
    for path, payload in (
        (supervisor.global_attempt_dir / "baseline.attested.json", forged_baseline.to_dict()),
        (supervisor.global_attempt_dir / "candidate.attested.json", forged_candidate.to_dict()),
        (supervisor.global_attempt_dir / "verdict.json", forged_verdict.to_dict()),
        (supervisor.global_decision_path, forged_decision.to_dict()),
        (supervisor.decision_path, forged_decision.to_dict()),
    ):
        path.write_text(json.dumps(payload), encoding="utf-8")

    resumed = _Evaluator(["KEEP"])
    with pytest.raises(SealedError, match="recomputed terminal decision"):
        _supervisor(fixture, resumed).run()
    assert resumed.calls == 0

    for path in (
        supervisor.global_attempt_dir / "baseline.attested.json",
        supervisor.global_attempt_dir / "candidate.attested.json",
        supervisor.global_attempt_dir / "verdict.json",
        supervisor.global_decision_path,
        supervisor.decision_path,
    ):
        path.unlink()

    recovered = _supervisor(fixture, resumed).run()

    assert recovered.decision == "REJECT"
    assert recovered.reasons == ("sealed_reject",)
    assert resumed.calls == 0
    assert (
        _git(
            fixture.repository,
            "rev-parse",
            "--verify",
            "--quiet",
            fixture.plan.eligible_ref,
            check=False,
        )
        == ""
    )


def test_eligible_ref_must_match_train_campaign(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    wrong_plan = replace(
        fixture.plan,
        eligible_ref="refs/crucible/eligible/different-campaign",
    )
    wrong_fixture = replace(fixture, plan=wrong_plan)
    evaluator = _Evaluator(["KEEP"])

    with pytest.raises(SealedError, match="eligible ref must match the train campaign"):
        _supervisor(wrong_fixture, evaluator).run()

    assert evaluator.calls == 0


def test_preexisting_publication_intent_must_match_decision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    holder: dict[str, SealedSupervisor] = {}

    def plant_mismatched_intent(_evaluation_dir: Path, _attempt_number: int) -> None:
        supervisor = holder["supervisor"]
        publication = supervisor.state_dir / "publication"
        publication.mkdir()
        persist_intent(
            publication / "intent.json",
            RefIntent(
                ref=fixture.plan.eligible_ref,
                expected_old_sha=fixture.plan.expected_old_sha,
                new_sha=fixture.plan.candidate_sha,
                subject_id="f" * 64,
            ),
        )

    evaluator = _Evaluator(["KEEP"], on_call=plant_mismatched_intent)
    supervisor = _supervisor(fixture, evaluator)
    holder["supervisor"] = supervisor

    with pytest.raises(SealedError, match="publication intent does not match"):
        supervisor.run()

    assert evaluator.calls == 1
    assert (
        _git(
            fixture.repository,
            "rev-parse",
            "--verify",
            "--quiet",
            fixture.plan.eligible_ref,
            check=False,
        )
        == ""
    )


def test_global_pack_burn_rejects_reuse_by_a_different_candidate(tmp_path: Path) -> None:
    first_fixture = _fixture(tmp_path, state_name="state-1", suffix="1")
    first = _supervisor(first_fixture, _Evaluator(["REJECT"]))
    assert first.run().decision == "REJECT"

    repository = first_fixture.repository
    commits = _git(repository, "rev-list", "--reverse", "HEAD").splitlines()
    different_fixture = _fixture(
        tmp_path,
        candidate=commits[2],
        state_name="state-2",
        suffix="2",
    )
    evaluator = _Evaluator(["KEEP"])

    with pytest.raises((SealedError, ContractError), match=r"different sealed plan|belongs"):
        _supervisor(different_fixture, evaluator).run()

    assert evaluator.calls == 0
