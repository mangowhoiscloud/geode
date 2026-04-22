"""Hook System — event-driven extension points for the GEODE pipeline.

Cross-cutting infrastructure accessible by all layers.
Allows registering callbacks for pipeline events (pre/post node execution,
errors, sub-agent lifecycle, etc.).

Supports three trigger modes:
- trigger()              — fire-and-forget observer (L1 Observe)
- trigger_with_result()  — capture handler return values (L3 Decide)
- trigger_interceptor()  — block/modify execution (Interceptor pattern)
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class HookEvent(Enum):
    """Pipeline lifecycle events."""

    # Pipeline level
    PIPELINE_START = "pipeline_start"
    PIPELINE_END = "pipeline_end"
    PIPELINE_ERROR = "pipeline_error"

    # Node level
    NODE_BOOTSTRAP = "node_bootstrap"
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    NODE_ERROR = "node_error"

    # Analysis level
    ANALYST_COMPLETE = "analyst_complete"
    EVALUATOR_COMPLETE = "evaluator_complete"
    SCORING_COMPLETE = "scoring_complete"

    # Verification level
    VERIFICATION_PASS = "verification_pass"  # noqa: S105 — hook event name, not a password
    VERIFICATION_FAIL = "verification_fail"

    # L4.5 Automation level
    DRIFT_DETECTED = "drift_detected"
    OUTCOME_COLLECTED = "outcome_collected"
    MODEL_PROMOTED = "model_promoted"
    SNAPSHOT_CAPTURED = "snapshot_captured"
    TRIGGER_FIRED = "trigger_fired"
    POST_ANALYSIS = "post_analysis"

    # Memory Autonomy (triggered by memory_save/manage_rule tool handlers)
    MEMORY_SAVED = "memory_saved"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"

    # Prompt Assembly (ADR-007) + Drift Detection (Karpathy P4)
    PROMPT_ASSEMBLED = "prompt_assembled"

    # SubAgent lifecycle
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"

    # Tool error recovery (triggered by ToolCallProcessor auto-recovery)
    TOOL_RECOVERY_ATTEMPTED = "tool_recovery_attempted"
    TOOL_RECOVERY_SUCCEEDED = "tool_recovery_succeeded"
    TOOL_RECOVERY_FAILED = "tool_recovery_failed"

    # Agentic turn lifecycle (OpenClaw command:new pattern)
    TURN_COMPLETE = "turn_complete"

    # Context overflow detection (Karpathy P6 Context Budget)
    CONTEXT_CRITICAL = "context_critical"
    CONTEXT_OVERFLOW_ACTION = "context_overflow_action"

    # Session lifecycle (OpenClaw agent:bootstrap pattern)
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # Model switching (L1 Observe)
    MODEL_SWITCHED = "model_switched"

    # LLM call lifecycle (model-level latency/cost observability)
    LLM_CALL_START = "llm_call_start"
    LLM_CALL_END = "llm_call_end"
    LLM_CALL_FAILED = "llm_call_failed"
    LLM_CALL_RETRY = "llm_call_retry"

    # Tool approval HITL lifecycle
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    TOOL_APPROVAL_GRANTED = "tool_approval_granted"
    TOOL_APPROVAL_DENIED = "tool_approval_denied"

    # Cross-provider fallback (LLM resilience)
    FALLBACK_CROSS_PROVIDER = "fallback_cross_provider"

    # Pipeline timeout (B3)
    PIPELINE_TIMEOUT = "pipeline_timeout"

    # Serve lifecycle
    SHUTDOWN_STARTED = "shutdown_started"

    # Config hot-reload
    CONFIG_RELOADED = "config_reloaded"

    # Tool result offloading (P0 token optimization)
    TOOL_RESULT_OFFLOADED = "tool_result_offloaded"

    # MCP server lifecycle
    MCP_SERVER_CONNECTED = "mcp_server_connected"
    MCP_SERVER_FAILED = "mcp_server_failed"

    # Production hooks (P0) — interceptor + cost enforcement + audit
    USER_INPUT_RECEIVED = "user_input_received"
    TOOL_EXEC_START = "tool_exec_start"
    TOOL_EXEC_END = "tool_exec_end"
    TOOL_EXEC_FAILED = "tool_exec_failed"
    TOOL_RESULT_TRANSFORM = "tool_result_transform"
    COST_WARNING = "cost_warning"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    EXECUTION_CANCELLED = "execution_cancelled"

    # Reasoning metrics (DTR-inspired observability)
    REASONING_METRICS = "reasoning_metrics"


@dataclass
class HookResult:
    """Result from a hook execution."""

    success: bool
    event: HookEvent
    handler_name: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None-valued fields."""
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


@dataclass
class InterceptResult:
    """Result from an interceptor hook chain.

    Interceptor hooks can block execution or modify the event data.
    Handlers return ``{"block": True, "reason": "..."}`` to stop the chain,
    or ``{"modify": {"key": "val"}}`` to merge updates into the data dict.
    """

    blocked: bool = False
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# Type alias for hook handlers.
# Return type is dict|None: most handlers return None (fire-and-forget),
# but feedback-style hooks (e.g. CONTEXT_OVERFLOW_ACTION) return a dict
# that trigger_with_result() captures in HookResult.data.
HookHandler = Callable[[HookEvent, dict[str, Any]], dict[str, Any] | None]


@dataclass
class _RegisteredHook:
    """Internal registration record."""

    handler: HookHandler
    name: str
    priority: int  # Lower = higher priority (runs first)
    matcher: str  # Regex pattern for tool_name filtering ("" = match all)


class HookSystem:
    """Register and trigger hooks on pipeline events.

    Hooks execute in priority order (lower number = higher priority).

    Usage:
        hooks = HookSystem()

        def on_start(event, data):
            print(f"Pipeline started for {data.get('ip_name')}")

        hooks.register(HookEvent.PIPELINE_START, on_start, priority=10)
        results = hooks.trigger(HookEvent.PIPELINE_START, {"ip_name": "Berserk"})
    """

    # Events that support matcher-based tool_name filtering.
    _TOOL_EVENTS: frozenset[HookEvent] = frozenset()  # populated after class

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[_RegisteredHook]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        event: HookEvent,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
        matcher: str = "",
    ) -> None:
        """Register a hook handler for an event.

        Args:
            event: The hook event to listen for.
            handler: Callback function.
            name: Unique handler name (defaults to ``handler.__name__``).
            priority: Lower runs first (default 100).
            matcher: Regex pattern matched against ``data["tool_name"]``.
                Empty string (default) matches all tools.
                Only evaluated for ``TOOL_EXEC_*`` and ``TOOL_RESULT_TRANSFORM``
                events; ignored for other events.
        """
        hook_name = name or handler.__name__
        entry = _RegisteredHook(handler=handler, name=hook_name, priority=priority, matcher=matcher)

        with self._lock:
            if event not in self._hooks:
                self._hooks[event] = []
            # Dedup: replace existing handler with same name (prevents
            # double-registration from explicit + filesystem discovery)
            self._hooks[event] = [h for h in self._hooks[event] if h.name != hook_name]
            self._hooks[event].append(entry)
            # Keep sorted by priority (stable sort)
            self._hooks[event].sort(key=lambda h: h.priority)

    def unregister(self, event: HookEvent, name: str) -> bool:
        """Remove a named hook. Returns True if found and removed."""
        with self._lock:
            hooks = self._hooks.get(event, [])
            before = len(hooks)
            self._hooks[event] = [h for h in hooks if h.name != name]
            return len(self._hooks[event]) < before

    def trigger(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[HookResult]:
        """Trigger all hooks for an event in priority order.

        Returns list of HookResults. Errors in one hook don't stop others.
        """
        data = data or {}
        results: list[HookResult] = []
        with self._lock:
            hooks = list(self._hooks.get(event, []))
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                hook.handler(event, data)
                results.append(HookResult(success=True, event=event, handler_name=hook.name))
            except Exception as exc:
                log.warning("Hook '%s' failed on %s: %s", hook.name, event.value, exc)
                results.append(
                    HookResult(
                        success=False,
                        event=event,
                        handler_name=hook.name,
                        error=str(exc),
                    )
                )

        return results

    def trigger_with_result(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Trigger hooks and capture handler return values in HookResult.data.

        Like trigger(), but if a handler returns a dict it is stored in the
        corresponding HookResult.data field. This enables hooks that feed
        recommendations back to the caller (e.g. CONTEXT_OVERFLOW_ACTION).
        """
        data = data or {}
        results: list[HookResult] = []
        with self._lock:
            hooks = list(self._hooks.get(event, []))
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                ret = hook.handler(event, data)
                result_data = ret if isinstance(ret, dict) else {}
                results.append(
                    HookResult(
                        success=True,
                        event=event,
                        handler_name=hook.name,
                        data=result_data,
                    )
                )
            except Exception as exc:
                log.warning("Hook '%s' failed on %s: %s", hook.name, event.value, exc)
                results.append(
                    HookResult(
                        success=False,
                        event=event,
                        handler_name=hook.name,
                        error=str(exc),
                    )
                )

        return results

    def trigger_interceptor(
        self, event: HookEvent, data: dict[str, Any] | None = None, *, timeout_s: float = 0
    ) -> InterceptResult:
        """Trigger hooks as an interceptor chain (block/modify semantics).

        Runs handlers sequentially in priority order. Each handler may return:
        - ``{"block": True, "reason": "..."}`` → stop chain, return blocked
        - ``{"modify": {"key": "val"}}`` → merge into data, continue chain
        - ``None`` or ``{}`` → continue chain unchanged

        Args:
            event: The hook event to trigger.
            data: Mutable event data dict passed to all handlers.
            timeout_s: Per-handler timeout in seconds (0 = no timeout).

        Returns:
            InterceptResult with blocked status, reason, and final data.
        """
        data = dict(data) if data else {}  # defensive copy
        with self._lock:
            hooks = list(self._hooks.get(event, []))
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                ret = self._call_handler(hook, event, data, timeout_s=timeout_s)
                if isinstance(ret, dict):
                    if ret.get("block"):
                        return InterceptResult(
                            blocked=True,
                            reason=ret.get("reason", f"Blocked by {hook.name}"),
                            data=data,
                        )
                    modifications = ret.get("modify")
                    if isinstance(modifications, dict):
                        data.update(modifications)
            except Exception as exc:
                log.warning("Interceptor '%s' failed on %s: %s", hook.name, event.value, exc)
                # Interceptor errors are non-blocking — continue chain

        return InterceptResult(blocked=False, data=data)

    # -- Internal helpers ------------------------------------------------------

    @staticmethod
    def _filter_by_matcher(
        hooks: list[_RegisteredHook],
        event: HookEvent,
        data: dict[str, Any],
    ) -> list[_RegisteredHook]:
        """Filter hooks by matcher pattern for tool-scoped events.

        For non-tool events or hooks without a matcher, all hooks pass through.
        Matcher is a regex tested against ``data["tool_name"]``.
        """
        if event not in HookSystem._TOOL_EVENTS:
            return hooks
        tool_name = data.get("tool_name", "")
        if not tool_name:
            return hooks
        result: list[_RegisteredHook] = []
        for hook in hooks:
            if not hook.matcher:
                result.append(hook)
                continue
            try:
                if re.search(hook.matcher, tool_name):
                    result.append(hook)
            except re.error:
                log.warning("Invalid matcher regex '%s' in hook '%s'", hook.matcher, hook.name)
                result.append(hook)  # fail-open: invalid regex matches all
        return result

    @staticmethod
    def _call_handler(
        hook: _RegisteredHook,
        event: HookEvent,
        data: dict[str, Any],
        *,
        timeout_s: float = 0,
    ) -> dict[str, Any] | None:
        """Call a hook handler with optional timeout.

        When timeout_s > 0, the handler runs in a thread pool with a deadline.
        On timeout, logs a warning and returns None (non-blocking skip).
        """
        if timeout_s <= 0:
            return hook.handler(event, data)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(hook.handler, event, data)
            try:
                return future.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                log.warning(
                    "Hook '%s' timed out on %s (%.1fs limit)",
                    hook.name,
                    event.value,
                    timeout_s,
                )
                return None

    def list_hooks(self, event: HookEvent | None = None) -> dict[str, list[str]]:
        """List registered hook names, optionally filtered by event."""
        with self._lock:
            if event is not None:
                hooks = self._hooks.get(event, [])
                return {event.value: [h.name for h in hooks]}
            return {e.value: [h.name for h in hooks] for e, hooks in self._hooks.items() if hooks}

    def clear(self, event: HookEvent | None = None) -> None:
        """Clear hooks for a specific event, or all hooks."""
        with self._lock:
            if event is not None:
                self._hooks.pop(event, None)
            else:
                self._hooks.clear()


# Populate _TOOL_EVENTS after HookEvent members are available.
HookSystem._TOOL_EVENTS = frozenset(
    {
        HookEvent.TOOL_EXEC_START,
        HookEvent.TOOL_EXEC_END,
        HookEvent.TOOL_EXEC_FAILED,
        HookEvent.TOOL_RESULT_TRANSFORM,
    }
)
