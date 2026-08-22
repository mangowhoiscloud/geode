"""Depth-one foreground delegation and durable child collaboration."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.agent.safety import (
    SUBAGENT_CONTROL_TOOLS,
    residual_denied_tools,
    subagent_denied_tools,
)
from core.agent.subagent_announcements import SubagentAnnouncements
from core.agent.subagent_protocol import (
    SubagentProtocol,
)
from core.agent.subagent_protocol import (
    SubagentRunRecord as SubagentRunRecord,
)
from core.agent.subagent_protocol import (
    SubResult as SubResult,
)
from core.agent.subagent_protocol import (
    SubTask as SubTask,
)
from core.config.policy_source import EMPTY_POLICY_SOURCES, PolicySourceBundle
from core.hooks import HookRegistry, RuntimeEvent, RuntimeEventBus
from core.memory.collaboration import CollaborationRun, CollaborationStore
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
    IsolationResult,
)
from core.tools.base import load_tool_definition
from core.tools.personal_data import PERSONAL_DATA_TOOLS

if TYPE_CHECKING:
    from core.observability.run_event import RunEventSinkProvider
    from core.skills.agents import AgentRegistry
    from core.tools.plan import BoundToolPlan

log = logging.getLogger(__name__)


def _resolve_timeout_s(default: float) -> float:
    """Apply ``GEODE_SUBAGENT_TIMEOUT_S`` env override with clamp.

    PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — env knob for
    the SubAgentManager wall-clock cap so deployments can tune
    without code change. Clamp to ``[10, 3600]``:

    - Lower bound 10s — below this the orchestrator's per-phase
      framing overhead alone dominates; a sub-agent can't complete
      meaningful work.
    - Upper bound 3600s (1h) — matches openclaw's per-agent
      ``agents.defaults.timeoutSeconds`` documented range; longer
      runs should checkpoint + resume rather than hold a single
      subprocess open.

    Non-numeric or empty env values fall through to ``default``.
    """
    import os

    raw = os.environ.get("GEODE_SUBAGENT_TIMEOUT_S", "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        return float(default)
    return max(10.0, min(3600.0, value))


# Thread-local storage for subagent context (OpenClaw Spawn pattern)
_subagent_context = threading.local()

# Process-local execution controls. Durable truth remains in sessions.db; this
# registry only lets a later turn in the same runtime wait for or interrupt the
# live asyncio task without inventing a thread manager.
_background_controls: dict[str, tuple[asyncio.Task[None], IsolatedRunner, threading.Event]] = {}
_background_interrupting: set[str] = set()
_background_controls_lock = threading.Lock()


def get_subagent_context() -> tuple[bool, str]:
    """Return (is_subagent, child_session_key) from thread-local."""
    is_sub = getattr(_subagent_context, "is_subagent", False)
    key = getattr(_subagent_context, "child_session_key", "")
    return is_sub, key


# Compatibility denials for unbound and plan-external sub-agent tools. Native
# plan-owned tools derive the same boundary from ``SafetyPolicy.allow_subagents``.
SUBAGENT_DENIED_TOOLS: set[str] = {
    "set_api_key",  # credential changes — parent only
    "manage_auth",  # auth profile management — parent only
    "manage_login",  # plans + credentials + routing — parent only
    "profile_update",  # user profile changes — parent only
    *PERSONAL_DATA_TOOLS,  # personal Workspace data — parent approval only
    *SUBAGENT_CONTROL_TOOLS,
}


class SubAgentManager:
    """Delegate tasks to parallel sub-agents using IsolatedRunner.

    Subprocess workers receive native tool handlers resolved from their
    declared toolkit. Depth is capped independently by ``max_depth``.
    """

    def __init__(
        self,
        runner: IsolatedRunner,
        task_handler: Any | None = None,
        *,
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — raised
        # 120 → 600 (10 min) on operator directive ("야심차게 잡아도 돼.
        # 300초 그이상으로 잡아"). Matches the per-agent-run wall-clock
        # convergence from openclaw (`agents/timeout.ts:3` 48h default)
        # while still leaving room for the IsolationConfig outer cap.
        # 120s was too tight for tool-using sub-agents — smoke 16
        # evolver TimeoutError surfaced at 122s. Pilot's 90s Petri audit
        # alone leaves <30s for tool overhead at 120s; 600s gives
        # multi-round tool reasoning the headroom it needs. Override
        # via ``GEODE_SUBAGENT_TIMEOUT_S`` env (clamped [10, 3600]).
        timeout_s: float = 600.0,
        hooks: RuntimeEventBus | None = None,
        hook_registry: HookRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
        parent_session_key: str = "",
        # P2-B: Full AgenticLoop inheritance
        action_handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        depth: int = 0,
        max_depth: int = 1,  # Depth=1 enforced (Claude Code pattern: sub-agents cannot recurse)
        max_total_subagents: int = 15,  # session-wide cap on total sub-agents spawned
        # Sandbox hardening: tool scope restriction
        denied_tools: set[str] | None = None,
        time_budget_s: float = 0.0,
        # Sandbox: additional working directories for sub-agent scope
        working_dirs: list[str] | None = None,
        collaboration_store: CollaborationStore | None = None,
        activity_sink_provider: RunEventSinkProvider | None = None,
        policy_sources: PolicySourceBundle | None = None,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> None:
        self._runner = runner
        self._task_handler = task_handler
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — env override
        # for the wall-clock cap, clamped to a sane range so a bad
        # `GEODE_SUBAGENT_TIMEOUT_S=abc` or `=99999999` doesn't break
        # subprocess accounting. 10s lower bound matches the smoke
        # smallest phase (proximity ~0.2ms is fine; literature_review
        # ~30s on cache hit needs > 10s headroom).
        self._timeout_s = _resolve_timeout_s(timeout_s)
        self._records_lock = threading.Lock()
        # P2-B fields
        self._action_handlers = action_handlers
        self._depth = depth
        self._max_depth = max_depth
        self._max_total_subagents = max_total_subagents
        # Monotonic per-session spawn counter, guarded by ``_records_lock``.
        # SubAgentManager is built once per session (services.py
        # ``_build_sub_agent_manager``), so this counts the session total.
        self._spawned_total = 0
        # Sandbox hardening is additive and cannot be disabled by omitting or
        # passing an empty custom set. Production constructors historically
        # omitted ``denied_tools`` entirely, so a constant that was not folded
        # in here provided no protection to the worker request.
        self._custom_denied_tools: set[str] = set(denied_tools or ())
        denied = (
            set(SUBAGENT_DENIED_TOOLS)
            if bound_tool_plan is None
            else set(subagent_denied_tools(bound_tool_plan))
            | set(residual_denied_tools(SUBAGENT_DENIED_TOOLS, bound_tool_plan))
        )
        denied.update(self._custom_denied_tools)
        resolved_sources = policy_sources or EMPTY_POLICY_SOURCES
        self._protocol = SubagentProtocol(
            denied_tools=denied,
            timeout_s=self._timeout_s,
            time_budget_s=time_budget_s,
            agent_registry=agent_registry,
            parent_session_key=parent_session_key,
            policy_sources=resolved_sources,
        )
        self._announcements = SubagentAnnouncements(
            runtime_events=hooks,
            public_hooks=hook_registry,
            activity_sink_provider=activity_sink_provider,
            parent_session_key=parent_session_key,
        )
        # Sandbox: additional working directories for sub-agent
        self._working_dirs = working_dirs or []
        self._collaboration = collaboration_store or CollaborationStore()

    async def adelegate(
        self,
        tasks: list[SubTask],
        *,
        on_progress: Callable[[SubResult], None] | None = None,
        on_activity: Callable[[dict[str, Any]], None] | None = None,
        default_model: str = "",
        resume: bool = False,
        count_toward_cap: bool = True,
        durable_run: CollaborationRun | None = None,
        run_record: SubagentRunRecord | None = None,
    ) -> list[SubResult]:
        """Async sibling of :meth:`delegate` — ``asyncio.gather`` based fan-out.

        PR-Async-Phase-C (2026-05-22) — replaces the polling collection loop
        with native async. Each task runs in its own
        :class:`IsolatedRunner.arun` coroutine (which uses ``asyncio.to_thread``
        to off-load the blocking subprocess/thread wait); ``asyncio.gather``
        completes when all tasks finish. Backpressure is suspended-coroutine
        cost (~1 KB) instead of thread/subprocess RSS — fits cleanly with
        async caller paths (Pipeline.arun, async tool handlers).

        Contract parity with sync :meth:`delegate`: same depth guard, dedup,
        sandbox directory expansion, hooks and completion envelope.

        Fleet view Stage 1.5 — when ``on_activity`` is provided (only the
        interactive ``delegate_task`` turn path passes it), each spawned worker
        is asked to emit live per-tool activity (``WorkerRequest.emit_activity``)
        and every ``{"type":"activity", ...}`` line the worker streams before its
        result is forwarded to ``on_activity`` as it arrives. ``None`` (seed-gen /
        headless / tests) keeps the pure single-result-line worker contract.
        """
        import asyncio

        if not tasks:
            return []

        # Explicit depth guard (defense-in-depth alongside denied_tools)
        if self._depth >= self._max_depth:
            log.warning(
                "Sub-agent depth limit reached (%d/%d), rejecting %d tasks",
                self._depth,
                self._max_depth,
                len(tasks),
            )
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error=f"Depth limit exceeded ({self._depth}/{self._max_depth})",
                )
                for t in tasks
            ]

        tasks = self._deduplicate(tasks)
        if not tasks:
            log.info("All tasks coalesced — nothing to execute")
            return []

        # Session-wide total sub-agent cap (settings.max_total_subagents).
        # Reserve under the records lock so concurrent adelegate calls in the
        # same session cannot jointly overshoot the budget. Overflow tasks get
        # an explicit failed SubResult rather than silently spawning.
        cap_overflow: list[SubResult] = []
        with self._records_lock:
            remaining = self._max_total_subagents - self._spawned_total
            accepted = (
                tasks
                if not count_toward_cap or remaining >= len(tasks)
                else tasks[: max(remaining, 0)]
            )
            if count_toward_cap:
                self._spawned_total += len(accepted)
        if len(accepted) < len(tasks):
            rejected = tasks[len(accepted) :]
            log.warning(
                "Session sub-agent cap reached (%d/%d) — rejecting %d task(s)",
                self._spawned_total,
                self._max_total_subagents,
                len(rejected),
            )
            cap_overflow = [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error=f"Session sub-agent limit reached ({self._max_total_subagents})",
                )
                for t in rejected
            ]
        if not accepted:
            return cap_overflow
        tasks = accepted

        # Expand sandbox for sub-agent working directories
        added_dirs: list[Path] = []
        if self._working_dirs:
            from core.tools.sandbox import add_working_directory

            for dir_str in self._working_dirs:
                dir_path = Path(dir_str)
                if dir_path.is_dir():
                    add_working_directory(dir_path)
                    added_dirs.append(dir_path)

        # Build per-task IsolationConfig + run-record + hook STARTED in
        # the same shape sync delegate uses.
        per_task_setup: list[tuple[SubTask, Any, IsolationConfig, SubagentRunRecord]] = []
        for task in tasks:
            await self._announcements.emit_runtime(RuntimeEvent.SUBAGENT_STARTED, task)
            record = (
                run_record
                if run_record is not None and run_record.task_id == task.task_id
                else self._announcements.new_run_record(task)
            )
            child_key = record.child_session_key
            config = IsolationConfig(
                session_id=task.task_id,
                timeout_s=self._timeout_s,
                post_to_main=False,
                prefix=f"SubAgent:{task.task_type}",
                metadata={
                    "description": task.description,
                    "task_type": task.task_type,
                    "child_session_key": child_key,
                },
            )
            generation = durable_run.generation if durable_run is not None else 1
            await self._announcements.emit_start(task, record, generation=generation)
            fn_or_request: Any
            if self._action_handlers is not None:
                fn_or_request = self._protocol.build_worker_request(
                    task,
                    default_model=default_model,
                    emit_activity=on_activity is not None,
                    resume=resume,
                )
            else:
                # _execute_subtask is bound method; arun expects callable
                # passed via args/kwargs. The thread-mode path is sync.
                fn_or_request = self._execute_subtask
            per_task_setup.append((task, fn_or_request, config, record))

        # Launch ALL tasks concurrently via asyncio.gather over IsolatedRunner.arun.
        # arun's signature: arun(fn_or_request, *, args=(), kwargs=None, config=None)
        # For the legacy thread mode, args=(task,) carries the SubTask payload.
        async def _run_one(
            task: SubTask,
            fn_or_request: Any,
            config: IsolationConfig,
            record: SubagentRunRecord,
        ) -> SubResult:
            try:
                if self._action_handlers is not None:
                    # Subprocess mode — WorkerRequest carries the payload.
                    # Stage 1.5 — forward live activity lines (no-op when the
                    # caller didn't request activity: emit_activity stays False).
                    isolation = await self._runner.arun(
                        fn_or_request, config=config, on_activity=on_activity
                    )
                else:
                    # Thread mode — legacy callable + SubTask arg.
                    isolation = await self._runner.arun(fn_or_request, args=(task,), config=config)
            except Exception as exc:
                log.warning("adelegate: arun raised for %s — %s", task.task_id, exc)
                isolation = IsolationResult(
                    session_id=task.task_id,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            sub_result = self._protocol.to_sub_result(task, isolation)
            if sub_result.success:
                await self._announcements.emit_runtime(
                    RuntimeEvent.SUBAGENT_COMPLETED,
                    task,
                    result=sub_result,
                )
            else:
                # PR-COMM-3b — pass ``sub_result`` so the agent_runtime_state
                # writer receives ``status="failed"``. Pre-fix only ``error``
                # was passed and the status field was silently missing on
                # production failures (Codex MCP review catch).
                await self._announcements.emit_runtime(
                    RuntimeEvent.SUBAGENT_FAILED,
                    task,
                    result=sub_result,
                    error=sub_result.error,
                )
            if durable_run is not None:
                self._finish_durable_result(durable_run, task, sub_result)
            with _background_controls_lock:
                interrupted = task.task_id in _background_interrupting
            await self._announcements.emit_stop(
                task,
                sub_result,
                record,
                generation=durable_run.generation if durable_run is not None else 1,
                interrupted=interrupted,
            )
            if on_progress is not None:
                try:
                    on_progress(sub_result)
                except Exception:
                    log.warning(
                        "on_progress callback failed for %s",
                        task.task_id,
                        exc_info=True,
                    )
            return sub_result

        try:
            results: list[SubResult] = await asyncio.gather(
                *[
                    _run_one(task, fn_or_request, config, record)
                    for task, fn_or_request, config, record in per_task_setup
                ]
            )
        finally:
            # PR-Async-Phase-C step 4b fix-up — sandbox cleanup must run
            # even when the caller cancels ``adelegate`` mid-gather; a
            # missed ``remove_working_directory`` would leak the
            # sub-agent's writable paths into the parent's sandbox.
            if added_dirs:
                from core.tools.sandbox import remove_working_directory

                for dir_path in added_dirs:
                    remove_working_directory(dir_path)

        succeeded = sum(1 for r in results if r.success)
        log.info(
            "SubAgent async batch complete: %d/%d succeeded",
            succeeded,
            len(results),
        )
        # Append any tasks rejected by the session cap so the caller sees one
        # SubResult per submitted task (spawned outcomes + cap rejections).
        return list(results) + cap_overflow

    @property
    def hooks(self) -> RuntimeEventBus | None:
        return self._announcements.runtime_events

    async def aspawn(
        self,
        tasks: list[SubTask],
        *,
        parent_session_id: str,
        on_progress: Callable[[SubResult], None] | None = None,
        on_activity: Callable[[dict[str, Any]], None] | None = None,
        default_model: str = "",
        resume: bool = False,
    ) -> list[CollaborationRun]:
        """Schedule depth-one tasks and return their durable handles immediately."""
        if not parent_session_id:
            raise ValueError("Background delegation requires a parent session id")
        if self._action_handlers is None:
            raise ValueError("Background collaboration requires agentic subprocess workers")
        runs: list[CollaborationRun] = []
        for task in tasks:
            run = self._collaboration.begin_run(
                task_id=task.task_id,
                parent_session_id=parent_session_id,
                task_type=task.task_type,
                role=task.role,
                model=task.model or default_model,
                source=task.source,
                resume=resume,
                max_total_subagents=None if resume else self._max_total_subagents,
            )
            done = threading.Event()
            background = asyncio.create_task(
                self._run_background(
                    task,
                    run,
                    on_progress=on_progress,
                    on_activity=on_activity,
                    default_model=default_model,
                    resume=resume,
                ),
                name=f"subagent:{task.task_id}:g{run.generation}",
            )
            with _background_controls_lock:
                _background_interrupting.discard(task.task_id)
                _background_controls[task.task_id] = (background, self._runner, done)
            background.add_done_callback(partial(self._background_done, run=run, done=done))
            runs.append(run)
        return runs

    async def _run_background(
        self,
        task: SubTask,
        run: CollaborationRun,
        *,
        on_progress: Callable[[SubResult], None] | None,
        on_activity: Callable[[dict[str, Any]], None] | None,
        default_model: str,
        resume: bool,
    ) -> None:
        if not self._collaboration.mark_running(run.parent_session_id, run.task_id, run.generation):
            return
        status = "failed"
        summary = ""
        error = ""
        stopped = False
        record = self._announcements.new_run_record(task)
        try:
            results = await self.adelegate(
                [task],
                on_progress=on_progress,
                on_activity=on_activity,
                default_model=default_model,
                resume=resume,
                count_toward_cap=False,
                durable_run=run,
                run_record=record,
            )
            result = results[0] if results else None
            if result is None:
                error = "Sub-agent produced no result"
            else:
                stopped = True
        except asyncio.CancelledError:
            status = "interrupted"
            error = "Interrupted by parent"
        except Exception as exc:
            log.exception("Background sub-agent %s failed", task.task_id)
            error = f"{type(exc).__name__}: {exc}"
        finally:
            current = self._collaboration.get_run(run.parent_session_id, run.task_id)
            if current is not None and current.status in {"pending", "running"}:
                self._collaboration.finish_run(
                    parent_session_id=run.parent_session_id,
                    task_id=run.task_id,
                    generation=run.generation,
                    status=status,
                    summary=summary,
                    error=error,
                )
            if not stopped:
                with _background_controls_lock:
                    interrupted = task.task_id in _background_interrupting
                await self._announcements.emit_stop(
                    task,
                    SubResult(
                        task_id=task.task_id,
                        description=task.description,
                        success=False,
                        error=error,
                    ),
                    record,
                    generation=run.generation,
                    interrupted=interrupted,
                )
            if self._collaboration.has_pending_trigger(task.task_id):
                await self.aresume(
                    run.parent_session_id,
                    task.task_id,
                    prompt="Handle the pending parent follow-up.",
                    default_model=default_model,
                )

    def _background_done(
        self,
        completed: asyncio.Task[None],
        run: CollaborationRun,
        done: threading.Event,
    ) -> None:
        """Close the rare cancel-before-coroutine-start edge and wake waiters."""
        if completed.cancelled():
            self._collaboration.finish_run(
                parent_session_id=run.parent_session_id,
                task_id=run.task_id,
                generation=run.generation,
                status="interrupted",
                error="Interrupted by parent",
            )
        else:
            error = completed.exception()
            if error is not None:
                log.error("Background sub-agent %s crashed: %s", run.task_id, error)
                self._collaboration.finish_run(
                    parent_session_id=run.parent_session_id,
                    task_id=run.task_id,
                    generation=run.generation,
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                )
        done.set()
        with _background_controls_lock:
            current = _background_controls.get(run.task_id)
            if current is not None and current[0] is completed:
                _background_controls.pop(run.task_id, None)
                _background_interrupting.discard(run.task_id)

    def list_collaboration_runs(self, parent_session_id: str) -> list[CollaborationRun]:
        return self._collaboration.list_runs(parent_session_id)

    async def wait_for_task(
        self,
        parent_session_id: str,
        task_id: str,
        *,
        timeout_s: float,
    ) -> CollaborationRun | None:
        run = self._collaboration.get_run(parent_session_id, task_id)
        if run is None or run.status not in {"pending", "running"}:
            return run
        with _background_controls_lock:
            control = _background_controls.get(task_id)
        if control is not None:
            await asyncio.to_thread(control[2].wait, max(0.0, min(timeout_s, 3600.0)))
            return self._collaboration.get_run(parent_session_id, task_id)
        deadline = time.monotonic() + max(0.0, min(timeout_s, 3600.0))
        while run.status in {"pending", "running"} and time.monotonic() < deadline:
            await asyncio.sleep(max(0.0, min(0.1, deadline - time.monotonic())))
            refreshed = self._collaboration.get_run(parent_session_id, task_id)
            if refreshed is None:
                return None
            run = refreshed
        return run

    def interrupt_task(self, parent_session_id: str, task_id: str) -> bool:
        run = self._collaboration.get_run(parent_session_id, task_id)
        if run is None or run.status not in {"pending", "running"}:
            return False
        with _background_controls_lock:
            control = _background_controls.get(task_id)
            if control is None:
                return False
            _background_interrupting.add(task_id)
        task, runner, _done = control
        if not runner.cancel(task_id) and not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)
        return True

    def send_task_message(
        self,
        parent_session_id: str,
        task_id: str,
        message: str,
    ) -> CollaborationRun:
        run = self._collaboration.get_run(parent_session_id, task_id)
        if run is None:
            raise ValueError("Unknown child task for this parent session")
        if (
            self._collaboration.append_message_if_active(
                parent_session_id=parent_session_id,
                task_id=task_id,
                message=message,
            )
            is None
        ):
            raise ValueError("Child task is not running; use follow_up")
        return run

    async def afollow_up(
        self,
        parent_session_id: str,
        task_id: str,
        message: str,
        *,
        default_model: str = "",
    ) -> tuple[CollaborationRun, bool]:
        run = self._collaboration.get_run(parent_session_id, task_id)
        if run is None:
            raise ValueError("Unknown child task for this parent session")
        message_id = self._collaboration.append_message_if_active(
            parent_session_id=parent_session_id,
            task_id=task_id,
            message=message,
            trigger_turn=True,
        )
        if message_id is not None:
            return run, False
        resumed = await self.aresume(
            parent_session_id,
            task_id,
            prompt=message,
            default_model=default_model,
        )
        return resumed, True

    async def aresume(
        self,
        parent_session_id: str,
        task_id: str,
        *,
        prompt: str = "Continue from the saved checkpoint.",
        default_model: str = "",
    ) -> CollaborationRun:
        run = self._collaboration.get_run(parent_session_id, task_id)
        if run is None:
            raise ValueError("Unknown child task for this parent session")
        if run.status in {"pending", "running"}:
            raise ValueError("Child task is already running")
        resumed = await self.aspawn(
            [
                SubTask(
                    task_id=run.task_id,
                    description=prompt,
                    task_type=run.task_type,
                    role=run.role,
                    model=run.model,
                    source=run.source,
                )
            ],
            parent_session_id=parent_session_id,
            default_model=default_model or run.model,
            resume=True,
        )
        return resumed[0]

    @staticmethod
    def _result_summary(result: SubResult) -> str:
        summary = result.output.get("summary", "") if result.output else ""
        return str(summary or result.output or "completed")

    def _finish_durable_result(
        self,
        run: CollaborationRun,
        task: SubTask,
        result: SubResult,
    ) -> None:
        """Persist the terminal child state before publishing SubagentStop."""
        with _background_controls_lock:
            interrupted = task.task_id in _background_interrupting
        if interrupted:
            status, summary, error = "interrupted", "", "Interrupted by parent"
        elif result.success:
            status, summary, error = "completed", self._result_summary(result), ""
        else:
            error = result.error or "Sub-agent failed"
            status = "timeout" if "timeout" in error.lower() else "failed"
            summary = ""
        self._collaboration.finish_run(
            parent_session_id=run.parent_session_id,
            task_id=run.task_id,
            generation=run.generation,
            status=status,
            summary=summary,
            error=error,
        )

    def _deduplicate(self, tasks: list[SubTask]) -> list[SubTask]:
        """Filter duplicate task_id submissions via seen-set."""
        seen: set[str] = set()
        unique: list[SubTask] = []
        for task in tasks:
            if task.task_id not in seen:
                seen.add(task.task_id)
                unique.append(task)
            else:
                log.debug("Dedup: skipping duplicate task_id=%s", task.task_id)
        return unique

    def _execute_subtask(self, task: SubTask) -> str:
        """Execute a single sub-task in thread mode (legacy handler path only).

        Production sub-agents (P2-B with action_handlers) use subprocess via
        WorkerRequest instead. This method is kept for backward compatibility
        with tests and legacy task_handler consumers.

        NOTE: Thread mode cannot enforce denied_tools because the task_handler
        callback is opaque. Use subprocess mode (action_handlers) for security.
        """
        # The legacy callback receives no GEODE action-tool registry, so the
        # built-in worker baseline has nothing to filter here. A caller-supplied
        # restriction still implies a capability contract the opaque callback
        # cannot enforce, and therefore fails closed.
        if self._custom_denied_tools:
            raise RuntimeError(
                f"Thread mode cannot enforce denied_tools for task {task.task_id}. "
                "Use subprocess mode (action_handlers) for security."
            )

        from core.memory.session_key import build_subagent_session_key

        child_key = build_subagent_session_key(
            task.args.get("subject_id", task.args.get("subject", "unknown")), task.task_id
        )
        _subagent_context.is_subagent = True
        _subagent_context.child_session_key = child_key
        try:
            return self._execute_with_handler(task)
        except Exception as exc:
            log.error("SubTask %s failed: %s", task.task_id, exc, exc_info=True)
            return json.dumps({"error": str(exc)})
        finally:
            _subagent_context.is_subagent = False
            _subagent_context.child_session_key = ""

    def _execute_with_handler(self, task: SubTask) -> str:
        """Legacy path: simple task_handler function call."""
        if self._task_handler is None:
            return json.dumps({"error": "No task handler configured"})
        agent_context = self._protocol.resolve_agent(task)
        try:
            result: dict[str, Any] = self._task_handler(
                task.task_type,
                task.args,
                agent_context=agent_context,
            )
        except TypeError:
            result = self._task_handler(task.task_type, task.args)
        return json.dumps(result, default=str)


DELEGATE_TOOL_DEFINITION: dict[str, Any] = load_tool_definition("delegate_task")
