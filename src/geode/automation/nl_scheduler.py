"""Natural Language -> Structured Job converter for the Scheduler.

Parses human-readable scheduling descriptions into ``ScheduledJob`` objects
using pure rule-based pattern matching (no LLM calls).  Inspired by
OpenClaw's cron-tool NL layer that normalizes incomplete or ambiguous input
into structured scheduling data.

Architecture-v6 SS4.5: Automation Layer -- NL Scheduler (P6).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass

from geode.automation.scheduler import (
    ActiveHours,
    Schedule,
    ScheduledJob,
    ScheduleKind,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parse result
# ---------------------------------------------------------------------------


@dataclass
class ParseResult:
    """Result of parsing a natural language scheduling description."""

    success: bool
    job: ScheduledJob | None = None
    error: str | None = None
    inferred_kind: ScheduleKind | None = None
    original_text: str = ""
    normalized_text: str = ""


# ---------------------------------------------------------------------------
# Duration / time unit constants
# ---------------------------------------------------------------------------

_UNIT_TO_MS: dict[str, float] = {
    "s": 1_000,
    "sec": 1_000,
    "second": 1_000,
    "seconds": 1_000,
    "m": 60_000,
    "min": 60_000,
    "mins": 60_000,
    "minute": 60_000,
    "minutes": 60_000,
    "h": 3_600_000,
    "hr": 3_600_000,
    "hrs": 3_600_000,
    "hour": 3_600_000,
    "hours": 3_600_000,
    "d": 86_400_000,
    "day": 86_400_000,
    "days": 86_400_000,
}

_DURATION_RE = re.compile(
    r"(\d+)\s*(s|sec|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\b",
    re.IGNORECASE,
)

_DAY_MAP: dict[str, int] = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
    "sun": 0,
}

# Active-hours patterns
_ACTIVE_HOURS_24H_RE = re.compile(
    r"(?:during|between)\s+(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})",
    re.IGNORECASE,
)

_ACTIVE_HOURS_AMPM_RE = re.compile(
    r"(?:during|between)\s+(\d{1,2})\s*(am|pm)\s*[-–]\s*(\d{1,2})\s*(am|pm)",
    re.IGNORECASE,
)

# Time patterns
_TIME_24H_RE = re.compile(r"at\s+(\d{1,2}):(\d{2})", re.IGNORECASE)
_TIME_AMPM_RE = re.compile(r"at\s+(\d{1,2})\s*(am|pm)", re.IGNORECASE)

# Relative time: "in 30 minutes"
_RELATIVE_RE = re.compile(
    r"in\s+(\d+)\s*(s|sec|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\b",
    re.IGNORECASE,
)

# Job name: "run <name> every ..." or "<name> every ..."
_RUN_NAME_RE = re.compile(
    r"^run\s+([\w_]+)\s+",
    re.IGNORECASE,
)
_VERB_NAME_RE = re.compile(
    r"^([\w_]+)\s+([\w_]+)\s+",
    re.IGNORECASE,
)

# Stop-words to exclude from auto-generated names
_STOP_WORDS = frozenset(
    {
        "every",
        "at",
        "in",
        "on",
        "the",
        "a",
        "an",
        "once",
        "run",
        "during",
        "between",
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "weekday",
        "weekdays",
        "and",
        "or",
        "from",
        "to",
    }
)


# ---------------------------------------------------------------------------
# NLJobNormalizer
# ---------------------------------------------------------------------------


class NLJobNormalizer:
    """Normalize incomplete or malformed job specifications.

    Fixes common issues:
    - Duration string normalization: ``"5min"`` -> ``"5 minutes"``
    - Timezone abbreviation to IANA: ``"KST"`` -> ``"Asia/Seoul"``
    - Invalid cron expressions: attempts correction
    """

    TIMEZONE_MAP: dict[str, str] = {
        "KST": "Asia/Seoul",
        "JST": "Asia/Tokyo",
        "PST": "America/Los_Angeles",
        "EST": "America/New_York",
        "CST": "America/Chicago",
        "MST": "America/Denver",
        "UTC": "UTC",
        "GMT": "UTC",
    }

    _DURATION_ABBREV_RE = re.compile(
        r"(\d+)(s|sec|m|min|mins|h|hr|hrs|d)\b",
        re.IGNORECASE,
    )

    _ABBREV_EXPAND: dict[str, str] = {
        "s": "seconds",
        "sec": "seconds",
        "m": "minutes",
        "min": "minutes",
        "mins": "minutes",
        "h": "hours",
        "hr": "hours",
        "hrs": "hours",
        "d": "days",
    }

    @classmethod
    def normalize_timezone(cls, tz: str) -> str:
        """Map a timezone abbreviation to its IANA name.

        Unknown abbreviations are returned as-is (passthrough).
        """
        return cls.TIMEZONE_MAP.get(tz.upper().strip(), tz)

    @classmethod
    def normalize_duration(cls, text: str) -> str:
        """Expand compressed duration strings.

        ``"5min"`` -> ``"5 minutes"``, ``"2hr"`` -> ``"2 hours"``.
        """

        def _expand(m: re.Match[str]) -> str:
            num = m.group(1)
            unit = m.group(2).lower()
            expanded = cls._ABBREV_EXPAND.get(unit, unit)
            return f"{num} {expanded}"

        return cls._DURATION_ABBREV_RE.sub(_expand, text)

    @classmethod
    def normalize_cron(cls, expr: str) -> str | None:
        """Validate / fix a cron expression.

        Returns the cleaned expression or ``None`` if unrecoverable.
        """
        parts = expr.strip().split()
        if len(parts) == 5:
            return expr.strip()
        # Common mistake: 6-field (with seconds) -- drop the first field
        if len(parts) == 6:
            return " ".join(parts[1:])
        return None


# ---------------------------------------------------------------------------
# NLScheduleParser
# ---------------------------------------------------------------------------


class NLScheduleParser:
    """Parse natural language scheduling descriptions into ``ScheduledJob``.

    Supported patterns:

    - Duration intervals: ``"every 5 minutes"``, ``"every 2 hours"``,
      ``"every 30s"``
    - Cron-like: ``"daily at 9:00"``, ``"weekly on monday"``, ``"hourly"``,
      ``"every weekday at 14:00"``
    - One-shot: ``"at 2024-03-15 14:00"``, ``"in 30 minutes"``,
      ``"once at 15:00"``
    - Active hours: ``"every 5m during 09:00-22:00"``,
      ``"hourly between 8am-6pm"``
    - Job naming: ``"run analysis every 5m"`` -> name=``"analysis"``

    Usage::

        parser = NLScheduleParser()
        result = parser.parse("every 5 minutes during 09:00-22:00")
        if result.success:
            scheduler.add_job(result.job)
    """

    def parse(self, text: str, *, agent_id: str = "") -> ParseResult:
        """Parse *text* into a ``ParseResult`` containing a ``ScheduledJob``."""
        original = text
        if not text or not text.strip():
            return ParseResult(
                success=False,
                error="empty input",
                original_text=original,
                normalized_text="",
            )

        normalized = self._normalize(text)

        # Extract components (order matters: active hours before schedule)
        remaining, active_hours = self._extract_active_hours(normalized)
        remaining, job_name = self._extract_job_name(remaining)

        # Re-normalize after extractions (may have extra whitespace)
        remaining = re.sub(r"\s+", " ", remaining).strip()

        if not remaining:
            return ParseResult(
                success=False,
                error="no schedule pattern found after extraction",
                original_text=original,
                normalized_text=normalized,
            )

        try:
            kind = self._infer_kind(remaining)
        except ValueError as exc:
            return ParseResult(
                success=False,
                error=str(exc),
                original_text=original,
                normalized_text=normalized,
            )

        # Build schedule based on kind
        try:
            schedule = self._build_schedule(kind, remaining)
        except ValueError as exc:
            return ParseResult(
                success=False,
                error=str(exc),
                inferred_kind=kind,
                original_text=original,
                normalized_text=normalized,
            )

        job_id = self._generate_job_id(job_name, agent_id)
        now_ms = time.time() * 1000

        job = ScheduledJob(
            job_id=job_id,
            name=job_name,
            schedule=schedule,
            enabled=True,
            delete_after_run=(kind == ScheduleKind.AT),
            active_hours=active_hours,
            created_at_ms=now_ms,
            metadata={"source": "nl_parser", "original_text": original},
        )

        return ParseResult(
            success=True,
            job=job,
            inferred_kind=kind,
            original_text=original,
            normalized_text=normalized,
        )

    # -- Internal helpers ---------------------------------------------------

    def _normalize(self, text: str) -> str:
        """Lowercase, strip, and normalize whitespace."""
        text = text.strip().lower()
        text = re.sub(r"\s+", " ", text)
        # Expand compressed durations for easier parsing
        text = NLJobNormalizer.normalize_duration(text)
        return text

    def _extract_active_hours(
        self,
        text: str,
    ) -> tuple[str, ActiveHours | None]:
        """Extract an active-hours clause and return (remaining, hours)."""
        # Try 24-hour format: "during 09:00-22:00"
        m = _ACTIVE_HOURS_24H_RE.search(text)
        if m:
            start_str = m.group(1)
            end_str = m.group(2)
            remaining = text[: m.start()] + text[m.end() :]
            return remaining.strip(), ActiveHours(start=start_str, end=end_str)

        # Try AM/PM format: "between 8am-6pm"
        m = _ACTIVE_HOURS_AMPM_RE.search(text)
        if m:
            start_h = int(m.group(1))
            start_ap = m.group(2).lower()
            end_h = int(m.group(3))
            end_ap = m.group(4).lower()
            start_str = self._ampm_to_24h(start_h, start_ap)
            end_str = self._ampm_to_24h(end_h, end_ap)
            remaining = text[: m.start()] + text[m.end() :]
            return remaining.strip(), ActiveHours(start=start_str, end=end_str)

        return text, None

    def _extract_job_name(self, text: str) -> tuple[str, str]:
        """Extract a job name and return (remaining_text, name).

        Patterns:
        - ``"run analysis every 5m"`` -> name=``"analysis"``
        - Fallback: first 3 significant words joined by ``_``
        """
        # "run <name> <rest>"
        m = _RUN_NAME_RE.match(text)
        if m:
            name = m.group(1).lower().replace(" ", "_")
            remaining = text[m.end() :].strip()
            return remaining, name

        # Try "<verb> <noun> <schedule...>" pattern
        # e.g. "check drift hourly"
        m = _VERB_NAME_RE.match(text)
        if m:
            word1 = m.group(1).lower()
            word2 = m.group(2).lower()
            # Only extract if both words look like a name (not schedule keywords)
            if word1 not in _STOP_WORDS and word2 not in _STOP_WORDS:
                name = f"{word1}_{word2}"
                remaining = text[m.end() :].strip()
                return remaining, name

        # Fallback: auto-generate from first significant words
        name = self._auto_name(text)
        return text, name

    def _auto_name(self, text: str) -> str:
        """Generate a name from the first significant words of *text*."""
        words = re.findall(r"[a-zA-Z]+", text)
        significant = [w.lower() for w in words if w.lower() not in _STOP_WORDS]
        if significant:
            return "_".join(significant[:3])
        return "job"

    def _infer_kind(self, text: str) -> ScheduleKind:
        """Infer the schedule kind from the normalized text."""
        # Check for interval pattern: "every N unit"
        if _DURATION_RE.search(text) and re.search(r"\bevery\b", text, re.IGNORECASE):
            return ScheduleKind.EVERY

        # Check for cron-like keywords
        cron_keywords = ("hourly", "daily", "weekly", "monthly", "weekday", "weekdays")
        for kw in cron_keywords:
            if kw in text:
                return ScheduleKind.CRON

        # Check for one-shot patterns
        if re.search(r"\b(once|in\s+\d+)\b", text, re.IGNORECASE):
            return ScheduleKind.AT
        if re.search(r"\bat\s+\d", text, re.IGNORECASE):
            # "at <time>" without recurring keywords -> AT
            return ScheduleKind.AT

        msg = f"cannot infer schedule kind from: '{text}'"
        raise ValueError(msg)

    def _build_schedule(self, kind: ScheduleKind, text: str) -> Schedule:
        """Build a ``Schedule`` object from *kind* and *text*."""
        if kind == ScheduleKind.EVERY:
            ms = self._parse_interval(text)
            now_ms = time.time() * 1000
            return Schedule(
                kind=ScheduleKind.EVERY,
                every_ms=ms,
                anchor_ms=now_ms,
            )
        elif kind == ScheduleKind.CRON:
            cron_expr = self._parse_cron(text)
            return Schedule(kind=ScheduleKind.CRON, cron_expr=cron_expr)
        else:  # AT
            at_ms = self._parse_at(text)
            return Schedule(kind=ScheduleKind.AT, at_ms=at_ms)

    def _parse_interval(self, text: str) -> float:
        """Parse a duration string into milliseconds.

        ``"every 5 minutes"`` -> ``300000``.
        """
        m = _DURATION_RE.search(text)
        if not m:
            msg = f"no duration found in: '{text}'"
            raise ValueError(msg)
        amount = int(m.group(1))
        unit = m.group(2).lower()
        ms_per_unit = _UNIT_TO_MS.get(unit)
        if ms_per_unit is None:
            msg = f"unknown time unit: '{unit}'"
            raise ValueError(msg)
        return amount * ms_per_unit

    def _parse_cron(self, text: str) -> str:
        """Convert cron-like NL into a 5-field cron expression."""
        # "hourly"
        if "hourly" in text:
            hour_min = self._extract_minute(text)
            return f"{hour_min} * * * *"

        # "daily at HH:MM" or "daily at Hpm"
        if "daily" in text:
            hour, minute = self._extract_time(text)
            return f"{minute} {hour} * * *"

        # "weekly on <day>" or just "weekly"
        if "weekly" in text:
            day_num = self._extract_weekday(text)
            hour, minute = self._extract_time(text)
            return f"{minute} {hour} * * {day_num}"

        # "monthly"
        if "monthly" in text:
            hour, minute = self._extract_time(text)
            return f"{minute} {hour} 1 * *"

        # "every weekday at HH:MM" or "every weekday"
        if "weekday" in text or "weekdays" in text:
            hour, minute = self._extract_time(text)
            return f"{minute} {hour} * * 1-5"

        msg = f"cannot parse cron pattern from: '{text}'"
        raise ValueError(msg)

    def _parse_at(self, text: str) -> float:
        """Parse a one-shot time into a Unix timestamp in ms."""
        # "in N units" (relative)
        m = _RELATIVE_RE.search(text)
        if m:
            amount = int(m.group(1))
            unit = m.group(2).lower()
            ms_per_unit = _UNIT_TO_MS.get(unit)
            if ms_per_unit is None:
                msg = f"unknown time unit: '{unit}'"
                raise ValueError(msg)
            return time.time() * 1000 + amount * ms_per_unit

        # "once at HH:MM" or "at HH:MM"
        m = _TIME_24H_RE.search(text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            return self._next_occurrence_ms(hour, minute)

        # "once at Hpm"
        m = _TIME_AMPM_RE.search(text)
        if m:
            raw_h = int(m.group(1))
            ap = m.group(2).lower()
            hour = self._convert_ampm(raw_h, ap)
            return self._next_occurrence_ms(hour, 0)

        msg = f"cannot parse one-shot time from: '{text}'"
        raise ValueError(msg)

    # -- Time helper methods ------------------------------------------------

    @staticmethod
    def _ampm_to_24h(hour: int, ampm: str) -> str:
        """Convert hour + am/pm to ``"HH:MM"`` string."""
        h = (0 if hour == 12 else hour) if ampm == "am" else (hour if hour == 12 else hour + 12)
        return f"{h:02d}:00"

    @staticmethod
    def _convert_ampm(hour: int, ampm: str) -> int:
        """Convert hour + am/pm to 24-hour integer."""
        if ampm == "am":
            return 0 if hour == 12 else hour
        return hour if hour == 12 else hour + 12

    def _extract_time(self, text: str) -> tuple[int, int]:
        """Extract ``(hour, minute)`` from text, defaulting to ``(0, 0)``."""
        m = _TIME_24H_RE.search(text)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = _TIME_AMPM_RE.search(text)
        if m:
            raw_h = int(m.group(1))
            ap = m.group(2).lower()
            return self._convert_ampm(raw_h, ap), 0
        return 0, 0

    @staticmethod
    def _extract_minute(text: str) -> int:
        """Extract a minute offset for hourly schedules."""
        m = _TIME_24H_RE.search(text)
        if m:
            return int(m.group(2))
        return 0

    @staticmethod
    def _extract_weekday(text: str) -> int:
        """Extract a cron weekday number from text (0=Sun, 1=Mon, ...).

        Defaults to 1 (Monday).
        """
        for day_name, day_num in _DAY_MAP.items():
            if day_name in text:
                return day_num
        return 1

    @staticmethod
    def _next_occurrence_ms(hour: int, minute: int) -> float:
        """Get the next occurrence of ``HH:MM`` as epoch ms.

        If the time has already passed today, returns tomorrow's occurrence.
        """
        import datetime

        now = datetime.datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target.timestamp() * 1000

    @staticmethod
    def _generate_job_id(name: str, agent_id: str) -> str:
        """Generate a unique job ID."""
        hex8 = uuid.uuid4().hex[:8]
        prefix = agent_id if agent_id else "nl"
        return f"{prefix}_{hex8}"
