"""ToolExecutor — route tool calls to handlers with HITL safety checks."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager
    from core.hooks import HookSystem

from core.agent.approval import _write_denial_with_fallback
from core.agent.safety import (
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    WRITE_TOOLS,
)
from core.cli.bash_tool import BashTool

log = logging.getLogger(__name__)


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
        action_handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        bash_tool: BashTool | None = None,
        auto_approve: bool = False,
        sub_agent_manager: SubAgentManager | None = None,
        mcp_manager: Any | None = None,
        hitl_level: int = 2,
        hooks: HookSystem | None = None,
        approval_callback: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = action_handlers or {}
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

    def _fire_hook(self, event_name: str, data: dict[str, Any]) -> None:
        """Fire a hook event if HookSystem is available. No-op otherwise."""
        if self._hooks is None:
            return
        from core.hooks import HookEvent

        try:
            event = HookEvent(event_name)
            self._hooks.trigger(event, data)
        except Exception:
            log.debug("Hook fire failed for %s", event_name, exc_info=True)

    def _track_decision(self, tool_name: str, decision: str) -> None:
        """Delegates to ApprovalWorkflow."""
        self._approval.track_decision(tool_name, decision)

    def _check_auto_deny(self, tool_name: str) -> bool:
        """Delegates to ApprovalWorkflow."""
        return self._approval.check_auto_deny(tool_name)

    def _prompt_with_always(
        self,
        label: str,
        detail: str,
        *,
        safety_level: str = "write",
        tool_name: str = "",
    ) -> str:
        """Delegates to ApprovalWorkflow."""
        return self._approval.prompt_with_always(
            label, detail, safety_level=safety_level, tool_name=tool_name
        )

    def register(self, tool_name: str, handler: Callable[..., dict[str, Any]]) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    def _apply_safety_gates(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, bool]:
        """Check HITL gates. Returns (rejection_result, approved_via_hitl).

        Delegates to ApprovalWorkflow but routes through self._confirm_*
        methods so that test patches on ToolExecutor instances still work.
        """
        if tool_name in DANGEROUS_TOOLS:
            return self._execute_dangerous(tool_name, tool_input), False

        approved = False

        # Write tools
        if tool_name in WRITE_TOOLS:
            if self._approval._hitl_level == 0 or self._approval.is_bash_auto_approved(""):
                # Simplified: check if write is auto-approved
                pass
            if (
                self._approval._hitl_level == 0
                or "write" in self._approval._always_approved_categories
                or tool_name in self._approval._always_approved_tools
            ):
                approved = True
            else:
                self._fire_hook(
                    "tool_approval_requested",
                    {"tool_name": tool_name, "safety_level": "write"},
                )
                if not self._confirm_write(tool_name, tool_input):
                    self._fire_hook(
                        "tool_approval_denied",
                        {
                            "tool_name": tool_name,
                            "safety_level": "write",
                            "permission_level": "HITL",
                            "decision": "denied",
                            "latency_ms": 0.0,
                        },
                    )
                    return _write_denial_with_fallback(tool_name), False
                self._fire_hook(
                    "tool_approval_granted",
                    {
                        "tool_name": tool_name,
                        "safety_level": "write",
                        "always": "write" in self._approval._always_approved_categories,
                    },
                )
                approved = True

        # Expensive tools
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            if (
                self._approval._hitl_level == 0
                or "cost" in self._approval._always_approved_categories
                or tool_name in self._approval._always_approved_tools
            ):
                approved = True
            else:
                cost = EXPENSIVE_TOOLS[tool_name]
                self._fire_hook(
                    "tool_approval_requested",
                    {"tool_name": tool_name, "safety_level": "cost"},
                )
                if not self._confirm_cost(tool_name, cost):
                    self._fire_hook(
                        "tool_approval_denied",
                        {
                            "tool_name": tool_name,
                            "safety_level": "cost",
                            "permission_level": "HITL",
                            "decision": "denied",
                            "latency_ms": 0.0,
                        },
                    )
                    return {"error": "User denied expensive operation", "denied": True}, False
                self._fire_hook(
                    "tool_approval_granted",
                    {
                        "tool_name": tool_name,
                        "safety_level": "cost",
                        "always": "cost" in self._approval._always_approved_categories,
                    },
                )
                approved = True

        return None, approved

    # Delegation methods — route to ApprovalWorkflow, patchable by tests
    def _confirm_write(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        return self._approval.confirm_write(tool_name, tool_input)

    def _confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        return self._approval.confirm_cost(tool_name, estimated_cost)

    def _confirm_mcp(self, server: str, tool_name: str) -> bool:
        return self._approval.confirm_mcp(server, tool_name)

    def _request_approval(self, command: str, reason: str) -> bool:
        return self._approval.request_bash_approval(command, reason)

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

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call, applying HITL gate if needed."""
        log.debug("ToolExecutor: %s(%s)", tool_name, tool_input)

        # Safety gates (HITL approval for dangerous/write/expensive tools)
        gate_result, approved_via_hitl = self._apply_safety_gates(tool_name, tool_input)
        if gate_result is not None:
            return gate_result

        # Sub-agent delegation
        if tool_name == "delegate_task":
            return self._execute_delegate(tool_input)

        # Resolve handler (registered or MCP fallback)
        handler = self._handlers.get(tool_name)
        if handler is None:
            if self._mcp_manager is not None:
                server = self._mcp_manager.find_server_for_tool(tool_name)
                if server is not None:
                    return self._execute_mcp(server, tool_name, tool_input)
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: '{tool_name}'. Use 'show_help' for available tools."}

        # Execute handler
        try:
            if approved_via_hitl:
                with _tool_spinner(f"Executing {tool_name}..."):
                    raw: Any = handler(**tool_input)
            else:
                raw = handler(**tool_input)
            if raw is None:
                return {
                    "error": f"Tool '{tool_name}' returned None instead of a dict. "
                    "This is likely a bug in the tool handler implementation.",
                    "status": "failure",
                }
            if not isinstance(raw, dict):
                return {"result": raw}
            return raw
        except Exception as exc:
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            from core.tools.base import classify_tool_exception

            return classify_tool_exception(exc, tool_name=tool_name)

    def _execute_delegate(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Delegate task(s) to sub-agent. Supports single and batch."""
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
        results = self._sub_agent_manager.delegate(
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

    def _execute_dangerous(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a dangerous tool with user approval."""
        if tool_name == "run_bash":
            return self._execute_bash(tool_input)

        return {"error": f"Dangerous tool not implemented: {tool_name}"}

    def _execute_bash(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute bash command with HITL approval.

        DANGEROUS tools always require user approval — auto_approve is
        ignored for this category to prevent sub-agent bypass.

        HITL level gating:
        - hitl_level 0: skip all approval (autonomous)
        - hitl_level 1: skip bash approval (write-only gate)
        - hitl_level 2: full approval (default)
        """
        command = tool_input.get("command", "")
        reason = tool_input.get("reason", "")

        if not command:
            return {"error": "No command provided"}

        # Check blocked patterns first
        blocked = self._bash.validate(command)
        if blocked:
            return self._bash.to_tool_result(blocked)

        # Approval gate: safe commands auto-pass, others go through HITL
        if not self._approval.is_bash_auto_approved(command):
            approved = self._request_approval(command, reason)
            if not approved:
                return {"error": "User denied execution", "denied": True}

        with _tool_spinner(f"Running: {command}"):
            result = self._bash.execute(command)
        return self._bash.to_tool_result(result)

    def _execute_mcp(
        self, server: str, tool_name: str, tool_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute an MCP tool with safety logging.

        MCP tools from external servers are logged and routed through the
        manager.  Previously these bypassed all safety checks.
        """
        log.info("MCP tool: %s → %s (args=%s)", tool_name, server, list(tool_input.keys()))

        # MCP tools are external — confirm once per server per session.
        if not self._auto_approve and not self._approval.is_mcp_approved(server):
            if not self._confirm_mcp(server, tool_name):
                return {"error": "User denied MCP tool execution", "denied": True}
            self._approval.mark_mcp_approved(server)

        assert self._mcp_manager is not None  # guaranteed by caller
        with _tool_spinner(f"Calling {server}/{tool_name}..."):
            result: dict[str, Any] = self._mcp_manager.call_tool(server, tool_name, tool_input)

        # Sandbox hardening: redact secrets from MCP tool results
        from core.utils.redaction import redact_secrets

        for key in ("stdout", "stderr", "output", "content", "text", "result"):
            if key in result and isinstance(result[key], str):
                result[key] = redact_secrets(result[key])
        return result

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())
