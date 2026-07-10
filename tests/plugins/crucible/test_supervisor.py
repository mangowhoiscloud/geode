import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import (
    ExperimentContract,
    Mutation,
    content_sha256,
    load_contract,
    task_pack_sha256,
    tracked_tree_sha256,
)
from plugins.crucible.evidence import EvidenceEnvelope, ResourceUsage
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
)

VerdictName = Literal["KEEP", "REJECT", "INVALID"]

EVALUATOR_SCRIPT = "#!/usr/bin/env python3\n" + textwrap.dedent(
    """
    import hashlib
    import json
    import os
    from pathlib import Path

    request = json.loads(Path(os.environ["CRUCIBLE_PROPOSAL_REQUEST"]).read_text())
    candidate = json.loads(Path(os.environ["CRUCIBLE_CANDIDATE"]).read_text())
    contract = json.loads(Path(os.environ["CRUCIBLE_CONTRACT"]).read_text())

    def evidence(arm, reward, raw_hash):
        revision = contract[f"{arm}_sha"]
        assay_config = json.dumps(
            contract["assay_config"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return {
            "schema": "crucible.evidence.v1",
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
                for task_id in contract["task_ids"]
            ],
        }

    output = Path(os.environ["CRUCIBLE_EVALUATION_OUTPUT"])
    baseline_raw_path = output.parent / "baseline.raw.json"
    candidate_raw_path = output.parent / "candidate.raw.json"
    baseline_raw_path.write_text('{"arm":"baseline"}')
    candidate_raw_path.write_text('{"arm":"candidate"}')
    baseline_raw_hash = hashlib.sha256(baseline_raw_path.read_bytes()).hexdigest()
    candidate_raw_hash = hashlib.sha256(candidate_raw_path.read_bytes()).hexdigest()
    baseline_path = output.parent / "baseline.json"
    candidate_path = output.parent / "candidate-evidence.json"
    baseline_path.write_text(json.dumps(evidence("baseline", 0.2, baseline_raw_hash)))
    candidate_path.write_text(json.dumps(evidence("candidate", 0.9, candidate_raw_hash)))
    payload = {
        "schema": "crucible.train-evaluation.v2",
        "attempt_id": request["attempt_id"],
        "request_id": request["request_id"],
        "proposal_id": candidate["proposal_id"],
        "baseline": baseline_path.name,
        "candidate": candidate_path.name,
        "baseline_raw": baseline_raw_path.name,
        "candidate_raw": candidate_raw_path.name,
        "feedback": {
            "schema": "crucible.failure-feedback.v1",
            "summary": "fixture complete",
            "failure_classes": [],
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
    task_ids = ["task-1", "task-2", "task-3", "task-4"]
    return TrainPlan.from_mapping(
        {
            "schema": "crucible.train-plan.v1",
            "name": "supervisor-fixture",
            "evaluator_sha256": content_sha256(repo, ["evaluator.py"]),
            "harness_sha256": tracked_tree_sha256(harness),
            "task_pack_sha256": task_pack_sha256(task_ids),
            "agent_route": "fixture-agent",
            "user_route": "fixture-user",
            "task_ids": task_ids,
            "trials_per_task": 1,
            "assay_config": {"schema": "fixture.v1"},
            "evaluator_paths": ["evaluator.py"],
            "promotion": {
                "method": "paired_bootstrap.v1",
                "primary_metric": "reward",
                "minimum_improvement": 0.1,
                "minimum_candidate_mean": 0.7,
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

    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal:
        assert timeout > 0
        assert _git(request.worktree, "remote") == ""
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


class _Evaluator:
    def __init__(self, verdicts: list[VerdictName], *, calls_per_arm: int = 1) -> None:
        self.verdicts = verdicts
        self.calls_per_arm = calls_per_arm
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
            "schema": "crucible.evidence.v1",
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
        response = evaluation_dir / "response.json"
        response.write_text(
            json.dumps(
                {
                    "schema": "crucible.train-evaluation.v2",
                    "attempt_id": request.attempt_id,
                    "request_id": request.request_id,
                    "proposal_id": proposal.proposal_id,
                    "baseline": baseline_path.name,
                    "candidate": candidate_path.name,
                    "baseline_raw": baseline_raw.name,
                    "candidate_raw": candidate_raw.name,
                    "feedback": FailureFeedback(
                        summary=f"fixture {verdict.lower()}",
                        failure_classes=(verdict.lower(),),
                    ).to_dict(),
                }
            ),
            encoding="utf-8",
        )
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
    assert _git(config.repository, "rev-parse", first_contract.champion_ref) == baseline
    assert producer.worktree_roots
    assert all(not path.exists() for path in producer.worktree_roots)
    assert [row["outcome"] for row in ledger] == ["KEEP", "REJECT", "INVALID"]
    assert ledger[1]["previous_record_id"] == ledger[0]["record_id"]
    assert ledger[1]["search_head_after"] == first_keep
    assert summary.usage.calls == 9
    assert summary.usage.tokens == 630
    assert summary.usage.wall_seconds == pytest.approx(3.3)
    assert summary.usage.cost_usd == pytest.approx(1.8)


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
    assert "outside the mutation surface" in str(_ledger(config)[0]["reasons"])


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
    assert "single-parent" in str(_ledger(config)[0]["reasons"])


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


def test_existing_state_directory_is_never_reused(tmp_path: Path) -> None:
    config, _baseline = _config(tmp_path)
    config.state_dir.mkdir()

    with pytest.raises(SupervisorError, match="fresh campaign"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["KEEP"]),
        ).run()


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


def test_failed_keep_cas_does_not_commit_a_keep_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, baseline = _config(tmp_path, attempts=1)

    def fail_advance(
        _workspace: GitWorkspace,
        _candidate_sha: str,
        _parent_sha: str,
    ) -> None:
        raise SupervisorError("fixture CAS conflict")

    monkeypatch.setattr(GitWorkspace, "advance", fail_advance)
    with pytest.raises(SupervisorError, match="CAS conflict"):
        PromotionSupervisor(
            config,
            producer=_Producer(),
            evaluator=_Evaluator(["KEEP"]),
        ).run()

    attempt = next((config.state_dir / "attempts").iterdir())
    assert not (config.state_dir / "ledger.jsonl").exists()
    assert not (attempt / "record.json").exists()
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
            assert subprocess.run(
                ["git", "remote"],
                cwd=request["worktree"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip() == ""
            (Path(request["worktree"]).parent / "evaluation-response.json").write_text(
                "producer poison"
            )
            child = subprocess.Popen([
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ])
            Path(os.environ["CRUCIBLE_TEST_CHILD_PID"]).write_text(str(child.pid))
            surface = Path(request["worktree"]) / "surface.txt"
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
