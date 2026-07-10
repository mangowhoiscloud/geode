"""Canonical HookSystem dispatch persistence and transcript mirroring."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from core.hooks.catalog import event_persistence_spec
from core.hooks.system import HookDispatch, HookEvent
from core.observability.event_store import (
    EventRetentionPolicy,
    HookEventStore,
    HookEventWrite,
    bound_event_payload,
)

log = logging.getLogger(__name__)


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
    active per-run transcript mirror as one atomic policy decision.
    """

    def __init__(
        self,
        store: HookEventStore,
        *,
        session_key: str,
        run_id: str,
        payload_policy: EventRetentionPolicy | None = None,
    ) -> None:
        self.store = store
        self.session_key = session_key
        self.run_id = run_id
        self._payload_policy = payload_policy or EventRetentionPolicy()

    def __call__(self, dispatch: HookDispatch) -> None:
        spec = event_persistence_spec(dispatch.event)
        if not spec.persist_sql and not spec.mirror_transcript:
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
            self.store.append(
                HookEventWrite(
                    occurred_at=activity.occurred_at,
                    session_key=self.session_key,
                    run_id=self.run_id,
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

        if spec.mirror_transcript:
            self._mirror_transcript(dispatch, activity, bounded_payload)

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
                # the active transcript.
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

    @staticmethod
    def _mirror_transcript(
        dispatch: HookDispatch,
        activity: _ActivityEnvelope,
        payload: dict[str, Any],
    ) -> None:
        from core.self_improving.loop.observe.run_transcript import current_run_transcript

        transcript = current_run_transcript()
        if transcript is None:
            return
        transcript.append(
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
