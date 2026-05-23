"""Per-session aggregate metrics — session-level state object pattern.

Centralises 13-way scattered session-scoped state (LLM cost / tool calls /
provider routing / failover counts / mutation lifecycle) into a single
``SessionMetrics`` ContextVar-bound dataclass.

Designed against four frontier references:

1. **Claude Code** (``claude-code-ref/src/core/agent-loop.ts``) — its
   ``AgentLoopState.totalUsage`` is per-loop instance state. We follow
   the same grain but via ContextVar to support GEODE's multi-session
   gateway pattern (cron / serve / sub-agent fan-out).

2. **Hermes Agent** (``hermes-agent/gateway/session_context.py``) — its
   ``_SESSION_ID: ContextVar`` family isolates session-scoped data
   across concurrent gateway sessions. ``SessionMetrics`` mirrors that
   pattern, sitting alongside ``SessionJournal``'s existing
   ``_current_journal`` ContextVar (``core/observability/session_journal.py``).

3. **Hermes ``sessions`` SQLite table** (``hermes_state.py:190``) — the
   ``input_tokens / output_tokens / cache_*_tokens / reasoning_tokens
   / api_call_count / billing_provider / estimated_cost_usd`` column
   set is the persistence shape. ``SessionMetrics.to_session_row()``
   emits the same shape so a future ``~/.geode/self-improving-loop/
   sessions.jsonl`` row can carry these aggregates without separate
   wiring.

4. **Paperclip** (``paperclip/server/src/services/activity.ts``) —
   the ``usageJson`` JSONB column already accepts both ``inputTokens``
   /``input_tokens`` casing variants. Our row schema picks snake_case
   to align with the hermes SQLite path and Anthropic API conventions.

Coverage scope (Tier 1 — interim, not the only place these still live)
----------------------------------------------------------------------

Many GEODE subsystems already manage their own session-scoped state:

- ``TokenTracker`` (``core/llm/token_tracker.py``) — per-call cost
  accumulate. ``SessionMetrics`` is the *aggregator*; TokenTracker
  remains for per-provider cost-table lookups and we delegate via a
  thin shim instead of duplicating cost math.
- ``SessionJournal`` (``core/observability/session_journal.py``) —
  event stream. ``SessionMetrics`` is the *roll-up* counterpart;
  journal events still carry the event-scoped context.
- ``UsageStore`` (``core/llm/usage_store.py``) — *daily* rolling
  ``~/.geode/usage/*.jsonl``. Not absorbed because the grain is
  per-calendar-day, not per-session.
- ``OAuthUsage`` (``core/llm/oauth_usage.py``) — 5-hour OAuth quota
  cache. Provider-wide, not session-scoped.
- ``LaneQueue`` (``core/llm/audit_lane.py``) — process-wide throttle.
- ``ContextLocal`` (``core/ui/context_local.py``) — UI ephemerals
  (SessionMeter backing). Read-only consumer of metrics in future.

Lifecycle
---------

::

    with session_metrics_scope(session_id="2026-05-23T...", gen_tag="autoresearch-abc1234"):
        # ... runs that emit accumulate_llm_call / increment_tool_call ...
        metrics = current_session_metrics()
        # produce final row
        row = metrics.to_session_row()
        # caller appends to sessions.jsonl

I/O failures NEVER raise — observability mustn't break the run it observes.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "SessionMetrics",
    "current_session_metrics",
    "session_metrics_scope",
    "set_current_session_metrics",
]


_current_metrics: contextvars.ContextVar[SessionMetrics | None] = contextvars.ContextVar(
    "session_metrics", default=None
)


@dataclass(slots=True)
class SessionMetrics:
    """Aggregate state for a single self-improving-loop / agentic session.

    Field grouping mirrors the ``hermes_state.sessions`` table schema +
    Claude Code's ``AgentLoopState.totalUsage`` + Paperclip's ``usageJson``.
    All counters are *additive* — use the ``accumulate_*`` / ``increment_*``
    / ``record_*`` methods rather than mutating fields directly so future
    field additions don't break callers.
    """

    # Identity
    session_id: str = ""
    gen_tag: str = ""
    component: str = ""
    started_at: float = 0.0

    # A. LLM call cost — per-call accumulate (claude-code AgentLoopState.totalUsage shape).
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    thinking_tokens: int = 0
    estimated_cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    model_used: str = ""  # last model after failover

    # B. Counts — turn / tool / message / mutation / audit
    api_call_count: int = 0
    tool_call_count: int = 0
    message_count: int = 0
    mutation_count: int = 0
    audit_call_count: int = 0

    # C. Billing surface (hermes sessions table parity)
    billing_provider: str = ""  # anthropic / openai / glm / openai-codex
    billing_mode: str = ""  # payg / subscription / adapter

    # D. Resilience metrics
    retry_count: int = 0
    circuit_breaker_trips: dict[str, int] = field(default_factory=dict)
    error_count_by_type: dict[str, int] = field(default_factory=dict)
    rollback_count: int = 0

    # E. Self-improving lifecycle (mutator session only — None otherwise)
    fitness_before: float | None = None
    fitness_after: float | None = None
    cohort_tag: str = ""

    # F. Last-LLM-call snapshot (replaces broken ``_LAST_LLM_CALL_USAGE`` sidecar
    #    from PR-SIL-5THEME C4 / PR-C4.fix-contextvar #1529). propose() reads
    #    this single field instead of a module dict — same caller frame, no
    #    sidecar, no race.
    last_call_input_tokens: int = 0
    last_call_output_tokens: int = 0
    last_call_elapsed_seconds: float = 0.0
    last_call_model: str = ""

    # H. Goodhart-surface aggregates (audit subprocess scope)
    missing_dims_total: int = 0
    missing_benches_total: int = 0
    cross_validation_conflict_count: int = 0

    # I. Wall-clock budget + handoff (PR-CL-BUDGET, 2026-05-23) — 2-hour
    #    time cap with T-10min auto-handoff trigger replacing the prior
    #    turn-count cap. ``time_budget_start_s`` is monotonic clock; 0.0
    #    means budget tracking inactive. ``handoff_threshold_s`` carves
    #    out the warning headroom (default 600s = 10 min). Once
    #    ``handoff_triggered_at`` is set, ``is_handoff_due`` returns False
    #    (one-shot trigger so AgenticLoop doesn't fire HANDOFF_TRIGGERED
    #    every subsequent round).
    time_budget_start_s: float = 0.0
    time_budget_total_s: float = 0.0  # 0.0 = no budget
    handoff_threshold_s: float = 600.0  # T-10min
    handoff_triggered_at: float = 0.0  # 0.0 = not yet fired
    # Codex MCP 2026-05-23 MEDIUM #2 — without this lock, two threads in the
    # same ContextVar scope (e.g. asyncio.to_thread fan-out) can both observe
    # ``handoff_triggered_at == 0.0`` and double-fire HANDOFF_TRIGGERED.
    # Async-only fan-out is safe (no ``await`` in ``is_handoff_due``); the
    # lock is the cheap defensive layer for the threaded edge case.
    _handoff_latch_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def accumulate_llm_call(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        thinking_tokens: int = 0,
        elapsed_seconds: float = 0.0,
        model: str = "",
        cost_usd: float = 0.0,
    ) -> None:
        """One LLM call completed — fold its usage into the session aggregate.

        Also captures the *last call* snapshot in F-fields so propose() / a
        mutation row writer can read just the latest call without diffing
        across the cumulative totals. Matches the C4 sidecar's contract
        without the module-level state.
        """
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        self.cache_creation_tokens += int(cache_creation_tokens)
        self.cache_read_tokens += int(cache_read_tokens)
        self.thinking_tokens += int(thinking_tokens)
        self.elapsed_seconds += float(elapsed_seconds)
        self.estimated_cost_usd += float(cost_usd)
        if model:
            self.model_used = str(model)
        self.api_call_count += 1
        # Last-call snapshot — caller (propose()) reads this for per-mutation cost.
        self.last_call_input_tokens = int(input_tokens)
        self.last_call_output_tokens = int(output_tokens)
        self.last_call_elapsed_seconds = float(elapsed_seconds)
        self.last_call_model = str(model)

    def reset_last_call(self) -> None:
        """Clear the last-call snapshot (called before a new propose() so a
        mock LLM that doesn't accumulate doesn't leak stale per-call values).
        Cumulative totals untouched."""
        self.last_call_input_tokens = 0
        self.last_call_output_tokens = 0
        self.last_call_elapsed_seconds = 0.0
        self.last_call_model = ""

    def increment_tool_call(self, count: int = 1) -> None:
        self.tool_call_count += int(count)

    def increment_message(self, count: int = 1) -> None:
        self.message_count += int(count)

    def increment_mutation(self, count: int = 1) -> None:
        self.mutation_count += int(count)

    def increment_audit_call(self, count: int = 1) -> None:
        self.audit_call_count += int(count)

    def record_retry(self, provider: str = "") -> None:
        self.retry_count += 1

    def record_circuit_breaker_trip(self, provider: str) -> None:
        self.circuit_breaker_trips[provider] = self.circuit_breaker_trips.get(provider, 0) + 1

    def record_error(self, error_type: str) -> None:
        self.error_count_by_type[error_type] = self.error_count_by_type.get(error_type, 0) + 1

    def record_rollback(self) -> None:
        self.rollback_count += 1

    def start_time_budget(self, total_seconds: float, *, threshold_seconds: float = 600.0) -> None:
        """Begin tracking a wall-clock budget. Caller passes the cap in seconds
        (e.g. 7200.0 for 2 hours) and the handoff threshold (default 600s = T-10min).
        Idempotent — re-calling resets the start time."""
        self.time_budget_start_s = time.monotonic()
        self.time_budget_total_s = float(total_seconds)
        self.handoff_threshold_s = float(threshold_seconds)
        self.handoff_triggered_at = 0.0

    def time_budget_remaining_s(self) -> float:
        """Seconds left before the wall-clock cap. ``inf`` when no budget set
        (``time_budget_total_s == 0``). Negative when over-budget — caller
        decides whether to hard-stop or grace."""
        if self.time_budget_total_s <= 0.0:
            return float("inf")
        elapsed = time.monotonic() - self.time_budget_start_s
        return self.time_budget_total_s - elapsed

    def is_handoff_due(self) -> bool:
        """One-shot check: returns True the first time wall-clock crosses
        the T-threshold (default T-10min) and a handoff has not yet been
        triggered. Subsequent calls return False so AgenticLoop fires
        ``HANDOFF_TRIGGERED`` once per session, not every round.

        Thread-safe — the latch test+set is guarded by an instance lock so
        ``asyncio.to_thread`` fan-out (or any concurrent threaded callers)
        observes a single winner. The fast-path early-return skips the lock
        when no budget is set or the latch has already fired.
        """
        if self.time_budget_total_s <= 0.0 or self.handoff_triggered_at > 0.0:
            return False
        with self._handoff_latch_lock:
            if self.handoff_triggered_at > 0.0:
                return False  # Lost the race to another caller.
            remaining = self.time_budget_remaining_s()
            if remaining <= self.handoff_threshold_s:
                self.handoff_triggered_at = time.monotonic()
                return True
            return False

    def record_goodhart(
        self,
        *,
        missing_dims: int = 0,
        missing_benches: int = 0,
        cross_validation_conflict: bool = False,
    ) -> None:
        self.missing_dims_total += int(missing_dims)
        self.missing_benches_total += int(missing_benches)
        if cross_validation_conflict:
            self.cross_validation_conflict_count += 1

    # ------------------------------------------------------------------
    # Persistence shape
    # ------------------------------------------------------------------

    def to_session_row(self) -> dict[str, Any]:
        """Render as ``sessions.jsonl`` row (hermes ``sessions`` table parity +
        paperclip ``usageJson`` parity). Caller appends to disk.
        """
        return {
            "session_id": self.session_id,
            "gen_tag": self.gen_tag,
            "component": self.component,
            "started_at": self.started_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "thinking_tokens": self.thinking_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "model_used": self.model_used,
            "api_call_count": self.api_call_count,
            "tool_call_count": self.tool_call_count,
            "message_count": self.message_count,
            "mutation_count": self.mutation_count,
            "audit_call_count": self.audit_call_count,
            "billing_provider": self.billing_provider,
            "billing_mode": self.billing_mode,
            "retry_count": self.retry_count,
            "circuit_breaker_trips": dict(self.circuit_breaker_trips),
            "error_count_by_type": dict(self.error_count_by_type),
            "rollback_count": self.rollback_count,
            "fitness_before": self.fitness_before,
            "fitness_after": self.fitness_after,
            "cohort_tag": self.cohort_tag,
            "missing_dims_total": self.missing_dims_total,
            "missing_benches_total": self.missing_benches_total,
            "cross_validation_conflict_count": self.cross_validation_conflict_count,
            "time_budget_total_s": self.time_budget_total_s,
            "handoff_threshold_s": self.handoff_threshold_s,
            "handoff_triggered_at": self.handoff_triggered_at,
        }


def current_session_metrics() -> SessionMetrics:
    """Return the SessionMetrics active in the current ContextVar scope.

    Lazy-init: returns a fresh ``SessionMetrics()`` and binds it to the
    ContextVar when none is set. This means *every* caller in *every*
    scope sees a valid object — never ``None``. The trade-off is that
    unscoped callers (test suites, ad-hoc scripts) accumulate into a
    throwaway object instead of crashing, which matches the
    ``SessionJournal`` pattern's no-op fallback.
    """
    metrics = _current_metrics.get()
    if metrics is None:
        metrics = SessionMetrics()
        _current_metrics.set(metrics)
    return metrics


def set_current_session_metrics(
    metrics: SessionMetrics | None,
) -> contextvars.Token[SessionMetrics | None]:
    """Bind ``metrics`` to the current ContextVar scope. Returns the reset token."""
    return _current_metrics.set(metrics)


@contextmanager
def session_metrics_scope(
    *,
    session_id: str = "",
    gen_tag: str = "",
    component: str = "",
) -> Iterator[SessionMetrics]:
    """Context manager — bind a fresh ``SessionMetrics`` for the duration of
    the ``with`` block. Restores the prior value on exit even if an
    exception propagates.

    Mirrors ``session_journal_scope`` (``core/observability/session_journal.py``)
    so callers can wrap both inside a single ``ExitStack`` when starting an
    audit / mutation cycle.
    """
    metrics = SessionMetrics(
        session_id=session_id,
        gen_tag=gen_tag,
        component=component,
        started_at=time.time(),
    )
    token = _current_metrics.set(metrics)
    try:
        yield metrics
    finally:
        _current_metrics.reset(token)
