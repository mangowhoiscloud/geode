"""ToolExecutor — route tool calls to handlers with HITL safety checks.

Central dispatch for all tools available to the AgenticLoop.
Classifies tools by safety level and gates dangerous operations
behind user approval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.cli.sub_agent import SubAgentManager

from core.cli.bash_tool import BashTool
from core.ui.console import console

log = logging.getLogger(__name__)

# Tool safety classifications
SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "list_ips",
        "search_ips",
        "show_help",
        "check_status",
        "switch_model",
        "memory_search",
        "manage_rule",
        "web_fetch",
        "general_web_search",
        "note_read",
        "read_document",
    }
)

DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
    }
)

# Expensive tools require cost confirmation before execution
EXPENSIVE_TOOLS: dict[str, float] = {
    "analyze_ip": 1.50,
    "batch_analyze": 5.00,
    "compare_ips": 3.00,
}

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
    ) -> None:
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = action_handlers or {}
        self._bash = bash_tool or BashTool()
        self._auto_approve = auto_approve  # for testing only
        self._sub_agent_manager = sub_agent_manager
        self._mcp_manager = mcp_manager

    def register(self, tool_name: str, handler: Callable[..., dict[str, Any]]) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call, applying HITL gate if needed."""
        log.debug("ToolExecutor: %s(%s)", tool_name, tool_input)

        # Dangerous tools: HITL gate
        if tool_name in DANGEROUS_TOOLS:
            return self._execute_dangerous(tool_name, tool_input)

        # Expensive tools: cost confirmation gate
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            cost = EXPENSIVE_TOOLS[tool_name]
            if not self._confirm_cost(tool_name, cost):
                return {
                    "error": "User denied expensive operation",
                    "denied": True,
                }

        # Sub-agent delegation
        if tool_name == "delegate_task":
            return self._execute_delegate(tool_input)

        # Delegate to registered handler
        handler = self._handlers.get(tool_name)
        if handler is None:
            # MCP fallback: try MCP servers
            if self._mcp_manager is not None:
                server = self._mcp_manager.find_server_for_tool(tool_name)
                if server is not None:
                    log.info("MCP fallback: %s → %s", tool_name, server)
                    result: dict[str, Any] = self._mcp_manager.call_tool(
                        server, tool_name, tool_input
                    )
                    return result
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(**tool_input)
        except Exception as exc:
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return {"error": str(exc)}

    def _execute_delegate(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Delegate task(s) to sub-agent. Supports single and batch."""
        from core.cli.sub_agent import SubTask

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

        results = self._sub_agent_manager.delegate(sub_tasks)

        if len(results) == 1:
            r = results[0]
            if r.success:
                return {"result": r.output, "task_id": r.task_id}
            return {"error": r.error or "No result"}

        return {
            "results": [r.to_dict() for r in results],
            "total": len(results),
            "succeeded": sum(1 for r in results if r.success),
        }

    def _execute_dangerous(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a dangerous tool with user approval."""
        if tool_name == "run_bash":
            return self._execute_bash(tool_input)

        return {"error": f"Dangerous tool not implemented: {tool_name}"}

    def _execute_bash(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute bash command with HITL approval."""
        command = tool_input.get("command", "")
        reason = tool_input.get("reason", "")

        if not command:
            return {"error": "No command provided"}

        # Check blocked patterns first
        blocked = self._bash.validate(command)
        if blocked:
            return self._bash.to_tool_result(blocked)

        # HITL approval gate
        if not self._auto_approve:
            approved = self._request_approval(command, reason)
            if not approved:
                return {"error": "User denied execution", "denied": True}

        result = self._bash.execute(command)
        return self._bash.to_tool_result(result)

    def _confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        """Prompt user for cost confirmation on expensive tools."""
        console.print()
        console.print("  [bold yellow]$ Cost confirmation[/bold yellow]")
        console.print(f"  [dim]Tool:[/dim] [bold]{tool_name}[/bold]")
        console.print(f"  [dim]Estimated cost:[/dim] ~${estimated_cost:.2f}")
        console.print()
        try:
            response = console.input("  [bold cyan]Proceed? [Y/n][/bold cyan] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False
        return response in ("", "y", "yes")

    def _request_approval(self, command: str, reason: str) -> bool:
        """Prompt user for bash command approval."""
        console.print()
        console.print("  [bold yellow]⚠ Bash command requires approval[/bold yellow]")
        console.print(f"  [dim]Command:[/dim] [bold]{command}[/bold]")
        if reason:
            console.print(f"  [dim]Reason:[/dim]  {reason}")
        console.print()

        try:
            response = console.input("  [bold cyan]Allow? [Y/n][/bold cyan] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False

        return response in ("", "y", "yes")

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())
