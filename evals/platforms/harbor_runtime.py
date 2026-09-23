"""Opt-in native GEODE runtime inside a Harbor Docker task container.

The host adapter installs a content-addressed source bundle. The same module's
CLI owns one native session inside the container, not a second agent loop.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import re
import shlex
import signal
import sqlite3
import tarfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evals.platforms.harbor import HarborBaseAgent, _summarize_usage

if TYPE_CHECKING:

    class HarborInstalledAgent(HarborBaseAgent):
        async def ensure_system_dependencies(
            self, environment: Any, dependencies: tuple[str, ...]
        ) -> None: ...

        async def exec_as_root(self, environment: Any, command: str, **kwargs: Any) -> Any: ...

        async def exec_as_agent(self, environment: Any, command: str, **kwargs: Any) -> Any: ...

        def render_instruction(self, instruction: str) -> str: ...

        def _classify_exec_error(self, command: str, result: Any) -> Any: ...

else:
    try:
        HarborInstalledAgent = importlib.import_module(
            "harbor.agents.installed.base"
        ).BaseInstalledAgent
        if not hasattr(HarborInstalledAgent, "exec_as_agent"):
            HarborInstalledAgent = object
    except ImportError:  # Harbor is an opt-in, host-side dependency.
        HarborInstalledAgent = object

_INSTALL = "/installed-agent/geode"
_LOGS = "/logs/agent"
_UV_VERSION = "0.10.2"
_PYTHON_VERSION = "3.12.12"
_FINALIZE_SECONDS = 20


async def _stop_runtime(
    environment: Any, *, module: str = "evals.platforms.harbor_runtime"
) -> None:
    """Wait for export and process exit before Harbor downloads agent logs."""
    if module not in {"evals.platforms.harbor_runtime", "evals.platforms.harbor_handoff"}:
        raise ValueError("unknown runtime entry point")
    command = f"""import json, os, signal, time
from pathlib import Path
p = Path('{_LOGS}/runtime.pid')
if not p.is_file():
    raise RuntimeError('runtime never recorded its process identity')
pid = int(p.read_text())
proc = Path('/proc') / str(pid)
if pid <= 1:
    raise RuntimeError('invalid runtime process identity')
try:
    if {module.encode()!r} not in (proc / 'cmdline').read_bytes().split(b'\\0'):
        raise RuntimeError('runtime process identity changed')
    os.kill(pid, signal.SIGTERM)
except (FileNotFoundError, ProcessLookupError):
    pass
deadline = time.monotonic() + {_FINALIZE_SECONDS}
while True:
    try:
        if (proc / 'stat').read_text().split()[2] == 'Z':
            break
    except FileNotFoundError:
        break
    if time.monotonic() >= deadline:
        raise RuntimeError('runtime finalization deadline exceeded')
    time.sleep(0.1)
p = Path('{_LOGS}/runtime-finalized.json')
if not p.is_file() or json.loads(p.read_text()).get('exports_complete') is not True:
    raise RuntimeError('runtime export incomplete')
"""
    # This deadline belongs to the stop task, not its repeatedly cancellable
    # host caller. The environment operation must cooperate with cancellation.
    async with asyncio.timeout(_FINALIZE_SECONDS + 5):
        result = await environment.exec(
            command="python3 -c " + shlex.quote(command), timeout_sec=_FINALIZE_SECONDS + 5
        )
    if result.return_code != 0:
        raise RuntimeError("runtime shutdown/export incomplete; trial is infrastructure-invalid")


def _verify_bundle(path: Path, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("source_sha256 must be a SHA-256 digest")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("source bundle hash mismatch")
    with tarfile.open(path) as archive:
        names = set()
        for member in archive:
            # Source archives are files/directories only; never follow links.
            parts = Path(member.name).parts
            if (
                member.name.startswith("/")
                or ".." in parts
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe source bundle member")
            names.add(member.name)
        if not {"pyproject.toml", "uv.lock", "core/wiring/runtime.py"} <= names:
            raise ValueError("source bundle is missing native runtime or lockfile")


class GeodeRuntimeHarborAgent(HarborInstalledAgent):
    """Native runtime composition, with all local execution inside Harbor."""

    SUPPORTS_ATIF = True

    @staticmethod
    def name() -> str:
        return "geode-runtime"

    def __init__(
        self,
        *args: Any,
        source_bundle: str,
        source_sha256: str,
        source_revision: str,
        provider: str = "openai",
        source: str = "subscription",
        effort: str = "max",
        verify_mode: str = "rule_based",
        agent_timeout_sec: float,
        **kwargs: Any,
    ) -> None:
        try:
            harbor_version = importlib.metadata.version("harbor")
        except importlib.metadata.PackageNotFoundError:
            harbor_version = None
        if harbor_version != "0.22.0":
            raise RuntimeError("native GEODE integration is validated only with harbor==0.22.0")
        super().__init__(*args, **kwargs)
        from core.agent.verify import resolve_verify_mode

        resolve_verify_mode(verify_mode)
        # The frozen bundle owns alias semantics; older bundles distinguish these modes.
        self.verify_mode = verify_mode.strip().lower()
        self.provider = provider
        self.source = source
        self.effort = effort
        self.agent_timeout_sec = agent_timeout_sec
        if self.provider != "openai" or self.source != "subscription":
            raise ValueError("this adapter requires explicit OpenAI subscription routing")
        if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
            raise ValueError("source_revision must be a full commit SHA")
        if not self.model_name:
            raise ValueError("an explicit model is required")
        if not math.isfinite(self.agent_timeout_sec) or self.agent_timeout_sec <= 0:
            raise ValueError("an explicit positive agent timeout is required")
        self.source_bundle = Path(source_bundle).resolve(strict=True)
        self.source_sha256 = source_sha256
        self.source_revision = source_revision
        _verify_bundle(self.source_bundle, source_sha256)

    def version(self) -> str:
        return self.source_revision

    async def install(self, environment: Any) -> None:
        # Fail closed on a non-container environment; never start the runtime
        # against the host filesystem. No operator workspace/config is mounted.
        await self.exec_as_root(environment, command="test -f /.dockerenv", timeout_sec=10)
        _verify_bundle(self.source_bundle, self.source_sha256)
        await self.exec_as_root(
            environment,
            command=f"test ! -e {_INSTALL} && mkdir -p {_INSTALL} {_LOGS}",
            timeout_sec=10,
        )
        await environment.upload_file(self.source_bundle, f"{_INSTALL}/source.tar.gz")
        await self.ensure_system_dependencies(environment, ("python3", "python_pip", "tar", "xz"))
        command = (
            f"tar -xzf {_INSTALL}/source.tar.gz -C {_INSTALL} && "
            f"python3 -m pip install --disable-pip-version-check uv=={_UV_VERSION} && "
            f"uv sync --project {_INSTALL} --frozen --no-dev --extra desktop "
            f"--python {_PYTHON_VERSION} > {_LOGS}/runtime-install.log 2>&1"
        )
        await self.exec_as_root(environment, command=command, timeout_sec=600)

        from core.auth.codex_cli_oauth import codex_auth_path

        auth = codex_auth_path()
        if not auth.is_file():
            raise RuntimeError("subscription credential is unavailable")
        # Upload via the transport, never interpolate credential bytes in shell
        # commands, logs, run metadata, or the task instruction.
        result = await self.exec_as_agent(environment, command='printf "%s" "$HOME"')
        home = str(result.stdout).strip()
        if not home.startswith("/") or "\n" in home:
            raise RuntimeError("unable to resolve container agent home")
        credential_dir = shlex.quote(home + "/.codex")
        await self.exec_as_agent(
            environment, command=f"mkdir -p {credential_dir} && chmod 700 {credential_dir}"
        )
        await self._upload_credential(environment, auth, home + "/.codex/auth.json")

    async def _upload_credential(self, environment: Any, source: Path, target: str) -> None:
        # Compose copies host ownership; an unset task user may still use image USER.
        result = await self.exec_as_agent(environment, command="id -u")
        uid = str(result.stdout).strip()
        if re.fullmatch(r"[0-9]+", uid) is None:
            raise RuntimeError("unable to resolve container agent uid")
        await environment.upload_file(source, target)
        destination = shlex.quote(target)
        await self.exec_as_root(
            environment,
            command=f"chmod 600 {destination} && chown {uid} {destination}",
        )

    def _classify_exec_error(self, command: str, result: Any) -> Any:
        if result.return_code == 124 and " -m evals.platforms.harbor_runtime " in command:
            error = importlib.import_module("harbor.trial.errors").AgentTimeoutError
            return error(f"Agent execution timed out after {self.agent_timeout_sec} seconds")
        return super()._classify_exec_error(command, result)

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        from core.memory.atomic_write import atomic_write_json, atomic_write_text

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        instruction_path = self.logs_dir / "instruction.txt"
        atomic_write_text(instruction_path, self.render_instruction(instruction))
        await environment.upload_file(instruction_path, f"{_INSTALL}/instruction.txt")
        model = str(self.model_name).removeprefix("geode/")
        # Workers inherit GEODE_HOME, not arbitrary parent environment knobs.
        # Persist the selected role models/source/effort in the native config.
        config = (
            f"[llm]\nprimary_model = {json.dumps(model)}\n"
            f'model_policy_path = "{_INSTALL}/model-policy.toml"\n'
            f"learning_extract_model = {json.dumps(model)}\n"
            f"act_model = {json.dumps(model)}\njudge_model = {json.dumps(model)}\n"
            'openai_credential_source = "openai-codex"\n'
            'anthropic_credential_source = "none"\n'
            f"[agentic]\neffort = {json.dumps(self.effort)}\n"
            f"[cognitive]\nreflection_model = {json.dumps(model)}\n"
        )
        config_path = self.logs_dir / "runtime-config.toml"
        atomic_write_text(config_path, config)
        policy_path = self.logs_dir / "model-policy.toml"
        atomic_write_text(policy_path, f"[policy]\nallowlist = [{json.dumps(model)}]\n")
        await environment.upload_file(policy_path, f"{_INSTALL}/model-policy.toml")
        await self.exec_as_agent(
            environment, command=f"test ! -e {_LOGS}/geode-home && mkdir {_LOGS}/geode-home"
        )
        await environment.upload_file(config_path, f"{_LOGS}/geode-home/config.toml")
        # This profile belongs only to the fresh task container. Approval
        # bypass alone does not admit shell tools in the native profile policy.
        profile_path = self.logs_dir / "runtime-preferences.toml"
        atomic_write_text(profile_path, "[policy]\nallow_dangerous = true\n")
        await self.exec_as_agent(environment, command=f"mkdir {_LOGS}/geode-home/user_profile")
        await environment.upload_file(
            profile_path, f"{_LOGS}/geode-home/user_profile/preferences.toml"
        )
        args = [
            f"{_INSTALL}/.venv/bin/python",
            "-m",
            "evals.platforms.harbor_runtime",
            "--instruction",
            f"{_INSTALL}/instruction.txt",
            "--model",
            model,
            "--effort",
            self.effort,
            "--timeout",
            str(self.agent_timeout_sec),
            "--revision",
            self.source_revision,
            "--verify-mode",
            self.verify_mode,
        ]
        # This environment belongs only to the new container process.
        env = {
            "PYTHONFAULTHANDLER": "1",
            "GEODE_HOME": f"{_LOGS}/geode-home",
            "GEODE_MODEL": model,
            "GEODE_AGENTIC_EFFORT": self.effort,
            "GEODE_OPENAI_CREDENTIAL_SOURCE": "openai-codex",
            "GEODE_ANTHROPIC_CREDENTIAL_SOURCE": "none",
            "GEODE_DANGEROUSLY_SKIP_PERMISSIONS": "true",
            "GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT": "1",
            "GEODE_LEARNING_EXTRACT_MODEL": model,
            "GEODE_COGNITIVE_REFLECTION_MODEL": model,
            "GEODE_ACT_MODEL": model,
            "GEODE_JUDGE_MODEL": model,
            "GEODE_VERIFY_MODE": self.verify_mode,
        }
        atomic_write_json(
            self.logs_dir / "runtime-contract.json",
            {
                "source_revision": self.source_revision,
                "source_sha256": self.source_sha256,
                "runtime": "core.wiring.runtime:build_runtime+build_shared_services",
                "external_search_loop": False,
                "model": model,
                "source": self.source,
                "effort": self.effort,
                "verify_mode": self.verify_mode,
                "required_tools": ["run_bash"],
                "profile_scope": "fresh task container only; allow_dangerous=true",
                "effort_scope": (
                    "root and auxiliary OpenAI calls inherit the owning loop effort; "
                    "explicit worker overrides remain distinct and require observed-call validation"
                ),
                "agent_timeout_sec": self.agent_timeout_sec,
                "uv_version": _UV_VERSION,
                "python_version": _PYTHON_VERSION,
            },
        )
        try:
            await self.exec_as_agent(
                environment,
                command=shlex.join(args) + f" > {_LOGS}/runtime.log 2>&1",
                env=env,
            )
        except BaseException as primary_error:
            # Harbor owns the deadline. Request finalization from the exact
            # trial process, without starting another inference or extending it.
            stop_task = asyncio.create_task(_stop_runtime(environment))
            # Keep this exact, independently bounded stop task owned until it
            # is terminal. A second cancellation must not race log download.
            while not stop_task.done():
                try:
                    await asyncio.shield(stop_task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break  # Read its terminal exception below, once.
            try:
                stop_task.result()
            except BaseException as stop_error:
                # The host execution failure remains authoritative. Do not put
                # exception text (which can contain task data) in the receipt.
                try:
                    path = self.logs_dir / "runtime-contract.json"
                    contract = json.loads(path.read_text())
                    contract["finalization_errors"] = [
                        {"stage": "host_stop_runtime", "error_type": type(stop_error).__name__}
                    ]
                    atomic_write_json(path, contract)
                except BaseException as receipt_error:
                    primary_error.add_note(
                        "host finalization receipt failed: " + type(receipt_error).__name__
                    )
            raise

    def populate_context_post_run(self, context: Any) -> None:
        # Harbor invokes this after downloading logs, including failed trials.
        require_handoff_replay = self.name() == "geode-handoff"
        path = self.logs_dir / "runtime-result.json"
        if not path.is_file():
            if require_handoff_replay:
                raise ValueError("handoff replay requires runtime-result.json")
            return
        value = json.loads(path.read_text())
        # Reflection, judging, text completion and hosted web search do not
        # all emit these usage events. Keep the AgenticLoop subtotal, never
        # present it as a whole-runtime total beside native Codex totals.
        context.n_input_tokens = None
        context.n_output_tokens = None
        context.n_cache_tokens = None
        context.cost_usd = None  # Subscription usage is not a billed API cost.
        context.metadata = value["metadata"]
        if (
            context.metadata.get("finalization_errors")
            or value["usage"].get("source_snapshot_complete") is False
        ):
            return  # Retain failure metadata without promoting a partial replay.
        trajectory_path = self.logs_dir / "geode-trajectory.private.json"
        if not trajectory_path.is_file():
            if require_handoff_replay:
                raise ValueError("handoff replay requires complete canonical content")
            return
        trajectory = json.loads(trajectory_path.read_text())
        if require_handoff_replay:
            from core.observability.trajectory import verify_trajectory_integrity

            if not verify_trajectory_integrity(trajectory)["replay_complete"]:
                raise ValueError("handoff replay requires complete canonical content")
        if not trajectory["integrity"]["scope_complete"]:
            return
        from evals.platforms.harbor import (
            _atif_trajectory_from_geode,
            _write_atif_trajectory,
            write_harbor_recording,
        )

        # Harbor and its ATIF validator stay host-side. The native runtime
        # container does not need Harbor's dependencies or runner privileges.
        atif = _atif_trajectory_from_geode(
            trajectory,
            model=str(self.model_name).removeprefix("geode/"),
            provider=self.provider,
            source=self.source,
            effort=None,  # ATIF tool steps are not LLM calls; do not infer per-step effort.
            version=self.source_revision,
            metrics={
                "input_tokens": None,
                "output_tokens": None,
                "cache_read_tokens": None,
            },
        )
        atif["agent"]["name"] = self.name()
        atif["extra"]["configured_root_effort"] = self.effort
        atif["agent"]["tool_definitions"] = value["tool_definitions"]
        _write_atif_trajectory(self.logs_dir / "trajectory.json", atif)
        write_harbor_recording(self.logs_dir / "trajectory.json")


async def _finalize_native(
    runtime: Any,
    services: Any,
    executor: Any,
    loop: Any,
    *,
    succeeded: bool,
    metadata: dict[str, Any],
    event_loop: asyncio.AbstractEventLoop | None,
    execution_deadline: float | None = None,
) -> BaseException | None:
    """Recover existing exports independently; never replace an execution error."""
    from core.memory.atomic_write import atomic_write_json
    from core.observability.event_store import HookEventStore
    from core.observability.session_timeline import SessionEventKind
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions

    errors: list[dict[str, str]] = []
    first_error: BaseException | None = None
    finalization_started = time.monotonic()
    finalization_deadline = (
        execution_deadline if execution_deadline is not None else finalization_started
    ) + _FINALIZE_SECONDS
    if not succeeded:
        finalization_deadline = min(finalization_deadline, finalization_started + _FINALIZE_SECONDS)

    def record_error(stage: str, error: BaseException) -> None:
        nonlocal first_error
        if first_error is None:
            first_error = error
        # Several children may fail identically; the receipt is bounded by
        # stage/error classes, not child count or private exception contents.
        entry = {"stage": stage, "error_type": type(error).__name__}
        if entry not in errors:
            errors.append(entry)

    @contextmanager
    def stage(name: str) -> Iterator[None]:
        try:
            yield
        except BaseException as error:
            record_error(name, error)

    dreaming = runtime.dreaming_service if runtime is not None else None
    if dreaming is not None:
        with stage("background_admission"):
            dreaming.stop_admission()
            if not succeeded:
                dreaming.cancel()

    expected_child_sessions: set[str] = set()
    if executor is not None and loop is not None:
        with stage("children"):
            manager = executor._sub_agent_manager
            if manager is not None:
                children = manager.list_collaboration_runs(loop._session_id)
                expected_child_sessions.update(child.task_id for child in children)
                for child in children:
                    with stage("child_interrupt"):
                        manager.interrupt_task(loop._session_id, child.task_id)
                # Drain all waits even when one fails, before reading sources.
                results = await asyncio.gather(
                    *(
                        manager.wait_for_task(loop._session_id, child.task_id, timeout_s=10)
                        for child in children
                    ),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        record_error("child_wait", result)
                if any(
                    child.status in {"pending", "running"}
                    for child in manager.list_collaboration_runs(loop._session_id)
                ):
                    raise RuntimeError("child shutdown incomplete")
    if dreaming is not None:
        if succeeded and execution_deadline is not None:
            # Agent budget ending switches to cancellation, not a new execution window.
            with stage("background_settle"), suppress(TimeoutError):
                await dreaming.settle(deadline=execution_deadline)
        with stage("background_drain"):
            await dreaming.aclose(deadline=finalization_deadline)
    metadata["background_lifecycle_policy"] = (
        "admitted-jobs-within-agent-deadline-then-cancellation-only-grace"
    )
    if loop is not None:
        with stage("session_end"):
            if succeeded:
                await loop.amark_session_completed()
            else:
                await loop.amark_session_error()
    # Stop native writers before paging the isolated trial's durable sources.
    if services is not None:
        with stage("services_close"):
            services.close()
    if runtime is not None:
        with stage("runtime_shutdown"):
            runtime.shutdown(background_timeout_s=0)

    events: list[Any] = []
    reader = None
    if runtime is not None:
        with stage("usage_read"):
            reader = HookEventStore(db_path=runtime.event_store.db_path)
            while batch := reader.read(limit=500, offset=len(events)):
                events.extend(batch)
        if reader is not None:
            with stage("usage_reader_close"):
                reader.close()

    sessions: list[str] = []
    session_id = metadata["geode_session_id"]
    if runtime is not None:
        with (
            stage("session_inventory"),
            sqlite3.connect(runtime.event_store.db_path) as connection,
        ):
            sessions = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT session_id FROM session_events ORDER BY session_id"
                )
            ]
            if session_id:
                # Foreground delegates have no durable collaboration handle. Their
                # parent-authored lifecycle rows carry the same task_id passed to
                # WorkerRequest and AgenticLoopConfig.session_id, not model prose.
                for row in connection.execute(
                    "SELECT payload_json FROM session_events "
                    "WHERE session_id = ? AND kind IN (?, ?)",
                    (
                        session_id,
                        SessionEventKind.SUBAGENT_STARTED.value,
                        SessionEventKind.SUBAGENT_STOPPED.value,
                    ),
                ):
                    payload = json.loads(row[0])
                    task_id = payload.get("task_id") if isinstance(payload, dict) else None
                    if not isinstance(task_id, str) or not task_id:
                        raise ValueError("canonical child lifecycle identity is invalid")
                    expected_child_sessions.add(task_id)
        missing_children = expected_child_sessions.difference(sessions)
        if missing_children:
            record_error("child_session_inventory", RuntimeError("child canonical history missing"))
        # Keep absent expected identities so the existing trajectory reader also
        # reports their missing canonical rows instead of silently dropping them.
        sessions.extend(sorted(missing_children))
        if session_id and session_id not in sessions:
            sessions.append(session_id)

    snapshot_complete = runtime is not None and loop is not None and not errors
    usage = _summarize_usage([])
    with stage("usage_summary"):
        usage = _summarize_usage(
            events,
            known_sink_failure=runtime is not None and runtime.hooks.has_sink_failures is True,
        )
    if usage.get("observation_status") == "degraded":
        record_error("observation_health", RuntimeError("native observation degraded"))
    snapshot_complete = snapshot_complete and not errors
    usage["source_snapshot_complete"] = snapshot_complete
    if not snapshot_complete:
        # Matching surviving IDs cannot prove a complete source snapshot.
        # Keep the observed sums without turning them into complete totals.
        for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"):
            usage[field] = None
    metadata.update(usage=usage, finalization_errors=errors)

    canonical_scope_complete = True
    if runtime is not None:
        for policy, name in (
            ("digest", "geode-trajectory.json"),
            ("full", "geode-trajectory.private.json"),
        ):
            if not sessions:
                continue  # No invented session identity for failed bootstrap.
            with stage(f"trajectory_{policy}"):
                trajectory = trajectory_from_sessions(
                    sessions,
                    trajectory_id=f"harbor-{session_id or sessions[0]}",
                    source={"harness": "harbor", "session": session_id or sessions[0]},
                    db_path=runtime.event_store.db_path,
                    outcome=metadata,
                    provenance={"adapter": "evals.platforms.harbor_runtime"},
                    privacy={"review_state": "local"},
                    content_policy=policy,
                )
                canonical_scope_complete = (
                    canonical_scope_complete and trajectory["integrity"]["scope_complete"] is True
                )
                if not snapshot_complete or any(e["stage"] == "session_inventory" for e in errors):
                    integrity = trajectory["integrity"]
                    integrity.update(complete=False, scope_complete=False, replay_complete=False)
                    integrity["scope_incompleteness"].append("native source snapshot incomplete")
                    integrity["incompleteness"] = list(
                        dict.fromkeys(
                            integrity["scope_incompleteness"] + integrity["replay_incompleteness"]
                        )
                    )
                export_trajectory(Path(_LOGS) / name, trajectory)

    if sessions and not canonical_scope_complete:
        record_error("trajectory_scope", RuntimeError("native canonical scope incomplete"))

    if event_loop is not None:
        with stage("signal_handler_remove"):
            event_loop.remove_signal_handler(signal.SIGTERM)
    with stage("runtime_result"):
        atomic_write_json(
            Path(_LOGS) / "runtime-result.json",
            {
                "usage": usage,
                "metadata": metadata,
                "tool_definitions": [
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {}),
                    }
                    for tool in (loop._tools if loop is not None else [])
                ],
            },
        )
    with stage("runtime_receipt"):
        atomic_write_json(
            Path(_LOGS) / "runtime-finalized.json",
            {
                "exports_complete": bool(snapshot_complete and sessions and not errors),
                "status": "finalized",
                "execution_started": metadata["execution_started"],
                "error_type": metadata["error_type"],
                "finalization_errors": errors,
            },
        )
    if any(error["stage"] == "runtime_receipt" for error in errors):
        # A failed receipt replacement leaves the initial false marker. Retain
        # its bounded failure classification in the other existing export.
        with stage("runtime_result_update"):
            path = Path(_LOGS) / "runtime-result.json"
            result = json.loads(path.read_text())
            result["metadata"]["finalization_errors"] = errors
            atomic_write_json(path, result)
    return first_error


async def _run_native(args: argparse.Namespace) -> int:
    # Imports follow container/env checks so native path singletons can never
    # initialize against the operator's home during an accidental host launch.
    if not Path("/.dockerenv").is_file() or os.environ.get("GEODE_HOME") != f"{_LOGS}/geode-home":
        raise RuntimeError("container-local runtime entry point only")
    started = time.monotonic()
    Path(f"{_LOGS}/runtime.pid").write_text(str(os.getpid()))
    from core.memory.atomic_write import atomic_write_json

    atomic_write_json(
        Path(_LOGS) / "runtime-finalized.json", {"exports_complete": False, "status": "bootstrap"}
    )
    runtime = services = executor = loop = None
    event_loop = asyncio.get_running_loop()
    signal_installed = False
    outcome = "error"
    exit_code = 0
    error_type: str | None = None
    primary_error: BaseException | None = None
    succeeded = False
    execution_started = False
    try:
        task = asyncio.current_task()
        assert task is not None
        event_loop.add_signal_handler(signal.SIGTERM, task.cancel)
        signal_installed = True
        from core.agent.loop.models import TerminationReason, is_successful_task_termination
        from core.agent.session_mode import SessionMode
        from core.agent.verify import get_verify_mode, resolve_verify_mode
        from core.config import load_model_policy, settings
        from core.wiring.runtime import build_runtime, build_shared_services

        if (
            settings.model != args.model
            or settings.agentic_effort != args.effort
            or settings.model_policy_path != f"{_INSTALL}/model-policy.toml"
            or load_model_policy().allowlist != [args.model]
            or settings.openai_credential_source != "openai-codex"
            or settings.anthropic_credential_source != "none"
            or get_verify_mode() != resolve_verify_mode(args.verify_mode)
            or os.environ.get("GEODE_VERIFY_MODE") != args.verify_mode
            or settings.judge_model != args.model
            or any(value for key, value in os.environ.items() if key.endswith("API_KEY"))
        ):
            raise RuntimeError("runtime model/credential isolation preflight failed")
        runtime = build_runtime()
        if runtime.dreaming_service is not None:
            runtime.dreaming_service.set_deadline(started + args.timeout)
        services = build_shared_services(
            mcp_manager=runtime.mcp_manager,
            skill_registry=runtime.skill_registry,
            hook_system=runtime.hooks,
            hook_registry=runtime.hook_registry,
            middleware_registry=runtime.middleware_registry,
            policy_sources=runtime.policy_sources,
            activity_sink_provider=runtime.activity_sink_provider,
            lane_queue=runtime.lane_queue,
            persistence=runtime.persistence_services,
            integrations=runtime.integration_services,
            scheduler_service=runtime.scheduler_service,
            user_profile=runtime.user_profile,
        )
        executor, loop = services.create_session(
            SessionMode.REPL, time_budget_override=args.timeout
        )
        if "run_bash" not in {tool["name"] for tool in loop._tools} or (
            executor._session_scope_denial("run_bash") is not None
        ):
            raise RuntimeError("runtime shell capability preflight failed")
        async with asyncio.timeout(max(0, args.timeout - (time.monotonic() - started))):
            execution_started = True
            result = await loop.arun(Path(args.instruction).read_text())
        outcome = str(result.termination_reason)
        if result.error and not (
            result.termination_reason == TerminationReason.EXTERNAL_VERIFICATION_REQUIRED
            and result.error == TerminationReason.EXTERNAL_VERIFICATION_REQUIRED
        ):
            raise RuntimeError("native runtime reported an execution error")
        succeeded = is_successful_task_termination(result.termination_reason)
        if result.termination_reason in {
            TerminationReason.TIME_BUDGET_EXPIRED,
            TerminationReason.SESSION_TIME_BUDGET_EXPIRED,
            TerminationReason.SESSION_TIME_BUDGET_HANDOFF,
        }:
            exit_code = 124
        elif not succeeded:
            exit_code = 1
    except TimeoutError as exc:
        primary_error = exc
        error_type = "TimeoutError"
        if execution_started:
            outcome = "time_budget"
            exit_code = 124
    except BaseException as exc:
        primary_error = exc
        error_type = type(exc).__name__
        if isinstance(exc, asyncio.CancelledError):
            outcome = "external_cancellation"
    finally:
        finalization_error = None
        finalizer_returned = False
        try:
            finalization_error = await _finalize_native(
                runtime,
                services,
                executor,
                loop,
                succeeded=succeeded,
                metadata={
                    "geode_session_id": loop._session_id if loop is not None else None,
                    "termination_reason": outcome,
                    "error_type": error_type,
                    "execution_started": execution_started,
                    "source_revision": args.revision,
                    "verify_mode": args.verify_mode,
                    "score_authority": "Harbor task verifier, not this runtime receipt",
                },
                event_loop=event_loop if signal_installed else None,
                execution_deadline=started + args.timeout,
            )
            finalizer_returned = True
        except BaseException as exc:
            finalization_error = exc
            # Even finalizer import/setup failure must leave a bounded status,
            # not an apparent bootstrap-only receipt after execution started.
            try:
                atomic_write_json(
                    Path(_LOGS) / "runtime-finalized.json",
                    {
                        "exports_complete": False,
                        "status": "finalization_failed",
                        "execution_started": execution_started,
                        "error_type": error_type,
                        "finalization_errors": [
                            {"stage": "finalizer", "error_type": type(exc).__name__}
                        ],
                    },
                )
            except BaseException as receipt_error:
                exc.add_note("finalization receipt failed: " + type(receipt_error).__name__)
        finally:
            if signal_installed and not finalizer_returned:
                try:
                    event_loop.remove_signal_handler(signal.SIGTERM)
                except BaseException as exc:
                    if finalization_error is None:
                        finalization_error = exc
                    for name in ("runtime-finalized.json", "runtime-result.json"):
                        try:
                            path = Path(_LOGS) / name
                            value = json.loads(path.read_text())
                            if name == "runtime-finalized.json":
                                value["exports_complete"] = False
                                metadata = value
                            else:
                                metadata = value["metadata"]
                            metadata.setdefault("finalization_errors", []).append(
                                {"stage": "signal_handler_remove", "error_type": type(exc).__name__}
                            )
                            atomic_write_json(path, value)
                        except BaseException as receipt_error:
                            exc.add_note(
                                "signal cleanup receipt failed: " + type(receipt_error).__name__
                            )
    if primary_error is not None:
        if not (isinstance(primary_error, TimeoutError) and execution_started):
            raise primary_error
    elif finalization_error is not None and exit_code == 0:
        raise finalization_error
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--verify-mode", default="rule_based")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")
    return asyncio.run(_run_native(args))


if __name__ == "__main__":
    raise SystemExit(main())
