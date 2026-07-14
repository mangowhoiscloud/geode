"""ActivityRow — paperclip activity_log envelope + per-event payload schemas.

Spec: ``docs/plans/2026-05-24-hookevent-activity-schema.md``.

Adapts paperclip's ``PluginEvent<TPayload>`` envelope
(``~/workspace/paperclip/packages/plugins/sdk/src/types.ts:180``) and
openclaw's ``z.discriminatedUnion("type")`` pattern
(``~/workspace/openclaw/extensions/voice-call/src/types.ts:90``) to
GEODE. Pre-PR-COMM-1 the ``HookEvent`` payloads were untyped
``dict[str, Any]`` — bugs only surfaced at the handler reading the dict.

Structure (PR-OBS-CONTRACT, 2026-06-13 — full coverage):
  - 1 envelope (``ActivityRowBase``) with ``schema_version``
  - 4 lifecycle detail mixins (started / completed / failed / retried)
  - 19 lifecycle concrete classes (A=6 started, B=7 completed, C=5 failed,
    D=1 retried) with discriminator on ``action``
  - 45 K-group concrete classes covering every remaining HookEvent, each
    with a typed ``details`` sub-schema (25 shared details models — one per
    event family, e.g. ``CognitivePhaseDetails`` for 6 cognitive phases)
  - ``GenericActivityRow`` is now ONLY a fail-soft fallback (a typed
    builder that hits a malformed payload), never a routine destination —
    every one of the 65 events has a concrete typed row.

Construction is centralized in ``activity_registry.py``: 19 lifecycle
curry-builders + a single declarative ``_TYPED_ROW_SPECS`` table that drives
all 45 K-group rows through one ``_build_from_spec`` builder.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ActivityRow",
    "ActivityRowBase",
    "AdapterDispatchAttemptDetails",
    "AdapterDispatchAttemptRow",
    "ApprovalTransitionDetails",
    "ApprovalTransitionRow",
    "AutoTriggerDetails",
    "AutoTriggerRow",
    "BaselinePromotedDetails",
    "BaselinePromotedRow",
    "CognitiveActRow",
    "CognitiveObserveRow",
    "CognitivePerceiveRow",
    "CognitivePhaseDetails",
    "CognitivePlanRow",
    "CognitiveReflectRow",
    "CognitiveUpdateMemoryRow",
    "ConfigReloadedDetails",
    "ConfigReloadedRow",
    "ContextCriticalRow",
    "ContextOverflowActionRow",
    "ContextPressureDetails",
    "CostGuardDetails",
    "CostLimitExceededRow",
    "CostWarningRow",
    "ExecutionCancelledDetails",
    "ExecutionCancelledRow",
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
    "McpServerConnectedRow",
    "McpServerDetails",
    "McpServerFailedRow",
    "MemoryPromotionProposedDetails",
    "MemoryPromotionProposedRow",
    "MemorySavedDetails",
    "MemorySavedRow",
    "ModelSwitchedDetails",
    "ModelSwitchedRow",
    "MutationAppliedRow",
    "MutationDetails",
    "MutationProposedRow",
    "MutationRejectedRow",
    "MutationRevertedRow",
    "PostAnalysisDetails",
    "PostAnalysisRow",
    "ProgramMdUnreadableDetails",
    "ProgramMdUnreadableRow",
    "PromptAssembledDetails",
    "PromptAssembledRow",
    "ReasoningMetricsDetails",
    "ReasoningMetricsRow",
    "ResultFeedbackDetails",
    "ResultFeedbackRow",
    "RuleChangeDetails",
    "RuleChangedRow",
    "SessionEndedRow",
    "SessionStartedRow",
    "ShutdownStartedDetails",
    "ShutdownStartedRow",
    "SubAgentCompletedRow",
    "SubAgentFailedRow",
    "SubAgentStartedRow",
    "ToolApprovalDetails",
    "ToolApprovalRequestedRow",
    "ToolExecEndedRow",
    "ToolExecFailedRow",
    "ToolExecStartedRow",
    "ToolRecoveryAttemptedRow",
    "ToolRecoveryFailedRow",
    "ToolRecoverySucceededRow",
    "ToolResultOffloadedDetails",
    "ToolResultOffloadedRow",
    "ToolResultTransformDetails",
    "ToolResultTransformRow",
    "TriggerFiredDetails",
    "TriggerFiredRow",
    "TurnCompletedRow",
    "TurnVerifyFailedRow",
    "TurnVerifyPassedRow",
    "TypedActivityRow",
    "UserInputReceivedDetails",
    "UserInputReceivedRow",
]


# ---------------------------------------------------------------------------
# Tier 1 — paperclip-style envelope
# ---------------------------------------------------------------------------


class ActivityRowBase(BaseModel):
    """paperclip ``PluginEvent`` envelope equivalent + GEODE run metadata.

    Every mapped HookEvent produces one of 56 concrete subclasses or a
    :class:`GenericActivityRow` fail-soft fallback. ``HookPersistenceSink``
    uses this envelope as its projection; the catalog excludes compatibility
    duplicates before SQL or active-run transcript persistence.

    Field semantics mirror paperclip's
    ``packages/db/src/schema/activity_log.ts:6`` ``activity_log`` table:
    actor / action / entity is the classification quintuple operators
    can grep on for any cross-cycle / cross-agent question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    """Row-schema version (PR-OBS-CONTRACT, 2026-06-13). Bump when a
    field is added/renamed/retyped on any row class so JSONL re-readers
    can branch on shape instead of guessing from key presence."""

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


class GenericActivityRow(ActivityRowBase):
    """Fail-soft row for malformed payloads or an unregistered future event.

    The ``details`` dict is free-form, but the registry and persistence sink
    scrub and bound it before it reaches a durable surface."""

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
# PR-OBS-CONTRACT (2026-06-13) — typed details for the formerly-generic 43.
# Each class IS the payload contract for its event family; the HookEvent
# enum carries a single pointer note instead of 43 scattered comments
# (dual-SoT rule: one schema home). Privacy/size drops are explicit:
# raw user input, full tool results, and cognitive-state snapshots are
# NOT persisted — derived scalars stand in for them.
# ---------------------------------------------------------------------------


class AdapterDispatchAttemptDetails(BaseModel):
    """ADAPTER_DISPATCH_ATTEMPT — one row per adapter try (dispatch.py)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_name: str
    provider: str = ""
    source: str = ""
    capability: str = ""
    outcome: str = ""
    elapsed_ms: float = 0.0
    error_type: str = ""
    error_msg: str = ""


class BaselinePromotedDetails(BaseModel):
    """BASELINE_PROMOTED — self-improving baseline SoT rotation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_path: str
    prior_baseline_path: str = ""
    run_id: str = ""
    reason: str = ""
    ts: float = 0.0


class CognitivePhaseDetails(BaseModel):
    """COGNITIVE_* family — loop phase telemetry. The full
    ``cognitive_state`` snapshot and raw ``user_input`` are intentionally
    NOT persisted (size + privacy); ``input_len`` stands in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = ""
    round: int = 0
    tool_names: tuple[str, ...] = ()
    result_count: int = 0
    input_len: int = 0


class ConfigReloadedDetails(BaseModel):
    """CONFIG_RELOADED — runtime config re-read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config_path: str = ""


class ContextPressureDetails(BaseModel):
    """CONTEXT_CRITICAL / CONTEXT_OVERFLOW_ACTION — context-budget
    pressure. ``metrics`` is the ContextMetrics asdict (usage_pct,
    estimated_tokens, context_window, ...)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metrics: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    provider: str = ""


class CostGuardDetails(BaseModel):
    """COST_WARNING / COST_LIMIT_EXCEEDED — session cost-cap telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_cost_usd: float
    limit_usd: float
    pct: float = 1.0


class ExecutionCancelledDetails(BaseModel):
    """EXECUTION_CANCELLED — isolated-execution subprocess cancel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = ""
    reason: str = ""


class McpServerDetails(BaseModel):
    """MCP_SERVER_CONNECTED / MCP_SERVER_FAILED."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    server_name: str
    error: str = ""


class MemorySavedDetails(BaseModel):
    """MEMORY_SAVED — note/memory persistence. The CLI handler omits
    ``persistent`` (defaults False) — accepted divergence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = ""
    persistent: bool = False


class MemoryPromotionProposedDetails(BaseModel):
    """MEMORY_PROMOTION_PROPOSED — memory dedup cluster crossed the
    >=3-distinct-sessions gate and a HITL proposal file was written
    (never an automatic rules/ write)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str = ""
    proposal_path: str = ""
    session_ids: tuple[str, ...] = ()
    source_count: int = 0
    ts: float = 0.0


class ResultFeedbackDetails(BaseModel):
    """RESULT_FEEDBACK — operator verdict on a result (rate/accept/reject_result
    tool handlers). ``verdict`` is one of ``rated`` / ``accepted`` / ``rejected``;
    ``rating`` + ``comment`` accompany a rating, ``reason`` a rejection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = ""
    verdict: str = ""
    rating: int = 0
    comment: str = ""
    reason: str = ""


class ModelSwitchedDetails(BaseModel):
    """MODEL_SWITCHED — live-session model switch (trigger_async emit;
    ``purged_ack_count`` = stale-ack purge count, PR-SIL-5THEME C5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_model: str = ""
    to_model: str = ""
    reason: str = ""
    purged_ack_count: int = 0


class MutationDetails(BaseModel):
    """MUTATION_PROPOSED/APPLIED/REJECTED/REVERTED — scaffold mutation
    lifecycle (reason populated on reject/revert)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mutation_id: str
    target_kind: str = ""
    target_path: str = ""
    run_id: str = ""
    reason: str = ""
    ts: float = 0.0


class PostAnalysisDetails(BaseModel):
    """POST_ANALYSIS — scheduler trigger post-run summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_type: str = ""
    automation_id: str = ""
    session_id: str = ""
    snapshot_id: str = ""
    success: bool = True


class ProgramMdUnreadableDetails(BaseModel):
    """PROGRAM_MD_UNREADABLE — feedback hook (trigger_with_result)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = ""


class PromptAssembledDetails(BaseModel):
    """PROMPT_ASSEMBLED — D4 X2 system-prompt rebuild telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = ""
    provider: str = ""
    reason: str = ""
    x2_injected: bool = False
    prompt_len: int = 0


class ReasoningMetricsDetails(BaseModel):
    """REASONING_METRICS — per-session reasoning economics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_rounds: int = 0
    thinking_tokens: int = 0
    output_tokens: int = 0
    thinking_ratio: float = 0.0
    tool_calls_total: int = 0
    empty_rounds: int = 0
    cost_usd: float = 0.0
    cost_per_tool_call: float | None = None
    overthinking_detected: bool = False


class AutoTriggerDetails(BaseModel):
    """SELF_IMPROVING_AUTO_TRIGGER — one terminal state per row; the
    ``stage`` field carries the state discriminator (fired / lock_busy /
    interval_blocked / runner_error / parse_error /
    max_generation_reached)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_id: str
    stage: str = ""
    detail: str = ""
    ts: float = 0.0


class ShutdownStartedDetails(BaseModel):
    """SHUTDOWN_STARTED — serve daemon shutdown entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_sessions: int = 0


class ToolApprovalDetails(BaseModel):
    """TOOL_APPROVAL_REQUESTED — HITL gate telemetry (grant/deny outcomes
    live on the APPROVAL_TRANSITION rail)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    safety_level: str = ""
    always: bool = False
    permission_level: str = ""
    decision: str = ""
    latency_ms: float = 0.0


class ApprovalTransitionDetails(BaseModel):
    """APPROVAL_TRANSITION — one ApprovalRecord FSM handoff.

    ``raw_input`` and the full ``transitions`` trail are deliberately NOT
    declared — the key-intersection pull in ``_build_from_spec`` drops them
    from the timeline (they persist on the EvidenceLedger rail instead).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    approval_id: str = ""
    category: str = ""
    state: str = ""
    verdict: str = ""
    detail: str = ""
    illegal: bool = False


class ToolResultOffloadedDetails(BaseModel):
    """TOOL_RESULT_OFFLOADED — large-result filesystem offload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref_id: str = ""
    original_tokens: int = 0
    block_id: str = ""


class ToolResultTransformDetails(BaseModel):
    """TOOL_RESULT_TRANSFORM — feedback hook. The full ``result`` and
    ``tool_input`` are intentionally NOT persisted (size)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = ""
    has_error: bool = False


class RuleChangeDetails(BaseModel):
    """RULE_CHANGED — analysis-rule CRUD; ``action`` carries
    created / updated / deleted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    action: str = ""
    paths: tuple[str, ...] = ()


class TriggerFiredDetails(BaseModel):
    """TRIGGER_FIRED — scheduler trigger callback success."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_id: str = ""
    type: str = ""


class UserInputReceivedDetails(BaseModel):
    """USER_INPUT_RECEIVED — interceptor hook. Raw input is NOT
    persisted (privacy, G9 lesson); ``input_len`` stands in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = ""
    input_len: int = 0


# ---------------------------------------------------------------------------
# Tier 3 — 37 K-group concrete classes (PR-OBS-CONTRACT, 2026-06-13)
#
# Each formerly-generic HookEvent now has a concrete typed row with a
# Literal ``action`` discriminator + a typed ``details`` sub-schema. The
# details models (shared across event families — one CognitivePhaseDetails
# for 6 cognitive phases, one MutationDetails for 4 mutation verbs, one
# AutoTriggerDetails carrying the auto-trigger terminal ``stage``) are
# defined above.
# Construction is driven by the single declarative ``_TYPED_ROW_SPECS`` table
# in activity_registry.py — NOT 43 hand-written builders.
# ---------------------------------------------------------------------------


class AdapterDispatchAttemptRow(ActivityRowBase):
    action: Literal["adapter.dispatch.attempt"] = "adapter.dispatch.attempt"
    entity_type: Literal["adapter"] = "adapter"
    details: AdapterDispatchAttemptDetails


class BaselinePromotedRow(ActivityRowBase):
    action: Literal["baseline.promoted"] = "baseline.promoted"
    entity_type: Literal["baseline"] = "baseline"
    details: BaselinePromotedDetails


class CognitivePerceiveRow(ActivityRowBase):
    action: Literal["cognitive.perceive"] = "cognitive.perceive"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class CognitivePlanRow(ActivityRowBase):
    action: Literal["cognitive.plan"] = "cognitive.plan"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class CognitiveActRow(ActivityRowBase):
    action: Literal["cognitive.act"] = "cognitive.act"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class CognitiveObserveRow(ActivityRowBase):
    action: Literal["cognitive.observe"] = "cognitive.observe"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class CognitiveReflectRow(ActivityRowBase):
    action: Literal["cognitive.reflect"] = "cognitive.reflect"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class CognitiveUpdateMemoryRow(ActivityRowBase):
    action: Literal["cognitive.update.memory"] = "cognitive.update.memory"
    entity_type: Literal["cognitive"] = "cognitive"
    details: CognitivePhaseDetails


class ConfigReloadedRow(ActivityRowBase):
    action: Literal["config.reloaded"] = "config.reloaded"
    entity_type: Literal["config"] = "config"
    details: ConfigReloadedDetails


class ContextCriticalRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["context.critical"] = "context.critical"
    entity_type: Literal["context"] = "context"
    details: ContextPressureDetails


class ContextOverflowActionRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["context.overflow.action"] = "context.overflow.action"
    entity_type: Literal["context"] = "context"
    details: ContextPressureDetails


class CostWarningRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["cost.warning"] = "cost.warning"
    entity_type: Literal["cost"] = "cost"
    details: CostGuardDetails


class CostLimitExceededRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "error"
    action: Literal["cost.limit.exceeded"] = "cost.limit.exceeded"
    entity_type: Literal["cost"] = "cost"
    details: CostGuardDetails


class ExecutionCancelledRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["execution.cancelled"] = "execution.cancelled"
    entity_type: Literal["execution"] = "execution"
    details: ExecutionCancelledDetails


class McpServerConnectedRow(ActivityRowBase):
    action: Literal["mcp.server.connected"] = "mcp.server.connected"
    entity_type: Literal["mcp_server"] = "mcp_server"
    details: McpServerDetails


class McpServerFailedRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "error"
    action: Literal["mcp.server.failed"] = "mcp.server.failed"
    entity_type: Literal["mcp_server"] = "mcp_server"
    details: McpServerDetails


class MemorySavedRow(ActivityRowBase):
    action: Literal["memory.saved"] = "memory.saved"
    entity_type: Literal["memory"] = "memory"
    details: MemorySavedDetails


class MemoryPromotionProposedRow(ActivityRowBase):
    action: Literal["memory.promotion.proposed"] = "memory.promotion.proposed"
    entity_type: Literal["memory_promotion"] = "memory_promotion"
    details: MemoryPromotionProposedDetails


class ResultFeedbackRow(ActivityRowBase):
    action: Literal["result.feedback"] = "result.feedback"
    entity_type: Literal["result"] = "result"
    details: ResultFeedbackDetails


class RuleChangedRow(ActivityRowBase):
    action: Literal["rule.changed"] = "rule.changed"
    entity_type: Literal["rule"] = "rule"
    details: RuleChangeDetails


class ModelSwitchedRow(ActivityRowBase):
    action: Literal["model.switched"] = "model.switched"
    entity_type: Literal["model"] = "model"
    details: ModelSwitchedDetails


class PromptAssembledRow(ActivityRowBase):
    action: Literal["prompt.assembled"] = "prompt.assembled"
    entity_type: Literal["prompt"] = "prompt"
    details: PromptAssembledDetails


class ReasoningMetricsRow(ActivityRowBase):
    action: Literal["reasoning.metrics"] = "reasoning.metrics"
    entity_type: Literal["reasoning"] = "reasoning"
    details: ReasoningMetricsDetails


class MutationProposedRow(ActivityRowBase):
    action: Literal["mutation.proposed"] = "mutation.proposed"
    entity_type: Literal["mutation"] = "mutation"
    details: MutationDetails


class MutationAppliedRow(ActivityRowBase):
    action: Literal["mutation.applied"] = "mutation.applied"
    entity_type: Literal["mutation"] = "mutation"
    details: MutationDetails


class MutationRejectedRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["mutation.rejected"] = "mutation.rejected"
    entity_type: Literal["mutation"] = "mutation"
    details: MutationDetails


class MutationRevertedRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["mutation.reverted"] = "mutation.reverted"
    entity_type: Literal["mutation"] = "mutation"
    details: MutationDetails


class AutoTriggerRow(ActivityRowBase):
    """One row per auto-trigger terminal state; ``details.stage`` is the
    discriminator (PR-HOOK-TAXONOMY D2 collapsed the former six per-state
    row classes — per-state ``level`` nuance now lives in the stage
    field, every row persists at ``info``)."""

    action: Literal["self.improving.auto.trigger"] = "self.improving.auto.trigger"
    entity_type: Literal["auto_trigger"] = "auto_trigger"
    details: AutoTriggerDetails


class ShutdownStartedRow(ActivityRowBase):
    action: Literal["shutdown.started"] = "shutdown.started"
    entity_type: Literal["shutdown"] = "shutdown"
    details: ShutdownStartedDetails


class ToolApprovalRequestedRow(ActivityRowBase):
    action: Literal["tool.approval.requested"] = "tool.approval.requested"
    entity_type: Literal["tool_approval"] = "tool_approval"
    details: ToolApprovalDetails


class ApprovalTransitionRow(ActivityRowBase):
    action: Literal["tool.approval.transition"] = "tool.approval.transition"
    entity_type: Literal["tool_approval"] = "tool_approval"
    details: ApprovalTransitionDetails


class ToolResultOffloadedRow(ActivityRowBase):
    action: Literal["tool.result.offloaded"] = "tool.result.offloaded"
    entity_type: Literal["tool_result"] = "tool_result"
    details: ToolResultOffloadedDetails


class ToolResultTransformRow(ActivityRowBase):
    action: Literal["tool.result.transform"] = "tool.result.transform"
    entity_type: Literal["tool_result"] = "tool_result"
    details: ToolResultTransformDetails


class PostAnalysisRow(ActivityRowBase):
    action: Literal["post.analysis"] = "post.analysis"
    entity_type: Literal["trigger"] = "trigger"
    details: PostAnalysisDetails


class ProgramMdUnreadableRow(ActivityRowBase):
    level: Literal["info", "warn", "error"] = "warn"
    action: Literal["program.md.unreadable"] = "program.md.unreadable"
    entity_type: Literal["program_md"] = "program_md"
    details: ProgramMdUnreadableDetails


class TriggerFiredRow(ActivityRowBase):
    action: Literal["trigger.fired"] = "trigger.fired"
    entity_type: Literal["trigger"] = "trigger"
    details: TriggerFiredDetails


class UserInputReceivedRow(ActivityRowBase):
    action: Literal["user.input.received"] = "user.input.received"
    entity_type: Literal["user_input"] = "user_input"
    details: UserInputReceivedDetails


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
        # K (PR-OBS-CONTRACT — 37 formerly-generic events)
        AdapterDispatchAttemptRow,
        BaselinePromotedRow,
        CognitivePerceiveRow,
        CognitivePlanRow,
        CognitiveActRow,
        CognitiveObserveRow,
        CognitiveReflectRow,
        CognitiveUpdateMemoryRow,
        ConfigReloadedRow,
        ContextCriticalRow,
        ContextOverflowActionRow,
        CostWarningRow,
        CostLimitExceededRow,
        ExecutionCancelledRow,
        McpServerConnectedRow,
        McpServerFailedRow,
        MemorySavedRow,
        MemoryPromotionProposedRow,
        ResultFeedbackRow,
        RuleChangedRow,
        ModelSwitchedRow,
        PromptAssembledRow,
        ReasoningMetricsRow,
        MutationProposedRow,
        MutationAppliedRow,
        MutationRejectedRow,
        MutationRevertedRow,
        AutoTriggerRow,
        ShutdownStartedRow,
        ToolApprovalRequestedRow,
        ApprovalTransitionRow,
        ToolResultOffloadedRow,
        ToolResultTransformRow,
        PostAnalysisRow,
        ProgramMdUnreadableRow,
        TriggerFiredRow,
        UserInputReceivedRow,
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
