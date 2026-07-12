from copy import deepcopy
from pathlib import Path

import plugins.crucible.contract as contract_module
import pytest
from plugins.crucible.contract import (
    ContractError,
    ExperimentContract,
    TaskUnit,
    content_sha256,
    task_pack_sha256,
    tracked_tree_sha256,
    validate_candidate_diff,
    validate_shards,
    validate_test_parent,
)

BASELINE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
EVALUATOR_SHA = "a" * 64
HARNESS_SHA = "b" * 64
TASKS = (
    TaskUnit("retail-1", "retail-family-1", "1" * 64),
    TaskUnit("retail-2", "retail-family-2", "2" * 64),
)
TASK_PACK_SHA = task_pack_sha256(TASKS, 1)


def _payload() -> dict[str, object]:
    return {
        "schema": "crucible.experiment.v3",
        "name": "retail-write-invariant",
        "stage": "train",
        "champion_ref": "refs/heads/develop",
        "baseline_sha": BASELINE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "evaluator_sha256": EVALUATOR_SHA,
        "harness_sha256": HARNESS_SHA,
        "task_pack_sha256": TASK_PACK_SHA,
        "agent_route": "openai/subscription/gpt-5.5/high",
        "user_route": "tau2-user_simulator-gpt-5.2",
        "tasks": [task.to_dict() for task in TASKS],
        "trials_per_task": 1,
        "assay_config": {
            "schema": "crucible.tau2-assay.v1",
            "domain": "retail",
            "user": {
                "implementation": "user_simulator",
                "runtime_owner": "evaluator",
            },
        },
        "mutations": [
            {
                "surface": "core/agent/verify.py",
                "hypothesis": "Confirmed writes require emitted tool calls.",
            }
        ],
        "evaluator_paths": ["plugins/benchmark_harness", "scripts/eval"],
        "promotion": {
            "method": "paired_bootstrap.v2",
            "primary_metric": "reward",
            "materiality_pp": 0.01,
            "minimum_candidate_mean": 0.5,
            "minimum_families": 2,
            "minimum_tasks": 2,
            "confidence_level": 0.95,
            "bootstrap_samples": 1_000,
        },
        "budget": {
            "max_wall_seconds": 300.0,
            "max_calls": 100,
            "max_tokens": 500_000,
            "max_cost_usd": 5.0,
            "max_changed_lines": 120,
        },
        "vetoes": ["infra_clean", "task_coverage", "safety", "budget"],
    }


def _contract() -> ExperimentContract:
    return ExperimentContract.from_mapping(_payload())


def _shard(contract: ExperimentContract, task_ids: list[str]) -> dict[str, object]:
    return {
        "schema": "crucible.shard.v3",
        "contract_id": contract.contract_id,
        "revision_sha": contract.candidate_sha,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "trials_per_task": contract.trials_per_task,
        "task_ids": task_ids,
    }


def test_contract_id_is_canonical_and_round_trips() -> None:
    contract = _contract()
    serialized = contract.to_dict()

    assert len(contract.contract_id) == 64
    assert contract.task_ids == ("retail-1", "retail-2")
    assert "task_ids" not in serialized
    assert serialized["contract_id"] == contract.contract_id
    assert ExperimentContract.from_mapping(serialized) == contract


def test_task_pack_hash_binds_order_family_content_and_trials() -> None:
    changed_family = (TASKS[0], TaskUnit("retail-2", "other-family", "2" * 64))
    changed_content = (
        TASKS[0],
        TaskUnit("retail-2", "retail-family-2", "3" * 64),
    )

    assert task_pack_sha256(tuple(reversed(TASKS)), 1) != TASK_PACK_SHA
    assert task_pack_sha256(changed_family, 1) != TASK_PACK_SHA
    assert task_pack_sha256(changed_content, 1) != TASK_PACK_SHA
    assert task_pack_sha256(TASKS, 2) != TASK_PACK_SHA


def test_contract_requires_exactly_one_mutation() -> None:
    payload = _payload()
    payload["mutations"] = []

    with pytest.raises(ContractError, match="exactly one"):
        ExperimentContract.from_mapping(payload)


@pytest.mark.parametrize("schema", ["crucible.experiment.v1", "crucible.experiment.v2"])
def test_contract_rejects_retired_schema(schema: str) -> None:
    payload = _payload()
    payload["schema"] = schema

    with pytest.raises(ContractError, match=r"crucible\.experiment\.v3"):
        ExperimentContract.from_mapping(payload)


def test_contract_rejects_non_finite_numbers_and_wrong_task_hash() -> None:
    payload = _payload()
    promotion = deepcopy(payload["promotion"])
    assert isinstance(promotion, dict)
    promotion["materiality_pp"] = float("nan")
    payload["promotion"] = promotion
    with pytest.raises(ContractError, match="finite number"):
        ExperimentContract.from_mapping(payload)

    payload = _payload()
    budget = deepcopy(payload["budget"])
    assert isinstance(budget, dict)
    budget["max_cost_usd"] = float("inf")
    payload["budget"] = budget
    with pytest.raises(ContractError, match="greater than zero"):
        ExperimentContract.from_mapping(payload)

    payload = _payload()
    payload["task_pack_sha256"] = "c" * 64
    with pytest.raises(ContractError, match="ordered tasks and trials_per_task"):
        ExperimentContract.from_mapping(payload)


def test_contract_rejects_duplicate_task_ids() -> None:
    payload = _payload()
    payload["tasks"] = [TASKS[0].to_dict(), TASKS[0].to_dict()]
    payload["task_pack_sha256"] = task_pack_sha256((TASKS[0], TASKS[0]), 1)

    with pytest.raises(ContractError, match="duplicate task_id"):
        ExperimentContract.from_mapping(payload)


def test_contract_rejects_relabeled_duplicate_task_content() -> None:
    payload = _payload()
    duplicate = TaskUnit("retail-relabeled", "other-family", TASKS[0].content_sha256)
    tasks = (TASKS[0], duplicate)
    payload["tasks"] = [task.to_dict() for task in tasks]
    payload["task_pack_sha256"] = task_pack_sha256(tasks, 1)

    with pytest.raises(ContractError, match="duplicate content_sha256"):
        ExperimentContract.from_mapping(payload)


def test_contract_separates_candidate_and_evaluator_surfaces() -> None:
    payload = _payload()
    payload["evaluator_paths"] = ["core/agent"]

    with pytest.raises(ContractError, match="must not overlap"):
        ExperimentContract.from_mapping(payload)


def test_sealed_test_requires_frozen_train_parent() -> None:
    payload = _payload()
    payload["stage"] = "test"

    with pytest.raises(ContractError, match="require the frozen train"):
        ExperimentContract.from_mapping(payload)

    payload["parent_contract_id"] = "d" * 64
    contract = ExperimentContract.from_mapping(payload)
    assert contract.stage == "test"


def test_sealed_test_parent_must_match_candidate_and_be_disjoint() -> None:
    parent = _contract()
    payload = _payload()
    payload["stage"] = "test"
    child_tasks = (TaskUnit("retail-3", "retail-family-3", "3" * 64),)
    payload["tasks"] = [task.to_dict() for task in child_tasks]
    payload["task_pack_sha256"] = task_pack_sha256(child_tasks, 1)
    payload["parent_contract_id"] = parent.contract_id
    child = ExperimentContract.from_mapping(payload)

    validate_test_parent(child, parent)

    overlap = _payload()
    overlap["stage"] = "test"
    overlap["parent_contract_id"] = parent.contract_id
    with pytest.raises(ContractError, match="train task IDs"):
        validate_test_parent(ExperimentContract.from_mapping(overlap), parent)

    family_overlap = deepcopy(payload)
    family_tasks = (TaskUnit("retail-3", "retail-family-1", "3" * 64),)
    family_overlap["tasks"] = [task.to_dict() for task in family_tasks]
    family_overlap["task_pack_sha256"] = task_pack_sha256(family_tasks, 1)
    with pytest.raises(ContractError, match="train task families"):
        validate_test_parent(ExperimentContract.from_mapping(family_overlap), parent)

    content_overlap = deepcopy(payload)
    content_tasks = (TaskUnit("retail-3", "retail-family-3", "1" * 64),)
    content_overlap["tasks"] = [task.to_dict() for task in content_tasks]
    content_overlap["task_pack_sha256"] = task_pack_sha256(content_tasks, 1)
    with pytest.raises(ContractError, match="train task content hashes"):
        validate_test_parent(ExperimentContract.from_mapping(content_overlap), parent)

    different_candidate = deepcopy(payload)
    different_candidate["candidate_sha"] = "3" * 40
    different = ExperimentContract.from_mapping(different_candidate)
    with pytest.raises(ContractError, match="candidate_sha"):
        validate_test_parent(different, parent)

    different_budget = deepcopy(payload)
    budget = deepcopy(different_budget["budget"])
    assert isinstance(budget, dict)
    budget["max_cost_usd"] = 999.0
    different_budget["budget"] = budget
    with pytest.raises(ContractError, match="budget"):
        validate_test_parent(ExperimentContract.from_mapping(different_budget), parent)


def test_supplied_contract_id_must_match_payload() -> None:
    payload = _payload()
    payload["contract_id"] = "f" * 64

    with pytest.raises(ContractError, match="does not match"):
        ExperimentContract.from_mapping(payload)


def test_shards_require_one_frozen_revision_and_exact_order() -> None:
    contract = _contract()
    first = _shard(contract, ["retail-1"])
    second = _shard(contract, ["retail-2"])

    assert validate_shards(contract, [first, second], arm="candidate") == contract.task_ids

    mixed_revision = deepcopy(second)
    mixed_revision["revision_sha"] = "3" * 40
    with pytest.raises(ContractError, match="revision_sha"):
        validate_shards(contract, [first, mixed_revision], arm="candidate")

    baseline = _shard(contract, ["retail-1", "retail-2"])
    baseline["revision_sha"] = contract.baseline_sha
    assert validate_shards(contract, [baseline], arm="baseline") == contract.task_ids


def test_shards_reject_missing_reordered_or_repeated_tasks() -> None:
    contract = _contract()

    with pytest.raises(ContractError, match="order/coverage"):
        validate_shards(contract, [_shard(contract, ["retail-1"])], arm="candidate")
    with pytest.raises(ContractError, match="order/coverage"):
        validate_shards(
            contract,
            [_shard(contract, ["retail-2", "retail-1"])],
            arm="candidate",
        )
    with pytest.raises(ContractError, match="repeat task"):
        validate_shards(
            contract,
            [_shard(contract, ["retail-1"]), _shard(contract, ["retail-1"])],
            arm="candidate",
        )


def test_content_hash_covers_relative_paths_and_bytes(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "nested" / "b.txt").write_text("beta", encoding="utf-8")

    before = content_sha256(tmp_path, ["a.txt", "nested"])
    (tmp_path / "nested" / "b.txt").write_text("changed", encoding="utf-8")

    assert content_sha256(tmp_path, ["a.txt", "nested"]) != before


def test_hashes_preserve_executable_mode_and_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "runner.sh"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o644)
    regular_hash = content_sha256(tmp_path, ["runner.sh"])
    executable.chmod(0o755)
    assert content_sha256(tmp_path, ["runner.sh"]) != regular_hash

    link = tmp_path / "domains"
    link.symlink_to("task-data-a")
    monkeypatch.setattr(
        contract_module,
        "_run_git",
        lambda *_args: "120000 deadbeef 0\tdomains\0",
    )
    first_target = tracked_tree_sha256(tmp_path)
    link.unlink()
    link.symlink_to("task-data-b")

    assert tracked_tree_sha256(tmp_path) != first_target


def test_candidate_diff_is_one_bounded_production_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _contract()

    def git_with_numstat(_repo: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return f"{contract.baseline_sha}\n"
        if args[0] == "rev-list":
            return "1\n"
        if args[0] == "diff":
            return "2\t1\tcore/agent/verify.py\0"
        if args[0] == "ls-tree":
            return "100644 blob deadbeef\tcore/agent/verify.py\0"
        return ""

    monkeypatch.setattr(
        contract_module,
        "_run_git",
        git_with_numstat,
    )
    validate_candidate_diff(contract, Path("."))

    monkeypatch.setattr(
        contract_module,
        "_run_git",
        lambda _repo, *args: "3" * 40 if args[0] == "rev-parse" else "",
    )
    with pytest.raises(ContractError, match="champion ref"):
        validate_candidate_diff(contract, Path("."))

    def git_with_unexpected_path(_repo: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return f"{contract.baseline_sha}\n"
        if args[0] == "rev-list":
            return "1\n"
        if args[0] == "diff":
            return "2\t1\tcore/agent/verify.py\0" + "1\t0\tcore/orchestration/unrelated.py\0"
        if args[0] == "ls-tree":
            return "100644 blob deadbeef\tcore/agent/verify.py\0"
        return ""

    monkeypatch.setattr(
        contract_module,
        "_run_git",
        git_with_unexpected_path,
    )
    with pytest.raises(ContractError, match="outside the mutation surface"):
        validate_candidate_diff(contract, Path("."))

    def git_with_candidate_test(_repo: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return f"{contract.baseline_sha}\n"
        if args[0] == "rev-list":
            return "1\n"
        if args[0] == "diff":
            return "2\t1\tcore/agent/verify.py\0" + "1\t0\ttests/test_evaluator.py\0"
        if args[0] == "ls-tree":
            return "100644 blob deadbeef\tcore/agent/verify.py\0"
        return ""

    monkeypatch.setattr(contract_module, "_run_git", git_with_candidate_test)
    with pytest.raises(ContractError, match="outside the mutation surface"):
        validate_candidate_diff(contract, Path("."))

    monkeypatch.setattr(
        contract_module,
        "_run_git",
        lambda _repo, *args: (
            f"{contract.baseline_sha}\n"
            if args[0] == "rev-parse"
            else "2\n"
            if args[0] == "rev-list"
            else ""
        ),
    )
    with pytest.raises(ContractError, match="exactly one commit"):
        validate_candidate_diff(contract, Path("."))


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_candidate_mutation_rejects_symlinks_and_gitlinks(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    contract = _contract()

    def git_with_mode(_repo: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return f"{contract.baseline_sha}\n"
        if args[0] == "rev-list":
            return "1\n"
        if args[0] == "diff":
            return "1\t1\tcore/agent/verify.py\0"
        if args[0] == "ls-tree":
            return f"{mode} object deadbeef\tcore/agent/verify.py\0"
        return ""

    monkeypatch.setattr(contract_module, "_run_git", git_with_mode)
    with pytest.raises(ContractError, match="regular tracked file"):
        validate_candidate_diff(contract, Path("."))
