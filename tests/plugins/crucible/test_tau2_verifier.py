import hashlib
import json
from pathlib import Path

import pytest
from plugins.crucible.contract import ContractError, ExperimentContract, task_pack_sha256
from plugins.crucible.evidence import ResourceUsage
from plugins.crucible.verifiers.tau2 import TAU2_ADAPTER, normalize_tau2_results


def _assay_config() -> dict[str, object]:
    return {
        "schema": "crucible.tau2-assay.v1",
        "domain": "retail",
        "task_set_name": None,
        "task_split_name": "base",
        "num_trials": 1,
        "max_concurrency": 1,
        "max_steps": 20,
        "max_errors": 1,
        "max_retries": 0,
        "timeout": None,
        "seed": 300,
        "agent": {
            "implementation": "geode_agent",
            "route": "openai-subscription-gpt-5.5-high",
            "model": "gpt-5.5",
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
            "implementation": "user_simulator",
            "runtime_owner": "evaluator",
            "route": "tau2-user_simulator-gpt-5.2",
            "llm": "gpt-5.2",
            "llm_args": {"temperature": 0.0},
        },
        "retrieval": {"config": None, "kwargs": {}},
    }


def _contract() -> ExperimentContract:
    task_ids = ["1", "2"]
    return ExperimentContract.from_mapping(
        {
            "schema": "crucible.experiment.v1",
            "name": "tau2-retail",
            "stage": "train",
            "champion_ref": "refs/heads/develop",
            "baseline_sha": "1" * 40,
            "candidate_sha": "2" * 40,
            "evaluator_sha256": "a" * 64,
            "harness_sha256": "b" * 64,
            "task_pack_sha256": task_pack_sha256(task_ids, 1),
            "agent_route": "openai-subscription-gpt-5.5-high",
            "user_route": "tau2-user_simulator-gpt-5.2",
            "task_ids": task_ids,
            "trials_per_task": 1,
            "assay_config": _assay_config(),
            "mutations": [{"surface": "core/agent/verify.py", "hypothesis": "fewer misses"}],
            "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
            "promotion": {
                "method": "paired_bootstrap.v1",
                "primary_metric": "reward",
                "minimum_improvement": 0.1,
                "minimum_candidate_mean": 0.5,
                "minimum_tasks": 2,
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


def _raw_results(*, second_termination: str = "max_steps") -> dict[str, object]:
    return {
        "info": {
            "num_trials": 1,
            "max_steps": 20,
            "max_errors": 1,
            "seed": 300,
            "agent_info": {"implementation": "geode_agent", "llm": "gpt-5.5"},
            "user_info": {
                "implementation": "user_simulator",
                "llm": "gpt-5.2",
                "llm_args": {"temperature": 0.0},
            },
            "environment_info": {"domain_name": "retail"},
            "retrieval_config": None,
            "retrieval_config_kwargs": {},
        },
        "tasks": [],
        "simulations": [
            {
                "id": "1.0",
                "task_id": "1",
                "trial": 0,
                "termination_reason": "user_stop",
                "reward_info": {"reward": 1.0},
            },
            {
                "id": "2.0",
                "task_id": "2",
                "trial": 0,
                "termination_reason": second_termination,
                "reward_info": None,
            },
        ],
    }


def _write_artifacts(
    tmp_path: Path,
    contract: ExperimentContract,
    *,
    raw: dict[str, object],
    status: str = "complete",
) -> tuple[Path, Path]:
    results = tmp_path / "results.json"
    results.write_text(json.dumps(raw), encoding="utf-8")
    raw_sha = hashlib.sha256(results.read_bytes()).hexdigest()
    snapshot = tmp_path / "snapshot.json"
    payload: dict[str, object] = {
        "schema": "crucible_tau2_trajectory_snapshot.v1",
        "experiment_contract_id": contract.contract_id,
        "baseline_sha": contract.baseline_sha,
        "candidate_sha": contract.candidate_sha,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "assay_config": contract.assay_config,
        "arm": "candidate",
        "raw_artifact_sha256": raw_sha,
        "execution_status": status,
        "failure_class": None,
    }
    if status == "invalid":
        payload["failure_class"] = "run_error"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    return results, snapshot


def _usage() -> ResourceUsage:
    return ResourceUsage(wall_seconds=20.0, calls=10, tokens=1_000, cost_usd=1.0)


def _checks() -> dict[tuple[str, int], dict[str, bool]]:
    return {("1", 0): {"safety": True}, ("2", 0): {"safety": True}}


def test_tau2_adapter_keeps_max_steps_as_semantic_zero(tmp_path: Path) -> None:
    contract = _contract()
    results, snapshot = _write_artifacts(tmp_path, contract, raw=_raw_results())

    evidence = normalize_tau2_results(
        contract,
        arm="candidate",
        results_path=results,
        snapshot_path=snapshot,
        usage=_usage(),
        checks_by_pair=_checks(),
    )

    assert evidence.execution_status == "complete"
    assert evidence.rows[1].status == "completed"
    assert evidence.rows[1].metric("reward") == 0.0


def test_tau2_adapter_marks_upstream_infrastructure_error_invalid(tmp_path: Path) -> None:
    contract = _contract()
    results, snapshot = _write_artifacts(
        tmp_path,
        contract,
        raw=_raw_results(second_termination="infrastructure_error"),
    )

    evidence = normalize_tau2_results(
        contract,
        arm="candidate",
        results_path=results,
        snapshot_path=snapshot,
        usage=_usage(),
        checks_by_pair=_checks(),
    )

    assert evidence.execution_status == "invalid"
    assert evidence.failure_class == "tau2_infrastructure_error"


def test_tau2_adapter_rejects_raw_tampering_and_missing_checks(tmp_path: Path) -> None:
    contract = _contract()
    results, snapshot = _write_artifacts(tmp_path, contract, raw=_raw_results())
    results.write_text(json.dumps({**_raw_results(), "tampered": True}), encoding="utf-8")

    with pytest.raises(ContractError, match="raw_artifact_sha256"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair=_checks(),
        )

    results, snapshot = _write_artifacts(tmp_path, contract, raw=_raw_results())
    with pytest.raises(ContractError, match="checks missing"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair={("1", 0): {"safety": True}},
        )


def test_tau2_profile_rejects_candidate_coupled_user_runtime() -> None:
    config = _assay_config()
    user = config["user"]
    assert isinstance(user, dict)
    user["implementation"] = "geode_user"
    user["runtime_owner"] = "candidate"

    with pytest.raises(ContractError, match="isolated from candidate code"):
        TAU2_ADAPTER.validate_config(config)
