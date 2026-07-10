"""GEODE adapter for MCPMark.

This module is public-safe and can be imported from an upstream MCPMark checkout.
It intentionally depends on MCPMark only at runtime so GEODE can ship the adapter
without vendoring the benchmark repository.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
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


def _normalize_tool_arguments(schema: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    parameters = schema.get("inputSchema")
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    if "path" in properties and "path" not in kwargs and "file_path" in kwargs:
        kwargs["path"] = kwargs.pop("file_path")
    if "start_cursor" in properties and "start_cursor" in kwargs:
        cursor = kwargs["start_cursor"]
        if cursor is None or cursor == 0 or str(cursor).strip().lower() in {
            "",
            "none",
            "null",
            "undefined",
        }:
            kwargs.pop("start_cursor", None)
    return kwargs


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
        kwargs = _normalize_tool_arguments(self.schema, kwargs)
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
    from core.llm.adapters.registry import bootstrap_builtins
    from core.tools.registry import ToolRegistry

    bootstrap_builtins()

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
            "Agent: GEODE running inside MCPMark. Complete the benchmark task "
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


def _github_repo_visibility() -> str:
    visibility = os.getenv("GEODE_MCPMARK_GITHUB_REPO_VISIBILITY", "private").strip().lower()
    if visibility in {"public", "private"}:
        return visibility
    return "private"


def _patch_mcpmark_github_visibility() -> None:
    """Allow GEODE runs to opt into public transient GitHub repos.

    MCPMark intentionally creates most GitHub fixtures as private repos. GEODE keeps
    that default, but public benchmark runs are useful when a token or account is set
    up like an ordinary Codex workflow. The patch converts the repo after MCPMark has
    imported history/issues/PRs and registered cleanup, preserving upstream behavior
    unless GEODE_MCPMARK_GITHUB_REPO_VISIBILITY=public is set.
    """

    if _github_repo_visibility() != "public":
        return

    try:
        module = importlib.import_module("src.mcp_services.github.github_state_manager")
        manager_cls = module.GitHubStateManager
    except Exception:
        return

    if getattr(manager_cls, "_geode_public_visibility_patched", False):
        return

    original_create_initial_state = manager_cls._create_initial_state

    def create_initial_state_public(self: Any, task: Any) -> Any:
        state_info = original_create_initial_state(self, task)
        if state_info is None:
            return state_info

        metadata = getattr(state_info, "metadata", None)
        if not isinstance(metadata, dict):
            return state_info

        owner = metadata.get("owner")
        repo_name = metadata.get("repo_name")
        if not owner or not repo_name:
            return state_info

        response = self._request_with_retry(
            "PATCH",
            f"https://api.github.com/repos/{owner}/{repo_name}",
            json={"private": False},
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to make GitHub MCPMark repo public: {response.status_code} {response.text}"
            )

        metadata["visibility"] = "public"
        return state_info

    manager_cls._create_initial_state = create_initial_state_public
    manager_cls._geode_public_visibility_patched = True


BaseMCPAgent: Any
try:
    BaseMCPAgent = importlib.import_module("src.agents.base_agent").BaseMCPAgent
except Exception:
    BaseMCPAgent = object


class GeodeMCPMarkAgent(BaseMCPAgent):
    """MCPMark agent that routes model calls through GEODE."""

    def _create_stdio_server(self) -> Any:
        if self.mcp_service == "github":
            github_token = self.service_config.get("github_token")
            if not github_token:
                raise ValueError("GitHub token required")
            mcp_module = importlib.import_module("src.agents.mcp")
            return mcp_module.MCPStdioServer(
                command="docker",
                args=[
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    "GITHUB_PERSONAL_ACCESS_TOKEN",
                    "ghcr.io/github/github-mcp-server:v0.15.0",
                ],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_token},
            )

        if self.mcp_service == "postgres":
            host = self.service_config.get("host", "localhost")
            port = self.service_config.get("port", 5432)
            username = self.service_config.get("username")
            password = self.service_config.get("password")
            database = self.service_config.get("current_database") or self.service_config.get(
                "database"
            )
            if not all([username, password, database]):
                raise ValueError("PostgreSQL requires username, password, and database")
            database_url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
            mcp_module = importlib.import_module("src.agents.mcp")
            return mcp_module.MCPStdioServer(
                command="pipx",
                args=[
                    "run",
                    "--python",
                    sys.executable,
                    "postgres-mcp==0.3.0",
                    "--access-mode=unrestricted",
                ],
                env={"DATABASE_URI": database_url},
            )

        return super()._create_stdio_server()

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
    _patch_mcpmark_github_visibility()
    registry["geode"] = GeodeMCPMarkAgent
