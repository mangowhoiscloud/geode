"""Tests for tool category and cost_tier metadata (1-A).

Validates that:
- All tools in definitions.json have category and cost_tier fields
- category and cost_tier values are from the allowed set
- ToolRegistry.get_tools_by_category() returns correct tools
- ToolRegistry.get_tools_by_cost_tier() returns correct tools
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.tools.base import VALID_CATEGORIES, VALID_COST_TIERS, Tool
from core.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixture: definitions.json path
# ---------------------------------------------------------------------------

_DEFINITIONS_PATH = Path(__file__).resolve().parent.parent / "core" / "tools" / "definitions.json"


def _load_definitions() -> list[dict[str, Any]]:
    with open(_DEFINITIONS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helper tools for registry tests
# ---------------------------------------------------------------------------


class _TaggedTool:
    """Minimal Tool with category and cost_tier."""

    def __init__(
        self,
        name: str,
        *,
        category: str = "discovery",
        cost_tier: str = "free",
    ) -> None:
        self._name = name
        self.category = category
        self.cost_tier = cost_tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Tagged tool {self._name}"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"result": "ok"}


class _UntaggedTool:
    """Minimal Tool WITHOUT category / cost_tier."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Untagged tool {self._name}"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"result": "ok"}


# ===================================================================
# definitions.json validation
# ===================================================================


class TestDefinitionsJsonMetadata:
    """Every entry in definitions.json must have category + cost_tier."""

    def test_all_tools_have_category(self) -> None:
        for tool in _load_definitions():
            assert "category" in tool, f"Tool '{tool['name']}' missing 'category' field"

    def test_all_tools_have_cost_tier(self) -> None:
        for tool in _load_definitions():
            assert "cost_tier" in tool, f"Tool '{tool['name']}' missing 'cost_tier' field"

    def test_categories_are_valid(self) -> None:
        for tool in _load_definitions():
            assert tool["category"] in VALID_CATEGORIES, (
                f"Tool '{tool['name']}' has invalid category '{tool['category']}'"
            )

    def test_cost_tiers_are_valid(self) -> None:
        for tool in _load_definitions():
            assert tool["cost_tier"] in VALID_COST_TIERS, (
                f"Tool '{tool['name']}' has invalid cost_tier '{tool['cost_tier']}'"
            )

    def test_every_category_has_at_least_one_tool(self) -> None:
        used = {t["category"] for t in _load_definitions()}
        assert used == VALID_CATEGORIES

    def test_every_cost_tier_has_at_least_one_tool(self) -> None:
        used = {t["cost_tier"] for t in _load_definitions()}
        assert used == VALID_COST_TIERS


# ===================================================================
# Specific category membership (from task spec)
# ===================================================================


class TestCategoryMembership:
    """Verify the category mapping matches the task specification."""

    def _category_map(self) -> dict[str, str]:
        return {t["name"]: t["category"] for t in _load_definitions()}

    def test_discovery_tools(self) -> None:
        m = self._category_map()
        for name in ("list_ips", "search_ips", "check_status", "show_help"):
            assert m.get(name) == "discovery", f"{name} should be discovery"

    def test_analysis_tools(self) -> None:
        m = self._category_map()
        for name in ("analyze_ip", "compare_ips", "batch_analyze", "generate_report"):
            assert m.get(name) == "analysis", f"{name} should be analysis"

    def test_memory_tools(self) -> None:
        m = self._category_map()
        for name in ("memory_search", "memory_save", "note_read", "note_save", "manage_rule"):
            assert m.get(name) == "memory", f"{name} should be memory"

    def test_planning_tools(self) -> None:
        m = self._category_map()
        for name in ("create_plan", "approve_plan", "delegate_task"):
            assert m.get(name) == "planning", f"{name} should be planning"

    def test_external_tools(self) -> None:
        m = self._category_map()
        for name in ("web_fetch", "general_web_search"):
            assert m.get(name) == "external", f"{name} should be external"

    def test_model_tools(self) -> None:
        m = self._category_map()
        for name in ("switch_model", "set_api_key", "manage_auth"):
            assert m.get(name) == "model", f"{name} should be model"

    def test_data_tools(self) -> None:
        m = self._category_map()
        assert m.get("generate_data") == "data"

    def test_scheduling_tools(self) -> None:
        m = self._category_map()
        for name in ("schedule_job", "trigger_event"):
            assert m.get(name) == "scheduling", f"{name} should be scheduling"


class TestCostTierMembership:
    """Verify the cost_tier mapping matches the task specification."""

    def _tier_map(self) -> dict[str, str]:
        return {t["name"]: t["cost_tier"] for t in _load_definitions()}

    def test_free_tools(self) -> None:
        m = self._tier_map()
        for name in (
            "list_ips",
            "search_ips",
            "check_status",
            "show_help",
            "memory_search",
            "note_read",
            "manage_rule",
            "switch_model",
        ):
            assert m.get(name) == "free", f"{name} should be free"

    def test_cheap_tools(self) -> None:
        m = self._tier_map()
        for name in (
            "web_fetch",
            "general_web_search",
            "memory_save",
            "note_save",
            "set_api_key",
            "manage_auth",
            "create_plan",
            "approve_plan",
            "generate_data",
            "schedule_job",
            "trigger_event",
            "delegate_task",
        ):
            assert m.get(name) == "cheap", f"{name} should be cheap"

    def test_expensive_tools(self) -> None:
        m = self._tier_map()
        for name in ("analyze_ip", "compare_ips", "batch_analyze", "generate_report"):
            assert m.get(name) == "expensive", f"{name} should be expensive"


# ===================================================================
# ToolRegistry.get_tools_by_category / get_tools_by_cost_tier
# ===================================================================


class TestRegistryGetByCategory:
    """Test ToolRegistry.get_tools_by_category()."""

    def _build_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(_TaggedTool("a", category="discovery", cost_tier="free"))
        reg.register(_TaggedTool("b", category="discovery", cost_tier="cheap"))
        reg.register(_TaggedTool("c", category="analysis", cost_tier="expensive"))
        reg.register(_UntaggedTool("d"))
        return reg

    def test_returns_matching_category(self) -> None:
        reg = self._build_registry()
        result = reg.get_tools_by_category("discovery")
        names = {t.name for t in result}
        assert names == {"a", "b"}

    def test_returns_empty_for_unknown_category(self) -> None:
        reg = self._build_registry()
        assert reg.get_tools_by_category("nonexistent") == []

    def test_skips_untagged_tools(self) -> None:
        reg = self._build_registry()
        # "d" has no category — should not appear in any result
        all_returned = set()
        for cat in VALID_CATEGORIES:
            all_returned.update(t.name for t in reg.get_tools_by_category(cat))
        assert "d" not in all_returned

    def test_single_match(self) -> None:
        reg = self._build_registry()
        result = reg.get_tools_by_category("analysis")
        assert len(result) == 1
        assert result[0].name == "c"


class TestRegistryGetByCostTier:
    """Test ToolRegistry.get_tools_by_cost_tier()."""

    def _build_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(_TaggedTool("x", category="discovery", cost_tier="free"))
        reg.register(_TaggedTool("y", category="analysis", cost_tier="expensive"))
        reg.register(_TaggedTool("z", category="external", cost_tier="cheap"))
        reg.register(_UntaggedTool("w"))
        return reg

    def test_returns_matching_tier(self) -> None:
        reg = self._build_registry()
        result = reg.get_tools_by_cost_tier("free")
        names = {t.name for t in result}
        assert names == {"x"}

    def test_expensive_tier(self) -> None:
        reg = self._build_registry()
        result = reg.get_tools_by_cost_tier("expensive")
        assert len(result) == 1
        assert result[0].name == "y"

    def test_returns_empty_for_unknown_tier(self) -> None:
        reg = self._build_registry()
        assert reg.get_tools_by_cost_tier("nonexistent") == []

    def test_skips_untagged_tools(self) -> None:
        reg = self._build_registry()
        all_returned = set()
        for tier in VALID_COST_TIERS:
            all_returned.update(t.name for t in reg.get_tools_by_cost_tier(tier))
        assert "w" not in all_returned


class TestTaggedToolSatisfiesProtocol:
    """Tagged tools still satisfy the Tool protocol."""

    def test_tagged_tool_is_tool(self) -> None:
        tool = _TaggedTool("t", category="analysis", cost_tier="expensive")
        assert isinstance(tool, Tool)

    def test_untagged_tool_is_tool(self) -> None:
        tool = _UntaggedTool("u")
        assert isinstance(tool, Tool)
