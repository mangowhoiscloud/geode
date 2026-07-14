import hashlib
import json
from pathlib import Path

import pytest
from plugins.crucible.cli import main as crucible_main
from plugins.crucible.contract import (
    ContractError,
    ExperimentContract,
    task_pack_sha256,
)
from plugins.crucible.evidence import ResourceUsage
from plugins.crucible.verifiers.tau2 import (
    TAU2_ADAPTER,
    _canonical_task_sha256,
    normalize_tau2_results,
    tau2_has_infrastructure_contamination,
    tau2_resource_usage_floor,
    tau2_task_unit,
)


def _raw_tasks() -> list[dict[str, object]]:
    return [
        {
            "id": "1",
            "description": {"purpose": "first task"},
            "evaluation_criteria": {
                "actions": [{"name": "lookup"}],
                "communicate_info": [],
            },
            "user_tools": None,
        },
        {
            "id": "2",
            "description": {"purpose": "second task"},
            "evaluation_criteria": {
                "actions": [{"name": "update"}],
                "communicate_info": [],
            },
            "user_tools": None,
        },
    ]


TASKS = tuple(tau2_task_unit(task) for task in _raw_tasks())


def test_tau2_incremental_infrastructure_detection_is_fail_fast() -> None:
    semantic = _raw_results()
    assert tau2_has_infrastructure_contamination(semantic) is False

    contaminated = _raw_results(second_termination="infrastructure_error")
    assert tau2_has_infrastructure_contamination(contaminated) is True

    retried = _raw_results()
    messages = retried["simulations"][0]["messages"]
    messages[0]["raw_data"] = {
        "geode_pre_execution_retry_count": 1,
        "geode_pre_execution_retry_errors": ["APITimeoutError"],
    }
    assert tau2_has_infrastructure_contamination(retried) is True


def test_tau2_task_content_hash_excludes_only_top_level_id() -> None:
    task = _raw_tasks()[0]
    relabeled = {**task, "id": "relabeled"}
    changed_nested_content = {
        **task,
        "description": {"purpose": "first task", "id": "nested-id"},
    }

    assert _canonical_task_sha256(task, "task") == _canonical_task_sha256(
        relabeled,
        "task",
    )
    assert _canonical_task_sha256(task, "task") != _canonical_task_sha256(
        changed_nested_content,
        "task",
    )


def test_tau2_task_hash_normalizes_runtime_materialized_optional_defaults() -> None:
    source = dict(_raw_tasks()[0])
    source.pop("user_tools")
    runtime = {
        **source,
        "issues": None,
        "required_documents": None,
        "user_tools": None,
    }

    assert tau2_task_unit(source) == tau2_task_unit(runtime)


def test_tau2_family_is_derived_from_workflow_shape_not_task_values() -> None:
    task = _raw_tasks()[0]
    same_workflow = {
        **task,
        "id": "different-id",
        "description": {"purpose": "different task-specific value"},
    }
    different_workflow = {
        **task,
        "evaluation_criteria": {
            "actions": [{"name": "lookup"}, {"name": "update"}],
            "communicate_info": [],
        },
    }

    assert tau2_task_unit(task).family_id == tau2_task_unit(same_workflow).family_id
    assert tau2_task_unit(task).family_id != tau2_task_unit(different_workflow).family_id


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
        "timeout": 600.0,
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
            "provider": "openai",
            "source": "payg",
            "effort": "high",
            "time_budget_s": 120.0,
            "max_tokens": 8192,
            "max_rounds": 0,
        },
        "retrieval": {"config": None, "kwargs": {}},
    }


def test_tau2_geode_agent_rejects_unattested_thread_pool_concurrency() -> None:
    config = _assay_config()
    config["max_concurrency"] = 2

    with pytest.raises(ContractError, match="geode_agent supports max_concurrency<=1"):
        TAU2_ADAPTER.validate_config(config)


def test_tau2_contract_accepts_explicit_unbounded_per_simulation_timeout() -> None:
    config = _assay_config()
    config["timeout"] = None

    TAU2_ADAPTER.validate_config(config)


def test_tau2_contract_requires_explicit_timeout_policy() -> None:
    config = _assay_config()
    del config["timeout"]

    with pytest.raises(ContractError, match="explicit timeout field"):
        TAU2_ADAPTER.validate_config(config)


@pytest.mark.parametrize("timeout", [0, -1.0, float("inf"), True, "600"])
def test_tau2_contract_rejects_invalid_per_simulation_timeout(timeout: object) -> None:
    config = _assay_config()
    config["timeout"] = timeout

    with pytest.raises(ContractError, match="null or a positive finite number"):
        TAU2_ADAPTER.validate_config(config)


@pytest.mark.parametrize("role", ["agent", "user"])
def test_tau2_contract_leaves_round_yield_to_the_external_boundary(role: str) -> None:
    config = _assay_config()
    participant = config[role]
    assert isinstance(participant, dict)
    participant["max_rounds"] = 1

    with pytest.raises(ContractError, match=rf"{role} requires max_rounds=0"):
        TAU2_ADAPTER.validate_config(config)


def _contract() -> ExperimentContract:
    return ExperimentContract.from_mapping(
        {
            "schema": "crucible.experiment.v3",
            "name": "tau2-retail",
            "stage": "train",
            "champion_ref": "refs/heads/develop",
            "baseline_sha": "1" * 40,
            "candidate_sha": "2" * 40,
            "evaluator_sha256": "a" * 64,
            "harness_sha256": "b" * 64,
            "task_pack_sha256": task_pack_sha256(TASKS, 1),
            "agent_route": "openai-subscription-gpt-5.5-high",
            "user_route": "tau2-user_simulator-gpt-5.2",
            "tasks": [task.to_dict() for task in TASKS],
            "trials_per_task": 1,
            "assay_config": _assay_config(),
            "mutations": [{"surface": "core/agent/verify.py", "hypothesis": "fewer misses"}],
            "evaluator_paths": ["plugins/benchmark_harness", "plugins/crucible"],
            "promotion": {
                "method": "paired_bootstrap.v2",
                "primary_metric": "reward",
                "materiality_pp": 0.1,
                "minimum_candidate_mean": 0.5,
                "minimum_families": 2,
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
        "tasks": _raw_tasks(),
        "simulations": [
            {
                "id": "1.0",
                "task_id": "1",
                "trial": 0,
                "duration": 2.0,
                "termination_reason": "user_stop",
                "reward_info": {"reward": 1.0},
                "messages": [
                    {
                        "usage": {
                            "input_tokens": 50,
                            "output_tokens": 10,
                            "cost_usd": 0.2,
                        }
                    }
                ],
            },
            {
                "id": "2.0",
                "task_id": "2",
                "trial": 0,
                "duration": 3.0,
                "termination_reason": second_termination,
                "reward_info": None,
                "messages": [
                    {
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 5,
                            "cost_usd": 0.1,
                        }
                    }
                ],
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
        "schema": "crucible_tau2_trajectory_snapshot.v3",
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


def test_tau2_adapter_rejects_reward_outside_the_unit_interval(tmp_path: Path) -> None:
    contract = _contract()
    raw = _raw_results()
    simulations = raw["simulations"]
    assert isinstance(simulations, list)
    simulations[0]["reward_info"]["reward"] = 1.1
    results, snapshot = _write_artifacts(tmp_path, contract, raw=raw)

    with pytest.raises(ContractError, match=r"within \[0, 1\]"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair=_checks(),
        )


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


def test_tau2_adapter_marks_recovered_llm_retry_as_infrastructure_invalid(
    tmp_path: Path,
) -> None:
    contract = _contract()
    raw = _raw_results()
    simulations = raw["simulations"]
    assert isinstance(simulations, list)
    first = simulations[0]
    assert isinstance(first, dict)
    messages = first["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    message["raw_data"] = {
        "geode_pre_execution_retry_count": 1,
        "geode_pre_execution_retry_errors": ["APITimeoutError"],
    }
    results, snapshot = _write_artifacts(tmp_path, contract, raw=raw)

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
    assert evidence.rows[0].status == "infrastructure_error"
    assert evidence.rows[0].failure_class == "tau2_pre_execution_retry"


@pytest.mark.parametrize(
    ("count", "errors"),
    [
        (True, ["APITimeoutError"]),
        (1, []),
        (0, ["APITimeoutError"]),
        (1, [""]),
    ],
)
def test_tau2_adapter_rejects_malformed_retry_telemetry(
    tmp_path: Path,
    count: object,
    errors: object,
) -> None:
    contract = _contract()
    raw = _raw_results()
    simulations = raw["simulations"]
    assert isinstance(simulations, list)
    first = simulations[0]
    assert isinstance(first, dict)
    messages = first["messages"]
    assert isinstance(messages, list)
    message = messages[0]
    assert isinstance(message, dict)
    message["raw_data"] = {
        "geode_pre_execution_retry_count": count,
        "geode_pre_execution_retry_errors": errors,
    }
    results, snapshot = _write_artifacts(tmp_path, contract, raw=raw)

    with pytest.raises(ContractError, match="pre-execution retry"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair=_checks(),
        )


def test_tau2_usage_manifest_cannot_underreport_raw_messages(tmp_path: Path) -> None:
    raw = _raw_results()
    observed = tau2_resource_usage_floor(raw)
    assert observed.wall_seconds == pytest.approx(3.0)
    assert observed.calls == 2
    assert observed.tokens == 85
    assert observed.cost_usd == pytest.approx(0.3)
    contract = _contract()
    results, snapshot = _write_artifacts(tmp_path, contract, raw=raw)
    usage_path = tmp_path / "usage.json"
    assert crucible_main(["tau2-usage", str(results), "--output", str(usage_path)]) == 0
    assert json.loads(usage_path.read_text())["tokens"] == 85

    with pytest.raises(
        ContractError,
        match=r"underreports.*wall_seconds.*calls.*tokens.*cost_usd",
    ):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=ResourceUsage(wall_seconds=1.0, calls=1, tokens=84, cost_usd=0.29),
            checks_by_pair=_checks(),
        )


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


def test_tau2_adapter_requires_frozen_task_order_and_content(tmp_path: Path) -> None:
    contract = _contract()
    reordered = _raw_results()
    reordered_tasks = reordered["tasks"]
    assert isinstance(reordered_tasks, list)
    reordered_tasks.reverse()
    results, snapshot = _write_artifacts(tmp_path, contract, raw=reordered)
    with pytest.raises(ContractError, match="task order/coverage"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair=_checks(),
        )

    changed = _raw_results()
    changed_tasks = changed["tasks"]
    assert isinstance(changed_tasks, list)
    first = changed_tasks[0]
    assert isinstance(first, dict)
    first["description"] = {"purpose": "changed after contract freeze"}
    results, snapshot = _write_artifacts(tmp_path, contract, raw=changed)
    with pytest.raises(ContractError, match="content_sha256"):
        normalize_tau2_results(
            contract,
            arm="candidate",
            results_path=results,
            snapshot_path=snapshot,
            usage=_usage(),
            checks_by_pair=_checks(),
        )


def test_tau2_profile_rejects_candidate_coupled_user_runtime() -> None:
    config = _assay_config()
    user = config["user"]
    assert isinstance(user, dict)
    user["implementation"] = "geode_user"
    user["runtime_owner"] = "candidate"

    with pytest.raises(ContractError, match="isolated from candidate code"):
        TAU2_ADAPTER.validate_config(config)


def test_tau2_profile_accepts_frozen_subscription_user_runtime() -> None:
    config = _assay_config()
    user = config["user"]
    assert isinstance(user, dict)
    user.update(
        {
            "implementation": "crucible_user",
            "runtime_owner": "evaluator",
            "route": "evaluator-openai-subscription-gpt-5.4-high",
            "llm": "gpt-5.4",
            "source": "subscription",
        }
    )

    TAU2_ADAPTER.validate_config(config)
    assert (
        TAU2_ADAPTER.user_route(
            implementation="crucible_user",
            native_model="gpt-5.4",
            candidate_route="openai-subscription-gpt-5.4-high",
        )
        == "evaluator-openai-subscription-gpt-5.4-high"
    )


def test_tau2_task_pack_cli_emits_only_ordered_hash_identities(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    output = tmp_path / "pack.json"
    tasks_path.write_text(json.dumps(_raw_tasks()), encoding="utf-8")

    assert (
        crucible_main(
            [
                "tau2-task-pack",
                str(tasks_path),
                "--task-id",
                "2",
                "--task-id",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text())
    assert payload["schema"] == "crucible.task-pack.v1"
    assert [task["task_id"] for task in payload["tasks"]] == ["2", "1"]
    assert all(set(task) == {"task_id", "family_id", "content_sha256"} for task in payload["tasks"])
    assert "description" not in json.dumps(payload)


def test_tau2_task_pack_cli_rejects_tasks_outside_frozen_split(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    split_path = tmp_path / "split_tasks.json"
    output = tmp_path / "pack.json"
    tasks_path.write_text(json.dumps(_raw_tasks()), encoding="utf-8")
    split_path.write_text(json.dumps({"base": ["1"]}), encoding="utf-8")

    assert (
        crucible_main(
            [
                "tau2-task-pack",
                str(tasks_path),
                "--task-id",
                "2",
                "--task-split",
                str(split_path),
                "--task-split-name",
                "base",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


def test_tau2_task_pack_cli_accepts_tasks_inside_frozen_split(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    split_path = tmp_path / "split_tasks.json"
    output = tmp_path / "pack.json"
    tasks_path.write_text(json.dumps(_raw_tasks()), encoding="utf-8")
    split_path.write_text(json.dumps({"base": ["2", "1"]}), encoding="utf-8")

    assert (
        crucible_main(
            [
                "tau2-task-pack",
                str(tasks_path),
                "--task-id",
                "2",
                "--task-split",
                str(split_path),
                "--task-split-name",
                "base",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert [task["task_id"] for task in json.loads(output.read_text())["tasks"]] == ["2"]
