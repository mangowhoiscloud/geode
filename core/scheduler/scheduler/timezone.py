"""Active-hours and CRON timezone helpers."""

from __future__ import annotations

import logging
import time

from core.scheduler.triggers import CronParser

log = logging.getLogger(__name__)


def _parse_hhmm(s: str) -> int:
    """Parse "HH:MM" -> total minutes since midnight."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM format: '{s}'")
    return int(parts[0]) * 60 + int(parts[1])


def _now_minutes(timezone: str) -> int:
    """Current local time as minutes since midnight.

    When *timezone* is empty or not available, falls back to local time.
    Uses ``datetime`` if *zoneinfo* is available for tz-aware resolution.
    """
    if timezone:
        try:
            import datetime
            import zoneinfo

            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.datetime.now(tz=tz)
            return now.hour * 60 + now.minute
        except Exception:
            log.debug("Timezone '%s' unavailable, falling back to local", timezone)
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def _cron_tuple_for_tz(timezone: str) -> tuple[int, int, int, int, int]:
    """Get a cron-compatible tuple, optionally in a specific timezone.

    Returns weekday in standard cron convention: 0=Sun, 1=Mon, ..., 6=Sat.
    Python's ``datetime.weekday()`` uses 0=Mon, so we convert:
    ``(weekday() + 1) % 7``.
    """
    if timezone:
        try:
            import datetime
            import zoneinfo

            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.datetime.now(tz=tz)
            cron_wday = (now.weekday() + 1) % 7  # Python 0=Mon -> cron 0=Sun
            return (now.minute, now.hour, now.day, now.month, cron_wday)
        except Exception:  # noqa: S110 — fallback to CronParser.current_tuple() below
            pass
    return CronParser.current_tuple()
