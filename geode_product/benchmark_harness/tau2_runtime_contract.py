"""Run-scoped GEODE runtime and evidence contract for tau2-bench.

The benchmark keeps tau2's orchestrator, environment, retry loop, evaluator,
and native ``results.json`` authoritative.  This module only supplies the
production-shaped GEODE surfaces that the adapter used to omit and preserves
the identities needed to join tau2 outcomes back to GEODE sessions.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.hooks import (
    HookDecision,
    HookDispatch,
    HookInvocation,
    HookName,
    HookRegistry,
    HookSystem,
    LlmCallRequest,
    ToolCallRequest,
)
from core.hooks.middleware import LlmNextCall, ToolNextCall
from core.llm.adapters.base import AdapterCallResult
from core.memory.atomic_write import atomic_write_json
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink

RUNTIME_PROFILE_SCHEMA = "geode.tau2-runtime-profile.v1"
ATTEMPT_MANIFEST_SCHEMA = "geode.tau2-attempt-manifest.v1"
NATIVE_VERDICT_SCHEMA = "tau2.results@native"
TAU2_NATIVE_USER_PROFILE = "tau2-native-user"
GEODE_DUAL_RUNTIME_PROFILE = "geode-dual-runtime"

_PROMPT_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9_-]{0,63})(?:\s|>)")
_REQUIRED_PUBLIC_HOOKS = frozenset(
    {
        HookName.USER_PROMPT_SUBMIT,
        HookName.SESSION_START,
        HookName.SESSION_END,
        HookName.PRE_VERIFY,
        HookName.POST_VERIFY,
        HookName.STOP,
    }
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _runtime_revision(repo_root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    result = subprocess.run(  # noqa: S603 -- executable resolved by shutil.which
        [git, "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and len(revision) == 40 else "unknown"


def _tool_name(tool: Any) -> str:
    if isinstance(tool, Mapping):
        direct = tool.get("name")
        if isinstance(direct, str):
            return direct
        function = tool.get("function")
        if isinstance(function, Mapping) and isinstance(function.get("name"), str):
            return str(function["name"])
    return str(getattr(tool, "name", "") or "")


@dataclass(slots=True)
class _Attempt:
    attempt_id: str
    task_id: str
    trial: int
    attempt: int
    seed: int
    retry_of: str | None
    status: str = "running"
    retry_reason: str | None = None
    selected_final: bool = False
    simulation_id: str | None = None
    sessions: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "trial": self.trial,
            "attempt": self.attempt,
            "seed": self.seed,
            "retry_of": self.retry_of,
            "status": self.status,
            "retry_reason": self.retry_reason,
            "selected_final": self.selected_final,
            "simulation_id": self.simulation_id,
            "sessions": list(self.sessions),
        }


_CURRENT_ATTEMPT: contextvars.ContextVar[_Attempt | None] = contextvars.ContextVar(
    "geode_tau2_attempt",
    default=None,
)


class Tau2AttemptTracker:
    """Observe tau2's existing retry loop without changing its policy."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._attempts: list[_Attempt] = []
        self._final_results: list[dict[str, Any]] = []
        self._resumed_results: list[dict[str, Any]] = []

    def register_session(self, *, participant_role: str, session_id: str) -> None:
        attempt = _CURRENT_ATTEMPT.get()
        if attempt is None:
            raise RuntimeError("tau2 participant was created outside a tracked attempt")
        with self._lock:
            attempt.sessions.append(
                {"participant_role": participant_role, "session_id": session_id}
            )

    def attempt_for_session(self, session_id: str) -> _Attempt | None:
        with self._lock:
            return next(
                (
                    attempt
                    for attempt in self._attempts
                    if any(row["session_id"] == session_id for row in attempt.sessions)
                ),
                None,
            )

    def wrap(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def tracked(
            run_fn: Callable[[], Any],
            task: Any,
            trial: int,
            seed: int,
            **kwargs: Any,
        ) -> Any:
            task_id = str(getattr(task, "id", "") or "unknown-task")
            previous: _Attempt | None = None
            attempt_number = 0

            def tracked_run() -> Any:
                nonlocal attempt_number, previous
                if (
                    previous is not None
                    and previous.status == "complete"
                    and not previous.selected_final
                ):
                    # tau2 can retry after run_fn returns when display or
                    # checkpoint persistence fails inside run_with_retry.
                    previous.status = "error"
                    previous.retry_reason = "upstream post-run failure before selection"
                attempt_number += 1
                attempt = _Attempt(
                    attempt_id=f"{self.run_id}:{task_id}:{trial}:{attempt_number}",
                    task_id=task_id,
                    trial=int(trial),
                    attempt=attempt_number,
                    seed=int(seed),
                    retry_of=previous.attempt_id if previous is not None else None,
                )
                with self._lock:
                    self._attempts.append(attempt)
                token = _CURRENT_ATTEMPT.set(attempt)
                try:
                    simulation = run_fn()
                except BaseException as exc:
                    attempt.status = "error"
                    attempt.retry_reason = f"{type(exc).__name__}: {str(exc)[:512]}"
                    previous = attempt
                    raise
                finally:
                    _CURRENT_ATTEMPT.reset(token)
                attempt.status = "complete"
                attempt.simulation_id = str(getattr(simulation, "id", "") or "") or None
                previous = attempt
                return simulation

            result = original(tracked_run, task, trial, seed, **kwargs)
            simulation_id = str(getattr(result, "id", "") or "") or None
            with self._lock:
                selected_attempt = next(
                    (
                        row
                        for row in reversed(self._attempts)
                        if row.task_id == task_id
                        and row.trial == int(trial)
                        and row.status == "complete"
                        and row.simulation_id == simulation_id
                    ),
                    None,
                )
                if (
                    selected_attempt is None
                    and previous is not None
                    and previous.status == "complete"
                ):
                    previous.status = "error"
                    previous.retry_reason = "upstream post-run failure before selection"
                if selected_attempt is not None:
                    selected_attempt.selected_final = True
                selected = selected_attempt.attempt_id if selected_attempt is not None else None
                self._final_results.append(
                    {
                        "task_id": task_id,
                        "trial": int(trial),
                        "simulation_id": simulation_id,
                        "selected_attempt_id": selected,
                        "selection_status": "selected" if selected else "no_successful_attempt",
                    }
                )
            return result

        return tracked

    def record_resumed_result(
        self,
        *,
        task_id: str,
        trial: int,
        simulation_id: str,
        session_ids: list[str],
    ) -> None:
        """Mark a native auto-resume row whose originating process is unavailable."""
        with self._lock:
            self._resumed_results.append(
                {
                    "task_id": task_id,
                    "trial": trial,
                    "simulation_id": simulation_id,
                    "session_ids": session_ids,
                    "selection_status": "resumed_native_unattested",
                }
            )

    @contextlib.contextmanager
    def patch_tau2_retry_runner(self) -> Iterator[None]:
        """Temporarily instrument the pinned runner's imported retry function."""
        from tau2.runner import batch

        original = batch.run_with_retry
        batch.run_with_retry = self.wrap(original)
        try:
            yield
        finally:
            batch.run_with_retry = original

    def manifest(self) -> dict[str, Any]:
        with self._lock:
            attempts = [attempt.as_dict() for attempt in self._attempts]
            final_results = [dict(row) for row in self._final_results]
            resumed_results = [dict(row) for row in self._resumed_results]
        return {
            "schema": ATTEMPT_MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "attempts": attempts,
            "final_results": final_results,
            "resumed_results": resumed_results,
        }


class Tau2RuntimeCapture:
    """No-op production middleware that records only bounded contract facts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._surface_counts = {
            "tool_request": 0,
            "tool_execution": 0,
            "llm_request": 0,
            "llm_execution": 0,
        }
        self._hook_counts = {hook.value: 0 for hook in HookName}
        self._event_counts: dict[str, int] = {}
        self._prompts: dict[str, dict[str, Any]] = {}

    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
        self._increment_surface("tool_request")
        return request

    async def tool_execution(
        self,
        request: ToolCallRequest,
        next_call: ToolNextCall,
    ) -> dict[str, Any]:
        self._increment_surface("tool_execution")
        return await next_call(request)

    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
        self._increment_surface("llm_request")
        system_prompt = str(request.request.system_prompt or "")
        tools = list(request.request.tools or [])
        session_id = str(request.correlation.get("session_id") or "unbound")
        prompt_sha256 = _sha256_bytes(system_prompt.encode("utf-8"))
        tool_schema_sha256 = _canonical_sha256(tools)
        tags: dict[str, int] = {}
        for match in _PROMPT_TAG.finditer(system_prompt):
            name = match.group(1)
            tags[name] = tags.get(name, 0) + 1
        record = {
            "session_id": session_id,
            "model": request.request.model,
            "assembled_prompt_sha256": prompt_sha256,
            "assembled_prompt_bytes": len(system_prompt.encode("utf-8")),
            "prompt_block_inventory": {
                "cache_boundary_present": "__GEODE_PROMPT_CACHE_BOUNDARY__" in system_prompt,
                "xml_tags": [{"name": name, "count": tags[name]} for name in sorted(tags)[:64]],
            },
            "tool_schema_sha256": tool_schema_sha256,
            "tool_allowlist": sorted(name for tool in tools if (name := _tool_name(tool))),
            "observed_count": 1,
        }
        with self._lock:
            key = f"{session_id}:{prompt_sha256}:{tool_schema_sha256}"
            existing = self._prompts.get(key)
            if existing is None:
                self._prompts[key] = record
            else:
                existing["observed_count"] = int(existing["observed_count"]) + 1
        return request

    async def llm_execution(
        self,
        request: LlmCallRequest,
        next_call: LlmNextCall,
    ) -> AdapterCallResult:
        self._increment_surface("llm_execution")
        return await next_call(request)

    def observe_hook(self, invocation: HookInvocation) -> HookDecision:
        with self._lock:
            self._hook_counts[invocation.name.value] += 1
        return HookDecision()

    def observe_event(self, dispatch: HookDispatch) -> None:
        with self._lock:
            name = dispatch.event.value
            self._event_counts[name] = self._event_counts.get(name, 0) + 1

    def _increment_surface(self, surface: str) -> None:
        with self._lock:
            self._surface_counts[surface] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "middleware": dict(self._surface_counts),
                "public_hooks": dict(self._hook_counts),
                "runtime_events": dict(sorted(self._event_counts.items())),
                "assembled_requests": [dict(self._prompts[key]) for key in sorted(self._prompts)],
            }


class Tau2RuntimeContract:
    """One process-owned runtime surface shared by every tau2 participant."""

    def __init__(
        self,
        *,
        run_id: str,
        repo_root: Path,
        agent_route: Mapping[str, Any],
        user_route: Mapping[str, Any],
        runtime_profile: str,
        event_db_path: Path | None = None,
        allow_resumed_native: bool = False,
    ) -> None:
        self.run_id = run_id
        self.repo_root = repo_root
        self.agent_route = dict(agent_route)
        self.user_route = dict(user_route)
        if runtime_profile not in {
            TAU2_NATIVE_USER_PROFILE,
            GEODE_DUAL_RUNTIME_PROFILE,
        }:
            raise ValueError(f"unsupported tau2 runtime profile: {runtime_profile!r}")
        self.runtime_profile = runtime_profile
        self.allow_resumed_native = allow_resumed_native
        self.capture = Tau2RuntimeCapture()
        self.hooks = HookSystem()
        self.event_store = HookEventStore(event_db_path)
        from core.wiring.bootstrap import (
            build_middleware_registry,
            current_product_activity_sink,
        )

        self.hooks.register_sink(
            HookPersistenceSink(
                self.event_store,
                session_key=f"tau2:{run_id}",
                run_id=run_id,
                activity_sink_provider=current_product_activity_sink,
            ),
            name="hook_persistence",
        )
        self.hooks.register_sink(self.capture.observe_event, name="tau2_runtime_capture")
        self.hook_registry = HookRegistry(events=self.hooks)
        self.middleware_registry = build_middleware_registry(events=self.hooks)
        for hook in HookName:
            self.hook_registry.register(
                hook,
                self.capture.observe_hook,
                name="tau2_runtime_capture",
            )
        self.middleware_registry.register_tool_request(self.capture, name="tau2_runtime_capture")
        self.middleware_registry.register_tool_execution(self.capture, name="tau2_runtime_capture")
        self.middleware_registry.register_llm_request(self.capture, name="tau2_runtime_capture")
        self.middleware_registry.register_llm_execution(self.capture, name="tau2_runtime_capture")
        self.attempts = Tau2AttemptTracker(run_id)
        self._loops: dict[str, Any] = {}
        self._roles: dict[str, str] = {}
        self._native_receipt: dict[str, Any] | None = None
        self._bound_sessions: set[str] = set()
        self.infrastructure_contaminated = False

    def register_loop(self, loop: Any, *, participant_role: str) -> None:
        session_id = str(getattr(loop, "_session_id", "") or f"loop-{id(loop)}")
        self._loops[session_id] = loop
        self._roles[session_id] = participant_role
        self.attempts.register_session(
            participant_role=participant_role,
            session_id=session_id,
        )

    def execute(
        self,
        run_fn: Callable[[Any], Any],
        config: Any,
        results_path: Path,
        *,
        classify_termination: Callable[[str], str],
    ) -> BaseException | None:
        """Run Tau2, bind its receipt, and close every participant in order."""
        run_error: BaseException | None = None
        try:
            with self.attempts.patch_tau2_retry_runner():
                run_fn(config)
        except BaseException as exc:
            run_error = exc
        try:
            self.bind_native_results(
                results_path,
                classify_termination=classify_termination,
            )
        except BaseException as exc:
            if run_error is None:
                run_error = exc
        try:
            from geode_product.benchmark_harness.trajectory_artifacts import (
                close_benchmark_session,
            )

            for session_id, loop in self._loops.items():
                close_benchmark_session(
                    loop,
                    success=run_error is None and self.session_completed(session_id),
                )
        finally:
            self.close()
        return run_error

    def bind_native_results(
        self,
        results_path: Path,
        *,
        classify_termination: Callable[[str], str],
    ) -> None:
        """Join the authoritative receipt to live timelines before they close."""
        raw = results_path.read_bytes()
        digest = _sha256_bytes(raw)
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping):
            raise RuntimeError("tau2 results receipt must be a JSON object")
        simulations = parsed.get("simulations")
        if not isinstance(simulations, list):
            raise RuntimeError("tau2 results receipt must contain simulations")
        bound_sessions: set[str] = set()
        for simulation in simulations:
            if not isinstance(simulation, Mapping):
                continue
            termination = str(simulation.get("termination_reason") or "")
            termination_class = classify_termination(termination)
            validity = "infrastructure" if termination_class == "infra" else "semantic"
            if validity == "infrastructure":
                self.infrastructure_contaminated = True
            reward_info = simulation.get("reward_info")
            reward_row = reward_info if isinstance(reward_info, Mapping) else {}
            reward = reward_row.get("reward")
            simulation_id = str(simulation.get("id") or "")
            task_id = str(simulation.get("task_id") or "")
            trial = int(simulation.get("trial") or 0)
            simulation_sessions = _simulation_sessions(simulation)
            unknown_sessions = [
                session_id
                for session_id, _termination in simulation_sessions
                if session_id not in self._loops
            ]
            if unknown_sessions:
                if self.allow_resumed_native and len(unknown_sessions) == len(simulation_sessions):
                    self.attempts.record_resumed_result(
                        task_id=task_id,
                        trial=trial,
                        simulation_id=simulation_id,
                        session_ids=unknown_sessions,
                    )
                    continue
                raise RuntimeError(
                    f"tau2 receipt references unknown GEODE session {unknown_sessions[0]!r}"
                )
            if validity == "semantic":
                expected_roles = (
                    {"assistant", "user_simulator"}
                    if self.runtime_profile == GEODE_DUAL_RUNTIME_PROFILE
                    else {"assistant"}
                )
                observed_roles = {
                    self._roles.get(session_id, "unknown")
                    for session_id, _runtime_termination in simulation_sessions
                }
                if observed_roles != expected_roles:
                    raise RuntimeError(
                        f"tau2 simulation {simulation_id!r} GEODE participant coverage "
                        f"{sorted(observed_roles)!r} != {sorted(expected_roles)!r}"
                    )
            for session_id, runtime_termination in simulation_sessions:
                loop = self._loops.get(session_id)
                if loop is None:  # guarded by unknown_sessions above
                    raise AssertionError("known tau2 session disappeared during native binding")
                bound_sessions.add(session_id)
                pending = getattr(loop, "_tau2_pending_tool_calls", {})
                if pending:
                    from geode_product.benchmark_harness.tau2_turn_supervisor import (
                        GeodeTau2State,
                        _reconcile_tau2_terminal_results,
                    )

                    requestor = (
                        "user" if self._roles.get(session_id) == "user_simulator" else "assistant"
                    )
                    _reconcile_tau2_terminal_results(
                        GeodeTau2State(loop=loop, pending_tool_calls=pending),
                        simulation.get("messages"),
                        requestor=requestor,
                    )
                if pending:
                    raise RuntimeError(
                        f"tau2 session {session_id!r} closed with orphan tool calls: "
                        + ", ".join(sorted(pending))
                    )
                attempt = self.attempts.attempt_for_session(session_id)
                reference = {
                    "kind": "native_receipt",
                    "schema_id": NATIVE_VERDICT_SCHEMA,
                    "authority": "tau2 native evaluator",
                    "reference": digest,
                    "raw_artifact_sha256": digest,
                    "simulation_id": simulation_id,
                    "task_id": task_id,
                    "trial": trial,
                    "participant_role": self._roles.get(session_id, "unknown"),
                    "attempt_id": attempt.attempt_id if attempt is not None else None,
                    "reward": reward,
                    "reward_components": _reward_components(reward_row),
                    "native_termination_reason": termination,
                    "runtime_termination_reason": runtime_termination,
                    "validity": validity,
                    "promotion_authority": "none",
                }
                timeline = getattr(loop, "_timeline", None)
                if timeline is None:
                    raise RuntimeError(f"GEODE session {session_id!r} has no timeline")
                timeline.record_verification_evidence(
                    [reference],
                    root_turn_id=str(getattr(loop, "_turn_id", "") or "tau2-native-verdict"),
                    verify_attempt=0,
                    policy_action="observe_native_verdict",
                )

        for session_id, loop in self._loops.items():
            if session_id in bound_sessions:
                continue
            attempt = self.attempts.attempt_for_session(session_id)
            timeline = getattr(loop, "_timeline", None)
            if timeline is None:
                continue
            timeline.record_verification_evidence(
                [
                    {
                        "kind": "native_receipt",
                        "schema_id": "tau2.retry-exclusion.v1",
                        "authority": "tau2 retry controller",
                        "reference": attempt.attempt_id if attempt is not None else session_id,
                        "raw_artifact_sha256": digest,
                        "participant_role": self._roles.get(session_id, "unknown"),
                        "attempt_id": attempt.attempt_id if attempt is not None else None,
                        "retry_reason": attempt.retry_reason if attempt is not None else None,
                        "validity": "infrastructure",
                        "promotion_authority": "none",
                    }
                ],
                root_turn_id=str(getattr(loop, "_turn_id", "") or "tau2-retry-exclusion"),
                verify_attempt=0,
                policy_action="exclude_failed_attempt",
            )
        self._native_receipt = {
            "path": results_path.name,
            "sha256": digest,
            "simulation_count": len(simulations),
        }
        self._bound_sessions = bound_sessions

    def session_completed(self, session_id: str) -> bool:
        """Return whether the native receipt selected this session's attempt."""
        attempt = self.attempts.attempt_for_session(session_id)
        return (
            session_id in self._bound_sessions
            and attempt is not None
            and attempt.status == "complete"
            and attempt.selected_final
        )

    def write_companions(self, snapshot_dir: Path) -> tuple[Path, Path]:
        if self._native_receipt is None:
            raise RuntimeError("runtime profile requires a bound tau2 native receipt")
        from core import __version__

        snapshot_dir.mkdir(parents=True, exist_ok=True)
        slug = _slug(self.run_id)
        profile_path = snapshot_dir / f"{slug}.runtime-profile.json"
        attempts_path = snapshot_dir / f"{slug}.attempt-manifest.json"
        capture = self.capture.snapshot()
        session_dbs = sorted(
            {
                str(getattr(getattr(loop, "_timeline", None), "db_path", ""))
                for loop in self._loops.values()
                if getattr(getattr(loop, "_timeline", None), "db_path", None)
            }
        )
        session_dbs = sorted({Path(path).name for path in session_dbs})
        hook_rows = []
        for hook in HookName:
            count = int(capture["public_hooks"].get(hook.value, 0))
            hook_rows.append(
                {
                    "name": hook.value,
                    "expectation": "required" if hook in _REQUIRED_PUBLIC_HOOKS else "conditional",
                    "observed_count": count,
                    "status": "exercised" if count else "not_exercised",
                }
            )
        profile = {
            "schema": RUNTIME_PROFILE_SCHEMA,
            "run_id": self.run_id,
            "runtime_revision": _runtime_revision(self.repo_root),
            "runtime_version": __version__,
            "runtime_profile": self.runtime_profile,
            "routes": {"agent": self.agent_route, "user": self.user_route},
            "assembled_requests": capture["assembled_requests"],
            "surfaces": {
                "public_hooks": hook_rows,
                "middleware": [
                    {
                        "name": name,
                        "status": "exercised" if count else "not_exercised",
                        "observed_count": count,
                    }
                    for name, count in sorted(capture["middleware"].items())
                ],
                "runtime_events": capture["runtime_events"],
                "disabled": [
                    {
                        "name": name,
                        "status": "disabled",
                        "reason": "outside benchmark-safe runtime profile",
                    }
                    for name in (
                        "auto_learning",
                        "gateway",
                        "mcp_discovery",
                        "plugin_discovery",
                        "scheduler",
                    )
                ],
            },
            "persistence": {
                "session_event_dbs": session_dbs,
                "hook_event_db": Path(self.event_store.db_path).name,
                "native_receipt": dict(self._native_receipt),
            },
        }
        atomic_write_json(profile_path, profile, indent=2)
        atomic_write_json(attempts_path, self.attempts.manifest(), indent=2)
        return profile_path, attempts_path

    def companion_artifacts(self, snapshot_dir: Path) -> dict[str, dict[str, str]]:
        profile_path, attempts_path = self.write_companions(snapshot_dir)
        return {
            "runtime_profile": artifact_reference(profile_path),
            "attempt_manifest": artifact_reference(attempts_path),
        }

    def close(self) -> None:
        self.hooks.close()
        self.event_store.close()


def _simulation_sessions(simulation: Mapping[str, Any]) -> list[tuple[str, str]]:
    sessions: dict[str, str] = {}
    messages = simulation.get("messages")
    if not isinstance(messages, list):
        return []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        raw_data = message.get("raw_data")
        if not isinstance(raw_data, Mapping):
            continue
        session_id = str(raw_data.get("geode_session_id") or "")
        if not session_id:
            continue
        termination = str(raw_data.get("geode_termination_reason") or "")
        if termination or session_id not in sessions:
            sessions[session_id] = termination
    return list(sessions.items())


def _reward_components(reward_info: Mapping[str, Any]) -> dict[str, Any]:
    breakdown = reward_info.get("reward_breakdown")
    return {
        "reward_breakdown": dict(breakdown) if isinstance(breakdown, Mapping) else {},
        "db_check_present": reward_info.get("db_check") is not None,
        "env_assertion_count": len(reward_info.get("env_assertions") or []),
        "action_check_count": len(reward_info.get("action_checks") or []),
        "nl_assertion_count": len(reward_info.get("nl_assertions") or []),
        "communicate_check_count": len(reward_info.get("communicate_checks") or []),
    }


def artifact_reference(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": _sha256_bytes(path.read_bytes())}


def runtime_contract_from_args(
    args: Any,
    run_id: str,
    repo_root: Path,
) -> Tau2RuntimeContract:
    profile = (
        GEODE_DUAL_RUNTIME_PROFILE
        if args.user in {"geode_user", "crucible_user"}
        else TAU2_NATIVE_USER_PROFILE
    )
    return Tau2RuntimeContract(
        run_id=run_id,
        repo_root=repo_root,
        agent_route={
            "model": args.model,
            "provider": args.provider,
            "source": args.source,
            "effort": args.effort,
        },
        user_route={
            "implementation": args.user,
            "model": args.user_llm,
            "provider": args.user_provider,
            "source": args.user_source,
            "effort": args.user_effort,
        },
        runtime_profile=profile,
        allow_resumed_native=bool(args.auto_resume),
    )


def runtime_companion_paths(snapshot_dir: Path, run_id: str) -> tuple[Path, Path]:
    slug = _slug(run_id)
    return (
        snapshot_dir / f"{slug}.runtime-profile.json",
        snapshot_dir / f"{slug}.attempt-manifest.json",
    )


def native_results_path(data_root: Path, run_id: str) -> Path:
    return data_root / "simulations" / run_id / "results.json"


def snapshot_contract_metadata(contract: Any | None) -> dict[str, Any]:
    if contract is None:
        return {"promotion_authority": "none"}
    return {
        "experiment_contract_id": contract.contract_id,
        "baseline_sha": contract.baseline_sha,
        "candidate_sha": contract.candidate_sha,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "contract_validation": "identity_preflight",
        "promotion_authority": "none",
    }


def _slug(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "-" for character in value
    )


__all__ = [
    "ATTEMPT_MANIFEST_SCHEMA",
    "GEODE_DUAL_RUNTIME_PROFILE",
    "RUNTIME_PROFILE_SCHEMA",
    "TAU2_NATIVE_USER_PROFILE",
    "Tau2RuntimeContract",
    "artifact_reference",
    "native_results_path",
    "runtime_companion_paths",
    "runtime_contract_from_args",
    "snapshot_contract_metadata",
]
