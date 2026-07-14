"""HITL Approval Workflow — extracted from ToolExecutor for SRP.

Manages user approval gates for dangerous, write, expensive, and MCP tools.
Tracks session-scoped approval patterns (auto-approve after 3 consecutive
approvals, auto-deny after 3 consecutive denials).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from core.agent.approval_fsm import (
    LEDGER_ROW_STATES,
    VERDICT_BY_DECISION,
    VERDICT_DENY,
    ApprovalRecord,
    parse_decision,
)
from core.agent.safety import (
    AUTO_APPROVED_MCP_SERVERS,
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    WRITE_TOOLS,
    is_bash_command_read_only,
)
from core.hooks.system import HookEvent
from core.ui import spinner_glyph
from core.ui.console import console

if TYPE_CHECKING:
    from core.hooks import HookSystem

log = logging.getLogger(__name__)

_AUTO_APPROVE_THRESHOLD = 3
_AUTO_DENY_THRESHOLD = 3
_T = TypeVar("_T")

# Bare prompt labels carry no information beyond "answer the gate" — the
# options line replaces them. Anything else (e.g. the computer-control
# question) is a real question and still renders above the options line.
_BARE_PROMPT_LABELS = frozenset({"Allow?", "Proceed?"})


def _approval_header(tool_name: str, category: str) -> str:
    """``◆ Approval · tool (category)`` — rose mark, bold tool, dim category.

    The IPC thin client renders the same header shape in
    ``core/cli/ipc_client.py::_handle_approval_request`` (kept inline there so
    the thin client does not import the agent layer).
    """
    return (
        f"  [bold {spinner_glyph.ROSE_HEX}]{spinner_glyph.GLYPH}[/] Approval · "
        f"[bold]{tool_name}[/bold] [dim]({category})[/dim]"
    )


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
        approval_callback: Callable[..., str] | None = None,
    ) -> None:
        self._auto_approve = auto_approve
        self._hitl_level = hitl_level
        self._hooks = hooks
        self._approval_callback = approval_callback
        # Session EvidenceLedger — attached by AgenticLoop via
        # ToolExecutor.attach_evidence_ledger (best-effort rail; None when the
        # workflow runs outside a loop, e.g. tests / CLI utilities).
        self._evidence_ledger: Any | None = None

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
        from core.hooks.dispatch import fire_hook

        fire_hook(self._hooks, event, data)

    async def _fire_hook_async(self, event: HookEvent, data: dict[str, Any]) -> None:
        from core.hooks.dispatch import fire_hook_async

        await fire_hook_async(self._hooks, event, data)

    async def _with_approval_locks(self, body: Callable[[], Awaitable[_T]]) -> _T:
        """Serialize async prompts with both async and legacy sync approval paths."""
        await asyncio.to_thread(self._approval_lock.acquire)
        try:
            return await body()
        finally:
            self._approval_lock.release()

    # -----------------------------------------------------------------
    # Approval FSM — per-transition records (PR-HITL-APPROVAL-FSM)
    # -----------------------------------------------------------------

    def attach_evidence_ledger(self, ledger: Any | None) -> None:
        """Attach the session's EvidenceLedger (terminal-state rows rail)."""
        self._evidence_ledger = ledger

    def begin_record(self, tool_name: str) -> ApprovalRecord | None:
        """Create an ApprovalRecord for a gated tool; ``None`` for ungated.

        Category mirrors the gate that will run: ``bash`` (run_bash),
        ``dangerous`` (computer), ``write``, ``expensive``. MCP tools are not
        classifiable here (server lookup happens at dispatch) — see
        :meth:`begin_mcp_record`.
        """
        if tool_name == "run_bash":
            category = "bash"
        elif tool_name in DANGEROUS_TOOLS:
            category = "dangerous"
        elif tool_name in WRITE_TOOLS:
            category = "write"
        elif tool_name in EXPENSIVE_TOOLS:
            category = "expensive"
        else:
            return None
        record = ApprovalRecord(tool_name=tool_name, category=category)
        self.record_transition(record, "requested", "gate")
        return record

    def begin_mcp_record(self, server: str, tool_name: str) -> ApprovalRecord:
        """Create the ApprovalRecord for an MCP server confirmation."""
        record = ApprovalRecord(tool_name=tool_name, category="mcp")
        self.record_transition(record, "requested", f"server={server}")
        return record

    def record_transition(
        self, record: ApprovalRecord | None, state: str, detail: str = ""
    ) -> None:
        """Record one FSM transition on BOTH observability rails.

        Rail (a): ``HookEvent.APPROVAL_TRANSITION`` — one event per handoff
        with the target ``state`` in the payload. Rail (b): an EvidenceLedger
        row for terminal states (granted/denied + executed/skipped) when a
        session ledger is attached; skipped silently otherwise (the ledger is
        best-effort). ``record=None`` is a no-op so ungated tools pay nothing.
        """
        if record is None:
            return
        record.transition(state, detail)
        payload = record.to_event_payload()
        payload["detail"] = detail
        self._fire_hook(HookEvent.APPROVAL_TRANSITION, payload)
        if state in LEDGER_ROW_STATES and self._evidence_ledger is not None:
            try:
                self._evidence_ledger.append(
                    kind="hitl_approval",
                    summary=f"{record.tool_name} {state} ({record.category})",
                    payload=payload,
                )
            except Exception:
                log.debug("EvidenceLedger approval row write failed", exc_info=True)

    def _auto_grant_reason(self, category: str, tool_name: str) -> str:
        """Return the auto-approve reason for a gate short-circuit, or ""."""
        if self._skip_permissions():
            return "auto:skip-permissions"
        if self._hitl_level == 0:
            return "auto:hitl-open"
        if category in self._always_approved_categories:
            return f"auto:always-category:{category}"
        if tool_name and tool_name in self._always_approved_tools:
            return "auto:always-tool"
        return ""

    def _invoke_approval_callback(
        self, tool_name: str, detail: str, safety_level: str, approval_id: str
    ) -> str:
        """Call the IPC approval callback, forwarding ``approval_id`` when the
        callback accepts it (4-positional / var-positional signature). Legacy
        3-arg callbacks (tests, third-party wiring) are called without it."""
        callback = self._approval_callback
        assert callback is not None
        if self._callback_accepts_approval_id(callback):
            return callback(tool_name, detail, safety_level, approval_id)
        return callback(tool_name, detail, safety_level)

    @staticmethod
    def _callback_accepts_approval_id(callback: Callable[..., str]) -> bool:
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return False
        params = list(signature.parameters.values())
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
            return True
        positional = [
            p
            for p in params
            if p.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return len(positional) >= 4

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
        record: ApprovalRecord | None = None,
    ) -> str:
        """Show the approval options line and return 'y', 'n', or 'a'.

        Threads the ApprovalRecord through display → input → parse: the
        direct console path records the actual raw keystrokes; the IPC path
        records the thin client's parsed decision char as the selection (the
        raw input stays client-side) plus the ``approval_id`` round-trip.
        """
        if self._approval_callback is not None:
            decision = self._invoke_approval_callback(
                tool_name or label,
                detail,
                safety_level,
                record.approval_id if record is not None else "",
            )
            log.debug("HITL: IPC callback decision=%s tool=%s", decision, tool_name or label)
            self.record_transition(record, "displayed", "ipc")
            self.record_transition(record, "user_selected", decision)
            self.record_transition(
                record, "parsed", VERDICT_BY_DECISION.get(decision, VERDICT_DENY)
            )
            return decision

        from core.cli import _restore_terminal

        _restore_terminal()
        if label not in _BARE_PROMPT_LABELS:
            console.print(f"  [bold]{label}[/bold]")
        self.record_transition(record, "displayed", "console")
        try:
            raw = console.input("  [muted]y allow · n deny · a always-allow[/muted] ")
        except (KeyboardInterrupt, EOFError):
            console.print()
            self.record_transition(record, "user_selected", "<interrupt>")
            self.record_transition(record, "parsed", VERDICT_DENY)
            return "n"
        self.record_transition(record, "user_selected", raw.strip()[:20])
        decision, verdict = parse_decision(raw)
        self.record_transition(record, "parsed", verdict)
        return decision

    async def prompt_with_always_async(
        self,
        label: str,
        detail: str,
        *,
        safety_level: str = "write",
        tool_name: str = "",
        record: ApprovalRecord | None = None,
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
            record=record,
        )

    # -----------------------------------------------------------------
    # Safety gate orchestration
    # -----------------------------------------------------------------

    def apply_safety_gates(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
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
                auto_reason = self._auto_grant_reason("write", tool_name)
                if auto_reason:
                    self.record_transition(record, "granted", auto_reason)
                    approved = True
                else:
                    # REQUESTED fires inside confirm_write (richer payload);
                    # a second outer emission double-notified handlers.
                    if not self.confirm_write(tool_name, tool_input, record=record):
                        return _write_denial_with_fallback(tool_name), False
                    approved = True

        # Expensive tools
        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:
            with self._approval_lock:
                auto_reason = self._auto_grant_reason("cost", tool_name)
                if auto_reason:
                    self.record_transition(record, "granted", auto_reason)
                    approved = True
                else:
                    cost = EXPENSIVE_TOOLS[tool_name]
                    if not self.confirm_cost(tool_name, cost, record=record):
                        return {
                            "error": "User denied expensive operation",
                            "denied": True,
                        }, False
                    approved = True

        return None, approved

    async def apply_safety_gates_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Async HITL gate path used by ToolExecutor.aexecute()."""
        if tool_name in DANGEROUS_TOOLS:
            return None, False

        approved = False

        if tool_name in WRITE_TOOLS:

            async def write_gate() -> tuple[dict[str, Any] | None, bool]:
                auto_reason = self._auto_grant_reason("write", tool_name)
                if auto_reason:
                    self.record_transition(record, "granted", auto_reason)
                    return None, True
                if not await self.confirm_write_async(tool_name, tool_input, record=record):
                    return _write_denial_with_fallback(tool_name), False
                return None, True

            gate_result, approved = await self._with_approval_locks(write_gate)
            if gate_result is not None:
                return gate_result, False

        if tool_name in EXPENSIVE_TOOLS and not self._auto_approve:

            async def cost_gate() -> tuple[dict[str, Any] | None, bool]:
                auto_reason = self._auto_grant_reason("cost", tool_name)
                if auto_reason:
                    self.record_transition(record, "granted", auto_reason)
                    return None, True
                cost = EXPENSIVE_TOOLS[tool_name]
                if not await self.confirm_cost_async(tool_name, cost, record=record):
                    return {"error": "User denied expensive operation", "denied": True}, False
                return None, True

            gate_result, approved = await self._with_approval_locks(cost_gate)
            if gate_result is not None:
                return gate_result, False

        return None, approved

    # -----------------------------------------------------------------
    # Confirmation prompts
    # -----------------------------------------------------------------

    def confirm_mcp(
        self, server: str, tool_name: str, record: ApprovalRecord | None = None
    ) -> bool:
        """Prompt user for MCP tool confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print(_approval_header(tool_name, "mcp"))
            console.print(f"  [dim]Server:[/dim] [bold]{server}[/bold]")
            console.print()

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "MCP",
                "args_preview": f"server={server}",
            },
        )

        response = self.prompt_with_always(
            "Allow?",
            f"{server}/{tool_name}",
            safety_level="mcp",
            tool_name=tool_name,
            record=record,
        )
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add(f"mcp:{server}")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    async def confirm_mcp_async(
        self, server: str, tool_name: str, record: ApprovalRecord | None = None
    ) -> bool:
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

            response = await self.prompt_with_always_async(
                "Allow?",
                f"{server}/{tool_name}",
                safety_level="mcp",
                tool_name=tool_name,
                record=record,
            )
            if response in ("a", "y"):
                if response == "a":
                    self._always_approved_categories.add(f"mcp:{server}")
                self.record_transition(record, "granted", f"user:{response}")
                return True
            self.record_transition(record, "denied", f"user:{response}")
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

    def confirm_write(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
    ) -> bool:
        """Prompt user for write operation confirmation."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            summary = self._write_summary(tool_name, tool_input)

            console.print()
            console.print(_approval_header(tool_name, "write"))
            if summary:
                console.print(f"  [dim]Summary:[/dim] {summary}")
            console.print()

        if self.check_auto_deny(tool_name):
            self.record_transition(record, "denied", "auto_denied:3-strikes")
            return False

        self._fire_hook(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "WRITE",
                "args_preview": str(tool_input)[:200],
            },
        )

        response = self.prompt_with_always(
            "Allow?", tool_name, safety_level="write", tool_name=tool_name, record=record
        )
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("write")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    async def confirm_write_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
    ) -> bool:
        """Async write operation confirmation."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            summary = self._write_summary(tool_name, tool_input)
            console.print()
            console.print(_approval_header(tool_name, "write"))
            if summary:
                console.print(f"  [dim]Summary:[/dim] {summary}")
            console.print()

        if self.check_auto_deny(tool_name):
            self.record_transition(record, "denied", "auto_denied:3-strikes")
            return False

        await self._fire_hook_async(
            HookEvent.TOOL_APPROVAL_REQUESTED,
            {
                "tool_name": tool_name,
                "safety_level": "WRITE",
                "args_preview": str(tool_input)[:200],
            },
        )

        response = await self.prompt_with_always_async(
            "Allow?", tool_name, safety_level="write", tool_name=tool_name, record=record
        )
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("write")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    def confirm_cost(
        self,
        tool_name: str,
        estimated_cost: float,
        record: ApprovalRecord | None = None,
    ) -> bool:
        """Prompt user for cost confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print(_approval_header(tool_name, "expensive"))
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
            self.record_transition(record, "denied", "auto_denied:3-strikes")
            return False

        response = self.prompt_with_always(
            "Proceed?", tool_name, safety_level="cost", tool_name=tool_name, record=record
        )
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("cost")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    async def confirm_cost_async(
        self,
        tool_name: str,
        estimated_cost: float,
        record: ApprovalRecord | None = None,
    ) -> bool:
        """Async cost confirmation with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print(_approval_header(tool_name, "expensive"))
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
            self.record_transition(record, "denied", "auto_denied:3-strikes")
            return False

        response = await self.prompt_with_always_async(
            "Proceed?", tool_name, safety_level="cost", tool_name=tool_name, record=record
        )
        self.track_decision(tool_name, response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("cost")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    def request_bash_approval(
        self, command: str, reason: str, record: ApprovalRecord | None = None
    ) -> bool:
        """Prompt user for bash command approval with A=Always option."""
        if self._approval_callback is None:
            from core.cli import _restore_terminal

            _restore_terminal()
            console.print()
            console.print(_approval_header("run_bash", "bash"))
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
            self.record_transition(record, "denied", "auto_denied:3-strikes")
            return False

        response = self.prompt_with_always(
            "Allow?", command, safety_level="dangerous", tool_name="run_bash", record=record
        )
        self.track_decision("run_bash", response)
        if response in ("a", "y"):
            if response == "a":
                self._always_approved_categories.add("bash")
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    async def request_bash_approval_async(
        self, command: str, reason: str, record: ApprovalRecord | None = None
    ) -> bool:
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
                self.record_transition(record, "denied", "auto_denied:3-strikes")
                return False

            response = await self.prompt_with_always_async(
                "Allow?", command, safety_level="dangerous", tool_name="run_bash", record=record
            )
            self.track_decision("run_bash", response)
            if response in ("a", "y"):
                if response == "a":
                    self._always_approved_categories.add("bash")
                self.record_transition(record, "granted", f"user:{response}")
                return True
            self.record_transition(record, "denied", f"user:{response}")
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

    async def confirm_computer_async(self, record: ApprovalRecord | None = None) -> bool:
        """Computer-use gate — approve ONCE per session, then remember.

        ``computer`` is DANGEROUS but continuous-control (screenshot → click →
        type loops), so a per-action HITL prompt is impractical; enabling the
        tool (``computer_use_enabled``) is the operator's standing opt-in.
        Auto-approves under ``--dangerously-skip-permissions`` / open HITL
        (≤ 1) / a prior session approval; otherwise prompts once and any
        approval (Y / A) is remembered for the rest of the session.
        """
        if self._skip_permissions() or self._hitl_level <= 1 or self._computer_approved:
            self.record_transition(record, "granted", "auto:computer-session")
            return True
        response = await self.prompt_with_always_async(
            "Allow computer control (screen + mouse + keyboard)?",
            "computer",
            safety_level="dangerous",
            tool_name="computer",
            record=record,
        )
        if response in ("a", "y"):
            self._computer_approved = True
            self.record_transition(record, "granted", f"user:{response}")
            return True
        self.record_transition(record, "denied", f"user:{response}")
        return False

    # -----------------------------------------------------------------
    # Batch cost approval (used by ToolCallProcessor)
    # -----------------------------------------------------------------

    async def batch_cost_approval(self, blocks: list[Any]) -> bool:
        """Show a single cost confirmation prompt for all EXPENSIVE tools.

        Threads ONE ApprovalRecord for the whole batch (the per-tool records
        cover propagation/execution; this one covers the shared decision).
        """
        record = ApprovalRecord(
            tool_name=",".join(str(block.name) for block in blocks) or "batch",
            category="expensive",
        )
        self.record_transition(record, "requested", f"batch:{len(blocks)}")
        # --dangerously-skip-permissions / fully-open HITL / always-approved
        # cost → no batch prompt (parity with the per-tool expensive gate).
        if self._skip_permissions():
            self.record_transition(record, "granted", "auto:skip-permissions")
            return True
        if self._hitl_level == 0:
            self.record_transition(record, "granted", "auto:hitl-open")
            return True
        if self._auto_approve:
            self.record_transition(record, "granted", "auto:auto-approve")
            return True
        if "cost" in self._always_approved_categories:
            self.record_transition(record, "granted", "auto:always-category:cost")
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

            count = len(items)
            plural = "s" if count != 1 else ""
            console.print()
            console.print(_approval_header(f"{count} tool{plural}", "expensive"))
            for name, inp, cost in items:
                args_preview = ", ".join(f"{k}={v!r}" for k, v in inp.items())
                console.print(f"    [dim]--[/dim] {name}({args_preview}) -- ~${cost:.2f}")
            console.print(f"  [dim]Total estimated cost:[/dim] ~${total_cost:.2f}")
            console.print()
            self.record_transition(record, "displayed", "console")
            try:
                raw = console.input("  [muted]y allow · n deny[/muted] ")
            except (KeyboardInterrupt, EOFError):
                console.print()
                self.record_transition(record, "user_selected", "<interrupt>")
                self.record_transition(record, "parsed", VERDICT_DENY)
                return False
            self.record_transition(record, "user_selected", raw.strip()[:20])
            # Batch grammar is y/n only — "a" is NOT an always-allow here
            # (the options line offers none), so it parses to deny.
            allowed = raw.strip().lower() in ("", "y", "yes")
            self.record_transition(record, "parsed", "allow" if allowed else "deny")
            return allowed

        approved = await asyncio.to_thread(_prompt)
        self.record_transition(record, "granted" if approved else "denied", "batch-decision")
        return approved
