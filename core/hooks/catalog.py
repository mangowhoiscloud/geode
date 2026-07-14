"""Persistence and emit-contract metadata for the HookEvent catalog.

The event enum remains the public compatibility surface. This module adds the
small amount of policy that should not be repeated by every persistence sink:
retention class, whether a compatibility signal is durable, and the emit-side
payload contract (:data:`REQUIRED_PAYLOAD_KEYS`) that
``core.hooks.dispatch`` validates on every fire.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.hooks.system import HookEvent


class EventRetentionClass(StrEnum):
    """Retention buckets understood by the SQLite event store."""

    HIGH_VOLUME = "high_volume"
    STANDARD = "standard"
    AUDIT = "audit"
    TRANSIENT = "transient"


@dataclass(frozen=True, slots=True)
class EventPersistenceSpec:
    retention: EventRetentionClass = EventRetentionClass.STANDARD
    persist_sql: bool = True
    mirror_transcript: bool = True
    canonical_event: HookEvent | None = None


_HIGH_VOLUME_EVENTS = frozenset(
    {
        HookEvent.ADAPTER_DISPATCH_ATTEMPT,
        HookEvent.LLM_CALL_STARTED,
        HookEvent.LLM_CALL_ENDED,
        HookEvent.LLM_CALL_RETRIED,
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_EXEC_ENDED,
        HookEvent.REASONING_METRICS,
        HookEvent.COGNITIVE_PERCEIVE,
        HookEvent.COGNITIVE_PLAN,
        HookEvent.COGNITIVE_ACT,
        HookEvent.COGNITIVE_OBSERVE,
        HookEvent.COGNITIVE_REFLECT,
        HookEvent.COGNITIVE_UPDATE_MEMORY,
    }
)

_AUDIT_EVENTS = frozenset(
    {
        HookEvent.APPROVAL_TRANSITION,
        HookEvent.CONFIG_RELOADED,
        HookEvent.COST_WARNING,
        HookEvent.COST_LIMIT_EXCEEDED,
        HookEvent.EXECUTION_CANCELLED,
        HookEvent.HANDOFF_TRIGGERED,
        HookEvent.MEMORY_PROMOTION_PROPOSED,
        HookEvent.MUTATION_PROPOSED,
        HookEvent.MUTATION_APPLIED,
        HookEvent.MUTATION_REJECTED,
        HookEvent.MUTATION_REVERTED,
        HookEvent.BASELINE_PROMOTED,
        HookEvent.RESULT_FEEDBACK,
        HookEvent.SHUTDOWN_STARTED,
    }
)

# These coarse-grained signals remain available to third-party handlers while
# the public hook API deprecates them. Their canonical events already carry the
# same transition with more context, so persisting both would double-count.
_COMPATIBILITY_EVENTS: dict[HookEvent, HookEvent] = {
    HookEvent.LLM_CALL_FAILED: HookEvent.LLM_CALL_ENDED,
    HookEvent.TOOL_EXEC_FAILED: HookEvent.TOOL_EXEC_ENDED,
    HookEvent.TOOL_RESULT_TRANSFORM: HookEvent.TOOL_EXEC_ENDED,
    HookEvent.TOOL_APPROVAL_REQUESTED: HookEvent.APPROVAL_TRANSITION,
}


# Emit-side payload contract (PR-HOOK-TAXONOMY D7). Populated ONLY for
# events whose bootstrap handlers demonstrably require the keys — each
# entry cites the handler read in ``core/wiring/bootstrap.py`` (or the
# journal/episodic handlers it registers). ``core.hooks.dispatch``
# checks these on every fire and logs a WARNING (never raises) when an
# emit site drops a key the registered handlers need.
#
# Deliberately ABSENT despite a key-sensitive handler:
#   LLM_CALL_ENDED — the ``agent_runtime_llm_call_ended`` accumulator
#   needs ``session_id`` + ``usage`` (bootstrap.py ``_on_llm_call_ended``),
#   and the AgenticLoop emit site carries both. But the one-off router
#   path (``core/llm/router/calls/text.py``) fires the same event from a
#   layer where no session exists and provider usage objects are recorded
#   via the token tracker instead — the handler's empty-payload early
#   return is by-design filtering, not a wiring break. Requiring the keys
#   would warn on every legitimate one-off call; fabricating a session_id
#   to silence it would be worse. Honesty over noise.
REQUIRED_PAYLOAD_KEYS: dict[HookEvent, frozenset[str]] = {
    # bootstrap ``_on_session_ended`` early-returns without an id.
    HookEvent.SESSION_ENDED: frozenset({"session_id"}),
    # bootstrap ``sa_started`` audit logger + ``journal_subagent_started``
    # both read task_id/task_type.
    HookEvent.SUBAGENT_STARTED: frozenset({"task_id", "task_type"}),
    # bootstrap ``_on_subagent_completed`` early-returns without task_id
    # and persists component/status; ``journal_subagent`` reads status.
    HookEvent.SUBAGENT_COMPLETED: frozenset({"task_id", "component", "status"}),
    # episodic recorder (``make_episodic_recorder_handler``) reads
    # tool_name/has_error/duration_ms to build the Episode row.
    HookEvent.TOOL_EXEC_ENDED: frozenset({"tool_name", "has_error", "duration_ms"}),
}


def event_persistence_spec(event: HookEvent) -> EventPersistenceSpec:
    """Return the single persistence policy for ``event``."""
    canonical = _COMPATIBILITY_EVENTS.get(event)
    if canonical is not None:
        return EventPersistenceSpec(
            retention=EventRetentionClass.TRANSIENT,
            persist_sql=False,
            mirror_transcript=False,
            canonical_event=canonical,
        )
    if event in _HIGH_VOLUME_EVENTS:
        return EventPersistenceSpec(retention=EventRetentionClass.HIGH_VOLUME)
    if event in _AUDIT_EVENTS:
        return EventPersistenceSpec(retention=EventRetentionClass.AUDIT)
    return EventPersistenceSpec()


__all__ = [
    "REQUIRED_PAYLOAD_KEYS",
    "EventPersistenceSpec",
    "EventRetentionClass",
    "event_persistence_spec",
]
