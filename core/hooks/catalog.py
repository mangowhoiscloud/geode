"""Persistence metadata for the HookEvent catalog.

The event enum remains the public compatibility surface. This module adds the
small amount of policy that should not be repeated by every persistence sink:
retention class and whether a compatibility signal is durable.
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
    HookEvent.TOOL_APPROVAL_GRANTED: HookEvent.APPROVAL_TRANSITION,
    HookEvent.TOOL_APPROVAL_DENIED: HookEvent.APPROVAL_TRANSITION,
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
    "EventPersistenceSpec",
    "EventRetentionClass",
    "event_persistence_spec",
]
