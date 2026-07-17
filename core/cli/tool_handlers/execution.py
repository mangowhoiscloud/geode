"""Execution-related tool handlers: schedule_job, trigger_event."""

from __future__ import annotations

import logging
from typing import Any

from core.cli.tool_handlers.registration import UniqueEntries
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_execution_handlers() -> UniqueEntries[str, Any]:
    """Build execution-related tool handlers."""
    from core.cli import _scheduler_service_ctx
    from core.cli.commands import cmd_trigger

    def handle_schedule_job(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        target_id = kwargs.get("target_id", "")
        expression = kwargs.get("expression", "")
        action_text = kwargs.get("action", "")
        svc = _scheduler_service_ctx.get(None)

        if sub_action == "create" and expression:
            if not action_text:
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": "action parameter is required for create. "
                    "Specify what to do when the schedule fires.",
                }
            if not svc:
                return {"status": "error", "action": "schedule", "error": "Scheduler not available"}
            try:
                from core.scheduler.nl_scheduler import NLScheduleParser

                result = NLScheduleParser().parse(expression)
                if not result.success or not result.job:
                    return {
                        "status": "error",
                        "action": "schedule",
                        "sub_action": "create",
                        "error": result.error or "parse failed",
                    }
                job = result.job
                job.action = action_text
                svc.add_job(job)
                svc.save()
                from core.cli.commands.schedule import _format_schedule_desc

                console.print(f"  [success]Created: {job.job_id}[/success]")
                console.print(f"  Schedule: {_format_schedule_desc(job)}")
                if action_text:
                    console.print(f"  Action: {action_text[:80]}")
                console.print()
                return {
                    "status": "ok",
                    "action": "schedule",
                    "sub_action": "create",
                    "job_id": job.job_id,
                    "schedule_kind": (result.inferred_kind.value if result.inferred_kind else ""),
                    "expression": expression,
                    "job_action": action_text,
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "action": "schedule",
                    "sub_action": "create",
                    "error": str(exc),
                }

        # Data-only: no cmd_schedule() call — avoids console.print in quiet/isolated sessions.
        # enable/disable/delete/run handled directly via SchedulerService.
        if sub_action in ("enable", "disable") and target_id and svc:
            new_state = sub_action == "enable"
            updated = svc.update_job(target_id, enabled=new_state)
            if updated:
                svc.save()
            return {
                "status": "ok" if updated else "error",
                "action": "schedule",
                "sub_action": sub_action,
                "target_id": target_id,
                "error": "" if updated else f"Job not found: {target_id}",
            }

        if sub_action == "delete" and target_id and svc:
            removed = svc.remove_job(target_id)
            if removed:
                svc.save()
            return {
                "status": "ok" if removed else "error",
                "action": "schedule",
                "sub_action": "delete",
                "target_id": target_id,
                "error": "" if removed else f"Job not found: {target_id}",
            }

        if sub_action == "run" and target_id and svc:
            result = svc.run_now(target_id)
            return {
                "status": result.get("status", "ok"),
                "action": "schedule",
                "sub_action": "run",
                "target_id": target_id,
                "error": result.get("error", ""),
            }

        # list / status — return structured data
        try:
            from core.scheduler.predefined import PREDEFINED_AUTOMATIONS

            templates = [
                {"id": t.id, "name": t.name, "enabled": t.enabled} for t in PREDEFINED_AUTOMATIONS
            ]
        except Exception:
            templates = []
        result_dict: dict[str, Any] = {
            "status": "ok",
            "action": "schedule",
            "sub_action": sub_action,
            "templates": templates[:10],
        }
        if svc is not None:
            try:
                dynamic = [
                    {
                        "id": j.job_id,
                        "name": j.name,
                        "enabled": j.enabled,
                        "action": j.action[:60] if j.action else "",
                    }
                    for j in svc.list_jobs(include_disabled=True)
                    if not j.job_id.startswith("predefined:")
                ]
                result_dict["dynamic_jobs"] = dynamic
            except Exception:
                log.debug("Failed to list dynamic jobs", exc_info=True)
        return result_dict

    def handle_trigger_event(**kwargs: Any) -> dict[str, Any]:
        sub_action = kwargs.get("sub_action", "") or "list"
        event_name = kwargs.get("event_name", "")
        trigger_args = f"{sub_action} {event_name}".strip() if sub_action else ""
        cmd_trigger(trigger_args)
        return {
            "status": "ok",
            "action": "trigger",
            "sub_action": sub_action,
            "event_name": event_name,
        }

    return UniqueEntries[str, Any](
        (
            ("schedule_job", handle_schedule_job),
            ("trigger_event", handle_trigger_event),
        )
    )
