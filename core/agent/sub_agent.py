"""SubAgentManager — delegate tasks to parallel sub-agents.

Leverages the existing IsolatedRunner infrastructure for concurrent
task execution, following the Claude Code pattern of parallel
sub-agent delegation.

Orchestration integration:
- TaskGraph: DAG-based dependency tracking per sub-task
- HookSystem: Event emission on task lifecycle (start/complete/fail)
- CoalescingQueue: Deduplication of repeated requests within a time window
- AgentRegistry: Agent-aware execution with context injection
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from core.agent.worker import WorkerRequest
from core.hooks import HookEvent, HookSystem
from core.orchestration.coalescing import CoalescingQueue
from core.orchestration.isolated_execution import (
    IsolatedRunner,
    IsolationConfig,
    IsolationResult,
)
from core.orchestration.task_system import Task, TaskGraph

if TYPE_CHECKING:
    from core.skills.agents import AgentRegistry

log = logging.getLogger(__name__)

# Thread-local storage for subagent context (OpenClaw Spawn pattern)
_subagent_context = threading.local()

# Module-level announce queue: parent_session_key → list[SubAgentResult]
# Thread-safe via _announce_lock. Parent AgenticLoop polls this queue
# to inject completion notifications into its conversation context.
_announce_queue: dict[str, list[SubAgentResult]] = {}
_announce_lock = threading.Lock()

# TTL-based orphan cleanup for announce queue entries that are never drained
# (e.g. parent session crashed or was abandoned).
_announce_timestamps: dict[str, float] = {}
_ANNOUNCE_TTL_S = 300.0  # 5 min TTL for orphan results


def _cleanup_stale_announces() -> None:
    """Remove announce queue entries older than TTL."""
    now = time.time()
    with _announce_lock:
        stale_keys = [
            k for k, ts in _announce_timestamps.items()
            if now - ts > _ANNOUNCE_TTL_S
        ]
        for k in stale_keys:
            _announce_queue.pop(k, None)
            _announce_timestamps.pop(k, None)


def drain_announced_results(parent_session_key: str) -> list[SubAgentResult]:
    """Drain all announced results for a parent session (thread-safe).

    Returns the list of completed SubAgentResults and clears the queue.
    Called by AgenticLoop._check_announced_results() each round.
    """
    _cleanup_stale_announces()
    with _announce_lock:
        results = _announce_queue.pop(parent_session_key, [])
        _announce_timestamps.pop(parent_session_key, None)
    return results


def cleanup_announce_queue(parent_session_key: str) -> None:
    """Remove orphan announce queue entry for a terminated session.

    Called on session end to prevent unbounded accumulation when parent
    sessions crash or are abandoned without draining.
    """
    with _announce_lock:
        _announce_queue.pop(parent_session_key, None)
        _announce_timestamps.pop(parent_session_key, None)


def get_subagent_context() -> tuple[bool, str]:
    """Return (is_subagent, child_session_key) from thread-local."""
    is_sub = getattr(_subagent_context, "is_subagent", False)
    key = getattr(_subagent_context, "child_session_key", "")
    return is_sub, key


# Task-type → default agent mapping
_TYPE_AGENT_MAP: dict[str, str] = {
    "analyze": "data_analyst",
    "search": "web_researcher",
    "compare": "data_analyst",
}

# Default denied tools for sub-agents (sandbox hardening).
# These tools should only be invoked by the parent agent.
SUBAGENT_DENIED_TOOLS: set[str] = {
    "set_api_key",  # credential changes — parent only
    "manage_auth",  # auth profile management — parent only
    "profile_update",  # user profile changes — parent only
    "calendar_create_event",  # external system mutation — parent only
    "calendar_sync_scheduler",  # external system mutation — parent only
    "delegate_task",  # recursive delegation — explicit depth control preferred
}


@dataclass
class SubTask:
    """A task to delegate to a sub-agent."""

    task_id: str
    description: str
    task_type: str  # "analyze", "search", "compare"
    args: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None  # Explicit agent override


@dataclass
class SubResult:
    """Result from a sub-agent execution."""

    task_id: str
    description: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


class ErrorCategory(StrEnum):
    """Sub-agent error classification for retry policy."""

    TIMEOUT = "timeout"
    API_ERROR = "api_error"
    VALIDATION = "validation"
    RESOURCE = "resource"
    DEPTH_EXCEEDED = "depth_exceeded"
    UNKNOWN = "unknown"


@dataclass
class SubAgentResult:
    """Standardized result from sub-agent execution (P2-A).

    Every sub-agent returns this format, enabling:
    - Consistent LLM parsing (``summary`` always present)
    - Token guard (``summary`` preserved on truncation)
    - Error classification + retry decisions
    - Depth tracking for recursive orchestration
    """

    task_id: str
    task_type: str
    status: Literal["ok", "error", "timeout", "partial"] = "ok"
    depth: int = 0
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    token_usage: dict[str, int] | None = None
    children_count: int = 0
    error_category: str | None = None
    error_message: str | None = None
    retryable: bool = False
    announced: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @property
    def success(self) -> bool:
        return self.status == "ok"


@dataclass
class SubagentRunRecord:
    """Track parent-child relationship (OpenClaw Spawn pattern)."""

    run_id: str
    task_id: str
    child_session_key: str
    parent_session_key: str
    task_type: str
    started_at: float = 0.0
    completed_at: float = 0.0
    outcome: str = "pending"  # pending | ok | error


class SubAgentManager:
    """Delegate tasks to parallel sub-agents using IsolatedRunner.

    Orchestration features:
    - **TaskGraph**: DAG-based dependency tracking per sub-task.
    - **HookSystem**: Emits SUBAGENT_STARTED/COMPLETED/FAILED events.
    - **CoalescingQueue**: Deduplicates identical task_id submissions.
    - **AgentRegistry**: Resolves agent definitions for context injection.
    - **Full AgenticLoop inheritance** (P2-B): sub-agents get the same tools,
      MCP, skills, memory as the parent.  Controlled by ``depth`` / ``max_depth``.
    """

    def __init__(
        self,
        runner: IsolatedRunner,
        task_handler: Any | None = None,
        *,
        timeout_s: float = 120.0,
        hooks: HookSystem | None = None,
        coalescing: CoalescingQueue | None = None,
        agent_registry: AgentRegistry | None = None,
        parent_session_key: str = "",
        # P2-B: Full AgenticLoop inheritance
        action_handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        mcp_manager: Any | None = None,
        skill_registry: Any | None = None,
        depth: int = 0,
        max_depth: int = 1,  # Depth=1 enforced (Claude Code pattern: sub-agents cannot recurse)
        # Sandbox hardening: tool scope restriction
        denied_tools: set[str] | None = None,
    ) -> None:
        self._runner = runner
        self._task_handler = task_handler
        self._timeout_s = timeout_s
        self._hooks = hooks
        self._coalescing = coalescing
        self._agent_registry = agent_registry
        self._parent_session_key = parent_session_key
        self._run_records: dict[str, SubagentRunRecord] = {}
        self._records_lock = threading.Lock()
        # P2-B fields
        self._action_handlers = action_handlers
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry
        self._depth = depth
        self._max_depth = max_depth
        # Sandbox hardening: filter denied tools from action_handlers
        self._denied_tools: set[str] = denied_tools or set()
        # Announce mechanism (OpenClaw Spawn+Announce pattern)
        self._announce_enabled = bool(parent_session_key)

    def delegate(
        self,
        tasks: list[SubTask],
        *,
        on_progress: Callable[[SubResult], None] | None = None,
        announce: bool = True,
    ) -> list[SubResult]:
        """Run multiple sub-tasks in parallel, wait for all.

        Args:
            announce: If False, skip pushing results to the announce queue.
                Callers that already return full results via tool_result
                (e.g. delegate_task) should pass announce=False to avoid
                injecting the same information into the parent context twice.
        """
        if not tasks:
            return []

        tasks = self._deduplicate(tasks)
        if not tasks:
            log.info("All tasks coalesced — nothing to execute")
            return []

        graph = self._build_task_graph(tasks)

        session_ids: list[tuple[SubTask, str]] = []
        for task in tasks:
            graph.mark_running(task.task_id)
            self._emit_hook(HookEvent.SUBAGENT_STARTED, task)

            # Build subagent session key for isolation (G7 fix)
            from core.memory.session_key import build_subagent_session_key

            child_key = build_subagent_session_key(
                task.args.get("ip_name", "unknown"), task.task_id
            )

            # Track parent-child relationship (OpenClaw Spawn pattern)
            import uuid as _uuid

            record = SubagentRunRecord(
                run_id=_uuid.uuid4().hex[:12],
                task_id=task.task_id,
                child_session_key=child_key,
                parent_session_key=self._parent_session_key,
                task_type=task.task_type,
                started_at=time.time(),
            )
            with self._records_lock:
                self._run_records[task.task_id] = record
                # Evict oldest records to prevent unbounded growth
                if len(self._run_records) > 200:
                    oldest_key = next(iter(self._run_records))
                    self._run_records.pop(oldest_key, None)

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
            # Route: P2-B (action_handlers set) → subprocess via WorkerRequest
            #        Legacy (task_handler only) → thread via _execute_subtask
            if self._action_handlers is not None:
                fn_or_request = self._build_worker_request(task)
                sid = self._runner.run_async(fn_or_request, config=config)
            else:
                sid = self._runner.run_async(
                    self._execute_subtask, args=(task,), config=config
                )
            session_ids.append((task, sid))
            log.debug(
                "SubAgent launched: %s (%s) key=%s",
                task.task_id,
                task.description,
                child_key,
            )

        # Collect results as they arrive (not in submission order).
        # This ensures SUBAGENT_COMPLETED hooks fire immediately when
        # a task finishes, rather than waiting for earlier tasks.
        results: list[SubResult] = []
        pending: dict[str, SubTask] = {sid: task for task, sid in session_ids}
        deadline = time.time() + self._timeout_s
        poll_interval = 0.05
        max_poll = 0.5

        while pending and time.time() < deadline:
            completed_sids: list[str] = []
            for sid in list(pending):
                isolation = self._runner.get_result(sid)
                if isolation is not None:
                    completed_sids.append(sid)
                    task = pending.pop(sid)
                    sub_result = self._to_sub_result(task, isolation)
                    results.append(sub_result)

                    if sub_result.success:
                        graph.mark_completed(task.task_id, result=sub_result.output)
                        self._emit_hook(HookEvent.SUBAGENT_COMPLETED, task, sub_result=sub_result)
                    else:
                        graph.mark_failed(task.task_id, error=sub_result.error or "unknown")
                        self._emit_hook(HookEvent.SUBAGENT_FAILED, task, error=sub_result.error)

                    if on_progress is not None:
                        try:
                            on_progress(sub_result)
                        except Exception:
                            log.warning(
                                "on_progress callback failed for %s",
                                task.task_id,
                                exc_info=True,
                            )

            if not completed_sids and pending:
                time.sleep(min(poll_interval, max(0, deadline - time.time())))
                poll_interval = min(poll_interval * 1.5, max_poll)

        # Handle timed-out tasks
        for _sid, task in pending.items():
            sub_result = self._to_sub_result(task, None)
            results.append(sub_result)
            graph.mark_failed(task.task_id, error=f"Timeout after {self._timeout_s}s")
            self._emit_hook(HookEvent.SUBAGENT_FAILED, task, error=sub_result.error)

        # Update run records with outcomes (G7 observability)
        now = time.time()
        with self._records_lock:
            for sub_result in results:
                rec = self._run_records.get(sub_result.task_id)
                if rec is not None:
                    rec.completed_at = now
                    rec.outcome = "ok" if sub_result.success else "error"

        # Announce completed results to parent (OpenClaw Spawn+Announce)
        if announce and self._announce_enabled and self._parent_session_key:
            for sub_result in results:
                # Build a SubAgentResult for announce (may already be one)
                summary = ""
                if sub_result.success:
                    summary = sub_result.output.get("summary", "") if sub_result.output else ""
                    if not summary:
                        summary = str(sub_result.output)[:200] if sub_result.output else "completed"
                else:
                    summary = sub_result.error or "failed"
                agent_result = SubAgentResult(
                    task_id=sub_result.task_id,
                    task_type=sub_result.description,
                    status="ok" if sub_result.success else "error",
                    summary=summary,
                    data=sub_result.output,
                    duration_ms=sub_result.duration_ms,
                    error_message=sub_result.error,
                )
                self._announce_result(self._parent_session_key, agent_result)

        succeeded = sum(1 for r in results if r.success)
        log.info(
            "SubAgent batch complete: %d/%d succeeded",
            succeeded,
            len(results),
        )
        return results

    @property
    def hooks(self) -> HookSystem | None:
        return self._hooks

    def get_run_records(self) -> dict[str, SubagentRunRecord]:
        """Return a snapshot of all run records for observability."""
        with self._records_lock:
            return dict(self._run_records)

    def _announce_result(self, parent_session_key: str, child_result: SubAgentResult) -> None:
        """Announce a completed sub-agent result to the parent session.

        Pushes the result into the module-level ``_announce_queue`` so
        the parent AgenticLoop can pick it up on the next round via
        ``drain_announced_results()``.  Marks ``child_result.announced``
        to prevent double-announce.

        OpenClaw Spawn+Announce pattern: child completes -> parent is
        notified asynchronously -> parent injects summary into context.
        """
        with _announce_lock:
            if child_result.announced:
                return
            child_result.announced = True
            _announce_queue.setdefault(parent_session_key, []).append(child_result)
            _announce_timestamps.setdefault(parent_session_key, time.time())
        log.debug(
            "Announced result: task_id=%s to parent=%s (status=%s)",
            child_result.task_id,
            parent_session_key,
            child_result.status,
        )

    def _build_worker_request(self, task: SubTask) -> WorkerRequest:
        """Build a WorkerRequest for subprocess execution (Phase 2).

        The subprocess inherits API keys via env vars. Domain context,
        model config, and denied tools are passed explicitly.
        """
        from core.config import Settings, _resolve_provider
        from core.domains.port import get_domain_or_none

        settings = Settings()
        domain = get_domain_or_none()
        denied = list(self._denied_tools | {"delegate_task"})

        return WorkerRequest(
            task_id=task.task_id,
            task_type=task.task_type,
            description=task.description,
            args=task.args,
            denied_tools=denied,
            model=settings.model,
            provider=_resolve_provider(settings.model),
            timeout_s=self._timeout_s,
            domain=domain.name if domain else "",
        )

    def _resolve_agent(self, task: SubTask) -> dict[str, Any] | None:
        """Resolve agent context.

        Priority: task.agent > _TYPE_AGENT_MAP > None.
        """
        if self._agent_registry is None:
            return None
        agent_name = task.agent or _TYPE_AGENT_MAP.get(task.task_type)
        if agent_name is None:
            return None
        agent_def = self._agent_registry.get(agent_name)
        if agent_def is None:
            log.debug("Agent '%s' not found in registry", agent_name)
            return None
        return {
            "agent_name": agent_def.name,
            "role": agent_def.role,
            "system_prompt": agent_def.system_prompt,
            "tools": agent_def.tools,
            "model": agent_def.model,
        }

    def _build_task_graph(self, tasks: list[SubTask]) -> TaskGraph:
        graph = TaskGraph()
        for task in tasks:
            graph.add_task(
                Task(
                    task_id=task.task_id,
                    name=task.description,
                    metadata={
                        "task_type": task.task_type,
                        **task.args,
                    },
                )
            )
        return graph

    def _deduplicate(self, tasks: list[SubTask]) -> list[SubTask]:
        if self._coalescing is None:
            seen: set[str] = set()
            unique: list[SubTask] = []
            for task in tasks:
                if task.task_id not in seen:
                    seen.add(task.task_id)
                    unique.append(task)
                else:
                    log.debug(
                        "Dedup: skipping duplicate task_id=%s",
                        task.task_id,
                    )
            return unique

        unique = []
        for task in tasks:
            key = f"subagent:{task.task_id}"
            is_new = self._coalescing.submit(key, lambda _k, _d: None, None)
            if is_new:
                unique.append(task)
            else:
                log.debug(
                    "Coalesced: task_id=%s already pending",
                    task.task_id,
                )
        return unique

    def _emit_hook(
        self,
        event: HookEvent,
        task: SubTask,
        *,
        sub_result: SubResult | None = None,
        error: str | None = None,
    ) -> None:
        if self._hooks is None:
            return
        data: dict[str, Any] = {
            "source": "sub_agent",
            "task_id": task.task_id,
            "task_type": task.task_type,
            "description": task.description,
        }
        if sub_result is not None:
            data["duration_ms"] = sub_result.duration_ms
            data["success"] = sub_result.success
            # Include result summary in SUBAGENT_COMPLETED hook data
            # (OpenClaw Announce pattern — hooks carry the completion summary)
            if event == HookEvent.SUBAGENT_COMPLETED:
                summary = sub_result.output.get("summary", "") if sub_result.output else ""
                if not summary:
                    summary = str(sub_result.output)[:200] if sub_result.output else ""
                data["summary"] = summary
        if error is not None:
            data["error"] = error
        try:
            self._hooks.trigger(event, data)
        except Exception:
            log.warning(
                "Hook trigger failed for %s on task %s",
                event.value,
                task.task_id,
                exc_info=True,
            )

    def _execute_subtask(self, task: SubTask) -> str:
        """Execute a single sub-task in thread mode (legacy handler path only).

        Production sub-agents (P2-B with action_handlers) use subprocess via
        WorkerRequest instead. This method is kept for backward compatibility
        with tests and legacy task_handler consumers.

        NOTE: Thread mode cannot enforce denied_tools because the task_handler
        callback is opaque. Use subprocess mode (action_handlers) for security.
        """
        if self._denied_tools:
            log.warning(
                "Thread mode does not enforce denied_tools for task %s. "
                "Use subprocess mode (action_handlers) for security.",
                task.task_id,
            )

        from core.memory.session_key import build_subagent_session_key

        child_key = build_subagent_session_key(task.args.get("ip_name", "unknown"), task.task_id)
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
        agent_context = self._resolve_agent(task)
        try:
            result: dict[str, Any] = self._task_handler(
                task.task_type,
                task.args,
                agent_context=agent_context,
            )
        except TypeError:
            result = self._task_handler(task.task_type, task.args)
        return json.dumps(result, default=str)

    def _wait_for_result(self, session_id: str) -> IsolationResult | None:
        deadline = time.time() + self._timeout_s
        interval = 0.05
        max_interval = 1.0
        while time.time() < deadline:
            result = self._runner.get_result(session_id)
            if result is not None:
                return result
            time.sleep(min(interval, max(0, deadline - time.time())))
            interval = min(interval * 2, max_interval)
        log.warning("SubAgent %s: timeout waiting for result", session_id)
        return None

    def _to_sub_result(self, task: SubTask, isolation: IsolationResult | None) -> SubResult:
        if isolation is None:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=f"Timeout after {self._timeout_s}s",
            )
        if not isolation.success:
            return SubResult(
                task_id=task.task_id,
                description=task.description,
                success=False,
                error=isolation.error,
                duration_ms=isolation.duration_ms,
            )
        output: dict[str, Any]
        try:
            parsed = json.loads(isolation.output) if isolation.output else {}
            output = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, RecursionError):
            output = {"raw": isolation.output}
        return SubResult(
            task_id=task.task_id,
            description=task.description,
            success=True,
            output=output,
            duration_ms=isolation.duration_ms,
        )

    def _to_agent_result(self, task: SubTask, isolation: IsolationResult | None) -> SubAgentResult:
        """Convert IsolationResult to standardized SubAgentResult (P2-A)."""
        if isolation is None:
            return SubAgentResult(
                task_id=task.task_id,
                task_type=task.task_type,
                status="timeout",
                summary=f"Task timed out after {self._timeout_s}s",
                error_category=ErrorCategory.TIMEOUT,
                error_message=f"Timeout after {self._timeout_s}s",
                retryable=True,
            )
        if not isolation.success:
            category = self._classify_error(isolation.error or "")
            return SubAgentResult(
                task_id=task.task_id,
                task_type=task.task_type,
                status="error",
                summary=f"Failed: {isolation.error or 'unknown'}",
                error_category=category,
                error_message=isolation.error,
                retryable=category in {ErrorCategory.TIMEOUT, ErrorCategory.API_ERROR},
                duration_ms=isolation.duration_ms,
            )
        data: dict[str, Any]
        try:
            parsed = json.loads(isolation.output) if isolation.output else {}
            data = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except (json.JSONDecodeError, RecursionError):
            data = {"raw": isolation.output}
        summary = data.get("summary", "")
        if not summary:
            summary = str(data.get("tier", data.get("status", "")))[:200]
        return SubAgentResult(
            task_id=task.task_id,
            task_type=task.task_type,
            status="ok",
            summary=summary,
            data=data,
            duration_ms=isolation.duration_ms,
        )

    @staticmethod
    def _classify_error(error_msg: str) -> str:
        """Classify error message into ErrorCategory."""
        lower = error_msg.lower()
        if "timeout" in lower or "timed out" in lower:
            return ErrorCategory.TIMEOUT
        if "api" in lower or "rate limit" in lower or "authentication" in lower:
            return ErrorCategory.API_ERROR
        if "validation" in lower or "required" in lower or "invalid" in lower:
            return ErrorCategory.VALIDATION
        if "memory" in lower or "disk" in lower or "resource" in lower:
            return ErrorCategory.RESOURCE
        if "depth" in lower:
            return ErrorCategory.DEPTH_EXCEEDED
        return ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Pipeline Handler Factory (Phase 1 — G2 fix)
# ---------------------------------------------------------------------------


def make_pipeline_handler(
    *,
    run_analysis_fn: Callable[..., dict[str, Any] | None],
    search_fn: Callable[..., dict[str, Any]] | None = None,
    compare_fn: Callable[..., dict[str, Any]] | None = None,
    report_fn: Callable[..., tuple[str, str] | None] | None = None,
    force_dry_run: bool = True,
) -> Callable[..., dict[str, Any]]:
    """Create a task_handler routing task_type to pipeline functions."""

    def handler(
        task_type: str,
        args: dict[str, Any],
        *,
        agent_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_type == "analyze":
            ip_name = args.get("ip_name", "")
            if not ip_name:
                return {"error": "ip_name required for analyze task"}
            dry_run = args.get("dry_run", force_dry_run)
            result = run_analysis_fn(ip_name, dry_run=dry_run)
            if result is None:
                return {"error": f"Analysis failed for '{ip_name}'"}
            return _extract_analysis_summary(result, ip_name)
        if task_type == "search":
            if search_fn is None:
                return {"error": "Search not configured"}
            query = args.get("query", "")
            return search_fn(query=query)
        if task_type == "compare":
            if compare_fn is None:
                return {"error": "Compare not configured"}
            return compare_fn(**args)
        if task_type == "report":
            if report_fn is None:
                return {"error": "Report generation not configured"}
            ip_name = args.get("ip_name", "")
            if not ip_name:
                return {"error": "ip_name required for report task"}
            report_result = report_fn(
                ip_name,
                fmt=args.get("format", "markdown"),
                template=args.get("template", "summary"),
                dry_run=args.get("dry_run", force_dry_run),
            )
            if report_result is None:
                return {"error": f"Report generation failed for '{ip_name}'"}
            file_path, content = report_result
            return {
                "status": "ok",
                "action": "report",
                "ip_name": ip_name,
                "file_path": file_path,
                "content_length": len(content),
            }
        return {"error": f"Unknown task_type: {task_type}"}

    return handler


def _extract_analysis_summary(result: dict[str, Any], ip_name: str) -> dict[str, Any]:
    """Extract a compact summary from a pipeline analysis result."""
    return {
        "ip_name": ip_name,
        "tier": result.get("tier", "N/A"),
        "final_score": result.get("final_score", 0),
        "cause": result.get("cause", "unknown"),
        "confidence": result.get("confidence", 0),
    }


# Tool definition loaded from centralized JSON
_TOOLS_JSON_PATH = Path(__file__).resolve().parent.parent / "tools" / "definitions.json"


def _load_tool_definition(name: str) -> dict[str, Any]:
    """Load a single tool definition by name from definitions.json."""
    all_tools: list[dict[str, Any]] = json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))
    for t in all_tools:
        if t["name"] == name:
            return t
    raise KeyError(f"Tool '{name}' not found in {_TOOLS_JSON_PATH}")


DELEGATE_TOOL_DEFINITION: dict[str, Any] = _load_tool_definition("delegate_task")
