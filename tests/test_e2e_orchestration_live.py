"""Live E2E tests for orchestration integration.

Tests that exercise the full pipeline with real components (dry-run mode).
Covers scenarios from:
  - docs/e2e/e2e-orchestration-scenarios.md (Sections 3, 5)
  - docs/architecture/orchestration-operation.md (Sections 3-6)

No LLM API calls — all tests use dry-run fixtures.
"""

from __future__ import annotations

from typing import Any

from core.agent.sub_agent import SubAgentManager, SubTask
from core.graph import compile_graph
from core.hooks import HookEvent, HookSystem
from core.orchestration.coalescing import CoalescingQueue
from core.orchestration.isolated_execution import IsolatedRunner
from core.orchestration.task_system import Task, TaskGraph, TaskStatus
from core.state import GeodeState

# ---------------------------------------------------------------------------
# Doc 3 §3: LangGraph Pipeline + HookSystem Event Flow
# ---------------------------------------------------------------------------


class TestPipelineHookEventFlow:
    """Doc 3 §4: HookSystem event flow during pipeline execution."""

    def test_full_event_lifecycle(self) -> None:
        """Verify pipeline emits expected hook events in correct order."""
        hooks = HookSystem()
        events: list[tuple[str, dict[str, Any]]] = []

        def collector(event: HookEvent, data: dict[str, Any]) -> None:
            events.append((event.value, dict(data)))

        for ev in HookEvent:
            hooks.register(ev, collector, name="e2e_collector")

        graph = compile_graph(hooks=hooks)
        state: GeodeState = {
            "ip_name": "berserk",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": False,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        final: dict[str, Any] = {}
        for event in graph.stream(state):
            for node_name, output in event.items():
                if node_name != "__end__":
                    for k, v in output.items():
                        if k in ("analyses", "errors"):
                            final.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                        else:
                            final[k] = v

        # --- Doc 3 §4: Hook event assertions ---
        event_types = [e[0] for e in events]

        # Pipeline lifecycle
        assert "pipeline_start" in event_types
        assert "pipeline_end" in event_types

        # Node lifecycle (at least router, signals, analysts, evaluators, scoring, synthesizer)
        enter_count = event_types.count("node_enter")
        exit_count = event_types.count("node_exit")
        assert enter_count >= 6, f"Expected ≥6 node_enter, got {enter_count}"
        assert exit_count >= 6, f"Expected ≥6 node_exit, got {exit_count}"

        # Analyst-level events
        assert "analyst_complete" in event_types

        # Scoring
        assert "scoring_complete" in event_types

        # pipeline_start and pipeline_end should both be present
        assert "pipeline_start" in event_types
        assert "pipeline_end" in event_types

        # Pipeline result
        assert final.get("tier") in ("S", "A", "B", "C")
        assert final.get("final_score", 0) > 0
        assert len(final.get("analyses", [])) == 4

    def test_node_enter_exit_pairing(self) -> None:
        """Every node_enter should have a matching node_exit."""
        hooks = HookSystem()
        enters: list[str] = []
        exits: list[str] = []

        def on_enter(event: HookEvent, data: dict[str, Any]) -> None:
            enters.append(data.get("node", "unknown"))

        def on_exit(event: HookEvent, data: dict[str, Any]) -> None:
            exits.append(data.get("node", "unknown"))

        hooks.register(HookEvent.NODE_ENTER, on_enter, name="enter_tracker")
        hooks.register(HookEvent.NODE_EXIT, on_exit, name="exit_tracker")

        graph = compile_graph(hooks=hooks)
        state: GeodeState = {
            "ip_name": "cowboy bebop",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": True,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        for _ in graph.stream(state):
            pass

        # Every entered node should also exit
        assert len(enters) == len(exits), f"Mismatch: {len(enters)} enters vs {len(exits)} exits"


# ---------------------------------------------------------------------------
# Doc 3 §5: TaskGraph DAG State Tracking
# ---------------------------------------------------------------------------


class TestTaskGraphDAGTracking:
    """Doc 3 §5: TaskGraph as observer of pipeline state."""

    def test_create_geode_task_graph(self) -> None:
        """Verify standard GEODE task graph has correct topology."""
        from core.orchestration.task_system import create_geode_task_graph

        graph = create_geode_task_graph("Berserk")
        assert graph.task_count == 13  # 13 tasks in standard GEODE topology

        # Validate no cycles or missing deps
        errors = graph.validate()
        assert errors == [], f"Validation errors: {errors}"

        # Topological order should produce multiple batches
        batches = graph.topological_order()
        assert len(batches) >= 4  # at least: router, signals, analysts, evaluators...

        # First batch should be router (no deps)
        assert len(batches[0]) == 1
        assert "router" in batches[0][0]

    def test_task_lifecycle_transitions(self) -> None:
        """Verify TaskGraph state transitions match Doc 3 §5."""
        graph = TaskGraph()
        graph.add_task(Task("t1", "Router"))
        graph.add_task(Task("t2", "Signals", dependencies=["t1"]))

        # Initially both PENDING
        assert graph.get_task("t1").status == TaskStatus.PENDING  # type: ignore[union-attr]
        assert graph.get_task("t2").status == TaskStatus.PENDING  # type: ignore[union-attr]

        # t1 ready (no deps), t2 not yet
        ready = graph.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "t1"

        # Run t1
        graph.mark_running("t1")
        assert graph.get_task("t1").status == TaskStatus.RUNNING  # type: ignore[union-attr]

        # Complete t1
        graph.mark_completed("t1", result={"data": "ok"})
        assert graph.get_task("t1").status == TaskStatus.COMPLETED  # type: ignore[union-attr]

        # Now t2 should be ready
        ready2 = graph.get_ready_tasks()
        assert len(ready2) == 1
        assert ready2[0].task_id == "t2"

    def test_failure_propagation(self) -> None:
        """Doc 3 §6: failure cascades to downstream tasks."""
        graph = TaskGraph()
        graph.add_task(Task("router", "Router"))
        graph.add_task(Task("signals", "Signals", dependencies=["router"]))
        graph.add_task(Task("analyst", "Analyst", dependencies=["signals"]))

        graph.get_ready_tasks()  # promotes router to READY
        graph.mark_running("router")
        graph.mark_failed("router", error="API timeout")

        # Propagate failure
        skipped = graph.propagate_failure("router")
        assert "signals" in skipped
        assert "analyst" in skipped

        assert graph.get_task("signals").status == TaskStatus.SKIPPED  # type: ignore[union-attr]
        assert graph.get_task("analyst").status == TaskStatus.SKIPPED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Doc 1 §3: SubAgent Orchestration (live execution with real IsolatedRunner)
# ---------------------------------------------------------------------------


class TestSubAgentOrchestrationLive:
    """Doc 1 §3: SubAgent parallel execution with orchestration."""

    def test_parallel_tasks_with_hooks_and_graph(self) -> None:
        """Full integration: IsolatedRunner + TaskGraph + HookSystem."""
        hooks = HookSystem()
        event_log: list[tuple[str, str]] = []

        def on_event(event: HookEvent, data: dict[str, Any]) -> None:
            event_log.append((event.value, data.get("task_id", "")))

        hooks.register(HookEvent.SUBAGENT_STARTED, on_event, name="log_enter")
        hooks.register(HookEvent.SUBAGENT_COMPLETED, on_event, name="log_exit")

        runner = IsolatedRunner()

        def handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"ip_name": args.get("ip_name", ""), "score": 85.0}

        manager = SubAgentManager(runner, handler, timeout_s=30, hooks=hooks)

        tasks = [
            SubTask("t1", "Analyze Berserk", "analyze", {"ip_name": "Berserk"}),
            SubTask("t2", "Analyze Cowboy Bebop", "analyze", {"ip_name": "Cowboy Bebop"}),
            SubTask("t3", "Analyze Naruto", "analyze", {"ip_name": "Naruto"}),
        ]

        results = manager.delegate(tasks)

        # All 3 succeed
        assert len(results) == 3
        assert all(r.success for r in results)

        # Verify hook events
        enter_ids = [tid for ev, tid in event_log if ev == "subagent_started"]
        exit_ids = [tid for ev, tid in event_log if ev == "subagent_completed"]
        assert set(enter_ids) == {"t1", "t2", "t3"}
        assert set(exit_ids) == {"t1", "t2", "t3"}

        # Verify output content
        for r in results:
            assert r.output["score"] == 85.0

    def test_coalescing_prevents_duplicate_execution(self) -> None:
        """Doc 1 §3-3: CoalescingQueue dedup across batches."""
        runner = IsolatedRunner()
        call_count = 0

        def counting_handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"call": call_count}

        queue = CoalescingQueue(window_ms=5000)
        manager = SubAgentManager(runner, counting_handler, timeout_s=10, coalescing=queue)

        # First batch
        r1 = manager.delegate([SubTask("dup1", "First", "analyze", {})])
        assert len(r1) == 1

        # Second batch — same key should be coalesced
        r2 = manager.delegate([SubTask("dup1", "Duplicate", "analyze", {})])
        assert len(r2) == 0

        # Different key should execute
        r3 = manager.delegate([SubTask("dup2", "Different", "search", {})])
        assert len(r3) == 1

        queue.cancel_all()

    def test_mixed_success_and_failure(self) -> None:
        """Some tasks succeed, some fail — verify per-task hook events."""
        hooks = HookSystem()
        errors: list[str] = []
        successes: list[str] = []

        def on_exit(event: HookEvent, data: dict[str, Any]) -> None:
            successes.append(data["task_id"])

        def on_error(event: HookEvent, data: dict[str, Any]) -> None:
            errors.append(data["task_id"])

        hooks.register(HookEvent.SUBAGENT_COMPLETED, on_exit, name="success_log")
        hooks.register(HookEvent.SUBAGENT_FAILED, on_error, name="error_log")

        runner = IsolatedRunner()

        def flaky_handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            if args.get("fail"):
                raise ValueError("intentional failure")
            return {"ok": True}

        manager = SubAgentManager(runner, flaky_handler, timeout_s=10, hooks=hooks)

        tasks = [
            SubTask("good1", "Good task", "analyze", {"fail": False}),
            SubTask("bad1", "Bad task", "analyze", {"fail": True}),
            SubTask("good2", "Good task 2", "search", {"fail": False}),
        ]

        results = manager.delegate(tasks)
        assert len(results) == 3

        # good1, good2 succeed; bad1 has error in output
        good_results = [r for r in results if r.task_id in ("good1", "good2")]
        assert all(r.success for r in good_results)

        # bad1: exception caught by _execute_subtask → error in JSON output
        bad = next(r for r in results if r.task_id == "bad1")
        assert "error" in bad.output


# ---------------------------------------------------------------------------
# Doc 3 §6: End-to-End Execution Flow (full pipeline + orchestration)
# ---------------------------------------------------------------------------


class TestEndToEndExecutionFlow:
    """Doc 3 §6: Complete runtime → pipeline → hook → task flow."""

    def test_runtime_to_synthesis(self) -> None:
        """Full flow: compile_graph → stream → all nodes → final result."""
        hooks = HookSystem()
        node_sequence: list[str] = []

        def track_node(event: HookEvent, data: dict[str, Any]) -> None:
            node_sequence.append(data.get("node", "?"))

        hooks.register(HookEvent.NODE_ENTER, track_node, name="seq_tracker")

        graph = compile_graph(hooks=hooks)
        state: GeodeState = {
            "ip_name": "ghost in the shell",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": True,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        final: dict[str, Any] = {}
        for event in graph.stream(state):
            for node_name, output in event.items():
                if node_name != "__end__":
                    for k, v in output.items():
                        if k in ("analyses", "errors"):
                            final.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                        else:
                            final[k] = v

        # Doc 3 §3.1 topology: router → cortex → signals → analysts → evaluators → scoring → ...
        assert "router" in node_sequence
        assert "synthesizer" in node_sequence

        # Pipeline produced valid output
        assert final.get("tier") in ("S", "A", "B", "C")
        assert len(final.get("analyses", [])) == 4
        assert final.get("synthesis") is not None

    def test_analyst_parallel_execution(self) -> None:
        """Doc 3 §3: 4 analysts run via Send API (parallel in LangGraph)."""
        hooks = HookSystem()
        analyst_nodes: list[str] = []

        def track_analyst(event: HookEvent, data: dict[str, Any]) -> None:
            # Hook data uses "_analyst_type" key from Send API subtype propagation
            atype = data.get("_analyst_type", data.get("node", "unknown"))
            analyst_nodes.append(atype)

        hooks.register(HookEvent.ANALYST_COMPLETE, track_analyst, name="analyst_track")

        graph = compile_graph(hooks=hooks)
        state: GeodeState = {
            "ip_name": "berserk",
            "pipeline_mode": "full_pipeline",
            "dry_run": True,
            "verbose": False,
            "skip_verification": True,
            "analyses": [],
            "errors": [],
            "iteration": 1,
            "max_iterations": 3,
        }

        for _ in graph.stream(state):
            pass

        # 4 analyst types: game_mechanics, player_experience, growth_potential, discovery
        assert len(analyst_nodes) == 4, f"Expected 4 analysts, got {analyst_nodes}"
        expected = {"game_mechanics", "player_experience", "growth_potential", "discovery"}
        assert set(analyst_nodes) == expected


# ---------------------------------------------------------------------------
# G7 Fix: Parallel SubAgent Session Isolation
# ---------------------------------------------------------------------------


class TestSubAgentSessionIsolationE2E:
    """G7 fix: Verify parallel subagents don't contend on SQLite."""

    def test_parallel_subagent_no_sqlite_contention(self) -> None:
        """Start 3 tasks in parallel and verify all succeed without errors."""
        import time

        runner = IsolatedRunner()

        def slow_handler(task_type: str, args: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.1)
            return {"ip_name": args.get("ip_name", ""), "done": True}

        manager = SubAgentManager(runner, slow_handler, timeout_s=30)

        tasks = [
            SubTask("p1", "Parallel 1", "analyze", {"ip_name": "Berserk"}),
            SubTask("p2", "Parallel 2", "analyze", {"ip_name": "Cowboy Bebop"}),
            SubTask("p3", "Parallel 3", "analyze", {"ip_name": "Ghost in the Shell"}),
        ]

        results = manager.delegate(tasks)

        assert len(results) == 3
        assert all(r.success for r in results), (
            f"Some tasks failed: {[(r.task_id, r.error) for r in results if not r.success]}"
        )

        # Verify each result has correct output
        ip_names = {r.output.get("ip_name") for r in results}
        assert "Berserk" in ip_names
        assert "Cowboy Bebop" in ip_names
        assert "Ghost in the Shell" in ip_names
