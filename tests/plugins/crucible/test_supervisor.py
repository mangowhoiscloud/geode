import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from plugins.crucible.bundle import PromotionBundle
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import (
    ExperimentContract,
    Mutation,
    TaskUnit,
    content_sha256,
    load_contract,
    task_pack_sha256,
    tracked_tree_sha256,
)
from plugins.crucible.evidence import EvidenceEnvelope, ResourceUsage
from plugins.crucible.ref_journal import load_receipt
from plugins.crucible.runtime_receipt import SharedRuntimeDeadline, runtime_artifact_bindings
from plugins.crucible.supervisor import (
    CandidateProposal,
    FailureFeedback,
    GitWorkspace,
    LoopLimits,
    PromotionSupervisor,
    ProposalRequest,
    SupervisorConfig,
    SupervisorError,
    TrainPlan,
    _run_process,
)

VerdictName = Literal["KEEP", "REJECT", "INVALID"]


def test_role_process_sigterm_reaps_its_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: dict[signal.Signals, object] = {}
    kill_calls: list[tuple[int, int]] = []

    class Process:
        pid = 12345
        stopped = False

        def wait(self, timeout: float | None = None) -> int:
            handler = installed[signal.SIGTERM]
            assert callable(handler)
            handler(signal.SIGTERM, None)
            raise AssertionError("signal handler must interrupt wait")

        def poll(self) -> int | None:
            return -signal.SIGTERM if self.stopped else None

    process = Process()

    def install(signum: signal.Signals, handler: object) -> object:
        installed[signum] = handler
        return signal.SIG_DFL

    def kill_group(pid: int, signum: int) -> None:
        kill_calls.append((pid, signum))
        if signum == 0 and process.stopped:
            raise ProcessLookupError
        if signum == signal.SIGTERM:
            process.stopped = True

    monkeypatch.setattr("plugins.crucible.supervisor.subprocess.Popen", lambda *a, **kw: process)
    monkeypatch.setattr("plugins.crucible.supervisor.signal.signal", install)
    monkeypatch.setattr("plugins.crucible.supervisor.os.killpg", kill_group)

    with pytest.raises(SystemExit, match=str(128 + signal.SIGTERM)):
        _run_process(
            ("fixture",),
            cwd=tmp_path,
            environment={},
            timeout=10.0,
        )

    assert (12345, signal.SIGTERM) in kill_calls
    assert (12345, 0) in kill_calls


EVALUATOR_SCRIPT = "#!/usr/bin/env python3\n" + textwrap.dedent(
    """
    import hashlib
    import json
    import math
    import os
    from pathlib import Path

    request = json.loads(Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"]).read_text())
    candidate = json.loads(Path(os.environ["CRUCIBLE_CANDIDATE"]).read_text())
    contract = json.loads(Path(os.environ["CRUCIBLE_CONTRACT"]).read_text())
    assert "worktree" not in request
    assert not (Path.cwd() / ".venv").exists()
    assert (Path.cwd() / "surface.txt").read_text() == "candidate\\n"

    assay_config = json.dumps(
        contract["assay_config"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    def evidence(arm, reward, raw_hash):
        revision = contract[f"{arm}_sha"]
        return {
            "schema": "crucible.evidence.v3",
            "contract_id": contract["contract_id"],
            "arm": arm,
            "revision_sha": revision,
            "evaluator_sha256": contract["evaluator_sha256"],
            "harness_sha256": contract["harness_sha256"],
            "task_pack_sha256": contract["task_pack_sha256"],
            "assay_config_sha256": hashlib.sha256(assay_config).hexdigest(),
            "raw_artifact_sha256": raw_hash,
            "execution_status": "complete",
            "usage": {
                "wall_seconds": 0.5,
                "calls": 1,
                "tokens": 10,
                "cost_usd": 0.1,
            },
            "rows": [
                {
                    "task_id": task_id,
                    "trial": 0,
                    "status": "completed",
                    "termination_reason": "done",
                    "metrics": {"reward": reward},
                    "checks": {"safety": True},
                }
                for task_id in (task["task_id"] for task in contract["tasks"])
            ],
        }

    output = Path(os.environ["CRUCIBLE_EVALUATION_OUTPUT"])
    baseline_raw_path = output.parent / "baseline.raw.json"
    candidate_raw_path = output.parent / "candidate.raw.json"
    baseline_raw_path.write_text('{"arm":"baseline"}')
    candidate_raw_path.write_text('{"arm":"candidate"}')
    baseline_raw_hash = hashlib.sha256(baseline_raw_path.read_bytes()).hexdigest()
    candidate_raw_hash = hashlib.sha256(candidate_raw_path.read_bytes()).hexdigest()
    canonical = lambda value: hashlib.sha256(json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()).hexdigest()
    baseline_evidence = evidence("baseline", 0.2, baseline_raw_hash)
    candidate_evidence = evidence("candidate", 0.9, candidate_raw_hash)
    baseline_path = output.parent / "baseline.json"
    candidate_path = output.parent / "candidate-evidence.json"
    baseline_path.write_text(json.dumps(baseline_evidence))
    candidate_path.write_text(json.dumps(candidate_evidence))
    family_counts = {}
    for task in contract["tasks"]:
        family_counts[task["family_id"]] = family_counts.get(task["family_id"], 0) + 1
    wall = min(
        float(os.environ["CRUCIBLE_EVALUATION_WALL_SECONDS"]),
        contract["budget"]["max_wall_seconds"],
    )
    supervisor_started = float(os.environ["CRUCIBLE_EVALUATION_STARTED_MONOTONIC"])
    supervisor_deadline = float(os.environ["CRUCIBLE_EVALUATION_DEADLINE_MONOTONIC"])
    assert math.isclose(supervisor_deadline - supervisor_started, wall, abs_tol=1e-6)
    runtime_regime = {
        "schema": "crucible.runtime-regime.v1",
        "stage": contract["stage"],
        "bindings": {
            "evaluator_sha256": contract["evaluator_sha256"],
            "harness_sha256": contract["harness_sha256"],
            "assay_config_sha256": hashlib.sha256(assay_config).hexdigest(),
            "agent_route": contract["agent_route"],
            "user_route": contract["user_route"],
        },
        "design": {
            "task_pack_sha256": contract["task_pack_sha256"],
            "task_count": len(contract["tasks"]),
            "family_count": len(family_counts),
            "family_task_counts": sorted(family_counts.values()),
            "trials_per_task": contract["trials_per_task"],
            "paired_row_count": len(contract["tasks"]) * contract["trials_per_task"] * 2,
        },
        "execution": {
            "arm_order": "baseline_then_candidate",
            "arm_wall_policy": "shared_deadline_remaining.v1",
            "accounting_scope": "fresh_simulation_active_wall",
            "experiment_wall_seconds": wall,
            "outer_finalization_grace_seconds": 5.5,
            "row_cache": "excluded_from_runtime_model",
        },
    }
    receipt_payload = {
        "schema": "crucible.runtime-receipt.v2",
        "contract_id": contract["contract_id"],
        "runtime_regime_id": canonical(runtime_regime),
        "wall_policy": "shared_deadline_remaining.v1",
        "configured_experiment_wall_seconds": wall,
        "active_evaluation_wall_seconds": wall - 5.5,
        "observation": {"status": "complete", "observed_wall_seconds": 0.0},
        "arms": [
            {"arm": "baseline", "allocated_wall_seconds": wall - 5.5, "measurement_source": "fresh", "observed_wall_seconds": 0.0, "outcome": "complete"},
            {"arm": "candidate", "allocated_wall_seconds": wall - 5.5, "measurement_source": "fresh", "observed_wall_seconds": 0.0, "outcome": "complete"},
        ],
        "artifacts": {
            "baseline": {
                "evidence_id": canonical(baseline_evidence),
                "raw_artifact_sha256": baseline_raw_hash,
            },
            "candidate": {
                "evidence_id": canonical(candidate_evidence),
                "raw_artifact_sha256": candidate_raw_hash,
            },
        },
        "cleanup": {
            "measured_scope": "evaluator_inner",
            "phases": [],
            "observed_wall_seconds": 0.0,
            "unmeasured_scopes": [
                "outer_supervisor_process_reap",
                "ledger_and_ref_finalization",
            ],
        },
    }
    runtime_receipt = output.parent / "runtime.receipt.json"
    runtime_receipt.write_text(json.dumps({
        **receipt_payload, "runtime_receipt_id": canonical(receipt_payload)
    }))
    payload = {
        "schema": "crucible.train-evaluation.v4",
        "attempt_id": request["attempt_id"],
        "request_id": request["request_id"],
        "proposal_id": candidate["proposal_id"],
        "baseline": baseline_path.name,
        "candidate": candidate_path.name,
        "baseline_raw": baseline_raw_path.name,
        "candidate_raw": candidate_raw_path.name,
        "runtime_receipt": runtime_receipt.name,
        "feedback": {
            "schema": "crucible.failure-feedback.v3",
            "failure_codes": [],
        },
    }
    output.write_text(json.dumps(payload))
    """
)


def _git(repo: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(  # noqa: S603 - fixed test executable and argv
        [executable, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "fixture@example.com")
    _git(path, "config", "user.name", "Fixture")
    for relative, content in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if content.startswith("#!"):
            target.chmod(0o755)
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "fixture baseline")
    return _git(path, "rev-parse", "HEAD")


def _train_plan(repo: Path, harness: Path) -> TrainPlan:
    tasks = tuple(
        TaskUnit(f"task-{index}", f"family-{index}", f"{index:064x}") for index in range(1, 5)
    )
    return TrainPlan.from_mapping(
        {
            "schema": "crucible.train-plan.v3",
            "name": "supervisor-fixture",
            "evaluator_sha256": content_sha256(repo, ["evaluator.py"]),
            "harness_sha256": tracked_tree_sha256(harness),
            "task_pack_sha256": task_pack_sha256(tasks),
            "agent_route": "fixture-agent",
            "user_route": "fixture-user",
            "tasks": [task.to_dict() for task in tasks],
            "trials_per_task": 1,
            "assay_config": {"schema": "fixture.v1"},
            "evaluator_paths": ["evaluator.py"],
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
                "max_wall_seconds": 60.0,
                "max_calls": 1_000,
                "max_tokens": 100_000,
                "max_cost_usd": 100.0,
                "max_changed_lines": 20,
            },
            "vetoes": ["budget", "infra_clean", "safety", "task_coverage"],
        }
    )


def _config(
    tmp_path: Path,
    *,
    attempts: int = 3,
    invalid_limit: int = 3,
    max_calls: int = 100,
) -> tuple[SupervisorConfig, str]:
    repo = tmp_path / "repo"
    baseline = _init_repo(
        repo,
        {
            ".gitignore": ".venv/\n",
            "surface.txt": "baseline\n",
            "evaluator.py": EVALUATOR_SCRIPT,
        },
    )
    harness = tmp_path / "harness"
    _init_repo(harness, {"runner.txt": "frozen harness\n"})
    return (
        SupervisorConfig(
            campaign_id="fixture-campaign",
            initial_search_head_sha=baseline,
            repository=repo,
            harness_root=harness,
            state_dir=tmp_path / "campaign-state",
            allowed_surfaces=("surface.txt",),
            producer_command=("unused-producer",),
            evaluator_entrypoint="evaluator.py",
            producer_environment=(),
            evaluator_environment=(),
            train_plan=_train_plan(repo, harness),
            limits=LoopLimits(
                max_attempts=attempts,
                max_consecutive_invalid=invalid_limit,
                max_wall_seconds=60.0,
                max_calls=max_calls,
                max_tokens=10_000,
                max_cost_usd=10.0,
            ),
        ),
        baseline,
    )


class _Producer:
    def __init__(
        self,
        *,
        dirty: bool = False,
        extra_path: bool = False,
        calls: int = 1,
    ) -> None:
        self.dirty = dirty
        self.extra_path = extra_path
        self.calls = calls
        self.worktree_roots: list[Path] = []
        self.feedbacks: list[Mapping[str, object] | None] = []

    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal:
        assert timeout > 0
        assert _git(request.worktree, "remote") == ""
        self.feedbacks.append(request.feedback)
        self.worktree_roots.append(request.worktree.parent)
        surface = request.worktree / "surface.txt"
        surface.write_text(f"candidate {request.iteration}\n", encoding="utf-8")
        _git(request.worktree, "add", "surface.txt")
        if self.extra_path:
            (request.worktree / "escape.py").write_text("ESCAPE = True\n", encoding="utf-8")
            _git(request.worktree, "add", "escape.py")
        _git(request.worktree, "commit", "-qm", f"candidate {request.iteration}")
        if self.dirty:
            (request.worktree / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            poison = request.worktree / ".venv" / "bin" / "python"
            poison.parent.mkdir(parents=True)
            poison.write_text("candidate controlled\n", encoding="utf-8")
        return CandidateProposal(
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            parent_sha=request.parent_sha,
            candidate_sha=_git(request.worktree, "rev-parse", "HEAD"),
            mutation=Mutation(surface="surface.txt", hypothesis="fixture improvement"),
            usage=ResourceUsage(0.1, self.calls, 10, 0.1),
        )


class _RepeatingProducer(_Producer):
    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal:
        assert timeout > 0
        self.feedbacks.append(request.feedback)
        surface = request.worktree / "surface.txt"
        surface.write_text("same candidate\n", encoding="utf-8")
        _git(request.worktree, "add", "surface.txt")
        _git(request.worktree, "commit", "-qm", f"repeated candidate {request.iteration}")
        return CandidateProposal(
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            parent_sha=request.parent_sha,
            candidate_sha=_git(request.worktree, "rev-parse", "HEAD"),
            mutation=Mutation(surface="surface.txt", hypothesis="repeat fixture"),
            usage=ResourceUsage(0.1, self.calls, 10, 0.1),
        )


class _Evaluator:
    def __init__(
        self,
        verdicts: list[VerdictName],
        *,
        calls_per_arm: int = 1,
        dirty_after_response: bool = False,
        feedback_code: str = "quality",
    ) -> None:
        self.verdicts = verdicts
        self.calls_per_arm = calls_per_arm
        self.dirty_after_response = dirty_after_response
        self.feedback_code = feedback_code
        self.calls = 0

    def _evidence(
        self,
        contract: ExperimentContract,
        *,
        arm: Literal["baseline", "candidate"],
        reward: float,
        invalid: bool,
        raw_hash: str,
    ) -> EvidenceEnvelope:
        revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
        payload: dict[str, object] = {
            "schema": "crucible.evidence.v3",
            "contract_id": contract.contract_id,
            "arm": arm,
            "revision_sha": revision,
            "evaluator_sha256": contract.evaluator_sha256,
            "harness_sha256": contract.harness_sha256,
            "task_pack_sha256": contract.task_pack_sha256,
            "assay_config_sha256": contract.assay_config_sha256,
            "raw_artifact_sha256": raw_hash,
            "execution_status": "invalid" if invalid else "complete",
            "usage": {
                "wall_seconds": 0.5,
                "calls": self.calls_per_arm,
                "tokens": 100,
                "cost_usd": 0.25,
            },
            "rows": [
                {
                    "task_id": task_id,
                    "trial": 0,
                    "status": "completed",
                    "termination_reason": "done",
                    "metrics": {"reward": reward},
                    "checks": {"safety": True},
                }
                for task_id in contract.task_ids
            ],
        }
        if invalid:
            payload["failure_class"] = "fixture_infrastructure"
        return EvidenceEnvelope.from_mapping(payload)

    def evaluate(
        self,
        request: ProposalRequest,
        proposal: CandidateProposal,
        contract: ExperimentContract,
        *,
        checkout: Path,
        timeout: float,
    ) -> Path:
        assert timeout > 0
        assert checkout != request.worktree
        assert _git(checkout, "remote") == ""
        assert not (checkout / ".venv").exists()
        verdict = self.verdicts[self.calls]
        self.calls += 1
        baseline_reward, candidate_reward = {
            "KEEP": (0.2, 0.9),
            "REJECT": (0.8, 0.7),
            "INVALID": (0.2, 0.9),
        }[verdict]
        evaluation_dir = request.attempt_dir / f"fixture-evaluation-{request.attempt_id}"
        evaluation_dir.mkdir()
        baseline_raw = evaluation_dir / "baseline.raw.json"
        candidate_raw = evaluation_dir / "candidate.raw.json"
        baseline_raw.write_text('{"arm":"baseline"}', encoding="utf-8")
        candidate_raw.write_text('{"arm":"candidate"}', encoding="utf-8")
        baseline = self._evidence(
            contract,
            arm="baseline",
            reward=baseline_reward,
            invalid=False,
            raw_hash=hashlib.sha256(baseline_raw.read_bytes()).hexdigest(),
        )
        candidate = self._evidence(
            contract,
            arm="candidate",
            reward=candidate_reward,
            invalid=verdict == "INVALID",
            raw_hash=hashlib.sha256(candidate_raw.read_bytes()).hexdigest(),
        )
        baseline_path = evaluation_dir / "baseline.json"
        candidate_path = evaluation_dir / "candidate.json"
        baseline_path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")
        candidate_path.write_text(json.dumps(candidate.to_dict()), encoding="utf-8")
        runtime_receipt = evaluation_dir / "runtime.receipt.json"
        deadline = SharedRuntimeDeadline(contract, min(timeout, contract.budget.max_wall_seconds))
        baseline_clock = deadline.begin_arm("baseline")
        deadline.finish_arm(baseline_clock, "complete")
        candidate_clock = deadline.begin_arm("candidate")
        deadline.finish_arm(candidate_clock, "invalid" if verdict == "INVALID" else "complete")
        deadline.write(
            runtime_receipt,
            "infrastructure_invalid" if verdict == "INVALID" else "complete",
            artifacts=runtime_artifact_bindings(baseline, candidate),
        )
        response = evaluation_dir / "response.json"
        response.write_text(
            json.dumps(
                {
                    "schema": "crucible.train-evaluation.v4",
                    "attempt_id": request.attempt_id,
                    "request_id": request.request_id,
                    "proposal_id": proposal.proposal_id,
                    "baseline": baseline_path.name,
                    "candidate": candidate_path.name,
                    "baseline_raw": baseline_raw.name,
                    "candidate_raw": candidate_raw.name,
                    "runtime_receipt": runtime_receipt.name,
                    "feedback": FailureFeedback(
                        failure_codes=(self.feedback_code,),
                    ).to_dict(),
                }
            ),
            encoding="utf-8",
        )
        if self.dirty_after_response:
            (checkout / "evaluator-residue.txt").write_text("dirty\n", encoding="utf-8")
        return response


class _MarginalEvaluator(_Evaluator):
    def evaluate(
        self,
        request: ProposalRequest,
        proposal: CandidateProposal,
        contract: ExperimentContract,
        *,
        checkout: Path,
        timeout: float,
    ) -> Path:
        response = super().evaluate(
            request,
            proposal,
            contract,
            checkout=checkout,
            timeout=timeout,
        )
        payload = json.loads(response.read_text(encoding="utf-8"))
        payload["marginal_usage"] = ResourceUsage(0.0, 0, 0, 0.0).to_dict()
        response.write_text(json.dumps(payload), encoding="utf-8")
        return response


class _ReplaceSpoofProducer:
    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal:
        assert timeout > 0
        escape = request.worktree / "escape.py"
        escape.write_text("ESCAPE = True\n", encoding="utf-8")
        _git(request.worktree, "add", "escape.py")
        _git(request.worktree, "commit", "-qm", "hidden parent")
        surface = request.worktree / "surface.txt"
        surface.write_text("candidate\n", encoding="utf-8")
        _git(request.worktree, "add", "surface.txt")
        _git(request.worktree, "commit", "-qm", "visible candidate")
        candidate = _git(request.worktree, "rev-parse", "HEAD")
        tree = _git(request.worktree, "rev-parse", f"{candidate}^{{tree}}")
        replacement = _git(
            request.worktree,
            "commit-tree",
            tree,
            "-p",
            request.parent_sha,
            "-m",
            "fake one-child view",
        )
        _git(request.worktree, "replace", candidate, replacement)
        return CandidateProposal(
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            parent_sha=request.parent_sha,
            candidate_sha=candidate,
            mutation=Mutation(surface="surface.txt", hypothesis="spoofed history"),
            usage=ResourceUsage(0.1, 1, 10, 0.1),
        )


def _ledger(config: SupervisorConfig) -> list[dict[str, object]]:
    return [json.loads(row) for row in (config.state_dir / "ledger.jsonl").read_text().splitlines()]


def test_standalone_loop_advances_only_private_search_ref_on_train_keep(
    tmp_path: Path,
) -> None:
    config, baseline = _config(tmp_path)
    producer = _Producer()
    summary = PromotionSupervisor(
        config,
        producer=producer,
        evaluator=_Evaluator(["KEEP", "REJECT", "INVALID"]),
    ).run()

    ledger = _ledger(config)
    first_keep = str(ledger[0]["search_head_after"])
    assert summary.final_search_head_sha == first_keep
    assert (summary.attempts, summary.keeps, summary.rejects, summary.invalids) == (3, 1, 1, 1)
    assert summary.stop_reason == "max_attempts"
    assert _git(config.repository, "rev-parse", "HEAD") == baseline
    assert _git(config.repository, "rev-parse", summary.search_ref) == first_keep
    first_attempt = sorted((config.state_dir / "attempts").iterdir())[0]
    first_contract = load_contract(first_attempt / "contract.json")
    first_receipt = load_receipt(first_attempt / "search-ref.receipt.json")
    assert _git(config.repository, "rev-parse", first_contract.champion_ref) == baseline
    assert first_receipt.ref == summary.search_ref
    assert first_receipt.subject_id == ledger[0]["record_id"]
    assert first_receipt.expected_old_sha == baseline
    assert first_receipt.new_sha == first_keep
    bundle = PromotionBundle.build_from_attempt(config.repository, first_attempt)
    assert bundle.candidate_sha == first_keep
    assert producer.worktree_roots
    assert all(not path.exists() for path in producer.worktree_roots)
    assert [row["outcome"] for row in ledger] == ["KEEP", "REJECT", "INVALID"]
    assert ledger[1]["previous_record_id"] == ledger[0]["record_id"]
    assert ledger[1]["search_head_after"] == first_keep
    assert summary.usage.calls == 9
    assert summary.usage.tokens == 630
    assert summary.usage.wall_seconds == pytest.approx(3.3)
    assert summary.usage.cost_usd == pytest.approx(1.8)


def test_invalid_evidence_feedback_is_not_forwarded(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path, attempts=2)
    producer = _Producer()
    PromotionSupervisor(
        config,
        producer=producer,
        evaluator=_Evaluator(["INVALID", "REJECT"]),
    ).run()

    assert producer.feedbacks[0] is None
    assert producer.feedbacks[1] is not None
    assert producer.feedbacks[1]["outcome"] == "INVALID"
    assert "evaluator" not in producer.feedbacks[1]
    first_attempt = sorted((config.state_dir / "attempts").iterdir())[0]
    persisted_feedback = json.loads((first_attempt / "feedback.json").read_text())
    assert "evaluator" not in persisted_feedback


def test_initial_closed_feedback_is_forwarded_to_the_first_producer(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path, attempts=1)
    task_id = str(config.train_plan.payload["tasks"][0]["task_id"])
    initial_feedback = FailureFeedback(
        failure_codes=("workflow_completion",),
        failed_task_ids=(task_id,),
    )
    config = replace(config, initial_feedback=initial_feedback)
    producer = _Producer()

    PromotionSupervisor(
        config,
        producer=producer,
        evaluator=_Evaluator(["REJECT"]),
    ).run()

    assert producer.feedbacks == [initial_feedback.to_dict()]
    persisted_path = config.state_dir / "config.json"
    persisted = json.loads(persisted_path.read_text())
    assert persisted["initial_feedback"] == initial_feedback.to_dict()
    assert SupervisorConfig.load(persisted_path).initial_feedback == initial_feedback


def test_command_producer_view_cannot_carry_task_identity_or_verdict_reasons(
    tmp_path: Path,
) -> None:
    request = ProposalRequest(
        campaign_id="campaign",
        config_id="a" * 64,
        attempt_id="attempt",
        iteration=2,
        parent_sha="b" * 40,
        allowed_surfaces=("surface.txt",),
        attempt_dir=tmp_path / "attempt",
        worktree=tmp_path / "checkout",
        producer_dir=tmp_path / "producer",
        feedback={
            "schema": "crucible.supervisor-feedback.v3",
            "attempt_id": "previous",
            "outcome": "REJECT",
            "reasons": ["confidence_bound_not_positive"],
            "search_head_sha": "c" * 40,
            "evaluator": {
                "schema": "crucible.failure-feedback.v3",
                "failure_codes": ["workflow_completion"],
                "failed_task_ids": ["private-train-task"],
            },
        },
        remaining_budget={
            "wall_seconds": 60.0,
            "calls": 10,
            "tokens": 1_000,
            "cost_usd": 1.0,
        },
        objective="Preserve completed work.",
    )

    producer_view = request.to_producer_dict()
    serialized = json.dumps(producer_view)

    assert producer_view["request_id"] == request.request_id
    assert producer_view["feedback"] == {
        "schema": "crucible.failure-feedback.v3",
        "failure_codes": ["workflow_completion"],
    }
    assert producer_view["objective"] == "Preserve completed work."
    assert "private-train-task" not in serialized
    assert "confidence_bound_not_positive" not in serialized


def test_initial_feedback_cannot_name_a_task_outside_the_train_pack(
    tmp_path: Path,
) -> None:
    config, _baseline = _config(tmp_path, attempts=1)
    config = replace(
        config,
        initial_feedback=FailureFeedback(
            failure_codes=("workflow_completion",),
            failed_task_ids=("outside-task",),
        ),
    )

    with pytest.raises(SupervisorError, match="outside the train contract"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["REJECT"]),
        ).run()

    assert not config.state_dir.exists()


def test_invalid_parser_detail_is_operator_only(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path, attempts=2)
    producer = _Producer()
    oracle = "gold_action_toggle_everything"
    PromotionSupervisor(
        config,
        producer=producer,
        evaluator=_Evaluator(["REJECT", "REJECT"], feedback_code=oracle),
    ).run()

    assert producer.feedbacks[1] is not None
    assert producer.feedbacks[1]["reasons"] == ["invalid_attempt"]
    assert oracle not in json.dumps(producer.feedbacks[1])
    first_attempt = sorted((config.state_dir / "attempts").iterdir())[0]
    operator_error = json.loads((first_attempt / "error.json").read_text())
    assert oracle in operator_error["message"]


def test_uncommitted_producer_residue_cannot_contaminate_measurement(
    tmp_path: Path,
) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    evaluator = _Evaluator(["KEEP"])
    summary = PromotionSupervisor(
        config,
        producer=_Producer(dirty=True),
        evaluator=evaluator,
    ).run()

    assert summary.stop_reason == "max_attempts"
    assert summary.attempts == summary.keeps == 1
    assert summary.final_search_head_sha != baseline
    assert _git(config.repository, "rev-parse", "HEAD") == baseline
    assert evaluator.calls == 1


def test_candidate_cannot_change_production_outside_declared_surface(
    tmp_path: Path,
) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    evaluator = _Evaluator(["KEEP"])
    summary = PromotionSupervisor(
        config,
        producer=_Producer(extra_path=True),
        evaluator=evaluator,
    ).run()

    assert summary.invalids == 1
    assert summary.final_search_head_sha == baseline
    assert evaluator.calls == 0
    assert _ledger(config)[0]["reasons"] == ["invalid_attempt"]
    attempt = next((config.state_dir / "attempts").iterdir())
    assert (
        "outside the mutation surface"
        in json.loads((attempt / "error.json").read_text())["message"]
    )


def test_producer_git_replace_cannot_spoof_one_child_history(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    evaluator = _Evaluator(["KEEP"])
    summary = PromotionSupervisor(
        config,
        producer=_ReplaceSpoofProducer(),
        evaluator=evaluator,
    ).run()

    assert summary.invalids == 1
    assert summary.final_search_head_sha == baseline
    assert evaluator.calls == 0
    assert _ledger(config)[0]["reasons"] == ["invalid_attempt"]
    attempt = next((config.state_dir / "attempts").iterdir())
    assert "single-parent" in json.loads((attempt / "error.json").read_text())["message"]


def test_campaign_budget_overrun_blocks_an_evaluator_keep(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path, attempts=2, max_calls=3)
    summary = PromotionSupervisor(
        config,
        producer=_Producer(calls=1),
        evaluator=_Evaluator(["KEEP"], calls_per_arm=2),
    ).run()

    assert summary.attempts == 1
    assert summary.rejects == 1
    assert summary.stop_reason == "call_budget"
    assert summary.final_search_head_sha == baseline
    assert "campaign_budget_exceeded" in _ledger(config)[0]["reasons"]


def test_cached_evidence_usage_does_not_consume_the_current_campaign_budget(
    tmp_path: Path,
) -> None:
    config, baseline = _config(tmp_path, attempts=1, max_calls=2)
    summary = PromotionSupervisor(
        config,
        producer=_Producer(calls=1),
        evaluator=_MarginalEvaluator(["KEEP"], calls_per_arm=2),
    ).run()

    assert summary.keeps == 1
    assert summary.final_search_head_sha != baseline
    assert summary.usage.calls == 1
    assert summary.evidence_usage.calls == 5
    record = _ledger(config)[0]
    assert record["usage"]["calls"] == 5
    assert record["marginal_usage"]["calls"] == 1


def test_valid_candidate_patch_is_measured_once_across_recommits(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path, attempts=3)
    producer = _RepeatingProducer()
    evaluator = _Evaluator(["REJECT"])

    summary = PromotionSupervisor(config, producer=producer, evaluator=evaluator).run()

    assert summary.rejects == 3
    assert summary.invalids == 0
    assert summary.final_search_head_sha == baseline
    assert evaluator.calls == 1
    ledger = _ledger(config)
    assert ledger[0]["reasons"] != ["duplicate_candidate"]
    assert ledger[1]["reasons"] == ["duplicate_candidate"]
    assert ledger[2]["reasons"] == ["duplicate_candidate"]
    assert producer.feedbacks[2] is not None
    assert producer.feedbacks[2]["evaluator"]["failure_codes"] == ["duplicate_candidate"]
    refs = _git(
        config.repository,
        "for-each-ref",
        "--format=%(refname)",
        "refs/crucible/candidate-fingerprints/",
    ).splitlines()
    assert len(refs) == 1


def test_infrastructure_invalid_does_not_poison_candidate_dedup(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path, attempts=2, invalid_limit=3)
    evaluator = _Evaluator(["INVALID", "REJECT"])

    summary = PromotionSupervisor(
        config,
        producer=_RepeatingProducer(),
        evaluator=evaluator,
    ).run()

    assert summary.invalids == 1
    assert summary.rejects == 1
    assert evaluator.calls == 2


def test_candidate_fingerprint_changes_with_the_frozen_evaluator(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    surface = config.repository / "surface.txt"
    surface.write_text("same candidate\n", encoding="utf-8")
    _git(config.repository, "add", "surface.txt")
    _git(config.repository, "commit", "-qm", "candidate")
    candidate = _git(config.repository, "rev-parse", "HEAD")
    contract = config.train_plan.contract(
        champion_ref="refs/crucible/baselines/fingerprint/attempt",
        baseline_sha=baseline,
        candidate_sha=candidate,
        mutation=Mutation(surface="surface.txt", hypothesis="fixture"),
    )
    workspace = GitWorkspace(config.repository, "fingerprint-fixture")

    first = workspace.candidate_fingerprint(contract=contract, surfaces=("surface.txt",))
    revised = workspace.candidate_fingerprint(
        contract=replace(contract, evaluator_sha256="f" * 64),
        surfaces=("surface.txt",),
    )

    assert first != revised


def test_postflight_failure_still_charges_attested_evaluator_usage(tmp_path: Path) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    summary = PromotionSupervisor(
        config,
        producer=_Producer(calls=1),
        evaluator=_Evaluator(["KEEP"], calls_per_arm=2, dirty_after_response=True),
    ).run()

    assert summary.invalids == 1
    assert summary.final_search_head_sha == baseline
    assert summary.usage.calls == 5
    assert summary.usage.tokens == 210
    assert summary.usage.cost_usd == pytest.approx(0.6)


def test_command_producer_preserves_structured_failure_detail(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path, attempts=1)
    producer = tmp_path / "failing-producer.py"
    producer.write_text(
        textwrap.dedent(
            """
            import json
            import os
            from pathlib import Path

            Path(os.environ["CRUCIBLE_ERROR_OUTPUT"]).write_text(json.dumps({
                "schema": "crucible.producer-error.v1",
                "error_type": "ProducerError",
                "message": "subscription quota exhausted",
            }))
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    config = replace(config, producer_command=(sys.executable, str(producer)))

    summary = PromotionSupervisor(config).run()

    assert summary.invalids == 1
    attempt = next((config.state_dir / "attempts").iterdir())
    error = json.loads((attempt / "error.json").read_text(encoding="utf-8"))
    assert error["message"] == "producer failed: subscription quota exhausted"


def test_existing_state_directory_is_never_reused(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    config.state_dir.mkdir()

    with pytest.raises(SupervisorError, match="fresh campaign"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["KEEP"]),
        ).run()


def test_unknown_initial_head_is_rejected_before_state_creation(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    config = replace(config, initial_search_head_sha="f" * 40)

    with pytest.raises(SupervisorError, match="does not resolve to a commit"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["KEEP"]),
        ).run()

    assert not config.state_dir.exists()
    assert not (config.repository / ".git/refs/crucible/search/fixture-campaign").exists()


@pytest.mark.parametrize("field", ["producer_environment", "evaluator_environment"])
def test_config_rejects_adaptive_or_sealed_environment_for_train_roles(
    tmp_path: Path,
    field: str,
) -> None:
    config, _baseline = _config(tmp_path)
    path = tmp_path / "supervisor.json"
    payload = config.to_dict()
    payload.pop("config_id")
    payload[field] = ["GEODE_HELD_OUT_BENCH"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SupervisorError, match="sealed state"):
        SupervisorConfig.load(path)


def test_config_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    path = tmp_path / "supervisor.json"
    payload = config.to_dict()
    payload["max_attemps"] = 10
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SupervisorError, match="unknown fields: max_attemps"):
        SupervisorConfig.load(path)


def test_config_id_binds_the_optional_search_objective(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    path = tmp_path / "supervisor.json"
    payload = config.to_dict()
    payload.pop("config_id")
    payload["search"] = {"objective": "Preserve completed work."}
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = SupervisorConfig.load(path)

    assert loaded.producer_objective == "Preserve completed work."
    assert loaded.config_id != config.config_id


def test_config_rejects_unknown_search_fields(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    path = tmp_path / "supervisor.json"
    payload = config.to_dict()
    payload.pop("config_id")
    payload["search"] = {"objective": "Preserve work.", "temperature": 1.0}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SupervisorError, match="search has unknown fields: temperature"):
        SupervisorConfig.load(path)


def test_failed_keep_cas_leaves_a_record_but_no_receipt_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, baseline = _config(tmp_path, attempts=1)

    def fail_reconcile(
        _repository: Path,
        *,
        intent_path: Path,
        receipt_path: Path,
    ) -> None:
        assert intent_path.name == "search-ref.intent.json"
        assert receipt_path.name == "search-ref.receipt.json"
        raise SupervisorError("fixture CAS conflict")

    monkeypatch.setattr("plugins.crucible.supervisor.reconcile_ref_update", fail_reconcile)
    with pytest.raises(SupervisorError, match="CAS conflict"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["KEEP"]),
        ).run()

    attempt = next((config.state_dir / "attempts").iterdir())
    assert not (config.state_dir / "ledger.jsonl").exists()
    record = json.loads((attempt / "record.json").read_text())
    intent = json.loads((attempt / "search-ref.intent.json").read_text())
    assert record["outcome"] == "KEEP"
    assert intent["subject_id"] == record["record_id"]
    assert not (attempt / "search-ref.receipt.json").exists()
    assert _git(config.repository, "rev-parse", "refs/crucible/search/fixture-campaign") == baseline


def test_packaged_cli_runs_isolated_producer_and_evaluator_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, baseline = _config(tmp_path, attempts=1)
    child_pid_path = tmp_path / "producer-child.pid"
    monkeypatch.setenv("CRUCIBLE_TEST_CHILD_PID", str(child_pid_path))
    producer = tmp_path / "producer.py"
    producer.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import subprocess
            import sys
            from pathlib import Path

            request = json.loads(Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"]).read_text())
            assert "attempt_dir" not in request
            assert "worktree" not in request
            checkout = Path.cwd()
            assert subprocess.run(
                ["git", "remote"],
                cwd=checkout,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip() == ""
            (checkout.parent / "evaluation-response.json").write_text(
                "producer poison"
            )
            poison = checkout / ".venv" / "bin" / "python"
            poison.parent.mkdir(parents=True)
            poison.write_text("candidate controlled")
            child = subprocess.Popen([
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ])
            Path(os.environ["CRUCIBLE_TEST_CHILD_PID"]).write_text(str(child.pid))
            surface = checkout / "surface.txt"
            surface.write_text("candidate\\n", encoding="utf-8")
            subprocess.run(["git", "add", "surface.txt"], cwd=surface.parent, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "candidate"], cwd=surface.parent, check=True
            )
            candidate = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=surface.parent,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            payload = {
                "schema": "crucible.candidate.v2",
                "attempt_id": request["attempt_id"],
                "request_id": request["request_id"],
                "parent_sha": request["parent_sha"],
                "candidate_sha": candidate,
                "mutation": {
                    "surface": "surface.txt",
                    "hypothesis": "fixture improvement",
                },
                "usage": {
                    "wall_seconds": 0.1,
                    "calls": 1,
                    "tokens": 10,
                    "cost_usd": 0.1,
                },
            }
            Path(os.environ["CRUCIBLE_CANDIDATE_OUTPUT"]).write_text(json.dumps(payload))
            """
        ),
        encoding="utf-8",
    )
    config = replace(
        config,
        producer_command=(sys.executable, str(producer)),
        producer_environment=("CRUCIBLE_TEST_CHILD_PID",),
    )
    config_path = tmp_path / "supervisor.json"
    config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")

    assert crucible_main(["loop", str(config_path)]) == 0
    summary = json.loads((config.state_dir / "summary.json").read_text())
    assert summary["final_search_head_sha"] != baseline
    assert summary["final_search_head_sha"] == _git(
        config.repository, "rev-parse", summary["search_ref"]
    )
    assert _git(config.repository, "rev-parse", "HEAD") == baseline
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_failure_feedback_v3_carries_bounded_train_task_identity() -> None:
    feedback = FailureFeedback.from_mapping(
        {
            "schema": "crucible.failure-feedback.v3",
            "failure_codes": ["required_user_action", "state_correctness"],
            "failed_task_ids": ["task-3", "task-9"],
        }
    )
    assert feedback.failed_task_ids == ("task-3", "task-9")
    assert feedback.failure_codes == ("required_user_action", "state_correctness")


def test_failure_feedback_v3_accepts_long_ids_owned_by_the_contract() -> None:
    task_id = "[workflow]" + "step|" * 100

    feedback = FailureFeedback.from_mapping(
        {
            "schema": "crucible.failure-feedback.v3",
            "failure_codes": ["workflow_completion"],
            "failed_task_ids": [task_id],
        }
    )

    assert feedback.failed_task_ids == (task_id,)


def test_failure_feedback_v3_rejects_retired_v2_schema() -> None:
    with pytest.raises(SupervisorError, match=r"crucible\.failure-feedback\.v3"):
        FailureFeedback.from_mapping(
            {
                "schema": "crucible.failure-feedback.v2",
                "failure_codes": [],
            }
        )


def test_failure_feedback_v3_enforces_transport_caps() -> None:
    with pytest.raises(SupervisorError, match="failed_task_ids"):
        FailureFeedback.from_mapping(
            {
                "schema": "crucible.failure-feedback.v3",
                "failure_codes": [],
                "failed_task_ids": [f"task-{i}" for i in range(65)],
            }
        )
    with pytest.raises(SupervisorError, match="failed_task_ids"):
        FailureFeedback.from_mapping(
            {
                "schema": "crucible.failure-feedback.v3",
                "failure_codes": [],
                "failed_task_ids": ["x" * (64 * 1024 + 1)],
            }
        )


@pytest.mark.parametrize("field", ["summary", "trajectory_excerpts"])
def test_failure_feedback_v3_rejects_free_text_oracle_channels(field: str) -> None:
    with pytest.raises(SupervisorError, match=f"unknown fields: {field}"):
        FailureFeedback.from_mapping(
            {
                "schema": "crucible.failure-feedback.v3",
                "failure_codes": [],
                field: "oracle text",
            }
        )


def test_failure_feedback_v3_rejects_task_ids_outside_contract(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    contract = config.train_plan.contract(
        champion_ref="refs/crucible/test",
        baseline_sha="1" * 40,
        candidate_sha="2" * 40,
        mutation=Mutation(surface="surface.txt", hypothesis="fixture"),
    )
    feedback = FailureFeedback(
        failure_codes=("quality",),
        failed_task_ids=("outside-pack",),
    )
    with pytest.raises(SupervisorError, match="outside the train contract"):
        feedback.validate_for(contract)
