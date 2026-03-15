"""Tests for tool_search + defer_loading in ToolRegistry.

Tests unified deferred loading for native + MCP tools.
"""

from __future__ import annotations

from typing import Any

from core.tools.policy import PolicyChain, ToolPolicy
from core.tools.registry import ToolRegistry, ToolSearchTool

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


def _make_mcp_tool(name: str, description: str = "mcp desc") -> dict[str, Any]:
    """Create a minimal MCP tool dict for testing."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        },
        "_mcp_server": "test_server",
    }


# Default threshold is 10
DEFAULT_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Tests — below threshold (no defer)
# ---------------------------------------------------------------------------


class TestBelowThreshold:
    """When tool count <= defer_threshold, return standard format."""

    def test_returns_standard_format(self) -> None:
        reg = _make_registry("a", "b", "c")
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        assert len(result) == 3
        for tool in result:
            assert "defer_loading" not in tool

    def test_exact_threshold_no_defer(self) -> None:
        names = [f"t{i}" for i in range(DEFAULT_THRESHOLD)]
        reg = _make_registry(*names)
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        assert len(result) == DEFAULT_THRESHOLD
        for tool in result:
            assert "defer_loading" not in tool

    def test_empty_registry(self) -> None:
        reg = ToolRegistry()
        result = reg.to_anthropic_tools_with_defer()
        assert result == []

    def test_backward_compat_few_tools_no_mcp(self) -> None:
        """With <=10 tools and no MCP, all are loaded directly."""
        reg = _make_registry("a", "b", "c", "d", "e")
        result = reg.to_anthropic_tools_with_defer()
        assert len(result) == 5
        for tool in result:
            assert "defer_loading" not in tool


# ---------------------------------------------------------------------------
# Tests — above threshold (defer)
# ---------------------------------------------------------------------------


class TestAboveThreshold:
    """When tool count > defer_threshold, adds tool_search + defer_loading."""

    def _eleven_tools(self) -> ToolRegistry:
        return _make_registry(*[f"t{i}" for i in range(11)])

    def test_tool_search_prepended(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        assert result[0]["name"] == "tool_search"

    def test_total_count_is_original_plus_one(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        # 11 tools (all deferred since none are core) + 1 tool_search = 12
        assert len(result) == 12

    def test_deferred_tools_have_flag(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        # Skip tool_search (index 0), remaining are deferred (no core tools)
        for tool in result[1:]:
            assert tool["defer_loading"] is True

    def test_tool_search_has_no_defer_flag(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        assert "defer_loading" not in result[0]

    def test_tool_search_schema(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        ts = result[0]
        assert ts["name"] == "tool_search"
        assert "input_schema" in ts
        schema = ts["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_tool_search_description_contains_categories(self) -> None:
        result = self._eleven_tools().to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD
        )
        desc = result[0]["description"]
        assert "Categories:" in desc
        # All unknown names -> "other"
        assert "other" in desc


# ---------------------------------------------------------------------------
# Tests — core tools always loaded (never deferred)
# ---------------------------------------------------------------------------


class TestCoreToolsAlwaysLoaded:
    """The 6 core tools are always loaded, never deferred."""

    CORE_TOOLS = [
        "list_ips",
        "search_ips",
        "analyze_ip",
        "memory_search",
        "show_help",
        "general_web_search",
    ]

    def test_core_tools_never_deferred(self) -> None:
        """Core tools should NOT have defer_loading flag."""
        all_names = self.CORE_TOOLS + [f"extra_{i}" for i in range(8)]
        reg = _make_registry(*all_names)
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)

        # tool_search first, then core tools (no defer), then extras (deferred)
        assert result[0]["name"] == "tool_search"

        # Find core tools in result — they should NOT be deferred
        for tool in result:
            if tool["name"] in self.CORE_TOOLS:
                assert "defer_loading" not in tool, (
                    f"Core tool '{tool['name']}' should not be deferred"
                )

    def test_non_core_tools_are_deferred(self) -> None:
        """Non-core tools SHOULD have defer_loading flag."""
        all_names = self.CORE_TOOLS + [f"extra_{i}" for i in range(8)]
        reg = _make_registry(*all_names)
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)

        for tool in result:
            if tool["name"].startswith("extra_"):
                assert tool.get("defer_loading") is True, (
                    f"Non-core tool '{tool['name']}' should be deferred"
                )

    def test_core_tools_count_in_result(self) -> None:
        """All 6 core tools + tool_search + 8 deferred = 15 total."""
        all_names = self.CORE_TOOLS + [f"extra_{i}" for i in range(8)]
        reg = _make_registry(*all_names)
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)

        # 1 (tool_search) + 6 (core) + 8 (deferred) = 15
        assert len(result) == 15

        core_in_result = [t for t in result if t["name"] in self.CORE_TOOLS]
        assert len(core_in_result) == 6


# ---------------------------------------------------------------------------
# Tests — MCP tools integration
# ---------------------------------------------------------------------------


class TestMCPToolsIntegration:
    """MCP tools are merged and included in deferred loading."""

    def test_mcp_tools_merged(self) -> None:
        """MCP tools are included in the combined tool list."""
        reg = _make_registry("a", "b", "c")
        mcp = [_make_mcp_tool("mcp_tool_1"), _make_mcp_tool("mcp_tool_2")]
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD, mcp_tools=mcp)
        # 3 native + 2 MCP = 5, below threshold -> no defer
        assert len(result) == 5
        names = {t["name"] for t in result}
        assert "mcp_tool_1" in names
        assert "mcp_tool_2" in names

    def test_mcp_tools_deferred_above_threshold(self) -> None:
        """MCP tools are deferred when combined count > threshold."""
        native_names = [f"native_{i}" for i in range(9)]
        reg = _make_registry(*native_names)
        mcp = [_make_mcp_tool("mcp_tool_1"), _make_mcp_tool("mcp_tool_2")]
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD, mcp_tools=mcp)
        # 9 native + 2 MCP = 11, above threshold -> deferral activated
        assert result[0]["name"] == "tool_search"
        mcp_in_result = [t for t in result if t["name"].startswith("mcp_")]
        for tool in mcp_in_result:
            assert tool.get("defer_loading") is True

    def test_mcp_tools_dedup(self) -> None:
        """MCP tools with same name as native tools are deduplicated."""
        reg = _make_registry("tool_a", "tool_b")
        mcp = [_make_mcp_tool("tool_a"), _make_mcp_tool("tool_c")]
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD, mcp_tools=mcp)
        # tool_a is deduped -> 3 tools (tool_a, tool_b, tool_c)
        assert len(result) == 3
        names = [t["name"] for t in result]
        assert names.count("tool_a") == 1

    def test_mcp_category_in_description(self) -> None:
        """MCP tools contribute 'mcp' category to tool_search description."""
        native_names = [f"native_{i}" for i in range(9)]
        reg = _make_registry(*native_names)
        mcp = [_make_mcp_tool("mcp_tool_1"), _make_mcp_tool("mcp_tool_2")]
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD, mcp_tools=mcp)
        desc = result[0]["description"]
        assert "mcp" in desc

    def test_mcp_tools_none_is_noop(self) -> None:
        """Passing mcp_tools=None behaves like original (no MCP)."""
        reg = _make_registry("a", "b", "c")
        result = reg.to_anthropic_tools_with_defer(
            defer_threshold=DEFAULT_THRESHOLD, mcp_tools=None
        )
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Tests — ToolSearchTool searches MCP tools
# ---------------------------------------------------------------------------


class TestToolSearchToolMCP:
    """ToolSearchTool.execute() searches both native and MCP tools."""

    def test_search_finds_mcp_tool(self) -> None:
        reg = _make_registry("native_tool")
        search_tool = ToolSearchTool(reg)
        reg.register(search_tool)  # type: ignore[arg-type]
        search_tool.set_mcp_tools([_make_mcp_tool("steam_mcp", "Steam store lookup")])

        result = search_tool.execute(query="steam")
        assert result["matched"] is True
        names = [t["name"] for t in result["tools"]]
        assert "steam_mcp" in names

    def test_search_finds_native_tool(self) -> None:
        reg = _make_registry("analyze_ip")
        search_tool = ToolSearchTool(reg)
        reg.register(search_tool)  # type: ignore[arg-type]
        search_tool.set_mcp_tools([_make_mcp_tool("mcp_tool")])

        result = search_tool.execute(query="analyze")
        assert result["matched"] is True
        names = [t["name"] for t in result["tools"]]
        assert "analyze_ip" in names

    def test_search_returns_both_sources(self) -> None:
        reg = _make_registry("steam_native")
        search_tool = ToolSearchTool(reg)
        reg.register(search_tool)  # type: ignore[arg-type]
        search_tool.set_mcp_tools([_make_mcp_tool("steam_mcp", "Steam MCP tool")])

        result = search_tool.execute(query="steam")
        assert result["matched"] is True
        names = [t["name"] for t in result["tools"]]
        assert "steam_native" in names
        assert "steam_mcp" in names

    def test_no_match_returns_all_including_mcp(self) -> None:
        reg = _make_registry("native_tool")
        search_tool = ToolSearchTool(reg)
        reg.register(search_tool)  # type: ignore[arg-type]
        search_tool.set_mcp_tools([_make_mcp_tool("mcp_tool")])

        result = search_tool.execute(query="zzz_nonexistent")
        assert result["matched"] is False
        names = [t["name"] for t in result["available_tools"]]
        assert "native_tool" in names
        assert "mcp_tool" in names

    def test_mcp_result_has_source_field(self) -> None:
        reg = _make_registry("native_tool")
        search_tool = ToolSearchTool(reg)
        reg.register(search_tool)  # type: ignore[arg-type]
        search_tool.set_mcp_tools([_make_mcp_tool("steam_mcp", "Steam store")])

        result = search_tool.execute(query="steam")
        mcp_matches = [t for t in result["tools"] if t.get("source") == "mcp"]
        assert len(mcp_matches) == 1


# ---------------------------------------------------------------------------
# Tests — category detection
# ---------------------------------------------------------------------------


class TestCategoryDetection:
    """Category strings in tool_search description."""

    def test_analysis_category(self) -> None:
        reg = _make_registry(
            "run_analyst",
            "run_evaluator",
            "psm_calculate",
            *[f"extra{i}" for i in range(8)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        assert "analysis" in desc

    def test_signals_category(self) -> None:
        reg = _make_registry(
            "youtube_search",
            "reddit_sentiment",
            "twitch_stats",
            "steam_info",
            "google_trends",
            *[f"extra{i}" for i in range(6)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        assert "signals" in desc

    def test_data_category(self) -> None:
        reg = _make_registry(
            "query_monolake",
            "cortex_analyst",
            "cortex_search",
            *[f"extra{i}" for i in range(8)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        assert "data" in desc

    def test_memory_category(self) -> None:
        reg = _make_registry(
            "memory_search",
            "memory_get",
            "memory_save",
            *[f"extra{i}" for i in range(8)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        assert "memory" in desc

    def test_output_category(self) -> None:
        reg = _make_registry(
            "generate_report",
            "export_json",
            "send_notification",
            *[f"extra{i}" for i in range(8)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        assert "output" in desc

    def test_multiple_categories(self) -> None:
        reg = _make_registry(
            "run_analyst",
            "youtube_search",
            "memory_search",
            "query_monolake",
            "generate_report",
            *[f"extra{i}" for i in range(6)],
        )
        result = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        desc = result[0]["description"]
        for cat in ("analysis", "signals", "memory", "data", "output", "other"):
            assert cat in desc


# ---------------------------------------------------------------------------
# Tests — policy filtering with defer
# ---------------------------------------------------------------------------


class TestPolicyWithDefer:
    """Policy filtering still works before defer is applied."""

    def test_policy_reduces_below_threshold(self) -> None:
        names = [f"t{i}" for i in range(12)]
        reg = _make_registry(*names)
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="block_most",
                mode="dry_run",
                denied_tools={f"t{i}" for i in range(8)},
                priority=100,
            )
        )
        # After policy: only t8..t11 -> 4 tools, below threshold of 10
        result = reg.to_anthropic_tools_with_defer(
            policy=chain,
            mode="dry_run",
            defer_threshold=DEFAULT_THRESHOLD,
        )
        assert len(result) == 4
        for tool in result:
            assert "defer_loading" not in tool

    def test_policy_still_above_threshold(self) -> None:
        names = [f"t{i}" for i in range(13)]
        reg = _make_registry(*names)
        chain = PolicyChain()
        chain.add_policy(
            ToolPolicy(
                name="block_one",
                mode="dry_run",
                denied_tools={"t0"},
                priority=100,
            )
        )
        # After policy: 12 tools, above threshold of 10
        result = reg.to_anthropic_tools_with_defer(
            policy=chain,
            mode="dry_run",
            defer_threshold=DEFAULT_THRESHOLD,
        )
        assert result[0]["name"] == "tool_search"
        assert len(result) == 13  # 12 deferred + 1 tool_search


# ---------------------------------------------------------------------------
# Tests — original tools are not mutated
# ---------------------------------------------------------------------------


class TestNoMutation:
    """Original tool dicts from to_anthropic_tools are not mutated."""

    def test_original_tools_unchanged(self) -> None:
        names = [f"t{i}" for i in range(12)]
        reg = _make_registry(*names)
        original = reg.to_anthropic_tools()
        _ = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD)
        for tool in original:
            assert "defer_loading" not in tool

    def test_mcp_tools_not_mutated(self) -> None:
        reg = _make_registry(*[f"t{i}" for i in range(9)])
        mcp = [_make_mcp_tool("mcp1"), _make_mcp_tool("mcp2")]
        original_mcp = [dict(t) for t in mcp]
        _ = reg.to_anthropic_tools_with_defer(defer_threshold=DEFAULT_THRESHOLD, mcp_tools=mcp)
        for orig, current in zip(original_mcp, mcp, strict=True):
            assert "defer_loading" not in current
            assert orig == current


# ---------------------------------------------------------------------------
# Tests — threshold default is 10
# ---------------------------------------------------------------------------


class TestDefaultThreshold:
    """Default defer_threshold is 10 (not 5)."""

    def test_nine_tools_no_defer(self) -> None:
        """9 tools: below default threshold of 10, no deferral."""
        reg = _make_registry(*[f"t{i}" for i in range(9)])
        result = reg.to_anthropic_tools_with_defer()
        assert len(result) == 9
        for tool in result:
            assert "defer_loading" not in tool

    def test_ten_tools_no_defer(self) -> None:
        """10 tools: at threshold, no deferral."""
        reg = _make_registry(*[f"t{i}" for i in range(10)])
        result = reg.to_anthropic_tools_with_defer()
        assert len(result) == 10
        for tool in result:
            assert "defer_loading" not in tool

    def test_eleven_tools_defer_activated(self) -> None:
        """11 tools: above threshold, deferral activated."""
        reg = _make_registry(*[f"t{i}" for i in range(11)])
        result = reg.to_anthropic_tools_with_defer()
        assert result[0]["name"] == "tool_search"
        assert len(result) == 12  # 11 deferred + tool_search

    def test_native_plus_mcp_triggers_defer(self) -> None:
        """8 native + 3 MCP = 11, above threshold."""
        reg = _make_registry(*[f"native_{i}" for i in range(8)])
        mcp = [_make_mcp_tool(f"mcp_{i}") for i in range(3)]
        result = reg.to_anthropic_tools_with_defer(mcp_tools=mcp)
        assert result[0]["name"] == "tool_search"
        assert len(result) == 12  # 11 deferred + tool_search
