from __future__ import annotations

import json
import os
import sys
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
    max_tool_result_tokens: int | None = None,
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
    deadline = {
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
    if max_tool_result_tokens is not None:
        deadline["runtime_config"] = {
            "max_tool_result_tokens": max_tool_result_tokens,
            "offload_store_bound": False,
        }
    (task_dir / "execution.deadline.json").write_text(
        json.dumps(deadline),
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
    assert pair._workload_hash(pair.TOOL_CAP_IDS) == pair.TOOL_CAP_SHA256
    assert pair._tool_cap_arm_order(1, 1) == pair.TOOL_CAP_ARMS
    assert pair._tool_cap_arm_order(1, 2) == pair.TOOL_CAP_ARMS[::-1]
    assert pair._tool_cap_arm_order(2, 1) == pair.TOOL_CAP_ARMS[::-1]
    schedule = pair._execution_schedule(pair.TOOL_CAP_PROFILE, pair.TOOL_CAP_IDS)
    assert len(schedule) == 30
    assert {row[4] for row in schedule} == {"geode"}
    assert [(row[2], row[5]) for row in schedule] == [
        (task, cap)
        for repetition in range(1, 4)
        for index, task in enumerate(pair.TOOL_CAP_IDS, start=1)
        for _label, cap in pair._tool_cap_arm_order(index, repetition)
    ]
    patch = Path(pair.__file__).with_name("patches") / (
        "mcpmark-cd45b7f-filesystem-standard-verifier-missing-output.patch"
    )
    assert pair._sha256(patch) == pair.PATCH_SHA256


def test_tool_cap_spec_freezes_model_budget_and_diagnostic_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {
        "preregistration": {"mode": "prospective"},
        "study": {
            "research_question": (
                "Does removing the 25K tool-result guard on the same large-result MCP tasks "
                "increase verifier accuracy and change rereads, fresh input tokens, and wall time?"
            ),
            "hypothesis": (
                "Across 15 task-repetitions per arm, unlimited-0 produces more verifier passes "
                "than guard-25000."
            ),
            "primary_metric": {
                "name": "verifier-pass-rate arm delta",
                "unit": "ratio",
                "direction": "target",
                "aggregation": "(sum(unlimited-0 passes) - sum(guard-25000 passes)) / 15",
                "denominator": 15,
            },
            "decision_rule": (
                "supported if unlimited-0 passes exceed guard-25000 passes; "
                "mixed if equal; not-supported if lower"
            ),
            "invalidation_rule": (
                "Invalidate the run if any attempt changes the frozen deadline or identity "
                "contract, cannot bind the arm cap or reconstruct truncation, fails fixture "
                "cleanup or reset, lacks native result, verifier, or trajectory evidence, or "
                "exits on an unrecovered provider quota or transport error."
            ),
            "analysis_plan": (
                "Select all 30 fresh attempts; compute the signed verifier-pass-rate arm delta "
                "as (unlimited-0 passes - guard-25000 passes) / 15; report secondary token, "
                "wall-time, MCP call/error, reread, and truncation metrics for explanation only; "
                "preserve infrastructure-invalid attempts and do not replace or score them."
            ),
        },
        "reproduction": {
            "execution": {
                "timeout_seconds": 1200,
                "seed_schedule": ["upstream-run-1", "upstream-run-2", "upstream-run-3"],
                "budget": {"kind": "wall-time", "limit": 1200, "unit": "seconds"},
            },
            "model": {"label": "gpt-5.4", "reasoning": "high"},
            "comparison": {"claim_class": "diagnostic", "promotion_authority": "none"},
        },
    }
    monkeypatch.setattr(pair, "_validate_spec", lambda *_args, **_kwargs: spec)

    assert (
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_sha256="a" * 64,
        )
        is spec
    )

    spec["reproduction"]["model"]["reasoning"] = "medium"
    with pytest.raises(pair.PairRunError, match=r"GPT-5\.4/high"):
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_sha256="a" * 64,
        )

    spec["reproduction"]["model"]["reasoning"] = "high"
    for field, bad_value in (("name", "accuracy"), ("direction", "minimize")):
        original = spec["study"]["primary_metric"][field]
        spec["study"]["primary_metric"][field] = bad_value
        with pytest.raises(pair.PairRunError, match="frozen primary metric"):
            pair._validate_tool_cap_spec(
                tmp_path / "run-spec.json",
                fixture_sha256="a" * 64,
            )
        spec["study"]["primary_metric"][field] = original

    spec["study"]["decision_rule"] = "always supported"
    with pytest.raises(pair.PairRunError, match="frozen decision rule"):
        pair._validate_tool_cap_spec(
            tmp_path / "run-spec.json",
            fixture_sha256="a" * 64,
        )

    spec["study"]["decision_rule"] = (
        "supported if unlimited-0 passes exceed guard-25000 passes; "
        "mixed if equal; not-supported if lower"
    )
    mutations = (
        (spec["preregistration"], "mode", "retrospective", "prospective preregistration"),
        (spec["reproduction"]["execution"]["budget"], "limit", 1, "wall-time budget"),
        (spec["study"], "research_question", "changed", "research question"),
        (spec["study"], "hypothesis", "changed", "hypothesis"),
        (spec["study"], "invalidation_rule", "changed", "invalidation rule"),
        (spec["study"], "analysis_plan", "changed", "analysis plan"),
    )
    for target, field, bad_value, message in mutations:
        original = target[field]
        target[field] = bad_value
        with pytest.raises(pair.PairRunError, match=message):
            pair._validate_tool_cap_spec(
                tmp_path / "run-spec.json",
                fixture_sha256="a" * 64,
            )
        target[field] = original


def test_spec_rejects_a_digest_outside_the_selected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = ("desktop/first",)
    spec = {
        "preregistration": {"live_test_approved": True},
        "reproduction": {
            "execution": {
                "ordered_workload_ids": list(ids),
                "workload_ids_sha256": "0" * 64,
                "repetitions": 1,
                "max_concurrency": 1,
                "timeout_seconds": 1200,
            },
            "harness": {"revision": f"harness+patch-sha256:{pair.PATCH_SHA256}"},
            "environment": {"initial_state_ref": "fixture-tree-sha256:" + "a" * 64},
            "model": {
                "provider": "openai",
                "route": "subscription",
                "label": "gpt-5.4",
                "reasoning": "high",
            },
            "geode": {"revision": "head", "dirty": False},
        },
    }
    monkeypatch.setattr(pair, "validate_run_spec", lambda _path: spec)
    monkeypatch.setattr(
        pair,
        "get_harness",
        lambda _name: type("Harness", (), {"commit": "harness"})(),
    )
    monkeypatch.setattr(
        pair,
        "_git",
        lambda _root, *args: "head" if args[0] == "rev-parse" else "",
    )

    with pytest.raises(pair.PairRunError, match="workload digest"):
        pair._validate_spec(tmp_path / "run-spec.json", ids=ids, fixture_sha256="a" * 64)


def test_python_preflight_checks_clean_dependencies_and_source_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(command: tuple[str, ...], **kwargs: object):
        calls.append((command, kwargs))
        return pair.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pair, "_run_process", run)

    receipt = pair._python_preflight(Path("/repo/.venv/bin/python"), tmp_path)

    assert calls[0][0][-3:] == ("-m", "pip", "check")
    assert calls[1][0][1] == "-c"
    assert "import pipeline" in calls[1][0][2]
    assert "create_task_manager('filesystem', task_suite='standard')" in calls[1][0][2]
    assert "create_state_manager('filesystem')" in calls[1][0][2]
    assert calls[2][0] == ("npx", "--version")
    assert all(call[1]["cwd"] == tmp_path for call in calls)
    assert receipt["dependency_check"] == "pass"


def test_python_preflight_rejects_a_dependency_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pair,
        "_run_process",
        lambda command, **_kwargs: pair.subprocess.CompletedProcess(command, 1),
    )

    with pytest.raises(pair.PairRunError, match="dependency integrity"):
        pair._python_preflight(Path("/repo/.venv/bin/python"), tmp_path)


def test_invoke_arm_sets_the_tool_cap_only_in_the_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}
    parent_value = os.environ.get("GEODE_MAX_TOOL_RESULT_TOKENS")

    def run(command, **kwargs):
        captured.update(kwargs["env"])
        return pair.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pair.subprocess, "run", run)
    pair._invoke_arm(
        python=Path("python"),
        mcpmark_root=tmp_path,
        native_dir=tmp_path / "native",
        log_dir=tmp_path / "logs",
        task="legal_document/dispute_review",
        arm="geode",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        run_id="tool-cap-test",
        max_tool_result_tokens=0,
    )

    assert captured["GEODE_MAX_TOOL_RESULT_TOKENS"] == "0"
    assert os.environ.get("GEODE_MAX_TOOL_RESULT_TOKENS") == parent_value


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
    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["arms"] == {
        "codex": {"attempts": 2, "passes": 2},
        "geode": {"attempts": 2, "passes": 2},
    }
    assert result["source_events"]["sha256"] == pair._sha256(output / "runner-events.jsonl")


@pytest.mark.parametrize(
    ("guard_passes", "unlimited_passes", "numerator"),
    ((1, 2, 1), (2, 2, 0), (2, 1, -1)),
)
def test_tool_cap_result_records_a_signed_digest_bound_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    guard_passes: int,
    unlimited_passes: int,
    numerator: int,
) -> None:
    output = tmp_path / f"out-{numerator}"
    output.mkdir()
    root = tmp_path / "mcpmark"
    (root / "test_environments/desktop").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pair, "_tree_row", lambda *_args, **_kwargs: _fixture()["categories"][0])

    def invoke(**kwargs: object) -> tuple[int, Path, Path]:
        native_dir = kwargs["native_dir"]
        log_dir = kwargs["log_dir"]
        assert isinstance(native_dir, Path) and isinstance(log_dir, Path)
        native_dir.mkdir(parents=True)
        log_dir.mkdir(parents=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return 0, stdout, stderr

    remaining = {25_000: guard_passes, 0: unlimited_passes}

    def receipt(_native_dir: Path, **kwargs: object) -> dict[str, object]:
        cap = kwargs["expected_tool_cap"]
        assert isinstance(cap, int)
        passed = remaining[cap] > 0
        remaining[cap] -= int(passed)
        return {"task_sha256": "a" * 64, "verifier_pass": passed}

    monkeypatch.setattr(pair, "_invoke_arm", invoke)
    monkeypatch.setattr(pair, "_native_receipt", receipt)
    pair._run_tasks(
        output_dir=output,
        mcpmark_root=root,
        python=Path("python"),
        ids=("desktop/task",),
        fixture=_fixture(),
        run_id="tool-cap-test",
        model_label="gpt-5.4",
        effort="high",
        timeout=1200,
        profile=pair.TOOL_CAP_PROFILE,
    )

    result = json.loads((output / "runner-result.json").read_text(encoding="utf-8"))
    assert result["primary_metric"] == {
        "name": "verifier-pass-rate arm delta",
        "value": numerator / 3,
        "numerator": numerator,
        "denominator": 3,
    }
    assert result["source_events"]["sha256"] == pair._sha256(output / "runner-events.jsonl")


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


def test_tool_cap_receipt_rejects_a_different_effective_config(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="legal_document/dispute_review",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
        max_tool_result_tokens=0,
    )

    with pytest.raises(pair.PairRunError, match="runtime configuration mismatch"):
        pair._native_receipt(
            native,
            task="legal_document/dispute_review",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
            expected_tool_cap=25_000,
        )


def test_native_receipt_rejects_a_summary_that_contradicts_the_verifier(tmp_path: Path) -> None:
    native = tmp_path / "native"
    _write_native(
        native,
        task="desktop/task",
        arm="geode",
        model="geode-gpt-5.4",
        effort="high",
        timeout=1200,
    )
    summary_path = next(native.rglob("summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["successful_tasks"] = 0
    summary["failed_tasks"] = 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="exact one-task arm result"):
        pair._native_receipt(
            native,
            task="desktop/task",
            arm="geode",
            model="geode-gpt-5.4",
            effort="high",
            timeout=1200,
        )


def test_tool_cap_truncation_is_reconstructed_from_the_raw_log(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {"content": [{"type": "text", "text": "x" * 100_100}]}}]),
        encoding="utf-8",
    )

    assert pair._truncation_count(path, max_tokens=25_000) == 1
    assert pair._truncation_count(path, max_tokens=0) == 0


def test_tool_cap_truncation_accepts_error_dicts_and_ignores_server_flags(
    tmp_path: Path,
) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {"error": "caught"}}, {"result": {"_truncated": True}}]),
        encoding="utf-8",
    )

    assert pair._truncation_count(path, max_tokens=25_000) == 0
    assert pair._truncation_count(path, max_tokens=0) == 0


def test_tool_cap_truncation_rejects_a_non_dict_result(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(json.dumps([{"result": "unexpected"}]), encoding="utf-8")

    with pytest.raises(pair.PairRunError, match="unknown tool-result shape"):
        pair._truncation_count(path, max_tokens=25_000)


def test_tool_cap_truncation_rejects_a_saturated_tool_log(tmp_path: Path) -> None:
    path = tmp_path / "execution.log"
    path.write_text(
        json.dumps([{"result": {}}] * pair.ToolCallProcessor.MAX_TOOL_LOG_ENTRIES),
        encoding="utf-8",
    )

    with pytest.raises(pair.PairRunError, match="retention cap"):
        pair._truncation_count(path, max_tokens=25_000)


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
    monkeypatch.setattr(pair, "_python_preflight", lambda *_args: {"dependency_check": "pass"})

    pair.run_pair(
        run_spec_path=spec_path,
        mcpmark_root=tmp_path / "mcpmark",
        output_dir=output,
        python=Path("python"),
    )

    assert (output / "run-spec.json").read_bytes() == spec_path.read_bytes()


def test_pair_runner_preflights_before_creating_output_or_running_tasks(
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
            "reproduction": {
                "execution": {"timeout_seconds": 1200},
                "model": {"label": "gpt-5.4", "route": "subscription", "reasoning": "high"},
            }
        },
    )
    monkeypatch.setattr(
        pair,
        "_python_preflight",
        lambda *_args: (_ for _ in ()).throw(pair.PairRunError("preflight failed")),
    )
    run_tasks_called = False

    def run_tasks(**_kwargs: object) -> None:
        nonlocal run_tasks_called
        run_tasks_called = True

    monkeypatch.setattr(pair, "_run_tasks", run_tasks)

    with pytest.raises(pair.PairRunError, match="preflight failed"):
        pair.run_pair(
            run_spec_path=spec_path,
            mcpmark_root=tmp_path / "mcpmark",
            output_dir=output,
            python=Path("python"),
        )

    assert not output.exists()
    assert run_tasks_called is False


def test_cli_preserves_the_selected_virtualenv_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "python-real"
    target.touch()
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(target)
    captured: dict[str, Path] = {}

    def run_pair(**kwargs: object) -> None:
        selected = kwargs["python"]
        assert isinstance(selected, Path)
        captured["python"] = selected

    monkeypatch.setattr(pair, "run_pair", run_pair)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_mcpmark_pair",
            "--run-spec",
            str(tmp_path / "run-spec.json"),
            "--mcpmark-root",
            str(tmp_path / "mcpmark"),
            "--output-dir",
            str(tmp_path / "output"),
            "--python",
            str(python),
        ],
    )

    pair.main()

    assert captured["python"] == python.absolute()
    assert captured["python"].is_symlink()


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
