"""ToolExecutor — route tool calls to handlers with HITL safety checks.

Central dispatch for all tools available to the AgenticLoop.
Classifies tools by safety level and gates dangerous operations
behind user approval.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.cli.bash_tool import BashTool
from core.ui.console import console

log = logging.getLogger(__name__)

# Tool safety classifications
SAFE_TOOLS: frozenset[str] = frozenset({
    "list_ips",
    "search_ips",
    "show_help",
    "check_status",
    "switch_model",
    "memory_search",
    "manage_rule",
})

DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "run_bash",
})

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
    ) -> None:
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = action_handlers or {}
        self._bash = bash_tool or BashTool()
        self._auto_approve = auto_approve  # for testing only

    def register(self, tool_name: str, handler: Callable[..., dict[str, Any]]) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call, applying HITL gate if needed."""
        log.debug("ToolExecutor: %s(%s)", tool_name, tool_input)

        # Dangerous tools: HITL gate
        if tool_name in DANGEROUS_TOOLS:
            return self._execute_dangerous(tool_name, tool_input)

        # Delegate to registered handler
        handler = self._handlers.get(tool_name)
        if handler is None:
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(**tool_input)
        except Exception as exc:
            log.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return {"error": str(exc)}

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
