"""FleetRegistry — Stage 1 fleet-view data layer (docs/plans/2026-07-03-fleet-view.md).

Pure-data contract tests: dispatch -> running -> terminal lifecycle, snapshot
ordering (running first then by dispatch time), status transitions, tokens/elapsed
capture, and the honest ``current_activity == ""`` invariant (child live tool text
is Stage 1.5, never faked here).
"""

from __future__ import annotations

from core.ui.fleet import TERMINAL_STATUSES, FleetAgent, FleetRegistry


class TestDispatchLifecycle:
    def test_on_dispatch_registers_running_agent(self) -> None:
        reg = FleetRegistry()
        agent = reg.on_dispatch("t1", role="repo_researcher", description="scan the repo")
        assert agent.task_id == "t1"
        assert agent.role == "repo_researcher"
        assert agent.description == "scan the repo"
        assert agent.status == "running"
        assert agent.is_running is True
        assert agent.end_ts is None
        assert agent.start_ts > 0

    def test_on_dispatch_keeps_start_ts_on_redispatch(self) -> None:
        reg = FleetRegistry()
        first = reg.on_dispatch("t1", start_ts=100.0)
        again = reg.on_dispatch("t1", role="patcher")
        assert again is first  # same object, not a duplicate
        assert again.start_ts == 100.0  # original dispatch time preserved
        assert again.role == "patcher"  # metadata refreshed

    def test_on_state_completion_transitions_to_done(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1", role="patcher", start_ts=100.0)
        agent = reg.on_state("t1", status="done", tokens=1500, elapsed_s=12.0)
        assert agent.status == "done"
        assert agent.is_running is False
        assert agent.tokens == 1500
        # end_ts pinned from elapsed so the frozen elapsed matches the parent's measure.
        assert agent.end_ts == 100.0 + 12.0
        assert agent.elapsed_s == 12.0


class TestStatusTransitions:
    def test_error_status(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        agent = reg.on_state("t1", status="error", elapsed_s=3.0)
        assert agent.status == "error"
        assert agent.is_running is False

    def test_timeout_status(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        agent = reg.on_state("t1", status="timeout", elapsed_s=600.0)
        assert agent.status == "timeout"
        assert agent.status in TERMINAL_STATUSES

    def test_on_complete_wrapper_coerces_unknown_to_done(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        agent = reg.on_complete("t1", status="weird", tokens=42, elapsed_s=1.0)
        assert agent.status == "done"
        assert agent.tokens == 42

    def test_completion_racing_ahead_of_dispatch_autocreates(self) -> None:
        """A completion event for an unseen task_id must not drop state."""
        reg = FleetRegistry()
        agent = reg.on_state("t-late", status="done", tokens=7, elapsed_s=2.0)
        assert agent.task_id == "t-late"
        assert agent.status == "done"
        assert agent.tokens == 7


class TestSnapshotOrdering:
    def test_running_first_then_by_start_ts(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("a", start_ts=100.0)
        reg.on_dispatch("b", start_ts=101.0)
        reg.on_dispatch("c", start_ts=102.0)
        # Complete the earliest-dispatched — it must sink below the running ones.
        reg.on_state("a", status="done", elapsed_s=1.0)
        order = [agent.task_id for agent in reg.snapshot()]
        assert order == ["b", "c", "a"]  # running (by start) first, terminal last

    def test_running_helper_filters_to_running(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("a", start_ts=100.0)
        reg.on_dispatch("b", start_ts=101.0)
        reg.on_state("a", status="done", elapsed_s=1.0)
        running = reg.running()
        assert [agent.task_id for agent in running] == ["b"]
        assert all(agent.is_running for agent in running)

    def test_insertion_order_is_stable_tiebreak(self) -> None:
        reg = FleetRegistry()
        # Identical start_ts — insertion order decides.
        reg.on_dispatch("x", start_ts=50.0)
        reg.on_dispatch("y", start_ts=50.0)
        assert [a.task_id for a in reg.snapshot()] == ["x", "y"]


class TestCurrentActivityInvariant:
    def test_current_activity_empty_by_default(self) -> None:
        """Stage 1.5 not plumbed — current_activity must stay '' (never faked)."""
        reg = FleetRegistry()
        agent = reg.on_dispatch("t1", role="verifier")
        assert agent.current_activity == ""
        reg.on_state("t1", status="done", elapsed_s=1.0)
        assert agent.current_activity == ""

    def test_terminal_clears_any_activity(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        # Even if a future plumbing pass sets activity mid-run…
        reg.on_state("t1", status="running", current_activity="grep_files")
        assert reg.snapshot()[0].current_activity == "grep_files"
        # …a terminal transition clears it (nothing is running).
        agent = reg.on_state("t1", status="done", elapsed_s=1.0)
        assert agent.current_activity == ""


class TestTokensAndElapsed:
    def test_tokens_accumulate_from_final_count(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        agent = reg.on_state("t1", status="done", tokens=2048, elapsed_s=5.0)
        assert agent.tokens == 2048

    def test_zero_tokens_not_overwritten_by_later_zero(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        reg.on_state("t1", status="running", tokens=100)
        agent = reg.on_state("t1", status="done", tokens=0, elapsed_s=1.0)
        # A later 0 (subscription/CLI final) must not wipe a known count.
        assert agent.tokens == 100

    def test_elapsed_zero_falls_back_to_wall_clock(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1", start_ts=0.0)
        agent = reg.on_state("t1", status="done", elapsed_s=0.0)
        # elapsed_s == 0 → end_ts pinned to wall clock, elapsed becomes large-ish.
        assert agent.end_ts is not None
        assert agent.elapsed_s >= 0.0


class TestClear:
    def test_clear_drops_all(self) -> None:
        reg = FleetRegistry()
        reg.on_dispatch("t1")
        reg.on_dispatch("t2")
        assert len(reg.snapshot()) == 2
        reg.clear()
        assert reg.snapshot() == []


class TestFleetAgentDefaults:
    def test_defaults(self) -> None:
        agent = FleetAgent(task_id="t")
        assert agent.role == ""
        assert agent.status == "running"
        assert agent.tokens == 0
        assert agent.current_activity == ""
        assert agent.end_ts is None


def test_prespawn_failure_gets_terminal_state_no_stuck_running() -> None:
    """Codex catch: a task that fails before spawn (depth/session cap) still
    must reach a terminal state so the registry never reports it 'running'
    forever. The executor emits terminal status for every dispatched task not
    covered by on_progress; here we assert the registry itself transitions
    running→error cleanly and snapshot() shows zero running."""
    from core.ui.fleet import FleetRegistry

    reg = FleetRegistry()
    reg.on_dispatch("t1", role="patcher", start_ts=100.0)
    assert sum(1 for a in reg.snapshot() if a.status == "running") == 1
    reg.on_state("t1", role="patcher", status="error", description="", tokens=0, elapsed_s=0.1)
    assert sum(1 for a in reg.snapshot() if a.status == "running") == 0
