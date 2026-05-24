"""ScheduledJob ↔ dict serialisation helpers (callbacks excluded)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.scheduler.models import (
    ActiveHours,
    Schedule,
    ScheduledJob,
    ScheduleKind,
)


def _job_to_dict(job: ScheduledJob) -> dict[str, Any]:
    """Serialize a ScheduledJob to a JSON-safe dict (excludes callback)."""
    return {
        "job_id": job.job_id,
        "name": job.name,
        "schedule": {
            "kind": job.schedule.kind.value,
            "at_ms": job.schedule.at_ms,
            "every_ms": job.schedule.every_ms,
            "anchor_ms": job.schedule.anchor_ms,
            "cron_expr": job.schedule.cron_expr,
            "timezone": job.schedule.timezone,
        },
        "enabled": job.enabled,
        "delete_after_run": job.delete_after_run,
        "durable": job.durable,
        "permanent": job.permanent,
        "agent_id": job.agent_id,
        "action": job.action,
        "isolated": job.isolated,
        "active_hours": (asdict(job.active_hours) if job.active_hours is not None else None),
        "metadata": job.metadata,
        "created_at_ms": job.created_at_ms,
        "next_run_at_ms": job.next_run_at_ms,
        "last_run_at_ms": job.last_run_at_ms,
        "last_status": job.last_status,
        "last_duration_ms": job.last_duration_ms,
        "running_since_ms": job.running_since_ms,
    }


def _job_from_dict(data: dict[str, Any]) -> ScheduledJob:
    """Deserialize a dict into a ScheduledJob (callback will be None)."""
    sched_data = data["schedule"]
    schedule = Schedule(
        kind=ScheduleKind(sched_data["kind"]),
        at_ms=sched_data.get("at_ms", 0.0),
        every_ms=sched_data.get("every_ms", 0.0),
        anchor_ms=sched_data.get("anchor_ms", 0.0),
        cron_expr=sched_data.get("cron_expr", ""),
        timezone=sched_data.get("timezone", ""),
    )
    ah_data = data.get("active_hours")
    active_hours = ActiveHours(**ah_data) if ah_data is not None else None

    return ScheduledJob(
        job_id=data["job_id"],
        name=data["name"],
        schedule=schedule,
        enabled=data.get("enabled", True),
        delete_after_run=data.get("delete_after_run", False),
        durable=data.get("durable", True),
        permanent=data.get("permanent", False),
        agent_id=data.get("agent_id", ""),
        callback=None,  # Callbacks are not serialised
        action=data.get("action", ""),
        isolated=data.get("isolated", True),
        active_hours=active_hours,
        metadata=data.get("metadata", {}),
        created_at_ms=data.get("created_at_ms", 0.0),
        next_run_at_ms=data.get("next_run_at_ms"),
        last_run_at_ms=data.get("last_run_at_ms"),
        last_status=data.get("last_status", ""),
        last_duration_ms=data.get("last_duration_ms", 0.0),
        running_since_ms=data.get("running_since_ms"),
    )
