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
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "tool_search"

    @property
    def description(self) -> str:
        return (
            "Search GEODE analysis tools by keyword. "
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

        if not matches:
            # Return all tools as summary if no match
            matches = [
                {"name": t.name, "description": t.description[:80]}
                for t in self._registry._tools.values()
                if t.name != "tool_search"
            ]
            return {"matched": False, "available_tools": matches}

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

    def to_anthropic_tools_with_defer(
        self,
        *,
        policy: PolicyChain | None = None,
        mode: str = "full_pipeline",
        defer_threshold: int = 5,
    ) -> list[dict[str, Any]]:
        """Return Anthropic tool definitions with defer_loading for large tool sets.

        When tool count exceeds defer_threshold, adds tool_search meta-tool
        and marks all other tools with defer_loading=True. This reduces
        context token usage by ~85%.

        Below threshold, returns standard tool definitions (no defer).
        """
        tools = self.to_anthropic_tools(policy=policy, mode=mode)

        if len(tools) <= defer_threshold:
            return tools

        # Build category descriptions for tool_search
        categories: set[str] = set()
        for tool in tools:
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
            else:
                categories.add("other")

        category_str = ", ".join(sorted(categories))

        # Mark all tools as deferred
        deferred: list[dict[str, Any]] = []
        for tool in tools:
            tool_copy = dict(tool)
            tool_copy["defer_loading"] = True
            deferred.append(tool_copy)

        # Insert tool_search meta-tool at the beginning
        tool_search: dict[str, Any] = {
            "name": "tool_search",
            "description": (
                f"Search GEODE analysis tools. Categories: {category_str}. "
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

        return [tool_search, *deferred]

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

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
