"""SubAgentManager — delegate tasks to parallel sub-agents.

Leverages the existing IsolatedRunner infrastructure for concurrent
task execution, following the Claude Code pattern of parallel
sub-agent delegation.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.orchestration.isolated_execution import IsolatedRunner, IsolationConfig, IsolationResult

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
    ) -> None:
        self._runner = runner
        self._task_handler = task_handler
        self._timeout_s = timeout_s

    def delegate(self, tasks: list[SubTask]) -> list[SubResult]:
        """Run multiple sub-tasks in parallel, wait for all to complete."""
        if not tasks:
            return []

        # Launch all tasks asynchronously
        session_ids: list[tuple[SubTask, str]] = []
        for task in tasks:
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
            result = self._wait_for_result(sid)
            results.append(self._to_sub_result(task, result))

        log.info(
            "SubAgent batch complete: %d/%d succeeded",
            sum(1 for r in results if r.success),
            len(results),
        )
        return results

    def _execute_subtask(self, task: SubTask) -> dict[str, Any]:
        """Execute a single sub-task (runs in isolated thread)."""
        if self._task_handler is None:
            return {"error": "No task handler configured"}

        try:
            result: dict[str, Any] = self._task_handler(task.task_type, task.args)
            return result
        except Exception as exc:
            log.error("SubTask %s failed: %s", task.task_id, exc, exc_info=True)
            return {"error": str(exc)}

    def _wait_for_result(
        self, session_id: str, poll_interval: float = 0.1
    ) -> IsolationResult | None:
        """Poll for result completion."""
        deadline = time.time() + self._timeout_s
        while time.time() < deadline:
            result = self._runner.get_result(session_id)
            if result is not None:
                return result
            time.sleep(poll_interval)

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

        # Parse output string back to dict if possible
        output: dict[str, Any]
        try:
            import ast

            output = ast.literal_eval(isolation.output) if isolation.output else {}
        except (ValueError, SyntaxError):
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
