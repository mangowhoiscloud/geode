"""Client-side fleet registry — per-sub-agent live state for the fleet view.

Stage 1 data layer (design SOT: ``docs/plans/2026-07-03-fleet-view.md``). This
module is **pure data, no rendering**: the thin-client :class:`EventRenderer`
feeds it from ``subagent_state`` IPC events and reads :meth:`FleetRegistry.snapshot`
to draw the one-line turn-time fleet summary. Stage 2's interactive full-screen
view (``/fleet`` + up/down/Enter) reads the same snapshot — building that
interactive surface is a separate later stage, not this module.

What Stage 1 can populate per agent (all parent-side, all honest):

- ``task_id`` — correlation id (crosses the worker IPC boundary both ways).
- ``role`` / ``description`` — from the parent's :class:`~core.agent.sub_agent.SubTask`.
- ``status`` — ``running`` at dispatch; ``done`` / ``error`` / ``timeout`` on
  completion (derived from the ``SubResult``).
- ``start_ts`` / ``end_ts`` / ``elapsed_s`` — parent-side wall clock.
- ``tokens`` — the sub-agent's final ``prompt + completion`` count from the
  ``WorkerResult`` (``0`` for subscription / CLI-routed calls — the subscription
  path does not expose usage; never fabricated).

What Stage 1 CANNOT populate (deferred to Stage 1.5): ``current_activity`` — a
child's live current tool. Sub-agents run as ``python -m core.agent.worker``
subprocesses with the child ``AgenticLoop`` in ``quiet=True`` mode, so the child
emits no per-tool IPC back to the parent — only a single final ``WorkerResult``
line crosses the boundary at exit. Surfacing the child's live tool text requires
child->parent activity plumbing (a task_id-tagged event side-channel), which is
Stage 1.5. It is left as ``""`` here rather than faked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Statuses that mean the sub-agent is no longer executing. A terminal status
# freezes ``end_ts`` and clears ``current_activity`` (nothing is running).
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "error", "timeout"})


@dataclass
class FleetAgent:
    """Live state of one delegated sub-agent, keyed by ``task_id``."""

    task_id: str
    role: str = ""
    description: str = ""
    # running | done | error | timeout
    status: str = "running"
    start_ts: float = 0.0
    end_ts: float | None = None
    tokens: int = 0
    # '' until Stage 1.5 child->parent activity plumbing lands — never faked.
    current_activity: str = ""

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def elapsed_s(self) -> float:
        """Wall-clock seconds since dispatch (frozen at ``end_ts`` once terminal)."""
        end = self.end_ts if self.end_ts is not None else time.time()
        return max(0.0, end - self.start_ts)


class FleetRegistry:
    """In-memory per-agent registry keyed by ``task_id`` (single-threaded owner).

    Owned by one :class:`EventRenderer` instance, mutated only from the thin
    client's event-dispatch path, so no lock is needed. Every mutator is
    idempotent-friendly: an unseen ``task_id`` is auto-created so a completion
    event that races ahead of (or replaces) a dispatch event never drops state.
    """

    def __init__(self) -> None:
        self._agents: dict[str, FleetAgent] = {}
        # Insertion order — the stable tiebreaker for snapshot() so agents
        # dispatched in the same wall-clock instant keep a deterministic order.
        self._seq: dict[str, int] = {}
        self._next_seq = 0

    def _ensure(self, task_id: str, *, start_ts: float | None = None) -> FleetAgent:
        agent = self._agents.get(task_id)
        if agent is None:
            agent = FleetAgent(
                task_id=task_id,
                start_ts=start_ts if start_ts is not None else time.time(),
            )
            self._agents[task_id] = agent
            self._seq[task_id] = self._next_seq
            self._next_seq += 1
        return agent

    def on_dispatch(
        self,
        task_id: str,
        *,
        role: str = "",
        description: str = "",
        start_ts: float | None = None,
    ) -> FleetAgent:
        """Register a newly dispatched sub-agent as ``running``.

        Re-dispatching an existing ``task_id`` refreshes metadata but keeps the
        original ``start_ts`` (elapsed time must not reset mid-run).
        """
        agent = self._ensure(task_id, start_ts=start_ts)
        agent.status = "running"
        agent.end_ts = None
        if role:
            agent.role = role
        if description:
            agent.description = description
        return agent

    def on_state(
        self,
        task_id: str,
        *,
        role: str = "",
        status: str = "running",
        description: str = "",
        tokens: int = 0,
        elapsed_s: float = 0.0,
        current_activity: str = "",
    ) -> FleetAgent:
        """Apply a ``subagent_state`` transition (the authoritative feed).

        Handles both the ``running`` dispatch event and the terminal
        completion event. On a terminal status, ``end_ts`` is pinned from
        ``elapsed_s`` (when > 0) so the frozen elapsed matches the parent's
        measured duration, and ``current_activity`` is cleared.
        """
        agent = self._ensure(task_id)
        if role:
            agent.role = role
        if description:
            agent.description = description
        if tokens:
            agent.tokens = tokens
        if status:
            agent.status = status
        if status in TERMINAL_STATUSES:
            agent.end_ts = (agent.start_ts + elapsed_s) if elapsed_s > 0 else time.time()
            agent.current_activity = ""
        else:
            agent.end_ts = None
            # current_activity is Stage 1.5; only accept it when actually plumbed.
            if current_activity:
                agent.current_activity = current_activity
        return agent

    def on_complete(
        self,
        task_id: str,
        *,
        status: str = "done",
        tokens: int = 0,
        elapsed_s: float = 0.0,
    ) -> FleetAgent:
        """Terminal-transition convenience wrapper over :meth:`on_state`."""
        final_status = status if status in TERMINAL_STATUSES else "done"
        return self.on_state(
            task_id,
            status=final_status,
            tokens=tokens,
            elapsed_s=elapsed_s,
        )

    def snapshot(self) -> list[FleetAgent]:
        """Return all agents, running first then by dispatch time (stable).

        Sort key: ``(not running, start_ts, insertion_seq)`` — running agents
        lead, ties broken by wall-clock then by insertion order so the order is
        fully deterministic for both the summary line and the Stage 2 view.
        """
        return sorted(
            self._agents.values(),
            key=lambda a: (not a.is_running, a.start_ts, self._seq[a.task_id]),
        )

    def running(self) -> list[FleetAgent]:
        """Snapshot filtered to the currently-running agents (already ordered)."""
        return [agent for agent in self.snapshot() if agent.is_running]

    def clear(self) -> None:
        """Drop all tracked agents (e.g. at the start of a fresh turn)."""
        self._agents.clear()
        self._seq.clear()
        self._next_seq = 0
