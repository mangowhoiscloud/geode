"""TaskGraph Hook Bridge — maps LangGraph node events to TaskGraph state transitions.

Observer pattern: the bridge listens to HookSystem NODE_ENTER/EXIT/ERROR events
and translates them into TaskGraph mark_running/completed/failed calls.
TaskGraph never controls LangGraph execution — it only tracks status.

Node → Task mapping:
    router, gather       → ignored (no task)
    signals              → 1:1
    analyst              → _analyst_type → {p}_analyst_{type}
    evaluator            → counted; {p}_evaluators completes after 3 exits
    scoring              → {p}_scoring + {p}_psm
    verification         → {p}_verification + {p}_cross_llm
    synthesizer          → {p}_synthesis + {p}_report
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.orchestration.task_system import TaskGraph, TaskStatus

log = logging.getLogger(__name__)

# Nodes that have no corresponding task
_IGNORED_NODES = frozenset({"gather"})

# Nodes with 1:1 mapping (node_name → task_id suffix)
_SIMPLE_NODES: dict[str, str] = {
    "router": "router",
    "signals": "signals",
}

# Nodes that map to multiple tasks (node_name → list of task_id suffixes)
_MULTI_TASK_NODES: dict[str, list[str]] = {
    "scoring": ["scoring", "psm"],
    "verification": ["verification", "cross_llm"],
    "synthesizer": ["synthesis", "report"],
}

# Number of evaluator exits required to complete the evaluators task
_EVALUATOR_EXPECTED_COUNT = 3


class TaskGraphHookBridge:
    """Bridge between HookSystem events and TaskGraph state transitions.

    Usage:
        bridge = TaskGraphHookBridge(task_graph, ip_prefix="berserk")
        bridge.register(hooks)
        # Now NODE_ENTER/EXIT/ERROR events automatically update TaskGraph
    """

    def __init__(self, task_graph: TaskGraph, *, ip_prefix: str) -> None:
        self._graph = task_graph
        self._prefix = ip_prefix
        self._evaluator_done_count = 0  # exit + error combined
        self._evaluator_has_error = False
        self._evaluator_lock = threading.Lock()
        self._hooks: HookSystem | None = None

    @property
    def task_graph(self) -> TaskGraph:
        return self._graph

    @property
    def evaluator_done_count(self) -> int:
        return self._evaluator_done_count

    def register(self, hooks: HookSystem) -> None:
        """Register NODE_ENTER/EXIT/ERROR handlers on the HookSystem."""
        self._hooks = hooks
        hooks.register(
            HookEvent.NODE_ENTER,
            self._on_node_enter,
            name="task_bridge_enter",
            priority=30,
        )
        hooks.register(
            HookEvent.NODE_EXIT,
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
            (HookEvent.NODE_ENTER, "task_bridge_enter"),
            (HookEvent.NODE_EXIT, "task_bridge_exit"),
            (HookEvent.NODE_ERROR, "task_bridge_error"),
        ]:
            self._hooks.unregister(event, name)

    def reset(self) -> None:
        """Reset evaluator counters (for REPL reuse)."""
        self._evaluator_done_count = 0
        self._evaluator_has_error = False

    # ------------------------------------------------------------------
    # Hook handlers
    # ------------------------------------------------------------------

    def _on_node_enter(self, event: HookEvent, data: dict[str, Any]) -> None:
        node = data.get("node", "")
        if node in _IGNORED_NODES:
            return

        task_ids = self._resolve_task_ids(node, data)
        for tid in task_ids:
            task = self._graph.get_task(tid)
            if task is None:
                log.debug("Bridge: no task for id=%s (node=%s)", tid, node)
                continue
            # Phase 4-A: skip node if dependency failed (execution control)
            if self._graph.is_blocked(tid):
                log.warning(
                    "Bridge: skipping node '%s' (task %s blocked by failed dependency)",
                    node,
                    tid,
                )
                self._graph.mark_skipped(tid)
                data["_skip_node"] = True
                return
            if task.status in (TaskStatus.PENDING, TaskStatus.READY):
                self._graph.mark_running(tid)

    def _on_node_exit(self, event: HookEvent, data: dict[str, Any]) -> None:
        node = data.get("node", "")
        if node in _IGNORED_NODES:
            return

        # Evaluator counting: complete after all N done (exit + error)
        if node == "evaluator":
            with self._evaluator_lock:
                self._evaluator_done_count += 1
                if self._evaluator_done_count < _EVALUATOR_EXPECTED_COUNT:
                    return
            # All evaluators done — complete if no errors occurred
            tid = f"{self._prefix}_evaluators"
            task = self._graph.get_task(tid)
            if task and task.status == TaskStatus.RUNNING:
                self._graph.mark_completed(tid)
            return

        task_ids = self._resolve_task_ids(node, data)
        for tid in task_ids:
            task = self._graph.get_task(tid)
            if task is None:
                continue
            if task.status == TaskStatus.RUNNING:
                self._graph.mark_completed(tid)

    def _on_node_error(self, event: HookEvent, data: dict[str, Any]) -> None:
        node = data.get("node", "")
        if node in _IGNORED_NODES:
            return

        error_msg = data.get("error", "unknown error")

        # Evaluator: count toward done, fail immediately on first error
        if node == "evaluator":
            self._evaluator_done_count += 1
            self._evaluator_has_error = True
            tid = f"{self._prefix}_evaluators"
            task = self._graph.get_task(tid)
            if task and not task.is_terminal:
                if task.status in (TaskStatus.PENDING, TaskStatus.READY):
                    self._graph.mark_running(tid)
                self._graph.mark_failed(tid, error=error_msg)
                self._graph.propagate_failure(tid)
            return

        task_ids = self._resolve_task_ids(node, data)
        for tid in task_ids:
            task = self._graph.get_task(tid)
            if task is None:
                continue
            if not task.is_terminal:
                if task.status in (TaskStatus.PENDING, TaskStatus.READY):
                    self._graph.mark_running(tid)
                self._graph.mark_failed(tid, error=error_msg)
                self._graph.propagate_failure(tid)

    # ------------------------------------------------------------------
    # Task ID resolution
    # ------------------------------------------------------------------

    def _resolve_task_ids(self, node: str, data: dict[str, Any]) -> list[str]:
        """Resolve a LangGraph node name + hook data to TaskGraph task IDs."""
        p = self._prefix

        # Simple 1:1 mapping
        if node in _SIMPLE_NODES:
            return [f"{p}_{_SIMPLE_NODES[node]}"]

        # Analyst — use _analyst_type from hook data
        if node == "analyst":
            atype = data.get("_analyst_type", "")
            if atype:
                return [f"{p}_analyst_{atype}"]
            return []

        # Evaluator — single evaluators task (counting handled in _on_node_exit)
        if node == "evaluator":
            return [f"{p}_evaluators"]

        # Multi-task nodes
        if node in _MULTI_TASK_NODES:
            return [f"{p}_{suffix}" for suffix in _MULTI_TASK_NODES[node]]

        log.debug("Bridge: unmapped node '%s'", node)
        return []
