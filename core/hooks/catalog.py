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
    mirror_run_projection: bool = True
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
        HookEvent.EXTENSION_INVOKED,
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
    # Historical name: emitted at each arun/turn completion for agent-runtime
    # subscribers. The durable session lifetime lives in session_events and
    # the public SessionEnd hook; TURN_COMPLETED is the sole telemetry row.
    HookEvent.SESSION_ENDED: HookEvent.TURN_COMPLETED,
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


# Contract version carried on every dispatched payload. Bump when a payload
# contract changes shape; readers pin on it the way SQL readers pin on the
# hook_events.schema_version column.
OBSERVER_SCHEMA_VERSION = "geode.observer.v1"


# Action-namespace families (2026-07-30). The first ``action`` segment is the
# only grouping key observability readers have, and 16 of the 27 segments held a
# single event each — a namespace that classifies nothing. Folding the singletons
# into the domain they already belong to leaves 13 families and 0 singletons
# without adding or removing an event.
#
# Hermes groups ~15 observer hooks into 6 families (hermes_cli/plugins.py
# VALID_HOOKS); Codex names ~66 signals across ~12 domains
# (codex-rs/otel/src/metrics/names.rs). GEODE sat at 56 events / 27 families.
#
# Old first segments stay readable through ACTION_FAMILY_ALIASES, the same shape
# the v1→v2 event rename used (core.hooks.system.LEGACY_EVENT_VALUES).
ACTION_FAMILY_ALIASES: dict[str, str] = {
    # the LLM call path — assembly, dispatch, switch, and its reasoning output
    "adapter": "llm",
    "prompt": "llm",
    "model": "llm",
    "reasoning": "llm",
    # one user turn, from input to cancellation, feedback, and post-analysis
    "user": "turn",
    "execution": "turn",
    "result": "turn",
    "post": "turn",
    # session lifetime boundaries
    "shutdown": "session",
    "handoff": "session",
    # operator-facing policy surfaces
    "rule": "policy",
    "config": "policy",
    "extension": "policy",
    "program": "policy",
    # the self-improvement loop
    "trigger": "improve",
    "self": "improve",
    "baseline": "improve",
}

ACTION_FAMILIES: frozenset[str] = frozenset(
    {
        "cognitive",
        "context",
        "cost",
        "improve",
        "llm",
        "mcp",
        "memory",
        "mutation",
        "policy",
        "session",
        "subagent",
        "tool",
        "turn",
    }
)


def action_family(action: str) -> str:
    """Return the canonical family for an ``action`` string.

    Accepts both the folded form and pre-fold values still on disk.
    """
    head = action.split(".", 1)[0]
    return ACTION_FAMILY_ALIASES.get(head, head)


def required_payload_keys(event: HookEvent) -> frozenset[str]:
    """The emit-side payload contract for ``event``, from both places it lives.

    Two registries described the same thing and neither knew about the other:
    ``REQUIRED_PAYLOAD_KEYS`` is hand-written and covers the 4 events built by
    dedicated row classes, while the declarative ``_TYPED_ROW_SPECS`` table
    carries pydantic ``details_cls`` models whose required fields are a contract
    for 14 more — a disjoint set. The dispatch validator only consulted the
    hand-written half, so 14 contracts that already existed went unchecked.

    Deriving the pydantic half instead of transcribing it keeps one source per
    event (CLAUDE.md CANNOT: no two registries for the same domain).
    """
    manual = REQUIRED_PAYLOAD_KEYS.get(event, frozenset())
    from core.observability.activity_registry import _TYPED_ROW_SPECS

    spec = _TYPED_ROW_SPECS.get(event)
    details = getattr(spec, "details_cls", None) if spec is not None else None
    derived = frozenset(
        name for name, field in getattr(details, "model_fields", {}).items() if field.is_required()
    )
    return manual | derived


def event_persistence_spec(event: HookEvent) -> EventPersistenceSpec:
    """Return the single persistence policy for ``event``."""
    canonical = _COMPATIBILITY_EVENTS.get(event)
    if canonical is not None:
        return EventPersistenceSpec(
            retention=EventRetentionClass.TRANSIENT,
            persist_sql=False,
            mirror_run_projection=False,
            canonical_event=canonical,
        )
    if event in _HIGH_VOLUME_EVENTS:
        return EventPersistenceSpec(retention=EventRetentionClass.HIGH_VOLUME)
    if event in _AUDIT_EVENTS:
        return EventPersistenceSpec(retention=EventRetentionClass.AUDIT)
    return EventPersistenceSpec()


__all__ = [
    "ACTION_FAMILIES",
    "ACTION_FAMILY_ALIASES",
    "OBSERVER_SCHEMA_VERSION",
    "REQUIRED_PAYLOAD_KEYS",
    "EventPersistenceSpec",
    "EventRetentionClass",
    "action_family",
    "event_persistence_spec",
    "required_payload_keys",
]
