"""Tool Registry — manages tool registration and lookup.

Provides to_anthropic_tools() for converting registered tools
to Anthropic API tool_use format. Supports PolicyChain for
mode-based tool access control.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.tools.base import Tool

if TYPE_CHECKING:
    from core.tools.policy import PolicyChain

log = logging.getLogger(__name__)


class ToolSearchTool:
    """Meta-tool that searches registered tools by name/description.

    Used with deferred tool loading: LLM calls tool_search first to discover
    relevant tools, then calls them with full schema knowledge.
    Searches both native (registry) and MCP tools.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._mcp_tools: list[dict[str, Any]] = []

    def set_mcp_tools(self, mcp_tools: list[dict[str, Any]]) -> None:
        """Update MCP tool index for searching."""
        self._mcp_tools = list(mcp_tools)

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Search GEODE native and MCP tools by keyword. "
            "Returns matching tool names and their full schemas. "
            "Use this to discover available tools before calling them."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant tools",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query = kwargs.get("query", "").lower()
        if not query:
            return {"error": "query is required"}

        matches: list[dict[str, Any]] = []

        # Search native (registry) tools
        for tool in self._registry._tools.values():
            if tool.name == "tool_search":
                continue  # Don't return self
            name_match = query in tool.name.lower()
            desc_match = query in tool.description.lower()
            if name_match or desc_match:
                matches.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.parameters,
                    }
                )

        # Search MCP tools
        for mcp_tool in self._mcp_tools:
            tool_name = mcp_tool.get("name", "")
            tool_desc = mcp_tool.get("description", "")
            name_match = query in tool_name.lower()
            desc_match = query in tool_desc.lower()
            if name_match or desc_match:
                matches.append(
                    {
                        "name": tool_name,
                        "description": tool_desc,
                        "input_schema": mcp_tool.get("input_schema", {}),
                        "source": "mcp",
                    }
                )

        if not matches:
            # Return all tools as summary if no match
            all_tools: list[dict[str, Any]] = [
                {"name": t.name, "description": t.description[:80]}
                for t in self._registry._tools.values()
                if t.name != "tool_search"
            ]
            for mcp_tool in self._mcp_tools:
                all_tools.append(
                    {
                        "name": mcp_tool.get("name", ""),
                        "description": mcp_tool.get("description", "")[:80],
                        "source": "mcp",
                    }
                )
            return {"matched": False, "available_tools": all_tools}

        return {"matched": True, "tools": matches}


class ToolRegistry:
    """Registry for GEODE tools with optional policy-based filtering.

    Usage:
        registry = ToolRegistry()
        registry.register(RunAnalystTool())
        tools = registry.to_anthropic_tools()  # All tools

        # With policy filtering:
        from core.tools.policy import PolicyChain, ToolPolicy
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block_llm", mode="dry_run",
                                     denied_tools={"run_analyst"}))
        tools = registry.to_anthropic_tools(policy=chain, mode="dry_run")
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ValueError if name already registered."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name. Returns None if not found."""
        return self._tools.get(name)

    def list_tools(
        self, *, policy: PolicyChain | None = None, mode: str = "full_pipeline"
    ) -> list[str]:
        """List registered tool names, optionally filtered by policy."""
        names = list(self._tools.keys())
        if policy is not None:
            names = policy.filter_tools(names, mode=mode)
        return names

    def to_anthropic_tools(
        self, *, policy: PolicyChain | None = None, mode: str = "full_pipeline"
    ) -> list[dict[str, Any]]:
        """Convert registered tools to Anthropic API format.

        Args:
            policy: Optional PolicyChain for filtering.
            mode: Pipeline mode for policy evaluation.
        """
        allowed_names = self.list_tools(policy=policy, mode=mode)
        result: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if tool.name not in allowed_names:
                continue
            schema = dict(tool.parameters)
            if "additionalProperties" not in schema:
                schema["additionalProperties"] = False
            result.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": schema,
                }
            )
        return result

    # Core tools that are always loaded (never deferred) when deferral activates.
    # These are the most frequently used tools that should be immediately available.
    ALWAYS_LOADED_TOOLS: frozenset[str] = frozenset(
        {
            "list_ips",
            "search_ips",
            "analyze_ip",
            "memory_search",
            "show_help",
            "general_web_search",
        }
    )

    def to_anthropic_tools_with_defer(
        self,
        *,
        policy: PolicyChain | None = None,
        mode: str = "full_pipeline",
        defer_threshold: int = 10,
        mcp_tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return Anthropic tool definitions with defer_loading for large tool sets.

        Merges native (registry) and MCP tools BEFORE applying deferred loading.
        When combined tool count exceeds defer_threshold, adds tool_search
        meta-tool. Core tools (ALWAYS_LOADED_TOOLS) are never deferred.
        The remaining tools are marked with defer_loading=True to reduce
        context token usage by ~85%.

        Below threshold, returns all tool definitions without defer.

        Args:
            policy: Optional PolicyChain for filtering native tools.
            mode: Pipeline mode for policy evaluation.
            defer_threshold: Combined tool count above which deferral activates.
            mcp_tools: Optional MCP tool definitions to merge before deferring.
        """
        native_tools = self.to_anthropic_tools(policy=policy, mode=mode)

        # Merge MCP tools (dedup by name)
        all_tools = list(native_tools)
        if mcp_tools:
            existing_names = {t["name"] for t in all_tools}
            for mcp_tool in mcp_tools:
                if mcp_tool.get("name") not in existing_names:
                    all_tools.append(mcp_tool)
                    existing_names.add(mcp_tool["name"])

        if len(all_tools) <= defer_threshold:
            return all_tools

        # Update ToolSearchTool MCP index if present in registry
        tool_search_tool = self._tools.get("tool_search")
        if tool_search_tool is not None and isinstance(tool_search_tool, ToolSearchTool):
            tool_search_tool.set_mcp_tools(mcp_tools or [])

        # Build category descriptions for tool_search
        categories: set[str] = set()
        for tool in all_tools:
            name = tool.get("name", "")
            if name in ("run_analyst", "run_evaluator", "psm_calculate"):
                categories.add("analysis")
            elif name in ("query_monolake", "cortex_analyst", "cortex_search"):
                categories.add("data")
            elif name in (
                "youtube_search",
                "reddit_sentiment",
                "twitch_stats",
                "steam_info",
                "google_trends",
            ):
                categories.add("signals")
            elif name in ("memory_search", "memory_get", "memory_save"):
                categories.add("memory")
            elif name in ("generate_report", "export_json", "send_notification"):
                categories.add("output")
            elif tool.get("_mcp_server"):
                categories.add("mcp")
            else:
                categories.add("other")

        category_str = ", ".join(sorted(categories))

        # Separate always-loaded (core) tools from deferred tools
        always_loaded: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        for tool in all_tools:
            name = tool.get("name", "")
            if name in self.ALWAYS_LOADED_TOOLS:
                always_loaded.append(tool)
            else:
                tool_copy = dict(tool)
                tool_copy["defer_loading"] = True
                deferred.append(tool_copy)

        # Insert tool_search meta-tool at the beginning
        tool_search: dict[str, Any] = {
            "name": "tool_search",
            "description": (
                f"Search GEODE native and MCP tools. Categories: {category_str}. "
                "Use this to find relevant tools before calling them."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant tools",
                    }
                },
                "required": ["query"],
            },
        }

        return [tool_search, *always_loaded, *deferred]

    def to_openai_tools(
        self, *, policy: PolicyChain | None = None, mode: str = "full_pipeline"
    ) -> list[dict[str, Any]]:
        """Convert registered tools to OpenAI function-calling format.

        Args:
            policy: Optional PolicyChain for filtering.
            mode: Pipeline mode for policy evaluation.
        """
        allowed_names = self.list_tools(policy=policy, mode=mode)
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
            if tool.name in allowed_names
        ]

    def execute(
        self,
        name: str,
        *,
        policy: PolicyChain | None = None,
        mode: str = "full_pipeline",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a tool by name with optional policy check.

        Raises:
            KeyError: If tool not found.
            PermissionError: If tool blocked by policy.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found in registry")
        if policy is not None and not policy.is_allowed(name, mode=mode):
            raise PermissionError(f"Tool '{name}' blocked by policy in mode '{mode}'")
        return tool.execute(**kwargs)

    # ------------------------------------------------------------------
    # Category / cost-tier filtering
    # ------------------------------------------------------------------

    def get_tools_by_category(self, category: str) -> list[Tool]:
        """Return tools that belong to *category*.

        The category is read from the ``category`` attribute on each tool.
        Tools without a ``category`` attribute are silently skipped.
        """
        result: list[Tool] = []
        for tool in self._tools.values():
            tool_category = getattr(tool, "category", None)
            if tool_category == category:
                result.append(tool)
        return result

    def get_tools_by_cost_tier(self, tier: str) -> list[Tool]:
        """Return tools that belong to *tier* (free / cheap / expensive).

        The tier is read from the ``cost_tier`` attribute on each tool.
        Tools without a ``cost_tier`` attribute are silently skipped.
        """
        result: list[Tool] = []
        for tool in self._tools.values():
            tool_tier = getattr(tool, "cost_tier", None)
            if tool_tier == tier:
                result.append(tool)
        return result

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
