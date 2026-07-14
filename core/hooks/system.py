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

import asyncio
import dataclasses
import inspect
import logging
import re
import threading
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

log = logging.getLogger(__name__)


class HookEvent(Enum):
    """Runtime lifecycle events.

    Naming convention (PR-HOOK-TAXONOMY, 2026-07-14): every member
    satisfies ``NAME == VALUE.upper()`` and new event names use the
    past-participle form (``*_STARTED`` / ``*_ENDED`` / ``*_COMPLETED``).
    Legacy stored-event strings from before the value alignment are
    resolved via :data:`LEGACY_EVENT_VALUES` on every read path.

    PR-DEAD-PIPELINE (2026-06-10) — the legacy analysis-pipeline event
    family (PIPELINE_*, NODE_*, ANALYST/EVALUATOR/SCORING_COMPLETED) and
    its cascade (DRIFT_DETECTED, OUTCOME_COLLECTED, MODEL_PROMOTED,
    SNAPSHOT_CAPTURED) were removed: the emitting LangGraph pipeline left
    core in the identity pivot, so the events had no writer and every
    listener was inert.
    """

    # Scheduler trigger level
    TRIGGER_FIRED = "trigger_fired"
    POST_ANALYSIS = "post_analysis"

    # Memory Autonomy (triggered by memory_save/manage_rule tool handlers).
    # RULE_CHANGED collapses the former RULE_CREATED/UPDATED/DELETED trio
    # (PR-HOOK-TAXONOMY D3) — the payload carries
    # ``action="created" | "updated" | "deleted"`` plus ``name`` (and
    # ``paths`` for creations).
    MEMORY_SAVED = "memory_saved"
    RULE_CHANGED = "rule_changed"
    # Human result feedback (rate/accept/reject_result tool handlers). The
    # canonical SQLite sink persists operator verdicts for indexed history.
    RESULT_FEEDBACK = "result_feedback"

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

    # Agentic turn lifecycle (OpenClaw command:new pattern; milestone-style —
    # fires once per turn on completion)
    TURN_COMPLETED = "turn_completed"

    # Context overflow detection (Karpathy P6 Context Budget)
    CONTEXT_CRITICAL = "context_critical"
    CONTEXT_OVERFLOW_ACTION = "context_overflow_action"

    # Session lifecycle (OpenClaw agent:bootstrap pattern; lifecycle pair)
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    # Model switching (L1 Observe)
    MODEL_SWITCHED = "model_switched"

    # LLM call lifecycle (model-level latency/cost observability; STARTED/ENDED
    # are the lifecycle pair, ENDED fires on success+error with ``error`` key,
    # FAILED is a legacy alias retained for plugin compatibility, RETRIED is
    # the action-past form for retry attempts)
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_ENDED = "llm_call_ended"
    LLM_CALL_FAILED = "llm_call_failed"
    LLM_CALL_RETRIED = "llm_call_retried"

    # Tool approval HITL lifecycle. TOOL_APPROVAL_GRANTED/DENIED were
    # deleted (PR-HOOK-TAXONOMY D1): they had zero handlers and the catalog
    # already excluded them from persistence — APPROVAL_TRANSITION carries
    # the granted/denied states with more context.
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    # Approval FSM — ONE event per ApprovalRecord state transition, with the
    # target ``state`` (requested / displayed / user_selected / parsed /
    # granted / denied / propagated / executed / skipped) in the payload
    # instead of nine enums. Fired by ``ApprovalWorkflow.record_transition``
    # (emit-only; the canonical event sink persists it). See
    # ``core/agent/approval_fsm.py``.
    APPROVAL_TRANSITION = "approval_transition"

    # Per-adapter dispatch attempt — fired by
    # ``core.llm.adapters.dispatch._fire_attempt`` for every single-adapter
    # try. Payload: adapter_name, provider, source, capability, outcome
    # (success/billing/transient/unavailable), elapsed_ms, error_type,
    # error_msg. Lets operators trace exactly which adapter handled a
    # web_search / complete_text call without having to parse serve logs.
    ADAPTER_DISPATCH_ATTEMPT = "adapter_dispatch_attempt"

    # Serve lifecycle
    SHUTDOWN_STARTED = "shutdown_started"

    # Config hot-reload
    CONFIG_RELOADED = "config_reloaded"

    # Tool result offloading (P0 token optimization)
    TOOL_RESULT_OFFLOADED = "tool_result_offloaded"

    # MCP server lifecycle
    MCP_SERVER_CONNECTED = "mcp_server_connected"
    MCP_SERVER_FAILED = "mcp_server_failed"

    # Production hooks (P0) — interceptor + cost enforcement + audit.
    # TOOL_EXEC_STARTED / TOOL_EXEC_ENDED form the lifecycle pair; FAILED is the
    # error variant. TOOL_RESULT_TRANSFORM is a separate feedback hook (post
    # observation, result rewriting).
    USER_INPUT_RECEIVED = "user_input_received"
    TOOL_EXEC_STARTED = "tool_exec_started"
    TOOL_EXEC_ENDED = "tool_exec_ended"
    TOOL_EXEC_FAILED = "tool_exec_failed"
    TOOL_RESULT_TRANSFORM = "tool_result_transform"
    COST_WARNING = "cost_warning"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    EXECUTION_CANCELLED = "execution_cancelled"

    # Reasoning metrics (DTR-inspired observability)
    REASONING_METRICS = "reasoning_metrics"

    # Cognitive cycle telemetry (C-6 — PR-2 cognitive-loop uplift sprint).
    # Six steps form the abstract cognitive cycle a downstream Petri /
    # Inspect viewer can segment a session by. Every event carries the
    # ``cognitive_state`` snapshot in its payload (see
    # ``CognitiveState.to_snapshot``) so the viewer can replay state
    # evolution without re-parsing the transcript.
    #
    # PERCEIVE: input received — user prompt + current context observed.
    # PLAN:     pre-LLM-call — the loop is deciding what to do next.
    # ACT:      tool execution started — the loop is taking an action.
    # OBSERVE:  tool execution ended — the loop is reading back results.
    # REFLECT:  round-end summary — the loop is updating its beliefs
    #           (PR-3 adds a dedicated reflection LLM call; PR-2 fires
    #           the event at turn complete with a deterministic
    #           summary).
    # UPDATE_MEMORY: cognitive-level sibling of MEMORY_SAVED — fires
    #           when the loop writes anything that should persist
    #           cross-round (episodic memory / rule update / outcome
    #           ledger entry).
    COGNITIVE_PERCEIVE = "cognitive_perceive"
    COGNITIVE_PLAN = "cognitive_plan"
    COGNITIVE_ACT = "cognitive_act"
    COGNITIVE_OBSERVE = "cognitive_observe"
    COGNITIVE_REFLECT = "cognitive_reflect"
    COGNITIVE_UPDATE_MEMORY = "cognitive_update_memory"

    # Self-improving loop auto-trigger telemetry (OL-A1.5 — 2026-05-22;
    # collapsed to ONE event in PR-HOOK-TAXONOMY D2). One emission per
    # terminal state of ``auto_trigger_mutator`` so a downstream
    # subscriber (audit log writer, Inspect viewer, FE) can count
    # firings, distinguish lock contention from interval gating, and
    # surface runner failures without parsing the daemon log. The
    # terminal state travels in the payload instead of six enums:
    #   {"trigger_id": str, "ts": float, "detail": str,
    #    "stage": "fired" | "lock_busy" | "interval_blocked" |
    #             "runner_error" | "parse_error" | "max_generation_reached"}
    # The ``trigger_id`` is the canonical id from
    # ``AUTO_TRIGGER_TRIGGER_ID`` so subscribers can filter by id when
    # multiple trigger families coexist in the same scheduler. For the
    # ``max_generation_reached`` stage, ``detail`` carries
    # ``"current/max"`` (e.g. ``"100/100"``).
    SELF_IMPROVING_AUTO_TRIGGER = "self_improving_auto_trigger"

    # Wall-clock budget hand-off (PR-CL-BUDGET, 2026-05-23). Replaces the
    # prior turn hard-cap with a 2h time-cap + automatic T-10min hand-off.
    # Payload schema (all variants):
    #   {"session_id": str, "platform": str, "remaining_s": float,
    #    "budget_total_s": float, "ts": float}
    # ``HANDOFF_TRIGGERED`` fires once per session — at the threshold
    # crossing — even if the round loop re-enters the budget check.
    # PR-LOOP-PRUNE (2026-06-13): the RESERVED ``HANDOFF_COMPLETED`` /
    # ``HANDOFF_FAILED`` pair was deleted with the unbuilt watcher's
    # write API (reserve-without-emit rule) — re-add WITH emit sites
    # when a watcher actually lands.
    HANDOFF_TRIGGERED = "handoff_triggered"

    # Per-turn verify telemetry (PR-CL-A3, 2026-05-23). Distinct from the
    # pipeline-level ``VERIFICATION_PASS / VERIFICATION_FAIL`` pair (which
    # covers node-level guardrail outcomes) — these fire once per
    # AgenticLoop turn at the TURN_COMPLETED boundary so PR-CL-A1
    # (Dynamic Replan) can read them to decide whether to replan the
    # next round. Payload schema:
    #   {"passed": bool, "mode": str, "score": float,
    #    "rubric_misses": list[str], "reflection_hint": str,
    #    "reflexion_hint": str, "ts": float}
    TURN_VERIFY_PASSED = "turn_verify_passed"
    TURN_VERIFY_FAILED = "turn_verify_failed"

    # Autoresearch mutation lifecycle. Writers emit these after the
    # corresponding state transition succeeds. The canonical event sink
    # stores the bounded activity projection in ``hook_events``; the
    # self-improving mutation ledger remains the domain provenance source.
    #
    # Payload schema (every variant):
    #   {"mutation_id": str, "target_kind": str, "target_path": str,
    #    "ts": float, "run_id": str}
    # MUTATION_REJECTED / REVERTED also carry ``"reason": str``.
    # BASELINE_PROMOTED replaces ``mutation_id`` semantics with
    # ``"baseline_path": str`` + ``"prior_baseline_path": str`` + the
    # ``"reason": str`` quote from ``_should_promote``.
    MUTATION_PROPOSED = "mutation_proposed"
    MUTATION_APPLIED = "mutation_applied"
    MUTATION_REJECTED = "mutation_rejected"
    MUTATION_REVERTED = "mutation_reverted"
    BASELINE_PROMOTED = "baseline_promoted"

    # Self-improving runner system-prompt source (PR-FALLBACK-HOOK-CONTROL,
    # 2026-06-09; demoted to plain notify in PR-HOOK-TAXONOMY D4). Fired by
    # ``core.self_improving.loop.mutate.runner._build_system_prompt`` when
    # ``program.md`` is unreadable, then the runner fails loud —
    # program.md ships with the package, so a missing file is a packaging
    # bug, not a routine fallback. The former ``trigger_with_result``
    # override contract (a handler could return a replacement body) was
    # removed: no handler was ever registered anywhere, so the feedback
    # path was structurally dead. Payload: ``{"path": str}``.
    PROGRAM_MD_UNREADABLE = "program_md_unreadable"

    # Memory promotion proposal (PR-MEMORY-LIFECYCLE, 2026-07-03). Fired by
    # ``core.memory.memory_lifecycle.propose_memory_promotions`` when a
    # dedup cluster of dream artifacts + project-memory entries crosses the
    # >=3-distinct-sessions gate and a HITL proposal file is written to
    # ``.geode/memory/_proposals/<slug>.md``. Emit-only (APPROVAL_TRANSITION
    # pattern) — the canonical event sink persists it; promotion
    # into ``.geode/rules/`` stays a human decision, never a handler.
    # Payload: ``{"slug": str, "proposal_path": str, "session_ids": list[str],
    #             "source_count": int, "ts": float}``.
    MEMORY_PROMOTION_PROPOSED = "memory_promotion_proposed"


# Read-side alias map for stored event strings written before the
# NAME == VALUE.upper() alignment (PR-HOOK-TAXONOMY D5). Maps the OLD
# stored value to the CURRENT enum value. Applied wherever an event
# string is parsed back into a :class:`HookEvent` (``resolve_event_value``,
# filesystem hook discovery) and expanded by
# ``HookEventStore.read(event_filter=...)`` so canonical filters still
# match legacy SQLite rows. Deliberately NOT covered here: the collapsed
# D1/D2/D3 families — an old per-state name has no faithful single-event
# mapping for *parsing back into a member* (the discriminator moved into
# the payload). Their HISTORY visibility is handled separately by
# :data:`COLLAPSED_EVENT_VALUES` below, which the event store folds into
# filter expansion (read-only, never used to construct members).
LEGACY_EVENT_VALUES: dict[str, str] = {
    "session_start": "session_started",
    "session_end": "session_ended",
    "turn_complete": "turn_completed",
    "llm_call_start": "llm_call_started",
    "llm_call_end": "llm_call_ended",
    "llm_call_retry": "llm_call_retried",
    "tool_exec_start": "tool_exec_started",
    "tool_exec_end": "tool_exec_ended",
}


# Collapsed-family history map (PR-HOOK-TAXONOMY D2/D3): CURRENT enum
# value -> the pre-collapse stored event strings it absorbed. Used ONLY
# for query/filter expansion (a canonical filter also returns the old
# rows); never for member construction — the old rows keep their original
# event string and payload shape.
COLLAPSED_EVENT_VALUES: dict[str, tuple[str, ...]] = {
    "rule_changed": ("rule_created", "rule_updated", "rule_deleted"),
    "self_improving_auto_trigger": (
        "self_improving_auto_trigger_fired",
        "self_improving_auto_trigger_lock_busy",
        "self_improving_auto_trigger_interval_blocked",
        "self_improving_auto_trigger_runner_error",
        "self_improving_auto_trigger_parse_error",
        "self_improving_auto_trigger_max_generation_reached",
    ),
}


def resolve_event_value(value: str) -> HookEvent:
    """Resolve an event value string to a member, accepting legacy values.

    Raises ``ValueError`` (from the enum constructor) when the string is
    neither a current value nor a :data:`LEGACY_EVENT_VALUES` key.
    """
    return HookEvent(LEGACY_EVENT_VALUES.get(value, value))


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


class HookDispatchMode(StrEnum):
    """Semantic dispatch channel used for handlers and durable records."""

    OBSERVE = "observe"
    FEEDBACK = "feedback"
    INTERCEPTOR = "interceptor"


HookReturn = dict[str, Any] | None
# Type alias for hook handlers. Most handlers return None (fire-and-forget),
# but feedback-style hooks (e.g. CONTEXT_OVERFLOW_ACTION) return a dict
# that trigger_with_result() captures in HookResult.data. Async handlers are
# supported by the trigger_*_async APIs.
HookHandler = Callable[[HookEvent, dict[str, Any]], HookReturn | Awaitable[HookReturn]]


class DuplicateHookRegistrationError(ValueError):
    """Raised when a name collision would silently replace another hook."""


class HookTimeoutUnsupportedError(RuntimeError):
    """Raised when a hard timeout is requested for a synchronous handler."""


class HookExecutionTimeoutError(TimeoutError):
    """Raised when an awaitable hook exceeds its cooperative timeout."""


@dataclass(frozen=True)
class HookDispatch:
    """One completed dispatch, delivered once to each registered sink.

    ``data`` is the final event payload after interceptor modifications.
    Handler return payloads are deliberately kept in ``results`` and are not
    folded into ``data`` for observer/feedback modes.
    """

    event: HookEvent
    mode: HookDispatchMode
    data: dict[str, Any]
    started_at: float
    completed_at: float
    results: tuple[HookResult, ...] = ()
    blocked: bool = False
    block_reason: str = ""
    blocked_by: str = ""


HookSink = Callable[[HookDispatch], Any]
CleanupCallback = Callable[[], Any]


@dataclass
class _RegisteredHook:
    """Internal registration record."""

    handler: HookHandler
    name: str
    priority: int  # Lower = higher priority (runs first)
    matcher: str  # Regex pattern for tool_name filtering ("" = match all)
    compiled_matcher: re.Pattern[str] | None = None


@dataclass
class HookSubscription:
    """Cancelable registration handle returned by ``register*`` methods."""

    _owner: weakref.ReferenceType[HookSystem]
    kind: str
    key: HookEvent | str | None
    name: str
    identity: Any
    _cancelled: bool = False

    def cancel(self) -> bool:
        """Remove the registration once; return whether it was present."""
        if self._cancelled:
            return False
        self._cancelled = True
        owner = self._owner()
        if owner is None:
            return False
        return owner._cancel_subscription(self)


class HookSystem:
    """Register and trigger hooks on runtime events.

    Hooks execute in priority order (lower number = higher priority).

    Usage:
        hooks = HookSystem()

        def on_start(event, data):
            print(f"Session started: {data.get('session_id')}")

        hooks.register(HookEvent.SESSION_STARTED, on_start, priority=10)
        results = hooks.trigger(HookEvent.SESSION_STARTED, {"session_id": "demo"})
    """

    # Events that support matcher-based tool_name filtering.
    _TOOL_EVENTS: frozenset[HookEvent] = frozenset()  # populated after class

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[_RegisteredHook]] = {}
        # PR-COMM-2 (2026-05-24) — prefix-keyed wildcard subscriptions.
        # ``"*"`` is the all-events sentinel; other keys match by
        # ``HookEvent.name == prefix`` or ``name.startswith(prefix + "_")``
        # so e.g. ``"SUBAGENT"`` covers ``SUBAGENT_STARTED`` / ``SUBAGENT_COMPLETED``
        # / ``SUBAGENT_FAILED`` without matching ``SUBAGENT_RUNNERV2`` if such
        # a value is ever added.
        self._prefix_hooks: dict[str, list[_RegisteredHook]] = {}
        self._sinks: dict[str, HookSink] = {}
        self._cleanups: dict[str, CleanupCallback] = {}
        self._sink_failure_warned: set[tuple[str, str]] = set()
        self._closed = False
        self._lock = threading.Lock()

    def register(
        self,
        event: HookEvent,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
        matcher: str = "",
        replace: bool = False,
    ) -> HookSubscription:
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
        hook_name = name or self._default_callable_name(handler)
        try:
            compiled_matcher = re.compile(matcher) if matcher else None
        except re.error as exc:
            raise ValueError(
                f"Invalid matcher regex {matcher!r} for hook {hook_name!r}: {exc}"
            ) from exc
        entry = _RegisteredHook(
            handler=handler,
            name=hook_name,
            priority=priority,
            matcher=matcher,
            compiled_matcher=compiled_matcher,
        )

        with self._lock:
            self._assert_open_locked()
            existing = next((h for h in self._hooks.get(event, []) if h.name == hook_name), None)
            if existing is not None:
                if self._registration_is_identical(existing, entry):
                    return HookSubscription(weakref.ref(self), "event", event, hook_name, existing)
                if not replace:
                    raise DuplicateHookRegistrationError(
                        f"Hook {hook_name!r} is already registered for {event.value}; "
                        "pass replace=True for an intentional replacement"
                    )
            for prefix, prefix_hooks in self._prefix_hooks.items():
                if not self._matches_prefix(prefix, event):
                    continue
                overlap = next((h for h in prefix_hooks if h.name == hook_name), None)
                if overlap is not None and not self._registration_is_identical(overlap, entry):
                    raise DuplicateHookRegistrationError(
                        f"Hook name {hook_name!r} already overlaps {event.value} via "
                        f"prefix {prefix!r}; use a distinct name or unregister it first"
                    )
            hooks = [h for h in self._hooks.get(event, []) if h.name != hook_name]
            hooks.append(entry)
            # Keep sorted by priority (stable sort)
            hooks.sort(key=lambda h: h.priority)
            self._hooks[event] = hooks
        return HookSubscription(weakref.ref(self), "event", event, hook_name, entry)

    def register_prefix(
        self,
        prefix: str,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
        replace: bool = False,
    ) -> HookSubscription:
        """Register a handler for every :class:`HookEvent` whose name matches ``prefix``.

        Match rule (see :meth:`_matches_prefix`):

        * ``prefix == "*"`` → matches every event (replaces the bootstrap
          ``for event in HookEvent: hooks.register(event, ...)`` loop).
        * Otherwise → matches when ``HookEvent.name == prefix`` OR
          ``HookEvent.name.startswith(prefix + "_")``. The trailing-``_``
          guard prevents ``"NODE"`` from accidentally matching a future
          ``NODELESS_*`` event.

        Args:
            prefix: ``"*"`` or a HookEvent name fragment without the trailing ``_``.
            handler: Callback function. Same shape as :meth:`register`.
            name: Unique handler name (defaults to ``handler.__name__``).
            priority: Lower runs first (default 100). Priorities are
                merged across exact + wildcard subscribers at trigger time.
        """
        if not prefix or (prefix != "*" and prefix.endswith("_")):
            raise ValueError("Hook prefix must be '*' or a non-empty enum-name fragment")
        hook_name = name or self._default_callable_name(handler)
        entry = _RegisteredHook(handler=handler, name=hook_name, priority=priority, matcher="")

        with self._lock:
            self._assert_open_locked()
            existing = next(
                (h for h in self._prefix_hooks.get(prefix, []) if h.name == hook_name), None
            )
            if existing is not None:
                if self._registration_is_identical(existing, entry):
                    return HookSubscription(
                        weakref.ref(self), "prefix", prefix, hook_name, existing
                    )
                if not replace:
                    raise DuplicateHookRegistrationError(
                        f"Hook {hook_name!r} is already registered for prefix {prefix!r}; "
                        "pass replace=True for an intentional replacement"
                    )
            for event, exact_hooks in self._hooks.items():
                if not self._matches_prefix(prefix, event):
                    continue
                overlap = next((h for h in exact_hooks if h.name == hook_name), None)
                if overlap is not None and not self._registration_is_identical(overlap, entry):
                    raise DuplicateHookRegistrationError(
                        f"Hook name {hook_name!r} already overlaps prefix {prefix!r} via "
                        f"event {event.value}; use a distinct name or unregister it first"
                    )
            for other_prefix, prefix_hooks in self._prefix_hooks.items():
                if other_prefix == prefix or not any(
                    self._matches_prefix(prefix, event)
                    and self._matches_prefix(other_prefix, event)
                    for event in HookEvent
                ):
                    continue
                overlap = next((h for h in prefix_hooks if h.name == hook_name), None)
                if overlap is not None and not self._registration_is_identical(overlap, entry):
                    raise DuplicateHookRegistrationError(
                        f"Hook name {hook_name!r} overlaps prefixes {prefix!r} and "
                        f"{other_prefix!r}; use a distinct name or unregister it first"
                    )
            hooks = [h for h in self._prefix_hooks.get(prefix, []) if h.name != hook_name]
            hooks.append(entry)
            hooks.sort(key=lambda h: h.priority)
            self._prefix_hooks[prefix] = hooks
        return HookSubscription(weakref.ref(self), "prefix", prefix, hook_name, entry)

    def register_sink(
        self,
        sink: HookSink,
        *,
        name: str | None = None,
        replace: bool = False,
    ) -> HookSubscription:
        """Register one post-dispatch sink.

        Sinks are synchronous, receive exactly one :class:`HookDispatch` per
        trigger, and are closed by :meth:`close` when they expose ``close()``.
        """
        sink_name = name or self._default_callable_name(sink)
        replaced: HookSink | None = None
        with self._lock:
            self._assert_open_locked()
            existing = self._sinks.get(sink_name)
            if existing is not None and existing is not sink and not replace:
                raise DuplicateHookRegistrationError(
                    f"Hook sink {sink_name!r} is already registered; "
                    "pass replace=True for an intentional replacement"
                )
            if existing is not None and existing is not sink:
                replaced = existing
            self._sinks[sink_name] = sink
        if replaced is not None:
            self._close_sink(sink_name, replaced)
        return HookSubscription(weakref.ref(self), "sink", None, sink_name, sink)

    def add_cleanup(
        self,
        name: str,
        callback: CleanupCallback,
        *,
        replace: bool = False,
    ) -> HookSubscription:
        """Register an idempotent callback run during :meth:`close`."""
        with self._lock:
            self._assert_open_locked()
            existing = self._cleanups.get(name)
            if existing is not None and existing is not callback and not replace:
                raise DuplicateHookRegistrationError(
                    f"Hook cleanup {name!r} is already registered; "
                    "pass replace=True for an intentional replacement"
                )
            self._cleanups[name] = callback
        return HookSubscription(weakref.ref(self), "cleanup", None, name, callback)

    def add_owner_cleanup(
        self,
        name: str,
        callback: Callable[[HookSystem], Any],
        *,
        replace: bool = False,
    ) -> HookSubscription:
        """Register a cleanup that receives this system without retaining it.

        Module-level hook bridges commonly need compare-and-clear teardown:
        ``clear_binding(active_hooks)``. Storing a closure that directly
        captures ``self`` creates a reference cycle and can delay release of
        SQLite connections and other sink resources until cyclic GC runs.
        This helper keeps only a weak reference while preserving the same
        identity-safe cleanup contract.
        """
        owner_ref = weakref.ref(self)

        def _cleanup() -> None:
            owner = owner_ref()
            if owner is not None:
                callback(owner)

        return self.add_cleanup(name, _cleanup, replace=replace)

    def _cancel_subscription(self, subscription: HookSubscription) -> bool:
        """Cancel only the generation represented by ``subscription``."""
        sink_to_close: HookSink | None = None
        removed = False
        with self._lock:
            if subscription.kind == "event" and isinstance(subscription.key, HookEvent):
                hooks = self._hooks.get(subscription.key, [])
                remaining = [hook for hook in hooks if hook is not subscription.identity]
                removed = len(remaining) < len(hooks)
                if remaining:
                    self._hooks[subscription.key] = remaining
                else:
                    self._hooks.pop(subscription.key, None)
            elif subscription.kind == "prefix" and isinstance(subscription.key, str):
                hooks = self._prefix_hooks.get(subscription.key, [])
                remaining = [hook for hook in hooks if hook is not subscription.identity]
                removed = len(remaining) < len(hooks)
                if remaining:
                    self._prefix_hooks[subscription.key] = remaining
                else:
                    self._prefix_hooks.pop(subscription.key, None)
            elif subscription.kind == "sink":
                current_sink = self._sinks.get(subscription.name)
                if current_sink is subscription.identity:
                    sink_to_close = self._sinks.pop(subscription.name)
                    removed = True
            elif subscription.kind == "cleanup":
                current_cleanup = self._cleanups.get(subscription.name)
                if current_cleanup is subscription.identity:
                    self._cleanups.pop(subscription.name)
                    removed = True
        if sink_to_close is not None:
            self._close_sink(subscription.name, sink_to_close)
        return removed

    def unregister(self, event: HookEvent, name: str) -> bool:
        """Remove a named hook. Returns True if found and removed."""
        with self._lock:
            hooks = self._hooks.get(event, [])
            before = len(hooks)
            remaining = [h for h in hooks if h.name != name]
            if remaining:
                self._hooks[event] = remaining
            else:
                self._hooks.pop(event, None)
            return len(remaining) < before

    def unregister_prefix(self, prefix: str, name: str) -> bool:
        """Remove a named wildcard hook. Returns True if found and removed."""
        with self._lock:
            hooks = self._prefix_hooks.get(prefix, [])
            before = len(hooks)
            remaining = [h for h in hooks if h.name != name]
            if remaining:
                self._prefix_hooks[prefix] = remaining
            else:
                self._prefix_hooks.pop(prefix, None)
            return len(remaining) < before

    def unregister_sink(self, name: str) -> bool:
        with self._lock:
            sink = self._sinks.pop(name, None)
        if sink is None:
            return False
        self._close_sink(name, sink)
        return True

    def unregister_cleanup(self, name: str) -> bool:
        with self._lock:
            return self._cleanups.pop(name, None) is not None

    @staticmethod
    def _matches_prefix(prefix: str, event: HookEvent) -> bool:
        """Return True if ``event`` is subscribed by a handler under ``prefix``."""
        if prefix == "*":
            return True
        return event.name == prefix or event.name.startswith(prefix + "_")

    def _resolve_hooks_for(self, event: HookEvent) -> list[_RegisteredHook]:
        """Merge exact-match + matching wildcard subscribers, sorted by priority.

        Dedup rule: when the same ``name`` appears in both the exact list
        and a wildcard list (or in multiple wildcard lists), the
        first-encountered entry wins — exact-match entries take priority
        over wildcards, then prefixes are scanned in insertion order.
        Callers therefore see at most one ``_RegisteredHook`` per name
        per event, matching :meth:`register`'s per-event dedup semantics.

        Trigger paths call this from outside the lock; :meth:`list_hooks`
        calls the ``_locked`` variant while holding ``self._lock``.
        """
        with self._lock:
            return self._resolve_hooks_for_locked(event)

    def trigger(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[HookResult]:
        """Trigger all hooks for an event in priority order.

        Returns list of HookResults. Errors in one hook don't stop others.
        """
        dispatch = self._dispatch_sync(event, data, HookDispatchMode.OBSERVE)
        return list(dispatch.results)

    async def trigger_async(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Async variant of trigger().

        Awaitable handlers are awaited in priority order. Sync handlers run
        inline to preserve hook data mutation semantics.
        """
        dispatch = await self._dispatch_async(event, data, HookDispatchMode.OBSERVE)
        return list(dispatch.results)

    def trigger_with_result(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Trigger hooks and capture handler return values in HookResult.data.

        Like trigger(), but if a handler returns a dict it is stored in the
        corresponding HookResult.data field. This enables hooks that feed
        recommendations back to the caller (e.g. CONTEXT_OVERFLOW_ACTION).
        """
        dispatch = self._dispatch_sync(event, data, HookDispatchMode.FEEDBACK)
        return list(dispatch.results)

    async def trigger_with_result_async(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Async variant of trigger_with_result()."""
        dispatch = await self._dispatch_async(event, data, HookDispatchMode.FEEDBACK)
        return list(dispatch.results)

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
        dispatch = self._dispatch_sync(
            event,
            data,
            HookDispatchMode.INTERCEPTOR,
            timeout_s=timeout_s,
        )
        return InterceptResult(
            blocked=dispatch.blocked,
            reason=dispatch.block_reason,
            data=dict(dispatch.data),
        )

    async def trigger_interceptor_async(
        self, event: HookEvent, data: dict[str, Any] | None = None, *, timeout_s: float = 0
    ) -> InterceptResult:
        """Async variant of trigger_interceptor()."""
        dispatch = await self._dispatch_async(
            event,
            data,
            HookDispatchMode.INTERCEPTOR,
            timeout_s=timeout_s,
        )
        return InterceptResult(
            blocked=dispatch.blocked,
            reason=dispatch.block_reason,
            data=dict(dispatch.data),
        )

    # -- Internal helpers ------------------------------------------------------

    def _dispatch_sync(
        self,
        event: HookEvent,
        data: dict[str, Any] | None,
        mode: HookDispatchMode,
        *,
        timeout_s: float = 0,
    ) -> HookDispatch:
        started_at = time.time()
        working = dict(data) if data is not None else {}
        # Emit-side payload contract (PR-HOOK-TAXONOMY D7) — validated at
        # the dispatch choke point so DIRECT trigger() callers are covered
        # too, not only the core.hooks.dispatch wrappers.
        from core.hooks.dispatch import _validate_payload

        _validate_payload(event, working)
        if self.closed:
            return HookDispatch(
                event=event,
                mode=mode,
                data=working,
                started_at=started_at,
                completed_at=time.time(),
            )
        hooks = self._filter_by_matcher(self._resolve_hooks_for(event), event, working)
        results: list[HookResult] = []
        blocked = False
        block_reason = ""
        blocked_by = ""

        for hook in hooks:
            try:
                ret = self._call_handler(hook, event, dict(working), timeout_s=timeout_s)
                result_data = (
                    ret if mode is HookDispatchMode.FEEDBACK and isinstance(ret, dict) else {}
                )
                results.append(
                    HookResult(
                        success=True,
                        event=event,
                        handler_name=hook.name,
                        data=result_data,
                    )
                )
                if mode is HookDispatchMode.INTERCEPTOR and isinstance(ret, dict):
                    modifications = ret.get("modify")
                    if isinstance(modifications, dict):
                        working.update(modifications)
                    if ret.get("block"):
                        blocked = True
                        blocked_by = hook.name
                        block_reason = str(ret.get("reason") or f"Blocked by {hook.name}")
                        break
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

        dispatch = HookDispatch(
            event=event,
            mode=mode,
            data=dict(working),
            started_at=started_at,
            completed_at=time.time(),
            results=tuple(results),
            blocked=blocked,
            block_reason=block_reason,
            blocked_by=blocked_by,
        )
        self._notify_sinks(dispatch)
        return dispatch

    async def _dispatch_async(
        self,
        event: HookEvent,
        data: dict[str, Any] | None,
        mode: HookDispatchMode,
        *,
        timeout_s: float = 0,
    ) -> HookDispatch:
        started_at = time.time()
        working = dict(data) if data is not None else {}
        # Emit-side payload contract (PR-HOOK-TAXONOMY D7) — validated at
        # the dispatch choke point so DIRECT trigger() callers are covered
        # too, not only the core.hooks.dispatch wrappers.
        from core.hooks.dispatch import _validate_payload

        _validate_payload(event, working)
        if self.closed:
            return HookDispatch(
                event=event,
                mode=mode,
                data=working,
                started_at=started_at,
                completed_at=time.time(),
            )
        hooks = self._filter_by_matcher(self._resolve_hooks_for(event), event, working)
        results: list[HookResult] = []
        blocked = False
        block_reason = ""
        blocked_by = ""

        for hook in hooks:
            try:
                ret = await self._call_handler_async(
                    hook,
                    event,
                    dict(working),
                    timeout_s=timeout_s,
                )
                result_data = (
                    ret if mode is HookDispatchMode.FEEDBACK and isinstance(ret, dict) else {}
                )
                results.append(
                    HookResult(
                        success=True,
                        event=event,
                        handler_name=hook.name,
                        data=result_data,
                    )
                )
                if mode is HookDispatchMode.INTERCEPTOR and isinstance(ret, dict):
                    modifications = ret.get("modify")
                    if isinstance(modifications, dict):
                        working.update(modifications)
                    if ret.get("block"):
                        blocked = True
                        blocked_by = hook.name
                        block_reason = str(ret.get("reason") or f"Blocked by {hook.name}")
                        break
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

        dispatch = HookDispatch(
            event=event,
            mode=mode,
            data=dict(working),
            started_at=started_at,
            completed_at=time.time(),
            results=tuple(results),
            blocked=blocked,
            block_reason=block_reason,
            blocked_by=blocked_by,
        )
        self._notify_sinks(dispatch)
        return dispatch

    def _notify_sinks(self, dispatch: HookDispatch) -> None:
        with self._lock:
            sinks = list(self._sinks.items())
        for sink_name, sink in sinks:
            try:
                ret = sink(dispatch)
                if inspect.isawaitable(ret):
                    if inspect.iscoroutine(ret):
                        ret.close()
                    raise TypeError(f"Hook sink {sink_name!r} must be synchronous")
            except Exception as exc:
                warning_key = (sink_name, dispatch.event.value)
                if warning_key not in self._sink_failure_warned:
                    self._sink_failure_warned.add(warning_key)
                    log.warning(
                        "Hook sink '%s' failed on %s (suppressing repeats): %s",
                        sink_name,
                        dispatch.event.value,
                        exc,
                    )
                else:
                    log.debug(
                        "Hook sink '%s' failed on %s: %s",
                        sink_name,
                        dispatch.event.value,
                        exc,
                    )

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
        tool_name = str(data.get("tool_name", "") or "")
        if not tool_name:
            return [hook for hook in hooks if hook.compiled_matcher is None]
        result: list[_RegisteredHook] = []
        for hook in hooks:
            if hook.compiled_matcher is None:
                result.append(hook)
                continue
            if hook.compiled_matcher.search(tool_name):
                result.append(hook)
        return result

    @staticmethod
    def _call_handler(
        hook: _RegisteredHook,
        event: HookEvent,
        data: dict[str, Any],
        *,
        timeout_s: float = 0,
    ) -> dict[str, Any] | None:
        """Call a synchronous hook without creating abandoned worker threads."""
        if timeout_s > 0:
            raise HookTimeoutUnsupportedError(
                f"Sync hook {hook.name!r} cannot guarantee a {timeout_s:.3f}s timeout; "
                "use an async handler with trigger_*_async"
            )
        return HookSystem._resolve_sync_return(hook.handler(event, data), hook, event)

    @staticmethod
    async def _call_handler_async(
        hook: _RegisteredHook,
        event: HookEvent,
        data: dict[str, Any],
        *,
        timeout_s: float = 0,
    ) -> dict[str, Any] | None:
        """Call a hook handler from async code with optional timeout."""

        async def invoke() -> dict[str, Any] | None:
            ret = hook.handler(event, data)
            if inspect.isawaitable(ret):
                return await ret
            return ret

        if timeout_s <= 0:
            return await invoke()

        if not HookSystem._is_async_callable(hook.handler):
            raise HookTimeoutUnsupportedError(
                f"Sync hook {hook.name!r} cannot guarantee a {timeout_s:.3f}s timeout; "
                "declare it async or omit timeout_s"
            )

        try:
            return await asyncio.wait_for(invoke(), timeout_s)
        except TimeoutError:
            raise HookExecutionTimeoutError(
                f"Hook {hook.name!r} timed out on {event.value} after {timeout_s:.3f}s"
            ) from None

    @staticmethod
    def _resolve_sync_return(
        ret: HookReturn | Awaitable[HookReturn],
        hook: _RegisteredHook,
        event: HookEvent,
    ) -> dict[str, Any] | None:
        """Resolve sync API return values without running async handlers."""
        if not inspect.isawaitable(ret):
            return ret

        if inspect.iscoroutine(ret):
            ret.close()
        raise RuntimeError(
            f"Async hook '{hook.name}' returned an awaitable on {event.value}; "
            "use trigger_async/trigger_with_result_async/trigger_interceptor_async"
        )

    @staticmethod
    def _is_async_callable(handler: HookHandler) -> bool:
        return inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
            type(handler).__call__
        )

    @staticmethod
    def _default_callable_name(callback: Callable[..., Any]) -> str:
        return str(getattr(callback, "__name__", callback.__class__.__name__))

    @staticmethod
    def _same_handler(left: HookHandler, right: HookHandler) -> bool:
        if left is right:
            return True
        return getattr(left, "__self__", None) is getattr(right, "__self__", None) and getattr(
            left, "__func__", left
        ) is getattr(right, "__func__", right)

    @classmethod
    def _registration_is_identical(cls, left: _RegisteredHook, right: _RegisteredHook) -> bool:
        return (
            cls._same_handler(left.handler, right.handler)
            and left.priority == right.priority
            and left.matcher == right.matcher
        )

    def _assert_open_locked(self) -> None:
        if self._closed:
            raise RuntimeError("HookSystem is closed")

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def list_hooks(self, event: HookEvent | None = None) -> dict[str, list[str]]:
        """List registered hook names, optionally filtered by event.

        PR-COMM-2 (2026-05-24) — output includes matching wildcard
        subscribers (via :meth:`_resolve_hooks_for`) so introspection
        accurately reports every handler that would fire on a trigger.
        Wildcard-only registrations land under the ``"*<prefix>"`` keys
        when ``event`` is not specified, so callers can still
        distinguish exact from wildcard sources.
        """
        with self._lock:
            if event is not None:
                hooks = self._resolve_hooks_for_locked(event)
                return {event.value: [h.name for h in hooks]}
            exact = {e.value: [h.name for h in hooks] for e, hooks in self._hooks.items() if hooks}
            wildcard = {
                f"*{prefix}": [h.name for h in hooks]
                for prefix, hooks in self._prefix_hooks.items()
                if hooks
            }
            return {**exact, **wildcard}

    def list_sinks(self) -> list[str]:
        """Return registered post-dispatch sink names in invocation order."""
        with self._lock:
            return list(self._sinks)

    def _resolve_hooks_for_locked(self, event: HookEvent) -> list[_RegisteredHook]:
        """Lock-free variant of :meth:`_resolve_hooks_for` for callers that
        already hold ``self._lock``."""
        exact = list(self._hooks.get(event, []))
        wildcard: list[_RegisteredHook] = []
        for prefix, hooks in self._prefix_hooks.items():
            if self._matches_prefix(prefix, event):
                wildcard.extend(hooks)
        if not wildcard:
            return exact
        merged = exact + wildcard
        seen: set[str] = set()
        unique: list[_RegisteredHook] = []
        for hook in merged:
            if hook.name in seen:
                continue
            seen.add(hook.name)
            unique.append(hook)
        unique.sort(key=lambda h: h.priority)
        return unique

    def clear(self, event: HookEvent | None = None) -> None:
        """Clear hooks for a specific event, or all hooks.

        PR-COMM-2 (2026-05-24) — when ``event`` is None, wildcard
        subscriptions are cleared alongside exact registrations so
        ``HookSystem.clear()`` actually drops every handler. The
        ``event``-specific variant keeps wildcards intact (they aren't
        bound to a single event by definition).
        """
        with self._lock:
            if event is not None:
                self._hooks.pop(event, None)
            else:
                self._hooks.clear()
                self._prefix_hooks.clear()

    def close(self) -> None:
        """Deterministically release handlers, callbacks, and sink resources."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            cleanups = list(reversed(self._cleanups.items()))
            sinks = list(reversed(self._sinks.items()))
            self._hooks.clear()
            self._prefix_hooks.clear()
            self._cleanups.clear()
            self._sinks.clear()

        for cleanup_name, callback in cleanups:
            try:
                callback()
            except Exception:
                log.warning("Hook cleanup '%s' failed", cleanup_name, exc_info=True)
        for sink_name, sink in sinks:
            self._close_sink(sink_name, sink)

    @staticmethod
    def _close_sink(name: str, sink: HookSink) -> None:
        close = getattr(sink, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception:
            log.warning("Hook sink '%s' close failed", name, exc_info=True)


# Populate _TOOL_EVENTS after HookEvent members are available.
HookSystem._TOOL_EVENTS = frozenset(
    {
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_EXEC_ENDED,
        HookEvent.TOOL_EXEC_FAILED,
        HookEvent.TOOL_RESULT_TRANSFORM,
    }
)
