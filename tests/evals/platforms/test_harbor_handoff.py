from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from evals.platforms import harbor_handoff
from evals.platforms.harbor_handoff import GeodeHandoffHarborAgent, _run_handoff, _task
from evals.platforms.harbor_runtime import GeodeRuntimeHarborAgent


def _write_task(path: Path, **overrides: Any) -> tuple[dict[str, Any], str]:
    value = {
        "case": {"id": "local-test", "request": "Check C-318."},
        "orders": {"C-318": "processing"},
        "intervention": None,
        **overrides,
    }
    path.write_text(json.dumps(value))
    return value, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def host_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Exercise the profile's own gates; the native parent has separate tests."""

    def base_init(self: Any, **kwargs: Any) -> None:
        for key, value in {
            "model_name": "geode/gpt-6-astra",
            "effort": "xhigh",
            "verify_mode": "rule_based",
            "agent_timeout_sec": 180,
            "source_revision": "a" * 40,
            "source_sha256": "b" * 64,
            "logs_dir": tmp_path / "logs",
            **kwargs,
        }.items():
            setattr(self, key, value)

    monkeypatch.setattr(GeodeRuntimeHarborAgent, "__init__", base_init)
    case = tmp_path / "task.json"
    value, digest = _write_task(case)
    secret = tmp_path / "typesafe.key"
    secret.write_text("synthetic-test-key")
    secret.chmod(0o600)
    return SimpleNamespace(
        path=tmp_path,
        case=case,
        task=value,
        secret=secret,
        kwargs={"arm": "a0", "case_file": str(case), "case_sha256": digest},
    )


@pytest.mark.parametrize("field", ["id", "request"])
@pytest.mark.parametrize("value", [None, "", 4])
def test_task_requires_nonempty_identity_and_request(
    tmp_path: Path, field: str, value: Any
) -> None:
    path = tmp_path / "task.json"
    _, digest = _write_task(path, case={"id": "case", "request": "request", field: value})
    with pytest.raises(ValueError, match="invalid handoff task contract"):
        _task(path, digest)


def test_task_rejects_changed_bytes_and_unrecognized_fields(tmp_path: Path) -> None:
    path = tmp_path / "task.json"
    _, digest = _write_task(path)
    with pytest.raises(ValueError, match="digest mismatch"):
        _task(path, "0" * 64)
    _write_task(path, unexpected="not a task field")
    with pytest.raises(ValueError, match="digest mismatch"):
        _task(path, digest)
    with pytest.raises(ValueError, match="invalid handoff task contract"):
        _task(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_inbox_task_admission_requires_complete_candidate_inventory(tmp_path: Path) -> None:
    from evals.benchmarks.decision_handoff_runtime import inbox_request

    fixture = json.loads(
        (
            Path(__file__).parents[3] / "evals/benchmarks/fixtures/decision-handoff-inbox.json"
        ).read_text()
    )
    case = fixture["admission"]
    case.update(profile="inbox", request=inbox_request(case["items"]))
    path = tmp_path / "task.json"
    _, digest = _write_task(path, case=case, orders=fixture["orders"])
    assert _task(path, digest)["case"]["profile"] == "inbox"
    case["items"][0]["candidates"].pop()
    _, digest = _write_task(path, case=case, orders=fixture["orders"])
    with pytest.raises(ValueError, match="candidate coverage"):
        _task(path, digest)


@pytest.mark.parametrize(
    "override",
    [
        {"arm": "unknown"},
        {"model_name": "gpt-5.6-sol"},
        {"effort": "max"},
        {"verify_mode": "reflexion"},
        {"agent_timeout_sec": 179},
        {"arm": "b"},
        {"env": {"UNEXPECTED": "value"}},
        {"extra_env": {"UNEXPECTED": "value"}},
        {"prompt_template_path": "unfrozen.md"},
    ],
)
def test_profile_rejects_unfrozen_arguments(
    host_agent: SimpleNamespace, override: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        GeodeHandoffHarborAgent(**(host_agent.kwargs | override))


def test_unassisted_profile_has_no_secret_or_helper_intervention(
    host_agent: SimpleNamespace,
) -> None:
    with pytest.raises(ValueError, match="credential scope mismatch"):
        GeodeHandoffHarborAgent(**host_agent.kwargs, typesafe_key_file=str(host_agent.secret))
    _, digest = _write_task(host_agent.case, intervention={"intent": "status", "order_id": "C-318"})
    with pytest.raises(ValueError, match="cannot have a helper intervention"):
        GeodeHandoffHarborAgent(**(host_agent.kwargs | {"case_sha256": digest}))


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "owner"])
def test_host_secret_must_be_private_owned_regular_file(
    host_agent: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    secret = host_agent.secret
    if unsafe == "mode":
        secret.chmod(0o640)
    elif unsafe == "symlink":
        secret = host_agent.path / "linked.key"
        secret.symlink_to(host_agent.secret)
    else:
        uid = os.getuid()
        monkeypatch.setattr(harbor_handoff.os, "getuid", lambda: uid + 1)
    with pytest.raises(ValueError, match="owner-only regular file"):
        GeodeHandoffHarborAgent(**(host_agent.kwargs | {"arm": "b"}), typesafe_key_file=str(secret))


def test_install_copies_only_b_secret_and_rechecks_frozen_inputs(
    host_agent: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = AsyncMock()
    monkeypatch.setattr(GeodeRuntimeHarborAgent, "install", install)
    agent = GeodeHandoffHarborAgent(
        **(host_agent.kwargs | {"arm": "b"}), typesafe_key_file=str(host_agent.secret)
    )
    agent.exec_as_root = AsyncMock()
    agent.exec_as_agent = AsyncMock(return_value=SimpleNamespace(stdout="1001\n"))
    environment = SimpleNamespace(upload_file=AsyncMock(), default_user="task user")
    asyncio.run(agent.install(environment))
    assert environment.upload_file.await_args_list[0].args == (
        host_agent.case,
        f"{harbor_handoff._INSTALL}/handoff-task.json",
    )
    assert environment.upload_file.await_args_list[1].args == (
        host_agent.secret,
        f"{harbor_handoff._INSTALL}/typesafe.key",
    )
    command = agent.exec_as_root.await_args.kwargs["command"]
    assert "chmod 600" in command and "chown 1001" in command
    host_agent.secret.chmod(0o640)
    with pytest.raises(ValueError, match="owner-only regular file"):
        asyncio.run(agent.install(environment))
    host_agent.case.write_text("changed after validation")
    with pytest.raises(ValueError, match="digest mismatch"):
        asyncio.run(agent.install(environment))


@pytest.mark.parametrize("receipt_fails", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_host_stop_and_receipt_errors_preserve_primary(
    host_agent: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    receipt_fails: bool,
    cancelled: bool,
) -> None:
    from core.memory.atomic_write import atomic_write_json

    agent = GeodeHandoffHarborAgent(**host_agent.kwargs)
    primary = (
        asyncio.CancelledError("private cancellation")
        if cancelled
        else TimeoutError("private timeout")
    )
    agent.exec_as_agent = AsyncMock(side_effect=[None, primary])
    stop = AsyncMock(side_effect=OSError("private stop error"))
    monkeypatch.setattr(harbor_handoff, "_stop_runtime", stop)

    def write(path: Path, value: Any) -> None:
        if receipt_fails and "finalization_errors" in value:
            raise PermissionError("private receipt error")
        atomic_write_json(path, value)

    monkeypatch.setattr("core.memory.atomic_write.atomic_write_json", write)
    with pytest.raises(type(primary)) as caught:
        asyncio.run(
            agent.run(host_agent.task["case"]["request"], SimpleNamespace(), SimpleNamespace())
        )
    assert caught.value is primary
    stop.assert_awaited_once_with(SimpleNamespace(), module="evals.platforms.harbor_handoff")
    assert any("OSError" in note for note in primary.__notes__)
    if receipt_fails:
        assert any("PermissionError" in note for note in primary.__notes__)
    else:
        receipt = json.loads((agent.logs_dir / "runtime-contract.json").read_text())
        assert receipt["finalization_errors"] == [
            {"stage": "host_stop_runtime", "error_type": "OSError"}
        ]
    assert "private" not in (agent.logs_dir / "runtime-contract.json").read_text()


@pytest.fixture
def container_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use real local evidence storage without touching host roots or providers."""
    from core.observability.session_timeline import SessionTimeline
    from core.observability.trajectory import export_trajectory
    from evals.platforms.harbor import _summarize_usage

    monkeypatch.setattr(harbor_handoff, "_LOGS", str(tmp_path))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr(harbor_handoff, "_INSTALL", str(install))
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: str(p) == "/.dockerenv" or real_is_file(p))
    monkeypatch.setattr(
        harbor_handoff,
        "Path",
        lambda p: tmp_path / "workspace" if str(p) == "/workspace" else Path(p),
    )
    monkeypatch.setattr(harbor_handoff.os, "chdir", lambda _: None)
    monkeypatch.setattr(harbor_handoff.os, "umask", lambda _: 0o077)
    monkeypatch.setattr(harbor_handoff.logging, "disable", lambda _: None)
    monkeypatch.setenv("GEODE_HOME", f"{tmp_path}/geode-home")
    monkeypatch.setenv("GEODE_VERIFY_MODE", "rule_based")
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    for key in list(os.environ):
        if key.endswith("API_KEY"):
            monkeypatch.delenv(key)
    settings = SimpleNamespace()
    monkeypatch.setattr("core.config.settings", settings)
    db = tmp_path / "sessions.db"
    timeline = SessionTimeline("fake-root", db_path=db, projection_path=tmp_path / "events.jsonl")
    timeline.record_session_start(model="gpt-6-astra", provider="openai")
    timeline.record_session_end()
    result = {
        "session_id": "fake-root",
        "termination_reason": "natural",
        "error_type": None,
        "usage": _summarize_usage([]),
        "source_snapshot_complete": True,
        "db_path": str(db),
        "tool_definitions": [],
        "valid": True,
        "final_text": "C-318 is processing.",
    }
    runner = AsyncMock(return_value=result)
    monkeypatch.setattr("evals.benchmarks.decision_handoff_runtime.run_arm", runner)
    task = tmp_path / "task.json"
    value, digest = _write_task(task)
    args = SimpleNamespace(
        arm="a0", timeout=180, task=str(task), task_sha256=digest, revision="a" * 40
    )
    return SimpleNamespace(
        path=tmp_path,
        args=args,
        runner=runner,
        result=result,
        task=value,
        secret=install / "typesafe.key",
        settings=settings,
        export=export_trajectory,
        timeline=timeline,
    )


def test_full_export_failure_preserves_digest_result_and_receipt(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = container_trial

    def export(path: Path, payload: Any) -> None:
        if path.name == "geode-trajectory.private.json":
            raise OSError("private full export failure")
        trial.export(path, payload)

    monkeypatch.setattr("core.observability.trajectory.export_trajectory", export)
    assert asyncio.run(_run_handoff(trial.args)) == 1
    for filename in (
        "geode-trajectory.json",
        "handoff-result.json",
        "runtime-result.json",
        "runtime-finalized.json",
    ):
        assert (trial.path / filename).is_file()
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["finalization_errors"] == [{"stage": "trajectory_full", "error_type": "OSError"}]
    assert "private full export failure" not in json.dumps(receipt)


def test_incomplete_source_invalidates_both_trajectories_and_blocks_atif(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = container_trial
    trial.result["source_snapshot_complete"] = False
    assert asyncio.run(_run_handoff(trial.args)) == 1
    for filename in ("geode-trajectory.private.json", "geode-trajectory.json"):
        integrity = json.loads((trial.path / filename).read_text())["integrity"]
        assert integrity["complete"] is False
        assert integrity["scope_complete"] is False
        assert integrity["replay_complete"] is False
        assert "handoff source snapshot incomplete" in integrity["scope_incompleteness"]
    writer = MagicMock()
    monkeypatch.setattr("evals.platforms.harbor._write_atif_trajectory", writer)
    agent = object.__new__(GeodeHandoffHarborAgent)
    agent.logs_dir = trial.path
    context = SimpleNamespace()
    agent.populate_context_post_run(context)
    writer.assert_not_called()
    assert context.metadata["usage"]["source_snapshot_complete"] is False
    assert context.cost_usd is None


def test_container_preserves_truncated_replay_but_refuses_export_success(
    container_trial: SimpleNamespace,
) -> None:
    trial = container_trial
    trial.timeline.bind_turn("test-turn")
    trial.timeline.record_user_message("x" * 100_001)
    trial.timeline.record_session_end()
    assert asyncio.run(_run_handoff(trial.args)) == 1
    private = json.loads((trial.path / "geode-trajectory.private.json").read_text())
    assert private["integrity"]["scope_complete"]
    assert private["integrity"]["replay_complete"] is False
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["finalization_errors"] == [
        {"stage": "trajectory_full", "error_type": "RuntimeError"}
    ]
    for filename in ("geode-trajectory.json", "handoff-result.json", "runtime-result.json"):
        assert (trial.path / filename).is_file()


@pytest.mark.parametrize("tampered", [False, True])
def test_host_checks_full_replay_before_projection(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tampered: bool
) -> None:
    from core.observability.trajectory import trajectory_from_sessions

    trial = container_trial
    assert asyncio.run(_run_handoff(trial.args)) == 0
    # Include real omitted dialogue while keeping a closed, paired scope.
    trial.timeline.bind_turn("test-turn")
    trial.timeline.record_user_message("Check C-318.")
    trial.timeline.record_session_end()
    trajectory = trajectory_from_sessions(
        [trial.result["session_id"]],
        trajectory_id="incomplete-test",
        source={"harness": "harbor", "session": trial.result["session_id"]},
        db_path=Path(trial.result["db_path"]),
        content_policy="digest",
    )
    assert trajectory["integrity"]["scope_complete"]
    assert not trajectory["integrity"]["replay_complete"]
    if tampered:
        trajectory["integrity"]["replay_complete"] = True
    (trial.path / "geode-trajectory.private.json").write_text(json.dumps(trajectory))
    writer = MagicMock()
    monkeypatch.setattr("evals.platforms.harbor._write_atif_trajectory", writer)
    agent = object.__new__(GeodeHandoffHarborAgent)
    agent.logs_dir = trial.path
    context = SimpleNamespace()
    with pytest.raises(ValueError):
        agent.populate_context_post_run(context)
    writer.assert_not_called()
    assert context.cost_usd is None


@pytest.mark.parametrize("missing", ["runtime-result.json", "geode-trajectory.private.json"])
def test_host_rejects_missing_required_replay_file(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    trial = container_trial
    assert asyncio.run(_run_handoff(trial.args)) == 0
    (trial.path / missing).unlink()
    writer = MagicMock()
    monkeypatch.setattr("evals.platforms.harbor._write_atif_trajectory", writer)
    agent = object.__new__(GeodeHandoffHarborAgent)
    agent.logs_dir = trial.path
    with pytest.raises(ValueError, match="handoff replay requires"):
        agent.populate_context_post_run(SimpleNamespace())
    writer.assert_not_called()


@pytest.mark.parametrize("gate", ["host", "environment", "timeout", "arm"])
def test_container_entry_gates_precede_execution(
    container_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    trial = container_trial
    if gate == "host":
        monkeypatch.setenv("GEODE_HOME", "/not-the-container")
    elif gate == "environment":
        monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-only")
    elif gate == "timeout":
        trial.args.timeout = 181
    else:
        trial.args.arm = "other"
    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(_run_handoff(trial.args))
    trial.runner.assert_not_awaited()
    assert not (trial.path / "runtime.pid").exists()


def test_container_b_secret_is_unlinked_before_runtime_and_not_serialized(
    container_trial: SimpleNamespace,
) -> None:
    trial = container_trial
    trial.args.arm = "b"
    trial.secret.write_text("synthetic-test-key\n")
    trial.secret.chmod(0o600)

    async def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert not trial.secret.exists()
        assert kwargs["api_key"].get_secret_value() == "synthetic-test-key"
        assert kwargs["orders"] == trial.task["orders"]
        return trial.result

    trial.runner.side_effect = run
    assert asyncio.run(_run_handoff(trial.args)) == 0
    assert trial.settings.llm_max_retries == 1
    assert trial.settings.cognitive_reflection_enabled is False
    assert trial.settings.cost_limit_usd == 0
    assert not trial.secret.exists()
    for path in trial.path.glob("*.json"):
        assert "synthetic-test-key" not in path.read_text()


@pytest.mark.parametrize("unsafe", ["mode", "symlink", "non_b"])
def test_container_rejects_unsafe_or_unscoped_secret_and_cleans_it(
    container_trial: SimpleNamespace, unsafe: str
) -> None:
    trial = container_trial
    trial.args.arm = "a0" if unsafe == "non_b" else "b"
    if unsafe == "symlink":
        target = trial.path / "secret-target"
        target.write_text("synthetic-test-key")
        trial.secret.symlink_to(target)
    else:
        trial.secret.write_text("synthetic-test-key")
        trial.secret.chmod(0o640 if unsafe == "mode" else 0o600)
    assert asyncio.run(_run_handoff(trial.args)) == 1
    trial.runner.assert_not_awaited()
    assert not trial.secret.exists()
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["execution_started"] is False
    assert receipt["exports_complete"] is False
    assert receipt["error_type"] == "RuntimeError"
    assert receipt["finalization_errors"] == [
        {"stage": "credential_load", "error_type": "RuntimeError"}
    ]
