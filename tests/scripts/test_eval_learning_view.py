from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from core.observability.trajectory import build_trajectory
from scripts.eval.learning_view import validate_learning_view


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> Path:
    native = tmp_path / "native.json"
    _write_json(native, {"simulations": [{"reward": 1.0}]})
    trajectory = tmp_path / "trajectory.json"
    _write_json(
        trajectory,
        build_trajectory(
            trajectory_id="trajectory-1",
            source={"harness": "fixture", "session": "run-1", "parents": ["session-1"]},
            events=[
                {
                    "kind": "fixture.event",
                    "actor": "agent",
                    "session_id": "session-1",
                    "payload": {"ok": True},
                }
            ],
            outcome={},
            provenance={},
            privacy={},
            captured_at="2026-08-25T00:00:00Z",
        ),
    )
    examples = tmp_path / "examples.jsonl"
    _write_jsonl(
        examples,
        [
            {
                "schema_id": "geode.eval-example@1",
                "schema_version": 1,
                "example_id": "fixture.task-1",
                "suite": "fixture",
                "dataset": {"name": "fixture", "revision": "1"},
                "source_task_id": "task-1",
                "stratum_id": None,
                "input_sha256": "a" * 64,
            }
        ],
    )
    rollouts = tmp_path / "rollouts.jsonl"
    _write_jsonl(
        rollouts,
        [
            {
                "schema_id": "geode.eval-rollout@1",
                "schema_version": 1,
                "run_id": "run-1",
                "rollout_id": "run-1.task-1.0",
                "example_id": "fixture.task-1",
                "rollout_index": 0,
                "seed": 7,
                "policy": {
                    "model": "fixture",
                    "provider": "none",
                    "source": "local",
                    "effort": "none",
                    "geode_revision": "b" * 40,
                },
                "rollout_attempt_ids": ["attempt-1"],
                "selected_attempt_id": "attempt-1",
                "trajectory": {
                    "path": trajectory.name,
                    "sha256": _sha(trajectory),
                    "trajectory_id": "trajectory-1",
                    "session_ids": ["session-1"],
                },
                "native_result": {
                    "path": native.name,
                    "sha256": _sha(native),
                    "source_locator": "/simulations/0",
                },
                "timing": {
                    "started_at": "2026-08-25T00:00:00Z",
                    "finished_at": "2026-08-25T00:00:01Z",
                    "wall_seconds": 1.0,
                },
                "validity": "valid",
                "termination_reason": "completed",
                "selected_for_reward": True,
            }
        ],
    )
    rewards = tmp_path / "rewards.jsonl"
    _write_jsonl(
        rewards,
        [
            {
                "schema_id": "geode.eval-reward@1",
                "schema_version": 1,
                "reward_id": "reward.run-1.task-1.0",
                "rollout_id": "run-1.task-1.0",
                "example_id": "fixture.task-1",
                "evaluator": {"name": "fixture", "revision": "1", "authority": "suite-native"},
                "measurement_status": "measured",
                "value": 1.0,
                "components": {},
                "source": {
                    "path": native.name,
                    "sha256": _sha(native),
                    "source_locator": "/simulations/0/reward",
                },
                "created_at": "2026-08-25T00:00:02Z",
            }
        ],
    )
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {
            "schema_id": "geode.eval-learning-view@2",
            "schema_version": 2,
            "run_id": "run-1",
            "created_at": "2026-08-25T00:00:03Z",
            "record_order": ["example", "rollout", "trajectory", "reward"],
            "files": {
                name: {
                    "path": path.name,
                    "sha256": _sha(path),
                    "rows": 1,
                    "record_schema": schema,
                }
                for name, path, schema in (
                    ("examples", examples, "geode.eval-example@1"),
                    ("rollouts", rollouts, "geode.eval-rollout@1"),
                    ("rewards", rewards, "geode.eval-reward@1"),
                )
            },
        },
    )
    return manifest


def test_learning_view_validates_closed_joins(tmp_path: Path) -> None:
    assert validate_learning_view(_fixture(tmp_path)) == {
        "run_id": "run-1",
        "examples": 1,
        "rollouts": 1,
        "rewards": 1,
    }


def test_learning_view_rejects_reward_for_invalid_rollout(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    rollouts = tmp_path / "rollouts.jsonl"
    row = json.loads(rollouts.read_text())
    row["validity"] = "invalid"
    row["selected_attempt_id"] = None
    row["selected_for_reward"] = False
    _write_jsonl(rollouts, [row])
    payload = json.loads(manifest.read_text())
    payload["files"]["rollouts"]["sha256"] = _sha(rollouts)
    _write_json(manifest, payload)
    with pytest.raises(ValueError, match=r"not reward-admitted|coverage"):
        validate_learning_view(manifest)
