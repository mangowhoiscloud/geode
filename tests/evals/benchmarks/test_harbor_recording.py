from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evals.platforms.harbor import (
    backfill_harbor_recordings,
    write_harbor_recording,
)


def _trajectory(path: Path) -> Path:
    path.parent.mkdir(parents=True)
    payload = {
        "schema_version": "ATIF-v1.7",
        "trajectory_id": "trial-1",
        "agent": {"name": "codex"},
        "steps": [
            {
                "step_id": 1,
                "timestamp": "2026-09-03T00:00:00Z",
                "source": "user",
                "message": "fix the task",
            },
            {
                "step_id": 2,
                "timestamp": "2026-09-03T00:00:02Z",
                "source": "agent",
                "message": "private reasoning must not be replayed",
                "reasoning_content": "also private",
                "tool_calls": [
                    {
                        "tool_call_id": "call-1",
                        "function_name": "exec",
                        "arguments": {"command": "pwd"},
                    }
                ],
                "observation": {
                    "results": [
                        {
                            "source_call_id": "call-1",
                            "content": "/app sk-proj-abcdefghijklmnopqrstuvwxyz123456",
                        }
                    ]
                },
            },
            {
                "step_id": 3,
                "timestamp": "invalid",
                "source": "agent",
                "message": "done",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_recording_reconstructs_atif_without_reasoning_or_secrets(tmp_path: Path) -> None:
    trajectory_path = _trajectory(tmp_path / "job" / "trial" / "agent" / "trajectory.json")
    receipt = write_harbor_recording(trajectory_path)

    assert receipt is not None
    cast_path = trajectory_path.with_name("recording.cast")
    lines = [json.loads(line) for line in cast_path.read_text().splitlines()]
    assert lines[0]["version"] == 2
    assert lines[0]["env"]["GEODE_RECORDING_PROVENANCE"] == "trajectory-reconstruction"
    assert [event[0] for event in lines[1:]] == sorted(event[0] for event in lines[1:])
    replay = "".join(event[2] for event in lines[1:])
    assert "fix the task" in replay
    assert "[exec]" in replay and "pwd" in replay and "/app" in replay
    assert "[REDACTED]" in replay and "sk-proj-" not in replay
    assert "private reasoning" not in replay and "also private" not in replay
    assert "done" in replay
    assert receipt["source"]["sha256"] == hashlib.sha256(trajectory_path.read_bytes()).hexdigest()
    assert receipt["timing"]["synthetic_timestamp_count"] == 1
    assert receipt["score_authority"] is False


def test_backfill_preserves_existing_recording(tmp_path: Path) -> None:
    first = _trajectory(tmp_path / "one" / "agent" / "trajectory.json")
    second = _trajectory(tmp_path / "two" / "agent" / "trajectory.json")
    first.with_name("recording.cast").write_text("native", encoding="utf-8")

    dry_run = backfill_harbor_recordings(tmp_path, dry_run=True)
    assert dry_run == {
        "trajectories": 2,
        "eligible": 1,
        "created": 0,
        "existing": 1,
        "failed": 0,
    }

    summary = backfill_harbor_recordings(tmp_path)
    assert summary == {
        "trajectories": 2,
        "eligible": 1,
        "created": 1,
        "existing": 1,
        "failed": 0,
    }
    assert first.with_name("recording.cast").read_text() == "native"
    assert second.with_name("recording.receipt.json").is_file()
