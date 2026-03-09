"""Tool Registry — manages tool registration and lookup.

Provides to_anthropic_tools() for converting registered tools
to Anthropic API tool_use format. Supports PolicyChain for
mode-based tool access control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from geode.tools.base import Tool

if TYPE_CHECKING:
    from geode.tools.policy import PolicyChain


class ToolRegistry:
    """Registry for GEODE tools with optional policy-based filtering.

    Usage:
        registry = ToolRegistry()
        registry.register(RunAnalystTool())
        tools = registry.to_anthropic_tools()  # All tools

        # With policy filtering:
        from geode.tools.policy import PolicyChain, ToolPolicy
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
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in self._tools.values()
            if tool.name in allowed_names
        ]

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
