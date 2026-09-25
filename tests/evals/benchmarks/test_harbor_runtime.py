from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import signal
import tarfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from evals.platforms import harbor_runtime
from evals.platforms.harbor import RecordedCodexHarborAgent
from evals.platforms.harbor_runtime import (
    GeodeRuntimeHarborAgent,
    _run_native,
    _stop_runtime,
    _summarize_usage,
    _verify_bundle,
)


@pytest.mark.parametrize("version", [None, "0.8.0", "0.23.0"])
def test_docker_provider_rejects_unsupported_harbor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str | None
) -> None:
    from evals.platforms import harbor_docker

    def detected_version(name: str) -> str:
        assert name == "harbor"
        if version is None:
            raise harbor_docker.importlib.metadata.PackageNotFoundError(name)
        return version

    monkeypatch.setattr(harbor_docker.importlib.metadata, "version", detected_version)
    with pytest.raises(RuntimeError, match=r"harbor==0\.22\.0"):
        harbor_docker.GeodeHarborDockerEnvironment(environment_dir=tmp_path)


@pytest.mark.parametrize("value", ["1", "true", "0", "false", "${CODEX_FORCE_AUTH_JSON}"])
def test_native_auth_flag_rejects_harbor_secret_scrubbing_path(value: str) -> None:
    with pytest.raises(ValueError, match=r"process environment, not agent\.env"):
        RecordedCodexHarborAgent(extra_env={"CODEX_FORCE_AUTH_JSON": value})


def test_source_bundle_rejects_mismatch_traversal_and_links(tmp_path: Path) -> None:
    path = tmp_path / "source.tar.gz"
    for unsafe in (None, "../escape", "/absolute", "linked"):
        with tarfile.open(path, "w:gz") as archive:
            for name in ("pyproject.toml", "uv.lock", "core/wiring/runtime.py"):
                item = tarfile.TarInfo(name)
                item.size = 1
                archive.addfile(item, io.BytesIO(b"x"))
            if unsafe:
                item = tarfile.TarInfo(unsafe)
                if unsafe == "linked":
                    item.type = tarfile.SYMTYPE
                    item.linkname = "outside"
                archive.addfile(item)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if unsafe:
            with pytest.raises(ValueError, match="unsafe"):
                _verify_bundle(path, digest)
        else:
            _verify_bundle(path, digest)
        with pytest.raises(ValueError, match="mismatch"):
            _verify_bundle(path, "0" * 64)


@pytest.mark.parametrize("default_user,uid", [(None, "0"), (None, "1001"), ("task", "1001")])
def test_credential_upload_uses_actual_agent_uid(
    tmp_path: Path, default_user: str | None, uid: str
) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.exec_as_agent = AsyncMock(return_value=SimpleNamespace(stdout=uid + "\n"))
    agent.exec_as_root = AsyncMock()
    environment = SimpleNamespace(upload_file=AsyncMock(), default_user=default_user)
    source = tmp_path / "synthetic.key"
    target = "/installed-agent/secret key"
    asyncio.run(agent._upload_credential(environment, source, target))
    agent.exec_as_agent.assert_awaited_once_with(environment, command="id -u")
    environment.upload_file.assert_awaited_once_with(source, target)
    agent.exec_as_root.assert_awaited_once_with(
        environment, command=f"chmod 600 '{target}' && chown {uid} '{target}'"
    )


@pytest.mark.parametrize("uid", [None, "", "root", "0; echo unsafe", "0\n1"])
def test_invalid_agent_uid_prevents_credential_upload(tmp_path: Path, uid: str | None) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.exec_as_agent = AsyncMock(return_value=SimpleNamespace(stdout=uid))
    agent.exec_as_root = AsyncMock()
    environment = SimpleNamespace(upload_file=AsyncMock())
    with pytest.raises(RuntimeError, match="container agent uid"):
        asyncio.run(agent._upload_credential(environment, tmp_path / "key", "/secret"))
    environment.upload_file.assert_not_awaited()
    agent.exec_as_root.assert_not_awaited()


def test_usage_projects_partial_evidence_without_fabricating_totals() -> None:
    def event(cache: int | None, call: str) -> SimpleNamespace:
        return SimpleNamespace(
            action="llm.call.ended",
            session_id="usage-session",
            llm_call_id=call,
            llm_attempt_id=call + ":attempt-1",
            payload={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cached_input_tokens": cache,
                    "cache_write_tokens": None,
                },
            },
        )

    def paired(*calls: SimpleNamespace) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                action="llm.call.started",
                session_id="usage-session",
                llm_attempt_id=c.llm_attempt_id,
            )
            for c in calls
        ] + list(calls)

    result = _summarize_usage(paired(event(0, "a"), event(4, "b")))
    assert result["input_tokens"] == 20
    assert result["cached_input_tokens"] == 4
    assert result["cached_input_tokens_missing_events"] == 0
    assert result["whole_runtime_complete"] is False
    partial = _summarize_usage(paired(event(None, "a"), event(4, "b")))
    assert partial["cached_input_tokens"] is None
    assert partial["cached_input_tokens_observed_sum"] == 4
    assert partial["cached_input_tokens_missing_events"] == 1
    assert partial["cache_write_tokens"] is None
    assert _summarize_usage([])["input_tokens"] is None
    failed = SimpleNamespace(
        action="llm.call.ended",
        session_id="usage-session",
        llm_attempt_id="c:attempt-1",
        payload={"error_type": "TimeoutError"},
    )
    assert _summarize_usage(paired(event(4, "a"), failed))["input_tokens"] is None
    unclosed = [
        *paired(event(4, "a")),
        SimpleNamespace(action="llm.call.started", llm_attempt_id="open:attempt-1"),
    ]
    assert _summarize_usage(unclosed)["cached_input_tokens"] is None
    assert _summarize_usage(paired(event(4, "a"), event(4, "a")))["input_tokens"] is None


def test_runtime_entry_refuses_host_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEODE_HOME", "/not-a-harbor-runtime")
    with pytest.raises(RuntimeError, match="container-local"):
        asyncio.run(_run_native(SimpleNamespace()))


def test_post_run_context_keeps_missing_cache_and_no_subscription_price(tmp_path: Path) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    context = SimpleNamespace(n_cache_tokens="uninitialized")
    agent.populate_context_post_run(context)
    assert context.n_cache_tokens == "uninitialized"
    payload = {
        "usage": {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": None},
        "metadata": {
            "termination_reason": "done",
            "verify_mode": "rule_based",
            "effective_verify_mode": "llm_judge",
        },
    }
    (tmp_path / "runtime-result.json").write_text(json.dumps(payload))
    agent.populate_context_post_run(context)
    assert context.n_input_tokens is None
    assert context.n_cache_tokens is None
    assert context.cost_usd is None
    assert context.metadata == payload["metadata"]


def test_stop_runtime_waits_for_shutdown_receipt_and_fails_closed() -> None:
    environment = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=0)))
    asyncio.run(_stop_runtime(environment))
    command = environment.exec.call_args.kwargs["command"]
    assert "runtime-finalized.json" in command
    assert "exports_complete" in command
    assert "is not True" in command
    assert "SIGTERM" in command
    assert "deadline" in command
    environment.exec.return_value.return_code = 1
    with pytest.raises(RuntimeError, match="shutdown/export incomplete"):
        asyncio.run(_stop_runtime(environment))


def test_runtime_config_pins_role_models_and_absolute_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tomllib

    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    agent.model_name = "gpt-5.6-sol"
    agent.effort = "max"
    agent.verify_mode = "llm_judge"
    agent.source = "subscription"
    agent.source_revision = "a" * 40
    agent.source_sha256 = "b" * 64
    agent.agent_timeout_sec = 900
    agent.render_instruction = lambda instruction: instruction
    agent.exec_as_agent = AsyncMock()
    environment = SimpleNamespace(upload_file=AsyncMock())
    asyncio.run(agent.run("Solve the task.", environment, SimpleNamespace()))
    config = tomllib.loads((tmp_path / "runtime-config.toml").read_text())
    assert config["llm"]["model_policy_path"] == "/installed-agent/geode/model-policy.toml"
    assert config["llm"]["primary_model"] == "gpt-5.6-sol"
    assert config["llm"]["openai_credential_source"] == "openai-codex"
    assert config["llm"]["anthropic_credential_source"] == "none"
    policy = tomllib.loads((tmp_path / "model-policy.toml").read_text())
    assert policy == {"policy": {"allowlist": ["gpt-5.6-sol"]}}
    assert config["agentic"]["effort"] == "max"
    call = agent.exec_as_agent.call_args.kwargs
    assert "runtime.log 2>&1" in call["command"]
    assert call["env"]["PYTHONFAULTHANDLER"] == "1"
    assert call["env"]["GEODE_VERIFY_MODE"] == "llm_judge"
    assert "--verify-mode llm_judge" in call["command"]
    profile_path = tmp_path / "runtime-preferences.toml"
    assert tomllib.loads(profile_path.read_text()) == {"policy": {"allow_dangerous": True}}
    environment.upload_file.assert_any_await(
        profile_path, "/logs/agent/geode-home/user_profile/preferences.toml"
    )
    contract = json.loads((tmp_path / "runtime-contract.json").read_text())
    assert contract["verify_mode"] == "llm_judge"
    assert contract["required_tools"] == ["run_bash"]

    from core.agent.loop.models import AgenticResult
    from core.agent.subagent_roles import SUBAGENT_ROLES
    from core.agent.tool_executor import ToolExecutor
    from core.agent.worker import WorkerRequest, _run_agentic
    from core.config import settings
    from core.llm.adapters.registry import registry_snapshot
    from core.server.supervised.services import SessionMode, SharedServices
    from core.tools.composition import compose_tool_plan

    # Keep native catalog/profile/session admission; stub only inference and
    # unrelated startup so this gate cannot read credentials or execute tools.
    monkeypatch.setattr(settings, "model", agent.model_name)
    monkeypatch.setattr(settings, "openai_credential_source", "openai-codex")
    monkeypatch.setattr("core.config.reload_settings_from_disk", lambda: None)
    monkeypatch.setattr(SharedServices, "_build_sub_agent_manager", lambda self, **kwargs: None)
    monkeypatch.setattr("core.wiring.bootstrap.build_worker_hooks", lambda **kwargs: None)
    executors: list[ToolExecutor] = []

    def fake_loop(_conversation, executor, **_kwargs):
        executors.append(executor)
        return SimpleNamespace(
            _adapter_registry_snapshot=registry_snapshot(),
            arun=AsyncMock(return_value=AgenticResult(text="ok", termination_reason="unknown")),
            amark_session_completed=AsyncMock(),
            amark_session_error=AsyncMock(),
        )

    monkeypatch.setattr("core.agent.loop.AgenticLoop", fake_loop)
    bound, transient = compose_tool_plan()
    services = SharedServices(bound_tool_plan=bound, transient_tool_handlers=transient)
    monkeypatch.setattr("core.paths.GLOBAL_USER_PREFERENCES", tmp_path / "missing-preferences.toml")
    executor, _loop = services.create_session(SessionMode.REPL)
    assert "run_bash" not in executor._bound_tool_plan.tool_names
    assert executor._session_scope_denial("run_bash") is not None

    monkeypatch.setattr("core.paths.GLOBAL_USER_PREFERENCES", profile_path)
    executor, _loop = services.create_session(SessionMode.REPL)
    assert "run_bash" in executor._bound_tool_plan.tool_names
    assert executor._session_scope_denial("run_bash") is None
    for role in ("verifier", "", "reviewer"):
        _run_agentic(
            WorkerRequest(
                task_id=role or "default",
                description="Inspect shell admission without executing it.",
                model=agent.model_name,
                provider="openai",
                source="subscription",
                agent_allowed_tools=list(SUBAGENT_ROLES[role].tools) if role else [],
            ),
            lambda: (bound, transient),
        )
        executor = executors[-1]
        assert ("run_bash" in executor._bound_tool_plan.tool_names) is (role == "verifier")
        assert (executor._session_scope_denial("run_bash") is None) is (role == "verifier")


def test_installed_agent_uses_harbor_lifecycle_and_classifies_timeout(tmp_path: Path) -> None:
    import importlib.metadata

    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name in ("pyproject.toml", "uv.lock", "core/wiring/runtime.py"):
            item = tarfile.TarInfo(name)
            archive.addfile(item)
    kwargs = {
        "logs_dir": tmp_path / "logs",
        "model_name": "gpt-5.6-sol",
        "source_bundle": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_revision": "a" * 40,
        "agent_timeout_sec": 900,
    }
    try:
        harbor_version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError:
        harbor_version = None
    if harbor_version != "0.22.0":
        with pytest.raises(RuntimeError, match=r"harbor==0\.22\.0"):
            GeodeRuntimeHarborAgent(**kwargs)
        return
    from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError
    from harbor.trial.errors import AgentTimeoutError

    agent = GeodeRuntimeHarborAgent(**kwargs)
    assert isinstance(agent, BaseInstalledAgent)
    assert agent.verify_mode == "rule_based"
    assert GeodeRuntimeHarborAgent(**kwargs, verify_mode="reflexion").verify_mode == "reflexion"
    assert GeodeRuntimeHarborAgent(**kwargs, verify_mode="llm_judge").verify_mode == "llm_judge"
    with pytest.raises(ValueError, match="is not a valid VerifyMode"):
        GeodeRuntimeHarborAgent(**kwargs, verify_mode="reflexionn")
    assert GeodeRuntimeHarborAgent.setup is BaseInstalledAgent.setup
    assert agent.SUPPORTS_ATIF
    assert isinstance(
        agent._classify_exec_error(
            "/venv/bin/python -m evals.platforms.harbor_runtime --timeout 900",
            SimpleNamespace(return_code=124),
        ),
        AgentTimeoutError,
    )
    assert isinstance(
        agent._classify_exec_error(
            "python -m other_module", SimpleNamespace(return_code=1, stdout="", stderr="")
        ),
        NonZeroAgentExitCodeError,
    )


@pytest.fixture
def native_trial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """Fake execution boundaries; real evidence stores/projections only in tmp_path."""
    import sqlite3

    from core.agent.loop.models import TerminationReason
    from core.hooks import HookEvent, HookSystem
    from core.memory.atomic_write import atomic_write_json
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.observability.session_timeline import SessionTimeline
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions

    monkeypatch.setattr(harbor_runtime, "_LOGS", str(tmp_path))
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: p == Path("/.dockerenv") or real_is_file(p))
    monkeypatch.setenv("GEODE_HOME", f"{tmp_path}/geode-home")
    monkeypatch.setenv("GEODE_VERIFY_MODE", "rule_based")
    for key in os.environ:
        if key.endswith("API_KEY"):
            monkeypatch.delenv(key)
    settings = SimpleNamespace(
        model="gpt-5.6-sol",
        agentic_effort="max",
        model_policy_path="/installed-agent/geode/model-policy.toml",
        openai_credential_source="openai-codex",
        anthropic_credential_source="none",
        judge_model="gpt-5.6-sol",
    )
    monkeypatch.setattr("core.config.settings", settings)
    monkeypatch.setattr(
        "core.config.load_model_policy", lambda: SimpleNamespace(allowlist=[settings.model])
    )
    db_path = tmp_path / "sessions.db"

    def record_session(session_id: str, *, closed: bool = True) -> SessionTimeline:
        timeline = SessionTimeline(
            session_id, db_path=db_path, projection_path=tmp_path / f"{session_id}.events.jsonl"
        )
        timeline.record_session_start(model=settings.model, provider="openai")
        timeline.bind_turn(f"{session_id}:turn-1")
        if closed:
            timeline.record_session_end()
        return timeline

    root_timeline = record_session("fake-root", closed=False)
    loop = SimpleNamespace(
        _session_id="fake-root",
        _tools=[{"name": "run_bash", "description": "test", "input_schema": {}}],
        arun=AsyncMock(
            return_value=SimpleNamespace(termination_reason=TerminationReason.NATURAL, error=None)
        ),
        amark_session_completed=AsyncMock(side_effect=root_timeline.record_session_end),
        amark_session_error=AsyncMock(
            side_effect=lambda: root_timeline.record_session_end(status="error")
        ),
    )
    executor = SimpleNamespace(_sub_agent_manager=None, _session_scope_denial=lambda name: None)
    runtime = MagicMock()
    runtime.hooks = SimpleNamespace(has_sink_failures=False)
    runtime.dreaming_service.settle = AsyncMock()
    runtime.dreaming_service.aclose = AsyncMock()
    runtime.event_store = HookEventStore(db_path)
    runtime.shutdown.side_effect = lambda **_kwargs: runtime.event_store.close()
    services = MagicMock()
    services.create_session.return_value = (executor, loop)

    def build_runtime() -> MagicMock:
        receipt = json.loads((tmp_path / "runtime-finalized.json").read_text())
        assert receipt == {"exports_complete": False, "status": "bootstrap"}
        return runtime

    runtime_builder = MagicMock(side_effect=build_runtime)
    services_builder = MagicMock(return_value=services)
    monkeypatch.setattr("core.wiring.runtime.build_runtime", runtime_builder)
    monkeypatch.setattr("core.wiring.runtime.build_shared_services", services_builder)
    recording_hooks = HookSystem()
    recording_hooks.register_sink(
        HookPersistenceSink(runtime.event_store, session_key="fake-root", run_id="fake-run")
    )
    call_metadata = {
        "session_id": "fake-root",
        "llm_call_id": "fake-call",
        "llm_attempt_id": "fake-attempt",
        "model": settings.model,
        "provider": "openai",
        "adapter": "codex-oauth",
        "purpose": "agentic_loop",
    }
    recording_hooks.trigger(HookEvent.LLM_CALL_STARTED, call_metadata)
    recording_hooks.trigger(
        HookEvent.LLM_CALL_ENDED,
        {
            **call_metadata,
            "latency_ms": 1,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "cache_write_tokens": None,
            },
        },
    )
    events = runtime.event_store.read()
    evidence_reader = HookEventStore(db_path)
    reader = MagicMock(spec=HookEventStore, wraps=evidence_reader)
    monkeypatch.setattr(
        "core.observability.event_store.HookEventStore", MagicMock(return_value=reader)
    )
    connect = MagicMock(wraps=sqlite3.connect)
    # Limit inventory failure injection to the adapter; canonical readers still
    # use real sqlite3 and can recover the known root after this boundary fails.
    monkeypatch.setattr(harbor_runtime, "sqlite3", SimpleNamespace(connect=connect))
    trajectory_builder = MagicMock(side_effect=trajectory_from_sessions)
    exporter = MagicMock(side_effect=export_trajectory)
    writer = MagicMock(side_effect=atomic_write_json)
    monkeypatch.setattr(
        "core.observability.trajectory.trajectory_from_sessions", trajectory_builder
    )
    monkeypatch.setattr("core.observability.trajectory.export_trajectory", exporter)
    monkeypatch.setattr("core.memory.atomic_write.atomic_write_json", writer)
    instruction = tmp_path / "instruction.txt"
    instruction.write_text("fake instruction")
    args = SimpleNamespace(
        instruction=str(instruction),
        model=settings.model,
        effort="max",
        timeout=10,
        revision="a" * 40,
        verify_mode="rule_based",
    )
    yield SimpleNamespace(
        path=tmp_path,
        args=args,
        runtime=runtime,
        services=services,
        loop=loop,
        executor=executor,
        runtime_builder=runtime_builder,
        services_builder=services_builder,
        reader=reader,
        connect=connect,
        trajectory_builder=trajectory_builder,
        exporter=exporter,
        writer=writer,
        atomic_write_json=atomic_write_json,
        export_trajectory=export_trajectory,
        events=events,
        record_session=record_session,
        root_timeline=root_timeline,
        recording_hooks=recording_hooks,
        call_metadata=call_metadata,
    )
    evidence_reader.close()
    recording_hooks.close()


@pytest.mark.parametrize("requested_mode", ["off", "rule_based", "reflexion", "llm_judge"])
def test_native_preflight_uses_current_verify_alias_semantics(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, requested_mode: str
) -> None:
    from core.agent.verify import VerifyMode, get_verify_mode, resolve_verify_mode

    trial = native_trial
    trial.args.verify_mode = requested_mode
    monkeypatch.setenv("GEODE_VERIFY_MODE", requested_mode)
    assert get_verify_mode() == resolve_verify_mode(requested_mode) == VerifyMode.LLM_JUDGE
    resolve_active = MagicMock(wraps=get_verify_mode)
    monkeypatch.setattr("core.agent.verify.get_verify_mode", resolve_active)
    assert asyncio.run(_run_native(trial.args)) == 0
    resolve_active.assert_called_once_with()
    trial.loop.arun.assert_awaited_once_with("fake instruction")
    result = json.loads((trial.path / "runtime-result.json").read_text())
    # Preserve the supplied label; the frozen runtime owns its effective semantics.
    assert result["metadata"]["verify_mode"] == requested_mode
    assert result["metadata"]["effective_verify_mode"] == "llm_judge"
    for name in ("geode-trajectory.json", "geode-trajectory.private.json"):
        assert json.loads((trial.path / name).read_text())["outcome"] == result["metadata"]


def test_native_bootstrap_before_policy_resolution_records_unknown_effective_mode(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = native_trial
    resolve_active = MagicMock()
    monkeypatch.setattr("core.agent.verify.get_verify_mode", resolve_active)

    async def run() -> int:
        monkeypatch.setattr(
            asyncio.get_running_loop(),
            "add_signal_handler",
            MagicMock(side_effect=LookupError("synthetic signal setup failure")),
        )
        return await _run_native(trial.args)

    with pytest.raises(LookupError, match="synthetic signal setup failure"):
        asyncio.run(run())
    resolve_active.assert_not_called()
    trial.runtime_builder.assert_not_called()
    trial.loop.arun.assert_not_awaited()
    metadata = json.loads((trial.path / "runtime-result.json").read_text())["metadata"]
    assert metadata["verify_mode"] == "rule_based"
    assert metadata["effective_verify_mode"] is None
    assert metadata["execution_started"] is False


def test_native_preflight_rejects_raw_verify_mode_drift_despite_equivalent_aliases(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.agent.verify import get_verify_mode, resolve_verify_mode

    trial = native_trial
    monkeypatch.setenv("GEODE_VERIFY_MODE", "llm_judge")
    assert get_verify_mode() == resolve_verify_mode(trial.args.verify_mode)
    with pytest.raises(RuntimeError, match="runtime model/credential isolation preflight failed"):
        asyncio.run(_run_native(trial.args))
    trial.runtime_builder.assert_not_called()
    trial.loop.arun.assert_not_awaited()
    result = json.loads((trial.path / "runtime-result.json").read_text())
    assert result["metadata"]["execution_started"] is False


@pytest.mark.parametrize("success", [False, True])
def test_native_dreaming_uses_existing_deadlines_and_drains_before_session_end(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, success: bool
) -> None:
    trial = native_trial
    now = [100.0]
    monkeypatch.setattr(harbor_runtime.time, "monotonic", lambda: now[0])
    order: list[str] = []
    primary = ValueError("synthetic primary")
    if not success:
        trial.loop.arun.side_effect = primary
    dreaming = trial.runtime.dreaming_service
    dreaming.stop_admission.side_effect = lambda: order.append("stop_admission")
    dreaming.cancel.side_effect = lambda: order.append("cancel")

    async def settle(*, deadline: float) -> None:
        order.append("settle")
        assert deadline == 100 + trial.args.timeout

    async def close(*, deadline: float) -> None:
        order.append("drain")
        expected = (100 + trial.args.timeout if success else 100) + harbor_runtime._FINALIZE_SECONDS
        assert deadline == expected
        assert deadline - now[0] == expected - 107

    async def child_wait(*_args, **_kwargs):
        now[0] += 7  # Child cleanup consumes the same existing grace, not a fresh stage budget.

    manager = MagicMock()
    manager.list_collaboration_runs.return_value = [SimpleNamespace(task_id="child", status="done")]
    trial.record_session("child")
    manager.wait_for_task = AsyncMock(side_effect=child_wait)
    trial.executor._sub_agent_manager = manager
    dreaming.settle.side_effect = settle
    dreaming.aclose.side_effect = close

    def mark_completed() -> None:
        order.append("session_end")
        trial.root_timeline.record_session_end()

    def mark_error() -> None:
        order.append("session_end")
        trial.root_timeline.record_session_end(status="error")

    trial.loop.amark_session_completed.side_effect = mark_completed
    trial.loop.amark_session_error.side_effect = mark_error
    trial.services.close.side_effect = lambda: order.append("services_close")
    if success:
        assert asyncio.run(_run_native(trial.args)) == 0
    else:
        with pytest.raises(ValueError) as caught:
            asyncio.run(_run_native(trial.args))
        assert caught.value is primary
    assert order == (
        ["stop_admission", "settle", "drain", "session_end", "services_close"]
        if success
        else ["stop_admission", "cancel", "drain", "session_end", "services_close"]
    )
    trial.runtime.shutdown.assert_called_once_with(background_timeout_s=0)


@pytest.mark.parametrize(
    "outcome", ["success", "timeout", "cancel", "error", "canonical_timeout", "no_calls"]
)
def test_native_finalizes_success_timeout_and_cancel(
    native_trial: SimpleNamespace, outcome: str
) -> None:
    from core.agent.loop.models import TerminationReason

    trial = native_trial
    primary = {
        "timeout": TimeoutError("private failure"),
        "cancel": asyncio.CancelledError("private failure"),
        "error": ValueError("private failure"),
    }.get(outcome)
    if primary:
        trial.loop.arun.side_effect = primary
    if outcome == "canonical_timeout":
        trial.loop.arun.return_value.termination_reason = TerminationReason.TIME_BUDGET_EXPIRED
    if outcome == "no_calls":
        assert trial.runtime.event_store.clear() == 2
    if outcome in {"cancel", "error"}:
        with pytest.raises(type(primary)) as caught:
            asyncio.run(_run_native(trial.args))
        assert caught.value is primary
    else:
        assert asyncio.run(_run_native(trial.args)) == (124 if "timeout" in outcome else 0)
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    result = json.loads((trial.path / "runtime-result.json").read_text())
    assert receipt["exports_complete"] is True
    assert receipt["execution_started"] is True
    assert result["metadata"]["verify_mode"] == "rule_based"
    assert result["metadata"]["effective_verify_mode"] == "llm_judge"
    assert result["usage"]["whole_runtime_complete"] is False
    assert result["usage"]["input_tokens"] == (None if outcome == "no_calls" else 10)
    assert result["usage"]["cached_input_tokens"] == (None if outcome == "no_calls" else 0)
    assert trial.exporter.call_count == 2
    trial.services.close.assert_called_once()
    trial.runtime.shutdown.assert_called_once()
    assert trial.runtime.event_store.db_path == trial.path / "sessions.db"
    assert trial.runtime.event_store.db_path.is_file()
    assert "private failure" not in json.dumps(result)


@pytest.mark.parametrize(
    ("termination", "error"),
    [
        ("external_verification_required", "external_verification_required"),
        ("external_verification_required", "private unexpected error"),
        ("natural", "external_verification_required"),
    ],
)
def test_native_verification_hold_preserves_failure_without_synthetic_exception(
    native_trial: SimpleNamespace, termination: str, error: str
) -> None:
    trial = native_trial
    trial.loop.arun.return_value.termination_reason = termination
    trial.loop.arun.return_value.error = error
    held = termination == error == "external_verification_required"
    if held:
        assert asyncio.run(_run_native(trial.args)) == 1
    else:
        with pytest.raises(RuntimeError, match="native runtime reported an execution error"):
            asyncio.run(_run_native(trial.args))
    result = json.loads((trial.path / "runtime-result.json").read_text())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert result["metadata"]["termination_reason"] == termination
    assert result["metadata"]["error_type"] == (None if held else "RuntimeError")
    assert receipt["error_type"] == result["metadata"]["error_type"]
    assert receipt["exports_complete"] is True
    trial.loop.amark_session_completed.assert_not_awaited()
    trial.loop.amark_session_error.assert_awaited_once()
    assert "private unexpected error" not in json.dumps(result)


@pytest.mark.parametrize(
    "failure_stage",
    ["runtime_bootstrap", "services_bootstrap", "session_bootstrap", "shell_preflight"],
)
def test_native_bootstrap_failure_still_records_receipt(
    native_trial: SimpleNamespace, failure_stage: str
) -> None:
    trial = native_trial
    error = LookupError("private bootstrap failure")
    if failure_stage == "runtime_bootstrap":
        trial.runtime_builder.side_effect = error
    elif failure_stage == "services_bootstrap":
        trial.services_builder.side_effect = error
    elif failure_stage == "session_bootstrap":
        trial.services.create_session.side_effect = error
    else:
        trial.loop._tools = []
        error = None
    with pytest.raises(LookupError if error else RuntimeError) as caught:
        asyncio.run(_run_native(trial.args))
    if error:
        assert caught.value is error
    result = json.loads((trial.path / "runtime-result.json").read_text())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert result["metadata"]["execution_started"] is False
    assert receipt["status"] == "finalized"
    assert receipt["exports_complete"] is (failure_stage == "shell_preflight")
    trial.loop.arun.assert_not_awaited()
    if failure_stage == "runtime_bootstrap":
        trial.connect.assert_not_called()
        trial.exporter.assert_not_called()
    else:
        trial.runtime.shutdown.assert_called_once()
        assert trial.exporter.call_count == 2
    assert "private bootstrap failure" not in json.dumps(result)


@pytest.mark.parametrize(
    "primary_kind", ["success", "timeout", "canonical_timeout", "cancel", "error"]
)
@pytest.mark.parametrize(
    "failure_stage",
    [
        "child_wait",
        "background_drain",
        "session_end",
        "services_close",
        "runtime_shutdown",
        "usage_read",
        "session_inventory",
        "trajectory_digest",
        "trajectory_full",
        "runtime_result",
        "interrupted_finalization",
    ],
)
def test_native_failure_matrix_preserves_primary_and_other_exports(
    native_trial: SimpleNamespace, failure_stage: str, primary_kind: str
) -> None:
    trial = native_trial
    primary = {
        "timeout": TimeoutError("private primary"),
        "cancel": asyncio.CancelledError("private primary"),
        "error": ValueError("private primary"),
    }.get(primary_kind)
    if primary:
        trial.loop.arun.side_effect = primary
    if primary_kind == "canonical_timeout":
        from core.agent.loop.models import TerminationReason

        trial.loop.arun.return_value.termination_reason = TerminationReason.TIME_BUDGET_EXPIRED
    secondary = OSError("private secondary")
    expected_stage = failure_stage
    if failure_stage == "child_wait":
        children = [
            SimpleNamespace(task_id="child-a", status="cancelled"),
            SimpleNamespace(task_id="child-b", status="cancelled"),
        ]
        manager = MagicMock()
        manager.list_collaboration_runs.return_value = children
        manager.wait_for_task = AsyncMock(side_effect=[secondary, children[1]])
        trial.executor._sub_agent_manager = manager
        for child in children:
            trial.record_session(child.task_id)
    elif failure_stage == "background_drain":
        trial.runtime.dreaming_service.aclose.side_effect = secondary
    elif failure_stage in {"session_end", "interrupted_finalization"}:
        if failure_stage == "interrupted_finalization":
            secondary = asyncio.CancelledError("private second cancellation")
            expected_stage = "session_end"
        trial.loop.amark_session_completed.side_effect = secondary
        trial.loop.amark_session_error.side_effect = secondary
    elif failure_stage == "services_close":
        trial.services.close.side_effect = secondary
    elif failure_stage == "runtime_shutdown":
        trial.runtime.shutdown.side_effect = secondary
    elif failure_stage == "usage_read":
        trial.reader.read.side_effect = [trial.events, secondary]
    elif failure_stage == "session_inventory":
        trial.connect.side_effect = secondary
    elif failure_stage.startswith("trajectory_"):
        failed_name = (
            "geode-trajectory.json"
            if failure_stage.endswith("digest")
            else "geode-trajectory.private.json"
        )

        def export(path, trajectory):
            if path.name == failed_name:
                raise secondary
            return trial.export_trajectory(path, trajectory)

        trial.exporter.side_effect = export
    elif failure_stage == "runtime_result":

        def write(path, value):
            if path.name == "runtime-result.json":
                raise secondary
            trial.atomic_write_json(path, value)

        trial.writer.side_effect = write
    if primary_kind in {"timeout", "canonical_timeout"}:
        assert asyncio.run(_run_native(trial.args)) == 124
    else:
        expected_error = primary or secondary
        with pytest.raises(type(expected_error)) as caught:
            asyncio.run(_run_native(trial.args))
        assert caught.value is expected_error
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    expected_errors = [{"stage": expected_stage, "error_type": type(secondary).__name__}]
    if failure_stage in {"session_end", "interrupted_finalization"}:
        expected_errors.append({"stage": "trajectory_scope", "error_type": "RuntimeError"})
    assert receipt["finalization_errors"] == expected_errors
    assert trial.exporter.call_count == 2
    trial.services.close.assert_called_once()
    trial.runtime.shutdown.assert_called_once()
    if failure_stage == "child_wait":
        assert trial.executor._sub_agent_manager.wait_for_task.await_count == 2
    if failure_stage != "runtime_result":
        result = json.loads((trial.path / "runtime-result.json").read_text())
        assert result["metadata"]["finalization_errors"] == receipt["finalization_errors"]
        assert result["usage"]["whole_runtime_complete"] is False
        assert result["usage"]["input_tokens_observed_sum"] == 10
        if failure_stage in {
            "child_wait",
            "background_drain",
            "session_end",
            "services_close",
            "runtime_shutdown",
            "usage_read",
            "interrupted_finalization",
        }:
            assert result["usage"]["input_tokens"] is None
            assert result["usage"]["source_snapshot_complete"] is False
            full = json.loads((trial.path / "geode-trajectory.private.json").read_text())
            assert full["integrity"]["scope_complete"] is False
            if failure_stage in {"session_end", "interrupted_finalization"}:
                assert (
                    "session fake-root has no terminal event"
                    in full["integrity"]["scope_incompleteness"]
                )
    for path in trial.path.glob("*.json"):
        assert "private primary" not in path.read_text()
        assert "private secondary" not in path.read_text()
        assert "private second cancellation" not in path.read_text()


@pytest.mark.parametrize(
    "primary", [TimeoutError("private timeout"), asyncio.CancelledError("private cancel")]
)
def test_host_stop_error_does_not_mask_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: BaseException
) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    agent.model_name = "gpt-5.6-sol"
    agent.effort = "max"
    agent.verify_mode = "rule_based"
    agent.source = "subscription"
    agent.source_revision = "a" * 40
    agent.source_sha256 = "b" * 64
    agent.agent_timeout_sec = 900
    agent.render_instruction = lambda instruction: instruction
    agent.exec_as_agent = AsyncMock(side_effect=[None, None, primary])
    stop = AsyncMock(side_effect=OSError("private stop failure"))
    monkeypatch.setattr(harbor_runtime, "_stop_runtime", stop)
    with pytest.raises(type(primary)) as caught:
        asyncio.run(
            agent.run(
                "fake instruction", SimpleNamespace(upload_file=AsyncMock()), SimpleNamespace()
            )
        )
    assert caught.value is primary
    stop.assert_awaited_once()
    receipt = json.loads((tmp_path / "runtime-contract.json").read_text())
    assert receipt["finalization_errors"] == [
        {"stage": "host_stop_runtime", "error_type": "OSError"}
    ]
    assert "private" not in json.dumps(receipt)


@pytest.mark.parametrize(
    "health_source", ["before_close", "during_close", "sink_close", "mapping_anomaly"]
)
def test_native_rejects_degraded_observation_without_discarding_exports(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, health_source: str
) -> None:
    from core.hooks import HookEvent

    trial = native_trial
    trial.runtime.hooks.has_sink_failures = health_source == "before_close"
    if health_source == "during_close":
        trial.runtime.shutdown.side_effect = lambda **_kwargs: setattr(
            trial.runtime.hooks, "has_sink_failures", True
        )
    if health_source == "sink_close":
        sink = MagicMock()
        sink.close.side_effect = OSError("private buffered content")
        trial.recording_hooks.register_sink(sink, name="failed-flush")
        trial.runtime.hooks = trial.recording_hooks
        trial.runtime.shutdown.side_effect = lambda **_kwargs: trial.recording_hooks.close()
    if health_source == "mapping_anomaly":
        with monkeypatch.context() as patcher:
            patcher.setattr(
                "core.observability.activity_registry.map_hook_to_activity",
                MagicMock(side_effect=ValueError("synthetic mapping failure")),
            )
            trial.recording_hooks.trigger(HookEvent.LLM_CALL_ENDED, trial.call_metadata)
    with pytest.raises(RuntimeError, match="native observation degraded"):
        asyncio.run(_run_native(trial.args))
    result = json.loads((trial.path / "runtime-result.json").read_text())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert result["usage"]["whole_runtime_complete"] is False
    assert result["usage"]["source_snapshot_complete"] is False
    assert result["usage"]["input_tokens"] is None
    assert result["usage"]["input_tokens_observed_sum"] == 10
    assert result["usage"]["observation_status"] == "degraded"
    assert trial.exporter.call_count == 2


def test_native_terminal_receipt_failure_leaves_false_marker_and_secondary_metadata(
    native_trial: SimpleNamespace,
) -> None:
    trial = native_trial
    primary = asyncio.CancelledError("private cancellation")
    trial.loop.arun.side_effect = primary

    def write(path, value):
        if path.name == "runtime-finalized.json" and value["status"] == "finalized":
            raise OSError("private receipt failure")
        trial.atomic_write_json(path, value)

    trial.writer.side_effect = write
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(_run_native(trial.args))
    assert caught.value is primary
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    result = json.loads((trial.path / "runtime-result.json").read_text())
    assert receipt == {"exports_complete": False, "status": "bootstrap"}
    assert result["metadata"]["finalization_errors"] == [
        {"stage": "runtime_receipt", "error_type": "OSError"}
    ]
    assert trial.exporter.call_count == 2


def test_native_second_task_cancel_during_finalization_preserves_first_cancel(
    native_trial: SimpleNamespace,
) -> None:
    trial = native_trial
    execution_started = asyncio.Event()
    finalization_started = asyncio.Event()
    primary_errors = []

    async def run(_instruction):
        execution_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as error:
            primary_errors.append(error)
            raise

    async def mark_error():
        finalization_started.set()
        await asyncio.Event().wait()

    trial.loop.arun.side_effect = run
    trial.loop.amark_session_error.side_effect = mark_error

    async def cancel_twice():
        task = asyncio.create_task(_run_native(trial.args))
        await execution_started.wait()
        task.cancel("private first cancel")
        await finalization_started.wait()
        task.cancel("private second cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert caught.value is primary_errors[0]

    asyncio.run(cancel_twice())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["finalization_errors"] == [
        {"stage": "session_end", "error_type": "CancelledError"},
        {"stage": "trajectory_scope", "error_type": "RuntimeError"},
    ]
    assert trial.exporter.call_count == 2


def test_native_finalizer_setup_failure_keeps_execution_error_and_status(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial = native_trial
    primary = ValueError("private execution failure")
    trial.loop.arun.side_effect = primary
    monkeypatch.setattr(
        harbor_runtime,
        "_finalize_native",
        AsyncMock(side_effect=ImportError("private import failure")),
    )
    with pytest.raises(ValueError) as caught:
        asyncio.run(_run_native(trial.args))
    assert caught.value is primary
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["status"] == "finalization_failed"
    assert receipt["execution_started"] is True
    assert receipt["finalization_errors"] == [{"stage": "finalizer", "error_type": "ImportError"}]
    assert "private" not in json.dumps(receipt)


@pytest.mark.parametrize("primary_kind", ["success", "timeout", "cancel", "error"])
def test_native_signal_cleanup_failure_preserves_original_outcome(
    native_trial: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, primary_kind: str
) -> None:
    trial = native_trial
    primary = {
        "timeout": TimeoutError(),
        "cancel": asyncio.CancelledError(),
        "error": ValueError(),
    }.get(primary_kind)
    if primary:
        trial.loop.arun.side_effect = primary
    secondary = OSError("private signal cleanup failure")

    async def run():
        event_loop = asyncio.get_running_loop()
        remove = event_loop.remove_signal_handler

        def fail_remove(signum):
            assert signum == signal.SIGTERM
            remove(signum)
            raise secondary

        monkeypatch.setattr(event_loop, "remove_signal_handler", fail_remove)
        if primary_kind == "timeout":
            assert await _run_native(trial.args) == 124
        else:
            expected = primary or secondary
            with pytest.raises(type(expected)) as caught:
                await _run_native(trial.args)
            assert caught.value is expected

    asyncio.run(run())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    result = json.loads((trial.path / "runtime-result.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["finalization_errors"] == [
        {"stage": "signal_handler_remove", "error_type": "OSError"}
    ]
    assert result["metadata"]["finalization_errors"] == receipt["finalization_errors"]
    assert "private" not in json.dumps(receipt)


@pytest.mark.parametrize("primary_kind", ["success", "timeout", "cancel"])
def test_native_incomplete_canonical_scope_never_gets_complete_receipt(
    native_trial: SimpleNamespace, primary_kind: str
) -> None:
    trial = native_trial
    primary = {"timeout": TimeoutError(), "cancel": asyncio.CancelledError()}.get(primary_kind)
    if primary:
        trial.loop.arun.side_effect = primary
    # Simulate an acknowledged close with no retained terminal row. The real
    # canonical reader, not a fabricated integrity dict, must reject the scope.
    trial.loop.amark_session_completed.side_effect = None
    trial.loop.amark_session_error.side_effect = None
    if primary_kind == "timeout":
        assert asyncio.run(_run_native(trial.args)) == 124
    else:
        with pytest.raises(type(primary) if primary else RuntimeError) as caught:
            asyncio.run(_run_native(trial.args))
        if primary:
            assert caught.value is primary
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert receipt["finalization_errors"] == [
        {"stage": "trajectory_scope", "error_type": "RuntimeError"}
    ]
    assert trial.exporter.call_count == 2
    for name in ("geode-trajectory.json", "geode-trajectory.private.json"):
        integrity = json.loads((trial.path / name).read_text())["integrity"]
        assert integrity["scope_complete"] is False
        assert "session fake-root has no terminal event" in integrity["scope_incompleteness"]


def test_native_reduced_replay_does_not_invalidate_complete_canonical_scope(
    native_trial: SimpleNamespace,
) -> None:
    trial = native_trial
    trial.root_timeline.record_user_message("Fixture benchmark instruction")
    assert asyncio.run(_run_native(trial.args)) == 0
    assert (
        json.loads((trial.path / "runtime-finalized.json").read_text())["exports_complete"] is True
    )
    digest = json.loads((trial.path / "geode-trajectory.json").read_text())
    full = json.loads((trial.path / "geode-trajectory.private.json").read_text())
    assert digest["integrity"]["scope_complete"] is True
    assert digest["integrity"]["replay_complete"] is False
    assert full["integrity"]["scope_complete"] is True
    assert full["integrity"]["replay_complete"] is True


@pytest.mark.parametrize("authority", ["durable", "foreground"])
@pytest.mark.parametrize("primary_kind", ["success", "timeout", "cancel", "error"])
def test_native_missing_expected_child_invalidates_source_snapshot(
    native_trial: SimpleNamespace, authority: str, primary_kind: str
) -> None:
    trial = native_trial
    child = SimpleNamespace(task_id="known-child", status="completed")
    if authority == "durable":
        manager = MagicMock()
        manager.list_collaboration_runs.return_value = [child]
        manager.wait_for_task = AsyncMock(return_value=child)
        trial.executor._sub_agent_manager = manager
    else:
        trial.root_timeline.record_subagent_start(child.task_id)
    primary = {
        "timeout": TimeoutError("private timeout"),
        "cancel": asyncio.CancelledError("private cancellation"),
        "error": ValueError("private execution error"),
    }.get(primary_kind)
    if primary is not None:
        trial.loop.arun.side_effect = primary
    if primary_kind == "timeout":
        assert asyncio.run(_run_native(trial.args)) == 124
    else:
        with pytest.raises(type(primary) if primary else RuntimeError) as caught:
            asyncio.run(_run_native(trial.args))
        if primary is not None:
            assert caught.value is primary
    result = json.loads((trial.path / "runtime-result.json").read_text())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is False
    assert {"stage": "child_session_inventory", "error_type": "RuntimeError"} in receipt[
        "finalization_errors"
    ]
    assert result["usage"]["source_snapshot_complete"] is False
    assert result["usage"]["input_tokens_observed_sum"] == 10
    for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
        assert result["usage"][field] is None
    for call in trial.trajectory_builder.call_args_list:
        assert call.args[0] == ["fake-root", "known-child"]
    for name in ("geode-trajectory.json", "geode-trajectory.private.json"):
        trajectory = json.loads((trial.path / name).read_text())
        assert trajectory["integrity"]["scope_complete"] is False
        assert (
            "session known-child has no canonical events"
            in trajectory["integrity"]["scope_incompleteness"]
        )
        assert "private execution error" not in json.dumps(trajectory)
    assert trial.runtime.event_store.db_path == trial.path / "sessions.db"
    assert trial.runtime.event_store.db_path.is_file()


@pytest.mark.parametrize("authority", ["durable", "foreground", "both"])
def test_native_expected_child_with_canonical_rows_remains_complete_and_unique(
    native_trial: SimpleNamespace, authority: str
) -> None:
    trial = native_trial
    trial.record_session("known-child")
    if authority in {"durable", "both"}:
        child = SimpleNamespace(task_id="known-child", status="completed")
        manager = MagicMock()
        manager.list_collaboration_runs.return_value = [child]
        manager.wait_for_task = AsyncMock(return_value=child)
        trial.executor._sub_agent_manager = manager
    if authority in {"foreground", "both"}:
        # Start and stop are two declarations of the same child, not two sessions.
        trial.root_timeline.record_subagent_start("known-child")
        trial.root_timeline.record_subagent_complete("known-child", "completed")
    assert asyncio.run(_run_native(trial.args)) == 0
    result = json.loads((trial.path / "runtime-result.json").read_text())
    receipt = json.loads((trial.path / "runtime-finalized.json").read_text())
    assert receipt["exports_complete"] is True
    assert receipt["finalization_errors"] == []
    assert result["usage"]["source_snapshot_complete"] is True
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["whole_runtime_complete"] is False
    for call in trial.trajectory_builder.call_args_list:
        assert sorted(call.args[0]) == ["fake-root", "known-child"]
        assert len(call.args[0]) == 2
    assert trial.runtime.event_store.db_path == trial.path / "sessions.db"
    assert trial.runtime.event_store.db_path.is_file()


@pytest.mark.parametrize("stop_fails", [False, True])
def test_host_repeated_cancel_drains_owned_stop_before_log_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_fails: bool
) -> None:
    agent = object.__new__(GeodeRuntimeHarborAgent)
    agent.logs_dir = tmp_path
    agent.model_name = "gpt-5.6-sol"
    agent.effort = "max"
    agent.verify_mode = "rule_based"
    agent.source = "subscription"
    agent.source_revision = "a" * 40
    agent.source_sha256 = "b" * 64
    agent.agent_timeout_sec = 900
    agent.render_instruction = lambda instruction: instruction
    primary = asyncio.CancelledError("private original cancellation")
    agent.exec_as_agent = AsyncMock(side_effect=[None, None, primary])
    entered = asyncio.Event()
    release = asyncio.Event()
    stop_terminal = asyncio.Event()
    host_returned = asyncio.Event()

    async def stop(_environment):
        entered.set()
        await release.wait()
        stop_terminal.set()
        if stop_fails:
            raise OSError("private stop failure")

    monkeypatch.setattr(harbor_runtime, "_stop_runtime", stop)

    async def run():
        async def host():
            try:
                await agent.run(
                    "fake task", SimpleNamespace(upload_file=AsyncMock()), SimpleNamespace()
                )
            finally:
                assert stop_terminal.is_set()  # Harbor downloads only after run returns.
                host_returned.set()

        task = asyncio.create_task(host())
        await entered.wait()
        for _ in range(2):
            task.cancel("private repeated cancellation")
            # An event-loop barrier, not a time-based wait or real subprocess.
            barrier = asyncio.Event()
            asyncio.get_running_loop().call_soon(barrier.set)
            await barrier.wait()
            assert not task.done()
            assert not host_returned.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert caught.value is primary
        assert host_returned.is_set()
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(run())


def test_stop_runtime_owned_deadline_cancels_environment_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = []

    async def execute(**_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(harbor_runtime, "_FINALIZE_SECONDS", -5)
    with pytest.raises(TimeoutError):
        asyncio.run(_stop_runtime(SimpleNamespace(exec=execute)))
    assert cancelled == [True]
