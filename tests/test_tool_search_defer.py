"""Tests for tool_search + defer_loading in ToolRegistry."""

from __future__ import annotations

from typing import Any

from geode.tools.policy import PolicyChain, ToolPolicy
from geode.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal Tool implementation for testing."""

    def __init__(self, name: str, description: str = "desc") -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"result": "ok"}


def _make_registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(_FakeTool(n))
    return reg


# ---------------------------------------------------------------------------
# Tests — below threshold (no defer)
# ---------------------------------------------------------------------------


class TestBelowThreshold:
    """When tool count <= defer_threshold, return standard format."""

    def test_returns_standard_format(self) -> None:
        reg = _make_registry("a", "b", "c")
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        assert len(result) == 3
        for tool in result:
            assert "defer_loading" not in tool

    def test_exact_threshold_no_defer(self) -> None:
        reg = _make_registry("a", "b", "c", "d", "e")
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        assert len(result) == 5
        for tool in result:
            assert "defer_loading" not in tool

    def test_empty_registry(self) -> None:
        reg = ToolRegistry()
        result = reg.to_anthropic_tools_with_defer()
        assert result == []


# ---------------------------------------------------------------------------
# Tests — above threshold (defer)
# ---------------------------------------------------------------------------


class TestAboveThreshold:
    """When tool count > defer_threshold, adds tool_search + defer_loading."""

    def _six_tools(self) -> ToolRegistry:
        return _make_registry("t1", "t2", "t3", "t4", "t5", "t6")

    def test_tool_search_prepended(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        assert result[0]["name"] == "tool_search"

    def test_total_count_is_original_plus_one(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        # 6 deferred + 1 tool_search = 7
        assert len(result) == 7

    def test_all_deferred_tools_have_flag(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        for tool in result[1:]:  # skip tool_search
            assert tool["defer_loading"] is True

    def test_tool_search_has_no_defer_flag(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        assert "defer_loading" not in result[0]

    def test_tool_search_schema(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        ts = result[0]
        assert ts["name"] == "tool_search"
        assert "input_schema" in ts
        schema = ts["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_tool_search_description_contains_categories(self) -> None:
        result = self._six_tools().to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "Categories:" in desc
        # All unknown names → "other"
        assert "other" in desc


# ---------------------------------------------------------------------------
# Tests — category detection
# ---------------------------------------------------------------------------


class TestCategoryDetection:
    """Category strings in tool_search description."""

    def test_analysis_category(self) -> None:
        reg = _make_registry(
            "run_analyst", "run_evaluator", "psm_calculate",
            "extra1", "extra2", "extra3",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "analysis" in desc

    def test_signals_category(self) -> None:
        reg = _make_registry(
            "youtube_search", "reddit_sentiment", "twitch_stats",
            "steam_info", "google_trends", "extra",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "signals" in desc

    def test_data_category(self) -> None:
        reg = _make_registry(
            "query_monolake", "cortex_analyst", "cortex_search",
            "e1", "e2", "e3",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "data" in desc

    def test_memory_category(self) -> None:
        reg = _make_registry(
            "memory_search", "memory_get", "memory_save",
            "e1", "e2", "e3",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "memory" in desc

    def test_output_category(self) -> None:
        reg = _make_registry(
            "generate_report", "export_json", "send_notification",
            "e1", "e2", "e3",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        assert "output" in desc

    def test_multiple_categories(self) -> None:
        reg = _make_registry(
            "run_analyst", "youtube_search", "memory_search",
            "query_monolake", "generate_report", "unknown_tool",
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        desc = result[0]["description"]
        for cat in ("analysis", "signals", "memory", "data", "output", "other"):
            assert cat in desc


# ---------------------------------------------------------------------------
# Tests — policy filtering with defer
# ---------------------------------------------------------------------------


class TestPolicyWithDefer:
    """Policy filtering still works before defer is applied."""

    def test_policy_reduces_below_threshold(self) -> None:
        reg = _make_registry("a", "b", "c", "d", "e", "f")
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="block_most",
                mode="dry_run",
                denied_tools={"a", "b", "c", "d"},
                priority=100,
            )
        )
        # After policy: only e, f → 2 tools, below threshold of 5
        result = reg.to_anthropic_tools_with_defer(
            policy=chain, mode="dry_run", defer_threshold=5,
        )
        assert len(result) == 2
        for tool in result:
            assert "defer_loading" not in tool

    def test_policy_still_above_threshold(self) -> None:
        reg = _make_registry("a", "b", "c", "d", "e", "f", "g", "h")
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="block_one",
                mode="dry_run",
                denied_tools={"a"},
                priority=100,
            )
        )
        # After policy: 7 tools, above threshold of 5
        result = reg.to_anthropic_tools_with_defer(
            policy=chain, mode="dry_run", defer_threshold=5,
        )
        assert result[0]["name"] == "tool_search"
        assert len(result) == 8  # 7 deferred + 1 tool_search


# ---------------------------------------------------------------------------
# Tests — original tools are not mutated
# ---------------------------------------------------------------------------


class TestNoMutation:
    """Original tool dicts from to_anthropic_tools are not mutated."""

    def test_original_tools_unchanged(self) -> None:
        reg = _make_registry("a", "b", "c", "d", "e", "f")
        original = reg.to_anthropic_tools()
        _ = reg.to_anthropic_tools_with_defer(defer_threshold=5)
        for tool in original:
            assert "defer_loading" not in tool
