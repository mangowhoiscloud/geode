"""GEODE and Codex CLI adapters for MCPMark.

This module is public-safe and can be imported from an upstream MCPMark checkout.
It intentionally depends on MCPMark only at runtime so GEODE can ship the adapter
without vendoring the benchmark repository.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from core.agent.loop.models import TerminationReason, is_successful_task_termination

from geode_product.benchmark_harness.trajectory_artifacts import (
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

_MCPMARK_CLEANUP_GRACE_SECONDS = 5.0


class MCPMarkInfrastructureError(RuntimeError):
    """Fail-loud signal for an attempt whose cleanup/evidence boundary failed."""

    failure_class = "infrastructure_invalid"


def _tool_schema_sha256(tool_schemas: list[dict[str, Any]]) -> str:
    """Digest the order-independent raw MCP ``list_tools`` response."""
    schemas = sorted(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for schema in tool_schemas
    )
    encoded = ("[" + ",".join(schemas) + "]").encode()
    return hashlib.sha256(encoded).hexdigest()


def _kill_process_tree(process: Any) -> None:
    """Kill one isolated Codex process group, falling back off POSIX."""
    process_pid = getattr(process, "pid", None)
    if os.name == "posix" and isinstance(process_pid, int):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process_pid, signal.SIGKILL)
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()


async def _run_bounded_cleanup(label: str, *operations: Callable[[], Awaitable[Any]]) -> None:
    """Run ordered cleanup operations under one grace budget."""
    if not operations:
        return
    first_error: Exception | None = None
    try:
        async with asyncio.timeout(_MCPMARK_CLEANUP_GRACE_SECONDS):
            for operation in operations:
                try:
                    await operation()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
    except TimeoutError as exc:
        raise MCPMarkInfrastructureError(
            f"{label} cleanup exceeded {_MCPMARK_CLEANUP_GRACE_SECONDS}s; "
            "attempt is infrastructure-invalid"
        ) from exc
    if first_error is not None:
        raise MCPMarkInfrastructureError(
            f"{label} cleanup failed; attempt is infrastructure-invalid"
        ) from first_error


def _write_deadline_receipt(
    tool_call_log_file: str,
    *,
    arm: str,
    limit_seconds: float,
    action_started: float,
    action_deadline: float,
    action_finished: float,
    action_timed_out: bool,
    escaped_error: BaseException | None,
    cleanup_elapsed: float,
    cleanup_error: MCPMarkInfrastructureError | None,
    evidence_status: str,
    started_at: float,
    runtime_config: dict[str, Any] | None = None,
) -> Path:
    """Atomically publish one immutable deadline receipt beside the native log."""
    receipt: dict[str, Any] = {
        "schema_id": "geode.mcpmark.execution_deadline@1",
        "arm": arm,
        "timeout_owner": "adapter",
        "timed_surface": "adapter_execute_entry_through_native_runtime_return",
        "clock": "monotonic",
        "limit_seconds": limit_seconds,
        "action_started_monotonic": action_started,
        "action_deadline_monotonic": action_deadline,
        "action_finished_monotonic": action_finished,
        "action_elapsed_seconds": action_finished - action_started,
        "expired": action_timed_out,
        "action_status": (
            "right_censored"
            if action_timed_out
            else "aborted"
            if escaped_error is not None
            else "complete"
        ),
        "cleanup_grace_seconds": _MCPMARK_CLEANUP_GRACE_SECONDS,
        "cleanup_elapsed_seconds": cleanup_elapsed,
        "cleanup_status": "infrastructure_invalid" if cleanup_error else "complete",
        "evidence_status": evidence_status,
        "started_at_unix_seconds": started_at,
        "finished_at_unix_seconds": time.time(),
    }
    if runtime_config is not None:
        receipt["runtime_config"] = runtime_config
    target = Path(tool_call_log_file).with_name("execution.deadline.json")
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except OSError as exc:
        raise MCPMarkInfrastructureError(
            "MCPMark deadline receipt publish failed; attempt is infrastructure-invalid"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _codex_mcp_config(command: str, args: list[str], timeout: int) -> str:
    """Build the inline TOML accepted by ``codex exec -c``."""
    return (
        "{command="
        f"{json.dumps(command)},args={json.dumps(args)},"
        f"startup_timeout_sec=120,tool_timeout_sec={timeout},"
        'required=true,default_tools_approval_mode="approve"'
        "}"
    )


def _summarize_codex_exec(
    stdout: str, *, allow_incomplete_final_record: bool = False
) -> dict[str, Any]:
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
    lines = [line for line in stdout.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if allow_incomplete_final_record and index == len(lines) - 1:
                break
            raise
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
        if isinstance(result, dict):
            return result
        model_dump = getattr(result, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(by_alias=True, exclude_none=True)
            if isinstance(dumped, dict):
                return dumped
        return {
            "result": (
                result
                if result is None or isinstance(result, (list, str, int, float, bool))
                else str(result)
            )
        }


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
    timeout: float,
) -> Any:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters.registry import bootstrap_builtins
    from core.tools.registry import ToolRegistry

    from geode_product.wiring import (
        build_middleware_registry,
        build_policy_sources,
        current_activity_sink,
    )

    policy_sources = build_policy_sources()
    bootstrap_builtins(policy_sources=policy_sources)

    registry = ToolRegistry()
    handlers: dict[str, Any] = {}
    for tool in tools:
        registry.register(tool)
        handlers[tool.name] = tool.aexecute

    schemas = {tool.name: tool.schema for tool in tools}
    middleware = build_middleware_registry(policy_sources=policy_sources)
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
        force_include_allowed_tools=True,
        system_prompt_override=(
            "Agent: GEODE running inside MCPMark. Complete the benchmark task "
            "using only the provided MCP tools. Do not invent tool results. "
            "When finished, provide a concise final answer."
        ),
        quiet=True,
        activity_sink_provider=current_activity_sink,
        policy_sources=policy_sources,
    )


def _route_from_model(model_name: str) -> tuple[str, str, str]:
    normalized = model_name.removeprefix("geode-")
    if normalized.startswith("gpt-"):
        return normalized, "openai", "subscription"
    if normalized.startswith("claude-"):
        return normalized, "anthropic", "api_key"
    if normalized.startswith("glm-"):
        return normalized, "zhipuai", "api_key"
    return normalized, "openai", "subscription"


def _usage_dict(result: Any) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    to_dict = getattr(usage, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, dict):
            raw.setdefault(
                "total_tokens",
                int(raw.get("input_tokens") or 0) + int(raw.get("output_tokens") or 0),
            )
            if thinking_tokens := int(raw.get("thinking_tokens") or 0):
                raw.setdefault("reasoning_tokens", thinking_tokens)
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


def _patch_mcpmark_cleanup_on_error() -> None:
    """Attempt fixture cleanup before MCPMark propagates an execution error."""
    module = importlib.import_module("src.evaluator")
    evaluator_cls = module.MCPEvaluator
    if getattr(evaluator_cls, "_geode_cleanup_on_error_patched", False):
        return

    original_run_single_task = evaluator_cls._run_single_task

    def run_single_task_with_cleanup(self: Any, task: Any) -> Any:
        try:
            return original_run_single_task(self, task)
        except BaseException:
            try:
                if self.state_manager.clean_up(task) is False:
                    log.error("MCPMark cleanup reported failure after an execution error")
            except Exception:
                log.exception("MCPMark cleanup failed after an execution error")
            raise

    evaluator_cls._run_single_task = run_single_task_with_cleanup
    evaluator_cls._geode_cleanup_on_error_patched = True


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
        event_loop = asyncio.get_running_loop()
        action_started = event_loop.time()
        action_deadline = action_started + float(self.timeout)
        self._reset_progress()
        self._refresh_service_config()
        model, provider, source = _route_from_model(self.litellm_input_model_name)
        from core.config import settings
        from core.orchestration.tool_offload import get_offload_store

        runtime_config: dict[str, Any] = {
            "max_tool_result_tokens": settings.max_tool_result_tokens,
            "offload_store_bound": get_offload_store() is not None,
        }
        loop: Any | None = None
        mcp_server: Any | None = None
        result: Any | None = None
        escaped_error: BaseException | None = None
        action_timed_out = False
        previous_fail_empty_text: str | None = None
        fail_empty_text_set = False
        wall = asyncio.timeout_at(action_deadline)

        try:
            async with wall:
                mcp_server = await self._create_mcp_server()
                await mcp_server.__aenter__()
                tool_schemas = await mcp_server.list_tools()
                runtime_config["tool_schema_sha256"] = _tool_schema_sha256(tool_schemas)
                tools = [
                    MCPMarkGeodeTool(mcp_server=mcp_server, schema=schema)
                    for schema in tool_schemas
                ]
                remaining = max(action_deadline - event_loop.time(), 0.001)
                loop = _build_loop(
                    tools=tools,
                    instruction=instruction,
                    model=model,
                    provider=provider,
                    source=source,
                    effort=str(self.reasoning_effort or "default"),
                    timeout=remaining,
                )
                previous_fail_empty_text = os.environ.get("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT")
                os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = "1"
                fail_empty_text_set = True
                result = await loop.arun(instruction)
        except BaseException as exc:
            if isinstance(exc, TimeoutError) and wall.expired():
                action_timed_out = True
            else:
                escaped_error = exc
        finally:
            if fail_empty_text_set:
                if previous_fail_empty_text is None:
                    os.environ.pop("GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT", None)
                else:
                    os.environ["GEODE_CODEX_OAUTH_FAIL_EMPTY_TEXT"] = previous_fail_empty_text
        action_finished = event_loop.time()
        if escaped_error is None and action_finished >= action_deadline:
            action_timed_out = True

        if action_timed_out:
            if loop is not None:
                cognitive_state = getattr(loop, "cognitive_state", None)
                rounds = int(getattr(cognitive_state, "round_count", 0) or 0)
                tool_processor = getattr(loop, "_tool_processor", None)
                tool_calls = list(getattr(tool_processor, "tool_log", []) or [])
                result = loop._terminal_result(
                    TerminationReason.TIME_BUDGET_EXPIRED,
                    f"GEODE exceeded MCPMark action deadline ({self.timeout}s)",
                    rounds=rounds,
                    error=True,
                    tool_calls=tool_calls,
                )
            else:
                result = SimpleNamespace(
                    text=f"GEODE exceeded MCPMark action deadline ({self.timeout}s)",
                    rounds=0,
                    error=str(TerminationReason.TIME_BUDGET_EXPIRED),
                    termination_reason=TerminationReason.TIME_BUDGET_EXPIRED,
                    tool_calls=[],
                    usage=None,
                )

        task_success = (
            result is not None
            and not bool(getattr(result, "error", None))
            and (is_successful_task_termination(getattr(result, "termination_reason", "")))
        )
        cleanup_started = event_loop.time()
        cleanup_operations: list[Callable[[], Awaitable[Any]]] = []
        if mcp_server is not None:
            server_to_close = mcp_server

            async def close_mcp_server() -> None:
                await server_to_close.__aexit__(None, None, None)

            cleanup_operations.append(close_mcp_server)
        if loop is not None:
            if task_success and escaped_error is None:
                cleanup_operations.append(loop.amark_session_completed)
            else:
                cleanup_operations.append(loop.amark_session_error)

        cleanup_error: MCPMarkInfrastructureError | None = None
        try:
            await _run_bounded_cleanup("GEODE MCPMark", *cleanup_operations)
        except MCPMarkInfrastructureError as exc:
            cleanup_error = exc
        cleanup_elapsed = event_loop.time() - cleanup_started

        token_usage = _usage_dict(result) if result is not None else {}
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
            if result is not None:
                try:
                    trajectory_path = export_mcpmark_trajectory(
                        loop=loop or SimpleNamespace(_session_id=""),
                        instruction=instruction,
                        result=result,
                        tool_call_log_file=tool_call_log_file,
                        model=model,
                        provider=provider,
                        source=source,
                        effort=str(self.reasoning_effort or "default"),
                        action_timed_out=action_timed_out,
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
                trajectory_status = "failed"
                trajectory_error = "GEODE action produced no terminal result"
        else:
            trajectory_path = None
            trajectory_status = "not_requested"
            trajectory_error = None

        evidence_error: MCPMarkInfrastructureError | None = None
        if trajectory_status == "failed":
            evidence_error = MCPMarkInfrastructureError(
                "GEODE MCPMark trajectory finalization failed; attempt is infrastructure-invalid"
            )
        if tool_call_log_file:
            try:
                _write_deadline_receipt(
                    tool_call_log_file,
                    arm="geode",
                    limit_seconds=float(self.timeout),
                    action_started=action_started,
                    action_deadline=action_deadline,
                    action_finished=action_finished,
                    action_timed_out=action_timed_out,
                    escaped_error=escaped_error,
                    cleanup_elapsed=cleanup_elapsed,
                    cleanup_error=cleanup_error,
                    evidence_status=(
                        "infrastructure_invalid"
                        if evidence_error is not None
                        else trajectory_status
                    ),
                    started_at=start_time,
                    runtime_config=runtime_config,
                )
            except MCPMarkInfrastructureError as exc:
                evidence_error = exc
        infrastructure_error = cleanup_error or evidence_error
        if infrastructure_error is not None:
            if escaped_error is not None:
                raise infrastructure_error from escaped_error
            raise infrastructure_error
        if escaped_error is not None:
            raise escaped_error

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


class CodexMCPMarkAgent(BaseMCPAgent):
    """Filesystem MCPMark adapter backed by ``codex exec`` subscription auth."""

    async def execute(
        self, instruction: str, tool_call_log_file: str | None = None
    ) -> dict[str, Any]:
        start_time = time.time()
        event_loop = asyncio.get_running_loop()
        action_started = event_loop.time()
        action_deadline = action_started + float(self.timeout)
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
                os.getenv("GEODE_MCPMARK_CODEX_BIN", "codex"),
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
            stdout_capture_path = Path(runner_dir) / "codex.stdout.jsonl"
            stderr_capture_path = Path(runner_dir) / "codex.stderr.log"
            escaped_error: BaseException | None = None
            process: Any | None = None
            action_timed_out = False
            wall = asyncio.timeout_at(action_deadline)
            with (
                stdout_capture_path.open("wb") as stdout_capture,
                stderr_capture_path.open("wb") as stderr_capture,
            ):
                try:
                    async with wall:
                        process = await asyncio.create_subprocess_exec(
                            *command,
                            env=_codex_subscription_environment(),
                            stdin=asyncio.subprocess.PIPE,
                            stdout=stdout_capture,
                            stderr=stderr_capture,
                            start_new_session=os.name == "posix",
                        )
                        await process.communicate(prompt.encode("utf-8"))
                except BaseException as exc:
                    if isinstance(exc, TimeoutError) and wall.expired():
                        action_timed_out = True
                        timeout_error = (
                            f"codex exec exceeded MCPMark action deadline ({self.timeout}s)"
                        )
                    else:
                        timeout_error = ""
                        escaped_error = exc
                else:
                    timeout_error = ""

                action_finished = event_loop.time()
                if escaped_error is None and action_finished >= action_deadline:
                    action_timed_out = True
                    timeout_error = f"codex exec exceeded MCPMark action deadline ({self.timeout}s)"
                cleanup_started = event_loop.time()
                cleanup_error: MCPMarkInfrastructureError | None = None
                if process is not None and (action_timed_out or escaped_error is not None):
                    _kill_process_tree(process)
                    if process.stdin is not None:
                        process.stdin.close()
                    try:
                        await _run_bounded_cleanup("Codex MCPMark process reap", process.wait)
                    except MCPMarkInfrastructureError as exc:
                        cleanup_error = exc
                cleanup_elapsed = event_loop.time() - cleanup_started

            stdout_bytes = stdout_capture_path.read_bytes()
            stderr_bytes = stderr_capture_path.read_bytes()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if tool_call_log_file:
            log_path = Path(tool_call_log_file)
            log_path.write_text(stdout, encoding="utf-8")
            if stderr:
                log_path.with_suffix(".stderr.log").write_text(stderr, encoding="utf-8")
        summary: dict[str, Any] | None = None
        trajectory_path: Path | None = None
        trajectory_status = "not_requested"
        trajectory_error: str | None = None
        evidence_error: MCPMarkInfrastructureError | None = None
        if escaped_error is None:
            summary = _summarize_codex_exec(
                stdout,
                allow_incomplete_final_record=bool(timeout_error),
            )
        if tool_call_log_file and escaped_error is None:
            try:
                trajectory_path = export_codex_mcpmark_trajectory(
                    exec_log_path=Path(tool_call_log_file),
                    instruction=instruction,
                    model=model,
                    effort=effort,
                    timeout_error=timeout_error,
                )
                trajectory_status = "written"
                trajectory_error = None
            except Exception as exc:
                log.warning("Codex MCPMark trajectory sidecar export failed: %s", exc)
                trajectory_path = None
                trajectory_status = "failed"
                trajectory_error = str(exc)
                evidence_error = MCPMarkInfrastructureError(
                    "Codex MCPMark trajectory finalization failed; "
                    "attempt is infrastructure-invalid"
                )
        receipt_error: MCPMarkInfrastructureError | None = None
        if tool_call_log_file:
            try:
                _write_deadline_receipt(
                    tool_call_log_file,
                    arm="codex",
                    limit_seconds=float(self.timeout),
                    action_started=action_started,
                    action_deadline=action_deadline,
                    action_finished=action_finished,
                    action_timed_out=action_timed_out,
                    escaped_error=escaped_error,
                    cleanup_elapsed=cleanup_elapsed,
                    cleanup_error=cleanup_error,
                    evidence_status=(
                        "infrastructure_invalid"
                        if evidence_error is not None
                        else trajectory_status
                    ),
                    started_at=start_time,
                )
            except MCPMarkInfrastructureError as exc:
                receipt_error = exc
        infrastructure_error = receipt_error or cleanup_error or evidence_error
        if infrastructure_error is not None:
            if escaped_error is not None:
                raise infrastructure_error from escaped_error
            raise infrastructure_error
        if escaped_error is not None:
            raise escaped_error

        assert summary is not None
        execution_time = time.time() - start_time
        error = timeout_error or summary["error"]
        returncode = getattr(process, "returncode", None)
        if returncode and not error:
            error = stderr.strip() or f"codex exec exited {returncode}"
        task_success = returncode == 0 and not error and summary["turn_count"] > 0
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
    if BaseMCPAgent is not object:
        _patch_mcpmark_cleanup_on_error()
    registry["geode"] = GeodeMCPMarkAgent
    registry["codex"] = CodexMCPMarkAgent
