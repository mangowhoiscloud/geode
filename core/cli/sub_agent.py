"""SubAgentManager — delegate tasks to parallel sub-agents.

Leverages the existing IsolatedRunner infrastructure for concurrent
task execution, following the Claude Code pattern of parallel
sub-agent delegation.

Orchestration integration:
- TaskGraph: DAG-based dependency tracking per sub-task
- HookSystem: Event emission on task lifecycle (start/complete/fail)
- CoalescingQueue: Deduplication of repeated requests within a time window
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.orchestration.coalescing import CoalescingQueue
from core.orchestration.hooks import HookEvent, HookSystem
from core.orchestration.isolated_execution import IsolatedRunner, IsolationConfig, IsolationResult
from core.orchestration.task_system import Task, TaskGraph

log = logging.getLogger(__name__)


@dataclass
class SubTask:
    """A task to delegate to a sub-agent."""

    task_id: str
    description: str
    task_type: str  # "analyze", "search", "compare", "bash"
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubResult:
    """Result from a sub-agent execution."""

    task_id: str
    description: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


class SubAgentManager:
    """Delegate tasks to parallel sub-agents using IsolatedRunner.

    Orchestration features:
    - **TaskGraph**: Each delegate() call creates a TaskGraph for DAG tracking.
      Tasks with dependencies are resolved via topological_order().
    - **HookSystem**: Emits NODE_ENTER/NODE_EXIT/NODE_ERROR events per sub-task.
    - **CoalescingQueue**: Deduplicates identical task_id submissions within a window.

    Usage::

        manager = SubAgentManager(runner, task_handler)
        results = manager.delegate([
            SubTask("t1", "Analyze Berserk", "analyze", {"ip_name": "Berserk"}),
            SubTask("t2", "Analyze Cowboy Bebop", "analyze", {"ip_name": "Cowboy Bebop"}),
        ])
        # Both run in parallel (up to MAX_CONCURRENT=5)
    """

    def __init__(
        self,
        runner: IsolatedRunner,
        task_handler: Any | None = None,
        *,
        timeout_s: float = 120.0,
        hooks: HookSystem | None = None,
        coalescing: CoalescingQueue | None = None,
    ) -> None:
        self._runner = runner
        self._task_handler = task_handler
        self._timeout_s = timeout_s
        self._hooks = hooks
        self._coalescing = coalescing

    def delegate(self, tasks: list[SubTask]) -> list[SubResult]:
        """Run multiple sub-tasks in parallel, wait for all to complete."""
        if not tasks:
            return []

        # Deduplicate via CoalescingQueue (synchronous check)
        tasks = self._deduplicate(tasks)
        if not tasks:
            log.info("All tasks coalesced — nothing to execute")
            return []

        # Build TaskGraph for dependency tracking
        graph = self._build_task_graph(tasks)

        # Launch all tasks asynchronously
        session_ids: list[tuple[SubTask, str]] = []
        for task in tasks:
            # Track in TaskGraph
            graph.mark_running(task.task_id)

            # Emit NODE_ENTER hook
            self._emit_hook(HookEvent.NODE_ENTER, task)

            config = IsolationConfig(
                session_id=task.task_id,
                timeout_s=self._timeout_s,
                post_to_main=False,  # we collect results ourselves
                prefix=f"SubAgent:{task.task_type}",
                metadata={"description": task.description, "task_type": task.task_type},
            )
            sid = self._runner.run_async(
                self._execute_subtask,
                args=(task,),
                config=config,
            )
            session_ids.append((task, sid))
            log.debug("SubAgent launched: %s (%s)", task.task_id, task.description)

        # Collect results
        results: list[SubResult] = []
        for task, sid in session_ids:
            isolation = self._wait_for_result(sid)
            sub_result = self._to_sub_result(task, isolation)
            results.append(sub_result)

            # Update TaskGraph + emit hooks
            if sub_result.success:
                graph.mark_completed(task.task_id, result=sub_result.output)
                self._emit_hook(HookEvent.NODE_EXIT, task, sub_result=sub_result)
            else:
                graph.mark_failed(task.task_id, error=sub_result.error or "unknown")
                self._emit_hook(HookEvent.NODE_ERROR, task, error=sub_result.error)

        succeeded = sum(1 for r in results if r.success)
        log.info(
            "SubAgent batch complete: %d/%d succeeded",
            succeeded,
            len(results),
        )
        return results

    @property
    def hooks(self) -> HookSystem | None:
        """Access the hook system (for testing/inspection)."""
        return self._hooks

    def _build_task_graph(self, tasks: list[SubTask]) -> TaskGraph:
        """Create a TaskGraph from the list of sub-tasks (no inter-dependencies)."""
        graph = TaskGraph()
        for task in tasks:
            graph.add_task(
                Task(
                    task_id=task.task_id,
                    name=task.description,
                    metadata={"task_type": task.task_type, **task.args},
                )
            )
        return graph

    def _deduplicate(self, tasks: list[SubTask]) -> list[SubTask]:
        """Remove duplicate tasks using CoalescingQueue or simple set-based dedup."""
        if self._coalescing is None:
            # Simple dedup by task_id
            seen: set[str] = set()
            unique: list[SubTask] = []
            for task in tasks:
                if task.task_id not in seen:
                    seen.add(task.task_id)
                    unique.append(task)
                else:
                    log.debug("Dedup: skipping duplicate task_id=%s", task.task_id)
            return unique

        # CoalescingQueue-based dedup: reject tasks with pending keys
        unique = []
        for task in tasks:
            key = f"subagent:{task.task_id}"
            is_new = self._coalescing.submit(key, lambda _k, _d: None, None)
            if is_new:
                unique.append(task)
            else:
                log.debug("Coalesced: task_id=%s already pending", task.task_id)
        return unique

    def _emit_hook(
        self,
        event: HookEvent,
        task: SubTask,
        *,
        sub_result: SubResult | None = None,
        error: str | None = None,
    ) -> None:
        """Emit a hook event for a sub-task lifecycle transition."""
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
        """Execute a single sub-task (runs in isolated thread).

        Returns JSON string so IsolatedRunner stores a safely parseable output.
        """
        if self._task_handler is None:
            return json.dumps({"error": "No task handler configured"})

        try:
            result: dict[str, Any] = self._task_handler(task.task_type, task.args)
            return json.dumps(result, default=str)
        except Exception as exc:
            log.error("SubTask %s failed: %s", task.task_id, exc, exc_info=True)
            return json.dumps({"error": str(exc)})

    def _wait_for_result(self, session_id: str) -> IsolationResult | None:
        """Poll for result completion with exponential backoff.

        Starts at 50ms, caps at 1s. Avoids busy-wait CPU burn on
        long-running tasks while staying responsive for fast ones.
        """
        deadline = time.time() + self._timeout_s
        interval = 0.05  # start 50ms
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
        """Convert IsolationResult to SubResult."""
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

        # Parse JSON output back to dict
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
