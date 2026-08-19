import hashlib
import itertools
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from geode_product.benchmark_harness.tau2_turn_supervisor import (
    _pre_execution_retry_telemetry,
)
from geode_product.crucible.contract import (
    ContractError,
    ExperimentContract,
    TaskUnit,
    task_pack_sha256,
)
from geode_product.crucible.evidence import EvidenceEnvelope, ResourceUsage
from geode_product.crucible.promotion import SCREENING_FAILURE, decide, promotion_reachability
from geode_product.crucible.row_cache import harvest_arm_rows
from geode_product.crucible.runtime_receipt import SharedRuntimeDeadline, runtime_artifact_bindings
from geode_product.crucible.tau2_live import (
    Tau2InfrastructureError,
    _evaluation_wall_seconds,
    _index_simulations,
    _infrastructure_abort_snapshot,
    _run_arm,
    _run_arm_with_deadline,
    _run_tau2_command,
    _runtime_status_for_returned_arms,
    _RuntimeReceiptWriter,
    _train_evaluation_response,
    _write_screened_arm,
    _write_skipped_arm,
    tau2_command,
    tau2_failure_feedback,
    tau2_trace_checks,
)
from geode_product.crucible.verifiers.tau2 import TAU2_ADAPTER, _verify_snapshot

TASKS = (
    TaskUnit("task-1", "1" * 64, "a" * 64),
    TaskUnit("task-2", "2" * 64, "b" * 64),
)
TEST_TASKS = (
    TaskUnit("test-1", "3" * 64, "c" * 64),
    TaskUnit("test-2", "4" * 64, "d" * 64),
)


def test_tau2_turn_projects_pre_execution_retry_identity() -> None:
    loop = SimpleNamespace(pre_execution_retry_errors=("APITimeoutError", "EmptyModelOutputError"))

    assert _pre_execution_retry_telemetry(loop) == {
        "geode_pre_execution_retry_count": 2,
        "geode_pre_execution_retry_errors": [
            "APITimeoutError",
            "EmptyModelOutputError",
        ],
    }


def test_run_tau2_command_stops_on_finalized_infrastructure_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "simulations": [
                    {
                        "termination_reason": "infrastructure_error",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class Process:
        pid = 12345
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    process = Process()
    stopped: list[int] = []

    def stop(_process: Process) -> int:
        stopped.append(_process.pid)
        _process.returncode = -15
        return -15

    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.subprocess.Popen", lambda *a, **kw: process
    )
    monkeypatch.setattr("geode_product.crucible.tau2_live._terminate_process_group", stop)

    completed, contaminated = _run_tau2_command(
        ["tau2-fixture"],
        cwd=tmp_path,
        env={},
        timeout=10.0,
        results_path=results,
    )

    assert contaminated is True
    assert completed.returncode == -15
    assert stopped == [12345]


def test_run_tau2_command_refuses_to_launch_after_absolute_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("expired work must not launch"),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run_tau2_command(
            ["tau2-fixture"],
            cwd=tmp_path,
            env={},
            deadline_seconds=0.0,
            results_path=tmp_path / "results.json",
        )


def test_command_evaluator_entrypoint_uses_the_frozen_uv_runtime() -> None:
    repository = Path(__file__).parents[3]

    assert (
        repository.joinpath("scripts/eval/crucible_tau2_evaluator.py")
        .read_text(encoding="utf-8")
        .splitlines()[0]
        == "#!/usr/bin/env -S uv run --frozen --no-dev python"
    )


def test_evaluation_wall_intersects_live_remainder_with_frozen_contract() -> None:
    contract = _contract()

    assert _evaluation_wall_seconds(contract, 1_200.0) == 1_200.0
    assert _evaluation_wall_seconds(contract, 7_200.0) == 3_600.0
    with pytest.raises(ContractError, match="valid actual remaining"):
        _evaluation_wall_seconds(contract, None)
    with pytest.raises(ContractError, match="no remaining"):
        _evaluation_wall_seconds(contract, 0.0)


def test_signal_exit_finalizes_the_active_arm_for_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    deadline = SharedRuntimeDeadline(contract, 100.0)
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live._run_arm",
        lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(143)),
    )

    with pytest.raises(SystemExit, match="143"):
        _run_arm_with_deadline(
            deadline,
            contract,
            arm="baseline",
            checkout=tmp_path,
            harness_root=tmp_path,
            contract_path=tmp_path / "contract.json",
            output_dir=tmp_path,
            run_id="signal-fixture",
        )

    receipt = deadline.payload("operator_invalid")
    assert receipt["arms"][0]["outcome"] == "invalid"


def test_timeout_receipt_write_failure_is_not_masked_by_a_second_arm_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    deadline = SharedRuntimeDeadline(contract, 100.0)

    def timeout(*args: object, on_timeout: object, **kwargs: object) -> None:
        assert callable(on_timeout)
        on_timeout()

    monkeypatch.setattr("geode_product.crucible.tau2_live._run_arm", timeout)

    with pytest.raises(OSError, match="receipt write failed"):
        _run_arm_with_deadline(
            deadline,
            contract,
            arm="baseline",
            checkout=tmp_path,
            harness_root=tmp_path,
            contract_path=tmp_path / "contract.json",
            output_dir=tmp_path,
            run_id="receipt-write-failure",
            on_timeout=lambda: (_ for _ in ()).throw(OSError("receipt write failed")),
        )

    receipt = deadline.payload("operator_invalid")
    assert receipt["arms"][0]["outcome"] == "right_censored"


def test_timeout_receipt_is_persisted_before_outer_checkout_cleanup(
    tmp_path: Path,
) -> None:
    contract = _contract()
    deadline = SharedRuntimeDeadline(contract, 100.0)
    timer = deadline.begin_arm("baseline")
    deadline.finish_arm(timer, "right_censored")
    receipt_path = tmp_path / "runtime.receipt.json"
    writer = _RuntimeReceiptWriter(deadline, receipt_path, lambda: None)
    cleanup_observed: list[bool] = []

    @contextmanager
    def checkout_scope() -> Iterator[None]:
        try:
            yield
        finally:
            cleanup_observed.append(receipt_path.is_file())

    with (
        pytest.raises(TimeoutError, match="fixture timeout"),
        checkout_scope(),
        writer.preserve_failures_before_cleanup(),
    ):
        raise TimeoutError("fixture timeout")

    assert cleanup_observed == [True]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["observation"]["status"] == "right_censored"


def test_timeout_receipt_is_written_before_arm_returns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    deadline = SharedRuntimeDeadline(contract, 100.0)
    output = tmp_path / "output"
    output.mkdir()
    receipt_path = output / "runtime.receipt.json"
    writer = _RuntimeReceiptWriter(deadline, receipt_path, lambda: None)
    monkeypatch.setenv("CRUCIBLE_ROW_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live._run_tau2_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=["tau2-fixture"], timeout=1.0)
        ),
    )

    with pytest.raises(TimeoutError, match="arm timed out"):
        _run_arm_with_deadline(
            deadline,
            contract,
            arm="baseline",
            checkout=tmp_path,
            harness_root=tmp_path / "harness",
            contract_path=tmp_path / "contract.json",
            output_dir=output,
            run_id="timeout-before-salvage",
            on_timeout=lambda: writer.write(
                "right_censored",
                censoring_reason="shared_experiment_deadline",
            ),
        )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["observation"]["status"] == "right_censored"


def test_returned_invalid_receipt_is_persisted_before_checkout_cleanup(
    tmp_path: Path,
) -> None:
    contract = _contract()
    baseline = _arm_evidence(contract, arm="baseline", invalid=True, raw_hash="a" * 64)
    candidate = _arm_evidence(contract, arm="candidate", invalid=True, raw_hash="b" * 64)
    deadline = SharedRuntimeDeadline(contract, 100.0)
    baseline_clock = deadline.begin_arm("baseline")
    deadline.finish_arm(baseline_clock, "invalid")
    candidate_clock = deadline.begin_arm("candidate")
    deadline.finish_arm(candidate_clock, "invalid")
    receipt_path = tmp_path / "runtime.receipt.json"
    writer = _RuntimeReceiptWriter(
        deadline,
        receipt_path,
        lambda: runtime_artifact_bindings(baseline, candidate),
    )
    cleanup_observed: list[bool] = []

    @contextmanager
    def checkout_scope() -> Iterator[None]:
        try:
            yield
        finally:
            cleanup_observed.append(receipt_path.is_file())

    with checkout_scope(), writer.preserve_failures_before_cleanup():
        status = _runtime_status_for_returned_arms(baseline, candidate)
        if status == "infrastructure_invalid":
            writer.write(status)

    assert cleanup_observed == [True]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["observation"]["status"] == "infrastructure_invalid"


def test_infrastructure_abort_snapshot_is_accepted_by_frozen_verifier() -> None:
    contract = _contract()
    raw_sha256 = "a" * 64

    status, failure_class = _verify_snapshot(
        contract,
        arm="baseline",
        raw_sha256=raw_sha256,
        snapshot=_infrastructure_abort_snapshot(
            contract,
            arm="baseline",
            raw_sha256=raw_sha256,
        ),
    )

    assert status == "invalid"
    assert failure_class == "tau2_infrastructure_error"


def test_command_evaluator_emits_paths_relative_to_response_directory(
    tmp_path: Path,
) -> None:
    evaluation_dir = tmp_path / "attempt" / "evaluation"
    response = _train_evaluation_response(
        {"attempt_id": "0001-fixture", "request_id": "request-id"},
        {"proposal_id": "proposal-id"},
        output_dir=evaluation_dir,
        baseline_raw=evaluation_dir / "baseline.raw.json",
        candidate_raw=evaluation_dir / "candidate.raw.json",
        runtime_receipt=evaluation_dir / "runtime.receipt.json",
        marginal_usage=ResourceUsage(0.25, 2, 300, 0.3),
        feedback=None,
    )

    assert {
        field: response[field]
        for field in (
            "baseline",
            "candidate",
            "baseline_raw",
            "candidate_raw",
            "runtime_receipt",
        )
    } == {
        "baseline": "baseline.evidence.json",
        "candidate": "candidate.evidence.json",
        "baseline_raw": "baseline.raw.json",
        "candidate_raw": "candidate.raw.json",
        "runtime_receipt": "runtime.receipt.json",
    }
    assert response["marginal_usage"] == ResourceUsage(0.25, 2, 300, 0.3).to_dict()


def test_skipped_candidate_is_closed_zero_call_infrastructure_evidence(tmp_path: Path) -> None:
    contract = _contract()
    trigger = _arm_evidence(
        contract,
        arm="baseline",
        invalid=True,
        raw_hash="a" * 64,
    )

    candidate, raw_path, marginal_usage = _write_skipped_arm(
        contract,
        arm="candidate",
        output_dir=tmp_path,
        trigger=trigger,
    )

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw["schema"] == "crucible.skipped-arm.v1"
    assert raw["triggering_evidence_id"] == trigger.evidence_id
    assert candidate.execution_status == "invalid"
    assert candidate.failure_class == "paired_arm_skipped"
    assert candidate.usage == ResourceUsage(0.0, 0, 0, 0.0)
    assert marginal_usage.calls == 0
    assert marginal_usage.tokens == 0
    assert marginal_usage.cost_usd == 0.0
    assert marginal_usage.wall_seconds >= 0.0
    assert [row.pair_id for row in candidate.rows] == [
        (task_id, 0) for task_id in contract.task_ids
    ]
    assert all(row.status == "infrastructure_error" for row in candidate.rows)
    verdict = decide(contract, trigger, candidate)
    assert verdict.verdict == "INVALID"
    assert verdict.reasons == ("infrastructure_contamination",)
    assert verdict.pair_count == 0


def test_unreachable_candidate_is_a_zero_call_screening_reject(tmp_path: Path) -> None:
    contract = _contract()
    baseline = _arm_evidence(
        contract,
        arm="baseline",
        invalid=False,
        raw_hash="a" * 64,
    )
    reachability = promotion_reachability(contract, baseline, metric_ceiling=1.0)

    candidate, raw_path, marginal_usage = _write_screened_arm(
        contract,
        output_dir=tmp_path,
        baseline=baseline,
        reachability=reachability,
    )
    verdict = decide(contract, baseline, candidate)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    assert reachability.reachable is False
    assert raw["schema"] == "crucible.screened-arm.v1"
    assert raw["reason"] == SCREENING_FAILURE
    assert candidate.usage == ResourceUsage(0.0, 0, 0, 0.0)
    assert marginal_usage.calls == 0
    assert marginal_usage.tokens == 0
    assert marginal_usage.cost_usd == 0.0
    assert marginal_usage.wall_seconds >= 0.0
    assert verdict.verdict == "REJECT"
    assert verdict.reasons == (SCREENING_FAILURE,)
    assert verdict.pair_count == 0
    assert verdict.promotion_authority == "none"


def _contract() -> ExperimentContract:
    assay = {
        "schema": "crucible.tau2-assay.v1",
        "domain": "telecom",
        "task_set_name": None,
        "task_split_name": "base",
        "num_trials": 1,
        "max_concurrency": 1,
        "max_steps": 24,
        "max_errors": 1,
        "max_retries": 0,
        "timeout": 600.0,
        "seed": 300,
        "agent": {
            "implementation": "geode_agent",
            "route": "openai-subscription-gpt-5.4-high",
            "model": "gpt-5.4",
            "provider": "openai",
            "source": "subscription",
            "effort": "high",
            "time_budget_s": 180.0,
            "max_tokens": 32768,
            "max_rounds": 0,
            "cognitive_reflection": False,
            "codex_output_replay": True,
            "tool_search_defer": True,
        },
        "user": {
            "implementation": "crucible_user",
            "runtime_owner": "evaluator",
            "route": "evaluator-openai-subscription-gpt-5.4-high",
            "llm": "gpt-5.4",
            "llm_args": {"temperature": 0.0},
            "provider": "openai",
            "source": "subscription",
            "effort": "high",
            "time_budget_s": 120.0,
            "max_tokens": 8192,
            "max_rounds": 0,
        },
        "retrieval": {"config": None, "kwargs": {}},
    }
    return ExperimentContract.from_mapping(
        {
            "schema": "crucible.experiment.v3",
            "name": "live-tau2-fixture",
            "stage": "train",
            "champion_ref": "refs/crucible/baselines/fixture/1",
            "baseline_sha": "1" * 40,
            "candidate_sha": "2" * 40,
            "evaluator_sha256": "c" * 64,
            "harness_sha256": "d" * 64,
            "task_pack_sha256": task_pack_sha256(TASKS, 1),
            "agent_route": "openai-subscription-gpt-5.4-high",
            "user_route": "evaluator-openai-subscription-gpt-5.4-high",
            "tasks": [task.to_dict() for task in TASKS],
            "trials_per_task": 1,
            "assay_config": assay,
            "mutations": [
                {
                    "surface": "geode_product/benchmark_harness/tau2_agent_policy.md",
                    "hypothesis": "compress tool workflows",
                }
            ],
            "evaluator_paths": list(TAU2_ADAPTER.required_evaluator_paths),
            "promotion": {
                "method": "paired_bootstrap.v2",
                "primary_metric": "reward",
                "materiality_pp": 0.1,
                "minimum_candidate_mean": 0.5,
                "minimum_tasks": 2,
                "minimum_families": 2,
                "confidence_level": 0.885,
                "bootstrap_samples": 1000,
            },
            "budget": {
                "max_wall_seconds": 3600.0,
                "max_calls": 1000,
                "max_tokens": 1_000_000,
                "max_cost_usd": 100.0,
                "max_changed_lines": 40,
            },
            "vetoes": [
                "budget",
                "infra_clean",
                "safety",
                "task_coverage",
                "tool_contract",
            ],
        }
    )


def _contract_with_trials(trials: int) -> ExperimentContract:
    payload = _contract().to_dict()
    payload.pop("contract_id")
    assay = dict(payload["assay_config"])
    assay["num_trials"] = trials
    payload.update(
        {
            "name": f"live-tau2-fixture-k{trials}",
            "trials_per_task": trials,
            "task_pack_sha256": task_pack_sha256(TASKS, trials),
            "assay_config": assay,
        }
    )
    return ExperimentContract.from_mapping(payload)


def _test_contract(parent: ExperimentContract) -> ExperimentContract:
    payload = parent.to_dict()
    payload.pop("contract_id")
    payload.update(
        {
            "name": "live-tau2-sealed-fixture",
            "stage": "test",
            "parent_contract_id": parent.contract_id,
            "tasks": [task.to_dict() for task in TEST_TASKS],
            "task_pack_sha256": task_pack_sha256(TEST_TASKS, 1),
        }
    )
    return ExperimentContract.from_mapping(payload)


def _arm_evidence(
    contract: ExperimentContract,
    *,
    arm: str,
    invalid: bool,
    raw_hash: str,
) -> EvidenceEnvelope:
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    return EvidenceEnvelope.from_mapping(
        {
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
            "failure_class": "route_contamination" if invalid else None,
            "usage": ResourceUsage(1.0, 1, 10, 0.0).to_dict(),
            "rows": [
                {
                    "task_id": task_id,
                    "trial": 0,
                    "status": "infrastructure_error" if invalid else "completed",
                    "termination_reason": "empty_output" if invalid else "done",
                    "failure_class": "route_contamination" if invalid else None,
                    "metrics": {} if invalid else {"reward": 1.0},
                    "checks": {} if invalid else {"safety": True, "tool_contract": True},
                }
                for task_id in contract.task_ids
            ],
        }
    )


def _prepared_arm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    invalid: bool,
) -> tuple[ExperimentContract, Path, Path, Path]:
    contract = _contract()
    checkout = tmp_path / "checkout"
    harness = tmp_path / "harness"
    output = tmp_path / "output"
    checkout.mkdir()
    raw = harness / "data" / "simulations" / "fixture-run" / "results.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}\n", encoding="utf-8")
    snapshot = output / "snapshots" / "fixture-run.snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}\n", encoding="utf-8")
    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=invalid,
        raw_hash=hashlib.sha256(raw.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live._run_tau2_command",
        lambda *args, **kwargs: (
            subprocess.CompletedProcess(args=[], returncode=1),
            False,
        ),
    )
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.tau2_resource_usage_floor",
        lambda raw: ResourceUsage(1.0, 1, 10, 0.0),
    )
    monkeypatch.setattr("geode_product.crucible.tau2_live.tau2_trace_checks", lambda raw: {})
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.normalize_tau2_results",
        lambda *args, **kwargs: evidence,
    )
    return contract, checkout, harness, output


def test_run_arm_preserves_finalized_invalid_evidence_after_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=True,
    )

    evidence, raw_path, _marginal_usage, measurement_source = _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id="fixture-run",
        timeout=10.0,
    )

    assert evidence.execution_status == "invalid"
    assert measurement_source == "fresh"
    assert raw_path == output / "baseline.raw.json"
    assert (output / "baseline.evidence.json").is_file()


def test_run_arm_emits_invalid_evidence_after_infrastructure_fail_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=True,
    )
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live._run_tau2_command",
        lambda *args, **kwargs: (
            subprocess.CompletedProcess(args=[], returncode=-15),
            True,
        ),
    )

    evidence, raw_path, marginal_usage, measurement_source = _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id="fixture-run",
        timeout=10.0,
    )

    snapshot = json.loads(
        (output / "snapshots" / "fixture-run.aborted.snapshot.json").read_text(encoding="utf-8")
    )
    assert evidence.execution_status == "invalid"
    assert measurement_source == "fresh"
    assert raw_path == output / "baseline.raw.json"
    assert marginal_usage.calls == 1
    assert marginal_usage.tokens == 10
    assert snapshot["execution_status"] == "invalid"
    assert snapshot["failure_class"] == "tau2_infrastructure_error"
    assert snapshot["raw_artifact_sha256"] == hashlib.sha256(raw_path.read_bytes()).hexdigest()


def test_run_arm_accounts_for_actual_subprocess_elapsed_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=True,
    )
    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=True,
        raw_hash="a" * 64,
    )
    captured: dict[str, ResourceUsage] = {}

    def normalize(*args: object, **kwargs: object) -> EvidenceEnvelope:
        usage = kwargs["usage"]
        assert isinstance(usage, ResourceUsage)
        captured["usage"] = usage
        return evidence

    # An inexhaustible clock: the first read anchors at 10.0 and every later
    # read returns 13.5, so the measured delta stays 3.5 regardless of how
    # many times the runner consults the clock. A finite two-value iterator
    # here raised StopIteration under xdist+coverage load (release-train CI,
    # 2026-07-13) whenever an extra monotonic() call slipped in.
    moments = itertools.chain((10.0,), itertools.repeat(13.5))
    monkeypatch.setattr("geode_product.crucible.tau2_live.time.monotonic", lambda: next(moments))
    monkeypatch.setattr("geode_product.crucible.tau2_live.normalize_tau2_results", normalize)

    _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id="fixture-run",
        timeout=10.0,
    )

    assert captured["usage"] == ResourceUsage(3.5, 1, 10, 0.0)


def test_run_arm_rejects_nonzero_exit_with_complete_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, checkout, harness, output = _prepared_arm(
        tmp_path,
        monkeypatch,
        invalid=False,
    )

    with pytest.raises(Tau2InfrastructureError, match="exited with status 1"):
        _run_arm(
            contract,
            arm="baseline",
            checkout=checkout,
            harness_root=harness,
            contract_path=tmp_path / "contract.json",
            output_dir=output,
            run_id="fixture-run",
            timeout=10.0,
        )


def test_run_arm_disables_legacy_partial_cache_without_v4_companions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract_with_trials(2)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    harness = tmp_path / "harness"
    output = tmp_path / "output"
    output.mkdir()
    cache = tmp_path / "cache"
    run_id = "partial-cache-run"

    def simulation(task_id: str, trial: int, reward: float) -> dict:
        return {
            "task_id": task_id,
            "trial": trial,
            "termination_reason": "user_stop",
            "reward_info": {"reward": reward},
            "messages": [],
        }

    context = {
        "info": {"environment_info": {"domain_name": "telecom"}},
        "tasks": [{"id": task_id} for task_id in contract.task_ids],
    }
    harvest_arm_rows(
        cache,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results={
            **context,
            "simulations": [
                simulation("task-1", 0, 1.0),
                simulation("task-2", 0, 1.0),
                simulation("task-2", 1, 1.0),
            ],
        },
    )

    source_raw = harness / "data" / "simulations" / run_id / "results.json"
    source_raw.parent.mkdir(parents=True)
    source_raw.write_text(
        json.dumps(
            {
                **context,
                "simulations": [
                    # tau2 re-runs the complete task when only one trial was
                    # missing.  The cached original must win this duplicate.
                    simulation("task-1", 0, 0.0),
                    simulation("task-1", 1, 1.0),
                ],
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> tuple[subprocess.CompletedProcess[str], bool]:
        commands.append(command)
        snapshot_dir = Path(command[command.index("--trajectory-snapshot-dir") + 1])
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / f"{run_id}.snapshot.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=command, returncode=0), False

    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=False,
        raw_hash="a" * 64,
    )
    monkeypatch.setenv("CRUCIBLE_ROW_CACHE_ROOT", str(cache))
    monkeypatch.setattr("geode_product.crucible.tau2_live._run_tau2_command", run)
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.tau2_resource_usage_floor",
        lambda raw: ResourceUsage(0.0, 0, 0, 0.0),
    )
    monkeypatch.setattr("geode_product.crucible.tau2_live.tau2_trace_checks", lambda raw: {})
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.normalize_tau2_results",
        lambda *args, **kwargs: evidence,
    )

    _, merged_path, marginal_usage, measurement_source = _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id=run_id,
        timeout=10.0,
    )

    command = commands[0]
    task_slice = command[command.index("--task-ids") + 1 : command.index("--num-tasks")]
    assert task_slice == list(contract.task_ids)
    assert measurement_source == "fresh"
    merged = json.loads(merged_path.read_text(encoding="utf-8"))
    rewards = {
        (row["task_id"], row["trial"]): row["reward_info"]["reward"]
        for row in merged["simulations"]
    }
    assert rewards == {("task-1", 0): 0.0, ("task-1", 1): 1.0}
    marker = json.loads((output / "state" / "baseline" / "row-cache-disabled.json").read_text())
    assert marker["reason"] == "cached-row.v1 lacks snapshot-v4 runtime companions"
    assert marginal_usage.calls == 0
    assert marginal_usage.tokens == 0
    assert marginal_usage.cost_usd == 0.0
    assert marginal_usage.wall_seconds >= 0.0


def test_run_arm_disables_legacy_full_cache_and_executes_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    harness = tmp_path / "harness"
    harness.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    cache = tmp_path / "cache"
    raw = {
        "info": {"environment_info": {"domain_name": "telecom"}},
        "tasks": [{"id": task_id} for task_id in contract.task_ids],
        "simulations": [
            {
                "task_id": task_id,
                "trial": 0,
                "termination_reason": "user_stop",
                "reward_info": {"reward": 1.0},
                "messages": [],
            }
            for task_id in contract.task_ids
        ],
    }
    harvest_arm_rows(
        cache,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results=raw,
    )
    run_id = "full-cache-run"
    source_raw = harness / "data" / "simulations" / run_id / "results.json"
    source_raw.parent.mkdir(parents=True)
    source_raw.write_text(json.dumps(raw), encoding="utf-8")
    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=False,
        raw_hash="a" * 64,
    )
    monkeypatch.setenv("CRUCIBLE_ROW_CACHE_ROOT", str(cache))
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> tuple[subprocess.CompletedProcess[str], bool]:
        commands.append(command)
        snapshot_dir = Path(command[command.index("--trajectory-snapshot-dir") + 1])
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / f"{run_id}.snapshot.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=command, returncode=0), False

    monkeypatch.setattr("geode_product.crucible.tau2_live._run_tau2_command", run)
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.tau2_resource_usage_floor",
        lambda _raw: ResourceUsage(0.0, 0, 0, 0.0),
    )
    monkeypatch.setattr("geode_product.crucible.tau2_live.tau2_trace_checks", lambda _raw: {})
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.normalize_tau2_results",
        lambda *args, **kwargs: evidence,
    )

    _attested, _raw_path, marginal_usage, measurement_source = _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id=run_id,
        timeout=10.0,
    )

    assert marginal_usage.calls == 0
    assert marginal_usage.tokens == 0
    assert marginal_usage.cost_usd == 0.0
    assert marginal_usage.wall_seconds >= 0.0
    assert measurement_source == "fresh"
    assert len(commands) == 1
    marker = json.loads((output / "state" / "baseline" / "row-cache-disabled.json").read_text())
    assert marker["reason"] == "cached-row.v1 lacks snapshot-v4 runtime companions"


def test_run_arm_ignores_row_cache_outside_train_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sealed one-shots must stay fresh: a cache root in the environment is
    refused (observably) for any non-train stage instead of replaying rows."""
    import dataclasses

    contract = dataclasses.replace(_contract(), stage="test")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    harness = tmp_path / "harness"
    output = tmp_path / "output"
    output.mkdir()
    cache = tmp_path / "cache"
    run_id = "sealed-fresh-run"

    def simulation(task_id: str, trial: int, reward: float) -> dict:
        return {
            "task_id": task_id,
            "trial": trial,
            "termination_reason": "user_stop",
            "reward_info": {"reward": reward},
            "messages": [],
        }

    context = {
        "info": {"environment_info": {"domain_name": "telecom"}},
        "tasks": [{"id": task_id} for task_id in contract.task_ids],
    }
    harvest_arm_rows(
        cache,
        dataclasses.replace(_contract(), stage="train"),
        revision_sha=contract.baseline_sha,
        raw_results={
            **context,
            "simulations": [simulation(task_id, 0, 1.0) for task_id in contract.task_ids],
        },
    )

    source_raw = harness / "data" / "simulations" / run_id / "results.json"
    source_raw.parent.mkdir(parents=True)
    source_raw.write_text(
        json.dumps(
            {
                **context,
                "simulations": [simulation(task_id, 0, 1.0) for task_id in contract.task_ids],
            }
        ),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> tuple[subprocess.CompletedProcess[str], bool]:
        commands.append(command)
        snapshot_dir = Path(command[command.index("--trajectory-snapshot-dir") + 1])
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / f"{run_id}.snapshot.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=command, returncode=0), False

    evidence = _arm_evidence(
        contract,
        arm="baseline",
        invalid=False,
        raw_hash="a" * 64,
    )
    monkeypatch.setenv("CRUCIBLE_ROW_CACHE_ROOT", str(cache))
    monkeypatch.setattr("geode_product.crucible.tau2_live._run_tau2_command", run)
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.tau2_resource_usage_floor",
        lambda raw: ResourceUsage(0.0, 0, 0, 0.0),
    )
    monkeypatch.setattr("geode_product.crucible.tau2_live.tau2_trace_checks", lambda raw: {})
    monkeypatch.setattr(
        "geode_product.crucible.tau2_live.normalize_tau2_results",
        lambda *args, **kwargs: evidence,
    )

    _run_arm(
        contract,
        arm="baseline",
        checkout=checkout,
        harness_root=harness,
        contract_path=tmp_path / "contract.json",
        output_dir=output,
        run_id=run_id,
        timeout=600.0,
        parent_contract_path=tmp_path / "train-contract.json",
    )

    # A live tau2 command ran: the fully-populated cache was not synthesized.
    assert commands, "sealed arm must execute a fresh measurement"
    marker = output / "state" / "baseline" / "row-cache-disabled.json"
    disabled = json.loads(marker.read_text(encoding="utf-8"))
    assert disabled["schema"] == "crucible.row-cache-disabled.v1"
    assert disabled["stage"] == "test"


def test_partial_cache_index_rejects_duplicate_or_malformed_rows() -> None:
    row = {"task_id": "task-1", "trial": 0}
    with pytest.raises(Tau2InfrastructureError, match="duplicate pair"):
        _index_simulations({"simulations": [row, row]}, "fresh")
    with pytest.raises(Tau2InfrastructureError, match="must be an object"):
        _index_simulations({"simulations": [None]}, "fresh")
    with pytest.raises(Tau2InfrastructureError, match="integer trial"):
        _index_simulations(
            {"simulations": [{"task_id": "task-1", "trial": True}]},
            "fresh",
        )


def test_tau2_command_is_fully_derived_from_frozen_subscription_config(tmp_path: Path) -> None:
    command = tau2_command(
        _contract(),
        arm="candidate",
        checkout=tmp_path / "candidate",
        harness_root=tmp_path / "harness",
        contract_path=tmp_path / "contract.json",
        snapshot_dir=tmp_path / "snapshots",
        run_id="fixture-candidate",
    )

    assert command[command.index("--user") + 1] == "crucible_user"
    assert command[command.index("--model") + 1] == "gpt-5.4"
    assert command[command.index("--user-max-tokens") + 1] == "8192"
    assert command[command.index("--trajectory-arm") + 1] == "candidate"
    assert "--disable-tool-search-defer" not in command
    assert "--max-retries" in command
    assert command[command.index("--max-retries") + 1] == "0"
    assert command[command.index("--agent-max-rounds") + 1] == "0"
    assert command[command.index("--user-max-rounds") + 1] == "0"
    assert command[command.index("--timeout") + 1] == "600.0"


def test_tau2_command_omits_per_simulation_timeout_when_contract_disables_it(
    tmp_path: Path,
) -> None:
    payload = _contract().to_dict()
    payload.pop("contract_id")
    assay = dict(payload["assay_config"])
    assay["timeout"] = None
    payload["assay_config"] = assay
    contract = ExperimentContract.from_mapping(payload)

    command = tau2_command(
        contract,
        arm="candidate",
        checkout=tmp_path / "candidate",
        harness_root=tmp_path / "harness",
        contract_path=tmp_path / "contract.json",
        snapshot_dir=tmp_path / "snapshots",
        run_id="fixture-unbounded-candidate",
    )

    assert "--timeout" not in command


def test_tau2_test_command_binds_the_frozen_train_parent(tmp_path: Path) -> None:
    parent = _contract()
    contract = _test_contract(parent)
    parent_path = tmp_path / "train-contract.json"

    command = tau2_command(
        contract,
        arm="candidate",
        checkout=tmp_path / "candidate",
        harness_root=tmp_path / "harness",
        contract_path=tmp_path / "test-contract.json",
        parent_contract_path=parent_path,
        snapshot_dir=tmp_path / "snapshots",
        run_id="sealed-candidate",
    )

    assert command[command.index("--parent-experiment-contract") + 1] == str(parent_path)
    with pytest.raises(ContractError, match="frozen train contract"):
        tau2_command(
            contract,
            arm="candidate",
            checkout=tmp_path / "candidate",
            harness_root=tmp_path / "harness",
            contract_path=tmp_path / "test-contract.json",
            snapshot_dir=tmp_path / "snapshots",
            run_id="missing-parent",
        )


def test_tau2_trace_checks_are_independent_of_reward() -> None:
    raw = {
        "info": {"environment_info": {"domain_name": "retail"}},
        "simulations": [
            {
                "task_id": "task-1",
                "trial": 0,
                "reward_info": {"reward": 1.0},
                "messages": [
                    {"role": "user", "content": "Please change it."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"name": "modify_order", "arguments": {"id": "1"}}],
                    },
                ],
            },
            {
                "task_id": "task-2",
                "trial": 0,
                "reward_info": {"reward": 0.0},
                "messages": [
                    {"role": "user", "content": "Yes, please proceed."},
                    {
                        "role": "assistant",
                        "tool_calls": [{"name": "modify_order", "arguments": {"id": "2"}}],
                    },
                    {"role": "tool", "content": "failed", "error": True},
                ],
            },
        ],
    }

    checks = tau2_trace_checks(raw)

    assert checks[("task-1", 0)] == {"safety": False, "tool_contract": True}
    assert checks[("task-2", 0)] == {"safety": True, "tool_contract": False}


def test_tau2_feedback_projects_structure_without_task_or_tool_cases() -> None:
    contract = _contract()
    payload = _arm_evidence(
        contract,
        arm="candidate",
        invalid=False,
        raw_hash="d" * 64,
    ).to_dict()
    payload.pop("evidence_id")
    rows = payload["rows"]
    assert isinstance(rows, list)
    for row in rows:
        row["metrics"]["reward"] = 0.0
    rows[1]["termination_reason"] = "max_steps"
    candidate = EvidenceEnvelope.from_mapping(payload)
    raw = {
        "simulations": [
            {
                "task_id": "task-1",
                "trial": 0,
                "reward_info": {
                    "action_checks": [
                        {
                            "action_match": False,
                            "action": {"requestor": "user", "name": "opaque-action"},
                        }
                    ]
                },
            },
            {
                "task_id": "task-2",
                "trial": 0,
                "reward_info": {"action_checks": []},
            },
        ]
    }

    feedback = tau2_failure_feedback(contract, candidate, raw)

    assert feedback is not None
    assert feedback.failure_codes == (
        "required_user_action",
        "termination",
        "workflow_completion",
    )
    assert feedback.failed_task_ids == ("task-1", "task-2")
