#!/usr/bin/env python3
"""Validate the v2 example → rollout → trajectory → reward learning view."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.hooks.llm_observation import route_check
from evals.collection_protocol import REPEAT_MINIMUMS
from scripts.eval import contract

# Accepted record schemas per file. v2 adds policy/sampling identity, label
# hygiene, grader kinds, and split/terms metadata; v1 views stay readable.
SCHEMAS = {
    "examples": {
        "geode.eval-example@1": "example.schema.json",
        "geode.eval-example@2": "example-v2.schema.json",
    },
    "rollouts": {
        "geode.eval-rollout@1": "rollout.schema.json",
        "geode.eval-rollout@2": "rollout-v2.schema.json",
    },
    "rewards": {
        "geode.eval-reward@1": "reward.schema.json",
        "geode.eval-reward@2": "reward-v2.schema.json",
    },
}
# Output terms that keep an example out of the train split.
_TRAIN_BLOCKING_TERMS = {"prohibited", "unknown"}


def _resolve(base: Path, value: str, *, label: str) -> Path:
    contract._validate_relative_reference(value, label=label)
    path = (base / value).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"{label}: path escapes manifest directory")
    if not path.is_file():
        raise ValueError(f"{label}: file does not exist: {value}")
    return path


def _jsonl(path: Path, schema: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}:{line_number}: blank JSONL row")
        value = contract._strict_json_loads(line, label=f"{path}:{line_number}")
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected object")
        contract._validate_schema(value, schema, label=f"{path}:{line_number}")
        rows.append(value)
    return rows


def _artifact(base: Path, ref: dict[str, Any], *, label: str) -> Path:
    path = _resolve(base, str(ref["path"]), label=label)
    if contract._sha256(path) != ref["sha256"]:
        raise ValueError(f"{label}: SHA-256 mismatch")
    return path


def _unique(rows: list[dict[str, Any]], key: str, *, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row[key])
        if value in indexed:
            raise ValueError(f"{label}: duplicate {key}: {value}")
        indexed[value] = row
    return indexed


def _check_splits(examples: dict[str, dict[str, Any]]) -> None:
    """Keep one source task in one split; keep eval sets and blocked terms out of train.

    Arms, repetitions, and retries share their ``example_id``, so this check
    covers them through the example. Examples that share a source task or a
    family must also agree, or a near-duplicate leaks across the boundary.
    """
    seen: dict[tuple[str, str], str] = {}
    for example_id, example in examples.items():
        if example["schema_version"] != 2:
            continue
        split = example["split"]
        for key in (
            ("source_task", f"{example['suite']}/{example['source_task_id']}"),
            ("family", example["family_id"]),
        ):
            other = seen.setdefault(key, split)
            if other != split:
                raise ValueError(
                    f"example {example_id}: {key[0]} {key[1]} spans {other} and {split}"
                )
        if split == "train" and example["benchmark_eval_set"]:
            raise ValueError(f"example {example_id}: public benchmark eval items cannot be train")
        if split == "train" and example["output_terms"]["training_use"] in _TRAIN_BLOCKING_TERMS:
            raise ValueError(f"example {example_id}: output terms do not admit training use")


def _check_rollout_v2(rollout_id: str, rollout: dict[str, Any]) -> None:
    policy, sampling = rollout["policy"], rollout["sampling"]
    check = route_check(policy["model_requested"], policy["model_served"])
    if check == "mismatch" and rollout["validity"] == "valid":
        raise ValueError(f"rollout {rollout_id}: served model differs from requested model")
    if sampling["repetition_index"] >= sampling["k_planned"]:
        raise ValueError(f"rollout {rollout_id}: repetition_index must be below k_planned")
    minimum = REPEAT_MINIMUMS[sampling["repetition_purpose"]]
    if sampling["k_planned"] < minimum:
        raise ValueError(
            f"rollout {rollout_id}: {sampling['repetition_purpose']} needs k_planned >= {minimum}"
        )


def validate_learning_view(path: Path) -> dict[str, int | str]:
    path = path.resolve()
    manifest = contract._load_json_object(path)
    contract._validate_schema(
        manifest,
        "learning-view-manifest.schema.json",
        label=str(path),
    )
    base = path.parent
    loaded: dict[str, list[dict[str, Any]]] = {}
    for name, accepted in SCHEMAS.items():
        ref = manifest["files"][name]
        schema_file = accepted.get(ref["record_schema"])
        if schema_file is None:
            raise ValueError(f"{path}: {name} record_schema must be one of {sorted(accepted)}")
        record_file = _artifact(base, ref, label=f"{path}:{name}")
        rows = _jsonl(record_file, schema_file)
        if len(rows) != ref["rows"]:
            raise ValueError(f"{path}: {name} row count mismatch")
        loaded[name] = rows

    examples = _unique(loaded["examples"], "example_id", label="examples")
    rollouts = _unique(loaded["rollouts"], "rollout_id", label="rollouts")
    rewards = _unique(loaded["rewards"], "reward_id", label="rewards")
    _check_splits(examples)
    for rollout_id, rollout in rollouts.items():
        if rollout["schema_version"] == 2:
            _check_rollout_v2(rollout_id, rollout)

    rewarded_rollouts: set[str] = set()
    for rollout_id, rollout in rollouts.items():
        example_id = str(rollout["example_id"])
        if example_id not in examples:
            raise ValueError(f"rollout {rollout_id}: unknown example_id {example_id}")
        if rollout["run_id"] != manifest["run_id"]:
            raise ValueError(f"rollout {rollout_id}: run_id does not match manifest")
        selected = rollout["selected_attempt_id"]
        if selected is not None and selected not in rollout["rollout_attempt_ids"]:
            raise ValueError(f"rollout {rollout_id}: selected attempt is outside retry lineage")

        trajectory_path = _artifact(
            base,
            rollout["trajectory"],
            label=f"rollout {rollout_id}:trajectory",
        )
        trajectory = contract._load_json_object(trajectory_path)
        from core.observability.record_schema import validate_record
        from core.observability.trajectory import verify_trajectory_integrity

        validate_record(trajectory, schema_id="geode.trajectory@1")
        verify_trajectory_integrity(trajectory)
        if trajectory["trajectory_id"] != rollout["trajectory"]["trajectory_id"]:
            raise ValueError(f"rollout {rollout_id}: trajectory_id mismatch")
        available_sessions = {
            str(event["session_id"]) for event in trajectory["events"] if event["session_id"]
        }
        parents = trajectory["source"].get("parents") or []
        available_sessions.update(str(parent) for parent in parents)
        requested_sessions = set(rollout["trajectory"]["session_ids"])
        if not requested_sessions.issubset(available_sessions):
            raise ValueError(f"rollout {rollout_id}: trajectory session scope is not present")

        native_path = _artifact(
            base,
            rollout["native_result"],
            label=f"rollout {rollout_id}:native_result",
        )
        native = contract._strict_json_loads(
            native_path.read_text(encoding="utf-8"), label=str(native_path)
        )
        contract._resolve_json_pointer(
            native,
            rollout["native_result"]["source_locator"],
            label=f"rollout {rollout_id}:native_result",
        )

    reward_targets: set[tuple[str, str, str]] = set()
    for reward_id, reward in rewards.items():
        rollout_id = str(reward["rollout_id"])
        target_rollout = rollouts.get(rollout_id)
        if target_rollout is None:
            raise ValueError(f"reward {reward_id}: unknown rollout_id {rollout_id}")
        if reward["example_id"] != target_rollout["example_id"]:
            raise ValueError(f"reward {reward_id}: example_id does not match rollout")
        if target_rollout["validity"] != "valid" or not target_rollout["selected_for_reward"]:
            raise ValueError(f"reward {reward_id}: rollout is not reward-admitted")
        evaluator = reward["evaluator"]
        target = (rollout_id, str(evaluator["name"]), str(evaluator["revision"]))
        if target in reward_targets:
            raise ValueError(f"reward {reward_id}: duplicate evaluator target")
        reward_targets.add(target)
        rewarded_rollouts.add(rollout_id)

        source_path = _artifact(base, reward["source"], label=f"reward {reward_id}:source")
        source_payload = contract._strict_json_loads(
            source_path.read_text(encoding="utf-8"), label=str(source_path)
        )
        observed = contract._resolve_json_pointer(
            source_payload,
            reward["source"]["source_locator"],
            label=f"reward {reward_id}:source",
        )
        if reward["measurement_status"] == "measured" and not contract._metric_values_match(
            reward["value"], observed
        ):
            raise ValueError(f"reward {reward_id}: value does not match evaluator source")

    expected_rewards = {
        rollout_id for rollout_id, rollout in rollouts.items() if rollout["selected_for_reward"]
    }
    if expected_rewards != rewarded_rollouts:
        raise ValueError("reward coverage does not match selected_for_reward rollouts")
    return {
        "run_id": str(manifest["run_id"]),
        "examples": len(examples),
        "rollouts": len(rollouts),
        "rewards": len(rewards),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = validate_learning_view(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"learning-view error: {exc}")
        raise SystemExit(1) from exc
    message = "learning view OK: {run_id} examples={examples} rollouts={rollouts} rewards={rewards}"
    print(message.format(**result))


if __name__ == "__main__":
    main()
