"""ToolExecutor — route tool calls to handlers with HITL safety checks.

Central dispatch for all tools available to the AgenticLoop.
Classifies tools by safety level and gates dangerous operations
behind user approval.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
        "profile_show",
        "calendar_list_events",
    }
)

DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "run_bash",
    }
)

# Write tools modify persistent state (credentials, memory, files).
# Require explicit user confirmation — never auto-approved, even for sub-agents.
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_auth",
        "profile_update",
        "profile_preference",
        "profile_learn",
        "calendar_create_event",
        "calendar_sync_scheduler",
    }
)

# Expensive tools require cost confirmation before execution
EXPENSIVE_TOOLS: dict[str, float] = {
    "analyze_ip": 1.50,
    "batch_analyze": 5.00,
    "compare_ips": 3.00,
}

# Bash commands starting with these prefixes are safe (read-only, no side effects).
# They execute without HITL approval to reduce friction for common queries.
SAFE_BASH_PREFIXES: tuple[str, ...] = (
    "cat ",
    "head ",
    "tail ",
    "ls ",
    "ls\n",
    "pwd",
    "echo ",
    "wc ",
    "grep ",
    "rg ",
    "find ",
    "which ",
    "whoami",
    "date",
    "env ",
    "printenv",
    "uname",
    "df ",
    "du ",
    "file ",
    "stat ",
    "curl -s",
    "curl --silent",
    "python3 -c",
    "python -c",
    "uv run pytest",
    "uv run ruff",
    "uv run mypy",
    "uv run python",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "git remote",
    "gh pr",
    "gh run",
    "gh api",
)

# MCP servers that are read-only and auto-approved (no HITL gate on first call).
AUTO_APPROVED_MCP_SERVERS: frozenset[str] = frozenset(
    {
        "brave-search",
        "steam",
        "arxiv",
        "linkedin-reader",
    }
)

# Everything else is STANDARD — executes without special gates


@contextmanager
def _tool_spinner(label: str) -> Iterator[None]:
    """Show a Rich dots spinner during post-approval tool execution.

    Displays ``label`` with a spinner while the wrapped block runs,
    then clears it on exit so OperationLogger markers (✓/✗) render cleanly.
    """
    status = console.status(f"  [dim]✢ {label}[/dim]", spinner="dots", spinner_style="cyan")
    status.start()
    try:
        yield
    finally:
        status.stop()


# Write fallback suggestions per tool — helps LLM recover from denial
_WRITE_FALLBACK_HINTS: dict[str, str] = {
    "memory_save": "Try memory_search to read existing data instead.",
    "note_save": "Try reading existing notes or suggest the content to the user.",
    "set_api_key": "Show the user the /key command to set it themselves.",
    "profile_update": "Show current profile with profile_get instead.",
    "profile_preference": "Show current preferences with profile_get instead.",
    "profile_learn": "Show current learning patterns with profile_get instead.",
    "calendar_create_event": "Try calendar_list_events to show existing events.",
    "calendar_sync_scheduler": "Show the user /schedule command to manage manually.",
}


def _write_denial_with_fallback(tool_name: str) -> dict[str, Any]:
    """Return a denial result with a fallback suggestion for the LLM."""
    hint = _WRITE_FALLBACK_HINTS.get(tool_name, "")
    fallback_msg = (
        f"User denied write operation for '{tool_name}'. "
        "Do NOT retry this tool without explicit user request."
    )
    if hint:
        fallback_msg += f" Suggestion: {hint}"
    return {"error": fallback_msg, "denied": True, "fallback_hint": hint}


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
        # Per-server MCP approval cache — approve once per server per session
        self._mcp_approved_servers: set[str] = set()

    def register(self, tool_name: str, handler: Callable[..., dict[str, Any]]) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call, applying HITL gate if needed."""
        log.debug("ToolExecutor: %s(%s)", tool_name, tool_input)

        # Dangerous tools: HITL gate (never auto-approved)
        if tool_name in DANGEROUS_TOOLS:
            return self._execute_dangerous(tool_name, tool_input)

        # Track whether user went through an approval gate — if so, show
        # a spinner during handler execution for visual feedback.
        approved_via_hitl = False

        # Write tools: HITL gate — always requires approval, even for
        # sub-agents (auto_approve is intentionally ignored here).
        if tool_name in WRITE_TOOLS:
            if not self._confirm_write(tool_name, tool_input):
                return _write_denial_with_fallback(tool_name)
            approved_via_hitl = True

        # Expensive tools: cost confirmation gate
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            cost = EXPENSIVE_TOOLS[tool_name]
            if not self._confirm_cost(tool_name, cost):
                return {
                    "error": "User denied expensive operation",
                    "denied": True,
                }
            approved_via_hitl = True

        # Sub-agent delegation
        if tool_name == "delegate_task":
            return self._execute_delegate(tool_input)

        # Delegate to registered handler
        handler = self._handlers.get(tool_name)
        if handler is None:
            # MCP fallback: route through safety checks
            if self._mcp_manager is not None:
                server = self._mcp_manager.find_server_for_tool(tool_name)
                if server is not None:
                    return self._execute_mcp(server, tool_name, tool_input)
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            if approved_via_hitl:
                with _tool_spinner(f"Executing {tool_name}..."):
                    return handler(**tool_input)
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
        """
        command = tool_input.get("command", "")
        reason = tool_input.get("reason", "")

        if not command:
            return {"error": "No command provided"}

        # Check blocked patterns first
        blocked = self._bash.validate(command)
        if blocked:
            return self._bash.to_tool_result(blocked)

        # Safe read-only commands skip HITL approval for reduced friction.
        # Dangerous patterns are already blocked above (validate).
        cmd_stripped = command.strip()
        is_safe_cmd = any(cmd_stripped.startswith(p) for p in SAFE_BASH_PREFIXES)

        if not is_safe_cmd:
            # HITL approval gate — not skipped for non-safe commands.
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
        # Read-only servers in AUTO_APPROVED_MCP_SERVERS skip first-call approval.
        # After first approval, subsequent calls to the same server auto-execute.
        if server in AUTO_APPROVED_MCP_SERVERS:
            self._mcp_approved_servers.add(server)
        if not self._auto_approve and server not in self._mcp_approved_servers:
            if not self._confirm_mcp(server, tool_name):
                return {"error": "User denied MCP tool execution", "denied": True}
            self._mcp_approved_servers.add(server)

        assert self._mcp_manager is not None  # guaranteed by caller
        with _tool_spinner(f"Calling {server}/{tool_name}..."):
            result: dict[str, Any] = self._mcp_manager.call_tool(server, tool_name, tool_input)
        return result

    def _confirm_mcp(self, server: str, tool_name: str) -> bool:
        """Prompt user for MCP tool confirmation."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]MCP tool requires approval[/warning]")
        console.print(f"  [dim]Server:[/dim] [bold]{server}[/bold]")
        console.print(f"  [dim]Tool:[/dim]   [bold]{tool_name}[/bold]")
        console.print()
        try:
            response = console.input("  [header]Allow? [Y/n][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False
        return response in ("", "y", "yes")

    def _confirm_write(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Prompt user for write operation confirmation."""
        from core.cli import _restore_terminal

        _restore_terminal()
        summary = ""
        if tool_name == "memory_save":
            summary = tool_input.get("content", tool_input.get("value", ""))[:80]
        elif tool_name == "note_save":
            summary = tool_input.get("content", "")[:80]
        elif tool_name == "set_api_key":
            summary = f"provider={tool_input.get('provider', '?')}"
        elif tool_name == "manage_auth":
            summary = f"action={tool_input.get('action', '?')}"
        elif tool_name == "profile_update":
            fields = [k for k in ("role", "expertise", "name", "team") if tool_input.get(k)]
            summary = f"fields={','.join(fields)}" if fields else "profile update"
        elif tool_name == "profile_preference":
            summary = f"{tool_input.get('key', '?')}={tool_input.get('value', '?')}"
        elif tool_name == "profile_learn":
            summary = tool_input.get("pattern", "")[:80]

        console.print()
        console.print("  [warning]Write operation requires approval[/warning]")
        console.print(f"  [dim]Tool:[/dim]    [bold]{tool_name}[/bold]")
        if summary:
            console.print(f"  [dim]Summary:[/dim] {summary}")
        console.print()
        try:
            response = console.input("  [header]Allow? [Y/n][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False
        return response in ("", "y", "yes")

    def _confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        """Prompt user for cost confirmation on expensive tools."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]$ Cost confirmation[/warning]")
        console.print(f"  [dim]Tool:[/dim] [bold]{tool_name}[/bold]")
        console.print(f"  [dim]Estimated cost:[/dim] ~${estimated_cost:.2f}")
        console.print()
        try:
            response = console.input("  [header]Proceed? [Y/n][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False
        return response in ("", "y", "yes")

    def _request_approval(self, command: str, reason: str) -> bool:
        """Prompt user for bash command approval."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]Bash command requires approval[/warning]")
        console.print(f"  [dim]Command:[/dim] [value]{command}[/value]")
        if reason:
            console.print(f"  [dim]Reason:[/dim]  {reason}")
        console.print()

        try:
            response = console.input("  [header]Allow? [Y/n][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return False

        return response in ("", "y", "yes")

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())
