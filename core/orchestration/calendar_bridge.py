"""Calendar ↔ Scheduler Bridge — bidirectional sync between GEODE scheduler and external calendars.

Push: ScheduledJob → [GEODE]-prefixed calendar event
Pull: [GEODE]-prefixed calendar event → ScheduledJob

Registers with TRIGGER_FIRED hook for automatic sync after scheduler runs.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

GEODE_PREFIX = "[GEODE] "


class CalendarSchedulerBridge:
    """Bidirectional sync between SchedulerService and CalendarPort."""

    def __init__(
        self,
        scheduler: Any,  # SchedulerService
        calendar: Any,  # CalendarPort
    ) -> None:
        self._scheduler = scheduler
        self._calendar = calendar

    def sync(self, *, direction: str = "both") -> dict[str, Any]:
        """Run sync in specified direction.

        Args:
            direction: "push", "pull", or "both".

        Returns:
            Summary dict with pushed/pulled counts.
        """
        result: dict[str, Any] = {"pushed": 0, "pulled": 0, "errors": []}

        if direction in ("push", "both"):
            pushed, errors = self._push_to_calendar()
            result["pushed"] = pushed
            result["errors"].extend(errors)

        if direction in ("pull", "both"):
            pulled, errors = self._pull_from_calendar()
            result["pulled"] = pulled
            result["errors"].extend(errors)

        return result

    def _push_to_calendar(self) -> tuple[int, list[str]]:
        """Push scheduler jobs as [GEODE]-prefixed calendar events."""
        pushed = 0
        errors: list[str] = []

        if not self._calendar.is_available():
            return 0, ["Calendar adapter not available"]

        try:
            jobs = self._scheduler.list_jobs()
        except Exception as exc:
            return 0, [f"Failed to list scheduler jobs: {exc}"]

        # Get existing GEODE events to avoid duplicates
        existing_titles: set[str] = set()
        try:
            events = self._calendar.list_events(
                start=datetime.now(UTC),
                end=datetime.now(UTC) + timedelta(days=30),
                max_results=100,
            )
            existing_titles = {e.title for e in events if e.is_geode}
        except Exception as exc:
            log.debug("Failed to fetch existing events: %s", exc)

        for job in jobs:
            if not job.enabled:
                continue
            title = f"{GEODE_PREFIX}{job.name}"
            if title in existing_titles:
                continue

            # Determine event time from next_run_at_ms
            if job.next_run_at_ms:
                start = datetime.fromtimestamp(
                    job.next_run_at_ms / 1000, tz=UTC
                )
            else:
                start = datetime.now(UTC) + timedelta(hours=1)

            end = start + timedelta(minutes=30)

            try:
                self._calendar.create_event(
                    title,
                    start,
                    end,
                    description=(
                        f"GEODE scheduled job: {job.job_id}\n"
                        f"Schedule: {job.schedule.kind.value}"
                    ),
                )
                pushed += 1
            except Exception as exc:
                errors.append(f"Failed to push job '{job.name}': {exc}")

        return pushed, errors

    def _pull_from_calendar(self) -> tuple[int, list[str]]:
        """Pull [GEODE]-prefixed calendar events as scheduler jobs."""
        pulled = 0
        errors: list[str] = []

        if not self._calendar.is_available():
            return 0, ["Calendar adapter not available"]

        try:
            events = self._calendar.list_events(
                start=datetime.now(UTC),
                end=datetime.now(UTC) + timedelta(days=30),
                max_results=100,
            )
        except Exception as exc:
            return 0, [f"Failed to list calendar events: {exc}"]

        # Get existing job names to avoid duplicates
        existing_names: set[str] = set()
        try:
            for job in self._scheduler.list_jobs():
                existing_names.add(job.name)
        except Exception as exc:
            log.debug("Failed to list existing jobs: %s", exc)
            pass

        for event in events:
            if not event.is_geode:
                continue
            # Strip [GEODE] prefix to get job name
            job_name = event.title[len(GEODE_PREFIX):].strip()
            if not job_name or job_name in existing_names:
                continue

            try:
                at_ms = event.start.timestamp() * 1000
                self._scheduler.add_job(
                    name=job_name,
                    schedule_kind="at",
                    at_ms=at_ms,
                    metadata={"source": "calendar", "event_id": event.event_id},
                )
                pulled += 1
            except Exception as exc:
                errors.append(f"Failed to pull event '{event.title}': {exc}")

        return pulled, errors


# ---------------------------------------------------------------------------
# contextvars injection
# ---------------------------------------------------------------------------

_bridge_ctx: ContextVar[CalendarSchedulerBridge | None] = ContextVar(
    "calendar_bridge", default=None
)


def set_calendar_bridge(bridge: CalendarSchedulerBridge | None) -> None:
    """Set the active calendar bridge for the current context."""
    _bridge_ctx.set(bridge)


def get_calendar_bridge() -> CalendarSchedulerBridge | None:
    """Get the active calendar bridge, or None if not set."""
    return _bridge_ctx.get()
