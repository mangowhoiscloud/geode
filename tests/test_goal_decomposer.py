"""Tests for GoalDecomposer — autonomous goal decomposition."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from core.orchestration.goal_decomposer import (
    DecomposerStats,
    DecompositionResult,
    GoalDecomposer,
    SubGoal,
    _has_compound_indicators,
    _is_clearly_simple,
)
from core.orchestration.task_system import TaskGraph

# ---------------------------------------------------------------------------
# SubGoal model tests
# ---------------------------------------------------------------------------


class TestSubGoal:
    """Unit tests for SubGoal Pydantic model."""

    def test_basic_creation(self) -> None:
        goal = SubGoal(
            id="step_1",
            description="Search for dark fantasy IPs",
            tool_name="search_ips",
            tool_args={"query": "dark fantasy"},
        )
        assert goal.id == "step_1"
        assert goal.tool_name == "search_ips"
        assert goal.depends_on == []

    def test_with_dependencies(self) -> None:
        goal = SubGoal(
            id="step_2",
            description="Analyze top result",
            tool_name="analyze_ip",
            tool_args={"ip_name": "Berserk"},
            depends_on=["step_1"],
        )
        assert goal.depends_on == ["step_1"]

    def test_empty_args(self) -> None:
        goal = SubGoal(id="s1", description="List IPs", tool_name="list_ips")
        assert goal.tool_args == {}


# ---------------------------------------------------------------------------
# DecompositionResult model tests
# ---------------------------------------------------------------------------


class TestDecompositionResult:
    """Unit tests for DecompositionResult model."""

    def test_simple_result(self) -> None:
        result = DecompositionResult(is_compound=False)
        assert not result.is_compound
        assert result.goals == []

    def test_compound_result(self) -> None:
        goals = [
            SubGoal(id="s1", description="Search", tool_name="search_ips"),
            SubGoal(id="s2", description="Analyze", tool_name="analyze_ip", depends_on=["s1"]),
        ]
        result = DecompositionResult(
            is_compound=True,
            goals=goals,
            reasoning="User wants search then analyze",
        )
        assert result.is_compound
        assert len(result.goals) == 2
        assert result.goals[1].depends_on == ["s1"]


# ---------------------------------------------------------------------------
# Heuristic pre-filter tests
# ---------------------------------------------------------------------------


class TestHeuristics:
    """Unit tests for _is_clearly_simple and _has_compound_indicators."""

    def test_simple_slash_command(self) -> None:
        assert _is_clearly_simple("/help") is True
        assert _is_clearly_simple("/status") is True

    def test_simple_short_input(self) -> None:
        assert _is_clearly_simple("목록") is True
        assert _is_clearly_simple("help") is True
        assert _is_clearly_simple("도움말") is True

    def test_not_simple_long_input(self) -> None:
        assert _is_clearly_simple("Berserk의 시장성을 종합적으로 평가해줘") is False

    def test_compound_korean_connectors(self) -> None:
        assert _has_compound_indicators("분석하고 비교해줘") is True
        assert _has_compound_indicators("검색하고 리포트 만들어줘") is True

    def test_compound_english_connectors(self) -> None:
        assert _has_compound_indicators("analyze and compare") is True
        assert _has_compound_indicators("search then report") is True

    def test_compound_comprehensive_keywords(self) -> None:
        assert _has_compound_indicators("종합 평가해줘") is True
        assert _has_compound_indicators("다각도 분석") is True
        assert _has_compound_indicators("comprehensive evaluation") is True
        assert _has_compound_indicators("end-to-end analysis") is True

    def test_no_compound_indicators(self) -> None:
        assert _has_compound_indicators("Berserk 분석해줘") is False
        assert _has_compound_indicators("목록 보여줘") is False
        assert _has_compound_indicators("help") is False


# ---------------------------------------------------------------------------
# GoalDecomposer tests
# ---------------------------------------------------------------------------


class TestGoalDecomposer:
    """Unit tests for GoalDecomposer."""

    def test_simple_passthrough_slash_command(self) -> None:
        """Slash commands should pass through without decomposition."""
        decomposer = GoalDecomposer()
        result = decomposer.decompose("/help")
        assert result is None
        assert decomposer.stats.simple_passthrough == 1

    def test_simple_passthrough_short_input(self) -> None:
        """Short inputs should pass through."""
        decomposer = GoalDecomposer()
        result = decomposer.decompose("목록")
        assert result is None
        assert decomposer.stats.simple_passthrough == 1

    def test_simple_passthrough_no_compound(self) -> None:
        """Single-intent requests without compound indicators pass through."""
        decomposer = GoalDecomposer()
        result = decomposer.decompose("Berserk 분석해줘")
        assert result is None
        assert decomposer.stats.simple_passthrough == 1

    @patch("core.llm.router.call_llm_parsed")
    def test_compound_request_decomposed(self, mock_llm: MagicMock) -> None:
        """Compound requests should be decomposed into sub-goals."""
        mock_llm.return_value = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(
                    id="step_1",
                    description="Analyze Berserk",
                    tool_name="analyze_ip",
                    tool_args={"ip_name": "Berserk"},
                ),
                SubGoal(
                    id="step_2",
                    description="Generate report",
                    tool_name="generate_report",
                    tool_args={"ip_name": "Berserk"},
                    depends_on=["step_1"],
                ),
            ],
            reasoning="User wants analysis then report",
        )

        decomposer = GoalDecomposer()
        result = decomposer.decompose("Berserk 분석하고 리포트 만들어줘")

        assert result is not None
        assert result.is_compound is True
        assert len(result.goals) == 2
        assert result.goals[0].tool_name == "analyze_ip"
        assert result.goals[1].depends_on == ["step_1"]
        assert decomposer.stats.compound_detected == 1

    @patch("core.llm.router.call_llm_parsed")
    def test_llm_says_not_compound(self, mock_llm: MagicMock) -> None:
        """When LLM determines the request is single-intent, return None."""
        mock_llm.return_value = DecompositionResult(
            is_compound=False,
            goals=[],
            reasoning="Single tool call sufficient",
        )

        decomposer = GoalDecomposer()
        # Use a keyword that triggers compound indicators but LLM says no
        result = decomposer.decompose("이것을 종합적으로 분석해줘")

        assert result is None
        assert decomposer.stats.simple_passthrough == 1

    @patch("core.llm.router.call_llm_parsed")
    def test_llm_error_returns_none(self, mock_llm: MagicMock) -> None:
        """LLM errors should return None (graceful degradation)."""
        mock_llm.side_effect = RuntimeError("API error")

        decomposer = GoalDecomposer()
        result = decomposer.decompose("이 게임의 시장성을 종합적으로 평가해줘")

        assert result is None
        assert decomposer.stats.llm_errors == 1

    @patch("core.llm.router.call_llm_parsed")
    def test_single_goal_not_compound(self, mock_llm: MagicMock) -> None:
        """Single goal result should not be treated as compound."""
        mock_llm.return_value = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(id="s1", description="Analyze", tool_name="analyze_ip"),
            ],
        )

        decomposer = GoalDecomposer()
        result = decomposer.decompose("종합 분석해줘")

        assert result is None  # Single goal = not compound
        assert decomposer.stats.simple_passthrough == 1


# ---------------------------------------------------------------------------
# TaskGraph conversion tests
# ---------------------------------------------------------------------------


class TestBuildTaskGraph:
    """Tests for GoalDecomposer.build_task_graph_from_goals."""

    def test_basic_dag(self) -> None:
        """Build a valid TaskGraph from decomposition result."""
        decomposer = GoalDecomposer()
        result = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(id="s1", description="Search", tool_name="search_ips"),
                SubGoal(
                    id="s2",
                    description="Analyze",
                    tool_name="analyze_ip",
                    depends_on=["s1"],
                ),
                SubGoal(
                    id="s3",
                    description="Report",
                    tool_name="generate_report",
                    depends_on=["s2"],
                ),
            ],
        )

        graph: TaskGraph = decomposer.build_task_graph_from_goals(result)

        assert graph.task_count == 3
        assert graph.validate() == []  # No errors

        # Check topological order
        batches = graph.topological_order()
        assert len(batches) == 3
        assert batches[0] == ["s1"]
        assert batches[1] == ["s2"]
        assert batches[2] == ["s3"]

    def test_parallel_goals(self) -> None:
        """Independent goals should be in the same batch."""
        decomposer = GoalDecomposer()
        result = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(id="s1", description="Analyze A", tool_name="analyze_ip"),
                SubGoal(id="s2", description="Analyze B", tool_name="analyze_ip"),
                SubGoal(
                    id="s3",
                    description="Compare",
                    tool_name="compare_ips",
                    depends_on=["s1", "s2"],
                ),
            ],
        )

        graph: TaskGraph = decomposer.build_task_graph_from_goals(result)

        assert graph.task_count == 3
        batches = graph.topological_order()
        assert len(batches) == 2
        # s1 and s2 should be in the first batch (parallel)
        assert set(batches[0]) == {"s1", "s2"}
        assert batches[1] == ["s3"]

    def test_task_metadata(self) -> None:
        """Tasks should carry tool_name and tool_args in metadata."""
        decomposer = GoalDecomposer()
        result = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(
                    id="s1",
                    description="Analyze Berserk",
                    tool_name="analyze_ip",
                    tool_args={"ip_name": "Berserk"},
                ),
            ],
        )

        graph: TaskGraph = decomposer.build_task_graph_from_goals(result)
        task = graph.get_task("s1")

        assert task is not None
        assert task.metadata["tool_name"] == "analyze_ip"
        assert task.metadata["tool_args"] == {"ip_name": "Berserk"}


# ---------------------------------------------------------------------------
# DecomposerStats tests
# ---------------------------------------------------------------------------


class TestDecomposerStats:
    """Tests for DecomposerStats."""

    def test_initial_stats(self) -> None:
        stats = DecomposerStats()
        assert stats.total_calls == 0
        assert stats.compound_detected == 0
        assert stats.simple_passthrough == 0
        assert stats.llm_errors == 0

    def test_to_dict(self) -> None:
        stats = DecomposerStats(total_calls=5, compound_detected=2, simple_passthrough=3)
        d = stats.to_dict()
        assert d["total_calls"] == 5
        assert d["compound_detected"] == 2
        assert d["simple_passthrough"] == 3

    def test_stats_accumulation(self) -> None:
        decomposer = GoalDecomposer()
        decomposer.decompose("/help")
        decomposer.decompose("목록")
        decomposer.decompose("Berserk 분석해")

        assert decomposer.stats.total_calls == 3
        assert decomposer.stats.simple_passthrough == 3


# ---------------------------------------------------------------------------
# Tool summary builder tests
# ---------------------------------------------------------------------------


class TestToolSummary:
    """Tests for GoalDecomposer._build_tool_summary."""

    def test_empty_tools(self) -> None:
        result = GoalDecomposer._build_tool_summary([])
        assert "no tools available" in result

    def test_with_tools(self) -> None:
        tools: list[dict[str, Any]] = [
            {
                "name": "analyze_ip",
                "description": "Analyze a specific IP. More details here.",
                "cost_tier": "expensive",
            },
            {
                "name": "list_ips",
                "description": "List all available IPs.",
                "cost_tier": "free",
            },
        ]
        result = GoalDecomposer._build_tool_summary(tools)
        assert "analyze_ip" in result
        assert "[expensive]" in result
        assert "list_ips" in result
        assert "[free]" in result


# ---------------------------------------------------------------------------
# Integration with AgenticLoop tests
# ---------------------------------------------------------------------------


class TestAgenticLoopIntegration:
    """Tests for GoalDecomposer integration with AgenticLoop."""

    def test_decomposition_disabled(self) -> None:
        """When decomposition is disabled, _try_decompose returns None."""
        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        context = ConversationContext()
        executor = ToolExecutor(auto_approve=True)
        loop = AgenticLoop(
            context,
            executor,
            enable_goal_decomposition=False,
        )

        result = loop._try_decompose("종합적으로 분석하고 리포트 만들어줘")
        assert result is None

    @patch("core.llm.router.call_llm_parsed")
    def test_decomposition_returns_hint(self, mock_llm: MagicMock) -> None:
        """Compound request should produce a system prompt hint."""
        mock_llm.return_value = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(
                    id="step_1",
                    description="Analyze Berserk",
                    tool_name="analyze_ip",
                    tool_args={"ip_name": "Berserk"},
                ),
                SubGoal(
                    id="step_2",
                    description="Generate report",
                    tool_name="generate_report",
                    tool_args={"ip_name": "Berserk"},
                    depends_on=["step_1"],
                ),
            ],
            reasoning="Analysis then report",
        )

        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        context = ConversationContext()
        executor = ToolExecutor(auto_approve=True)
        loop = AgenticLoop(context, executor)

        hint = loop._try_decompose("Berserk 분석하고 리포트 만들어줘")

        assert hint is not None
        assert "Goal Decomposition Plan" in hint
        assert "step_1" in hint
        assert "step_2" in hint
        assert "analyze_ip" in hint
        assert "generate_report" in hint
        assert "depends on: step_1" in hint

    def test_simple_request_no_hint(self) -> None:
        """Simple requests should not produce a decomposition hint."""
        from core.agent.conversation import ConversationContext
        from core.agent.loop import AgenticLoop
        from core.agent.tool_executor import ToolExecutor

        context = ConversationContext()
        executor = ToolExecutor(auto_approve=True)
        loop = AgenticLoop(context, executor)

        hint = loop._try_decompose("Berserk 분석해줘")
        assert hint is None


# ---------------------------------------------------------------------------
# Execution order with partial failures
# ---------------------------------------------------------------------------


class TestPartialFailure:
    """Tests for dependency-based execution when some goals fail."""

    def test_failure_propagation_in_task_graph(self) -> None:
        """When a goal fails, dependent goals should be skipped."""
        decomposer = GoalDecomposer()
        result = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(id="s1", description="Search", tool_name="search_ips"),
                SubGoal(
                    id="s2",
                    description="Analyze",
                    tool_name="analyze_ip",
                    depends_on=["s1"],
                ),
                SubGoal(
                    id="s3",
                    description="Report",
                    tool_name="generate_report",
                    depends_on=["s2"],
                ),
            ],
        )

        graph: TaskGraph = decomposer.build_task_graph_from_goals(result)

        # Simulate s1 failure
        graph.mark_running("s1")
        graph.mark_failed("s1", error="Search failed")

        # Propagate failure
        skipped = graph.propagate_failure("s1")
        assert "s2" in skipped
        assert "s3" in skipped

        # No ready tasks should remain
        ready = graph.get_ready_tasks()
        assert len(ready) == 0

    def test_partial_success_in_parallel(self) -> None:
        """When one parallel branch fails, the other should still complete."""
        decomposer = GoalDecomposer()
        result = DecompositionResult(
            is_compound=True,
            goals=[
                SubGoal(id="s1", description="Analyze A", tool_name="analyze_ip"),
                SubGoal(id="s2", description="Analyze B", tool_name="analyze_ip"),
                SubGoal(
                    id="s3",
                    description="Compare",
                    tool_name="compare_ips",
                    depends_on=["s1", "s2"],
                ),
            ],
        )

        graph: TaskGraph = decomposer.build_task_graph_from_goals(result)

        # s1 succeeds, s2 fails
        graph.mark_running("s1")
        graph.mark_completed("s1", result={"tier": "S"})
        graph.mark_running("s2")
        graph.mark_failed("s2", error="Not found")

        # s3 depends on both — should be blocked
        assert graph.is_blocked("s3") is True

        # Propagate failure
        skipped = graph.propagate_failure("s2")
        assert "s3" in skipped
