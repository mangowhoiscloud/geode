"""Tests for TaskGraphHookBridge — hook event → task state mapping."""

from __future__ import annotations

from core.hooks import HookEvent, HookSystem
from core.orchestration.task_bridge import TaskGraphHookBridge
from core.orchestration.task_system import (
    TaskStatus,
    create_geode_task_graph,
)


def _make_bridge(ip: str = "berserk") -> tuple[TaskGraphHookBridge, HookSystem]:
    """Create a bridge + hooks wired to a geode task graph."""
    graph = create_geode_task_graph(ip)
    hooks = HookSystem()
    bridge = TaskGraphHookBridge(graph, ip_prefix=ip.lower().replace(" ", "_"))
    bridge.register(hooks)
    return bridge, hooks


class TestSimpleNodeMapping:
    def test_router_enter_marks_running(self):
        bridge, hooks = _make_bridge()
        hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        task = bridge.task_graph.get_task("berserk_router")
        assert task is not None
        assert task.status == TaskStatus.RUNNING

    def test_router_exit_marks_completed(self):
        bridge, hooks = _make_bridge()
        hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "router", "ip_name": "berserk"})
        task = bridge.task_graph.get_task("berserk_router")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED

    def test_signals_enter_exit(self):
        bridge, hooks = _make_bridge()
        # Must complete router first (dependency)
        bridge.task_graph.get_ready_tasks()
        bridge.task_graph.mark_running("berserk_router")
        bridge.task_graph.mark_completed("berserk_router")

        hooks.trigger(HookEvent.NODE_ENTER, {"node": "signals", "ip_name": "berserk"})
        assert bridge.task_graph.get_task("berserk_signals").status == TaskStatus.RUNNING

        hooks.trigger(HookEvent.NODE_EXIT, {"node": "signals", "ip_name": "berserk"})
        assert bridge.task_graph.get_task("berserk_signals").status == TaskStatus.COMPLETED


class TestAnalystTypeMapping:
    def test_analyst_type_resolves_correct_task(self):
        bridge, hooks = _make_bridge()
        # Satisfy dependencies: router → signals
        g = bridge.task_graph
        g.get_ready_tasks()
        g.mark_running("berserk_router")
        g.mark_completed("berserk_router")
        g.get_ready_tasks()
        g.mark_running("berserk_signals")
        g.mark_completed("berserk_signals")

        hooks.trigger(
            HookEvent.NODE_ENTER,
            {"node": "analyst", "ip_name": "berserk", "_analyst_type": "game_mechanics"},
        )
        assert g.get_task("berserk_analyst_game_mechanics").status == TaskStatus.RUNNING

        hooks.trigger(
            HookEvent.NODE_EXIT,
            {"node": "analyst", "ip_name": "berserk", "_analyst_type": "game_mechanics"},
        )
        assert g.get_task("berserk_analyst_game_mechanics").status == TaskStatus.COMPLETED

    def test_all_four_analyst_types(self):
        bridge, hooks = _make_bridge()
        g = bridge.task_graph
        g.get_ready_tasks()
        g.mark_running("berserk_router")
        g.mark_completed("berserk_router")
        g.get_ready_tasks()
        g.mark_running("berserk_signals")
        g.mark_completed("berserk_signals")

        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            hooks.trigger(
                HookEvent.NODE_ENTER,
                {"node": "analyst", "ip_name": "berserk", "_analyst_type": atype},
            )
            hooks.trigger(
                HookEvent.NODE_EXIT,
                {"node": "analyst", "ip_name": "berserk", "_analyst_type": atype},
            )
            assert g.get_task(f"berserk_analyst_{atype}").status == TaskStatus.COMPLETED


class TestEvaluatorCounting:
    def _prepare_graph(self) -> tuple[TaskGraphHookBridge, HookSystem]:
        """Prepare graph with all analyst dependencies completed."""
        bridge, hooks = _make_bridge()
        g = bridge.task_graph
        g.get_ready_tasks()
        g.mark_running("berserk_router")
        g.mark_completed("berserk_router")
        g.get_ready_tasks()
        g.mark_running("berserk_signals")
        g.mark_completed("berserk_signals")
        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            g.get_ready_tasks()
            g.mark_running(f"berserk_analyst_{atype}")
            g.mark_completed(f"berserk_analyst_{atype}")
        return bridge, hooks

    def test_evaluators_complete_after_3_exits(self):
        bridge, hooks = self._prepare_graph()
        g = bridge.task_graph

        # Mark evaluators running via NODE_ENTER
        hooks.trigger(
            HookEvent.NODE_ENTER,
            {"node": "evaluator", "ip_name": "berserk", "_evaluator_type": "quality_judge"},
        )
        assert g.get_task("berserk_evaluators").status == TaskStatus.RUNNING

        # First 2 exits — still running
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "evaluator", "ip_name": "berserk"})
        assert bridge.evaluator_done_count == 1
        assert g.get_task("berserk_evaluators").status == TaskStatus.RUNNING

        hooks.trigger(HookEvent.NODE_EXIT, {"node": "evaluator", "ip_name": "berserk"})
        assert bridge.evaluator_done_count == 2
        assert g.get_task("berserk_evaluators").status == TaskStatus.RUNNING

        # Third exit — completes
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "evaluator", "ip_name": "berserk"})
        assert bridge.evaluator_done_count == 3
        assert g.get_task("berserk_evaluators").status == TaskStatus.COMPLETED

    def test_evaluator_error_counts_toward_done(self):
        """1 error + 2 success: done_count reaches 3, task FAILED from error."""
        bridge, hooks = self._prepare_graph()
        g = bridge.task_graph

        # Mark running
        hooks.trigger(
            HookEvent.NODE_ENTER,
            {"node": "evaluator", "ip_name": "berserk", "_evaluator_type": "quality_judge"},
        )

        # Evaluator 1 errors → immediate FAILED + propagate
        hooks.trigger(
            HookEvent.NODE_ERROR,
            {"node": "evaluator", "ip_name": "berserk", "error": "LLM timeout"},
        )
        assert bridge.evaluator_done_count == 1
        assert bridge._evaluator_has_error is True
        assert g.get_task("berserk_evaluators").status == TaskStatus.FAILED
        assert g.get_task("berserk_scoring").status == TaskStatus.SKIPPED

        # Evaluators 2 & 3 exit — done_count tracks, task stays FAILED
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "evaluator", "ip_name": "berserk"})
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "evaluator", "ip_name": "berserk"})
        assert bridge.evaluator_done_count == 3
        assert g.get_task("berserk_evaluators").status == TaskStatus.FAILED


class TestMultiTaskMapping:
    def test_scoring_maps_to_two_tasks(self):
        bridge, hooks = _make_bridge()
        g = bridge.task_graph
        # Fast-forward: complete all prerequisites
        for tid in ["berserk_router", "berserk_signals"]:
            g.get_ready_tasks()
            g.mark_running(tid)
            g.mark_completed(tid)
        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            g.get_ready_tasks()
            g.mark_running(f"berserk_analyst_{atype}")
            g.mark_completed(f"berserk_analyst_{atype}")
        g.get_ready_tasks()
        g.mark_running("berserk_evaluators")
        g.mark_completed("berserk_evaluators")

        hooks.trigger(HookEvent.NODE_ENTER, {"node": "scoring", "ip_name": "berserk"})
        assert g.get_task("berserk_scoring").status == TaskStatus.RUNNING
        assert g.get_task("berserk_psm").status == TaskStatus.RUNNING

        hooks.trigger(HookEvent.NODE_EXIT, {"node": "scoring", "ip_name": "berserk"})
        assert g.get_task("berserk_scoring").status == TaskStatus.COMPLETED
        assert g.get_task("berserk_psm").status == TaskStatus.COMPLETED

    def test_verification_maps_to_two_tasks(self):
        bridge, hooks = _make_bridge()
        g = bridge.task_graph
        # Fast-forward through all prerequisites
        for tid in ["berserk_router", "berserk_signals"]:
            g.get_ready_tasks()
            g.mark_running(tid)
            g.mark_completed(tid)
        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            g.get_ready_tasks()
            g.mark_running(f"berserk_analyst_{atype}")
            g.mark_completed(f"berserk_analyst_{atype}")
        for tid in ["berserk_evaluators", "berserk_scoring", "berserk_psm", "berserk_cross_llm"]:
            g.get_ready_tasks()
            g.mark_running(tid)
            g.mark_completed(tid)

        hooks.trigger(HookEvent.NODE_ENTER, {"node": "verification", "ip_name": "berserk"})
        assert g.get_task("berserk_verification").status == TaskStatus.RUNNING
        assert g.get_task("berserk_cross_llm").status == TaskStatus.COMPLETED  # already done

        hooks.trigger(HookEvent.NODE_EXIT, {"node": "verification", "ip_name": "berserk"})
        assert g.get_task("berserk_verification").status == TaskStatus.COMPLETED

    def test_synthesizer_maps_to_synthesis_and_report(self):
        bridge, hooks = _make_bridge()
        g = bridge.task_graph
        # Fast-forward all prerequisites
        for tid in ["berserk_router", "berserk_signals"]:
            g.get_ready_tasks()
            g.mark_running(tid)
            g.mark_completed(tid)
        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            g.get_ready_tasks()
            g.mark_running(f"berserk_analyst_{atype}")
            g.mark_completed(f"berserk_analyst_{atype}")
        for tid in [
            "berserk_evaluators",
            "berserk_scoring",
            "berserk_psm",
            "berserk_cross_llm",
            "berserk_verification",
        ]:
            g.get_ready_tasks()
            g.mark_running(tid)
            g.mark_completed(tid)

        hooks.trigger(HookEvent.NODE_ENTER, {"node": "synthesizer", "ip_name": "berserk"})
        assert g.get_task("berserk_synthesis").status == TaskStatus.RUNNING
        assert g.get_task("berserk_report").status == TaskStatus.RUNNING

        hooks.trigger(HookEvent.NODE_EXIT, {"node": "synthesizer", "ip_name": "berserk"})
        assert g.get_task("berserk_synthesis").status == TaskStatus.COMPLETED
        assert g.get_task("berserk_report").status == TaskStatus.COMPLETED


class TestErrorPropagation:
    def test_node_error_marks_failed_and_propagates(self):
        bridge, hooks = _make_bridge()
        hooks.trigger(
            HookEvent.NODE_ENTER,
            {"node": "router", "ip_name": "berserk"},
        )
        hooks.trigger(
            HookEvent.NODE_ERROR,
            {"node": "router", "ip_name": "berserk", "error": "connection timeout"},
        )
        g = bridge.task_graph
        assert g.get_task("berserk_router").status == TaskStatus.FAILED
        assert g.get_task("berserk_router").error == "connection timeout"

        # Downstream should be skipped
        assert g.get_task("berserk_signals").status == TaskStatus.SKIPPED


class TestIgnoredNodes:
    def test_gather_ignored(self):
        bridge, hooks = _make_bridge()
        hooks.trigger(HookEvent.NODE_ENTER, {"node": "gather", "ip_name": "berserk"})
        hooks.trigger(HookEvent.NODE_EXIT, {"node": "gather", "ip_name": "berserk"})
        assert bridge.task_graph.get_task("berserk_router").status == TaskStatus.PENDING


class TestBridgeLifecycle:
    def test_reset_clears_evaluator_state(self):
        bridge, hooks = _make_bridge()
        bridge._evaluator_done_count = 2
        bridge._evaluator_has_error = True
        bridge.reset()
        assert bridge.evaluator_done_count == 0
        assert bridge._evaluator_has_error is False

    def test_unregister_removes_handlers(self):
        bridge, hooks = _make_bridge()
        # Verify handlers are active
        hooks.trigger(HookEvent.NODE_ENTER, {"node": "router", "ip_name": "berserk"})
        assert bridge.task_graph.get_task("berserk_router").status == TaskStatus.RUNNING

        # Unregister
        bridge.unregister()

        # Create a new graph+bridge to verify old hooks are gone
        graph2 = create_geode_task_graph("berserk")
        bridge2 = TaskGraphHookBridge(graph2, ip_prefix="berserk")
        bridge2.register(hooks)

        hooks.trigger(HookEvent.NODE_ENTER, {"node": "signals", "ip_name": "berserk"})
        # Key: only 1 set of handlers, no duplicate firing
        assert bridge2.task_graph.get_task("berserk_router").status == TaskStatus.PENDING

    def test_unregister_without_register_is_safe(self):
        graph = create_geode_task_graph("berserk")
        bridge = TaskGraphHookBridge(graph, ip_prefix="berserk")
        bridge.unregister()  # Should not raise


class TestGeodeTaskGraphFactory:
    def test_creates_13_tasks(self):
        graph = create_geode_task_graph("Berserk")
        assert graph.task_count == 13

    def test_valid_graph(self):
        graph = create_geode_task_graph("Berserk")
        errors = graph.validate()
        assert errors == []

    def test_uses_real_analyst_types(self):
        graph = create_geode_task_graph("Berserk")
        for atype in ["game_mechanics", "player_experience", "growth_potential", "discovery"]:
            assert graph.get_task(f"berserk_analyst_{atype}") is not None

    def test_prefix_normalization(self):
        graph = create_geode_task_graph("Cowboy Bebop")
        assert graph.get_task("cowboy_bebop_router") is not None
        assert graph.get_task("cowboy_bebop_report") is not None

    def test_topological_order(self):
        graph = create_geode_task_graph("Berserk")
        batches = graph.topological_order()
        # batch 0: router
        assert batches[0] == ["berserk_router"]
        # batch 1: signals
        assert batches[1] == ["berserk_signals"]
        # batch 2: 4 analysts
        assert sorted(batches[2]) == sorted(
            [
                "berserk_analyst_game_mechanics",
                "berserk_analyst_player_experience",
                "berserk_analyst_growth_potential",
                "berserk_analyst_discovery",
            ]
        )
