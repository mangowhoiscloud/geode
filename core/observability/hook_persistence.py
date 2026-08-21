"""Canonical HookSystem dispatch persistence and run-event projection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from core.hooks.catalog import event_persistence_spec
from core.hooks.system import HookDispatch, HookEvent
from core.observability.event_store import (
    EventRetentionPolicy,
    HookEventStore,
    HookEventWrite,
    bound_event_payload,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.observability.run_event import RunEventSinkProvider


@dataclass(frozen=True, slots=True)
class _ActivityEnvelope:
    occurred_at: float
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    task_id: str | None
    level: str
    payload: dict[str, Any]


class HookPersistenceSink:
    """Write one sanitized operational row for each canonical dispatch.

    The sink is deliberately outside :mod:`core.hooks`: the event bus stays
    storage-agnostic, while production bootstrap opts into SQLite and the
    active per-run event projection as one policy decision.
    """

    def __init__(
        self,
        store: HookEventStore,
        *,
        session_key: str,
        run_id: str,
        payload_policy: EventRetentionPolicy | None = None,
        activity_sink_provider: RunEventSinkProvider | None = None,
    ) -> None:
        self.store = store
        self.session_key = session_key
        self.run_id = run_id
        self._payload_policy = payload_policy or EventRetentionPolicy()
        self._activity_sink_provider = activity_sink_provider

    def __call__(self, dispatch: HookDispatch) -> None:
        spec = event_persistence_spec(dispatch.event)
        if not spec.persist_sql and not spec.mirror_run_projection:
            return

        activity = self._map_activity(dispatch)
        failed_handlers = [result.handler_name for result in dispatch.results if not result.success]
        payload = {
            **activity.payload,
            "_dispatch_duration_ms": max(
                0.0,
                (dispatch.completed_at - dispatch.started_at) * 1_000,
            ),
        }
        if failed_handlers:
            payload["_failed_handlers"] = failed_handlers
        if dispatch.blocked:
            payload["_blocked_by"] = dispatch.blocked_by or "unknown"
        bounded_payload = bound_event_payload(payload, policy=self._payload_policy)

        error_count = len(failed_handlers)
        domain_failed = (
            dispatch.event.name.endswith(("FAILED", "ERROR"))
            or bool(dispatch.data.get("has_error"))
            or bool(dispatch.data.get("error"))
        )
        if dispatch.blocked:
            status = "blocked"
        elif domain_failed:
            status = "failed"
        elif error_count:
            status = "handler_error"
        else:
            status = "ok"
        if spec.persist_sql:
            live_session_id = str(dispatch.data.get("session_id") or "")
            live_turn_id = str(dispatch.data.get("turn_id") or "")
            step_id = str(dispatch.data.get("step_id") or "")
            tool_call_id = str(dispatch.data.get("tool_call_id") or "")
            llm_call_id = str(dispatch.data.get("llm_call_id") or "")
            llm_attempt_id = str(dispatch.data.get("llm_attempt_id") or "")
            self.store.append(
                HookEventWrite(
                    occurred_at=activity.occurred_at,
                    session_key=self.session_key,
                    run_id=self.run_id,
                    session_id=live_session_id,
                    turn_id=live_turn_id,
                    step_id=step_id,
                    tool_call_id=tool_call_id,
                    llm_call_id=llm_call_id,
                    llm_attempt_id=llm_attempt_id,
                    event=dispatch.event.value,
                    dispatch_mode=dispatch.mode.value,
                    status=status,
                    retention_class=spec.retention,
                    handler_count=len(dispatch.results),
                    handler_error_count=error_count,
                    blocked=dispatch.blocked,
                    block_reason=(
                        f"blocked_by:{dispatch.blocked_by or 'unknown'}" if dispatch.blocked else ""
                    ),
                    actor_type=activity.actor_type,
                    actor_id=activity.actor_id,
                    action=activity.action,
                    entity_type=activity.entity_type,
                    entity_id=activity.entity_id,
                    task_id=activity.task_id,
                    level=activity.level,
                    payload=bounded_payload,
                )
            )

        if spec.mirror_run_projection:
            self._mirror_run_projection(dispatch, activity, bounded_payload)

    def _map_activity(self, dispatch: HookDispatch) -> _ActivityEnvelope:
        try:
            from core.observability.activity_registry import map_hook_to_activity

            row = map_hook_to_activity(dispatch.event, dispatch.data, run_id=self.run_id)
            row_details = getattr(row, "details", None)
            if row_details is None:
                details: dict[str, Any] = {}
            elif hasattr(row_details, "model_dump"):
                dumped = row_details.model_dump()
                details = dumped if isinstance(dumped, dict) else {}
            elif isinstance(row_details, dict):
                details = row_details
            else:
                details = {"_omitted_details_type": type(row_details).__name__}
            for key in (
                "session_id",
                "turn_id",
                "step_id",
                "tool_call_id",
                "llm_call_id",
                "llm_attempt_id",
            ):
                value = dispatch.data.get(key)
                if isinstance(value, str) and value:
                    details[key] = value
            for key in ("session_generation", "verify_attempt"):
                value = dispatch.data.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    details[key] = value
            if type(row).__name__ == "GenericActivityRow":
                # A future/untyped event must not turn its arbitrary source
                # payload into durable storage. Preserve only value-free
                # diagnostics and derived size metadata.
                details = {
                    key: details[key] for key in ("_fallback_reason", "input_len") if key in details
                }
                details["_generic_projection"] = True
            entity_id = str(row.entity_id)
            if dispatch.event is HookEvent.RESULT_FEEDBACK:
                # ``subject`` is model/user supplied and may be a sentence or
                # pasted result rather than an opaque id. Keep per-run
                # correlation without storing the raw value in either SQL or
                # the active run projection.
                entity_id = self._opaque_entity_id("result", entity_id)
            return _ActivityEnvelope(
                occurred_at=float(row.ts),
                actor_type=str(row.actor_type),
                actor_id=str(row.actor_id),
                action=str(row.action),
                entity_type=str(row.entity_type),
                entity_id=entity_id,
                task_id=str(row.task_id) if row.task_id is not None else None,
                level=str(row.level),
                payload=details,
            )
        except Exception as exc:
            log.warning(
                "Hook activity mapping failed for %s; storing minimal envelope: %s",
                dispatch.event.value,
                type(exc).__name__,
            )
            return _ActivityEnvelope(
                occurred_at=dispatch.completed_at,
                actor_type="system",
                actor_id="hook_system",
                action=f"hook.{dispatch.event.value}",
                entity_type="hook_event",
                entity_id=dispatch.event.value,
                task_id=None,
                level="error" if any(not result.success for result in dispatch.results) else "info",
                payload={"_mapping_error_type": type(exc).__name__},
            )

    def _opaque_entity_id(self, namespace: str, value: str) -> str:
        digest = sha256(f"{self.run_id}\0{value}".encode()).hexdigest()[:24]
        return f"{namespace}:{digest}"

    def _mirror_run_projection(
        self,
        dispatch: HookDispatch,
        activity: _ActivityEnvelope,
        payload: dict[str, Any],
    ) -> None:
        timeline = self._activity_sink_provider() if self._activity_sink_provider else None
        if timeline is None:
            return
        timeline.append(
            event=dispatch.event.value,
            ts=activity.occurred_at,
            actor_type=activity.actor_type,
            actor_id=activity.actor_id,
            action=activity.action,
            entity_type=activity.entity_type,
            entity_id=activity.entity_id,
            task_id=activity.task_id,
            level=activity.level,
            payload=payload,
        )

    def close(self) -> None:
        self.store.close()


__all__ = ["HookPersistenceSink"]
