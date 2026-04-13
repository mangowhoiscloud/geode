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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.error_recovery import ErrorRecoveryStrategy
    from core.agent.sub_agent import SubAgentManager
    from core.cli.ui.agentic_ui import OperationLogger
    from core.hooks import HookSystem

from core.agent.approval import (
    _write_denial_with_fallback as _write_denial_with_fallback,
)
from core.agent.safety_constants import AUTO_APPROVED_MCP_SERVERS as AUTO_APPROVED_MCP_SERVERS
from core.agent.safety_constants import DANGEROUS_TOOLS as DANGEROUS_TOOLS
from core.agent.safety_constants import EXPENSIVE_TOOLS as EXPENSIVE_TOOLS
from core.agent.safety_constants import SAFE_BASH_PREFIXES as SAFE_BASH_PREFIXES
from core.agent.safety_constants import SAFE_TOOLS as SAFE_TOOLS
from core.agent.safety_constants import WRITE_TOOLS as WRITE_TOOLS
from core.cli.bash_tool import BashTool
from core.cli.ui.console import console

log = logging.getLogger(__name__)

# Everything else is STANDARD — executes without special gates


@contextmanager
def _tool_spinner(label: str) -> Iterator[None]:
    """Show a Rich dots spinner during post-approval tool execution.

    Displays ``label`` with a spinner while the wrapped block runs,
    then clears it on exit so OperationLogger markers (✓/✗) render cleanly.

    Skipped in IPC mode — thin CLI has its own ToolCallTracker spinner.
    Running both causes ANSI cursor-up race → UI corruption.
    """
    # IPC mode: ToolCallTracker on thin CLI handles the spinner
    from core.cli.ui.agentic_ui import _ipc_writer_local

    if getattr(_ipc_writer_local, "writer", None) is not None:
        yield
        return

    status = console.status(f"  [dim]✢ {label}[/dim]", spinner="dots", spinner_style="cyan")
    status.start()
    try:
        yield
    finally:
        status.stop()


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
            from core.cli.ui.agentic_ui import render_subagent_progress

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
        from core.cli.redaction import redact_secrets

        for key in ("stdout", "stderr", "output", "content", "text", "result"):
            if key in result and isinstance(result[key], str):
                result[key] = redact_secrets(result[key])
        return result

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
    For small-context models (<200K, e.g. GLM-5), caps each tool result at 5% of
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
        # Breadcrumb: skip recovery chain for non-recoverable errors (e.g. permission)
        self._last_error_recoverable: dict[str, bool] = {}
        self._tool_log: list[dict[str, Any]] = []
        self._clarification_count: int = 0

    def reset(self) -> None:
        """Reset per-run tracking state. Call at the start of each agentic run."""
        self._consecutive_failures.clear()
        self._last_error_recoverable.clear()
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

    def _record_tool_activity(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result: Any,
        visible: bool,
    ) -> None:
        """Log result, record transcript events, and append to tool_log."""
        # Progressive log: show tool result summary (skip if already logged)
        if isinstance(result, dict):
            skip_log = result.get("skipped") or result.get("recovery_attempted")
            if not skip_log:
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

    def _serialize_tool_result(self, result: Any, block_id: str) -> dict[str, Any]:
        """Apply token guard, offload large results, and serialize for LLM."""
        # Token guard: truncate oversized results to prevent context explosion
        # For small-context models (e.g. GLM-5), apply model-aware limit
        if isinstance(result, dict):
            model_limit = _compute_model_tool_limit(self._model) if self._model else 0
            result = _guard_tool_result(result, max_tokens=model_limit or None)

        # Serialize result as JSON for LLM (not Python repr)
        try:
            serialized = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            serialized = str(result)

        # P0: Offload large results to filesystem, inject compact summary
        estimated_tokens = len(serialized) // 4
        from core.orchestration.tool_offload import get_offload_store

        offload_store = get_offload_store()
        if (
            offload_store
            and offload_store.threshold > 0
            and estimated_tokens > offload_store.threshold
        ):
            from core.orchestration.tool_offload import extract_result_summary

            ref_id = offload_store.offload(block_id, result)
            summary = extract_result_summary(result, max_chars=400)
            content = json.dumps(
                {
                    "_offloaded": True,
                    "_ref_id": ref_id,
                    "_original_tokens": estimated_tokens,
                    "summary": summary,
                    "hint": "Use recall_tool_result(ref_id) to retrieve the full output.",
                },
                ensure_ascii=False,
            )
            # Fire hook for observability
            if self._hooks:
                from core.hooks import HookEvent

                self._hooks.trigger(
                    HookEvent.TOOL_RESULT_OFFLOADED,
                    {
                        "ref_id": ref_id,
                        "original_tokens": estimated_tokens,
                        "block_id": block_id,
                    },
                )
        else:
            content = serialized

        return {
            "type": "tool_result",
            "tool_use_id": block_id,
            "content": content,
        }

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

        last_recoverable = self._last_error_recoverable.get(tool_name, True)
        if fail_count >= self.MAX_CONSECUTIVE_FAILURES and last_recoverable:
            # Adaptive recovery: try recovery chain instead of auto-skip
            result = await self._attempt_recovery(tool_name, tool_input, fail_count)
            visible = self._op_logger.log_tool_call(tool_name, tool_input)
            self._op_logger.log_tool_result(tool_name, result, visible=visible)
        else:
            # Progressive log: show tool call before execution
            visible = self._op_logger.log_tool_call(tool_name, tool_input)

            # Hook: TOOL_EXEC_START
            self._fire_hook("tool_exec_start", {"tool_name": tool_name, "tool_input": tool_input})

            # Execute via ToolExecutor (sync handlers wrapped in to_thread)
            _t0 = time.monotonic()
            result = await asyncio.to_thread(self._executor.execute, tool_name, tool_input)
            _elapsed_ms = (time.monotonic() - _t0) * 1000

            # Hook: TOOL_EXEC_END
            self._fire_hook(
                "tool_exec_end",
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "duration_ms": _elapsed_ms,
                    "has_error": isinstance(result, dict) and bool(result.get("error")),
                },
            )

        # Track consecutive failures + recoverability breadcrumb
        if isinstance(result, dict) and result.get("error"):
            if not result.get("recovery_attempted"):
                self._consecutive_failures[tool_name] = fail_count + 1
                self._last_error_recoverable[tool_name] = result.get("recoverable", True)
        else:
            self._consecutive_failures[tool_name] = 0
            self._last_error_recoverable.pop(tool_name, None)

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

        self._record_tool_activity(tool_name, tool_input, result, visible)
        return self._serialize_tool_result(result, block.id)

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
        """Delegates to ApprovalWorkflow."""
        return await self._executor._approval.batch_cost_approval(blocks)

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
        self._fire_hook(
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
            self._fire_hook(
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

        self._fire_hook(
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

    def _fire_hook(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a hook event if HookSystem is configured."""
        if self._hooks is None:
            return
        try:
            from core.hooks import HookEvent as _HookEvent

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
