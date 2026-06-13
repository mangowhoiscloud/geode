"""Tool Registry — manages tool registration and lookup.

Provides to_anthropic_tools() for converting registered tools
to Anthropic API tool_use format. Supports PolicyChain for
mode-based tool access control.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

from core.tools.base import Tool

if TYPE_CHECKING:
    from core.tools.policy import PolicyChain

log = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for GEODE tools with optional policy-based filtering.

    Usage:
        registry = ToolRegistry()
        registry.register(MemorySearchTool())
        tools = registry.to_anthropic_tools()  # All tools

        # With policy filtering:
        from core.tools.policy import PolicyChain, ToolPolicy
        chain = PolicyChain()
        chain.add_policy(ToolPolicy(name="block_notify", mode="dry_run",
                                     denied_tools={"send_notification"}))
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

    async def aexecute(
        self,
        name: str,
        *,
        policy: PolicyChain | None = None,
        mode: str = "full_pipeline",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a tool by name through the async-native path when available."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found in registry")
        if policy is not None and not policy.is_allowed(name, mode=mode):
            raise PermissionError(f"Tool '{name}' blocked by policy in mode '{mode}'")

        async_execute = getattr(tool, "aexecute", None)
        if callable(async_execute):
            raw = async_execute(**kwargs)
            if inspect.isawaitable(raw):
                result = await raw
            else:
                result = raw
            return result if isinstance(result, dict) else {"result": result}

        raise TypeError(f"Tool '{name}' must implement aexecute() for registry execution")

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
