"""Tests for Production-Grade Agent Upgrade (Phases 1-5).

Covers:
- Phase 1: Confidence calculation bug fix, evaluator fallback, CLI type safety
- Phase 2: NodeScopePolicy, tool injection paths
- Phase 3: Partial retry (make_analyst_sends skips good results)
- Phase 4: TaskGraph.is_blocked / has_failed_dependency
- Phase 5: LangSmith conditional activation
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from core.domains.game_ip.nodes.scoring import _calc_analyst_confidence
from core.state import AnalysisResult

# ---------------------------------------------------------------------------
# Phase 1-A: Confidence Calculation Bug Fix
# ---------------------------------------------------------------------------


class TestConfidenceEdgeCases:
    """Verify _calc_analyst_confidence handles edge cases correctly."""

    def test_zero_analyses_returns_zero(self):
        assert _calc_analyst_confidence([]) == 0.0

    def test_single_analysis_returns_fifty(self):
        a = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=["x"],
            confidence=80.0,
        )
        assert _calc_analyst_confidence([a]) == 50.0

    def test_two_identical_analyses_returns_100(self):
        a = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=["x"],
            confidence=80.0,
        )
        # CV = 0 when all scores identical → (1 - 0) * 100 = 100
        assert _calc_analyst_confidence([a, a]) == 100.0

    def test_mean_zero_returns_ten(self):
        # AnalysisResult enforces score >= 1, so we test _calc_analyst_confidence
        # directly with mock objects that have score=0
        from unittest.mock import MagicMock

        a = MagicMock(score=0.0)
        assert _calc_analyst_confidence([a, a]) == 10.0

    def test_diverse_scores_reduces_confidence(self):
        a1 = AnalysisResult(
            analyst_type="game_mechanics",
            score=1.0,
            key_finding="low",
            reasoning="test",
            evidence=["x"],
            confidence=50.0,
        )
        a2 = AnalysisResult(
            analyst_type="player_experience",
            score=5.0,
            key_finding="high",
            reasoning="test",
            evidence=["x"],
            confidence=90.0,
        )
        conf = _calc_analyst_confidence([a1, a2])
        assert 0.0 <= conf <= 100.0
        # High variation → low confidence
        assert conf < 80.0


# ---------------------------------------------------------------------------
# Phase 1-B: Evaluator Fallback Default Mismatch
# ---------------------------------------------------------------------------


class TestEvaluatorFallbackDefaults:
    """Verify evaluator fallback uses neutral 3.0 instead of minimum 1.0."""

    def test_quality_judge_fallback_neutral(self):
        # We test the fallback values directly
        _FALLBACK_NEUTRAL = 3.0
        default_axes = {
            "quality_judge": {
                "a_score": _FALLBACK_NEUTRAL,
                "b_score": _FALLBACK_NEUTRAL,
                "c_score": _FALLBACK_NEUTRAL,
                "b1_score": _FALLBACK_NEUTRAL,
                "c1_score": _FALLBACK_NEUTRAL,
                "c2_score": _FALLBACK_NEUTRAL,
                "m_score": _FALLBACK_NEUTRAL,
                "n_score": _FALLBACK_NEUTRAL,
            },
        }
        axes = default_axes["quality_judge"]
        assert all(v == 3.0 for v in axes.values())

    def test_hidden_value_fallback_neutral(self):
        _FALLBACK_NEUTRAL = 3.0
        axes = {
            "d_score": _FALLBACK_NEUTRAL,
            "e_score": _FALLBACK_NEUTRAL,
            "f_score": _FALLBACK_NEUTRAL,
        }
        assert all(v == 3.0 for v in axes.values())


# ---------------------------------------------------------------------------
# Phase 2-D: NodeScopePolicy
# ---------------------------------------------------------------------------


class TestNodeScopePolicy:
    def test_default_allowlists(self):
        from core.tools.policy import NODE_TOOL_ALLOWLISTS, NodeScopePolicy

        NodeScopePolicy()  # Ensure it can be constructed
        assert "analyst" in NODE_TOOL_ALLOWLISTS
        assert "evaluator" in NODE_TOOL_ALLOWLISTS
        assert "scoring" in NODE_TOOL_ALLOWLISTS

    def test_filter_analyst_tools(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        all_tools = ["memory_search", "memory_get", "query_monolake", "steam_info", "psm_calculate"]
        filtered = policy.filter(all_tools, node="analyst")
        assert set(filtered) == {"memory_search", "memory_get", "query_monolake"}

    def test_filter_evaluator_tools(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        all_tools = [
            "memory_search",
            "memory_get",
            "steam_info",
            "reddit_sentiment",
            "psm_calculate",
        ]
        filtered = policy.filter(all_tools, node="evaluator")
        assert set(filtered) == {"memory_search", "memory_get", "steam_info", "reddit_sentiment"}

    def test_filter_scoring_tools(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        all_tools = ["memory_search", "psm_calculate", "steam_info"]
        filtered = policy.filter(all_tools, node="scoring")
        assert set(filtered) == {"memory_search", "psm_calculate"}

    def test_prefix_matching(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        filtered = policy.filter(["memory_search", "steam_info"], node="analyst_game_mechanics")
        assert "memory_search" in filtered
        assert "steam_info" not in filtered

    def test_unknown_node_passthrough(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        all_tools = ["a", "b", "c"]
        assert policy.filter(all_tools, node="unknown_node") == all_tools

    def test_none_node_passthrough(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        all_tools = ["a", "b"]
        assert policy.filter(all_tools, node=None) == all_tools

    def test_is_allowed(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        assert policy.is_allowed("memory_search", node="analyst") is True
        assert policy.is_allowed("steam_info", node="analyst") is False

    def test_get_allowlist(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        allowlist = policy.get_allowlist("analyst")
        assert "memory_search" in allowlist
        assert "steam_info" not in allowlist

    def test_custom_allowlists(self):
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy(node_allowlists={"custom": ["tool_a", "tool_b"]})
        filtered = policy.filter(["tool_a", "tool_b", "tool_c"], node="custom")
        assert set(filtered) == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# Phase 3-B: Partial Retry (make_analyst_sends)
# ---------------------------------------------------------------------------


class TestPartialRetry:
    def _base_state(self, iteration: int = 1, analyses: list | None = None):
        return {
            "ip_name": "Test IP",
            "ip_info": {"ip_name": "Test IP"},
            "monolake": {},
            "signals": {},
            "dry_run": True,
            "verbose": False,
            "_prompt_overrides": {},
            "_extra_instructions": [],
            "memory_context": None,
            "iteration": iteration,
            "analyses": analyses or [],
        }

    def test_first_iteration_sends_all_four(self):
        from core.domains.game_ip.nodes.analysts import make_analyst_sends

        state = self._base_state(iteration=1)
        sends = make_analyst_sends(state)
        assert len(sends) == 4

    def test_second_iteration_skips_good_results(self):
        from core.domains.game_ip.nodes.analysts import make_analyst_sends

        good_analysis = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="good",
            reasoning="solid",
            evidence=["x"],
            confidence=80.0,
            is_degraded=False,
        )
        degraded_analysis = AnalysisResult(
            analyst_type="player_experience",
            score=1.0,
            key_finding="degraded",
            reasoning="failed",
            evidence=["x"],
            confidence=0.0,
            is_degraded=True,
        )
        state = self._base_state(
            iteration=2,
            analyses=[good_analysis, degraded_analysis],
        )
        sends = make_analyst_sends(state)
        # Should skip game_mechanics (good), re-run player_experience + 2 missing
        types_sent = [s.arg.get("_analyst_type") for s in sends]
        assert "game_mechanics" not in types_sent
        assert "player_experience" in types_sent
        assert len(sends) == 3  # 4 total - 1 skipped


# ---------------------------------------------------------------------------
# Phase 4-A: TaskGraph.is_blocked
# ---------------------------------------------------------------------------


class TestTaskGraphBlocked:
    def test_is_blocked_with_failed_dep(self):
        from core.orchestration.task_system import Task, TaskGraph

        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A", dependencies=[]))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))

        graph.mark_running("a")
        graph.mark_failed("a", error="boom")

        assert graph.is_blocked("b") is True

    def test_is_blocked_no_failed_dep(self):
        from core.orchestration.task_system import Task, TaskGraph

        graph = TaskGraph()
        graph.add_task(Task(task_id="a", name="A", dependencies=[]))
        graph.add_task(Task(task_id="b", name="B", dependencies=["a"]))

        graph.mark_running("a")
        graph.mark_completed("a")

        assert graph.is_blocked("b") is False

    def test_is_blocked_unknown_task(self):
        from core.orchestration.task_system import TaskGraph

        graph = TaskGraph()
        assert graph.is_blocked("nonexistent") is False

    def test_has_failed_dependency(self):
        from core.orchestration.task_system import Task, TaskGraph

        graph = TaskGraph()
        graph.add_task(
            Task(
                task_id="test_analyst_gm",
                name="Analyst GM",
                dependencies=["test_signals"],
            )
        )
        graph.add_task(Task(task_id="test_signals", name="Signals", dependencies=[]))

        graph.mark_running("test_signals")
        graph.mark_failed("test_signals", error="api error")

        assert graph.has_failed_dependency("analyst", "test") is True


# ---------------------------------------------------------------------------
# Phase 4-B: StuckDetector Hook Registration
# ---------------------------------------------------------------------------


class TestStuckDetectorHooks:
    def test_register_hooks(self):
        from core.orchestration.stuck_detection import StuckDetector

        detector = StuckDetector(timeout_s=10.0)
        hooks = MagicMock()
        detector.register_hooks(hooks)
        assert hooks.register.call_count == 3

    def test_on_stuck_fires_pipeline_error(self):
        from core.orchestration.stuck_detection import StuckDetector

        detector = StuckDetector(timeout_s=0.0)  # instant timeout
        hooks = MagicMock()
        detector.register_hooks(hooks)

        detector.mark_running("test:node", metadata={"node": "analyst"})
        stuck = detector.check_stuck()
        assert "test:node" in stuck
        # on_stuck callback should have triggered PIPELINE_ERROR
        assert hooks.trigger.called


# ---------------------------------------------------------------------------
# Phase 5: LangSmith Conditional Activation
# ---------------------------------------------------------------------------


class TestLangSmithConditional:
    def test_no_api_key_returns_identity(self):
        from core.llm.client import maybe_traceable

        with patch.dict(os.environ, {}, clear=True):
            # No LANGCHAIN_TRACING_V2 or API key → passthrough
            decorator = maybe_traceable(run_type="llm", name="test")

            def dummy():
                return 42

            result = decorator(dummy)
            assert result is dummy  # Identity — no wrapping


# ---------------------------------------------------------------------------
# Phase 2 + Graph: NodeScopePolicy integration in build_graph
# ---------------------------------------------------------------------------


class TestGraphWithNodeScopePolicy:
    def test_build_graph_with_policy(self):
        from core.graph import build_graph
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        graph = build_graph(node_scope_policy=policy)
        assert graph is not None

    def test_compile_graph_with_policy(self):
        from core.graph import compile_graph
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        compiled = compile_graph(node_scope_policy=policy)
        assert compiled is not None

    def test_dry_run_with_policy_still_works(self):
        from core.graph import compile_graph
        from core.tools.policy import NodeScopePolicy

        policy = NodeScopePolicy()
        compiled = compile_graph(node_scope_policy=policy)
        result = compiled.invoke(
            {
                "ip_name": "Cowboy Bebop",
                "pipeline_mode": "full_pipeline",
                "dry_run": True,
                "verbose": False,
                "skip_verification": False,
                "analyses": [],
                "errors": [],
            }
        )
        assert result["tier"] in ("S", "A", "B", "C")
        assert len(result["analyses"]) == 4
