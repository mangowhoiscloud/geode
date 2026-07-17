"""ToolExecutor — route tool calls to handlers with HITL safety checks."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from core.agent.approval_fsm import ApprovalRecord
    from core.agent.sub_agent import SubAgentManager
    from core.hooks import HookSystem
    from core.tools.base import ToolContext

from core.agent.safety import DANGEROUS_TOOLS
from core.tools.bash_tool import BashTool

log = logging.getLogger(__name__)

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]] | Any]

# Execution bindings that bypass the ordinary handler map.  Architecture
# inventory imports this set so the model-visible schema and executable surface
# can be compared without duplicating these names in an audit script.
DELEGATE_TASK_TOOL_NAME = "delegate_task"
RUN_BASH_TOOL_NAME = "run_bash"
SPECIAL_EXECUTION_BINDINGS: frozenset[str] = frozenset(
    {DELEGATE_TASK_TOOL_NAME, RUN_BASH_TOOL_NAME}
)

# ---------------------------------------------------------------------------
# Tool wall-clock deadline — PR-LOOP-POLLUTION-FIX (2026-06-12)
# ---------------------------------------------------------------------------
#
# Hard upper bound on a single handler call, enforced with
# ``asyncio.wait_for`` at the harness layer. Per-phase HTTP timeouts are
# NOT wall-clock guarantees (httpx timeouts are per-operation, and a
# coroutine awaiting a foreign-loop primitive bypasses them entirely —
# the 2026-06-12 00:08 incident left two web_search calls hanging for
# 50+ minutes with the operator staring at a spinner). The deadline
# converts ANY hang into a structured timeout error the loop can report.
#
# Anthropic's server-side web_search runs an agentic search loop
# (25-50s observed envelope) — 120s default leaves ample headroom.
# Long-running tools override via _TOOL_DEADLINE_OVERRIDES_S; bash /
# delegate_task / MCP own their budgets on separate dispatch paths.
#
# Caveat: a SYNC handler bridged through ``asyncio.to_thread`` cannot be
# force-killed — wait_for abandons the await (the turn proceeds, spinner
# resolves) while the worker thread runs to completion in the background.
_TOOL_DEADLINE_DEFAULT_S = 120.0
# Keys MUST match REGISTERED handler names (pinned by
# test_deadline_override_keys_match_registered_handler_names — Codex MCP
# review 2026-06-12 caught "computer_use" vs the actual "computer").
_TOOL_DEADLINE_OVERRIDES_S: dict[str, float] = {
    "petri_audit": 900.0,  # inspect_ai audit subprocess (own 600s wall clock)
    "eval_dspy_optimize": 900.0,  # optimizer loop
    "computer": 600.0,  # multi-step UI automation (_build_computer_use_handler)
    "computer_use": 600.0,  # emulated function-call UI automation
    # web_search: must cover per-attempt client timeout (100s,
    # _capability_impls.ANTHROPIC_WEB_SEARCH_TIMEOUT_S) × the dispatch
    # retry (1 original + 1 same-adapter retry) + backoff. The 120s
    # default collided with exactly that stack — the operator watched a
    # healthy retry get killed at 119.9s (2026-06-12 02:0x). Coherence
    # pinned by test_web_search_deadline_covers_client_timeout_with_retry.
    "general_web_search": 240.0,
}


def _tool_deadline_s(tool_name: str) -> float:
    return _TOOL_DEADLINE_OVERRIDES_S.get(tool_name, _TOOL_DEADLINE_DEFAULT_S)


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
        # (tool_name, detail, safety_level[, approval_id]) -> decision char.
        # 4-arg callbacks receive the ApprovalRecord id for reply matching;
        # legacy 3-arg callbacks are detected and called without it.
        approval_callback: Callable[..., str] | None = None,
        denied_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._handlers: dict[str, ToolHandler] = action_handlers or {}
        self._bash = bash_tool or BashTool()
        self._auto_approve = auto_approve  # for testing only
        self._sub_agent_manager = sub_agent_manager
        self._mcp_manager = mcp_manager
        self._hitl_level = hitl_level
        # Tools refused outright on this session, BEFORE any gate/approval or the
        # run_bash/delegate_task special-cases. Removing a tool from
        # ``action_handlers`` is NOT enough — run_bash/delegate_task are
        # special-cased ahead of handler lookup, so a denylist must be enforced
        # here. Used by headless sessions (scheduler/daemon/MCP run_agent) where
        # no human can approve. (Codex MCP review, PR-EXEC-HARDENING.)
        self._denied_tools = denied_tools
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

    def attach_evidence_ledger(self, ledger: Any | None) -> None:
        """Attach the session EvidenceLedger for approval-FSM terminal rows.

        Called by AgenticLoop after it builds the per-session ledger (the
        loop owns the session identity; the executor is constructed before
        the loop exists). Best-effort — approval flows skip the ledger rail
        silently when none is attached.
        """
        self._approval.attach_evidence_ledger(ledger)

    def _track_decision(self, tool_name: str, decision: str) -> None:
        """Delegates to ApprovalWorkflow."""
        self._approval.track_decision(tool_name, decision)

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
        log.debug("ToolExecutor.async: %s(keys=%s)", tool_name, sorted(tool_input))

        if context and context.cancellation and context.cancellation.is_set():
            return {"error": "Tool execution cancelled before start", "cancelled": True}

        # Headless denylist — refuse BEFORE the gate and the run_bash/
        # delegate_task special-cases below (handler-dict filtering cannot stop
        # those, since they never consult the handler dict). No human to approve.
        if tool_name in self._denied_tools:
            log.info("Tool %s denied on this session (headless denylist)", tool_name)
            return {
                "error": f"Tool '{tool_name}' is not available in this session.",
                "denied": True,
            }

        # Fleet view Stage 1.5 — the single per-tool dispatch boundary. A no-op
        # unless this is a worker subprocess that opted in (WorkerRequest.
        # emit_activity), in which case the current tool + cumulative tokens are
        # forwarded to the parent over the activity side-channel. Placed after
        # the denylist so a refused tool never shows as "current activity".
        from core.agent.activity_channel import emit_tool_activity

        emit_tool_activity(tool_name)

        # Single safety GATE for EVERY tool (classify → approve). DANGEROUS
        # tools are gated HERE (approval only) and then fall through to the
        # SAME dispatch as every other tool — no execution short-circuit that
        # could leave a registered handler unreachable. (The bug this fixes:
        # ``computer`` ∈ DANGEROUS_TOOLS was routed to a bash-only execution
        # method and never reached its registered ``handle_computer``.)
        #
        # PR-HITL-APPROVAL-FSM (2026-07-02) — gated tools thread ONE
        # ApprovalRecord through gate → verdict → dispatch so a lost or
        # misrouted decision (the A-but-denied incident) is diagnosable from
        # the transition trail instead of a bare denial string.
        record = self._approval.begin_record(tool_name)
        gate_result, approved_via_hitl = await self._gate_async(tool_name, tool_input, record)
        if gate_result is not None:
            self._approval.record_transition(record, "skipped", "gate-rejected")
            return gate_result
        if record is not None and record.state == "requested":
            # No gate branch consumed the record (e.g. an EXPENSIVE tool while
            # batch approval temporarily set auto_approve) — close the chain
            # explicitly so the dispatch transitions stay legal.
            self._approval.record_transition(record, "granted", "auto:ungated")
        self._approval.record_transition(record, "propagated", "dispatch")
        result = await self._dispatch_async(
            tool_name, tool_input, context=context, approved_via_hitl=approved_via_hitl
        )
        if record is not None:
            has_error = isinstance(result, dict) and bool(result.get("error"))
            self._approval.record_transition(record, "executed", "error" if has_error else "ok")
        return result

    async def _dispatch_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
        approved_via_hitl: bool = False,
    ) -> dict[str, Any]:
        """Uniform post-gate dispatch — 'how does it run?', gate-free.

        Extracted from :meth:`aexecute` so the approval FSM records
        ``propagated`` exactly once before dispatch and ``executed`` exactly
        once after, regardless of which branch (delegate / bash / handler /
        MCP / unknown) serves the call.
        """
        if tool_name == DELEGATE_TASK_TOOL_NAME:
            # PR-Async-Phase-C step 3 (2026-05-22) — switched to native
            # async delegate dispatch. The old asyncio.to_thread bridge
            # over sync ``_execute_delegate`` is gone.
            # PR-SUBAGENT-MODEL-ALIGN (2026-06-14) — forward the ToolContext
            # so the sub-agent inherits the loop's LIVE model (the same
            # ``ctx.model`` web_search uses), not the global ``settings.model``
            # which can lag a mid-session ``/model`` switch.
            return await self._aexecute_delegate(tool_input, context)

        if tool_name == RUN_BASH_TOOL_NAME:
            # Validation + approval already cleared in the gate; this is the
            # subprocess execution, dispatched uniformly like any handler.
            return await self._run_bash_exec_async(tool_input, context=context)

        handler = self._handlers.get(tool_name)
        if handler is None:
            if self._mcp_manager is not None:
                server = await asyncio.to_thread(self._mcp_manager.find_server_for_tool, tool_name)
                if server is not None:
                    # MCP dispatch gets the same wall-clock guarantee as
                    # handler dispatch — an async MCP adapter awaiting a
                    # never-set event would otherwise hang the spinner
                    # forever (Codex MCP review 2026-06-12).
                    mcp_deadline_s = _tool_deadline_s(tool_name)
                    try:
                        return await asyncio.wait_for(
                            self._execute_mcp_async(server, tool_name, tool_input),
                            timeout=mcp_deadline_s,
                        )
                    except TimeoutError:
                        log.error(
                            "MCP tool %s/%s exceeded its %.0fs wall-clock deadline",
                            server,
                            tool_name,
                            mcp_deadline_s,
                        )
                        return {
                            "error": (
                                f"{server}/{tool_name} exceeded its "
                                f"{mcp_deadline_s:.0f}s wall-clock deadline and was "
                                "aborted by the harness."
                            ),
                            "timeout": True,
                        }
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: '{tool_name}'. Use 'show_help' for available tools."}

        deadline_s = _tool_deadline_s(tool_name)
        try:
            if approved_via_hitl:
                with _tool_spinner(f"Executing {tool_name}..."):
                    raw = await asyncio.wait_for(
                        self._call_handler_async(handler, tool_input, context=context),
                        timeout=deadline_s,
                    )
            else:
                raw = await asyncio.wait_for(
                    self._call_handler_async(handler, tool_input, context=context),
                    timeout=deadline_s,
                )
            return self._normalize_raw_result(tool_name, raw)
        except TimeoutError:
            log.error(
                "Tool %s exceeded its %.0fs wall-clock deadline — aborting the call "
                "(harness deadline, not an HTTP timeout; see PR-LOOP-POLLUTION-FIX)",
                tool_name,
                deadline_s,
            )
            return {
                "error": (
                    f"{tool_name} exceeded its {deadline_s:.0f}s wall-clock deadline "
                    "and was aborted by the harness. The operation may still be "
                    "running server-side; retry or narrow the request."
                ),
                "timeout": True,
            }
        except Exception as exc:
            return self._classify_execution_exception(tool_name, exc)

    async def _gate_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Single safety gate for EVERY tool — classify by safety level + approve.

        Returns ``(rejection_result | None, approved_via_hitl)``. DANGEROUS
        tools approve here and then dispatch uniformly; WRITE / EXPENSIVE / MCP
        go through :class:`ApprovalWorkflow`. Consolidating the gate is what
        keeps a new tool from falling into a dispatch gap — there is one place
        that decides "may this run?", separate from "how does it run?".
        """
        if tool_name in DANGEROUS_TOOLS:
            return await self._gate_dangerous_async(tool_name, tool_input, record)
        return await self._approval.apply_safety_gates_async(tool_name, tool_input, record=record)

    async def _gate_dangerous_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Approval gate for DANGEROUS tools — approval ONLY (execution happens
        in the uniform dispatch so each reaches its handler).

        ``run_bash``: validate + bash approval (skip-permissions-aware).
        ``computer``: session-level approval (continuous control makes
        per-action HITL impractical). A DANGEROUS tool with no branch here
        FAILS CLOSED — returns a denial so it can never dispatch unapproved
        (even with a registered handler); add a branch to gate a new one.
        """
        if tool_name == RUN_BASH_TOOL_NAME:
            command = tool_input.get("command", "")
            if command:
                blocked = self._bash.validate(command)
                if blocked:
                    self._approval.record_transition(record, "denied", "validator:blocked")
                    return self._bash.to_tool_result(blocked), False
                if self._approval.is_bash_auto_approved(command):
                    self._approval.record_transition(record, "granted", "auto:bash")
                else:
                    approved = await self._request_approval_async(
                        command, tool_input.get("reason", ""), record
                    )
                    if not approved:
                        return {"error": "User denied execution", "denied": True}, False
            return None, True
        if tool_name in {"computer", "computer_use"}:
            if not await self._approval.confirm_computer_async(record):
                return {"error": "User denied computer-use", "denied": True}, False
            return None, True
        # Fail CLOSED: a DANGEROUS tool with no explicit gate branch must NOT
        # dispatch unapproved (a registered handler would otherwise run without
        # any approval). Adding a DANGEROUS tool requires adding its gate branch
        # here — pinned by ``test_every_dangerous_tool_is_gated``.
        self._approval.record_transition(record, "denied", "fail-closed:no-gate-branch")
        return {
            "error": (
                f"DANGEROUS tool '{tool_name}' has no approval gate; refusing to run it "
                "unapproved. Add a branch to ToolExecutor._gate_dangerous_async."
            ),
            "denied": True,
        }, False

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

    async def _aexecute_delegate(
        self, tool_input: dict[str, Any], context: ToolContext | None = None
    ) -> dict[str, Any]:
        """Delegate task(s) to sub-agent (async). Supports single and batch.

        PR-Async-Phase-C step 3 (2026-05-22) — async-native sibling of
        :meth:`_execute_delegate`. Uses ``await
        SubAgentManager.adelegate(...)`` so the parent ToolExecutor's
        event loop is not pinned during sub-agent fan-out.

        ``context`` carries the loop's live LLM identity; its ``model`` and
        ``source`` are forwarded so delegation inherits the current
        ``/model`` and credential route. Per-task and AgentDefinition model
        overrides still win over this default.
        """
        from core.agent.sub_agent import SubTask

        if not self._sub_agent_manager:
            return {"error": "SubAgentManager not configured"}

        default_model = getattr(context, "model", "") or ""
        default_source = getattr(context, "source", "") or ""

        tasks_raw: list[dict[str, Any]] = tool_input.get("tasks", [])
        # ``best_of`` applies ONLY to single-task mode. Keyed on the caller's
        # actual call shape, not len(tasks_raw) — a one-item ``tasks`` batch is
        # still batch mode (Codex MCP MED, 2026-07-06).
        single_task_mode = not tasks_raw
        if not tasks_raw:
            tasks_raw = [
                {
                    "task_description": tool_input.get("task_description", ""),
                    "task_type": tool_input.get("task_type", "analyze"),
                    "args": tool_input.get("args", {}),
                    "model": tool_input.get("model", ""),
                    "source": tool_input.get("source", ""),
                    # PR-SUBAGENT-ROLES (2026-07-02) — optional built-in
                    # capability role (see core/agent/subagent_roles.py).
                    "role": tool_input.get("role", ""),
                }
            ]

        # Best-of-N candidate sampling — expand the one task into N copies,
        # each with a distinct diversity lens, then judge-select the winner
        # after the fan-out (GAP 2+4, 2026-07-06).
        # ``bool`` excluded: True would silently mean best_of=1.
        raw_best_of = tool_input.get("best_of", 1)
        best_of = (
            raw_best_of if isinstance(raw_best_of, int) and not isinstance(raw_best_of, bool) else 1
        )
        from core.agent.candidate_sampling import MAX_BEST_OF, lensed_description

        best_of = max(1, min(best_of, MAX_BEST_OF))
        if best_of > 1 and single_task_mode:
            base_task = tasks_raw[0]
            base_description = base_task.get("task_description", "")
            tasks_raw = [
                {**base_task, "task_description": lensed_description(base_description, i)}
                for i in range(best_of)
            ]
        else:
            best_of = 1  # batch mode: ignored (schema documents this)

        # Batch items may carry their own ``role``; the top-level ``role``
        # is the default for items that don't declare one.
        default_role = tool_input.get("role", "")
        ts = int(time.time())
        sub_tasks = [
            SubTask(
                task_id=f"delegate_{ts}_{i}",
                description=t.get("task_description", ""),
                task_type=t.get("task_type", "analyze"),
                args=t.get("args", {}),
                role=str(t.get("role") or default_role or ""),
                model=str(t.get("model") or ""),
                source=str(t.get("source") or default_source or ""),
            )
            for i, t in enumerate(tasks_raw)
        ]

        # P2-C: progress callback — progressive counter (Claude Code pattern)
        completed_count = 0
        total_count = len(sub_tasks)
        _start_ts = time.time()
        _task_starts: dict[str, float] = {t.task_id: time.time() for t in sub_tasks}
        # Stage 1 fleet view — per-task role for the subagent_state feed. The
        # SubResult passed to _on_progress carries no role, so map it here.
        _task_roles: dict[str, str] = {t.task_id: t.role for t in sub_tasks}
        # Stage 1.5 — per-task description, so a mid-run `activity` update
        # (which carries only task_id + tool) can re-emit the running row
        # without losing the label the summary line renders.
        _task_descs: dict[str, str] = {t.task_id: t.description for t in sub_tasks}

        # Fleet view: announce each sub-agent as `running` at dispatch so the
        # thin client's FleetRegistry has a per-agent row before any completes.
        # tokens=0 / elapsed=0 at this point (mid-run token counts are not
        # plumbed — the child subprocess runs quiet=True; see fleet-view doc).
        from core.ui.agentic_ui import emit_subagent_state

        for _sub in sub_tasks:
            emit_subagent_state(_sub.task_id, _sub.role, "running", _sub.description, 0, 0.0)

        _progressed_ids: set[str] = set()

        def _on_activity(update: dict[str, Any]) -> None:
            """Stage 1.5 — a mid-run activity update from a running sub-agent.

            The child worker forwards its *current* tool + best-effort cumulative
            token count (0 for subscription/CLI calls) over the worker stdout
            side-channel. Re-emit the sub-agent's ``running`` state carrying the
            live tool name in ``activity`` so the thin client's FleetRegistry
            updates ``current_activity`` (surfaced by the Stage 2 view).
            """
            tid = str(update.get("task_id", "") or "")
            if not tid or tid in _progressed_ids:
                # No id, or the task already reported terminal — ignore a late
                # activity line so a "running" row can never resurrect.
                return
            tool = str(update.get("tool", "") or "")
            tokens = int(update.get("tokens", 0) or 0)
            elapsed = time.time() - _task_starts.get(tid, _start_ts)
            from core.ui.agentic_ui import emit_subagent_state

            emit_subagent_state(
                tid,
                _task_roles.get(tid, ""),
                "running",
                _task_descs.get(tid, tid),
                tokens,
                elapsed,
                activity=tool,
            )

        def _on_progress(result: Any) -> None:
            nonlocal completed_count
            completed_count += 1
            _progressed_ids.add(str(getattr(result, "task_id", "") or ""))
            task_elapsed = time.time() - _task_starts.get(result.task_id, _start_ts)
            from core.ui.agentic_ui import emit_subagent_state, render_subagent_progress

            render_subagent_progress(
                completed_count,
                total_count,
                result.description or result.task_id,
                task_elapsed,
            )
            # Fleet view: per-agent terminal state with the final token count
            # (0 for subscription/CLI calls — SubResult never fabricates usage).
            tokens = int(getattr(result, "prompt_tokens", 0)) + int(
                getattr(result, "completion_tokens", 0)
            )
            if getattr(result, "success", False):
                status = "done"
            elif "timeout" in str(getattr(result, "error", "") or "").lower():
                status = "timeout"
            else:
                status = "error"
            emit_subagent_state(
                result.task_id,
                _task_roles.get(result.task_id, ""),
                status,
                result.description or result.task_id,
                tokens,
                task_elapsed,
            )

        # announce=False: delegate_task returns full results via tool_result,
        # so skip announce queue to avoid double context injection.
        results = await self._sub_agent_manager.adelegate(
            sub_tasks,
            on_progress=_on_progress,
            on_activity=_on_activity,
            announce=False,
            default_model=default_model,
        )

        # Fleet view: guarantee a terminal state for EVERY dispatched task.
        # Pre-spawn failures (depth-limit / session-cap) return a SubResult
        # without ever calling on_progress, so a "running" row would leak
        # forever and the summary would lie ("N running"). Emit the terminal
        # status for any result the progress callback didn't already cover.
        for r in results:
            tid = getattr(r, "task_id", None)
            if tid is None or tid in _progressed_ids:
                continue
            elapsed = time.time() - _task_starts.get(tid, _start_ts)
            tokens = int(getattr(r, "prompt_tokens", 0)) + int(getattr(r, "completion_tokens", 0))
            if getattr(r, "success", False):
                term = "done"
            elif "timeout" in str(getattr(r, "error", "") or "").lower():
                term = "timeout"
            else:
                term = "error"
            emit_subagent_state(
                tid, _task_roles.get(tid, ""), term, r.description or tid, tokens, elapsed
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
        payload: dict[str, Any] = {
            "tasks": [r.to_dict() for r in results],
            "total": len(results),
            "succeeded": succeeded,
            "summary": f"{succeeded}/{len(results)} tasks completed. [{', '.join(summary_parts)}]",
        }
        if best_of > 1:
            payload["best_of"] = await self._select_best_candidate(
                task_description=tool_input.get("task_description", ""),
                results=results,
                context=context,
            )
        return payload

    async def _select_best_candidate(
        self,
        *,
        task_description: str,
        results: list[Any],
        context: ToolContext | None,
    ) -> dict[str, Any]:
        """Judge-select the winner among best-of-N candidate SubResults.

        Judges only the SUCCESSFUL candidates; the winner block carries
        the winning candidate's full ``to_dict()`` so the model reads
        the selected result without re-scanning ``tasks``. Judge model
        precedence mirrors verify's llm_judge: ``settings.judge_model``
        → the delegating loop's live model → ``settings.model``. When
        the judge INHERITS the loop model, the ToolContext's live
        provider/source route is forwarded so the judge cannot land on
        a different credential source than the session's main calls
        (Codex MCP MED, 2026-07-06); an operator-pinned judge_model
        re-infers its own route (same rule as the reflection node's
        configured-model path). All failure shapes are observable
        (``judge_error``), never silent.
        """
        successful = [r for r in results if getattr(r, "success", False)]
        if not successful:
            return {
                "n": len(results),
                "winner": None,
                "judge_error": "no successful candidates to judge",
            }
        from core.agent.candidate_sampling import candidate_text, judge_candidates
        from core.config import settings

        pinned_judge_model = (getattr(settings, "judge_model", "") or "").strip()
        context_model = getattr(context, "model", "") or ""
        model = pinned_judge_model or context_model or getattr(settings, "model", "")
        inherits_loop_model = not pinned_judge_model and bool(context_model)
        judge_provider = getattr(context, "provider", None) if inherits_loop_model else None
        judge_source = getattr(context, "source", None) if inherits_loop_model else None
        candidate_texts = [candidate_text(getattr(r, "output", None)) for r in successful]
        verdict = await judge_candidates(
            task_description,
            candidate_texts,
            model=model,
            provider=judge_provider,
            source=judge_source,
        )
        winner = successful[verdict.winner_index]
        block: dict[str, Any] = {
            "n": len(results),
            "judged": len(successful),
            "winner_task_id": winner.task_id,
            "winner": winner.to_dict(),
            "reason": verdict.reason,
        }
        if verdict.judge_error:
            block["judge_error"] = verdict.judge_error
        return block

    async def _request_approval_async(
        self, command: str, reason: str, record: ApprovalRecord | None = None
    ) -> bool:
        return await self._approval.request_bash_approval_async(command, reason, record=record)

    async def _run_bash_exec_async(
        self,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Bash subprocess execution + result shaping. Validation + approval
        already cleared in the gate (``_gate_dangerous_async``)."""
        command = tool_input.get("command", "")
        if not command:
            return {"error": "No command provided"}
        try:
            timeout = int(tool_input.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30  # graceful: a malformed timeout must not raise post-approval
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

        mcp_record: ApprovalRecord | None = None
        if not self._auto_approve and not self._approval.is_mcp_approved(server):
            mcp_record = self._approval.begin_mcp_record(server, tool_name)
            if not await self._approval.confirm_mcp_async(server, tool_name, record=mcp_record):
                self._approval.record_transition(mcp_record, "skipped", "mcp-denial")
                return {"error": "User denied MCP tool execution", "denied": True}
            self._approval.mark_mcp_approved(server)
            self._approval.record_transition(mcp_record, "propagated", f"mcp:{server}")

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

        from core.observability.redaction import redact_secrets

        for key in ("stdout", "stderr", "output", "content", "text", "result"):
            if key in result and isinstance(result[key], str):
                result[key] = redact_secrets(result[key])
        if mcp_record is not None:
            self._approval.record_transition(
                mcp_record, "executed", "error" if result.get("error") else "ok"
            )
        return result

    @property
    def registered_tools(self) -> list[str]:
        """List registered tool names."""
        return list(self._handlers.keys())
