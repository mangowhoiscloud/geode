"""TaskGraph hook bridge.

The bridge observes generic node lifecycle hooks and updates matching
``TaskGraph`` tasks. Domain plugins that need richer node-to-task mapping should
provide their own bridge or task graph.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.orchestration.task_system import TaskGraph, TaskStatus

log = logging.getLogger(__name__)


class TaskGraphHookBridge:
    """Bridge between HookSystem node events and TaskGraph state transitions."""

    def __init__(self, task_graph: TaskGraph, *, subject_prefix: str) -> None:
        self._graph = task_graph
        self._prefix = subject_prefix
        self._hooks: HookSystem | None = None

    @property
    def task_graph(self) -> TaskGraph:
        return self._graph

    def register(self, hooks: HookSystem) -> None:
        """Register NODE_ENTER/EXIT/ERROR handlers on the HookSystem."""
        self._hooks = hooks
        hooks.register(
            HookEvent.NODE_ENTERED,
            self._on_node_enter,
            name="task_bridge_enter",
            priority=30,
        )
        hooks.register(
            HookEvent.NODE_EXITED,
            self._on_node_exit,
            name="task_bridge_exit",
            priority=30,
        )
        hooks.register(
            HookEvent.NODE_ERROR,
            self._on_node_error,
            name="task_bridge_error",
            priority=30,
        )

    def unregister(self) -> None:
        """Remove all bridge handlers from the HookSystem."""
        if self._hooks is None:
            return
        for event, name in [
            (HookEvent.NODE_ENTERED, "task_bridge_enter"),
            (HookEvent.NODE_EXITED, "task_bridge_exit"),
            (HookEvent.NODE_ERROR, "task_bridge_error"),
        ]:
            self._hooks.unregister(event, name)

    def reset(self) -> None:
        """Reset bridge-local state."""

    def _on_node_enter(self, event: HookEvent, data: dict[str, Any]) -> None:
        for task_id in self._resolve_task_ids(str(data.get("node", ""))):
            task = self._graph.get_task(task_id)
            if task is None:
                log.debug("Bridge: no task for id=%s", task_id)
                continue
            if self._graph.is_blocked(task_id):
                self._graph.mark_skipped(task_id)
                data["_skip_node"] = True
                return
            if task.status in (TaskStatus.PENDING, TaskStatus.READY):
                self._graph.mark_running(task_id)

    def _on_node_exit(self, event: HookEvent, data: dict[str, Any]) -> None:
        for task_id in self._resolve_task_ids(str(data.get("node", ""))):
            task = self._graph.get_task(task_id)
            if task is not None and task.status == TaskStatus.RUNNING:
                self._graph.mark_completed(task_id)

    def _on_node_error(self, event: HookEvent, data: dict[str, Any]) -> None:
        error_msg = str(data.get("error", "unknown error"))
        for task_id in self._resolve_task_ids(str(data.get("node", ""))):
            task = self._graph.get_task(task_id)
            if task is None or task.is_terminal:
                continue
            if task.status in (TaskStatus.PENDING, TaskStatus.READY):
                self._graph.mark_running(task_id)
            self._graph.mark_failed(task_id, error=error_msg)
            self._graph.propagate_failure(task_id)

    def _resolve_task_ids(self, node: str) -> list[str]:
        """Resolve a node name to a default task id."""
        if not node:
            return []
        safe_node = node.lower().replace(" ", "_")
        return [f"{self._prefix}_{safe_node}"]
