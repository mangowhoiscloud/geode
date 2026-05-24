"""HookEvent → ActivityRow mapping registry.

Spec: ``docs/plans/2026-05-24-hookevent-activity-schema.md`` §3.

Each of the 32 lifecycle events maps to a builder that produces the
appropriate concrete ``ActivityRow`` subclass with validated payload.
The 42 non-lifecycle events fall through to
:class:`GenericActivityRow` so they still land in the timeline — but
without the type-safety + IDE autocomplete benefit. Subsequent PRs
(E-K group concretes) will move events out of the fall-through.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from core.hooks.system import HookEvent
from core.observability.activity import (
    ActivityRowBase,
    AnalystCompletedRow,
    EvaluatorCompletedRow,
    GenericActivityRow,
    HandoffCompletedRow,
    HandoffFailedRow,
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
    NodeBootstrapRow,
    NodeEnteredRow,
    NodeErrorRow,
    NodeExitedRow,
    PipelineEndedRow,
    PipelineErrorRow,
    PipelineStartedRow,
    PipelineTimeoutRow,
    ScoringCompletedRow,
    SessionEndedRow,
    SessionStartedRow,
    SubAgentCompletedRow,
    SubAgentFailedRow,
    SubAgentStartedRow,
    ToolExecEndedRow,
    ToolExecFailedRow,
    ToolExecStartedRow,
    ToolRecoveryAttemptedRow,
    ToolRecoveryFailedRow,
    ToolRecoverySucceededRow,
    TurnCompletedRow,
    TurnVerifyFailedRow,
    TurnVerifyPassedRow,
)

log = logging.getLogger(__name__)

__all__ = ["map_hook_to_activity"]


# ---------------------------------------------------------------------------
# Per-event row builders (32 lifecycle events typed in S2 scope)
# ---------------------------------------------------------------------------


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
# 32 lifecycle event → builder mapping
# ---------------------------------------------------------------------------


HOOK_EVENT_TO_ROW_BUILDER: dict[HookEvent, Callable[[dict[str, Any], str], ActivityRowBase]] = {
    # A — lifecycle started (9)
    HookEvent.PIPELINE_STARTED: _lifecycle_started(
        PipelineStartedRow, actor_type_default="orchestrator", actor_key="pipeline_id"
    ),
    HookEvent.NODE_BOOTSTRAP: _lifecycle_started(
        NodeBootstrapRow, actor_type_default="orchestrator", actor_key="node"
    ),
    HookEvent.NODE_ENTERED: _lifecycle_started(
        NodeEnteredRow, actor_type_default="orchestrator", actor_key="node"
    ),
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
    # B — lifecycle completed (13)
    HookEvent.PIPELINE_ENDED: _lifecycle_completed(
        PipelineEndedRow, actor_type_default="orchestrator", actor_key="pipeline_id"
    ),
    HookEvent.NODE_EXITED: _lifecycle_completed(
        NodeExitedRow, actor_type_default="orchestrator", actor_key="node"
    ),
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
    HookEvent.HANDOFF_COMPLETED: _lifecycle_completed(
        HandoffCompletedRow, actor_type_default="orchestrator", identifier_key="handoff_id"
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
    HookEvent.ANALYST_COMPLETED: _lifecycle_completed(
        AnalystCompletedRow, actor_type_default="agent", identifier_key="analyst_id"
    ),
    HookEvent.EVALUATOR_COMPLETED: _lifecycle_completed(
        EvaluatorCompletedRow, actor_type_default="agent", identifier_key="evaluator_id"
    ),
    HookEvent.SCORING_COMPLETED: _lifecycle_completed(
        ScoringCompletedRow, actor_type_default="agent", identifier_key="scoring_id"
    ),
    # C — lifecycle failed (9)
    HookEvent.PIPELINE_ERROR: _lifecycle_failed(
        PipelineErrorRow, actor_type_default="orchestrator", actor_key="pipeline_id"
    ),
    HookEvent.PIPELINE_TIMEOUT: _lifecycle_failed(
        PipelineTimeoutRow, actor_type_default="orchestrator", actor_key="pipeline_id"
    ),
    HookEvent.NODE_ERROR: _lifecycle_failed(
        NodeErrorRow, actor_type_default="orchestrator", actor_key="node"
    ),
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
    HookEvent.HANDOFF_FAILED: _lifecycle_failed(
        HandoffFailedRow, actor_type_default="orchestrator", identifier_key="handoff_id"
    ),
    HookEvent.TURN_VERIFY_FAILED: _lifecycle_failed(
        TurnVerifyFailedRow, actor_type_default="agent", identifier_key="turn_id"
    ),
    # D — retry (1)
    HookEvent.LLM_CALL_RETRIED: _lifecycle_retried(LLMCallRetriedRow, actor_type_default="agent"),
}


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

    Lifecycle events (32, see :data:`HOOK_EVENT_TO_ROW_BUILDER`) get
    full pydantic validation against their per-event details schema —
    a payload bug surfaces at dispatch time with a precise
    ``ValidationError`` instead of much later at the handler. The 43
    non-lifecycle events fall through to :class:`GenericActivityRow`
    which keeps the timeline complete without forcing schema work
    upfront; subsequent PRs will tighten high-volume events.

    Any builder failure (pydantic ``ValidationError`` from a malformed
    data dict, or a builder bug) also falls through to
    :class:`GenericActivityRow` with a warning log — the policy is
    "always emit a row so the timeline is complete, even when typing
    fails", which mirrors paperclip's ``logActivity`` swallow-and-warn
    contract.
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
    return _build_generic(event, payload, run_id=run_id)


def _build_generic(
    event: HookEvent,
    data: dict[str, Any],
    *,
    run_id: str,
) -> GenericActivityRow:
    """Build the catch-all :class:`GenericActivityRow` for any event
    without a registry entry (or whose typed builder failed). The
    ``actor_type`` is heuristic — operators should treat
    ``GenericActivityRow`` rows as candidates for promotion to a
    typed subclass in a future PR."""
    dotted_action = event.value.replace("_", ".")
    actor_type = _infer_actor_type_from_event(event)
    actor_id = str(data.get("session_id") or data.get("actor_id") or actor_type)
    return GenericActivityRow(
        ts=time.time(),
        run_id=run_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=dotted_action,
        entity_type="system",
        entity_id=event.value,
        task_id=str(data["task_id"]) if data.get("task_id") else None,
        details=data,
    )


def _infer_actor_type_from_event(event: HookEvent) -> str:
    """Best-effort actor classification for the generic fall-through.

    The 42 non-lifecycle events span four actor types — pre-typing the
    fall-through helps operators filter the timeline by ``actor_type``
    without waiting for the per-event concrete class. ``GenericActivityRow``
    rows should still be considered "untyped" — promoting them to a
    concrete class is the path to strict validation.
    """
    name = event.name
    if name.startswith(("PIPELINE_", "NODE_", "SESSION_")):
        return "orchestrator"
    if name.startswith(
        ("SUBAGENT_", "TURN_", "LLM_", "TOOL_", "COGNITIVE_", "MEMORY_", "RULE_", "PROMPT_")
    ):
        return "agent"
    if name.startswith(("MCP_", "CONFIG_", "SHUTDOWN_")):
        return "system"
    return "system"
