"""ToolExecutor — route tool calls to handlers with HITL safety checks."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping, Set
from contextvars import copy_context
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from core.agent.approval_fsm import ApprovalRecord
    from core.agent.sub_agent import SubAgentManager
    from core.hooks import HookRegistry, HookSystem, MiddlewareRegistry
    from core.tools.base import ToolContext
    from core.tools.plan import BoundToolPlan, ToolRegistration

from core.agent.safety import (
    COLLABORATION_TOOLS,
    DANGEROUS_TOOLS,
    EXPENSIVE_TOOLS,
    SENSITIVE_TOOLS,
    WRITE_TOOLS,
)
from core.hooks.middleware import (
    InvalidMiddlewareResultError,
    ToolCallRequest,
)
from core.hooks.public import (
    HookAction,
    HookCorrelation,
    HookName,
    HookRegistry,
)
from core.tools.bash_tool import BashTool
from core.tools.personal_data import (
    PERSONAL_DATA_ERROR_OMITTED,
    PERSONAL_DATA_TOOLS,
    personal_data_omitted,
)
from core.tools.plan import (
    ApprovalPolicy,
    DataClassification,
    PersistenceRule,
    ResourceKeyResolutionError,
    SafetyPolicy,
    ToolEffect,
    thaw_tool_schema,
)

log = logging.getLogger(__name__)

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]] | Any]
ToolExecutionStartedCallback = Callable[[str, dict[str, Any]], None]


class _ResourceLockEntry:
    __slots__ = ("lock", "references")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.references = 0


ResourceLockLease = tuple[str, _ResourceLockEntry]


class ResourceLockPool:
    """Process-shareable keyed locks for policy-declared resources."""

    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._entries: dict[str, _ResourceLockEntry] = {}

    @property
    def entry_count(self) -> int:
        with self._registry_lock:
            return len(self._entries)

    def _reserve(self, key: str) -> _ResourceLockEntry:
        with self._registry_lock:
            entry = self._entries.setdefault(key, _ResourceLockEntry())
            entry.references += 1
            return entry

    def _drop(self, key: str, entry: _ResourceLockEntry) -> None:
        with self._registry_lock:
            entry.references -= 1
            if entry.references == 0 and self._entries.get(key) is entry:
                self._entries.pop(key, None)

    async def _acquire_cancel_safe(self, key: str, entry: _ResourceLockEntry) -> None:
        future = asyncio.get_running_loop().run_in_executor(None, entry.lock.acquire)
        try:
            acquired = await asyncio.shield(future)
        except asyncio.CancelledError:

            def _release_stray_grant(done: asyncio.Future[bool]) -> None:
                if not done.cancelled() and done.exception() is None and done.result():
                    entry.lock.release()
                self._drop(key, entry)

            future.add_done_callback(_release_stray_grant)
            raise
        if not acquired:
            raise RuntimeError(f"Failed to acquire resource lock: {key}")

    async def acquire(self, keys: tuple[str, ...]) -> tuple[ResourceLockLease, ...]:
        acquired: list[ResourceLockLease] = []
        for key in sorted(set(keys)):
            entry = self._reserve(key)
            try:
                await self._acquire_cancel_safe(key, entry)
            except asyncio.CancelledError:
                self.release(tuple(acquired))
                raise
            except BaseException:
                self._drop(key, entry)
                self.release(tuple(acquired))
                raise
            acquired.append((key, entry))
        return tuple(acquired)

    def release(self, leases: tuple[ResourceLockLease, ...]) -> None:
        for key, entry in reversed(leases):
            entry.lock.release()
            self._drop(key, entry)


# Execution bindings that bypass the ordinary handler map.  Architecture
# inventory imports this set so the model-visible schema and executable surface
# can be compared without duplicating these names in an audit script.
DELEGATE_TASK_TOOL_NAME = "delegate_task"
SPAWN_AGENT_TOOL_NAME = "spawn_agent"
COLLABORATION_TOOL_NAMES = COLLABORATION_TOOLS - {SPAWN_AGENT_TOOL_NAME}
RUN_BASH_TOOL_NAME = "run_bash"
SPECIAL_EXECUTION_BINDINGS: frozenset[str] = frozenset(
    {DELEGATE_TASK_TOOL_NAME, SPAWN_AGENT_TOOL_NAME, RUN_BASH_TOOL_NAME, *COLLABORATION_TOOL_NAMES}
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
        bound_tool_plan: BoundToolPlan | None = None,
        transient_handlers: Mapping[str, ToolHandler] | None = None,
        bash_tool: BashTool | None = None,
        auto_approve: bool = False,
        sub_agent_manager: SubAgentManager | None = None,
        mcp_manager: Any | None = None,
        hitl_level: int = 2,
        hooks: HookSystem | None = None,
        hook_registry: HookRegistry | None = None,
        middleware_registry: MiddlewareRegistry | None = None,
        tool_input_schemas: dict[str, dict[str, Any]] | None = None,
        # (tool_name, detail, safety_level[, approval_id]) -> decision char.
        # 4-arg callbacks receive the ApprovalRecord id for reply matching;
        # legacy 3-arg callbacks are detected and called without it.
        approval_callback: Callable[..., str] | None = None,
        denied_tools: frozenset[str] = frozenset(),
        allowed_tools: frozenset[str] | None = None,
        interactive_approval: bool = True,
        resource_lock_pool: ResourceLockPool | None = None,
        offload_store: Any = None,
    ) -> None:
        if action_handlers is not None and bound_tool_plan is not None:
            raise ValueError("action_handlers and bound_tool_plan are mutually exclusive")
        if transient_handlers is not None and bound_tool_plan is None:
            raise ValueError("transient_handlers requires bound_tool_plan")
        self._bound_tool_plan = bound_tool_plan
        self._handlers: Mapping[str, ToolHandler]
        self._transient_handlers: Mapping[str, ToolHandler]
        if bound_tool_plan is not None:
            transient = dict(transient_handlers or {})
            if collisions := sorted(transient.keys() & bound_tool_plan.plan.execution_map.keys()):
                names = ", ".join(collisions)
                raise ValueError(f"transient handlers collide with tool plan: {names}")
            if invalid := sorted(
                name for name, handler in transient.items() if not callable(handler)
            ):
                raise TypeError(f"transient handlers must be callable: {', '.join(invalid)}")
            self._transient_handlers = MappingProxyType(transient)
            self._handlers = MappingProxyType({**bound_tool_plan.handlers, **transient})
        else:
            self._transient_handlers = MappingProxyType({})
            self._handlers = action_handlers or {}
        self._bound_allowed_tools = (
            frozenset((*bound_tool_plan.tool_names, *self._transient_handlers))
            if bound_tool_plan is not None
            else None
        )
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
        # Session allowlist. The central rail covers native handlers, special
        # tools and MCP dispatch after request-name rewrites.
        self._allowed_tools = allowed_tools
        self._hooks: HookSystem | None = hooks
        if hook_registry is None:
            from core.hooks.public import HookRegistry as _HookRegistry

            hook_registry = _HookRegistry(events=hooks)
        if middleware_registry is None:
            from core.hooks.middleware import MiddlewareRegistry as _MiddlewareRegistry

            middleware_registry = _MiddlewareRegistry(events=hooks)
        self._hook_registry = hook_registry
        self._middleware_registry = middleware_registry
        if bound_tool_plan is not None:
            from core.tools.plan import thaw_tool_schema

            if tool_input_schemas is not None:
                raise ValueError("tool_input_schemas and bound_tool_plan are mutually exclusive")
            bound_schemas = {
                spec.name: thaw_tool_schema(spec.input_schema)
                for spec in bound_tool_plan.ordered_specs
            }
            self._tool_input_schemas = bound_schemas
        else:
            self._tool_input_schemas = dict(tool_input_schemas or {})
        self._approval_callback = approval_callback
        self._interactive_approval = interactive_approval
        self._resource_lock_pool = resource_lock_pool or ResourceLockPool()
        self._offload_store = offload_store

        # HITL approval workflow (extracted — SRP)
        from core.agent.approval import ApprovalWorkflow

        self._approval = ApprovalWorkflow(
            auto_approve=auto_approve,
            hitl_level=hitl_level,
            hooks=hooks,
            hook_registry=hook_registry,
            approval_callback=approval_callback,
            interactive_approval=interactive_approval,
        )

    @property
    def hook_registry(self) -> HookRegistry:
        """Public hook registry shared with the owning agent loop."""
        return self._hook_registry

    @property
    def middleware_registry(self) -> MiddlewareRegistry:
        """Trusted middleware registry shared with the owning agent loop."""
        return self._middleware_registry

    def attach_evidence_ledger(self, ledger: Any | None) -> None:
        """Attach the session EvidenceLedger for approval-FSM terminal rows.

        Called by AgenticLoop after it builds the per-session ledger (the
        loop owns the session identity; the executor is constructed before
        the loop exists). Best-effort — approval flows skip the ledger rail
        silently when none is attached.
        """
        self._approval.attach_evidence_ledger(ledger)

    def _replace_bound_tool_scope(self, transient_tool_names: Set[str]) -> None:
        """Replace the immutable dynamic overlay admitted beside this bound plan."""
        if self._bound_tool_plan is None:
            raise RuntimeError("bound tool scope requires a bound_tool_plan")
        self._bound_allowed_tools = frozenset(
            (*self._bound_tool_plan.tool_names, *self._transient_handlers, *transient_tool_names)
        )

    def _replace_bound_tool_plan(self, bound_tool_plan: BoundToolPlan) -> None:
        """Atomically replace provider/policy-projected schemas and handlers."""
        if self._bound_tool_plan is None:
            raise RuntimeError("bound tool replacement requires a bound_tool_plan")
        if collisions := sorted(
            self._transient_handlers.keys() & bound_tool_plan.plan.execution_map.keys()
        ):
            raise ValueError(f"transient handlers collide with tool plan: {', '.join(collisions)}")
        from core.tools.plan import thaw_tool_schema

        self._bound_tool_plan = bound_tool_plan
        self._handlers = MappingProxyType({**bound_tool_plan.handlers, **self._transient_handlers})
        self._tool_input_schemas = {
            spec.name: thaw_tool_schema(spec.input_schema) for spec in bound_tool_plan.ordered_specs
        }
        self._bound_allowed_tools = frozenset(
            (*bound_tool_plan.tool_names, *self._transient_handlers)
        )

    def _execution_plan(self, context: ToolContext | None) -> BoundToolPlan | None:
        captured = context.bound_tool_plan if context is not None else None
        if captured is None:
            return self._bound_tool_plan
        if self._bound_tool_plan is None or captured.base is not self._bound_tool_plan.base:
            raise ValueError("tool context carries an unrelated bound tool plan")
        if context is not None and (
            context.tool_plan_hash != captured.content_hash
            or context.tool_plan_generation != captured.generation
        ):
            raise ValueError("tool context plan identity does not match its captured plan")
        return captured

    def _registration_for(
        self,
        tool_name: str,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> ToolRegistration | None:
        plan = bound_tool_plan or self._bound_tool_plan
        if plan is None:
            return None
        return plan.registration_for(tool_name)

    def _contains_restricted_data(
        self,
        tool_name: str,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> bool:
        registration = self._registration_for(tool_name, bound_tool_plan=bound_tool_plan)
        if registration is None:
            return tool_name in PERSONAL_DATA_TOOLS
        return bool(
            registration.safety.data_class is DataClassification.PERSONAL
            or registration.safety.persistence is PersistenceRule.REDACT
        )

    def _safety_minimum_for(
        self,
        tool_name: str,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> SafetyPolicy | None:
        registration = self._registration_for(tool_name, bound_tool_plan=bound_tool_plan)
        if registration is not None:
            return registration.safety
        if tool_name in SENSITIVE_TOOLS:
            return SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
                approval=ApprovalPolicy.PER_INVOCATION,
                allow_headless=False,
            )
        if tool_name in DANGEROUS_TOOLS:
            return SafetyPolicy(
                effect=ToolEffect.EXECUTE,
                approval=ApprovalPolicy.CACHED,
                allow_headless=False,
            )
        if tool_name in WRITE_TOOLS:
            return SafetyPolicy(
                effect=ToolEffect.MUTATE,
                approval=ApprovalPolicy.CACHED,
            )
        if tool_name in EXPENSIVE_TOOLS:
            return SafetyPolicy(approval=ApprovalPolicy.CACHED)
        if self._mcp_manager is not None:
            try:
                if self._mcp_manager.find_server_for_tool(tool_name) is not None:
                    return SafetyPolicy(approval=ApprovalPolicy.CACHED)
            except Exception:
                log.debug("MCP safety lookup failed for %s", tool_name, exc_info=True)
        return None

    def _runtime_policy_denial(
        self,
        tool_name: str,
        context: ToolContext | None,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> dict[str, Any] | None:
        registration = self._registration_for(tool_name, bound_tool_plan=bound_tool_plan)
        if registration is None:
            return None
        safety = registration.safety
        if safety.denied:
            reason = "declared policy"
        elif context is not None and context.is_subagent and not safety.allow_subagents:
            reason = "sub-agent policy"
        elif not self._interactive_approval and not safety.allow_headless:
            reason = "headless policy"
        else:
            return None
        return {
            "error": f"Tool '{tool_name}' is unavailable under {reason}.",
            "error_type": "tool_policy_denied",
            "denied": True,
            "recoverable": False,
        }

    @staticmethod
    def _policy_downgrade(
        minimum: SafetyPolicy | None,
        current: SafetyPolicy | None,
    ) -> bool:
        if minimum is None:
            return False
        if current is None:
            return True
        approval_rank = {
            ApprovalPolicy.NONE: 0,
            ApprovalPolicy.CACHED: 1,
            ApprovalPolicy.PER_INVOCATION: 2,
        }
        effect_downgrade = current.effect is not minimum.effect and not (
            minimum.effect is ToolEffect.READ and current.effect is not ToolEffect.READ
        )
        return any(
            (
                approval_rank[current.approval] < approval_rank[minimum.approval],
                effect_downgrade,
                minimum.data_class is DataClassification.PERSONAL
                and current.data_class is DataClassification.PUBLIC,
                minimum.persistence is PersistenceRule.REDACT
                and current.persistence is PersistenceRule.PERSIST,
                not minimum.allow_headless and current.allow_headless,
                not minimum.allow_subagents and current.allow_subagents,
                minimum.denied and not current.denied,
            )
        )

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
        on_execution_started: ToolExecutionStartedCallback | None = None,
    ) -> dict[str, Any]:
        """Execute a tool call through the async runtime path.

        Async-native handlers are awaited directly. Legacy sync handlers are
        isolated behind ``asyncio.to_thread`` so the agent loop no longer wraps
        the entire executor in a thread.
        """
        from core.agent.cognitive_state_ctx import (
            reset_tool_call_id,
            set_tool_call_id,
        )

        token = set_tool_call_id(context.tool_call_id if context is not None else "")
        try:
            return await self._aexecute_bound(
                tool_name,
                tool_input,
                context=context,
                on_execution_started=on_execution_started,
            )
        finally:
            reset_tool_call_id(token)

    async def _aexecute_bound(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None,
        on_execution_started: ToolExecutionStartedCallback | None,
    ) -> dict[str, Any]:
        """Execute inside the physical tool-call correlation scope."""
        bound_tool_plan = self._execution_plan(context)
        minimum_safety = self._safety_minimum_for(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        contains_personal_data = self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        batch_cost_approved = bool(context and context.batch_cost_approved)
        if context is not None:
            context.contains_personal_data = (
                context.contains_personal_data or contains_personal_data
            )
        initial_scope_denial = self._session_scope_denial(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        if initial_scope_denial is not None:
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=contains_personal_data,
            )
            return initial_scope_denial
        correlation = self._tool_correlation(context)
        request = await self._middleware_registry.tool_request(
            ToolCallRequest(
                tool_name=tool_name,
                arguments=dict(tool_input),
                context=context,
                correlation={
                    "session_id": correlation.session_id,
                    "turn_id": correlation.turn_id,
                    "step_id": correlation.step_id,
                    "run_id": correlation.run_id,
                    "session_generation": correlation.session_generation,
                    "verify_attempt": correlation.verify_attempt,
                    "tool_call_id": correlation.tool_call_id,
                },
            )
        )
        tool_name = request.tool_name
        tool_input = dict(request.arguments)
        request_safety = self._safety_minimum_for(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        if contains_personal_data and not self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        ):
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=True,
            )
            return {
                "error": "Personal-data classification cannot be downgraded by a tool rewrite.",
                "error_type": "privacy_classification_downgrade",
                "denied": True,
                "recoverable": False,
            }
        if self._policy_downgrade(
            minimum_safety,
            request_safety,
        ):
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=contains_personal_data,
            )
            return {
                "error": "Tool rewrite cannot weaken its declared safety policy.",
                "error_type": "tool_policy_downgrade",
                "denied": True,
                "recoverable": False,
            }
        if request_safety is not None:
            minimum_safety = request_safety
        contains_personal_data = contains_personal_data or self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        scope_denial = self._session_scope_denial(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        if scope_denial is not None:
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=contains_personal_data,
            )
            return scope_denial
        policy_denial = self._runtime_policy_denial(
            tool_name,
            context,
            bound_tool_plan=bound_tool_plan,
        )
        if policy_denial is not None:
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=contains_personal_data,
            )
            return policy_denial
        if context is not None:
            # Request middleware owns name/argument transforms, not approval
            # grants carried by the processor-owned execution context.
            context.batch_cost_approved = batch_cost_approved
        self._record_effective_request(
            context,
            tool_name,
            tool_input,
            contains_personal_data=contains_personal_data,
        )
        validation_error = self._validate_tool_input(
            tool_name,
            tool_input,
            bound_tool_plan=bound_tool_plan,
        )
        if validation_error:
            return {
                "error": validation_error,
                "error_type": "invalid_tool_input",
                "recoverable": True,
            }

        pre_use = await self._hook_registry.invoke(
            HookName.PRE_TOOL_USE,
            payload={
                "tool_name": tool_name,
                "arguments": (
                    personal_data_omitted(tool_name) if contains_personal_data else tool_input
                ),
            },
            correlation=correlation,
        )
        if pre_use.blocked:
            reason = next(
                (
                    decision.reason
                    for decision in pre_use.decisions
                    if decision.action is HookAction.BLOCK
                ),
                "Blocked by PreToolUse hook",
            )
            return {
                "error": reason,
                "error_type": "hook_blocked",
                "blocked_by_hook": True,
                "recoverable": False,
            }
        rewrite_decisions = [
            decision for decision in pre_use.decisions if decision.action is HookAction.REWRITE
        ]
        if rewrite_decisions:
            effective_name = pre_use.invocation.payload.get("tool_name")
            effective_arguments = pre_use.invocation.payload.get("arguments")
            if any(
                "tool_name" in decision.updates for decision in rewrite_decisions
            ) and isinstance(effective_name, str):
                tool_name = effective_name
            if any(
                "arguments" in decision.updates for decision in rewrite_decisions
            ) and isinstance(effective_arguments, dict):
                tool_input = dict(effective_arguments)
        hook_safety = self._safety_minimum_for(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        if contains_personal_data and not self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        ):
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=True,
            )
            return {
                "error": "Personal-data classification cannot be downgraded by a tool rewrite.",
                "error_type": "privacy_classification_downgrade",
                "denied": True,
                "recoverable": False,
            }
        if self._policy_downgrade(
            minimum_safety,
            hook_safety,
        ):
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=contains_personal_data,
            )
            return {
                "error": "Tool rewrite cannot weaken its declared safety policy.",
                "error_type": "tool_policy_downgrade",
                "denied": True,
                "recoverable": False,
            }
        scope_denial = self._session_scope_denial(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        if scope_denial is not None:
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=(
                    contains_personal_data
                    or self._contains_restricted_data(
                        tool_name,
                        bound_tool_plan=bound_tool_plan,
                    )
                ),
            )
            return scope_denial
        policy_denial = self._runtime_policy_denial(
            tool_name,
            context,
            bound_tool_plan=bound_tool_plan,
        )
        if policy_denial is not None:
            self._record_effective_request(
                context,
                tool_name,
                tool_input,
                contains_personal_data=(
                    contains_personal_data
                    or self._contains_restricted_data(
                        tool_name,
                        bound_tool_plan=bound_tool_plan,
                    )
                ),
            )
            return policy_denial
        contains_personal_data = contains_personal_data or self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        )
        self._record_effective_request(
            context,
            tool_name,
            tool_input,
            contains_personal_data=contains_personal_data,
        )
        validation_error = self._validate_tool_input(
            tool_name,
            tool_input,
            bound_tool_plan=bound_tool_plan,
        )
        if validation_error:
            return {
                "error": validation_error,
                "error_type": "invalid_tool_input",
                "recoverable": True,
            }
        force_permission = any(
            decision.action is HookAction.REQUEST_PERMISSION for decision in pre_use.decisions
        )

        return await self._aexecute_effective(
            ToolCallRequest(
                tool_name=tool_name,
                arguments=tool_input,
                context=context,
                correlation=request.correlation,
            ),
            force_permission=force_permission,
            on_execution_started=on_execution_started,
            bound_tool_plan=bound_tool_plan,
        )

    async def _aexecute_effective(
        self,
        request: ToolCallRequest,
        *,
        force_permission: bool = False,
        on_execution_started: ToolExecutionStartedCallback | None = None,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> dict[str, Any]:
        """Gate one effective request, then wrap only its accepted dispatch."""
        tool_name = request.tool_name
        tool_input = dict(request.arguments)
        context = cast("ToolContext | None", request.context)
        correlation = self._tool_correlation(context)
        contains_personal_data = self._contains_restricted_data(
            tool_name,
            bound_tool_plan=bound_tool_plan,
        ) or bool(context and context.contains_personal_data)
        log.debug("ToolExecutor.async: %s(keys=%s)", tool_name, sorted(tool_input))

        if context and context.cancellation and context.cancellation.is_set():
            return {"error": "Tool execution cancelled before start", "cancelled": True}

        budget_permission = (
            tool_name == "create_goal" and tool_input.get("token_budget") is not None
        )
        force_permission = force_permission or budget_permission
        if force_permission:
            detail = (
                f"token_budget={tool_input['token_budget']}" if budget_permission else tool_name
            )
            permission_granted = await self._approval.confirm_permission_request_async(
                "Allow token-limited Goal?" if budget_permission else "Allow?",
                detail,
                safety_level="goal_budget" if budget_permission else "hook_requested",
                tool_name=tool_name,
                allow_human_prompt=self._interactive_approval,
                correlation=correlation,
            )
            if not permission_granted:
                return {
                    "error": (
                        "token_budget requires explicit PermissionRequest approval; "
                        "retry create_goal without token_budget when no budget was requested"
                        if budget_permission
                        else f"Permission denied for '{tool_name}'"
                    ),
                    "denied": True,
                    "recoverable": budget_permission,
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
        registration = self._registration_for(tool_name, bound_tool_plan=bound_tool_plan)
        declared_approval = (
            registration.safety.approval if registration is not None else ApprovalPolicy.NONE
        )
        record = (
            self._approval.begin_record(tool_name, correlation=correlation)
            if declared_approval is ApprovalPolicy.NONE
            else self._approval.begin_record(
                tool_name,
                declared_approval=declared_approval.value,
                correlation=correlation,
            )
        )
        declared_approval_granted = force_permission
        if force_permission:
            self._approval.record_transition(record, "granted", "hook:permission")
        if registration is not None:
            uses_special_gate = tool_name in DANGEROUS_TOOLS
            if not declared_approval_granted and (
                declared_approval is ApprovalPolicy.PER_INVOCATION
                or (declared_approval is ApprovalPolicy.CACHED and not uses_special_gate)
            ):
                if (
                    declared_approval is ApprovalPolicy.CACHED
                    and tool_name in EXPENSIVE_TOOLS
                    and bool(context and context.batch_cost_approved)
                ):
                    self._approval.record_transition(record, "granted", "batch:cost-approved")
                    declared_approval_granted = True
                else:
                    declared_approval_granted = await self._approval.confirm_declared_async(
                        tool_name,
                        tool_input,
                        per_invocation=declared_approval is ApprovalPolicy.PER_INVOCATION,
                        contains_personal_data=contains_personal_data,
                        record=record,
                    )
                    if not declared_approval_granted:
                        self._approval.record_transition(record, "skipped", "gate-rejected")
                        return {
                            "error": f"Permission denied for '{tool_name}'",
                            "denied": True,
                            "recoverable": False,
                        }
            if uses_special_gate:
                gate_result, approved_via_hitl = await self._gate_dangerous_async(
                    tool_name,
                    tool_input,
                    record,
                    approval_already_granted=(
                        declared_approval is ApprovalPolicy.NONE or declared_approval_granted
                    ),
                )
            else:
                gate_result, approved_via_hitl = None, declared_approval_granted
        else:
            gate_result, approved_via_hitl = await self._gate_async(
                tool_name,
                tool_input,
                record,
                batch_cost_approved=bool(context and context.batch_cost_approved),
                approval_already_granted=force_permission,
            )
        if gate_result is not None:
            self._approval.record_transition(record, "skipped", "gate-rejected")
            return gate_result
        if record is not None and record.state == "requested":
            # No gate branch consumed the record (e.g. an EXPENSIVE tool while
            # batch approval temporarily set auto_approve) — close the chain
            # explicitly so the dispatch transitions stay legal.
            self._approval.record_transition(record, "granted", "auto:ungated")
        self._approval.record_transition(record, "propagated", "dispatch")
        terminal_started = False
        started_at = time.monotonic()
        event_tool_input = (
            personal_data_omitted(tool_name) if contains_personal_data else tool_input
        )
        event_correlation = dict(request.correlation)

        async def dispatch(current: ToolCallRequest) -> dict[str, Any]:
            nonlocal terminal_started
            if current.tool_name != tool_name or dict(current.arguments) != tool_input:
                raise InvalidMiddlewareResultError(
                    "tool_execution middleware cannot change an already-approved request"
                )
            resource_keys: tuple[str, ...] = ()
            if bound_tool_plan is not None and registration is not None:
                try:
                    resource_keys = bound_tool_plan.resource_keys(tool_name, tool_input)
                except ResourceKeyResolutionError:
                    return {
                        "error": f"Resource policy could not resolve '{tool_name}'.",
                        "error_type": "resource_key_resolution",
                        "denied": True,
                        "recoverable": False,
                    }
            elif self._mcp_manager is not None:
                resolve_mcp_resources = getattr(self._mcp_manager, "resource_keys_for_tool", None)
                if callable(resolve_mcp_resources):
                    resolved_mcp_keys = cast(
                        "tuple[str, ...] | None", resolve_mcp_resources(tool_name)
                    )
                    if resolved_mcp_keys is None:
                        return {
                            "error": f"MCP resource policy is undeclared for '{tool_name}'.",
                            "error_type": "resource_key_resolution",
                            "denied": True,
                            "recoverable": False,
                        }
                    resource_keys = resolved_mcp_keys
            leases = await self._resource_lock_pool.acquire(resource_keys)
            release_deferred = False

            def defer_release(future: asyncio.Future[Any]) -> None:
                nonlocal release_deferred
                release_deferred = True

                def release_when_done(done: asyncio.Future[Any]) -> None:
                    if not done.cancelled():
                        done.exception()
                    self._resource_lock_pool.release(leases)

                future.add_done_callback(release_when_done)

            terminal_started = True
            from core.hooks.dispatch import fire_hook_async
            from core.hooks.system import RuntimeEvent

            try:
                if on_execution_started is not None:
                    try:
                        on_execution_started(tool_name, event_tool_input)
                    except Exception:
                        log.debug("Tool execution-start recorder failed", exc_info=True)
                await fire_hook_async(
                    self._hooks,
                    RuntimeEvent.TOOL_EXEC_STARTED,
                    {
                        **event_correlation,
                        "tool_name": tool_name,
                        "tool_input": event_tool_input,
                    },
                )
                return await self._dispatch_async(
                    tool_name,
                    tool_input,
                    context=context,
                    approved_via_hitl=approved_via_hitl,
                    on_sync_abandoned=defer_release,
                    bound_tool_plan=bound_tool_plan,
                )
            finally:
                if not release_deferred:
                    self._resource_lock_pool.release(leases)

        try:
            result = await self._middleware_registry.tool_execution(request, dispatch)
        except BaseException as exc:
            from core.hooks.dispatch import fire_hook_async
            from core.hooks.system import RuntimeEvent

            if record is not None:
                self._approval.record_transition(
                    record,
                    "executed" if terminal_started else "skipped",
                    f"exception:{type(exc).__name__}",
                )
            await fire_hook_async(
                self._hooks,
                RuntimeEvent.TOOL_EXEC_FAILED,
                {
                    **event_correlation,
                    "tool_name": tool_name,
                    "tool_input": event_tool_input,
                    "duration_ms": (time.monotonic() - started_at) * 1_000,
                    "error": (PERSONAL_DATA_ERROR_OMITTED if contains_personal_data else str(exc)),
                    "error_type": type(exc).__name__,
                    "recoverable": False,
                    "executed": terminal_started,
                },
            )
            raise

        if record is not None:
            has_error = isinstance(result, dict) and bool(result.get("error"))
            self._approval.record_transition(
                record,
                "executed" if terminal_started else "skipped",
                ("error" if has_error else "ok")
                if terminal_started
                else "middleware-short-circuit",
            )

        from core.hooks.dispatch import fire_hook_async
        from core.hooks.system import RuntimeEvent

        has_error = bool(result.get("error"))
        await fire_hook_async(
            self._hooks,
            RuntimeEvent.TOOL_EXEC_ENDED,
            {
                **event_correlation,
                "tool_name": tool_name,
                "tool_input": event_tool_input,
                "duration_ms": (time.monotonic() - started_at) * 1_000,
                "has_error": has_error,
                "result": (personal_data_omitted(tool_name) if contains_personal_data else result),
                "executed": terminal_started,
            },
        )
        if has_error:
            await fire_hook_async(
                self._hooks,
                RuntimeEvent.TOOL_EXEC_FAILED,
                {
                    **event_correlation,
                    "tool_name": tool_name,
                    "tool_input": event_tool_input,
                    "duration_ms": (time.monotonic() - started_at) * 1_000,
                    "error": (
                        PERSONAL_DATA_ERROR_OMITTED
                        if contains_personal_data
                        else str(result.get("error", ""))
                    ),
                    "error_type": str(result.get("error_type", "unknown")),
                    "recoverable": bool(result.get("recoverable", True)),
                    "executed": terminal_started,
                },
            )

        post_use = await self._hook_registry.invoke(
            HookName.POST_TOOL_USE,
            payload={
                "tool_name": tool_name,
                "arguments": event_tool_input,
                "result": (personal_data_omitted(tool_name) if contains_personal_data else result),
                "has_error": has_error,
                "executed": terminal_started,
            },
            correlation=self._tool_correlation(context),
        )
        for decision in post_use.decisions:
            if decision.action is HookAction.ADD_CONTEXT and decision.instruction:
                previous = str(result.get("additional_context", ""))
                result["additional_context"] = (
                    f"{previous}\n{decision.instruction}" if previous else decision.instruction
                )
        if post_use.blocked:
            return {
                "error": "Tool result withheld by PostToolUse hook",
                "error_type": "hook_blocked",
                "blocked_by_hook": True,
                "recoverable": False,
            }
        return result

    def _session_scope_denial(
        self,
        tool_name: str,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> dict[str, Any] | None:
        """Reject tools outside this session before schema lookup or hooks."""
        bound_allowed_tools = self._bound_allowed_tools
        if (
            bound_tool_plan is not None
            and self._bound_tool_plan is not None
            and bound_tool_plan is not self._bound_tool_plan
        ):
            transient_names = set(bound_allowed_tools or ()) - set(self._bound_tool_plan.tool_names)
            bound_allowed_tools = frozenset((*bound_tool_plan.tool_names, *transient_names))
        if tool_name in self._denied_tools:
            reason = "headless denylist"
        elif bound_allowed_tools is not None and tool_name not in bound_allowed_tools:
            reason = "bound tool plan"
        elif self._allowed_tools is not None and tool_name not in self._allowed_tools:
            reason = "binding allowlist"
        else:
            return None
        log.info("Tool %s denied on this session (%s)", tool_name, reason)
        return {
            "error": f"Tool '{tool_name}' is not available in this session.",
            "denied": True,
        }

    @staticmethod
    def _record_effective_request(
        context: ToolContext | None,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        contains_personal_data: bool,
    ) -> None:
        if context is None:
            return
        context.effective_tool_name = tool_name
        context.effective_tool_arguments = dict(tool_input)
        context.contains_personal_data = contains_personal_data

    @staticmethod
    def _tool_correlation(context: ToolContext | None = None) -> HookCorrelation:
        try:
            from core.agent.cognitive_state_ctx import get_session_id, get_turn_id

            return HookCorrelation(
                session_id=(context.session_id if context is not None else "") or get_session_id(),
                turn_id=(context.turn_id if context is not None else "") or get_turn_id(),
                step_id=(context.step_id if context is not None else ""),
                session_generation=(context.session_generation if context is not None else 0),
                verify_attempt=(context.verify_attempt if context is not None else 0),
                tool_call_id=str(
                    getattr(context, "tool_call_id", "") if context is not None else ""
                ),
            )
        except Exception:
            return HookCorrelation()

    def _validate_tool_input(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> str:
        """Validate against a caller-owned schema before the built-in fallback."""
        from jsonschema import Draft202012Validator

        spec = bound_tool_plan.schema_map.get(tool_name) if bound_tool_plan is not None else None
        schema = thaw_tool_schema(spec.input_schema) if spec is not None else None
        if schema is None:
            schema = self._tool_input_schemas.get(tool_name)
        if schema is None:
            try:
                from core.tools.base import load_tool_definition

                schema = load_tool_definition(tool_name).get("input_schema", {})
            except KeyError:
                return ""
            except Exception as exc:
                log.warning("Tool schema lookup failed for %s: %s", tool_name, exc)
                return ""
        errors = sorted(
            Draft202012Validator(schema).iter_errors(tool_input),
            key=lambda error: tuple(str(part) for part in error.path),
        )
        if not errors:
            return ""
        first = errors[0]
        location = ".".join(str(part) for part in first.path)
        prefix = f"{location}: " if location else ""
        return f"Invalid input for '{tool_name}': {prefix}{first.message}"

    async def _dispatch_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
        approved_via_hitl: bool = False,
        on_sync_abandoned: Callable[[asyncio.Future[Any]], None] | None = None,
        bound_tool_plan: BoundToolPlan | None = None,
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

        if tool_name == SPAWN_AGENT_TOOL_NAME:
            return await self._aexecute_spawn_agent(tool_input, context)

        if tool_name in COLLABORATION_TOOL_NAMES:
            return await self._aexecute_collaboration(tool_name, tool_input, context)

        if tool_name == RUN_BASH_TOOL_NAME:
            # Validation + approval already cleared in the gate; this is the
            # subprocess execution, dispatched uniformly like any handler.
            return await self._run_bash_exec_async(tool_input, context=context)

        handler = (
            bound_tool_plan.handlers.get(tool_name)
            if bound_tool_plan is not None and tool_name in bound_tool_plan.tool_names
            else self._handlers.get(tool_name)
        )
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
                            self._execute_mcp_async(server, tool_name, tool_input, context=context),
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
                known = self._mcp_manager.last_known_server_for_tool(tool_name)
                if known is not None:
                    # The tool IS in the model's schema list — telling the
                    # model it doesn't exist would misinform it (ADR-014 R3).
                    log.warning(
                        "MCP tool %s unavailable: server '%s' down or cooling",
                        tool_name,
                        known,
                    )
                    return {
                        "error": (
                            f"MCP server '{known}' providing '{tool_name}' is "
                            "currently unavailable (down or in retry cooldown). "
                            "Retry later or use an alternative tool."
                        )
                    }
            log.warning("No handler for tool: %s", tool_name)
            return {"error": f"Unknown tool: '{tool_name}'. Use 'show_help' for available tools."}

        deadline_s = _tool_deadline_s(tool_name)
        sync_future: asyncio.Future[Any] | None = None

        def capture_sync_future(future: asyncio.Future[Any]) -> None:
            nonlocal sync_future
            sync_future = future

        try:
            if approved_via_hitl:
                with _tool_spinner(f"Executing {tool_name}..."):
                    raw = await asyncio.wait_for(
                        self._call_handler_async(
                            handler,
                            tool_input,
                            context=context,
                            on_sync_future=capture_sync_future,
                        ),
                        timeout=deadline_s,
                    )
            else:
                raw = await asyncio.wait_for(
                    self._call_handler_async(
                        handler,
                        tool_input,
                        context=context,
                        on_sync_future=capture_sync_future,
                    ),
                    timeout=deadline_s,
                )
            return self._normalize_raw_result(tool_name, raw)
        except asyncio.CancelledError:
            if sync_future is not None and not sync_future.done() and on_sync_abandoned is not None:
                on_sync_abandoned(sync_future)
            raise
        except TimeoutError:
            if sync_future is not None and not sync_future.done() and on_sync_abandoned is not None:
                on_sync_abandoned(sync_future)
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
            return self._classify_execution_exception(
                tool_name,
                exc,
                bound_tool_plan=bound_tool_plan,
            )

    async def _gate_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
        *,
        batch_cost_approved: bool = False,
        approval_already_granted: bool = False,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Single safety gate for EVERY tool — classify by safety level + approve.

        Returns ``(rejection_result | None, approved_via_hitl)``. DANGEROUS
        tools approve here and then dispatch uniformly; WRITE / EXPENSIVE / MCP
        go through :class:`ApprovalWorkflow`. Consolidating the gate is what
        keeps a new tool from falling into a dispatch gap — there is one place
        that decides "may this run?", separate from "how does it run?".
        """
        if tool_name in DANGEROUS_TOOLS:
            return await self._gate_dangerous_async(
                tool_name,
                tool_input,
                record,
                approval_already_granted=approval_already_granted,
            )
        if approval_already_granted:
            return None, True
        return await self._approval.apply_safety_gates_async(
            tool_name,
            tool_input,
            record=record,
            batch_cost_approved=batch_cost_approved,
        )

    async def _gate_dangerous_async(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        record: ApprovalRecord | None = None,
        *,
        approval_already_granted: bool = False,
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
                if approval_already_granted:
                    pass
                elif self._approval.is_bash_auto_approved(command):
                    self._approval.record_transition(record, "granted", "auto:bash")
                else:
                    approved = await self._request_approval_async(
                        command, tool_input.get("reason", ""), record
                    )
                    if not approved:
                        return {"error": "User denied execution", "denied": True}, False
            return None, True
        if tool_name in {"computer", "computer_use"}:
            if approval_already_granted:
                return None, True
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

    async def _call_handler_async(
        self,
        handler: ToolHandler,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
        on_sync_future: Callable[[asyncio.Future[Any]], None] | None = None,
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
        dispatch_context = copy_context()
        future = asyncio.get_running_loop().run_in_executor(
            None,
            partial(dispatch_context.run, handler, **kwargs),
        )
        if on_sync_future is not None:
            on_sync_future(future)
        return await asyncio.shield(future)

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

    def _classify_execution_exception(
        self,
        tool_name: str,
        exc: Exception,
        *,
        bound_tool_plan: BoundToolPlan | None = None,
    ) -> dict[str, Any]:
        if self._contains_restricted_data(tool_name, bound_tool_plan=bound_tool_plan):
            log.error("Tool %s failed with %s", tool_name, type(exc).__name__)
        else:
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
        import uuid

        sub_tasks = [
            SubTask(
                task_id=f"delegate_{uuid.uuid4().hex[:12]}_{i}",
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

        results = await self._sub_agent_manager.adelegate(
            sub_tasks,
            on_progress=_on_progress,
            on_activity=_on_activity,
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

    async def _aexecute_spawn_agent(
        self,
        tool_input: dict[str, Any],
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Start one durable child without overloading foreground delegation."""
        if not self._sub_agent_manager:
            return {"error": "SubAgentManager not configured"}
        from uuid import uuid4

        from core.agent.cognitive_state_ctx import get_session_id
        from core.agent.sub_agent import SubTask

        parent_session_id = str(getattr(context, "session_id", "") or get_session_id())
        if not parent_session_id:
            return {"error": "No active parent session"}
        task = SubTask(
            task_id=f"agent_{uuid4().hex[:12]}",
            description=str(tool_input.get("task_description", "")),
            task_type=str(tool_input.get("task_type", "analyze")),
            args=dict(tool_input.get("args", {})),
            role=str(tool_input.get("role", "")),
            source=str(getattr(context, "source", "") or ""),
        )
        try:
            runs = await self._sub_agent_manager.aspawn(
                [task],
                parent_session_id=parent_session_id,
                default_model=str(getattr(context, "model", "") or ""),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"status": "dispatched", "task": runs[0].to_dict()}

    async def _aexecute_collaboration(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Execute one explicit parent-scoped collaboration operation."""
        if not self._sub_agent_manager:
            return {"error": "SubAgentManager not configured"}
        from core.agent.cognitive_state_ctx import get_session_id

        parent_session_id = str(getattr(context, "session_id", "") or get_session_id())
        if not parent_session_id:
            return {"error": "No active parent session"}
        task_id = str(tool_input.get("task_id", ""))
        message = str(tool_input.get("message", ""))
        default_model = str(getattr(context, "model", "") or "")
        try:
            if tool_name == "list_agents":
                runs = self._sub_agent_manager.list_collaboration_runs(parent_session_id)
                return {"tasks": [run.to_dict() for run in runs], "total": len(runs)}
            if tool_name == "wait_agent":
                raw_timeout = tool_input.get("timeout_seconds", 0.0)
                timeout_s = (
                    float(raw_timeout)
                    if isinstance(raw_timeout, int | float) and not isinstance(raw_timeout, bool)
                    else 0.0
                )
                run = await self._sub_agent_manager.wait_for_task(
                    parent_session_id,
                    task_id,
                    timeout_s=max(0.0, min(timeout_s, 3600.0)),
                )
                timed_out = bool(run and run.status in {"pending", "running"})
                return {"task": run.to_dict() if run else None, "timed_out": timed_out}
            if tool_name == "interrupt_agent":
                accepted = self._sub_agent_manager.interrupt_task(parent_session_id, task_id)
                return {"task_id": task_id, "accepted": accepted}
            if tool_name == "send_message":
                run = self._sub_agent_manager.send_task_message(parent_session_id, task_id, message)
                return {"task": run.to_dict(), "turn_triggered": False}
            if tool_name == "followup_task":
                run, resumed = await self._sub_agent_manager.afollow_up(
                    parent_session_id,
                    task_id,
                    message,
                    default_model=default_model,
                )
                return {"task": run.to_dict(), "turn_triggered": resumed, "resumed": resumed}
            return {"error": f"Unknown collaboration tool: {tool_name}"}
        except ValueError as exc:
            return {"error": str(exc)}

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
            middleware_registry=self._middleware_registry,
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
        self,
        server: str,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        context: ToolContext | None = None,
    ) -> dict[str, Any]:
        """Async MCP tool execution with async server approval."""
        log.info("MCP tool: %s → %s (args=%s)", tool_name, server, list(tool_input.keys()))

        mcp_record: ApprovalRecord | None = None
        if not self._auto_approve and not self._approval.is_mcp_approved(server):
            mcp_record = self._approval.begin_mcp_record(
                server,
                tool_name,
                correlation=self._tool_correlation(context),
            )
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
