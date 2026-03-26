"""ToolExecutor — route tool calls to handlers with HITL safety checks.

Central dispatch for all tools available to the AgenticLoop.
Classifies tools by safety level and gates dangerous operations
behind user approval.

Also contains ToolCallProcessor — orchestrates parallel/sequential
execution of tool_use blocks returned by the LLM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.error_recovery import ErrorRecoveryStrategy
    from core.agent.sub_agent import SubAgentManager
    from core.cli.ui.agentic_ui import OperationLogger
    from core.orchestration.hooks import HookSystem

from core.cli.bash_tool import BashTool
from core.cli.ui.console import console

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
        "manage_context",
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
    "manage_auth": "Show the user the /auth command to manage auth profiles.",
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
        hitl_level: int = 2,
    ) -> None:
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = action_handlers or {}
        self._bash = bash_tool or BashTool()
        self._auto_approve = auto_approve  # for testing only
        self._sub_agent_manager = sub_agent_manager
        self._mcp_manager = mcp_manager
        # HITL level: 0=autonomous, 1=write-only, 2=all prompts
        self._hitl_level = hitl_level
        # Per-server MCP approval cache — approve once per server per session
        # Thread-safe: ToolExecutor is per-AgenticLoop, but sub-agents may share.
        import threading

        self._approval_lock = threading.Lock()
        self._mcp_approved_servers: set[str] = set()
        # Session-level "Always" approval sets (Feature: A=Always)
        self._always_approved_tools: set[str] = set()
        # Categories: "bash", "write", "cost", "mcp:<server>"
        self._always_approved_categories: set[str] = set()

    def _prompt_with_always(self, label: str, detail: str) -> str:
        """Show a [Y/n/A] prompt and return 'y', 'n', or 'a'.

        Args:
            label: Header text (e.g., "Bash command requires approval")
            detail: Detail text already printed before this call

        Returns:
            'y' for yes, 'n' for no, 'a' for always (session-level)
        """
        from core.cli import _restore_terminal

        _restore_terminal()
        try:
            response = console.input(f"  [header]{label} [Y/n/A][/header] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return "n"
        if response in ("a", "always"):
            return "a"
        if response in ("", "y", "yes"):
            return "y"
        return "n"

    def register(self, tool_name: str, handler: Callable[..., dict[str, Any]]) -> None:
        """Register a tool handler."""
        self._handlers[tool_name] = handler

    def _apply_safety_gates(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, bool]:
        """Check HITL gates. Returns (rejection_result, approved_via_hitl).

        If the first element is not None, the tool was rejected — return it immediately.
        """
        # Dangerous tools: always require HITL
        if tool_name in DANGEROUS_TOOLS:
            return self._execute_dangerous(tool_name, tool_input), False

        approved = False

        # Write tools: require approval (hitl_level 0 = autonomous skip)
        if tool_name in WRITE_TOOLS:
            if self._hitl_level == 0 or "write" in self._always_approved_categories:
                approved = True
            elif not self._confirm_write(tool_name, tool_input):
                return _write_denial_with_fallback(tool_name), False
            else:
                approved = True

        # Expensive tools: cost confirmation
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            if self._hitl_level == 0 or "cost" in self._always_approved_categories:
                approved = True
            else:
                cost = EXPENSIVE_TOOLS[tool_name]
                if not self._confirm_cost(tool_name, cost):
                    return {"error": "User denied expensive operation", "denied": True}, False
                approved = True

        return None, approved

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
            return {"error": str(exc)}

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

        # P2-C: progress callback — consolidated progress line (Claude Code pattern)
        completed_count = 0
        total_count = len(sub_tasks)
        _start_ts = time.time()

        def _on_progress(result: Any) -> None:
            nonlocal completed_count
            completed_count += 1
            status = "ok" if result.success else "err"
            # Single overwriting line — no scroll flood
            sys.stdout.write(
                f"\r\x1b[2K  \x1b[2msub-agent {completed_count}/{total_count} {status}\x1b[0m"
            )
            sys.stdout.flush()

        results = self._sub_agent_manager.delegate(sub_tasks, on_progress=_on_progress)

        # Clear progress line and show final summary
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.flush()
        from core.cli.ui.agentic_ui import render_subagent_complete

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

        # Safe read-only commands skip HITL approval for reduced friction.
        # Dangerous patterns are already blocked above (validate).
        cmd_stripped = command.strip()
        is_safe_cmd = any(cmd_stripped.startswith(p) for p in SAFE_BASH_PREFIXES)

        if not is_safe_cmd:
            # HITL level 0/1: skip bash approval entirely
            if self._hitl_level <= 1:
                pass  # auto-approve
            # Session-level "Always" approval for bash category
            elif "bash" in self._always_approved_categories:
                pass  # already approved for session
            else:
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
        # hitl_level 0/1: auto-approve all MCP tools
        if server in AUTO_APPROVED_MCP_SERVERS:
            self._mcp_approved_servers.add(server)
        mcp_category = f"mcp:{server}"
        if mcp_category in self._always_approved_categories:
            self._mcp_approved_servers.add(server)
        if self._hitl_level <= 1:
            self._mcp_approved_servers.add(server)
        if not self._auto_approve and server not in self._mcp_approved_servers:
            if not self._confirm_mcp(server, tool_name):
                return {"error": "User denied MCP tool execution", "denied": True}
            self._mcp_approved_servers.add(server)

        assert self._mcp_manager is not None  # guaranteed by caller
        with _tool_spinner(f"Calling {server}/{tool_name}..."):
            result: dict[str, Any] = self._mcp_manager.call_tool(server, tool_name, tool_input)

        # Sandbox hardening: redact secrets from MCP tool results
        from core.cli.redaction import redact_secrets

        for key in ("stdout", "stderr", "output", "content", "text", "result"):
            if key in result and isinstance(result[key], str):
                result[key] = redact_secrets(result[key])
        return result

    def _confirm_mcp(self, server: str, tool_name: str) -> bool:
        """Prompt user for MCP tool confirmation with A=Always option."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]MCP tool requires approval[/warning]")
        console.print(f"  [dim]Server:[/dim] [bold]{server}[/bold]")
        console.print(f"  [dim]Tool:[/dim]   [bold]{tool_name}[/bold]")
        console.print()

        response = self._prompt_with_always("Allow?", f"{server}/{tool_name}")
        if response == "a":
            self._always_approved_categories.add(f"mcp:{server}")
            return True
        return response == "y"

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

        response = self._prompt_with_always("Allow?", tool_name)
        if response == "a":
            self._always_approved_categories.add("write")
            return True
        return response == "y"

    def _confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        """Prompt user for cost confirmation on expensive tools with A=Always option."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]$ Cost confirmation[/warning]")
        console.print(f"  [dim]Tool:[/dim] [bold]{tool_name}[/bold]")
        console.print(f"  [dim]Estimated cost:[/dim] ~${estimated_cost:.2f}")
        # Show pipeline model info for analysis tools
        if tool_name in ("analyze_ip", "compare_ips", "batch_analyze"):
            from core.config import ANTHROPIC_PRIMARY, get_node_model

            primary = get_node_model("analyst") or ANTHROPIC_PRIMARY
            console.print(f"  [dim]Pipeline model:[/dim] {primary}")
        console.print()

        response = self._prompt_with_always("Proceed?", tool_name)
        if response == "a":
            self._always_approved_categories.add("cost")
            return True
        return response == "y"

    def _request_approval(self, command: str, reason: str) -> bool:
        """Prompt user for bash command approval with A=Always option."""
        from core.cli import _restore_terminal

        _restore_terminal()
        console.print()
        console.print("  [warning]Bash command requires approval[/warning]")
        console.print(f"  [dim]Command:[/dim] [value]{command}[/value]")
        if reason:
            console.print(f"  [dim]Reason:[/dim]  {reason}")
        console.print()

        response = self._prompt_with_always("Allow?", command)
        if response == "a":
            self._always_approved_categories.add("bash")
            return True
        return response == "y"

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())


# ---------------------------------------------------------------------------
# ToolCallProcessor — orchestrate parallel/sequential tool_use execution
# ---------------------------------------------------------------------------


def _compute_model_tool_limit(model: str) -> int:
    """Compute per-tool-result token limit based on model context window.

    For large-context models (>=200K), returns 0 (unlimited — server-side handles it).
    For small-context models (<200K, e.g. GLM-5 80K), caps each tool result at 5% of
    the context window to prevent a single result from consuming the budget.
    """
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)
    if ctx >= 200_000:
        return 0  # trust server-side clear_tool_uses
    return ctx // 20  # 5% of context window


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary.

    When *max_tokens* is 0 (default), no truncation is performed.
    """
    from core.config import settings as _settings

    if max_tokens is None:
        max_tokens = _settings.max_tool_result_tokens
    if max_tokens <= 0:
        return result
    try:
        serialized = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return result
    estimated_tokens = len(serialized) // 4
    if estimated_tokens <= max_tokens:
        return result
    # Preserve summary if present (SubAgentResult always has one)
    if "summary" in result:
        guarded: dict[str, Any] = {
            "summary": result["summary"],
            "_truncated": True,
            "_original_tokens": estimated_tokens,
        }
        for key in ("task_id", "task_type", "status", "error_message", "tier"):
            if key in result:
                guarded[key] = result[key]
        return guarded
    return {
        "_truncated": True,
        "_original_tokens": estimated_tokens,
        "preview": serialized[: max_tokens * 4],
    }


class ToolCallProcessor:
    """Orchestrate parallel/sequential execution of tool_use blocks.

    Extracted from AgenticLoop to separate tool call processing
    (dispatch, tracking, tiering, parallel execution) from the
    conversational loop logic.

    The processor holds per-run mutable state (consecutive failures,
    tool log, clarification count) that is reset via ``reset()``
    at the start of each agentic run.
    """

    MAX_CONSECUTIVE_FAILURES = 2
    MAX_CLARIFICATION_ROUNDS = 3

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        op_logger: OperationLogger,
        error_recovery: ErrorRecoveryStrategy,
        hooks: HookSystem | None = None,
        mcp_manager: Any | None = None,
        transcript: Any | None = None,
        model: str = "",
    ) -> None:
        self._executor = executor
        self._op_logger = op_logger
        self._error_recovery = error_recovery
        self._hooks = hooks
        self._mcp_manager = mcp_manager
        self._transcript = transcript
        self._model = model

        # Per-run mutable state — reset via reset()
        self._consecutive_failures: dict[str, int] = {}
        self._tool_log: list[dict[str, Any]] = []
        self._clarification_count: int = 0

    def reset(self) -> None:
        """Reset per-run tracking state. Call at the start of each agentic run."""
        self._consecutive_failures.clear()
        self._tool_log.clear()
        self._clarification_count = 0

    @property
    def tool_log(self) -> list[dict[str, Any]]:
        """Read-only access to the tool execution log."""
        return self._tool_log

    async def process(self, response: Any) -> list[dict[str, Any]]:
        """Execute tool_use blocks — parallel when multiple, sequential when single.

        When the LLM returns 2+ tool_use blocks in one response, executes them
        concurrently via ``asyncio.gather``.  Single tool_use falls through to
        the sequential path for zero-overhead backward compatibility.

        Tracks consecutive failures per tool name.  After MAX_CONSECUTIVE_FAILURES
        for the same tool, triggers the adaptive error recovery chain.
        """
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        if len(tool_blocks) <= 1:
            return await self._execute_sequential(tool_blocks)

        return await self._execute_parallel(tool_blocks)

    async def _execute_single(self, block: Any) -> dict[str, Any]:
        """Execute a single tool_use block and return its processed result dict.

        Handles consecutive failure tracking, recovery, clarification guards,
        logging, tool_log bookkeeping, and token guard.

        Returns a dict ready to be used as a tool_result content block
        (with ``type``, ``tool_use_id``, ``content`` keys).
        """
        tool_name = block.name
        tool_input: dict[str, Any] = block.input

        log.info("ToolCallProcessor: tool_use %s(%s)", tool_name, tool_input)

        # Check consecutive failure count
        fail_count = self._consecutive_failures.get(tool_name, 0)

        if fail_count >= self.MAX_CONSECUTIVE_FAILURES:
            # Adaptive recovery: try recovery chain instead of auto-skip
            result = await self._attempt_recovery(tool_name, tool_input, fail_count)
            visible = self._op_logger.log_tool_call(tool_name, tool_input)
            self._op_logger.log_tool_result(tool_name, result, visible=visible)
        else:
            # Progressive log: show tool call before execution
            visible = self._op_logger.log_tool_call(tool_name, tool_input)

            # Execute via ToolExecutor (sync handlers wrapped in to_thread)
            result = await asyncio.to_thread(self._executor.execute, tool_name, tool_input)

        # Track consecutive failures
        if isinstance(result, dict) and result.get("error"):
            if not result.get("recovery_attempted"):
                self._consecutive_failures[tool_name] = fail_count + 1
        else:
            self._consecutive_failures[tool_name] = 0

        # Track clarification rounds to prevent infinite loops
        if isinstance(result, dict) and result.get("clarification_needed"):
            self._clarification_count += 1
            if self._clarification_count > self.MAX_CLARIFICATION_ROUNDS:
                result = {
                    "error": (
                        "Too many clarification attempts. Please provide all required parameters."
                    ),
                    "max_clarifications_exceeded": True,
                }

        # Progressive log: show tool result summary (skip if already logged)
        skip_log = result.get("skipped") or result.get("recovery_attempted")
        if isinstance(result, dict) and not skip_log:
            self._op_logger.log_tool_result(tool_name, result, visible=visible)

        # Transcript: tool_call + tool_result events
        if self._transcript is not None:
            self._transcript.record_tool_call(tool_name, tool_input)
            status = "error" if isinstance(result, dict) and result.get("error") else "ok"
            summary = ""
            if isinstance(result, dict):
                summary = str(result.get("summary", result.get("error", "")))
            self._transcript.record_tool_result(tool_name, status, summary)

        self._tool_log.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "result": result,
            }
        )

        # Token guard: truncate oversized results to prevent context explosion
        # For small-context models (e.g. GLM-5 80K), apply model-aware limit
        if isinstance(result, dict):
            model_limit = _compute_model_tool_limit(self._model) if self._model else 0
            result = _guard_tool_result(result, max_tokens=model_limit or None)

        # Serialize result as JSON for LLM (not Python repr)
        try:
            content = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(result)

        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    async def _execute_sequential(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute tool blocks one by one (single-tool fast path)."""
        tool_results: list[dict[str, Any]] = []
        for block in tool_blocks:
            tool_result = await self._execute_single(block)
            tool_results.append(tool_result)
        return tool_results

    # -- Tier classification for parallel execution --------------------------

    @staticmethod
    def _classify_tier(tool_name: str, mcp_manager: Any | None = None) -> int:
        """Classify a tool into a safety tier for parallel execution.

        TIER 0: SAFE tools — auto-execute, no gate
        TIER 1: MCP auto-approved — auto-execute, logged
        TIER 2: EXPENSIVE tools — batch cost confirmation, then parallel
        TIER 3: WRITE tools — individual approval, sequential
        TIER 4: DANGEROUS tools — individual approval, sequential
        Unclassified (STANDARD) tools default to TIER 0 (parallel-safe).
        """
        if tool_name in DANGEROUS_TOOLS:
            return 4
        if tool_name in WRITE_TOOLS:
            return 3
        if tool_name in EXPENSIVE_TOOLS:
            return 2
        if mcp_manager is not None:
            server = mcp_manager.find_server_for_tool(tool_name)
            if server is not None:
                if server in AUTO_APPROVED_MCP_SERVERS:
                    return 1
                return 3
        if tool_name in SAFE_TOOLS:
            return 0
        return 0

    async def _execute_parallel(self, tool_blocks: list[Any]) -> list[dict[str, Any]]:
        """Execute 2+ tool blocks with tiered batch approval.

        Tier classification:
          TIER 0-1 (SAFE/MCP auto-approved): start immediately in parallel
          TIER 2 (EXPENSIVE): batch cost confirmation -> parallel execution
          TIER 3-4 (WRITE/DANGEROUS): individual approval -> sequential

        Results are returned in the same order as the input tool_use blocks
        to satisfy the Anthropic API ordering requirement.
        """
        log.info(
            "ToolCallProcessor: parallel execution of %d tools: %s",
            len(tool_blocks),
            [b.name for b in tool_blocks],
        )

        # Step 1: Classify blocks into tiers
        tiered: dict[int, list[tuple[int, Any]]] = {0: [], 1: [], 2: [], 3: [], 4: []}
        for idx, block in enumerate(tool_blocks):
            tier = self._classify_tier(block.name, self._mcp_manager)
            tiered[tier].append((idx, block))
            log.debug("Tool %s -> tier %d", block.name, tier)

        # Pre-allocate result slots in original order
        results: list[dict[str, Any] | None] = [None] * len(tool_blocks)

        # Step 2: Batch cost approval for TIER 2 (EXPENSIVE) tools
        tier2_approved = True
        if tiered[2]:
            tier2_approved = await self._batch_cost_approval([block for _, block in tiered[2]])

        # Step 3: Build parallel tasks for TIER 0 + TIER 1 + approved TIER 2
        parallel_items: list[tuple[int, Any]] = []
        parallel_items.extend(tiered[0])
        parallel_items.extend(tiered[1])

        if tier2_approved:
            parallel_items.extend(tiered[2])
        else:
            for idx, block in tiered[2]:
                results[idx] = self._make_denial_result(block, "User denied batch cost approval")

        # Step 4: Execute parallel pool
        if parallel_items:
            old_auto_approve = self._executor._auto_approve
            if tier2_approved and tiered[2]:
                self._executor._auto_approve = True

            try:
                gathered = await asyncio.gather(
                    *[self._safe_execute_single(block) for _, block in parallel_items]
                )
            finally:
                if tier2_approved and tiered[2]:
                    self._executor._auto_approve = old_auto_approve

            for (idx, _block), result in zip(parallel_items, gathered, strict=True):
                results[idx] = result

        # Step 5: Execute TIER 3-4 (WRITE/DANGEROUS) sequentially
        sequential_items = list(tiered[3]) + list(tiered[4])
        for idx, block in sequential_items:
            results[idx] = await self._execute_single(block)

        return [r for r in results if r is not None]

    async def _safe_execute_single(self, block: Any) -> dict[str, Any]:
        """Wrapper that catches unexpected exceptions per tool."""
        try:
            return await self._execute_single(block)
        except Exception as exc:
            log.error(
                "Parallel tool %s raised unexpected error: %s",
                block.name,
                exc,
                exc_info=True,
            )
            return self._make_error_result(block, exc)

    async def _batch_cost_approval(self, blocks: list[Any]) -> bool:
        """Show a single cost confirmation prompt for all EXPENSIVE tools.

        Returns True if user approves, False if denied.
        """
        items: list[tuple[str, dict[str, Any], float]] = []
        for block in blocks:
            cost = EXPENSIVE_TOOLS.get(block.name, 0.0)
            items.append((block.name, block.input, cost))

        total_cost = sum(c for _, _, c in items)

        def _prompt() -> bool:
            try:
                from core.cli import _restore_terminal

                _restore_terminal()
            except Exception:
                log.debug("_restore_terminal() unavailable in batch approval")

            console.print()
            console.print("  [warning]$ Cost confirmation[/warning]")
            count = len(items)
            plural = "s" if count > 1 else ""
            verb = "s" if count == 1 else ""
            console.print(f"  {count} tool{plural} require{verb} approval:")
            for name, inp, cost in items:
                args_preview = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                console.print(f"    [dim]--[/dim] {name}({args_preview}) -- ~${cost:.2f}")
            console.print(f"  [dim]Total estimated cost:[/dim] ~${total_cost:.2f}")
            console.print()
            try:
                response = console.input("  [header]Proceed? [Y/n][/header] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                console.print()
                return False
            return response in ("", "y", "yes")

        return await asyncio.to_thread(_prompt)

    async def _attempt_recovery(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        fail_count: int,
    ) -> dict[str, Any]:
        """Attempt adaptive error recovery for a repeatedly failing tool.

        Runs the recovery chain in a background thread (sync executor calls)
        and emits hook events for observability.
        """
        self._emit_hook(
            "tool_recovery_attempted",
            {
                "tool_name": tool_name,
                "fail_count": fail_count,
                "source": "tool_call_processor",
            },
        )

        recovery_result = await asyncio.to_thread(
            self._error_recovery.recover,
            tool_name,
            tool_input,
            fail_count,
        )

        if recovery_result.recovered:
            self._consecutive_failures[tool_name] = 0
            self._emit_hook(
                "tool_recovery_succeeded",
                {
                    "tool_name": tool_name,
                    "strategy": recovery_result.strategy_used.value
                    if recovery_result.strategy_used
                    else "unknown",
                    "attempts": len(recovery_result.attempts),
                    "source": "tool_call_processor",
                },
            )
            result = dict(recovery_result.final_result)
            result["recovery_summary"] = recovery_result.to_summary()
            result["recovery_attempted"] = True
            return result

        self._emit_hook(
            "tool_recovery_failed",
            {
                "tool_name": tool_name,
                "attempts": len(recovery_result.attempts),
                "strategies_tried": [a.strategy.value for a in recovery_result.attempts],
                "source": "tool_call_processor",
            },
        )
        result = dict(recovery_result.final_result)
        result["recovery_summary"] = recovery_result.to_summary()
        result["recovery_attempted"] = True
        result["skipped"] = True
        return result

    def _emit_hook(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a hook event if HookSystem is configured."""
        if self._hooks is None:
            return
        try:
            from core.orchestration.hooks import HookEvent as _HookEvent

            event = _HookEvent(event_name)
            self._hooks.trigger(event, data)
        except Exception:
            log.debug("Hook trigger failed for %s", event_name, exc_info=True)

    @staticmethod
    def _make_denial_result(block: Any, reason: str) -> dict[str, Any]:
        """Build a tool_result for a denied tool execution."""
        error_result = {"error": reason, "denied": True}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }

    @staticmethod
    def _make_error_result(block: Any, exc: Exception) -> dict[str, Any]:
        """Build a tool_result for an unexpected exception."""
        error_result = {"error": str(exc)}
        try:
            content = json.dumps(error_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content = str(error_result)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
        }
