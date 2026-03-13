"""Tests for tool-augmented node paths (R-2: Synthesizer + BiasBuster)."""

from __future__ import annotations

from unittest.mock import patch

from core.infrastructure.ports.tool_port import set_tool_executor
from core.llm.client import ToolCallRecord, ToolUseResult
from core.nodes.synthesizer import _build_tool_augmented_synthesis, synthesizer_node
from core.state import AnalysisResult, EvaluatorResult, GeodeState


def _make_state(*, dry_run: bool = False, with_tools: bool = False) -> GeodeState:
    """Build a minimal GeodeState for synthesizer testing."""
    state: GeodeState = {  # type: ignore[typeddict-item]
        "ip_name": "Berserk",
        "pipeline_mode": "full",
        "dry_run": dry_run,
        "verbose": False,
        "analyses": [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.2,
                key_finding="Strong combat potential",
                reasoning="Dark Souls-like",
                evidence=["evidence1"],
                confidence=0.85,
            ),
        ],
        "evaluations": {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 2.0, "f_score": 3.0},
                composite_score=65.0,
                rationale="Undermarketed",
            ),
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={"a_score": 4.0},
                composite_score=72.0,
                rationale="High quality",
            ),
        },
        "monolake": {"last_game_year": 0, "active_game_count": 0, "metacritic_score": 0},
        "signals": {"youtube_views": 5000000},
        "tier": "A",
        "final_score": 72.0,
    }
    if with_tools:
        state["_tool_definitions"] = [  # type: ignore[typeddict-item]
            {"name": "memory_search", "description": "Search memory", "input_schema": {}}
        ]
        # Executor injected via contextvar, NOT in state (msgpack can't serialize functions)
        set_tool_executor(lambda name, **kw: {"result": "mock"})
    return state


class TestToolAugmentedSynthesis:
    def test_returns_none_without_tool_defs(self):
        state = _make_state()
        tool_fn = lambda: None  # noqa: E731
        result = _build_tool_augmented_synthesis(
            state,
            "undermarketed",
            "marketing_boost",
            tool_fn,
        )
        assert result is None

    def test_returns_synthesis_on_success(self):
        state = _make_state(with_tools=True)

        mock_result = ToolUseResult(
            text="Berserk는 다크 판타지 IP로서 높은 게임화 가치를 보유합니다.",
            tool_calls=[
                ToolCallRecord(
                    tool_name="memory_search",
                    tool_input={"query": "berserk"},
                    tool_result={"result": "past analysis"},
                    duration_ms=50.0,
                )
            ],
            usage=[],
            rounds=2,
        )

        def mock_tool_fn(system, user, *, tools, tool_executor, max_tool_rounds=5):
            return mock_result

        result = _build_tool_augmented_synthesis(
            state, "undermarketed", "marketing_boost", mock_tool_fn
        )
        assert result is not None
        assert result.undervaluation_cause == "undermarketed"
        assert "Berserk" in result.value_narrative

    def test_returns_none_on_failure(self):
        state = _make_state(with_tools=True)

        def failing_tool_fn(system, user, *, tools, tool_executor, max_tool_rounds=5):
            raise RuntimeError("API error")

        result = _build_tool_augmented_synthesis(
            state, "undermarketed", "marketing_boost", failing_tool_fn
        )
        assert result is None


class TestSynthesizerNodeToolPath:
    def test_dry_run_skips_tools(self):
        state = _make_state(dry_run=True, with_tools=True)
        result = synthesizer_node(state)
        assert "synthesis" in result
        assert result["synthesis"].undervaluation_cause == "undermarketed"

    def test_no_tool_callable_falls_back(self):
        """When get_llm_tool() raises RuntimeError, falls back to standard path."""
        state = _make_state(with_tools=True)

        # Mock both get_llm_tool (raises) and standard path
        with (
            patch("core.nodes.synthesizer.get_llm_tool", side_effect=RuntimeError("not injected")),
            patch("core.nodes.synthesizer._build_llm_synthesis") as mock_std,
        ):
            from core.state import SynthesisResult

            mock_std.return_value = SynthesisResult(
                undervaluation_cause="undermarketed",
                action_type="marketing_boost",
                value_narrative="Standard path",
                target_segment="Test",
            )
            result = synthesizer_node(state)
            assert result["synthesis"].value_narrative == "Standard path"
            mock_std.assert_called_once()
