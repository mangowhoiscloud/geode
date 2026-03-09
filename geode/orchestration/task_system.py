"""Task System — dependency-aware task decomposition and execution.

Layer 4 orchestration component for complex multi-IP analysis.
Manages a DAG of tasks with dependency tracking, parallel execution
of independent tasks, and status propagation.

A single IP analysis decomposes into ~13 tasks (see SOT dependency graph).
Multi-IP analyses create separate task subgraphs per IP.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    READY = "ready"  # All dependencies satisfied, waiting to run
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """A single unit of work in the task graph."""

    task_id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float | None:
        """Elapsed time in seconds, or None if not started."""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_terminal(self) -> bool:
        """Whether the task is in a terminal state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)


# Type alias for task executors
TaskExecutor = Callable[[Task], Any]


class TaskGraph:
    """Dependency-aware task graph with topological execution.

    Manages a DAG of tasks where each task declares its dependencies.
    Supports computing ready tasks, executing in dependency order,
    and propagating failures.

    Usage:
        graph = TaskGraph()
        graph.add_task(Task(task_id="router", name="Route + load data"))
        graph.add_task(Task(task_id="signals", name="Fetch signals", dependencies=["router"]))
        graph.add_task(Task(task_id="analyst", name="Run analysts", dependencies=["signals"]))

        ready = graph.get_ready_tasks()
        # → [Task(task_id="router", ...)]

        graph.mark_running("router")
        graph.mark_completed("router", result={"ip_info": {...}})

        ready = graph.get_ready_tasks()
        # → [Task(task_id="signals", ...)]
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._stats = _TaskGraphStats()

    @property
    def stats(self) -> _TaskGraphStats:
        return self._stats

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def add_task(self, task: Task) -> None:
        """Add a task to the graph.

        Raises:
            ValueError: If task ID already exists.
        """
        if task.task_id in self._tasks:
            raise ValueError(f"Task '{task.task_id}' already exists in the graph")
        self._tasks[task.task_id] = task
        log.debug("Task added: %s (deps=%s)", task.task_id, task.dependencies)

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    def get_ready_tasks(self) -> list[Task]:
        """Get all tasks whose dependencies are satisfied and that are pending.

        Returns tasks that can be executed in parallel.
        """
        ready: list[Task] = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if self._dependencies_satisfied(task):
                task.status = TaskStatus.READY
                ready.append(task)
        return ready

    def mark_running(self, task_id: str) -> None:
        """Mark a task as running."""
        task = self._require_task(task_id)
        if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
            raise ValueError(f"Cannot start task '{task_id}' in status '{task.status.value}'")
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        self._stats.started += 1
        log.debug("Task running: %s", task_id)

    def mark_completed(self, task_id: str, *, result: Any = None) -> None:
        """Mark a task as completed with an optional result."""
        task = self._require_task(task_id)
        if task.status != TaskStatus.RUNNING:
            raise ValueError(f"Cannot complete task '{task_id}' in status '{task.status.value}'")
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.completed_at = time.time()
        self._stats.completed += 1
        log.debug("Task completed: %s (%.3fs)", task_id, task.elapsed_s or 0)

    def mark_failed(self, task_id: str, *, error: str = "") -> None:
        """Mark a task as failed."""
        task = self._require_task(task_id)
        task.status = TaskStatus.FAILED
        task.error = error
        task.completed_at = time.time()
        self._stats.failed += 1
        log.warning("Task failed: %s — %s", task_id, error)

    def mark_skipped(self, task_id: str) -> None:
        """Mark a task as skipped (e.g., due to upstream failure)."""
        task = self._require_task(task_id)
        task.status = TaskStatus.SKIPPED
        task.completed_at = time.time()
        self._stats.skipped += 1
        log.debug("Task skipped: %s", task_id)

    def propagate_failure(self, task_id: str) -> list[str]:
        """Skip all downstream tasks that depend on a failed task.

        Returns list of task IDs that were skipped.
        """
        skipped: list[str] = []
        to_skip = self._get_dependents(task_id)

        while to_skip:
            current = to_skip.pop(0)
            if current.is_terminal:
                continue
            self.mark_skipped(current.task_id)
            skipped.append(current.task_id)
            # Also skip dependents of skipped tasks
            to_skip.extend(self._get_dependents(current.task_id))

        if skipped:
            log.info(
                "Failure propagation from '%s': skipped %d tasks — %s",
                task_id,
                len(skipped),
                skipped,
            )
        return skipped

    def is_complete(self) -> bool:
        """Check if all tasks are in a terminal state."""
        return all(task.is_terminal for task in self._tasks.values())

    def execution_summary(self) -> dict[str, Any]:
        """Generate a summary of task execution."""
        by_status: dict[str, int] = {}
        for task in self._tasks.values():
            status = task.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_tasks": self.task_count,
            "by_status": by_status,
            "is_complete": self.is_complete(),
            "tasks": {
                tid: {
                    "name": t.name,
                    "status": t.status.value,
                    "elapsed_s": t.elapsed_s,
                    "error": t.error,
                }
                for tid, t in self._tasks.items()
            },
        }

    def topological_order(self) -> list[list[str]]:
        """Compute topological execution order as parallelizable batches.

        Returns batches of task IDs. Tasks within the same batch
        have no interdependencies and can run in parallel.
        """
        completed: set[str] = set()
        remaining = list(self._tasks.keys())
        batches: list[list[str]] = []

        while remaining:
            batch = [
                tid
                for tid in remaining
                if all(dep in completed for dep in self._tasks[tid].dependencies)
            ]
            if not batch:
                log.warning(
                    "Unresolvable dependencies detected, forcing remaining %d tasks",
                    len(remaining),
                )
                batches.append(remaining)
                break
            batches.append(batch)
            completed.update(batch)
            remaining = [tid for tid in remaining if tid not in completed]

        return batches

    def validate(self) -> list[str]:
        """Validate the task graph for missing dependencies and cycles.

        Returns a list of error messages (empty if valid).
        """
        errors: list[str] = []

        # Check for missing dependencies
        for task in self._tasks.values():
            for dep in task.dependencies:
                if dep not in self._tasks:
                    errors.append(f"Task '{task.task_id}' depends on '{dep}' which does not exist")

        # Check for cycles via topological sort attempt
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def _has_cycle(tid: str) -> bool:
            visited.add(tid)
            rec_stack.add(tid)
            task = self._tasks.get(tid)
            if task is None:
                return False
            for dep in task.dependencies:
                if dep not in visited:
                    if _has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    errors.append(f"Cycle detected involving task '{tid}' and '{dep}'")
                    return True
            rec_stack.discard(tid)
            return False

        for tid in self._tasks:
            if tid not in visited:
                _has_cycle(tid)

        return errors

    def _dependencies_satisfied(self, task: Task) -> bool:
        """Check if all dependencies of a task are completed."""
        for dep_id in task.dependencies:
            dep = self._tasks.get(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    def _get_dependents(self, task_id: str) -> list[Task]:
        """Get all tasks that directly depend on the given task."""
        return [task for task in self._tasks.values() if task_id in task.dependencies]

    def _require_task(self, task_id: str) -> Task:
        """Get a task or raise KeyError."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found in the graph")
        return task


# ---------------------------------------------------------------------------
# Convenience: create a standard single-IP task graph
# ---------------------------------------------------------------------------


def create_ip_analysis_graph(ip_name: str) -> TaskGraph:
    """Create a standard task graph for single-IP analysis (~13 tasks).

    Mirrors the GEODE pipeline topology:
        router → signals → 4 analysts (parallel) → evaluators
        → scoring → verification → synthesis
    """
    graph = TaskGraph()
    prefix = ip_name.lower().replace(" ", "_")

    tasks = [
        Task(f"{prefix}_router", "Route + load IP data"),
        Task(f"{prefix}_signals", "Fetch market signals", dependencies=[f"{prefix}_router"]),
        Task(
            f"{prefix}_analyst_market",
            "Market analyst",
            dependencies=[f"{prefix}_signals"],
        ),
        Task(
            f"{prefix}_analyst_creative",
            "Creative quality analyst",
            dependencies=[f"{prefix}_signals"],
        ),
        Task(
            f"{prefix}_analyst_technical",
            "Technical depth analyst",
            dependencies=[f"{prefix}_signals"],
        ),
        Task(
            f"{prefix}_analyst_community",
            "Community momentum analyst",
            dependencies=[f"{prefix}_signals"],
        ),
        Task(
            f"{prefix}_evaluators",
            "Multi-axis evaluators",
            dependencies=[
                f"{prefix}_analyst_market",
                f"{prefix}_analyst_creative",
                f"{prefix}_analyst_technical",
                f"{prefix}_analyst_community",
            ],
        ),
        Task(
            f"{prefix}_scoring",
            "Composite scoring",
            dependencies=[f"{prefix}_evaluators"],
        ),
        Task(
            f"{prefix}_psm",
            "PSM causal inference",
            dependencies=[f"{prefix}_evaluators"],
        ),
        Task(
            f"{prefix}_verification",
            "Guardrails + bias check",
            dependencies=[f"{prefix}_scoring", f"{prefix}_psm"],
        ),
        Task(
            f"{prefix}_cross_llm",
            "Cross-LLM agreement check",
            dependencies=[f"{prefix}_scoring"],
        ),
        Task(
            f"{prefix}_synthesis",
            "Generate value narrative",
            dependencies=[f"{prefix}_verification", f"{prefix}_cross_llm"],
        ),
        Task(
            f"{prefix}_report",
            "Compile final report",
            dependencies=[f"{prefix}_synthesis"],
        ),
    ]

    for task in tasks:
        graph.add_task(task)

    return graph


def create_geode_task_graph(ip_name: str) -> TaskGraph:
    """Create a task graph matching actual GEODE LangGraph node topology.

    Uses real analyst type names (game_mechanics, player_experience, etc.)
    to enable 1:1 mapping from hook events to task state transitions.

    Topology mirrors graph.py:
        router → signals → 4 analysts (parallel) → evaluators
        → scoring + psm (parallel) → verification + cross_llm
        → synthesis → report
    """
    graph = TaskGraph()
    p = ip_name.lower().replace(" ", "_")

    tasks = [
        Task(f"{p}_router", "Route + load IP data"),
        Task(f"{p}_signals", "Fetch market signals", dependencies=[f"{p}_router"]),
        # 4 analysts — match ANALYST_TYPES in nodes/analysts.py
        Task(
            f"{p}_analyst_game_mechanics",
            "Game mechanics analyst",
            dependencies=[f"{p}_signals"],
        ),
        Task(
            f"{p}_analyst_player_experience",
            "Player experience analyst",
            dependencies=[f"{p}_signals"],
        ),
        Task(
            f"{p}_analyst_growth_potential",
            "Growth potential analyst",
            dependencies=[f"{p}_signals"],
        ),
        Task(
            f"{p}_analyst_discovery",
            "Discovery analyst",
            dependencies=[f"{p}_signals"],
        ),
        # Evaluators — single task, completes after 3 evaluator exits
        Task(
            f"{p}_evaluators",
            "Multi-axis evaluators",
            dependencies=[
                f"{p}_analyst_game_mechanics",
                f"{p}_analyst_player_experience",
                f"{p}_analyst_growth_potential",
                f"{p}_analyst_discovery",
            ],
        ),
        # Scoring produces 2 tasks
        Task(f"{p}_scoring", "Composite scoring", dependencies=[f"{p}_evaluators"]),
        Task(f"{p}_psm", "PSM causal inference", dependencies=[f"{p}_evaluators"]),
        # Verification produces 2 tasks
        Task(
            f"{p}_verification",
            "Guardrails + bias check",
            dependencies=[f"{p}_scoring", f"{p}_psm"],
        ),
        Task(f"{p}_cross_llm", "Cross-LLM agreement check", dependencies=[f"{p}_scoring"]),
        # Synthesis produces 2 tasks
        Task(
            f"{p}_synthesis",
            "Generate value narrative",
            dependencies=[f"{p}_verification", f"{p}_cross_llm"],
        ),
        Task(f"{p}_report", "Compile final report", dependencies=[f"{p}_synthesis"]),
    ]

    for task in tasks:
        graph.add_task(task)

    return graph


class _TaskGraphStats:
    """Track task graph statistics."""

    def __init__(self) -> None:
        self.started: int = 0
        self.completed: int = 0
        self.failed: int = 0
        self.skipped: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "started": self.started,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
        }
