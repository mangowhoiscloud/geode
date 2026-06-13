"""ActivityRow — paperclip activity_log envelope + per-event payload schemas.

Spec: ``docs/plans/2026-05-24-hookevent-activity-schema.md``.

Adapts paperclip's ``PluginEvent<TPayload>`` envelope
(``~/workspace/paperclip/packages/plugins/sdk/src/types.ts:180``) and
openclaw's ``z.discriminatedUnion("type")`` pattern
(``~/workspace/openclaw/extensions/voice-call/src/types.ts:90``) to
GEODE. Pre-PR-COMM-1 the 74 ``HookEvent`` payloads were untyped
``dict[str, Any]`` — bugs only surfaced at the handler reading the dict.

After PR-COMM-1 (S2 scope):
  - 1 envelope (``ActivityRowBase``)
  - 11 group bases (``LifecycleStartedRow`` / ``LifecycleCompletedRow`` /
    ``LifecycleFailedRow`` / ``LifecycleRetriedRow`` / ``CognitiveStepRow`` /
    ``AutoTriggerRow`` / ``StateChangeRow`` / ``CostBudgetRow`` /
    ``MemoryMutationRow`` / ``McpServerRow`` / ``GenericActivityRow``)
  - 32 lifecycle-pair concrete classes (A+B+C+D groups: 9 started + 13
    completed + 9 failed + 1 retried) with discriminator on ``action``
  - 42 non-lifecycle events fall through to ``GenericActivityRow``

Subsequent PRs (not in S2) will add concrete subclasses for the E-K
groups as their schemas stabilise.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ActivityRow",
    "ActivityRowBase",
    "AutoTriggerRow",
    "CognitiveStepRow",
    "CostBudgetRow",
    "GenericActivityRow",
    "HandoffTriggeredRow",
    "LLMCallEndedRow",
    "LLMCallFailedRow",
    "LLMCallRetriedRow",
    "LLMCallStartedRow",
    "LifecycleCompletedDetails",
    "LifecycleCompletedRow",
    "LifecycleFailedDetails",
    "LifecycleFailedRow",
    "LifecycleRetriedDetails",
    "LifecycleRetriedRow",
    "LifecycleStartedDetails",
    "LifecycleStartedRow",
    "McpServerRow",
    "MemoryMutationRow",
    "SessionEndedRow",
    "SessionStartedRow",
    "StateChangeRow",
    "SubAgentCompletedRow",
    "SubAgentFailedRow",
    "SubAgentStartedRow",
    "ToolExecEndedRow",
    "ToolExecFailedRow",
    "ToolExecStartedRow",
    "ToolRecoveryAttemptedRow",
    "ToolRecoveryFailedRow",
    "ToolRecoverySucceededRow",
    "TurnCompletedRow",
    "TurnVerifyFailedRow",
    "TurnVerifyPassedRow",
    "TypedActivityRow",
]


# ---------------------------------------------------------------------------
# Tier 1 — paperclip-style envelope
# ---------------------------------------------------------------------------


class ActivityRowBase(BaseModel):
    """paperclip ``PluginEvent`` envelope equivalent + GEODE run metadata.

    Every ``HookSystem.trigger()`` call produces exactly one of the 74
    concrete subclasses (when typed) or :class:`GenericActivityRow`
    (fall-through). The pipeline transcript at
    ``<run_dir>/transcript.jsonl`` carries a row for every hook event,
    not just the 4 SessionTranscript mirrors PR-U landed.

    Field semantics mirror paperclip's
    ``packages/db/src/schema/activity_log.ts:6`` ``activity_log`` table:
    actor / action / entity is the classification quintuple operators
    can grep on for any cross-cycle / cross-agent question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: float
    run_id: str
    actor_type: Literal["orchestrator", "agent", "system", "plugin"]
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    task_id: str | None = None
    level: Literal["info", "warn", "error"] = "info"


# ---------------------------------------------------------------------------
# Tier 2 — 11 group bases (shared payload schemas)
# ---------------------------------------------------------------------------


class LifecycleStartedDetails(BaseModel):
    """Group A — every ``*_STARTED`` / ``*_BOOTSTRAP`` / ``*_ENTERED``
    / ``*_TRIGGERED`` / ``*_ATTEMPTED`` event carries the identifier
    of the entity whose lifecycle just opened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str


class LifecycleStartedRow(ActivityRowBase):
    details: LifecycleStartedDetails


class LifecycleCompletedDetails(BaseModel):
    """Group B — every ``*_ENDED`` / ``*_COMPLETED`` / ``*_SUCCEEDED``
    / ``*_PASSED`` event carries the duration and success flag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_ms: float
    success: bool = True


class LifecycleCompletedRow(ActivityRowBase):
    details: LifecycleCompletedDetails


class LifecycleFailedDetails(BaseModel):
    """Group C — every ``*_ERROR`` / ``*_FAILED`` / ``*_TIMEOUT`` event
    carries an error classification + message. ``duration_ms`` is
    optional because some failures fire before the lifecycle pair's
    start event (e.g. a watchdog-fired failure)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_ms: float | None = None
    error_type: str
    message: str


class LifecycleFailedRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "error"
    details: LifecycleFailedDetails


class LifecycleRetriedDetails(BaseModel):
    """Group D — ``LLM_CALL_RETRIED`` carries the attempt number plus
    the reason classification (rate_limit / connection / timeout / ...)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int
    reason: str


class LifecycleRetriedRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    details: LifecycleRetriedDetails


# Group E-K base classes (defined for forward-compat with subsequent PRs
# that will add concrete subclasses; S2 routes these via GenericActivityRow).


class CognitiveStepRow(ActivityRowBase):
    """Group E — COGNITIVE_PERCEIVE / PLAN / ACT / OBSERVE / REFLECT /
    UPDATE_MEMORY. Concrete subclasses pending."""

    details: dict[str, Any] = Field(default_factory=dict)


class AutoTriggerRow(ActivityRowBase):
    """Group F — SELF_IMPROVING_AUTO_TRIGGER_* (5 events). Concrete
    subclasses pending."""

    details: dict[str, Any] = Field(default_factory=dict)


class StateChangeRow(ActivityRowBase):
    """Group G — MODEL_SWITCHED / TOOL_APPROVAL_* / VERIFICATION_* /
    CONFIG_RELOADED. Concrete subclasses pending."""

    details: dict[str, Any] = Field(default_factory=dict)


class CostBudgetRow(ActivityRowBase):
    """Group H — COST_WARNING / COST_LIMIT_EXCEEDED. Concrete
    subclasses pending."""

    level: Literal["info", "warn", "error"] = "warn"
    details: dict[str, Any] = Field(default_factory=dict)


class MemoryMutationRow(ActivityRowBase):
    """Group I — MEMORY_SAVED / RULE_CREATED / RULE_UPDATED / RULE_DELETED.
    Concrete subclasses pending."""

    details: dict[str, Any] = Field(default_factory=dict)


class McpServerRow(ActivityRowBase):
    """Group J — MCP_SERVER_CONNECTED / MCP_SERVER_FAILED. Concrete
    subclasses pending."""

    details: dict[str, Any] = Field(default_factory=dict)


class GenericActivityRow(ActivityRowBase):
    """Group K — fall-through for the 18+ non-lifecycle events that
    don't have a concrete subclass yet (PROMPT_ASSEMBLED /
    TRIGGER_FIRED / etc.). The ``details`` dict is
    free-form — subsequent PRs will tighten high-volume events.

    Also serves as the ValidationError fall-through path so a typed
    builder failure never silences a hook trigger."""

    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tier 3 — 21 lifecycle concrete classes (A + B + C + D groups, S2 scope)
# ---------------------------------------------------------------------------

# A — Lifecycle started (6)


class SessionStartedRow(LifecycleStartedRow):
    action: Literal["session.started"] = "session.started"
    entity_type: Literal["session"] = "session"


class SubAgentStartedRow(LifecycleStartedRow):
    action: Literal["subagent.started"] = "subagent.started"
    entity_type: Literal["task"] = "task"


class LLMCallStartedRow(LifecycleStartedRow):
    action: Literal["llm.call.started"] = "llm.call.started"
    entity_type: Literal["llm_call"] = "llm_call"


class ToolExecStartedRow(LifecycleStartedRow):
    action: Literal["tool.exec.started"] = "tool.exec.started"
    entity_type: Literal["tool_call"] = "tool_call"


class HandoffTriggeredRow(LifecycleStartedRow):
    action: Literal["handoff.triggered"] = "handoff.triggered"
    entity_type: Literal["handoff"] = "handoff"


class ToolRecoveryAttemptedRow(LifecycleStartedRow):
    action: Literal["tool.recovery.attempted"] = "tool.recovery.attempted"
    entity_type: Literal["tool_call"] = "tool_call"


# B — Lifecycle completed (9)


class SessionEndedRow(LifecycleCompletedRow):
    action: Literal["session.ended"] = "session.ended"
    entity_type: Literal["session"] = "session"


class SubAgentCompletedRow(LifecycleCompletedRow):
    action: Literal["subagent.completed"] = "subagent.completed"
    entity_type: Literal["task"] = "task"


class LLMCallEndedRow(LifecycleCompletedRow):
    action: Literal["llm.call.ended"] = "llm.call.ended"
    entity_type: Literal["llm_call"] = "llm_call"


class ToolExecEndedRow(LifecycleCompletedRow):
    action: Literal["tool.exec.ended"] = "tool.exec.ended"
    entity_type: Literal["tool_call"] = "tool_call"


class ToolRecoverySucceededRow(LifecycleCompletedRow):
    action: Literal["tool.recovery.succeeded"] = "tool.recovery.succeeded"
    entity_type: Literal["tool_call"] = "tool_call"


class TurnCompletedRow(LifecycleCompletedRow):
    action: Literal["turn.completed"] = "turn.completed"
    entity_type: Literal["turn"] = "turn"


class TurnVerifyPassedRow(LifecycleCompletedRow):
    action: Literal["turn.verify.passed"] = "turn.verify.passed"
    entity_type: Literal["turn_verify"] = "turn_verify"


# C — Lifecycle failed (5)


class SubAgentFailedRow(LifecycleFailedRow):
    action: Literal["subagent.failed"] = "subagent.failed"
    entity_type: Literal["task"] = "task"


class LLMCallFailedRow(LifecycleFailedRow):
    action: Literal["llm.call.failed"] = "llm.call.failed"
    entity_type: Literal["llm_call"] = "llm_call"


class ToolExecFailedRow(LifecycleFailedRow):
    action: Literal["tool.exec.failed"] = "tool.exec.failed"
    entity_type: Literal["tool_call"] = "tool_call"


class ToolRecoveryFailedRow(LifecycleFailedRow):
    action: Literal["tool.recovery.failed"] = "tool.recovery.failed"
    entity_type: Literal["tool_call"] = "tool_call"


class TurnVerifyFailedRow(LifecycleFailedRow):
    action: Literal["turn.verify.failed"] = "turn.verify.failed"
    entity_type: Literal["turn_verify"] = "turn_verify"


# D — Retry (1)


class LLMCallRetriedRow(LifecycleRetriedRow):
    action: Literal["llm.call.retried"] = "llm.call.retried"
    entity_type: Literal["llm_call"] = "llm_call"


# ---------------------------------------------------------------------------
# Discriminated union — openclaw NormalizedEventSchema parity
# ---------------------------------------------------------------------------


TypedActivityRow = Annotated[
    Union[  # noqa: UP007 — Annotated discriminator needs Union, not | syntax
        # A
        SessionStartedRow,
        SubAgentStartedRow,
        LLMCallStartedRow,
        ToolExecStartedRow,
        HandoffTriggeredRow,
        ToolRecoveryAttemptedRow,
        # B
        SessionEndedRow,
        SubAgentCompletedRow,
        LLMCallEndedRow,
        ToolExecEndedRow,
        ToolRecoverySucceededRow,
        TurnCompletedRow,
        TurnVerifyPassedRow,
        # C
        SubAgentFailedRow,
        LLMCallFailedRow,
        ToolExecFailedRow,
        ToolRecoveryFailedRow,
        TurnVerifyFailedRow,
        # D
        LLMCallRetriedRow,
    ],
    Field(discriminator="action"),
]
"""Discriminated union of 32 typed lifecycle ActivityRow subclasses.

Mirrors openclaw's ``NormalizedEventSchema = z.discriminatedUnion("type", [...])``.
The ``action`` field is the discriminator — pydantic dispatches to the
correct subclass at ``model_validate`` time, raising
``ValidationError`` when ``action`` matches none. The fall-through
escape hatch (``GenericActivityRow``) is intentionally a sibling type,
not a union member, because pydantic requires every discriminator
target to declare ``action`` as ``Literal`` — ``GenericActivityRow.action``
is open ``str`` so unknown hook events still land in the timeline
without forcing a literal per event.
"""


ActivityRow = Union[TypedActivityRow, GenericActivityRow]  # noqa: UP007 — pydantic Union semantics
"""Public type alias — either a typed lifecycle row or the generic
fall-through. Registry callers decide which type to construct; the
TypedAdapter for validation should prefer ``TypedActivityRow`` first
and fall back to ``GenericActivityRow`` on ``ValidationError``."""
