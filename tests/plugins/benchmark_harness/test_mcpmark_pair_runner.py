from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.observability.trajectory import build_trajectory
from plugins.benchmark_harness import run_mcpmark_pair as pair


def _fixture(category: str = "desktop") -> dict[str, object]:
    return {
        "categories": [
            {
                "category": category,
                "file_count": 1,
                "bytes": 1,
                "sha256": "a" * 64,
            }
        ],
        "aggregate_sha256": "b" * 64,
    }


def _write_native(
    native_dir: Path,
    *,
    task: str,
    arm: str,
    model: str,
    effort: str,
    timeout: int,
    timed_surface: str = "adapter_execute_entry_through_native_runtime_return",
) -> None:
    task_dir = native_dir / "run" / "model__filesystem" / "run-1" / "desktop__task"
    task_dir.mkdir(parents=True)
    (task_dir / "meta.json").write_text(
        json.dumps(
            {
                "task_name": task.replace("/", "__"),
                "model_name": model,
                "reasoning_effort": effort,
                "mcp": "filesystem",
                "timeout": timeout,
                "execution_result": {
                    "success": True,
                    "error_message": None,
                    "verification_output": "PASS",
                },
            }
        ),
        encoding="utf-8",
    )
    (task_dir.parent / "summary.json").write_text(
        json.dumps(
            {
                "total_tasks": 1,
                "successful_tasks": 1,
                "failed_tasks": 0,
                "model_config": {"model_name": model, "agent_name": arm},
            }
        ),
        encoding="utf-8",
    )
    trajectory = build_trajectory(
        trajectory_id=f"test-{arm}",
        source={
            "harness": "mcpmark",
            "run": f"run-{arm}",
            "session": f"session-{arm}",
            "task": "c" * 64,
            "parents": [],
        },
        events=[
            {
                "kind": "user_message",
                "actor": "user",
                "turn_id": "turn-1",
                "payload": {"content": "task"},
            },
            {
                "kind": "assistant_message",
                "actor": "assistant",
                "turn_id": "turn-1",
                "payload": {"content": "done"},
            },
        ],
        outcome={"success": True},
        provenance={
            "model": model.removeprefix(f"{arm}-"),
            "source": "subscription",
            "effort": effort,
        },
        privacy={"review_state": "local"},
    )
    (task_dir / "execution.trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    (task_dir / "execution.deadline.json").write_text(
        json.dumps(
            {
                "schema_id": "geode.mcpmark.execution_deadline@1",
                "arm": arm,
                "timeout_owner": "adapter",
                "timed_surface": timed_surface,
                "clock": "monotonic",
                "limit_seconds": float(timeout),
                "action_started_monotonic": 100.0,
                "action_deadline_monotonic": 100.0 + timeout,
                "action_finished_monotonic": 101.0,
                "action_elapsed_seconds": 1.0,
                "expired": False,
                "action_status": "complete",
                "cleanup_grace_seconds": 5.0,
                "cleanup_elapsed_seconds": 0.1,
                "cleanup_status": "complete",
                "evidence_status": "written",
                "started_at_unix_seconds": 1_000.0,
                "finished_at_unix_seconds": 1_002.0,
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "messages.json").write_text("[]", encoding="utf-8")
    (task_dir / "execution.log").write_text("[]", encoding="utf-8")


def test_filesystem_30_order_and_hash_are_frozen() -> None:
    assert pair.EXPECTED_FS30_SHA256 == (
        "50483308573ce407abaf0700885d56c6df0453557669dddce9edcece83710433"
    )
    assert pair._arm_order(1) == ("geode", "codex")
    assert pair._arm_order(2) == ("codex", "geode")
    patch = Path(pair.__file__).with_name("patches") / (
        "mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch"
    )
    assert pair._sha256(patch) == pair.PATCH_SHA256


def test_pair_runner_is_serial_counterbalanced_and_uses_fresh_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    fixture_dir = root / "test_environments/desktop"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "seed").write_text("x", encoding="utf-8")
    ids = ("desktop/first", "desktop/second")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        native_dir = kwargs["native_dir"]
        log_dir = kwargs["log_dir"]
        assert isinstance(native_dir, Path) and not native_dir.exists()
        assert isinstance(log_dir, Path) and not log_dir.exists()
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("ok", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        arm = str(kwargs["arm"])
        task = str(kwargs["task"])
        _write_native(
            native_dir,
            task=task,
            arm=arm,
            model=f"{arm}-gpt-5.4",
            effort="high",
            timeout=1200,
        )
        calls.append((task, arm))
        return 0, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    pair._run_tasks(
        output_dir=output,
        mcpmark_root=root,
        python=Path("python"),
        ids=ids,
        fixture=_fixture(),
        run_id="paired-test",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
    )

    assert calls == [
        ("desktop/first", "geode"),
        ("desktop/first", "codex"),
        ("desktop/second", "codex"),
        ("desktop/second", "geode"),
    ]
    rows = [json.loads(line) for line in (output / "runner-events.jsonl").read_text().splitlines()]
    assert [row["sequence"] for row in rows] == list(range(len(rows)))
    assert rows[0]["event"] == "run_started"
    assert rows[-1] == {
        **rows[-1],
        "event": "run_completed",
        "completed_tasks": 2,
        "completed_arms": 4,
    }


def test_pair_runner_stops_before_the_next_arm_on_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])
    calls = 0

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        nonlocal calls
        calls += 1
        log_dir = kwargs["log_dir"]
        assert isinstance(log_dir, Path)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("failed", encoding="utf-8")
        return 9, stdout, stderr

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    with pytest.raises(pair.PairRunError, match="exited 9"):
        pair._run_tasks(
            output_dir=output,
            mcpmark_root=root,
            python=Path("python"),
            ids=("desktop/first",),
            fixture=_fixture(),
            run_id="paired-test",
            model_label="gpt-5.4",
            effort="high",
            timeout=1200,
        )

    assert calls == 1
    rows = [json.loads(line) for line in (output / "runner-events.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "run_stopped"
    assert rows[-1]["failure_class"] == "infrastructure"


def test_pair_runner_refuses_preexisting_fixture_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / ".mcpmark_backups/stale").mkdir(parents=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])
    with pytest.raises(pair.PairRunError, match="not empty before"):
        pair._run_tasks(
            output_dir=output,
            mcpmark_root=root,
            python=Path("python"),
            ids=("desktop/first",),
            fixture=_fixture(),
            run_id="paired-test",
            model_label="gpt-5.4",
            effort="high",
            timeout=1200,
        )


def test_pair_runner_rejects_an_exception_shaped_verifier_receipt(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
    )
    meta_path = next(native.rglob("meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["execution_result"]["verification_error"] = (
        "Traceback (most recent call last):\nFileNotFoundError"
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="exception traceback"):
        pair._native_receipt(
            native,
            task="desktop/task",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
        )


def test_pair_runner_refuses_an_existing_attempt_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setattr(pair, "_validate_checkout", lambda _root: None)
    with pytest.raises(pair.PairRunError, match="must not exist"):
        pair.run_pair(
            run_spec_path=tmp_path / "run-spec.json",
            mcpmark_root=tmp_path / "mcpmark",
            output_dir=output,
            python=Path("python"),
        )


def test_pair_runner_freezes_the_validated_run_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "prospective.json"
    spec_path.write_bytes(b'{"frozen":true}\n')
    output = tmp_path / "attempt"
    monkeypatch.setattr(pair, "_validate_checkout", lambda _root: None)
    monkeypatch.setattr(pair, "_discover_workload", lambda _root: ("desktop/first",))
    monkeypatch.setattr(pair, "_fixture_receipt", lambda *_args: _fixture())
    monkeypatch.setattr(
        pair,
        "_validate_spec",
        lambda *_args, **_kwargs: {
            "run_id": "paired-test",
            "reproduction": {
                "execution": {"timeout_seconds": 1200},
                "model": {"label": "gpt-5.4", "route": "subscription", "reasoning": "high"},
                "geode": {"revision": "abc"},
                "harness": {"revision": "def"},
            },
        },
    )
    monkeypatch.setattr(pair, "_run_tasks", lambda **_kwargs: None)

    pair.run_pair(
        run_spec_path=spec_path,
        mcpmark_root=tmp_path / "mcpmark",
        output_dir=output,
        python=Path("python"),
    )

    assert (output / "run-spec.json").read_bytes() == spec_path.read_bytes()


def test_append_event_flushes_with_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(pair.os, "fsync", calls.append)
    path = tmp_path / "events.jsonl"
    pair._append_event(path, {"event": "started"})
    assert calls
    assert json.loads(path.read_text(encoding="utf-8")) == {"event": "started"}


def test_deadline_receipt_fails_closed_on_a_different_surface(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        timed_surface="loop_only",
    )
    path = next(native.rglob("execution.deadline.json"))
    with pytest.raises(pair.PairRunError, match="identity mismatch"):
        pair._deadline_receipt(path, arm="geode", timeout=1200)
