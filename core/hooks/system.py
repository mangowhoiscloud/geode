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
import concurrent.futures
import dataclasses
import inspect
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


def _mirror_hook_to_active_transcript(event: HookEvent, data: dict[str, Any]) -> None:
    """Mirror a HookSystem trigger into the active RunTranscript as a
    paperclip-style activity_log row.

    PR-COMM-1 (2026-05-24, spec doc §4). Pre-PR-COMM-1 the pipeline
    transcript only carried 4 SessionTranscript mirrors (record_user_message
    / record_assistant_message / record_tool_call / record_tool_result)
    from PR-U + orchestrator phase events from cli.py. The remaining 70
    HookEvent triggers were invisible in the unified timeline. Routing
    every trigger through this helper closes that gap.

    No-op when no orchestrator is bound (REPL / gateway / tests). Any
    builder / registry / append failure is swallow-and-warn so a failed
    mirror never breaks the upstream caller — same contract paperclip's
    ``logActivity`` uses (``activity-log.ts:65``).
    """
    try:
        from core.observability.activity_registry import map_hook_to_activity
        from core.self_improving.loop.run_transcript import current_run_transcript

        run_transcript = current_run_transcript()
        if run_transcript is None:
            return
        row = map_hook_to_activity(event, data, run_id=run_transcript.session_id)
        # Coerce details to a plain dict for the JSONL row. ``details``
        # lives on every concrete ``ActivityRowBase`` subclass (typed
        # rows carry pydantic ``BaseModel`` sub-schemas; generic rows
        # carry a free-form ``dict``); we access via ``getattr`` so
        # mypy doesn't trip over the base class's missing field.
        row_details = getattr(row, "details", None)
        details_payload: dict[str, Any]
        if row_details is None:
            details_payload = {}
        elif hasattr(row_details, "model_dump"):
            details_payload = row_details.model_dump()
        elif isinstance(row_details, dict):
            details_payload = row_details
        else:
            details_payload = {"_repr": repr(row_details)}
        run_transcript.append(
            event=event.value,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            task_id=row.task_id,
            level=row.level,
            payload=details_payload,
        )
    except Exception as exc:
        log.debug("HookEvent → ActivityRow mirror failed for %s: %s", event.value, exc)


class HookEvent(Enum):
    """Pipeline lifecycle events."""

    # Pipeline level (lifecycle fires on success + error; ERROR is a distinct
    # variant rather than a sub-state of ENDED, matching SUBAGENT_FAILED)
    PIPELINE_STARTED = "pipeline_start"
    PIPELINE_ENDED = "pipeline_end"
    PIPELINE_ERROR = "pipeline_error"

    # Node level
    NODE_BOOTSTRAP = "node_bootstrap"
    NODE_ENTERED = "node_enter"
    NODE_EXITED = "node_exit"
    NODE_ERROR = "node_error"

    # Analysis level (milestone — fires only on successful stage completion)
    ANALYST_COMPLETED = "analyst_complete"
    EVALUATOR_COMPLETED = "evaluator_complete"
    SCORING_COMPLETED = "scoring_complete"

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

    # Agentic turn lifecycle (OpenClaw command:new pattern; milestone-style —
    # fires once per turn on completion)
    TURN_COMPLETED = "turn_complete"

    # Context overflow detection (Karpathy P6 Context Budget)
    CONTEXT_CRITICAL = "context_critical"
    CONTEXT_OVERFLOW_ACTION = "context_overflow_action"

    # Session lifecycle (OpenClaw agent:bootstrap pattern; lifecycle pair)
    SESSION_STARTED = "session_start"
    SESSION_ENDED = "session_end"

    # Model switching (L1 Observe)
    MODEL_SWITCHED = "model_switched"

    # LLM call lifecycle (model-level latency/cost observability; START/ENDED
    # are the lifecycle pair, ENDED fires on success+error with ``error`` key,
    # FAILED is a legacy alias retained for plugin compatibility, RETRIED is
    # the action-past form for retry attempts)
    LLM_CALL_STARTED = "llm_call_start"
    LLM_CALL_ENDED = "llm_call_end"
    LLM_CALL_FAILED = "llm_call_failed"
    LLM_CALL_RETRIED = "llm_call_retry"

    # Tool approval HITL lifecycle
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    TOOL_APPROVAL_GRANTED = "tool_approval_granted"
    TOOL_APPROVAL_DENIED = "tool_approval_denied"

    # Cross-provider fallback (LLM resilience)
    # PR-NO-FALLBACK (2026-05-28) — cross-provider fallback removed;
    # the enum value is retained for back-compat (plugins may still
    # subscribe) but no production emit-site fires it any more.
    FALLBACK_CROSS_PROVIDER = "fallback_cross_provider"

    # Per-adapter dispatch attempt — fired by
    # ``core.llm.adapters.dispatch._fire_attempt`` for every single-adapter
    # try. Payload: adapter_name, provider, source, capability, outcome
    # (success/billing/transient/unavailable), elapsed_ms, error_type,
    # error_msg. Lets operators trace exactly which adapter handled a
    # web_search / complete_text call without having to parse serve logs.
    ADAPTER_DISPATCH_ATTEMPT = "adapter_dispatch_attempt"

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

    # Production hooks (P0) — interceptor + cost enforcement + audit.
    # TOOL_EXEC_STARTED / TOOL_EXEC_ENDED form the lifecycle pair; FAILED is the
    # error variant. TOOL_RESULT_TRANSFORM is a separate feedback hook (post
    # observation, result rewriting).
    USER_INPUT_RECEIVED = "user_input_received"
    TOOL_EXEC_STARTED = "tool_exec_start"
    TOOL_EXEC_ENDED = "tool_exec_end"
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

    # Self-improving loop auto-trigger telemetry (OL-A1.5 — 2026-05-22).
    # One event per terminal state of ``auto_trigger_mutator`` so a
    # downstream subscriber (audit log writer, Inspect viewer, FE) can
    # count firings, distinguish lock contention from interval gating,
    # and surface runner failures without parsing the daemon log.
    # Payload schema (every variant):
    #   {"trigger_id": str, "ts": float, "detail": str}
    # The ``trigger_id`` is the canonical id from
    # ``AUTO_TRIGGER_TRIGGER_ID`` so subscribers can filter by id when
    # multiple trigger families coexist in the same scheduler.
    SELF_IMPROVING_AUTO_TRIGGER_FIRED = "self_improving_auto_trigger_fired"
    SELF_IMPROVING_AUTO_TRIGGER_LOCK_BUSY = "self_improving_auto_trigger_lock_busy"
    SELF_IMPROVING_AUTO_TRIGGER_INTERVAL_BLOCKED = "self_improving_auto_trigger_interval_blocked"
    SELF_IMPROVING_AUTO_TRIGGER_RUNNER_ERROR = "self_improving_auto_trigger_runner_error"
    SELF_IMPROVING_AUTO_TRIGGER_PARSE_ERROR = "self_improving_auto_trigger_parse_error"
    # PR-MAX-GEN (2026-05-26) — emitted when the auto-trigger hits the
    # ``max_generation`` cap in ``~/.geode/autoresearch/handoff/auto_trigger_history.jsonl``.
    # Same ``{trigger_id, ts, detail}`` payload schema; ``detail`` carries
    # ``"current/max"`` (e.g. ``"100/100"``).
    SELF_IMPROVING_AUTO_TRIGGER_MAX_GENERATION_REACHED = (
        "self_improving_auto_trigger_max_generation_reached"
    )

    # Wall-clock budget hand-off (PR-CL-BUDGET, 2026-05-23). Replaces the
    # prior turn hard-cap with a 2h time-cap + automatic T-10min hand-off.
    # Payload schema (all variants):
    #   {"session_id": str, "platform": str, "remaining_s": float,
    #    "budget_total_s": float, "ts": float}
    # ``HANDOFF_TRIGGERED`` fires once per session — at the threshold
    # crossing — even if the round loop re-enters the budget check.
    # ``HANDOFF_COMPLETED`` fires when the graceful exit has persisted
    # transcript + DB state; ``HANDOFF_FAILED`` fires on watcher error.
    HANDOFF_TRIGGERED = "handoff_triggered"
    HANDOFF_COMPLETED = "handoff_completed"
    HANDOFF_FAILED = "handoff_failed"

    # Per-turn verify telemetry (PR-CL-A3, 2026-05-23). Distinct from the
    # pipeline-level ``VERIFICATION_PASS / VERIFICATION_FAIL`` pair (which
    # covers node-level guardrail outcomes) — these fire once per
    # AgenticLoop turn at the TURN_COMPLETED boundary so PR-CL-A1
    # (Dynamic Replan) can read them to decide whether to replan the
    # next round. Payload schema:
    #   {"passed": bool, "mode": str, "score": float,
    #    "rubric_misses": list[str], "reflexion_hint": str, "ts": float}
    TURN_VERIFY_PASSED = "turn_verify_passed"
    TURN_VERIFY_FAILED = "turn_verify_failed"

    # Autoresearch mutation lifecycle (PR-HOOKEVENT-RESERVE, 2026-05-26).
    # Reserved as the shared event namespace between two concurrent
    # sprints: (a) autoresearch attribution sprint Phase G
    # (PR-SOT-REVERT-ON-REJECT, PR-SOT-REVERT-ON-AUDIT-FAIL) — the
    # writers will emit these once the SoT-revert paths land in
    # ``core/self_improving/train.py:2407-2455`` + ``runner.py:1882-1888``;
    # (b) observability central SoT sprint PR-5 wildcard firehose +
    # PR-10 autoresearch indexer — the wildcard listener captures
    # every event into ``events`` SQLite, the autoresearch_indexer
    # cross-references against ``state/autoresearch/mutations.jsonl``
    # by ``mutation_id``. Reserving the names + values up-front avoids
    # value drift once both sprints start emitting concurrently.
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


HookReturn = dict[str, Any] | None
# Type alias for hook handlers. Most handlers return None (fire-and-forget),
# but feedback-style hooks (e.g. CONTEXT_OVERFLOW_ACTION) return a dict
# that trigger_with_result() captures in HookResult.data. Async handlers are
# supported by the trigger_*_async APIs.
HookHandler = Callable[[HookEvent, dict[str, Any]], HookReturn | Awaitable[HookReturn]]


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
            print(f"Pipeline started for {data.get('subject_id')}")

        hooks.register(HookEvent.PIPELINE_STARTED, on_start, priority=10)
        results = hooks.trigger(HookEvent.PIPELINE_STARTED, {"subject_id": "demo"})
    """

    # Events that support matcher-based tool_name filtering.
    _TOOL_EVENTS: frozenset[HookEvent] = frozenset()  # populated after class

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[_RegisteredHook]] = {}
        # PR-COMM-2 (2026-05-24) — prefix-keyed wildcard subscriptions.
        # ``"*"`` is the all-events sentinel; other keys match by
        # ``HookEvent.name == prefix`` or ``name.startswith(prefix + "_")``
        # so e.g. ``"PIPELINE"`` covers ``PIPELINE_STARTED`` / ``PIPELINE_ENDED``
        # / ``PIPELINE_ERROR`` / ``PIPELINE_TIMEOUT`` without matching
        # ``PIPELINE_RUNNERV2`` if such a value is ever added.
        self._prefix_hooks: dict[str, list[_RegisteredHook]] = {}
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

    def register_prefix(
        self,
        prefix: str,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
    ) -> None:
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
        hook_name = name or handler.__name__
        entry = _RegisteredHook(handler=handler, name=hook_name, priority=priority, matcher="")

        with self._lock:
            if prefix not in self._prefix_hooks:
                self._prefix_hooks[prefix] = []
            # Dedup against the SAME prefix (mirrors :meth:`register`'s
            # per-event dedup). Cross-prefix duplicate names are
            # resolved at trigger time by :meth:`_resolve_hooks_for`.
            self._prefix_hooks[prefix] = [
                h for h in self._prefix_hooks[prefix] if h.name != hook_name
            ]
            self._prefix_hooks[prefix].append(entry)
            self._prefix_hooks[prefix].sort(key=lambda h: h.priority)

    def unregister(self, event: HookEvent, name: str) -> bool:
        """Remove a named hook. Returns True if found and removed."""
        with self._lock:
            hooks = self._hooks.get(event, [])
            before = len(hooks)
            self._hooks[event] = [h for h in hooks if h.name != name]
            return len(self._hooks[event]) < before

    def unregister_prefix(self, prefix: str, name: str) -> bool:
        """Remove a named wildcard hook. Returns True if found and removed."""
        with self._lock:
            hooks = self._prefix_hooks.get(prefix, [])
            before = len(hooks)
            self._prefix_hooks[prefix] = [h for h in hooks if h.name != name]
            return len(self._prefix_hooks[prefix]) < before

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
        data = data or {}
        results: list[HookResult] = []
        hooks = self._resolve_hooks_for(event)
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                self._call_handler(hook, event, data)
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

        # PR-COMM-1 (2026-05-24, spec doc §4 union channel wiring) —
        # mirror this trigger into the active RunTranscript as a typed
        # ActivityRow so the pipeline transcript carries every hook
        # event, not just the 4 SessionTranscript record_* mirrors PR-U
        # landed. No-op when no orchestrator is bound (REPL / gateway /
        # tests). Failures are silent + warning-logged so the union
        # channel never breaks an upstream hook handler.
        _mirror_hook_to_active_transcript(event, data)

        return results

    async def trigger_async(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Async variant of trigger().

        Awaitable handlers are awaited in priority order. Sync handlers run
        inline to preserve hook data mutation semantics.
        """
        data = data or {}
        results: list[HookResult] = []
        hooks = self._resolve_hooks_for(event)
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                await self._call_handler_async(hook, event, data)
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

        # PR-COMM-1 (2026-05-24) — async-path parity with the sync
        # mirror call in :meth:`trigger` so both dispatch paths produce
        # the same unified timeline.
        _mirror_hook_to_active_transcript(event, data)

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
        hooks = self._resolve_hooks_for(event)
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                ret = self._call_handler(hook, event, data)
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

    async def trigger_with_result_async(
        self, event: HookEvent, data: dict[str, Any] | None = None
    ) -> list[HookResult]:
        """Async variant of trigger_with_result()."""
        data = data or {}
        results: list[HookResult] = []
        hooks = self._resolve_hooks_for(event)
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                ret = await self._call_handler_async(hook, event, data)
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
        hooks = self._resolve_hooks_for(event)
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

    async def trigger_interceptor_async(
        self, event: HookEvent, data: dict[str, Any] | None = None, *, timeout_s: float = 0
    ) -> InterceptResult:
        """Async variant of trigger_interceptor()."""
        data = dict(data) if data else {}
        hooks = self._resolve_hooks_for(event)
        hooks = self._filter_by_matcher(hooks, event, data)

        for hook in hooks:
            try:
                ret = await self._call_handler_async(hook, event, data, timeout_s=timeout_s)
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
            return HookSystem._resolve_sync_return(hook.handler(event, data), hook, event)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(hook.handler, event, data)
            try:
                ret = future.result(timeout=timeout_s)
                return HookSystem._resolve_sync_return(ret, hook, event)
            except concurrent.futures.TimeoutError:
                log.warning(
                    "Hook '%s' timed out on %s (%.1fs limit)",
                    hook.name,
                    event.value,
                    timeout_s,
                )
                return None

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

        try:
            return await asyncio.wait_for(invoke(), timeout_s)
        except TimeoutError:
            log.warning(
                "Hook '%s' timed out on %s (%.1fs limit)",
                hook.name,
                event.value,
                timeout_s,
            )
            return None

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
    async def _await_awaitable(ret: Awaitable[HookReturn]) -> dict[str, Any] | None:
        """Coroutine wrapper for sync APIs that need to run an awaitable handler."""
        return await ret

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


# Populate _TOOL_EVENTS after HookEvent members are available.
HookSystem._TOOL_EVENTS = frozenset(
    {
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_EXEC_ENDED,
        HookEvent.TOOL_EXEC_FAILED,
        HookEvent.TOOL_RESULT_TRANSFORM,
    }
)
