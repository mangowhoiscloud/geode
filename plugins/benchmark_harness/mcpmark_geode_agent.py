"""GEODE adapter for MCPMark.

This module is public-safe and can be imported from an upstream MCPMark checkout.
It intentionally depends on MCPMark only at runtime so GEODE can ship the adapter
without vendoring the benchmark repository.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import time
from dataclasses import dataclass
from typing import Any


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


@dataclass
class MCPMarkGeodeTool:
    mcp_server: Any
    schema: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.schema.get("name", ""))

    @property
    def description(self) -> str:
        return str(self.schema.get("description", "") or self.name)

    @property
    def parameters(self) -> dict[str, Any]:
        raw = self.schema.get("inputSchema")
        return raw if isinstance(raw, dict) else {"type": "object", "properties": {}}

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("_tool_context", None)
        result = await asyncio.wait_for(self.mcp_server.call_tool(self.name, kwargs), timeout=120)
        return {"result": _jsonish(result)}


def _build_loop(
    *,
    tools: list[MCPMarkGeodeTool],
    instruction: str,
    model: str,
    provider: str,
    source: str,
    effort: str,
    timeout: int,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.tools.registry import ToolRegistry

    registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tool in tools:
        registry.register(tool)
        handlers[tool.name] = tool.aexecute

    executor = ToolExecutor(action_handlers=handlers, auto_approve=True, hitl_level=0)
    return AgenticLoop(
        ConversationContext(max_turns=200),
        executor,
        model=model,
        provider=provider,
        source=source,
        effort=effort,
        max_tokens=32768,
        max_rounds=0,
        time_budget_s=float(timeout),
        tool_registry=registry,
        allowed_tool_names=set(handlers),
        system_prompt_override=(
            "You are GEODE running inside MCPMark. Complete the benchmark task "
            "using only the provided MCP tools. Do not invent tool results. "
            "When finished, provide a concise final answer."
        ),
        quiet=True,
        enable_goal_decomposition=False,
    )


def _route_from_model(model_name: str) -> tuple[str, str, str]:
    normalized = model_name.removeprefix("geode-")
    if normalized.startswith("gpt-"):
        return normalized, "openai", "subscription"
    if normalized.startswith("claude-"):
        return normalized, "anthropic", "subscription"
    if normalized.startswith("glm-"):
        return normalized, "zhipuai", "api_key"
    return normalized, "openai", "subscription"


def _usage_dict(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    to_dict = getattr(usage, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, dict):
            return raw
    return {}


BaseMCPAgent: Any
try:
    BaseMCPAgent = importlib.import_module("src.agents.base_agent").BaseMCPAgent
except Exception:
    BaseMCPAgent = object


class GeodeMCPMarkAgent(BaseMCPAgent):
    """MCPMark agent that routes model calls through GEODE."""

    async def execute(
        self, instruction: str, tool_call_log_file: str | None = None
    ) -> dict[str, Any]:
        start_time = time.time()
        self._reset_progress()
        self._refresh_service_config()
        model, provider, source = _route_from_model(self.litellm_input_model_name)

        try:
            mcp_server = await self._create_mcp_server()
            async with mcp_server:
                tool_schemas = await mcp_server.list_tools()
                tools = [
                    MCPMarkGeodeTool(mcp_server=mcp_server, schema=schema)
                    for schema in tool_schemas
                ]
                loop = _build_loop(
                    tools=tools,
                    instruction=instruction,
                    model=model,
                    provider=provider,
                    source=source,
                    effort=str(self.reasoning_effort or "default"),
                    timeout=int(self.timeout),
                )
                result = await loop.arun(instruction)

            token_usage = _usage_dict(result)
            execution_time = time.time() - start_time
            self.usage_tracker.update(
                success=True,
                token_usage=token_usage,
                turn_count=getattr(result, "rounds", 0),
                execution_time=execution_time,
            )
            if tool_call_log_file:
                with open(tool_call_log_file, "w", encoding="utf-8") as handle:
                    json.dump(
                        getattr(result, "tool_calls", []) or [],
                        handle,
                        ensure_ascii=False,
                        indent=2,
                    )
            return {
                "success": True,
                "output": getattr(result, "text", "") or "Task completed",
                "token_usage": token_usage,
                "turn_count": getattr(result, "rounds", 0),
                "execution_time": execution_time,
                "litellm_run_model_name": f"geode/{model}",
            }
        except Exception as exc:
            execution_time = time.time() - start_time
            self.usage_tracker.update(
                success=False,
                token_usage={},
                turn_count=0,
                execution_time=execution_time,
            )
            return {
                "success": False,
                "output": [],
                "token_usage": {},
                "turn_count": 0,
                "execution_time": execution_time,
                "error": f"GEODE MCPMark execution failed: {exc}",
                "litellm_run_model_name": f"geode/{model}",
            }


def register_mcpmark_agent(registry: dict[str, Any]) -> None:
    registry["geode"] = GeodeMCPMarkAgent
