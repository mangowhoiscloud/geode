#!/usr/bin/env python3
"""Project Harbor or tau2 native output into the GEODE v2 learning view."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.eval.learning_view import validate_learning_view


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sessions(trajectory: dict[str, Any]) -> list[str]:
    values = {str(value) for value in trajectory["source"].get("parents") or []}
    values.update(
        str(event["session_id"]) for event in trajectory["events"] if event.get("session_id")
    )
    return sorted(values)


def _wall_seconds(started_at: str, finished_at: str) -> float:
    elapsed = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    return elapsed.total_seconds()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def _harbor(root: Path, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], ...]:
    examples: list[dict[str, Any]] = []
    rollouts: list[dict[str, Any]] = []
    rewards: list[dict[str, Any]] = []
    revision = spec["reproduction"]["harness"]["revision"]
    for native_path in sorted((root / "native" / "harbor").glob("*/result.json")):
        native = _load(native_path)
        task_id = str(native["task_name"])
        slug = _slug(task_id.removeprefix("terminal-bench/"))
        example_id = f"tb21.{slug}"
        rollout_id = f"{spec['run_id']}.{slug}.0"
        trajectory_path = native_path.parent / "agent" / "geode-trajectory.json"
        trajectory = _load(trajectory_path)
        started = str(native["started_at"])
        finished = str(native["finished_at"])
        attempt_id = str(native["trial_name"])
        native_ref = {
            "path": _relative(root, native_path),
            "sha256": _sha(native_path),
            "source_locator": "/verifier_result/rewards/reward",
        }
        examples.append(
            {
                "schema_id": "geode.eval-example@1",
                "schema_version": 1,
                "example_id": example_id,
                "suite": "terminal-bench-2.1",
                "dataset": {
                    "name": spec["reproduction"]["harness"]["source"],
                    "revision": revision,
                },
                "source_task_id": task_id,
                "stratum_id": None,
                "input_sha256": str(native["task_checksum"]),
            }
        )
        rollouts.append(
            {
                "schema_id": "geode.eval-rollout@1",
                "schema_version": 1,
                "run_id": spec["run_id"],
                "rollout_id": rollout_id,
                "example_id": example_id,
                "rollout_index": 0,
                "seed": spec["reproduction"]["execution"]["seed_schedule"][0],
                "policy": {
                    "model": spec["reproduction"]["model"]["label"],
                    "provider": spec["reproduction"]["model"]["provider"],
                    "source": spec["reproduction"]["model"]["route"],
                    "effort": "max",
                    "geode_revision": spec["reproduction"]["geode"]["revision"],
                },
                "rollout_attempt_ids": [attempt_id],
                "selected_attempt_id": attempt_id,
                "trajectory": {
                    "path": _relative(root, trajectory_path),
                    "sha256": _sha(trajectory_path),
                    "trajectory_id": trajectory["trajectory_id"],
                    "session_ids": _sessions(trajectory),
                },
                "native_result": native_ref,
                "timing": {
                    "started_at": started,
                    "finished_at": finished,
                    "wall_seconds": _wall_seconds(started, finished),
                },
                "validity": "valid",
                "termination_reason": native["agent_result"]["metadata"]["termination_reason"],
                "selected_for_reward": True,
            }
        )
        rewards.append(
            {
                "schema_id": "geode.eval-reward@1",
                "schema_version": 1,
                "reward_id": f"{rollout_id}.terminal-bench",
                "rollout_id": rollout_id,
                "example_id": example_id,
                "evaluator": {
                    "name": "terminal-bench-2.1",
                    "revision": revision,
                    "authority": "suite-native",
                },
                "measurement_status": "measured",
                "value": native["verifier_result"]["rewards"]["reward"],
                "components": {},
                "source": native_ref,
                "created_at": finished,
            }
        )
    return examples, rollouts, rewards


def _tau2(root: Path, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], ...]:
    grouped: dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for native_path in sorted((root / "native" / "simulations").glob("*/results.json")):
        native = _load(native_path)
        domain = str(native["info"]["environment_info"]["domain_name"])
        task_id = str(native["tasks"][0]["id"])
        grouped.setdefault((domain, task_id), []).append((native_path, native))

    examples: list[dict[str, Any]] = []
    rollouts: list[dict[str, Any]] = []
    rewards: list[dict[str, Any]] = []
    revision = spec["reproduction"]["harness"]["revision"]
    for (domain, task_id), attempts in sorted(grouped.items()):
        selected = next(
            (
                item
                for item in reversed(attempts)
                if item[1]["simulations"][0]["reward_info"] is not None
                and item[1]["simulations"][0]["reward_info"].get("reward") is not None
            ),
            None,
        )
        if selected is None:
            continue
        native_path, native = selected
        simulation = native["simulations"][0]
        task = native["tasks"][0]
        selected_run_id = native_path.parent.name
        trajectory_path = (
            root / "native" / "trajectories" / f"{selected_run_id}.geode-trajectory.json"
        )
        trajectory = _load(trajectory_path)
        selected_manifest = _load(
            root / "native" / "trajectories" / f"{selected_run_id}.attempt-manifest.json"
        )
        selected_attempt_id = str(selected_manifest["final_results"][0]["selected_attempt_id"])
        lineage: list[str] = []
        for attempt_path, _ in attempts:
            manifest_name = f"{attempt_path.parent.name}.attempt-manifest.json"
            manifest_path = root / "native" / "trajectories" / manifest_name
            lineage.extend(str(row["attempt_id"]) for row in _load(manifest_path)["attempts"])
        slug = _slug(f"{domain}-{task_id}")
        example_id = f"tau2.{slug}"
        rollout_id = f"{spec['run_id']}.{slug}.0"
        native_ref = {
            "path": _relative(root, native_path),
            "sha256": _sha(native_path),
            "source_locator": "/simulations/0/reward_info/reward",
        }
        started = f"{simulation['start_time']}+09:00"
        finished = f"{simulation['end_time']}+09:00"
        examples.append(
            {
                "schema_id": "geode.eval-example@1",
                "schema_version": 1,
                "example_id": example_id,
                "suite": "tau2-1.0.1",
                "dataset": {"name": "sierra-research/tau2-bench", "revision": revision},
                "source_task_id": task_id,
                "stratum_id": domain,
                "input_sha256": _canonical_sha(task),
            }
        )
        rollouts.append(
            {
                "schema_id": "geode.eval-rollout@1",
                "schema_version": 1,
                "run_id": spec["run_id"],
                "rollout_id": rollout_id,
                "example_id": example_id,
                "rollout_index": 0,
                "seed": selected_manifest["attempts"][0]["seed"],
                "policy": {
                    "model": spec["reproduction"]["model"]["label"],
                    "provider": spec["reproduction"]["model"]["provider"],
                    "source": spec["reproduction"]["model"]["route"],
                    "effort": "max",
                    "geode_revision": spec["reproduction"]["geode"]["revision"],
                },
                "rollout_attempt_ids": lineage,
                "selected_attempt_id": selected_attempt_id,
                "trajectory": {
                    "path": _relative(root, trajectory_path),
                    "sha256": _sha(trajectory_path),
                    "trajectory_id": trajectory["trajectory_id"],
                    "session_ids": _sessions(trajectory),
                },
                "native_result": native_ref,
                "timing": {
                    "started_at": started,
                    "finished_at": finished,
                    "wall_seconds": simulation["duration"],
                },
                "validity": "valid",
                "termination_reason": simulation["termination_reason"],
                "selected_for_reward": True,
            }
        )
        reward_info = simulation["reward_info"]
        components = {
            key: value
            for key, value in (reward_info.get("reward_breakdown") or {}).items()
            if isinstance(value, (bool, int, float)) or value is None
        }
        rewards.append(
            {
                "schema_id": "geode.eval-reward@1",
                "schema_version": 1,
                "reward_id": f"{rollout_id}.tau2",
                "rollout_id": rollout_id,
                "example_id": example_id,
                "evaluator": {
                    "name": "tau2-bench",
                    "revision": revision,
                    "authority": "suite-native",
                },
                "measurement_status": "measured",
                "value": reward_info["reward"],
                "components": components,
                "source": native_ref,
                "created_at": finished,
            }
        )
    return examples, rollouts, rewards


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("harbor", "tau2"))
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    spec = _load(root / "run-spec.json")
    examples, rollouts, rewards = (
        _harbor(root, spec) if args.suite == "harbor" else _tau2(root, spec)
    )
    files = {
        "examples": ("examples.jsonl", "geode.eval-example@1", examples),
        "rollouts": ("rollouts.jsonl", "geode.eval-rollout@1", rollouts),
        "rewards": ("rewards.jsonl", "geode.eval-reward@1", rewards),
    }
    manifest_files: dict[str, Any] = {}
    for name, (filename, schema, rows) in files.items():
        path = root / filename
        _write_jsonl(path, rows)
        manifest_files[name] = {
            "path": filename,
            "sha256": _sha(path),
            "rows": len(rows),
            "record_schema": schema,
        }
    manifest = {
        "schema_id": "geode.eval-learning-view@2",
        "schema_version": 2,
        "run_id": spec["run_id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "record_order": ["example", "rollout", "trajectory", "reward"],
        "files": manifest_files,
    }
    manifest_path = root / "learning-view-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(validate_learning_view(manifest_path))


if __name__ == "__main__":
    main()
