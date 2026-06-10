"""ToolExecutor — route tool calls to handlers with HITL safety checks."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager
    from core.hooks import HookSystem
    from core.tools.base import ToolContext

from core.agent.safety import DANGEROUS_TOOLS
from core.hooks.system import HookEvent
from core.tools.bash_tool import BashTool

log = logging.getLogger(__name__)

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]] | Any]


def _tool_spinner(label: str) -> Any:
    """Lookup ``_tool_spinner`` via the package namespace.

    Tests patch ``core.agent.tool_executor._tool_spinner`` to assert spinner
    behavior; resolving via the parent package preserves that contract.
    """
    from core.agent import tool_executor as _pkg

    return _pkg._tool_spinner(label)


# Everything else is STANDARD — executes without special gates


class ToolExecutor:
    """Routes tool calls to handlers with HITL safety checks.

    Safety levels:
    - SAFE: execute immediately, no confirmation
    - STANDARD: execute normally (analyze, compare, report, etc.)
    - DANGEROUS: requires explicit user approval (bash)
    """

    def __init__(
        self,
        *,
        action_handlers: dict[str, ToolHandler] | None = None,
        bash_tool: BashTool | None = None,
        auto_approve: bool = False,
        sub_agent_manager: SubAgentManager | None = None,
        mcp_manager: Any | None = None,
        hitl_level: int = 2,
        hooks: HookSystem | None = None,
        approval_callback: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._handlers: dict[str, ToolHandler] = action_handlers or {}
        self._bash = bash_tool or BashTool()
        self._auto_approve = auto_approve  # for testing only
        self._sub_agent_manager = sub_agent_manager
        self._mcp_manager = mcp_manager
        self._hitl_level = hitl_level
        self._hooks: HookSystem | None = hooks
        self._approval_callback = approval_callback

        # HITL approval workflow (extracted — SRP)
        from core.agent.approval import ApprovalWorkflow

        self._approval = ApprovalWorkflow(
            auto_approve=auto_approve,
            hitl_level=hitl_level,
            hooks=hooks,
            approval_callback=approval_callback,
        )

    def _fire_hook(self, event: HookEvent, data: dict[str, Any]) -> None:
        """Fire a hook event if HookSystem is available. No-op otherwise."""
        if self._hooks is None:
            return
        try:
            self._hooks.trigger(event, data)
        except Exception:
            log.debug("Hook fire failed for %s", event, exc_info=True)

    def _track_decision(self, tool_name: str, decision: str) -> None:
        """Delegates to ApprovalWorkflow."""
        self._approval.track_decision(tool_name, decision)

    def register(self, tool_name: str, handler: ToolHandler) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    # Delegation methods — route to ApprovalWorkflow, patchable by tests
    def _confirm_write(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        return self._approval.confirm_write(tool_name, tool_input)

    def _confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        return self._approval.confirm_cost(tool_name, estimated_cost)

    # Proxy properties for backward compat (tests access these directly)
    @property
    def _always_approved_categories(self) -> set[str]:
        return self._approval._always_approved_categories

    @property
    def _always_approved_tools(self) -> set[str]:
        return self._approval._always_approved_tools

    @property
    def _mcp_approved_servers(self) -> set[str]:
        return self._approval._mcp_approved_servers

    async def aexecute(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Execute a tool call through the async runtime path.

        Async-native handlers are awaited directly. Legacy sync handlers are
        isolated behind ``asyncio.to_thread`` so the agent loop no longer wraps
        the entire executor in a thread.
        """
        log.debug("ToolExecutor.async: %s(%s)", tool_name, tool_input)

        if context and context.cancellation and context.cancellation.is_set():
            return {"error": "Tool execution cancelled before start", "cancelled": True}

        if tool_name in DANGEROUS_TOOLS:
            return await self._execute_dangerous_async(tool_name, tool_input, context=context)

        gate_result, approved_via_hitl = await self._apply_safety_gates_async(tool_name, tool_input)
        if gate_result is not None:
            return gate_result

        if tool_name == "delegate_task":
            # PR-Async-Phase-C step 3 (2026-05-22) — switched to native
            # async delegate dispatch. The old asyncio.to_thread bridge
            # over sync ``_execute_delegate`` is gone.
            return await self._aexecute_delegate(tool_input)

        handler = self._handlers.get(tool_name)
        if handler is None:
            if self._mcp_manager is not None:
                server = await asyncio.to_thread(self._mcp_manager.find_server_for_tool, tool_name)
                if server is not None:
                    return await self._execute_mcp_async(server, tool_name, tool_input)
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: '{tool_name}'. Use 'show_help' for available tools."}

        try:
            if approved_via_hitl:
                with _tool_spinner(f"Executing {tool_name}..."):
                    raw = await self._call_handler_async(handler, tool_input, context=context)
            else:
                raw = await self._call_handler_async(handler, tool_input, context=context)
            return self._normalize_raw_result(tool_name, raw)
        except Exception as exc:
            return self._classify_execution_exception(tool_name, exc)

    async def _apply_safety_gates_async(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, bool]:
        return await self._approval.apply_safety_gates_async(tool_name, tool_input)

    async def _call_handler_async(
        self,
        handler: ToolHandler,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> Any:
        # PR-TOOL-EXEC-CONTEXT (2026-05-28) — inject the loop's
        # ``ToolContext`` as a reserved ``_tool_context`` kwarg. Handlers
        # that accept it (via explicit signature OR ``**kwargs`` splat)
        # get the loop's adapter routing; handlers with closed signatures
        # (no ``**kwargs``, no explicit ``_tool_context`` parameter) are
        # detected via ``inspect.signature`` and called without the extra
        # key so a third-party plugin handler that wires explicit
        # parameters does not crash with ``unexpected keyword argument``.
        # The underscore prefix on ``_tool_context`` prevents accidental
        # collision with tool-arg JSON keys the LLM might emit.
        kwargs: dict[str, Any] = dict(tool_input)
        if context is not None and self._handler_accepts_tool_context(handler):
            kwargs["_tool_context"] = context
        if self._is_async_handler(handler):
            raw = handler(**kwargs)
            return await cast(Awaitable[Any], raw)
        return await asyncio.to_thread(handler, **kwargs)

    @staticmethod
    def _handler_accepts_tool_context(handler: ToolHandler) -> bool:
        """Return True iff *handler* can receive ``_tool_context=`` —
        either via ``**kwargs`` or via an explicit named parameter.

        Defensive: an unanalysable signature (C-extension callable,
        functools.partial with mangled introspection) defaults to True
        so we preserve the v0.99.x behaviour where every handler used
        ``**kwargs``. False only when the handler has a closed signature
        that does NOT include ``_tool_context``.
        """
        try:
            sig = inspect.signature(handler)
        except (TypeError, ValueError):
            return True
        for param in sig.parameters.values():
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                return True
            if param.name == "_tool_context":
                return True
        return False

    @staticmethod
    def _is_async_handler(handler: ToolHandler) -> bool:
        if inspect.iscoroutinefunction(handler):
            return True
        return callable(handler) and inspect.iscoroutinefunction(type(handler).__call__)

    @staticmethod
    def _normalize_raw_result(tool_name: str, raw: Any) -> dict[str, Any]:
        if inspect.isawaitable(raw):
            close = getattr(raw, "close", None)
            if callable(close):
                close()
            return {
                "error": (
                    f"Tool '{tool_name}' returned an awaitable from the sync execute() path. "
                    "Use ToolExecutor.aexecute() for async handlers."
                ),
                "status": "failure",
            }
        if raw is None:
            return {
                "error": f"Tool '{tool_name}' returned None instead of a dict. "
                "This is likely a bug in the tool handler implementation.",
                "status": "failure",
            }
        if not isinstance(raw, dict):
            return {"result": raw}
        return raw

    @staticmethod
    def _classify_execution_exception(tool_name: str, exc: Exception) -> dict[str, Any]:
        log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
        from core.tools.base import classify_tool_exception

        return classify_tool_exception(exc, tool_name=tool_name)

    async def _aexecute_delegate(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Delegate task(s) to sub-agent (async). Supports single and batch.

        PR-Async-Phase-C step 3 (2026-05-22) — async-native sibling of
        :meth:`_execute_delegate`. Uses ``await
        SubAgentManager.adelegate(...)`` so the parent ToolExecutor's
        event loop is not pinned during sub-agent fan-out.
        """
        from core.agent.sub_agent import SubTask

        if not self._sub_agent_manager:
            return {"error": "SubAgentManager not configured"}

        tasks_raw: list[dict[str, Any]] = tool_input.get("tasks", [])
        if not tasks_raw:
            tasks_raw = [
                {
                    "task_description": tool_input.get("task_description", ""),
                    "task_type": tool_input.get("task_type", "analyze"),
                    "args": tool_input.get("args", {}),
                }
            ]

        ts = int(time.time())
        sub_tasks = [
            SubTask(
                task_id=f"delegate_{ts}_{i}",
                description=t.get("task_description", ""),
                task_type=t.get("task_type", "analyze"),
                args=t.get("args", {}),
            )
            for i, t in enumerate(tasks_raw)
        ]

        # P2-C: progress callback — progressive counter (Claude Code pattern)
        completed_count = 0
        total_count = len(sub_tasks)
        _start_ts = time.time()
        _task_starts: dict[str, float] = {t.task_id: time.time() for t in sub_tasks}

        def _on_progress(result: Any) -> None:
            nonlocal completed_count
            completed_count += 1
            task_elapsed = time.time() - _task_starts.get(result.task_id, _start_ts)
            from core.ui.agentic_ui import render_subagent_progress

            render_subagent_progress(
                completed_count,
                total_count,
                result.description or result.task_id,
                task_elapsed,
            )

        # announce=False: delegate_task returns full results via tool_result,
        # so skip announce queue to avoid double context injection.
        results = await self._sub_agent_manager.adelegate(
            sub_tasks, on_progress=_on_progress, announce=False
        )

        # Final summary line
        from core.ui.agentic_ui import render_subagent_complete

        render_subagent_complete(len(results), time.time() - _start_ts)

        # P2-A: unified response format (single and batch identical)
        succeeded = sum(1 for r in results if r.success)
        summary_parts = []
        for r in results:
            status = "ok" if r.success else "error"
            summary_parts.append(f"{r.task_id}:{status}")
        return {
            "tasks": [r.to_dict() for r in results],
            "total": len(results),
            "succeeded": succeeded,
            "summary": f"{succeeded}/{len(results)} tasks completed. [{', '.join(summary_parts)}]",
        }

    async def _execute_dangerous_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Async dangerous tool execution with async approval."""
        if tool_name == "run_bash":
            return await self._execute_bash_async(tool_input, context=context)

        return {"error": f"Dangerous tool not implemented: {tool_name}"}

    async def _request_approval_async(self, command: str, reason: str) -> bool:
        return await self._approval.request_bash_approval_async(command, reason)

    async def _execute_bash_async(
        self,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Async bash execution with nonblocking approval prompt and subprocess call."""
        command = tool_input.get("command", "")
        reason = tool_input.get("reason", "")
        timeout = int(tool_input.get("timeout") or 30)

        if not command:
            return {"error": "No command provided"}

        blocked = self._bash.validate(command)
        if blocked:
            return self._bash.to_tool_result(blocked)

        if not self._approval.is_bash_auto_approved(command):
            approved = await self._request_approval_async(command, reason)
            if not approved:
                return {"error": "User denied execution", "denied": True}

        with _tool_spinner(f"Running: {command}"):
            result = await self._bash.aexecute(
                command,
                timeout=timeout,
                cancellation=context.cancellation if context else None,
            )
        return self._bash.to_tool_result(result)

    async def _execute_mcp_async(
        self, server: str, tool_name: str, tool_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Async MCP tool execution with async server approval."""
        log.info("MCP tool: %s → %s (args=%s)", tool_name, server, list(tool_input.keys()))

        if not self._auto_approve and not self._approval.is_mcp_approved(server):
            if not await self._approval.confirm_mcp_async(server, tool_name):
                return {"error": "User denied MCP tool execution", "denied": True}
            self._approval.mark_mcp_approved(server)

        assert self._mcp_manager is not None
        with _tool_spinner(f"Calling {server}/{tool_name}..."):
            acall_tool = getattr(self._mcp_manager, "acall_tool", None)
            if callable(acall_tool):
                maybe_result = acall_tool(server, tool_name, tool_input)
                if inspect.isawaitable(maybe_result):
                    result_raw = await maybe_result
                else:
                    result_raw = maybe_result
            else:
                result_raw = await asyncio.to_thread(
                    self._mcp_manager.call_tool, server, tool_name, tool_input
                )
        result: dict[str, Any] = (
            dict(result_raw) if isinstance(result_raw, dict) else {"result": result_raw}
        )

        from core.utils.redaction import redact_secrets

        for key in ("stdout", "stderr", "output", "content", "text", "result"):
            if key in result and isinstance(result[key], str):
                result[key] = redact_secrets(result[key])
        return result

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())
