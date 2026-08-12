"""GEODE and Codex CLI adapters for MCPMark.

This module is public-safe and can be imported from an upstream MCPMark checkout.
It intentionally depends on MCPMark only at runtime so GEODE can ship the adapter
without vendoring the benchmark repository.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.agent.loop.models import is_successful_task_termination

from plugins.benchmark_harness.trajectory_artifacts import (
    export_codex_mcpmark_trajectory,
    export_mcpmark_trajectory,
)

if TYPE_CHECKING:
    from core.hooks.middleware import ToolCallRequest

log = logging.getLogger(__name__)

_CODEX_DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "computer_use",
    "goals",
    "image_generation",
    "multi_agent",
    "shell_tool",
    "skill_search",
    "unified_exec",
    "workspace_dependencies",
)


def _codex_mcp_config(command: str, args: list[str], timeout: int) -> str:
    """Build the inline TOML accepted by ``codex exec -c``."""
    return (
        "{command="
        f"{json.dumps(command)},args={json.dumps(args)},"
        f"startup_timeout_sec=120,tool_timeout_sec={timeout},"
        'required=true,default_tools_approval_mode="approve"'
        "}"
    )


def _summarize_codex_exec(stdout: str) -> dict[str, Any]:
    """Reduce the stable ``codex exec --json`` stream for MCPMark reporting."""
    summary: dict[str, Any] = {
        "thread_id": "",
        "output": "",
        "turn_count": 0,
        "mcp_tool_calls": 0,
        "token_usage": {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        },
        "error": "",
    }
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("type")
        if event_type == "thread.started":
            summary["thread_id"] = str(event.get("thread_id") or "")
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                summary["output"] = str(item.get("text") or "")
            elif item.get("type") == "mcp_tool_call":
                summary["mcp_tool_calls"] += 1
        elif event_type == "turn.completed":
            summary["turn_count"] += 1
            usage = event.get("usage") or {}
            tokens = summary["token_usage"]
            for source, target in (
                ("input_tokens", "input_tokens"),
                ("cached_input_tokens", "cached_input_tokens"),
                ("cache_write_input_tokens", "cache_write_input_tokens"),
                ("output_tokens", "output_tokens"),
                ("reasoning_output_tokens", "reasoning_tokens"),
            ):
                tokens[target] += int(usage.get(source) or 0)
            tokens["total_tokens"] = tokens["input_tokens"] + tokens["output_tokens"]
        elif event_type == "turn.failed":
            summary["error"] = str((event.get("error") or {}).get("message") or "turn failed")
        elif event_type == "error":
            summary["error"] = str(event.get("message") or "codex exec failed")
    return summary


def _codex_model(label: str) -> str:
    return label.removeprefix("codex-").removeprefix("openai/")


def _codex_subscription_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("CODEX_ACCESS_TOKEN", "CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        env.pop(name, None)
    return env


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
        if (
            cursor is None
            or cursor == 0
            or str(cursor).strip().lower()
            in {
                "",
                "none",
                "null",
                "undefined",
            }
        ):
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


@dataclass
class _MCPMarkArgumentNormalizer:
    schemas: dict[str, dict[str, Any]]

    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
        schema = self.schemas.get(request.tool_name)
        if schema is None:
            return request
        arguments = _normalize_tool_arguments(schema, dict(request.arguments))
        return request.with_arguments(arguments)


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
    from core.hooks.middleware import MiddlewareRegistry
    from core.llm.adapters.registry import bootstrap_builtins
    from core.tools.registry import ToolRegistry

    bootstrap_builtins()

    registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tool in tools:
        registry.register(tool)
        handlers[tool.name] = tool.aexecute

    schemas = {tool.name: tool.schema for tool in tools}
    middleware = MiddlewareRegistry()
    middleware.register_tool_request(
        _MCPMarkArgumentNormalizer(schemas),
        name="mcpmark-argument-normalizer",
    )
    executor = ToolExecutor(
        action_handlers=handlers,
        auto_approve=True,
        hitl_level=0,
        middleware_registry=middleware,
        tool_input_schemas={tool.name: tool.parameters for tool in tools},
    )
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
        loop: Any | None = None

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
                task_success = not bool(getattr(result, "error", None)) and (
                    is_successful_task_termination(getattr(result, "termination_reason", ""))
                )
                if not task_success:
                    await loop.amark_session_error()
                else:
                    await loop.amark_session_completed()

            token_usage = _usage_dict(result)
            execution_time = time.time() - start_time
            self.usage_tracker.update(
                success=task_success,
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
                try:
                    trajectory_path = export_mcpmark_trajectory(
                        loop=loop,
                        instruction=instruction,
                        result=result,
                        tool_call_log_file=tool_call_log_file,
                        model=model,
                        provider=provider,
                        source=source,
                    )
                    trajectory_status = "written"
                    trajectory_error = None
                except Exception as exc:
                    log.warning("GEODE MCPMark trajectory sidecar export failed: %s", exc)
                    trajectory_path = None
                    trajectory_status = "failed"
                    trajectory_error = str(exc)
            else:
                trajectory_path = None
                trajectory_status = "not_requested"
                trajectory_error = None
            return {
                "success": task_success,
                "output": getattr(result, "text", "") or "Task completed",
                "token_usage": token_usage,
                "turn_count": getattr(result, "rounds", 0),
                "execution_time": execution_time,
                "litellm_run_model_name": f"geode/{model}",
                "geode_trajectory": str(trajectory_path) if trajectory_path else None,
                "geode_trajectory_status": trajectory_status,
                "geode_trajectory_error": trajectory_error,
                "error": (str(getattr(result, "error", "") or "") if not task_success else None),
            }
        except Exception as exc:
            if loop is not None:
                try:
                    await loop.amark_session_error()
                except Exception:
                    log.debug("MCPMark error lifecycle close failed", exc_info=True)
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


class CodexMCPMarkAgent(BaseMCPAgent):
    """Filesystem MCPMark adapter backed by ``codex exec`` subscription auth."""

    async def execute(
        self, instruction: str, tool_call_log_file: str | None = None
    ) -> dict[str, Any]:
        start_time = time.time()
        self._reset_progress()
        self._refresh_service_config()
        model = _codex_model(self.litellm_input_model_name)
        if self.mcp_service != "filesystem":
            raise ValueError("Codex MCPMark comparison currently supports filesystem only")

        server = self._create_stdio_server()
        params = server.params
        mcp_config = _codex_mcp_config(params.command, list(params.args), int(self.timeout))
        effort = str(self.reasoning_effort or "default")
        prompt = (
            "Mode: MCPMark benchmark.\n"
            "Action surface: mcpmark MCP tools only.\n"
            "Forbidden: shell commands, direct filesystem APIs, patches, web tools, "
            "and delegation.\n"
            "Completion: mutate the MCP-backed fixture exactly as requested, then "
            "report briefly.\n\n"
            f"Task:\n{instruction}"
        )

        with tempfile.TemporaryDirectory(prefix="geode-mcpmark-codex-") as runner_dir:
            command = [
                "codex",
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--strict-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                runner_dir,
                "--model",
                model,
                "-c",
                f"model_reasoning_effort={json.dumps(effort)}",
                "-c",
                'approval_policy="never"',
                "-c",
                "skills.include_instructions=false",
                "-c",
                "skills.bundled.enabled=false",
                "-c",
                "include_apps_instructions=false",
                "-c",
                "include_collaboration_mode_instructions=false",
                "-c",
                "tools.web_search=false",
                "-c",
                f"mcp_servers.mcpmark={mcp_config}",
            ]
            for feature in _CODEX_DISABLED_FEATURES:
                command.extend(("--disable", feature))
            command.append("-")
            process = await asyncio.create_subprocess_exec(
                *command,
                env=_codex_subscription_environment(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")), timeout=float(self.timeout)
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise TimeoutError(
                    f"codex exec exceeded MCPMark timeout ({self.timeout}s)"
                ) from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if tool_call_log_file:
            log_path = Path(tool_call_log_file)
            log_path.write_text(stdout, encoding="utf-8")
            if stderr:
                log_path.with_suffix(".stderr.log").write_text(stderr, encoding="utf-8")

        summary = _summarize_codex_exec(stdout)
        execution_time = time.time() - start_time
        error = summary["error"]
        if process.returncode and not error:
            error = stderr.strip() or f"codex exec exited {process.returncode}"
        task_success = process.returncode == 0 and not error and summary["turn_count"] > 0
        if tool_call_log_file:
            try:
                trajectory_path = export_codex_mcpmark_trajectory(
                    exec_log_path=Path(tool_call_log_file),
                    instruction=instruction,
                    model=model,
                    effort=effort,
                )
                trajectory_status = "written"
                trajectory_error = None
            except Exception as exc:
                log.warning("Codex MCPMark trajectory sidecar export failed: %s", exc)
                trajectory_path = None
                trajectory_status = "failed"
                trajectory_error = str(exc)
        else:
            trajectory_path = None
            trajectory_status = "not_requested"
            trajectory_error = None
        self.usage_tracker.update(
            success=task_success,
            token_usage=summary["token_usage"],
            turn_count=summary["turn_count"],
            execution_time=execution_time,
        )
        return {
            "success": task_success,
            "output": summary["output"] or "Task completed",
            "token_usage": summary["token_usage"],
            "turn_count": summary["turn_count"],
            "execution_time": execution_time,
            "litellm_run_model_name": f"codex/{model}",
            "codex_thread_id": summary["thread_id"],
            "mcp_tool_calls": summary["mcp_tool_calls"],
            "geode_trajectory": str(trajectory_path) if trajectory_path else None,
            "geode_trajectory_status": trajectory_status,
            "geode_trajectory_error": trajectory_error,
            "error": error or None,
        }


def register_mcpmark_agent(registry: dict[str, Any]) -> None:
    _patch_mcpmark_github_visibility()
    registry["geode"] = GeodeMCPMarkAgent
    registry["codex"] = CodexMCPMarkAgent
