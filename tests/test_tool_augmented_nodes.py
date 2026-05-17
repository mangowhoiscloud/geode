"""Tests for tool-augmented node paths (R-2: Synthesizer + BiasBuster)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from core.llm.client import ToolCallRecord, ToolUseResult
from core.state import AnalysisResult, EvaluatorResult, GeodeState
from core.tools.registry import set_async_tool_executor
from plugins.game_ip.nodes.synthesizer import (
    _build_tool_augmented_synthesis as _abuild_tool_augmented_synthesis,
)
from plugins.game_ip.nodes.synthesizer import synthesizer_node as _synthesizer_node


def _build_tool_augmented_synthesis(*args, **kwargs):
    return asyncio.run(_abuild_tool_augmented_synthesis(*args, **kwargs))


def synthesizer_node(state: GeodeState) -> dict[str, Any]:
    return asyncio.run(_synthesizer_node(state))


def _make_state(*, dry_run: bool = False, with_tools: bool = False) -> GeodeState:
    """Build a minimal GeodeState for synthesizer testing."""
    state: GeodeState = {
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
        state["_tool_definitions"] = [  # type: ignore[typeddict-unknown-key]
            {"name": "memory_search", "description": "Search memory", "input_schema": {}}
        ]
        # Executor injected via contextvar, NOT in state (msgpack can't serialize functions)
        async def _mock_executor(name: str, **kw: Any) -> dict[str, Any]:
            return {"result": "mock", "tool": name}

        set_async_tool_executor(_mock_executor)
    return state


class TestToolAugmentedSynthesis:
    def test_returns_none_without_tool_defs(self) -> None:
        state = _make_state()
        result = _build_tool_augmented_synthesis(state, "undermarketed", "marketing_boost")
        assert result is None

    def test_returns_synthesis_on_success(self) -> None:
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

        async def mock_tool_fn(*args: object, **kwargs: object) -> ToolUseResult:
            return mock_result

        with patch("plugins.game_ip.nodes.synthesizer.call_llm_with_tools_async", mock_tool_fn):
            result = _build_tool_augmented_synthesis(state, "undermarketed", "marketing_boost")
        assert result is not None
        assert result.undervaluation_cause == "undermarketed"
        assert "Berserk" in result.value_narrative

    def test_returns_none_on_failure(self) -> None:
        state = _make_state(with_tools=True)

        async def failing_tool_fn(*args: object, **kwargs: object) -> ToolUseResult:
            raise RuntimeError("API error")

        with patch("plugins.game_ip.nodes.synthesizer.call_llm_with_tools_async", failing_tool_fn):
            result = _build_tool_augmented_synthesis(state, "undermarketed", "marketing_boost")
        assert result is None


class TestSynthesizerNodeToolPath:
    def test_dry_run_skips_tools(self) -> None:
        state = _make_state(dry_run=True, with_tools=True)
        result = synthesizer_node(state)
        assert "synthesis" in result
        assert result["synthesis"].undervaluation_cause == "undermarketed"

    def test_no_async_tool_executor_falls_back(self) -> None:
        """When async tool executor is absent, falls back to standard path."""
        state = _make_state(with_tools=True)
        set_async_tool_executor(None)

        with patch("plugins.game_ip.nodes.synthesizer._build_llm_synthesis") as mock_std:
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
