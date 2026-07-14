"""HookEvent → ActivityRow mapping registry.

Spec: ``docs/plans/2026-05-24-hookevent-activity-schema.md`` §3, §7.1.

Every one of the 56 HookEvents maps to a builder that produces a
concrete typed ``ActivityRow`` subclass with a validated payload:
19 lifecycle events via the curry builders below, and the 37 K-group
events via the single declarative ``_TYPED_ROW_SPECS`` table +
``_build_from_spec`` (PR-OBS-CONTRACT, 2026-06-13). ``GenericActivityRow``
is now ONLY the fail-soft fallback for a typed builder that meets a
malformed payload — never a routine destination.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from core.hooks.system import HookEvent
from core.observability.activity import (
    AUTO_TRIGGER_STAGE_LEVELS,
    ActivityRowBase,
    AdapterDispatchAttemptDetails,
    AdapterDispatchAttemptRow,
    ApprovalTransitionDetails,
    ApprovalTransitionRow,
    AutoTriggerDetails,
    AutoTriggerRow,
    BaselinePromotedDetails,
    BaselinePromotedRow,
    CognitiveActRow,
    CognitiveObserveRow,
    CognitivePerceiveRow,
    CognitivePhaseDetails,
    CognitivePlanRow,
    CognitiveReflectRow,
    CognitiveUpdateMemoryRow,
    ConfigReloadedDetails,
    ConfigReloadedRow,
    ContextCriticalRow,
    ContextOverflowActionRow,
    ContextPressureDetails,
    CostGuardDetails,
    CostLimitExceededRow,
    CostWarningRow,
    ExecutionCancelledDetails,
    ExecutionCancelledRow,
    GenericActivityRow,
    HandoffTriggeredRow,
    LifecycleCompletedDetails,
    LifecycleCompletedRow,
    LifecycleFailedDetails,
    LifecycleFailedRow,
    LifecycleRetriedDetails,
    LifecycleRetriedRow,
    LifecycleStartedDetails,
    LifecycleStartedRow,
    LLMCallEndedRow,
    LLMCallFailedRow,
    LLMCallRetriedRow,
    LLMCallStartedRow,
    McpServerConnectedRow,
    McpServerDetails,
    McpServerFailedRow,
    MemoryPromotionProposedDetails,
    MemoryPromotionProposedRow,
    MemorySavedDetails,
    MemorySavedRow,
    ModelSwitchedDetails,
    ModelSwitchedRow,
    MutationAppliedRow,
    MutationDetails,
    MutationProposedRow,
    MutationRejectedRow,
    MutationRevertedRow,
    PostAnalysisDetails,
    PostAnalysisRow,
    ProgramMdUnreadableDetails,
    ProgramMdUnreadableRow,
    PromptAssembledDetails,
    PromptAssembledRow,
    ReasoningMetricsDetails,
    ReasoningMetricsRow,
    ResultFeedbackDetails,
    ResultFeedbackRow,
    RuleChangeDetails,
    RuleChangedRow,
    SessionEndedRow,
    SessionStartedRow,
    ShutdownStartedDetails,
    ShutdownStartedRow,
    SubAgentCompletedRow,
    SubAgentFailedRow,
    SubAgentStartedRow,
    ToolApprovalDetails,
    ToolApprovalRequestedRow,
    ToolExecEndedRow,
    ToolExecFailedRow,
    ToolExecStartedRow,
    ToolRecoveryAttemptedRow,
    ToolRecoveryFailedRow,
    ToolRecoverySucceededRow,
    ToolResultOffloadedDetails,
    ToolResultOffloadedRow,
    ToolResultTransformDetails,
    ToolResultTransformRow,
    TriggerFiredDetails,
    TriggerFiredRow,
    TurnCompletedRow,
    TurnVerifyFailedRow,
    TurnVerifyPassedRow,
    UserInputReceivedDetails,
    UserInputReceivedRow,
)

log = logging.getLogger(__name__)

__all__ = ["map_hook_to_activity"]


# ---------------------------------------------------------------------------
# Per-event row builders (32 lifecycle events typed in S2 scope)
# ---------------------------------------------------------------------------


_MISSING_IDENTIFIER_WARNED: set[tuple[str, str]] = set()


def _warn_missing_identifier(row_name: str, identifier_key: str) -> None:
    """One WARNING per (row, key) per process when the identifier
    fallback chain bottoms out at "" — an emit site is using the wrong
    key name and the row would otherwise ship with a silent empty
    identifier (PR-OBS-CONTRACT; silent coercion is an anti-pattern)."""
    seen_key = (row_name, identifier_key)
    if seen_key in _MISSING_IDENTIFIER_WARNED:
        return
    _MISSING_IDENTIFIER_WARNED.add(seen_key)
    log.warning(
        "%s: emit payload carries neither %r nor 'session_id' — identifier empty; "
        "fix the emit-site key",
        row_name,
        identifier_key,
    )


def _lifecycle_started(
    row_cls: type[LifecycleStartedRow],
    *,
    actor_type_default: str = "system",
    actor_key: str = "session_id",
    identifier_key: str = "task_id",
) -> Callable[[dict[str, Any], str], ActivityRowBase]:
    """Curry a builder for ``LifecycleStartedRow`` subclasses. The
    actor / identifier names are passed by keyword so each event can
    pick from its actual data dict (e.g. SUBAGENT_STARTED uses
    ``task_id``, SESSION_STARTED uses ``session_id``)."""

    def _build(data: dict[str, Any], run_id: str) -> ActivityRowBase:
        identifier = str(data.get(identifier_key) or data.get("session_id") or "")
        if not identifier:
            _warn_missing_identifier(row_cls.__name__, identifier_key)
        actor_id = str(data.get(actor_key) or data.get("session_id") or actor_type_default)
        return row_cls(  # type: ignore[call-arg]  # concrete row_cls overrides action/entity_type with Literal defaults; mypy can't see through dynamic type[]
            ts=time.time(),
            run_id=run_id,
            actor_type=_infer_actor_type(actor_type_default),
            actor_id=actor_id,
            entity_id=identifier or actor_id,
            task_id=str(data["task_id"]) if data.get("task_id") else None,
            details=LifecycleStartedDetails(identifier=identifier or actor_id),
        )

    return _build


def _lifecycle_completed(
    row_cls: type[LifecycleCompletedRow],
    *,
    actor_type_default: str = "system",
    actor_key: str = "session_id",
    identifier_key: str = "task_id",
) -> Callable[[dict[str, Any], str], ActivityRowBase]:
    """Curry a builder for ``LifecycleCompletedRow`` subclasses."""

    def _build(data: dict[str, Any], run_id: str) -> ActivityRowBase:
        identifier = str(data.get(identifier_key) or data.get("session_id") or "")
        if not identifier:
            _warn_missing_identifier(row_cls.__name__, identifier_key)
        actor_id = str(data.get(actor_key) or data.get("session_id") or actor_type_default)
        duration_ms = float(data.get("duration_ms", 0.0) or 0.0)
        success = bool(data.get("success", True))
        return row_cls(  # type: ignore[call-arg]  # concrete row_cls overrides action/entity_type with Literal defaults; mypy can't see through dynamic type[]
            ts=time.time(),
            run_id=run_id,
            actor_type=_infer_actor_type(actor_type_default),
            actor_id=actor_id,
            entity_id=identifier or actor_id,
            task_id=str(data["task_id"]) if data.get("task_id") else None,
            details=LifecycleCompletedDetails(duration_ms=duration_ms, success=success),
        )

    return _build


def _lifecycle_failed(
    row_cls: type[LifecycleFailedRow],
    *,
    actor_type_default: str = "system",
    actor_key: str = "session_id",
    identifier_key: str = "task_id",
) -> Callable[[dict[str, Any], str], ActivityRowBase]:
    """Curry a builder for ``LifecycleFailedRow`` subclasses."""

    def _build(data: dict[str, Any], run_id: str) -> ActivityRowBase:
        identifier = str(data.get(identifier_key) or data.get("session_id") or "")
        if not identifier:
            _warn_missing_identifier(row_cls.__name__, identifier_key)
        actor_id = str(data.get(actor_key) or data.get("session_id") or actor_type_default)
        duration_ms = data.get("duration_ms")
        return row_cls(  # type: ignore[call-arg]  # concrete row_cls overrides action/entity_type with Literal defaults; mypy can't see through dynamic type[]
            ts=time.time(),
            run_id=run_id,
            actor_type=_infer_actor_type(actor_type_default),
            actor_id=actor_id,
            entity_id=identifier or actor_id,
            task_id=str(data["task_id"]) if data.get("task_id") else None,
            details=LifecycleFailedDetails(
                duration_ms=float(duration_ms) if duration_ms is not None else None,
                error_type=str(data.get("error_type") or data.get("error") or "unknown"),
                message=str(data.get("message") or data.get("error") or ""),
            ),
        )

    return _build


def _lifecycle_retried(
    row_cls: type[LifecycleRetriedRow],
    *,
    actor_type_default: str = "system",
) -> Callable[[dict[str, Any], str], ActivityRowBase]:
    """Curry a builder for ``LifecycleRetriedRow`` subclasses."""

    def _build(data: dict[str, Any], run_id: str) -> ActivityRowBase:
        actor_id = str(data.get("session_id") or actor_type_default)
        attempt = int(data.get("attempt", 1) or 1)
        reason = str(data.get("reason") or data.get("error_type") or "unknown")
        return row_cls(  # type: ignore[call-arg]  # concrete row_cls overrides action/entity_type with Literal defaults; mypy can't see through dynamic type[]
            ts=time.time(),
            run_id=run_id,
            actor_type=_infer_actor_type(actor_type_default),
            actor_id=actor_id,
            entity_id=str(data.get("call_id") or actor_id),
            task_id=str(data["task_id"]) if data.get("task_id") else None,
            details=LifecycleRetriedDetails(attempt=attempt, reason=reason),
        )

    return _build


def _infer_actor_type(default: str) -> str:
    """Coerce the loose ``actor_type_default`` string into one of the
    four envelope-allowed literal values."""
    if default in {"orchestrator", "agent", "system", "plugin"}:
        return default
    return "system"


# ---------------------------------------------------------------------------
# 21 lifecycle event → builder mapping
# ---------------------------------------------------------------------------


HOOK_EVENT_TO_ROW_BUILDER: dict[HookEvent, Callable[[dict[str, Any], str], ActivityRowBase]] = {
    # A — lifecycle started (6)
    HookEvent.SESSION_STARTED: _lifecycle_started(
        SessionStartedRow, actor_type_default="orchestrator", identifier_key="session_id"
    ),
    HookEvent.SUBAGENT_STARTED: _lifecycle_started(SubAgentStartedRow, actor_type_default="agent"),
    HookEvent.LLM_CALL_STARTED: _lifecycle_started(
        LLMCallStartedRow, actor_type_default="agent", identifier_key="call_id"
    ),
    HookEvent.TOOL_EXEC_STARTED: _lifecycle_started(
        ToolExecStartedRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    HookEvent.HANDOFF_TRIGGERED: _lifecycle_started(
        HandoffTriggeredRow, actor_type_default="orchestrator", identifier_key="handoff_id"
    ),
    HookEvent.TOOL_RECOVERY_ATTEMPTED: _lifecycle_started(
        ToolRecoveryAttemptedRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    # B — lifecycle completed (9)
    HookEvent.SESSION_ENDED: _lifecycle_completed(
        SessionEndedRow, actor_type_default="orchestrator", identifier_key="session_id"
    ),
    HookEvent.SUBAGENT_COMPLETED: _lifecycle_completed(
        SubAgentCompletedRow, actor_type_default="agent"
    ),
    HookEvent.LLM_CALL_ENDED: _lifecycle_completed(
        LLMCallEndedRow, actor_type_default="agent", identifier_key="call_id"
    ),
    HookEvent.TOOL_EXEC_ENDED: _lifecycle_completed(
        ToolExecEndedRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    HookEvent.TOOL_RECOVERY_SUCCEEDED: _lifecycle_completed(
        ToolRecoverySucceededRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    HookEvent.TURN_COMPLETED: _lifecycle_completed(
        TurnCompletedRow, actor_type_default="agent", identifier_key="turn_id"
    ),
    HookEvent.TURN_VERIFY_PASSED: _lifecycle_completed(
        TurnVerifyPassedRow, actor_type_default="agent", identifier_key="turn_id"
    ),
    # C — lifecycle failed (5)
    HookEvent.SUBAGENT_FAILED: _lifecycle_failed(SubAgentFailedRow, actor_type_default="agent"),
    HookEvent.LLM_CALL_FAILED: _lifecycle_failed(
        LLMCallFailedRow, actor_type_default="agent", identifier_key="call_id"
    ),
    HookEvent.TOOL_EXEC_FAILED: _lifecycle_failed(
        ToolExecFailedRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    HookEvent.TOOL_RECOVERY_FAILED: _lifecycle_failed(
        ToolRecoveryFailedRow, actor_type_default="agent", identifier_key="tool_call_id"
    ),
    HookEvent.TURN_VERIFY_FAILED: _lifecycle_failed(
        TurnVerifyFailedRow, actor_type_default="agent", identifier_key="turn_id"
    ),
    # D — retry (1)
    HookEvent.LLM_CALL_RETRIED: _lifecycle_retried(LLMCallRetriedRow, actor_type_default="agent"),
}


# ---------------------------------------------------------------------------
# K-group typed rows (PR-OBS-CONTRACT, 2026-06-13) — centralized spec table
#
# The 37 formerly-generic events are typed via ONE declarative table +
# ONE builder, not 37 hand-written functions. Each _TypedRowSpec names the
# concrete row class, its details model, the envelope actor_type, and which
# payload key becomes entity_id. Construction pulls the intersection of the
# details model's declared fields and the live payload keys — which works
# because the details field names were chosen to MATCH the emit-site payload
# keys (see docs/plans/2026-05-24-hookevent-activity-schema.md, updated).
#
# Privacy/size drops are explicit and centralized in _derive_input_len:
# raw user_input / cognitive_state snapshots / full tool results never reach
# the timeline JSONL — derived scalars (input_len) stand in.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TypedRowSpec:
    """Declarative construction spec for one K-group event."""

    row_cls: type[ActivityRowBase]
    details_cls: type[BaseModel]
    actor_type: Literal["orchestrator", "agent", "system", "plugin"]
    entity_id_key: str = ""  # payload key -> entity_id; "" => event.value
    actor_id_key: str = "session_id"
    derive: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Payload -> row ``level`` override (e.g. auto-trigger failure stages
    # persist at error even though the collapsed event is one member).
    level_derive: Callable[[dict[str, Any]], str | None] | None = None


# Payload keys carrying raw user content or oversized blobs that must NEVER
# be persisted to the timeline JSONL (privacy + size; the G9 sanitizer lesson).
# The typed path drops them implicitly — the details models declare none of
# them, so the key-intersection pull in _build_from_spec excludes them. The
# generic FAIL-SOFT path must scrub them explicitly: a builder failure on a
# privacy-sensitive event (USER_INPUT_RECEIVED / COGNITIVE_* / TOOL_RESULT_*)
# would otherwise leak via ``details=data`` exactly what the typed row drops
# (Codex MCP review BLOCKER, 2026-06-13 — graceful contract must hold at
# EVERY exit, not just the typed one).
# ``args_preview`` is a bounded display string but ``approval._write_summary``
# can fill it from ``tool_input["content"][:80]`` — i.e. up to 80 chars of raw
# tool content — so it is forbidden from the fail-soft path too (Codex MCP
# review MAJOR). Typed approval rows already drop it (not a declared field).
_TIMELINE_FORBIDDEN_KEYS = frozenset(
    {"user_input", "cognitive_state", "tool_input", "result", "args_preview", "raw_input"}
)


def _derive_input_len(data: dict[str, Any]) -> dict[str, Any]:
    """COGNITIVE_PERCEIVE / USER_INPUT_RECEIVED carry the raw ``user_input``
    string in their hook payload. Persist only its LENGTH — raw user prompts
    must never land in the timeline JSONL (privacy; the G9 sanitizer lesson).
    ``cognitive_state`` snapshots and other non-field keys are dropped
    automatically because the builder only pulls declared details fields."""
    if "user_input" not in data:
        return data
    out = dict(data)
    out["input_len"] = len(str(out.get("user_input") or ""))
    return out


def _scrub_for_timeline(data: dict[str, Any]) -> dict[str, Any]:
    """Drop raw-content keys before they can reach a ``GenericActivityRow``
    on the fail-soft path, preserving the derived ``input_len`` signal where a
    raw ``user_input`` was. No-op (returns the same dict) when nothing is
    forbidden, so the common typed path pays nothing."""
    if not _TIMELINE_FORBIDDEN_KEYS.intersection(data):
        return data
    scrubbed = {k: v for k, v in data.items() if k not in _TIMELINE_FORBIDDEN_KEYS}
    if "user_input" in data and "input_len" not in scrubbed:
        scrubbed["input_len"] = len(str(data.get("user_input") or ""))
    return scrubbed


def _build_from_spec(
    spec: _TypedRowSpec,
    event: HookEvent,
    data: dict[str, Any],
    run_id: str,
) -> ActivityRowBase:
    """Construct a concrete typed K-group row from its spec.

    Pulls the intersection of the details model's declared fields and the
    payload keys, then lets pydantic validate/coerce (``list`` -> ``tuple``,
    numeric strings -> floats). A missing required field or a bad value
    raises ``ValidationError`` / ``ValueError`` which :func:`map_hook_to_activity`
    catches and routes to the distinguishable generic fallback row — the
    "always emit a row" contract holds."""
    src = spec.derive(data) if spec.derive is not None else data
    detail_kwargs = {k: src[k] for k in spec.details_cls.model_fields if k in src}
    details = spec.details_cls(**detail_kwargs)
    entity_id = (str(data.get(spec.entity_id_key)) if spec.entity_id_key else "") or event.value
    actor_id = str(data.get(spec.actor_id_key) or spec.actor_type)
    task_id = str(data["task_id"]) if data.get("task_id") else None
    row_kwargs: dict[str, Any] = {
        "ts": time.time(),
        "run_id": run_id,
        "actor_type": spec.actor_type,
        "actor_id": actor_id,
        "entity_id": entity_id,
        "task_id": task_id,
        "details": details,
    }
    if spec.level_derive is not None:
        derived_level = spec.level_derive(data)
        if derived_level is not None:
            row_kwargs["level"] = derived_level
    return spec.row_cls(**row_kwargs)


_TYPED_ROW_SPECS: dict[HookEvent, _TypedRowSpec] = {
    HookEvent.ADAPTER_DISPATCH_ATTEMPT: _TypedRowSpec(
        row_cls=AdapterDispatchAttemptRow,
        details_cls=AdapterDispatchAttemptDetails,
        actor_type="system",
        entity_id_key="adapter_name",
    ),
    HookEvent.BASELINE_PROMOTED: _TypedRowSpec(
        row_cls=BaselinePromotedRow,
        details_cls=BaselinePromotedDetails,
        actor_type="system",
        entity_id_key="run_id",
    ),
    HookEvent.COGNITIVE_PERCEIVE: _TypedRowSpec(
        row_cls=CognitivePerceiveRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.COGNITIVE_PLAN: _TypedRowSpec(
        row_cls=CognitivePlanRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.COGNITIVE_ACT: _TypedRowSpec(
        row_cls=CognitiveActRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.COGNITIVE_OBSERVE: _TypedRowSpec(
        row_cls=CognitiveObserveRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.COGNITIVE_REFLECT: _TypedRowSpec(
        row_cls=CognitiveReflectRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.COGNITIVE_UPDATE_MEMORY: _TypedRowSpec(
        row_cls=CognitiveUpdateMemoryRow,
        details_cls=CognitivePhaseDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
    HookEvent.CONFIG_RELOADED: _TypedRowSpec(
        row_cls=ConfigReloadedRow,
        details_cls=ConfigReloadedDetails,
        actor_type="system",
        entity_id_key="config_path",
    ),
    HookEvent.CONTEXT_CRITICAL: _TypedRowSpec(
        row_cls=ContextCriticalRow,
        details_cls=ContextPressureDetails,
        actor_type="agent",
        entity_id_key="model",
    ),
    HookEvent.CONTEXT_OVERFLOW_ACTION: _TypedRowSpec(
        row_cls=ContextOverflowActionRow,
        details_cls=ContextPressureDetails,
        actor_type="agent",
        entity_id_key="model",
    ),
    HookEvent.COST_WARNING: _TypedRowSpec(
        row_cls=CostWarningRow, details_cls=CostGuardDetails, actor_type="agent"
    ),
    HookEvent.COST_LIMIT_EXCEEDED: _TypedRowSpec(
        row_cls=CostLimitExceededRow, details_cls=CostGuardDetails, actor_type="agent"
    ),
    HookEvent.EXECUTION_CANCELLED: _TypedRowSpec(
        row_cls=ExecutionCancelledRow,
        details_cls=ExecutionCancelledDetails,
        actor_type="orchestrator",
        entity_id_key="session_id",
    ),
    HookEvent.MCP_SERVER_CONNECTED: _TypedRowSpec(
        row_cls=McpServerConnectedRow,
        details_cls=McpServerDetails,
        actor_type="system",
        entity_id_key="server_name",
    ),
    HookEvent.MCP_SERVER_FAILED: _TypedRowSpec(
        row_cls=McpServerFailedRow,
        details_cls=McpServerDetails,
        actor_type="system",
        entity_id_key="server_name",
    ),
    HookEvent.MEMORY_SAVED: _TypedRowSpec(
        row_cls=MemorySavedRow,
        details_cls=MemorySavedDetails,
        actor_type="agent",
        entity_id_key="key",
    ),
    HookEvent.MEMORY_PROMOTION_PROPOSED: _TypedRowSpec(
        row_cls=MemoryPromotionProposedRow,
        details_cls=MemoryPromotionProposedDetails,
        actor_type="system",
        entity_id_key="slug",
    ),
    HookEvent.RESULT_FEEDBACK: _TypedRowSpec(
        row_cls=ResultFeedbackRow,
        details_cls=ResultFeedbackDetails,
        actor_type="agent",
        entity_id_key="subject",
    ),
    HookEvent.RULE_CHANGED: _TypedRowSpec(
        row_cls=RuleChangedRow,
        details_cls=RuleChangeDetails,
        actor_type="agent",
        entity_id_key="name",
    ),
    HookEvent.MODEL_SWITCHED: _TypedRowSpec(
        row_cls=ModelSwitchedRow,
        details_cls=ModelSwitchedDetails,
        actor_type="agent",
        entity_id_key="to_model",
    ),
    HookEvent.PROMPT_ASSEMBLED: _TypedRowSpec(
        row_cls=PromptAssembledRow,
        details_cls=PromptAssembledDetails,
        actor_type="agent",
        entity_id_key="model",
    ),
    HookEvent.REASONING_METRICS: _TypedRowSpec(
        row_cls=ReasoningMetricsRow, details_cls=ReasoningMetricsDetails, actor_type="agent"
    ),
    HookEvent.MUTATION_PROPOSED: _TypedRowSpec(
        row_cls=MutationProposedRow,
        details_cls=MutationDetails,
        actor_type="system",
        entity_id_key="mutation_id",
    ),
    HookEvent.MUTATION_APPLIED: _TypedRowSpec(
        row_cls=MutationAppliedRow,
        details_cls=MutationDetails,
        actor_type="system",
        entity_id_key="mutation_id",
    ),
    HookEvent.MUTATION_REJECTED: _TypedRowSpec(
        row_cls=MutationRejectedRow,
        details_cls=MutationDetails,
        actor_type="system",
        entity_id_key="mutation_id",
    ),
    HookEvent.MUTATION_REVERTED: _TypedRowSpec(
        row_cls=MutationRevertedRow,
        details_cls=MutationDetails,
        actor_type="system",
        entity_id_key="mutation_id",
    ),
    HookEvent.SELF_IMPROVING_AUTO_TRIGGER: _TypedRowSpec(
        row_cls=AutoTriggerRow,
        details_cls=AutoTriggerDetails,
        actor_type="system",
        entity_id_key="trigger_id",
        level_derive=lambda data: AUTO_TRIGGER_STAGE_LEVELS.get(str(data.get("stage", ""))),
    ),
    HookEvent.SHUTDOWN_STARTED: _TypedRowSpec(
        row_cls=ShutdownStartedRow, details_cls=ShutdownStartedDetails, actor_type="system"
    ),
    HookEvent.TOOL_APPROVAL_REQUESTED: _TypedRowSpec(
        row_cls=ToolApprovalRequestedRow,
        details_cls=ToolApprovalDetails,
        actor_type="agent",
        entity_id_key="tool_name",
    ),
    HookEvent.APPROVAL_TRANSITION: _TypedRowSpec(
        row_cls=ApprovalTransitionRow,
        details_cls=ApprovalTransitionDetails,
        actor_type="agent",
        entity_id_key="tool_name",
    ),
    HookEvent.TOOL_RESULT_OFFLOADED: _TypedRowSpec(
        row_cls=ToolResultOffloadedRow,
        details_cls=ToolResultOffloadedDetails,
        actor_type="agent",
        entity_id_key="ref_id",
    ),
    HookEvent.TOOL_RESULT_TRANSFORM: _TypedRowSpec(
        row_cls=ToolResultTransformRow,
        details_cls=ToolResultTransformDetails,
        actor_type="agent",
        entity_id_key="tool_name",
    ),
    HookEvent.POST_ANALYSIS: _TypedRowSpec(
        row_cls=PostAnalysisRow,
        details_cls=PostAnalysisDetails,
        actor_type="orchestrator",
        entity_id_key="automation_id",
    ),
    HookEvent.PROGRAM_MD_UNREADABLE: _TypedRowSpec(
        row_cls=ProgramMdUnreadableRow,
        details_cls=ProgramMdUnreadableDetails,
        actor_type="system",
        entity_id_key="path",
    ),
    HookEvent.TRIGGER_FIRED: _TypedRowSpec(
        row_cls=TriggerFiredRow,
        details_cls=TriggerFiredDetails,
        actor_type="orchestrator",
        entity_id_key="trigger_id",
    ),
    HookEvent.USER_INPUT_RECEIVED: _TypedRowSpec(
        row_cls=UserInputReceivedRow,
        details_cls=UserInputReceivedDetails,
        actor_type="agent",
        entity_id_key="session_id",
        derive=_derive_input_len,
    ),
}


def _make_spec_builder(
    event: HookEvent, spec: _TypedRowSpec
) -> Callable[[dict[str, Any], str], ActivityRowBase]:
    """Bind one spec into a (data, run_id) builder for the registry. A
    factory (not an inline lambda) so the loop variable is captured by value,
    not by late-binding reference."""

    def _build(data: dict[str, Any], run_id: str) -> ActivityRowBase:
        return _build_from_spec(spec, event, data, run_id)

    return _build


for _ev, _spec in _TYPED_ROW_SPECS.items():
    HOOK_EVENT_TO_ROW_BUILDER[_ev] = _make_spec_builder(_ev, _spec)


# ---------------------------------------------------------------------------
# Top-level mapper used by the union channel wiring
# ---------------------------------------------------------------------------


def map_hook_to_activity(
    event: HookEvent,
    data: dict[str, Any] | None,
    *,
    run_id: str,
) -> ActivityRowBase:
    """Convert a ``HookEvent`` + ``data`` dict into a typed
    :class:`ActivityRowBase` subclass.

    All 56 events (see :data:`HOOK_EVENT_TO_ROW_BUILDER`) get full
    pydantic validation against their per-event details schema — a
    payload bug surfaces at dispatch time with a precise
    ``ValidationError`` instead of much later at the handler.

    Any builder failure (pydantic ``ValidationError`` from a malformed
    data dict, or a builder bug) falls through to
    :class:`GenericActivityRow` with a warning log + a ``_fallback_reason``
    on the row — the policy is "always emit a row so the timeline is
    complete, even when typing fails", which mirrors paperclip's
    ``logActivity`` swallow-and-warn contract. With full coverage, a
    GenericActivityRow in the timeline now signals a payload bug worth
    investigating, not a routine untyped event.
    """
    payload = data or {}
    builder = HOOK_EVENT_TO_ROW_BUILDER.get(event)
    if builder is not None:
        try:
            return builder(payload, run_id)
        except (ValidationError, ValueError, TypeError) as exc:
            # PR-COMM-1 fix-up (Codex MCP review M3): typed-row builders
            # do pre-pydantic coercion (``float()`` / ``int()`` /
            # ``str()``) before constructing the model, so malformed
            # *values* (e.g. ``{"duration_ms": "bad"}``) raise plain
            # ``ValueError`` / ``TypeError`` before pydantic's
            # ``ValidationError``. Catching all three preserves the
            # "always emit a row" contract — the timeline stays
            # complete even when an upstream caller sends garbage.
            log.warning(
                "ActivityRow builder for %s failed (%s); falling back to generic row: %s",
                event.value,
                type(exc).__name__,
                exc,
            )
            # PR-OBS-CONTRACT — a fallback row must be distinguishable
            # from an intentionally-generic row IN THE TIMELINE, not
            # only in the daemon log (silent-fallback anti-pattern). The
            # reason is value-free (see :func:`_safe_fallback_reason`) so a
            # ValidationError that echoes a raw field value never leaks it
            # into the persisted row (Codex MCP review BLOCKER #2).
            return _build_generic(
                event,
                {**payload, "_fallback_reason": _safe_fallback_reason(exc)},
                run_id=run_id,
            )
    return _build_generic(event, payload, run_id=run_id)


def _safe_fallback_reason(exc: Exception) -> str:
    """Describe WHY a typed builder failed without echoing any field VALUE.

    ``str(ValidationError)`` embeds ``input_value=...`` and a plain
    ``ValueError``/``TypeError`` message often embeds the offending value
    (``could not convert string to float: '<value>'``) — either would carry
    raw content into the persisted timeline row. So we record only the error
    type + field location for pydantic, and only the class name otherwise."""
    if isinstance(exc, ValidationError):
        locs = [
            f"{err.get('type', '?')}@{'.'.join(str(p) for p in err.get('loc', ()))}"
            for err in exc.errors(include_input=False, include_url=False)
        ]
        return f"ValidationError[{'; '.join(locs)}]"
    return type(exc).__name__


def _build_generic(
    event: HookEvent,
    data: dict[str, Any],
    *,
    run_id: str,
) -> GenericActivityRow:
    """Build the catch-all :class:`GenericActivityRow`. With 56/56
    coverage this is now ONLY reached when a typed builder fails on a
    malformed payload (carrying ``_fallback_reason``) or, defensively,
    for a future event added without a registry entry. The ``actor_type``
    is heuristic.

    The payload is scrubbed of raw-content keys first — the privacy
    contract the typed rows enforce must hold on this fail-soft path too,
    so a builder failure on a privacy-sensitive event does not leak raw
    ``user_input`` / ``cognitive_state`` / tool results into the JSONL."""
    safe_data = _scrub_for_timeline(data)
    dotted_action = event.value.replace("_", ".")
    actor_type = _infer_actor_type_from_event(event)
    actor_id = str(safe_data.get("session_id") or safe_data.get("actor_id") or actor_type)
    return GenericActivityRow(
        ts=time.time(),
        run_id=run_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=dotted_action,
        entity_type="system",
        entity_id=event.value,
        task_id=str(safe_data["task_id"]) if safe_data.get("task_id") else None,
        details=safe_data,
    )


def _infer_actor_type_from_event(event: HookEvent) -> str:
    """Best-effort actor classification for the generic fail-soft
    fallback row (a typed builder that hit a malformed payload). The
    primary typed path sets ``actor_type`` from the spec; this heuristic
    only applies when a row degrades to generic.
    """
    name = event.name
    if name.startswith("SESSION_"):
        return "orchestrator"
    if name.startswith(
        ("SUBAGENT_", "TURN_", "LLM_", "TOOL_", "COGNITIVE_", "MEMORY_", "RULE_", "PROMPT_")
    ):
        return "agent"
    if name.startswith(("MCP_", "CONFIG_", "SHUTDOWN_")):
        return "system"
    return "system"
