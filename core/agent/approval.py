"""HITL Approval Workflow — extracted from ToolExecutor for SRP.

Manages user approval gates for dangerous, write, expensive, and MCP tools.
Tracks session-scoped approval patterns (auto-approve after 3 consecutive
approvals, auto-deny after 3 consecutive denials).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from core.agent.safety import (
    AUTO_APPROVED_MCP_SERVERS,
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    WRITE_TOOLS,
    is_bash_command_read_only,
)
from core.hooks.system import HookEvent
from core.ui.console import console

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)

_AUTO_APPROVE_THRESHOLD = 3
_AUTO_DENY_THRESHOLD = 3
_T = TypeVar("_T")


def _write_denial_with_fallback(tool_name: str) -> dict[str, Any]:
    """Build a denial result with fallback suggestion for write tools."""
    _WRITE_FALLBACK_HINTS: dict[str, str] = {
        "memory_save": "Try memory_search to read existing data instead.",
        "note_save": "Try reading existing notes or suggest the content to the user.",
        "set_api_key": "Show the user the /login command to set it themselves.",
        "manage_auth": "Show the user the /login command to manage credentials.",
        "manage_login": "Show the user the /login command to register plans / keys / OAuth.",
        "profile_update": "Show current profile with profile_get instead.",
        "profile_preference": "Show current preferences with profile_get instead.",
        "profile_learn": "Show current learning patterns with profile_get instead.",
        "calendar_create_event": "Try calendar_list_events to show existing events.",
        "calendar_sync_scheduler": "Show the user /schedule command to manage manually.",
    }
    hint = _WRITE_FALLBACK_HINTS.get(tool_name, "")
    msg = (
        f"User denied write operation for '{tool_name}'. "
        "Do NOT retry this tool without explicit user request."
    )
    if hint:
        msg += f" Suggestion: {hint}"
    return {"error": msg, "denied": True, "fallback_hint": hint}


class ApprovalWorkflow:
    """HITL approval orchestration for tool safety gates.

    Extracted from ToolExecutor to isolate approval concerns.
    Uses composition: ToolExecutor creates and owns this instance.
    """

    def __init__(
        self,
        *,
        auto_approve: bool = False,
        hitl_level: int = 2,
        hooks: HookSystem | None = None,
        approval_callback: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._auto_approve = auto_approve
        self._hitl_level = hitl_level
        self._hooks = hooks
        self._approval_callback = approval_callback

        import threading

        self._approval_lock = threading.Lock()
        self._mcp_approved_servers: set[str] = set()
        self._always_approved_tools: set[str] = set()
        self._always_approved_categories: set[str] = set()
        self._tool_approval_counts: dict[str, int] = {}
        self._tool_denial_counts: dict[str, int] = {}
        # Computer-use is a DANGEROUS, continuous-control tool — per-action HITL
        # is impractical, so it is approved ONCE per session (then remembered).
        self._computer_approved: bool = False

    @staticmethod
    def _skip_permissions() -> bool:
        """``--dangerously-skip-permissions`` — read DYNAMICALLY (per gate call).

        Resolves the PER-SESSION ContextVar (set by the IPC capability
        handshake before the first prompt) at gate time, not cached at executor
        construction: the daemon builds the executor at CONNECTION time, the
        flag arrives AFTER. Per-session isolation means a concurrent skip
        session can't flip another session's gates (see
        :func:`core.agent.safety.current_skip_permissions`).
        """
        from core.agent.safety import current_skip_permissions

        return current_skip_permissions()

    def _fire_hook(self, event: HookEvent, data: dict[str, Any]) -> None:
        if self._hooks is None:
            return
        try:
            self._hooks.trigger(event, data)
        except Exception:
            log.debug("Hook fire failed for %s", event, exc_info=True)

    async def _fire_hook_async(self, event: HookEvent, data: dict[str, Any]) -> None:
        if self._hooks is None:
            return
        try:
            await self._hooks.trigger_async(event, data)
        except Exception:
            log.debug("Async hook fire failed for %s", event, exc_info=True)

    async def _with_approval_locks(self, body: Callable[[], Awaitable[_T]]) -> _T:
        """Serialize async prompts with both async and legacy sync approval paths."""
        await asyncio.to_thread(self._approval_lock.acquire)
        try:
            return await body()
        finally:
            self._approval_lock.release()

    # -----------------------------------------------------------------
    # Pattern learning
    # -----------------------------------------------------------------

    def track_decision(self, tool_name: str, decision: str) -> None:
        """Track per-tool approval/denial for session-scoped pattern learning."""
        if decision == "y":
            self._tool_approval_counts[tool_name] = self._tool_approval_counts.get(tool_name, 0) + 1
            self._tool_denial_counts.pop(tool_name, None)
            if self._tool_approval_counts[tool_name] >= _AUTO_APPROVE_THRESHOLD:
                self._always_approved_tools.add(tool_name)
                log.info("Auto-approved tool '%s' after 3 consecutive approvals", tool_name)
        elif decision == "n":
            self._tool_denial_counts[tool_name] = self._tool_denial_counts.get(tool_name, 0) + 1
            self._tool_approval_counts.pop(tool_name, None)

    def check_auto_deny(self, tool_name: str) -> bool:
        """Return True if tool has been denied 3+ times this session."""
        return self._tool_denial_counts.get(tool_name, 0) >= _AUTO_DENY_THRESHOLD

    # -----------------------------------------------------------------
    # Prompt
    # -----------------------------------------------------------------

    def prompt_with_always(
        self,
        label: str,
        detail: str,
        *,
        safety_level: str = "write",
        tool_name: str = "",
    ) -> str:
        """Show a [Y/n/A] prompt and return 'y', 'n', or 'a'."""
        if self._approval_callback is not None:
            decision = self._approval_callback(tool_name or label, detail, safety_level)
            log.debug("HITL: IPC callback decision=%s tool=%s", decision, tool_name or label)
            return decision

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

    async def prompt_with_always_async(
        self,
        label: str,
        detail: str,
        *,
        safety_level: str = "write",
        tool_name: str = "",
    ) -> str:
        """Async wrapper for approval prompts.

        Console input and IPC approval callbacks are blocking from the event
        loop's perspective, so they run in a worker thread.
        """
        return await asyncio.to_thread(
            self.prompt_with_always,
            label,
            detail,
            safety_level=safety_level,
            tool_name=tool_name,
        )

    # -----------------------------------------------------------------
    # Safety gate orchestration
    # -----------------------------------------------------------------

    def apply_safety_gates(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, bool]:
        """Check HITL gates. Returns (rejection_result, approved_via_hitl)."""
        if tool_name in DANGEROUS_TOOLS:
            # Dangerous tools handled separately by ToolExecutor._execute_dangerous
            return None, False

        approved = False

        # v0.52.2 — wrap the HITL prompt + always-set mutation under a single
        # mutex so parallel tool calls in the same round serialize their
        # approval prompts. Without this, two concurrent confirm_write() calls
        # both send approval_request to the thin client and the second blocks
        # on a recv() that no input ever satisfies (the user typed "A" once,
        # which the first prompt consumed). Result: 120s timeout → silent
        # denial. Bug 6 root cause from v0.52.1 incident.
        #
        # The lock also lets the second caller observe the first caller's
        # "A" → ``_always_approved_categories.add("write")`` and short-circuit
        # without re-prompting the user.

        # Write tools
        if tool_name in WRITE_TOOLS:
            with self._approval_lock:
                if (
                    self._skip_permissions()
                    or self._hitl_level == 0
                    or "write" in self._always_approved_categories
                    or tool_name in self._always_approved_tools
                ):
                    approved = True
                else:
                    self._fire_hook(
                        HookEvent.TOOL_APPROVAL_REQUESTED,
                        {"tool_name": tool_name, "safety_level": "write"},
                    )
                    if not self.confirm_write(tool_name, tool_input):
                        self._fire_hook(
                            HookEvent.TOOL_APPROVAL_DENIED,
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
                        HookEvent.TOOL_APPROVAL_GRANTED,
                        {
                            "tool_name": tool_name,
                            "safety_level": "write",
                            "always": "write" in self._always_approved_categories,
                        },
                    )
                    approved = True

        # Expensive tools
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            with self._approval_lock:
                if (
                    self._skip_permissions()
                    or self._hitl_level == 0
                    or "cost" in self._always_approved_categories
                    or tool_name in self._always_approved_tools
                ):
                    approved = True
                else:
                    cost = EXPENSIVE_TOOLS[tool_name]
                    self._fire_hook(
                        HookEvent.TOOL_APPROVAL_REQUESTED,
                        {"tool_name": tool_name, "safety_level": "cost"},
                    )
                    if not self.confirm_cost(tool_name, cost):
                        self._fire_hook(
                            HookEvent.TOOL_APPROVAL_DENIED,
                            {
                                "tool_name": tool_name,
                                "safety_level": "cost",
                                "permission_level": "HITL",
                                "decision": "denied",
                                "latency_ms": 0.0,
                            },
                        )
                        return {
                            "error": "User denied expensive operation",
                            "denied": True,
                        }, False
                    self._fire_hook(
                        HookEvent.TOOL_APPROVAL_GRANTED,
                        {
                            "tool_name": tool_name,
                            "safety_level": "cost",
                            "always": "cost" in self._always_approved_categories,
                        },
                    )
                    approved = True

        return None, approved

    async def apply_safety_gates_async(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, bool]:
        """Async HITL gate path used by ToolExecutor.aexecute()."""
        if tool_name in DANGEROUS_TOOLS:
            return None, False

        approved = False

        if tool_name in WRITE_TOOLS:

            async def write_gate() -> tuple[dict[str, Any] | None, bool]:
                if (
                    self._skip_permissions()
                    or self._hitl_level == 0
                    or "write" in self._always_approved_categories
                    or tool_name in self._always_approved_tools
                ):
                    return None, True
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_REQUESTED,
                    {"tool_name": tool_name, "safety_level": "write"},
                )
                if not await self.confirm_write_async(tool_name, tool_input):
                    await self._fire_hook_async(
                        HookEvent.TOOL_APPROVAL_DENIED,
                        {
                            "tool_name": tool_name,
                            "safety_level": "write",
                            "permission_level": "HITL",
                            "decision": "denied",
                            "latency_ms": 0.0,
                        },
                    )
                    return _write_denial_with_fallback(tool_name), False
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_GRANTED,
                    {
                        "tool_name": tool_name,
                        "safety_level": "write",
                        "always": "write" in self._always_approved_categories,
                    },
                )
                return None, True

            gate_result, approved = await self._with_approval_locks(write_gate)
            if gate_result is not None:
                return gate_result, False

        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:

            async def cost_gate() -> tuple[dict[str, Any] | None, bool]:
                if (
                    self._skip_permissions()
                    or self._hitl_level == 0
                    or "cost" in self._always_approved_categories
                    or tool_name in self._always_approved_tools
                ):
                    return None, True
                cost = EXPENSIVE_TOOLS[tool_name]
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_REQUESTED,
                    {"tool_name": tool_name, "safety_level": "cost"},
                )
                if not await self.confirm_cost_async(tool_name, cost):
                    await self._fire_hook_async(
                        HookEvent.TOOL_APPROVAL_DENIED,
                        {
                            "tool_name": tool_name,
                            "safety_level": "cost",
                            "permission_level": "HITL",
                            "decision": "denied",
                            "latency_ms": 0.0,
                        },
                    )
                    return {"error": "User denied expensive operation", "denied": True}, False
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_GRANTED,
                    {
                        "tool_name": tool_name,
                        "safety_level": "cost",
                        "always": "cost" in self._always_approved_categories,
                    },
                )
                return None, True

            gate_result, approved = await self._with_approval_locks(cost_gate)
            if gate_result is not None:
                return gate_result, False

        return None, approved

    # -----------------------------------------------------------------
    # Confirmation prompts
    # -----------------------------------------------------------------

    def confirm_mcp(self, server: str, tool_name: str) -> bool:
        """Prompt user for MCP tool confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print("  [warning]MCP tool requires approval[/warning]")
            console.print(f"  [dim]Server:[/dim] [bold]{server}[/bold]")
            console.print(f"  [dim]Tool:[/dim]   [bold]{tool_name}[/bold]")
            console.print()

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "MCP",
                "args_preview": f"server={server}",
            },
        )

        t0 = time.monotonic()
        response = self.prompt_with_always(
            "Allow?", f"{server}/{tool_name}", safety_level="mcp", tool_name=tool_name
        )
        latency_ms = (time.monotonic() - t0) * 1000
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add(f"mcp:{server}")
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": tool_name,
                    "permission_level": "MCP",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                },
            )
            return True
        self._fire_hook(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": tool_name,
                "permission_level": "MCP",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    async def confirm_mcp_async(self, server: str, tool_name: str) -> bool:
        """Async MCP tool confirmation with A=Always option."""

        async def gate() -> bool:
            if self._approval_callback is None:
                from core.cli import _restore_terminal

                _restore_terminal()
                console.print()
                console.print("  [warning]MCP tool requires approval[/warning]")
                console.print(f"  [dim]Server:[/dim] [bold]{server}[/bold]")
                console.print(f"  [dim]Tool:[/dim]   [bold]{tool_name}[/bold]")
                console.print()

            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_REQUESTED,
                {
                    "tool_name": tool_name,
                    "safety_level": "MCP",
                    "args_preview": f"server={server}",
                },
            )

            t0 = time.monotonic()
            response = await self.prompt_with_always_async(
                "Allow?", f"{server}/{tool_name}", safety_level="mcp", tool_name=tool_name
            )
            latency_ms = (time.monotonic() - t0) * 1000
            if response in ("a", "y"):
                if response == "a":
                    self._always_approved_categories.add(f"mcp:{server}")
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_GRANTED,
                    {
                        "tool_name": tool_name,
                        "permission_level": "MCP",
                        "decision": "approved",
                        "latency_ms": latency_ms,
                    },
                )
                return True
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": tool_name,
                    "permission_level": "MCP",
                    "decision": "denied",
                    "latency_ms": latency_ms,
                },
            )
            return False

        return await self._with_approval_locks(gate)

    @staticmethod
    def _write_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "memory_save":
            return str(tool_input.get("content", tool_input.get("value", "")))[:80]
        if tool_name == "note_save":
            return str(tool_input.get("content", ""))[:80]
        if tool_name == "set_api_key":
            return f"provider={tool_input.get('provider', '?')}"
        if tool_name == "manage_auth":
            return f"action={tool_input.get('action', '?')}"
        if tool_name == "manage_login":
            return f"sub={tool_input.get('subcommand', 'status')}" + (
                f" args={tool_input.get('args', '')[:60]}" if tool_input.get("args") else ""
            )
        if tool_name == "profile_update":
            fields = [k for k in ("role", "expertise", "name", "team") if tool_input.get(k)]
            return f"fields={','.join(fields)}" if fields else "profile update"
        if tool_name == "profile_preference":
            return f"{tool_input.get('key', '?')}={tool_input.get('value', '?')}"
        if tool_name == "profile_learn":
            return str(tool_input.get("pattern", ""))[:80]
        return ""

    def confirm_write(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Prompt user for write operation confirmation."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            summary = self._write_summary(tool_name, tool_input)

            console.print()
            console.print("  [warning]Write operation requires approval[/warning]")
            console.print(f"  [dim]Tool:[/dim]    [bold]{tool_name}[/bold]")
            if summary:
                console.print(f"  [dim]Summary:[/dim] {summary}")
            console.print()

        if self.check_auto_deny(tool_name):
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": tool_name,
                    "permission_level": "WRITE",
                    "decision": "auto_denied",
                    "latency_ms": 0.0,
                },
            )
            return False

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "WRITE",
                "args_preview": str(tool_input)[:200],
            },
        )

        t0 = time.monotonic()
        response = self.prompt_with_always(
            "Allow?", tool_name, safety_level="write", tool_name=tool_name
        )
        latency_ms = (time.monotonic() - t0) * 1000
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("write")
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": tool_name,
                    "permission_level": "WRITE",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                    "response_type": response,
                },
            )
            return True
        self._fire_hook(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": tool_name,
                "permission_level": "WRITE",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    async def confirm_write_async(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Async write operation confirmation."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            summary = self._write_summary(tool_name, tool_input)
            console.print()
            console.print("  [warning]Write operation requires approval[/warning]")
            console.print(f"  [dim]Tool:[/dim]    [bold]{tool_name}[/bold]")
            if summary:
                console.print(f"  [dim]Summary:[/dim] {summary}")
            console.print()

        if self.check_auto_deny(tool_name):
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": tool_name,
                    "permission_level": "WRITE",
                    "decision": "auto_denied",
                    "latency_ms": 0.0,
                },
            )
            return False

        await self._fire_hook_async(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "WRITE",
                "args_preview": str(tool_input)[:200],
            },
        )

        t0 = time.monotonic()
        response = await self.prompt_with_always_async(
            "Allow?", tool_name, safety_level="write", tool_name=tool_name
        )
        latency_ms = (time.monotonic() - t0) * 1000
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("write")
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": tool_name,
                    "permission_level": "WRITE",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                    "response_type": response,
                },
            )
            return True
        await self._fire_hook_async(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": tool_name,
                "permission_level": "WRITE",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    def confirm_cost(self, tool_name: str, estimated_cost: float) -> bool:
        """Prompt user for cost confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print("  [warning]$ Cost confirmation[/warning]")
            console.print(f"  [dim]Tool:[/dim] [bold]{tool_name}[/bold]")
            console.print(f"  [dim]Estimated cost:[/dim] ~${estimated_cost:.2f}")
            console.print()

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "EXPENSIVE",
                "args_preview": f"estimated_cost=${estimated_cost:.2f}",
            },
        )

        if self.check_auto_deny(tool_name):
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": tool_name,
                    "permission_level": "EXPENSIVE",
                    "decision": "auto_denied",
                    "latency_ms": 0.0,
                },
            )
            return False

        t0 = time.monotonic()
        response = self.prompt_with_always(
            "Proceed?", tool_name, safety_level="cost", tool_name=tool_name
        )
        latency_ms = (time.monotonic() - t0) * 1000
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("cost")
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": tool_name,
                    "permission_level": "EXPENSIVE",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                    "response_type": response,
                },
            )
            return True
        self._fire_hook(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": tool_name,
                "permission_level": "EXPENSIVE",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    async def confirm_cost_async(self, tool_name: str, estimated_cost: float) -> bool:
        """Async cost confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print("  [warning]$ Cost confirmation[/warning]")
            console.print(f"  [dim]Tool:[/dim] [bold]{tool_name}[/bold]")
            console.print(f"  [dim]Estimated cost:[/dim] ~${estimated_cost:.2f}")
            console.print()

        await self._fire_hook_async(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "EXPENSIVE",
                "args_preview": f"estimated_cost=${estimated_cost:.2f}",
            },
        )

        if self.check_auto_deny(tool_name):
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": tool_name,
                    "permission_level": "EXPENSIVE",
                    "decision": "auto_denied",
                    "latency_ms": 0.0,
                },
            )
            return False

        t0 = time.monotonic()
        response = await self.prompt_with_always_async(
            "Proceed?", tool_name, safety_level="cost", tool_name=tool_name
        )
        latency_ms = (time.monotonic() - t0) * 1000
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("cost")
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": tool_name,
                    "permission_level": "EXPENSIVE",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                    "response_type": response,
                },
            )
            return True
        await self._fire_hook_async(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": tool_name,
                "permission_level": "EXPENSIVE",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    def request_bash_approval(self, command: str, reason: str) -> bool:
        """Prompt user for bash command approval with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print("  [warning]Bash command requires approval[/warning]")
            console.print(f"  [dim]Command:[/dim] [value]{command}[/value]")
            if reason:
                console.print(f"  [dim]Reason:[/dim]  {reason}")
            console.print()

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": "run_bash",
                "safety_level": "DANGEROUS",
                "args_preview": str(command)[:200],
            },
        )

        if self.check_auto_deny("run_bash"):
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": "run_bash",
                    "permission_level": "DANGEROUS",
                    "decision": "auto_denied",
                    "latency_ms": 0.0,
                },
            )
            return False

        t0 = time.monotonic()
        response = self.prompt_with_always(
            "Allow?", command, safety_level="dangerous", tool_name="run_bash"
        )
        latency_ms = (time.monotonic() - t0) * 1000
        self.track_decision("run_bash", response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("bash")
            self._fire_hook(
                HookEvent.TOOL_APPROVAL_GRANTED,
                {
                    "tool_name": "run_bash",
                    "permission_level": "DANGEROUS",
                    "decision": "approved",
                    "latency_ms": latency_ms,
                    "response_type": response,
                },
            )
            return True
        self._fire_hook(
            HookEvent.TOOL_APPROVAL_DENIED,
            {
                "tool_name": "run_bash",
                "permission_level": "DANGEROUS",
                "decision": "denied",
                "latency_ms": latency_ms,
            },
        )
        return False

    async def request_bash_approval_async(self, command: str, reason: str) -> bool:
        """Async bash command approval with A=Always option."""

        async def gate() -> bool:
            if self._approval_callback is None:
                from core.cli import _restore_terminal

                _restore_terminal()
                console.print()
                console.print("  [warning]Bash command requires approval[/warning]")
                console.print(f"  [dim]Command:[/dim] [value]{command}[/value]")
                if reason:
                    console.print(f"  [dim]Reason:[/dim]  {reason}")
                console.print()

            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_REQUESTED,
                {
                    "tool_name": "run_bash",
                    "safety_level": "DANGEROUS",
                    "args_preview": str(command)[:200],
                },
            )

            if self.check_auto_deny("run_bash"):
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_DENIED,
                    {
                        "tool_name": "run_bash",
                        "permission_level": "DANGEROUS",
                        "decision": "auto_denied",
                        "latency_ms": 0.0,
                    },
                )
                return False

            t0 = time.monotonic()
            response = await self.prompt_with_always_async(
                "Allow?", command, safety_level="dangerous", tool_name="run_bash"
            )
            latency_ms = (time.monotonic() - t0) * 1000
            self.track_decision("run_bash", response)
            if response in ("a", "y"):
                if response == "a":
                    self._always_approved_categories.add("bash")
                await self._fire_hook_async(
                    HookEvent.TOOL_APPROVAL_GRANTED,
                    {
                        "tool_name": "run_bash",
                        "permission_level": "DANGEROUS",
                        "decision": "approved",
                        "latency_ms": latency_ms,
                        "response_type": response,
                    },
                )
                return True
            await self._fire_hook_async(
                HookEvent.TOOL_APPROVAL_DENIED,
                {
                    "tool_name": "run_bash",
                    "permission_level": "DANGEROUS",
                    "decision": "denied",
                    "latency_ms": latency_ms,
                },
            )
            return False

        return await self._with_approval_locks(gate)

    # -----------------------------------------------------------------
    # MCP server approval cache
    # -----------------------------------------------------------------

    def is_mcp_approved(self, server: str) -> bool:
        """Check if MCP server is already approved for this session."""
        if server in AUTO_APPROVED_MCP_SERVERS:
            return True
        if f"mcp:{server}" in self._always_approved_categories:
            return True
        if self._skip_permissions():
            return True
        if self._hitl_level <= 1:
            return True
        return server in self._mcp_approved_servers

    def mark_mcp_approved(self, server: str) -> None:
        """Mark an MCP server as approved for the rest of this session."""
        self._mcp_approved_servers.add(server)

    # -----------------------------------------------------------------
    # Bash safety check
    # -----------------------------------------------------------------

    def is_bash_auto_approved(self, command: str) -> bool:
        """Check if a bash command can skip HITL approval.

        Auto-approves when ``--dangerously-skip-permissions`` is set, HITL is
        fully open (level ≤ 1), the user explicitly marked `run_bash` /
        category `bash` always-allowed, or the command is a read-only pipeline
        (see :func:`is_bash_command_read_only`).
        """
        if self._skip_permissions():
            return True
        if self._hitl_level <= 1:
            return True
        if "bash" in self._always_approved_categories or "run_bash" in self._always_approved_tools:
            return True
        return is_bash_command_read_only(command)

    async def confirm_computer_async(self) -> bool:
        """Computer-use gate — approve ONCE per session, then remember.

        ``computer`` is DANGEROUS but continuous-control (screenshot → click →
        type loops), so a per-action HITL prompt is impractical; enabling the
        tool (``computer_use_enabled``) is the operator's standing opt-in.
        Auto-approves under ``--dangerously-skip-permissions`` / open HITL
        (≤ 1) / a prior session approval; otherwise prompts once and any
        approval (Y / A) is remembered for the rest of the session.
        """
        if self._skip_permissions() or self._hitl_level <= 1 or self._computer_approved:
            return True
        response = await self.prompt_with_always_async(
            "Allow computer control (screen + mouse + keyboard)?",
            "computer",
            safety_level="dangerous",
            tool_name="computer",
        )
        if response in ("a", "y"):
            self._computer_approved = True
            return True
        return False

    # -----------------------------------------------------------------
    # Batch cost approval (used by ToolCallProcessor)
    # -----------------------------------------------------------------

    async def batch_cost_approval(self, blocks: list[Any]) -> bool:
        """Show a single cost confirmation prompt for all EXPENSIVE tools."""
        # --dangerously-skip-permissions / fully-open HITL / always-approved
        # cost → no batch prompt (parity with the per-tool expensive gate).
        if (
            self._skip_permissions()
            or self._hitl_level == 0
            or self._auto_approve
            or "cost" in self._always_approved_categories
        ):
            return True
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
