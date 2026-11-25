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


# --- v2 records -------------------------------------------------------------


def _rewrite(tmp_path: Path, manifest: Path, name: str, rows: list[dict[str, object]]) -> None:
    path = tmp_path / f"{name}.jsonl"
    _write_jsonl(path, rows)
    payload = json.loads(manifest.read_text())
    entry = payload["files"][name]
    entry.update(sha256=_sha(path), rows=len(rows), record_schema=rows[0]["schema_id"])
    _write_json(manifest, payload)


def _v2_example(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_id": "geode.eval-example@2",
        "schema_version": 2,
        "example_id": "fixture.task-1",
        "suite": "fixture",
        "dataset": {"name": "fixture", "revision": "1"},
        "source_task_id": "task-1",
        "stratum_id": None,
        "input_sha256": "a" * 64,
        "split": "train",
        "family_id": "family-1",
        "source_benchmark": None,
        "benchmark_eval_set": False,
        "license": "MIT",
        "redistribution": "public",
        "canary": None,
        "output_terms": {"provider": "none", "training_use": "permitted", "terms_ref": None},
    }
    row.update(overrides)
    return row


def _v2_rollout(tmp_path: Path, **overrides: object) -> dict[str, object]:
    row = json.loads((tmp_path / "rollouts.jsonl").read_text())
    if row["schema_version"] == 1:
        del row["seed"]
        row.update(
            schema_id="geode.eval-rollout@2",
            schema_version=2,
            policy={
                "model_requested": "gpt-5.5",
                "model_served": "gpt-5.5",
                "provider": "openai",
                "source": "codex-oauth",
                "effort": "high",
                "geode_revision": "b" * 40,
                "candidate_patch_sha256": None,
                "system_prompt_sha256": "c" * 64,
                "tool_schema_sha256": "d" * 64,
            },
            user_simulator=None,
            environment={
                "harness_revision": "fixture-1",
                "task_content_sha256": "e" * 64,
                "max_steps": 30,
                "timeout_seconds": 600,
                "max_errors": 10,
                "reset_identity": None,
            },
            sampling={
                "harness_seed": 300,
                "provider_seed": "not-sent",
                "repetition_purpose": "evaluation-gate",
                "repetition_index": 0,
                "k_planned": 3,
            },
            outcome={"agent_completed": True, "verifier_pass": True},
            label_hygiene={
                "detector": "geode.contamination-detector@1",
                "validity": "valid",
                "flags": [],
            },
            invalid_reason=None,
        )
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(row.get(key), dict):
            row[key] = {**row[key], **value}
        else:
            row[key] = value
    return row


def _v2_reward(tmp_path: Path, **component: object) -> dict[str, object]:
    row = json.loads((tmp_path / "rewards.jsonl").read_text())
    row.update(
        schema_id="geode.eval-reward@2",
        schema_version=2,
        components={
            "db": {
                "value": 1.0,
                "grader_kind": "code",
                "grader_id": "tau2-db-check",
                "grader_stochastic": False,
                **component,
            }
        },
    )
    return row


def _v2_fixture(tmp_path: Path) -> Path:
    manifest = _fixture(tmp_path)
    _rewrite(tmp_path, manifest, "rewards", [_v2_reward(tmp_path)])
    _rewrite(tmp_path, manifest, "rollouts", [_v2_rollout(tmp_path)])
    _rewrite(tmp_path, manifest, "examples", [_v2_example()])
    return manifest


def test_learning_view_accepts_v2_records(tmp_path: Path) -> None:
    assert validate_learning_view(_v2_fixture(tmp_path))["rollouts"] == 1


@pytest.mark.parametrize(
    ("name", "rows", "match"),
    [
        (
            "examples",
            lambda _p: [_v2_example(benchmark_eval_set=True)],
            "eval items cannot be train",
        ),
        (
            "examples",
            lambda _p: [
                _v2_example(
                    output_terms={"provider": "x", "training_use": "unknown", "terms_ref": None}
                )
            ],
            "output terms",
        ),
        (
            "examples",
            lambda _p: [
                _v2_example(),
                _v2_example(example_id="fixture.task-2", source_task_id="task-2", split="sealed"),
            ],
            "family family-1 spans train and sealed",
        ),
        (
            "rollouts",
            lambda p: [_v2_rollout(p, policy={"model_served": "gpt-5.4"})],
            "served model differs",
        ),
        (
            "rollouts",
            lambda p: [_v2_rollout(p, sampling={"k_planned": 1})],
            "evaluation-gate needs k_planned >= 3",
        ),
        (
            "rollouts",
            lambda p: [
                _v2_rollout(
                    p,
                    label_hygiene={
                        "validity": "invalid",
                        "flags": [
                            {"kind": "harness_error_text", "message_index": 1, "role": "user"}
                        ],
                    },
                )
            ],
            "schema|valid",
        ),
        (
            "rewards",
            lambda p: [_v2_reward(p, grader_kind="model", grader_stochastic=False)],
            "schema|True",
        ),
    ],
)
def test_learning_view_v2_admission_rejects(
    tmp_path: Path, name: str, rows: object, match: str
) -> None:
    manifest = _v2_fixture(tmp_path)
    _rewrite(tmp_path, manifest, name, rows(tmp_path))  # type: ignore[operator]
    with pytest.raises(ValueError, match=match):
        validate_learning_view(manifest)
