"""Execution-related tool handlers: schedule_job, trigger_event.

Data-only: no console output, so quiet/isolated sessions stay clean. Every
mutation goes through the SchedulerService durable commands; a request that
cannot be carried out returns an error and never falls back to a listing.
"""

from __future__ import annotations

import logging
from typing import Any

from core.tools.handlers.clarification import _clarify
from core.tools.handlers.registration import UniqueEntries

log = logging.getLogger(__name__)

_SCHEDULE_ACTIONS = frozenset({"list", "status", "create", "delete", "enable", "disable", "run"})
_TARGETED_ACTIONS = frozenset({"delete", "enable", "disable", "run"})
_TRIGGER_ACTIONS = frozenset({"list", "fire"})


def _error(action: str, sub_action: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "error",
        "action": action,
        "sub_action": sub_action,
        "error": message,
        **extra,
    }


def _job_summary(job: Any) -> dict[str, Any]:
    return {
        "id": job.job_id,
        "name": job.name,
        "enabled": job.enabled,
        "action": job.action[:60] if job.action else "",
        "last_status": job.last_status,
        "running": job.running_since_ms is not None,
    }


def _build_execution_handlers(scheduler_service: Any = None) -> UniqueEntries[str, Any]:
    """Build execution-related tool handlers."""
    svc = scheduler_service

    def handle_schedule_job(**kwargs: Any) -> dict[str, Any]:
        sub_action = str(kwargs.get("sub_action") or "list")
        target_id = str(kwargs.get("target_id") or "").strip()
        expression = str(kwargs.get("expression") or "").strip()
        action_text = str(kwargs.get("action") or "").strip()

        if sub_action not in _SCHEDULE_ACTIONS:
            return _error(
                "schedule",
                sub_action,
                f"Unknown sub_action '{sub_action}'; expected one of {sorted(_SCHEDULE_ACTIONS)}",
            )
        if sub_action == "create":
            missing = [
                k for k, v in {"expression": expression, "action": action_text}.items() if not v
            ]
            if missing:
                return _clarify(
                    "schedule_job",
                    missing,
                    "Specify WHEN (expression) and WHAT to run when it fires (action).",
                )
        if sub_action in _TARGETED_ACTIONS and not target_id:
            return _clarify("schedule_job", ["target_id"], "Which job ID?")
        if svc is None:
            return _error("schedule", sub_action, "Scheduler not available")

        try:
            if sub_action == "create":
                from core.scheduler.nl_scheduler import NLScheduleParser

                parsed = NLScheduleParser().parse(expression)
                if not parsed.success or not parsed.job:
                    return _error("schedule", "create", parsed.error or "parse failed")
                job = parsed.job
                job.action = action_text
                svc.create_job(job)
                return {
                    "status": "ok",
                    "action": "schedule",
                    "sub_action": "create",
                    "job_id": job.job_id,
                    "schedule_kind": (parsed.inferred_kind.value if parsed.inferred_kind else ""),
                    "expression": expression,
                    "job_action": action_text,
                }
            if sub_action in ("enable", "disable"):
                found = svc.set_job_enabled(target_id, sub_action == "enable")
            elif sub_action == "delete":
                found = svc.delete_job(target_id)
            elif sub_action == "run":
                run = svc.run_now(target_id)
                status = run.get("status", "error")
                if status in ("error", "skipped"):
                    return _error(
                        "schedule",
                        "run",
                        run.get("error") or run.get("reason") or "run failed",
                        target_id=target_id,
                        run_status=status,
                    )
                return {
                    "status": "ok",
                    "action": "schedule",
                    "sub_action": "run",
                    "target_id": target_id,
                    # "dispatched": queued for a session; the outcome lands later.
                    "run_status": status,
                    "run_id": run.get("run_id", ""),
                }
            else:  # list / status
                if target_id:
                    job = svc.get_job(target_id)
                    if job is None:
                        return _error(
                            "schedule",
                            sub_action,
                            f"Job not found: {target_id}",
                            target_id=target_id,
                        )
                    return {
                        "status": "ok",
                        "action": "schedule",
                        "sub_action": sub_action,
                        "job": _job_summary(job),
                    }
                return {
                    "status": "ok",
                    "action": "schedule",
                    "sub_action": sub_action,
                    "jobs": [_job_summary(j) for j in svc.list_jobs(include_disabled=True)],
                }
        except KeyError:
            return _error(
                "schedule", sub_action, f"Job not found: {target_id}", target_id=target_id
            )
        except Exception as exc:
            return _error("schedule", sub_action, str(exc), target_id=target_id)

        if not found:
            return _error(
                "schedule", sub_action, f"Job not found: {target_id}", target_id=target_id
            )
        return {
            "status": "ok",
            "action": "schedule",
            "sub_action": sub_action,
            "target_id": target_id,
        }

    def handle_trigger_event(**kwargs: Any) -> dict[str, Any]:
        sub_action = str(kwargs.get("sub_action") or "list")
        event_name = str(kwargs.get("event_name") or "").strip()

        if sub_action not in _TRIGGER_ACTIONS:
            return _error(
                "trigger",
                sub_action,
                f"Unknown sub_action '{sub_action}'; expected one of {sorted(_TRIGGER_ACTIONS)}",
            )
        if sub_action == "fire" and not event_name:
            return _clarify("trigger_event", ["event_name"], "Which trigger ID should fire?")
        manager = getattr(svc, "trigger_manager", None)
        if manager is None:
            return _error("trigger", sub_action, "Trigger manager not available")
        if sub_action == "list":
            return {
                "status": "ok",
                "action": "trigger",
                "sub_action": "list",
                "triggers": manager.inventory(),
                "stats": manager.stats.to_dict(),
            }
        try:
            result = manager.fire_manual(event_name)
        except KeyError:
            return _error(
                "trigger", "fire", f"Unknown trigger: {event_name}", event_name=event_name
            )
        if not result.success:
            return _error("trigger", "fire", result.error, event_name=event_name)
        return {
            "status": "ok",
            "action": "trigger",
            "sub_action": "fire",
            "event_name": event_name,
            "trigger_type": result.trigger_type.value,
            "executed_at": result.executed_at,
        }

    return UniqueEntries[str, Any](
        (
            ("schedule_job", handle_schedule_job),
            ("trigger_event", handle_trigger_event),
        )
    )
