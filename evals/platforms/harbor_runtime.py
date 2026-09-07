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


async def _stop_runtime(environment: Any) -> None:
    """Wait for export and process exit before Harbor downloads agent logs."""
    command = f"""import os, signal, time
from pathlib import Path
p = Path('{_LOGS}/runtime.pid')
if not p.is_file():
    raise RuntimeError('runtime never recorded its process identity')
pid = int(p.read_text())
proc = Path('/proc') / str(pid)
if pid <= 1:
    raise RuntimeError('invalid runtime process identity')
try:
    if b'evals.platforms.harbor_runtime' not in (proc / 'cmdline').read_bytes():
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
if not Path('{_LOGS}/runtime-finalized.json').is_file():
    raise RuntimeError('runtime export incomplete')
"""
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
        await environment.upload_file(auth, home + "/.codex/auth.json")
        await self.exec_as_root(
            environment,
            command=f"chmod 600 {credential_dir}/auth.json"
            + (
                f" && chown {shlex.quote(str(environment.default_user))} {credential_dir}/auth.json"
                if environment.default_user is not None
                else ""
            ),
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
        ]
        # This environment belongs only to the new container process.
        env = {
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
                "effort_scope": "root setting; native worker difficulty and wrap-up policies apply",
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
        except BaseException:
            # Harbor owns the deadline. Request finalization from the exact
            # trial process, without starting another inference or extending it.
            await asyncio.shield(_stop_runtime(environment))
            raise

    def populate_context_post_run(self, context: Any) -> None:
        # Harbor invokes this after downloading logs, including failed trials.
        path = self.logs_dir / "runtime-result.json"
        if not path.is_file():
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
        trajectory_path = self.logs_dir / "geode-trajectory.private.json"
        if not trajectory_path.is_file():
            return
        trajectory = json.loads(trajectory_path.read_text())
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
            effort=None,  # Root, worker and wrap-up effort differ; no per-step inference.
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


async def _run_native(args: argparse.Namespace) -> int:
    # Imports follow container/env checks so native path singletons can never
    # initialize against the operator's home during an accidental host launch.
    if not Path("/.dockerenv").is_file() or os.environ.get("GEODE_HOME") != f"{_LOGS}/geode-home":
        raise RuntimeError("container-local runtime entry point only")
    started = time.monotonic()
    Path(f"{_LOGS}/runtime.pid").write_text(str(os.getpid()))
    from core.agent.loop.models import TerminationReason, is_successful_task_termination
    from core.agent.session_mode import SessionMode
    from core.config import load_model_policy, settings
    from core.memory.atomic_write import atomic_write_json
    from core.observability.event_store import HookEventStore
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions
    from core.wiring.runtime import build_runtime, build_shared_services

    if (
        settings.model != args.model
        or settings.agentic_effort != args.effort
        or settings.model_policy_path != f"{_INSTALL}/model-policy.toml"
        or load_model_policy().allowlist != [args.model]
        or settings.openai_credential_source != "openai-codex"
        or settings.anthropic_credential_source != "none"
        or any(value for key, value in os.environ.items() if key.endswith("API_KEY"))
    ):
        raise RuntimeError("runtime model/credential isolation preflight failed")
    runtime = build_runtime()
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
    executor, loop = services.create_session(SessionMode.REPL, time_budget_override=args.timeout)
    task = asyncio.current_task()
    assert task is not None
    event_loop = asyncio.get_running_loop()
    event_loop.add_signal_handler(signal.SIGTERM, task.cancel)
    outcome = "error"
    exit_code = 0
    error_type: str | None = None
    succeeded = False
    try:
        async with asyncio.timeout(max(0, args.timeout - (time.monotonic() - started))):
            result = await loop.arun(Path(args.instruction).read_text())
        outcome = str(result.termination_reason)
        if result.error:
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
    except TimeoutError:
        error_type = "TimeoutError"
        outcome = "time_budget"
        exit_code = 124
    except BaseException as exc:
        error_type = type(exc).__name__
        if isinstance(exc, asyncio.CancelledError):
            outcome = "external_cancellation"
        raise
    finally:
        try:
            manager = executor._sub_agent_manager
            if manager is not None:
                children = manager.list_collaboration_runs(loop._session_id)
                for child in children:
                    manager.interrupt_task(loop._session_id, child.task_id)
                await asyncio.gather(
                    *(
                        manager.wait_for_task(loop._session_id, child.task_id, timeout_s=10)
                        for child in children
                    )
                )
                if any(
                    child.status in {"pending", "running"}
                    for child in manager.list_collaboration_runs(loop._session_id)
                ):
                    raise RuntimeError("child shutdown incomplete; no complete usage claim")
            if succeeded:
                await loop.amark_session_completed()
            else:
                await loop.amark_session_error()
            # Stop native writers before paging the durable event source.
            services.close()
            runtime.shutdown()
            # The isolated trial database includes root/worker events. Export
            # the existing canonical sources, not a parallel raw-event store.
            events: list[Any] = []
            reader = HookEventStore(db_path=runtime.event_store.db_path)
            try:
                while batch := reader.read(limit=500, offset=len(events)):
                    events.extend(batch)
            finally:
                reader.close()
            usage = _summarize_usage(events)
            metadata = {
                "geode_session_id": loop._session_id,
                "termination_reason": outcome,
                "error_type": error_type,
                "source_revision": args.revision,
                "usage": usage,
                "score_authority": "Harbor task verifier, not this runtime receipt",
            }
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
                        for tool in loop._tools
                    ],
                },
            )
            with sqlite3.connect(runtime.event_store.db_path) as connection:
                sessions = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT DISTINCT session_id FROM session_events ORDER BY session_id"
                    )
                ]
            source = {"harness": "harbor", "session": loop._session_id}
            for policy, name in (
                ("digest", "geode-trajectory.json"),
                ("full", "geode-trajectory.private.json"),
            ):
                trajectory = trajectory_from_sessions(
                    sessions,
                    trajectory_id=f"harbor-{loop._session_id}",
                    source=source,
                    db_path=runtime.event_store.db_path,
                    outcome=metadata,
                    provenance={"adapter": "evals.platforms.harbor_runtime"},
                    privacy={"review_state": "local"},
                    content_policy=policy,
                )
                export_trajectory(Path(_LOGS) / name, trajectory)
            atomic_write_json(Path(_LOGS) / "runtime-finalized.json", {"exports_complete": True})
        finally:
            services.close()
            runtime.shutdown()
            event_loop.remove_signal_handler(signal.SIGTERM)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")
    return asyncio.run(_run_native(args))


if __name__ == "__main__":
    raise SystemExit(main())
