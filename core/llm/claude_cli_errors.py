"""Classify ``claude --print`` subprocess failures + extract reset times.

PR-LQ-Phase4 (2026-05-22) — fourth leg of the LaneQueue 5-phase plan
([[project_lanequeue_handoff_2026_05_22]]).

Why this module exists
======================

Both ``claude --print`` spawn sites (the self-improving-loop mutator
runner + the Petri inspect_ai bridge) currently surface a generic
``CliInvocationError("claude exited 1: <stderr clip>")`` when the
subprocess fails. The caller can retry with exponential backoff, but
that's the worst of both worlds:

* If the failure is **burst rate-limit** (HTTP 429 or "rate limit
  exceeded" text), retrying after 60s is wasteful — the burst limiter
  resets in seconds.
* If the failure is **5-hour quota** ("5-hour limit reached, resets
  at 3pm Pacific"), retrying after 60s burns more credit before the
  window actually rolls over — 2-3 hours later.
* If the failure is **deterministic** (auth required, max-turns
  exhausted), retrying at all is pointless.

paperclip (``~/workspace/paperclip/packages/adapters/claude-local/
src/server/parse.ts``) has 1+ year of production-tested regex
patterns + a tiered backoff schedule. This module ports the patterns
to Python for use by the GEODE callers; the backoff schedule is
exposed as data so callers can choose how to wait.

Scope
=====

This PR is **classifier + scheduler data**, not the retry-loop
itself. Callers (the mutator runner, the inspect_ai bridge, the
Anthropic provider's ``_on_retry_journal_emit`` hook) decide how to
weave the schedule into their own retry path; a single retry helper
would conflate too many concerns (sync vs async, jittered vs not,
journal-integrated vs not).

Module surface
==============

* :func:`is_transient_upstream` — boolean classifier matching paperclip's
  ``isClaudeTransientUpstreamError`` — true when the failure looks
  retryable (429 / 529 / overloaded / 5h or weekly limit reached /
  extra-usage exhausted).
* :func:`classify_transient` — finer-grained label
  (``"burst" | "quota" | "auth" | "deterministic" | "unknown"``).
* :func:`extract_reset_clock_time` — parse "resets at 3:00pm
  (Pacific)" style messages into a timezone-aware ``datetime``.
* :func:`next_retry_at` — combine classification + reset extraction
  + tiered backoff into a single suggested retry timestamp.
* :data:`BURST_BACKOFF_SECONDS` / :data:`QUOTA_BACKOFF_SECONDS` —
  paperclip's 4-tier schedules, exposed for direct use.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "BURST_BACKOFF_SECONDS",
    "QUOTA_BACKOFF_SECONDS",
    "TIMEZONE_HINTS",
    "TransientClass",
    "build_haystack",
    "classify_transient",
    "extract_reset_clock_time",
    "is_transient_upstream",
    "next_retry_at",
]


TransientClass = Literal["burst", "quota", "auth", "deterministic", "unknown"]
"""Coarse classification of a ``claude --print`` failure:

* ``"burst"`` — 429 / 529 / overloaded; retry in seconds.
* ``"quota"`` — 5-hour or weekly limit reached; retry in tens of
  minutes to hours (paperclip schedule: 2m / 10m / 30m / 2h).
* ``"auth"`` — login required / not logged in; retrying is pointless,
  operator must run ``claude login``.
* ``"deterministic"`` — non-transient error (model not found,
  max-turns hit, unknown-session). Retry is pointless.
* ``"unknown"`` — no pattern matched. Caller decides.
"""


# Ported from paperclip parse.ts:12 (CLAUDE_TRANSIENT_UPSTREAM_RE).
# Matches the broad transient family — keep in lockstep with paperclip
# so the GEODE classifier sees the same set of upstream signals.
# PR-PRT-STATUS (2026-05-25) — first alternative tightened from
# ``rate[-\s]?limit(?:ed)?`` to ``rate[-_\s]limit(?:ed|_error)?`` so
# a camelCase ``rateLimitType`` (inside claude-cli's informational
# ``rate_limit_event`` payload with ``status="allowed"``) no longer
# false-matches as a rejection signal. See sibling regex at
# ``plugins/petri_audit/claude_cli_provider.py``.
_TRANSIENT_UPSTREAM_RE = re.compile(
    r"(?:rate[-_\s]limit(?:ed\b|_error\b|(?![_a-zA-Z]))|too\s+many\s+requests|\b429\b"
    r"|overloaded(?:_error)?|server\s+overloaded|service\s+unavailable|\b503\b"
    r"|\b529\b|high\s+demand|try\s+again\s+later|temporarily\s+unavailable"
    r"|throttl(?:ed|ing)|throttlingexception|servicequotaexceededexception"
    r"|out\s+of\s+extra\s+usage|extra\s+usage\b|claude\s+usage\s+limit\s+reached"
    r"|5[-\s]?hour\s+limit\s+reached|weekly\s+limit\s+reached"
    r"|usage\s+limit\s+reached|usage\s+cap\s+reached)",
    re.IGNORECASE,
)

# Ported from paperclip parse.ts:14 (CLAUDE_EXTRA_USAGE_RESET_RE).
# Captures the "resets at 3:00pm (Pacific)" tail of a quota message.
_RESET_RE = re.compile(
    r"(?:out\s+of\s+extra\s+usage|extra\s+usage|usage\s+limit\s+reached|usage\s+cap\s+reached"
    r"|5[-\s]?hour\s+limit\s+reached|weekly\s+limit\s+reached"
    r"|claude\s+usage\s+limit\s+reached)"
    r"[\s\S]{0,80}?\bresets?\s+(?:at\s+)?"
    r"(?P<clock>[^\n()]+?)"
    r"(?:\s*\((?P<tz>[^)]+)\))?"
    r"(?:[.!]|\n|$)",
    re.IGNORECASE,
)

# Quota patterns get the longer 4-tier backoff; the rest of the
# transient family is burst (sub-minute resolution).
_QUOTA_RE = re.compile(
    r"(?:5[-\s]?hour\s+limit\s+reached|weekly\s+limit\s+reached"
    r"|claude\s+usage\s+limit\s+reached|usage\s+limit\s+reached"
    r"|usage\s+cap\s+reached|out\s+of\s+extra\s+usage)",
    re.IGNORECASE,
)

_AUTH_RE = re.compile(
    r"(?:not\s+logged\s+in|please\s+log\s+in|please\s+run\s+`?claude\s+login`?"
    r"|login\s+required|requires\s+login|unauthorized|authentication\s+required)",
    re.IGNORECASE,
)

_DETERMINISTIC_RE = re.compile(
    r"(?:model\s+not\s+found|unknown\s+session|max\s*[-_ ]?turns?\b|invalid\s+api\s+key)",
    re.IGNORECASE,
)

# Clock-time regex — matches "3pm", "3:00pm", "3:30 PM", etc. The
# meridiem letter is captured in `meridiem` so callers can convert
# to 24-hour.
_CLOCK_RE = re.compile(
    r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>[ap])\.?\s*m\.?",
    re.IGNORECASE,
)


# paperclip heartbeat.ts:217-226 — 4-tier quota retry schedule.
# These are absolute waits, not exponential; the assumption is that
# the 5h or weekly window has closed and a multi-minute wait is the
# minimum useful delay.
QUOTA_BACKOFF_SECONDS: tuple[float, ...] = (
    120.0,  # 2 minutes
    600.0,  # 10 minutes
    1800.0,  # 30 minutes
    7200.0,  # 2 hours
)
"""Paperclip's 4-tier backoff for quota (5-hour / weekly) failures.

Indexed by attempt number — caller selects ``schedule[min(attempt,
len(schedule) - 1)]``. paperclip recommends ``MAX_ATTEMPTS = 4`` +
``JITTER_RATIO = 0.25``; this module exposes the schedule but does
NOT apply jitter (callers may want different jitter strategies)."""

BURST_BACKOFF_SECONDS: tuple[float, ...] = (
    1.0,
    2.0,
    4.0,
    8.0,
    16.0,
)
"""Sub-minute exponential schedule for burst (429 / 529 / overloaded)
failures. Caller selects ``schedule[min(attempt, len(schedule) - 1)]``;
beyond the last tier, repeat the 16s wait or surrender."""


# Minimal timezone-hint map — paperclip's full normalisation table is
# long; we cover the cases Anthropic actually emits. Empty string
# means "let the caller's default ``now`` timezone stand".
TIMEZONE_HINTS: Mapping[str, str] = {
    "pacific": "America/Los_Angeles",
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "mountain": "America/Denver",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "central": "America/Chicago",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "eastern": "America/New_York",
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "utc": "UTC",
    "gmt": "UTC",
}


def build_haystack(
    *,
    stdout: str | None = None,
    stderr: str | None = None,
    error_message: str | None = None,
) -> str:
    """Concatenate every text source the CLI may surface into one
    grep-able string.

    paperclip ``buildClaudeTransientHaystack`` does the same: join
    stdout + stderr + error_message with newlines so a single regex
    pass catches the signal wherever the CLI dropped it.
    """
    parts = [p for p in (stdout, stderr, error_message) if p]
    return "\n".join(parts).strip()


def is_transient_upstream(
    *,
    stdout: str | None = None,
    stderr: str | None = None,
    error_message: str | None = None,
) -> bool:
    """Return True when the failure looks retryable.

    Mirrors paperclip ``isClaudeTransientUpstreamError``: deterministic
    failures (auth, model-not-found, max-turns) short-circuit to False
    so the caller doesn't waste a retry on something that won't fix
    itself.
    """
    haystack = build_haystack(stdout=stdout, stderr=stderr, error_message=error_message)
    if not haystack:
        return False
    if _AUTH_RE.search(haystack):
        return False
    if _DETERMINISTIC_RE.search(haystack):
        return False
    return bool(_TRANSIENT_UPSTREAM_RE.search(haystack))


def classify_transient(
    *,
    stdout: str | None = None,
    stderr: str | None = None,
    error_message: str | None = None,
) -> TransientClass:
    """Finer-grained label for retry-strategy selection.

    Precedence: deterministic > auth > quota > burst > unknown. The
    ordering matters when a single message carries multiple keywords
    — e.g. "rate limit exceeded; not logged in" should classify as
    ``"auth"`` (the deeper failure) rather than ``"burst"``.
    """
    haystack = build_haystack(stdout=stdout, stderr=stderr, error_message=error_message)
    if not haystack:
        return "unknown"
    if _DETERMINISTIC_RE.search(haystack):
        return "deterministic"
    if _AUTH_RE.search(haystack):
        return "auth"
    if _QUOTA_RE.search(haystack):
        return "quota"
    if _TRANSIENT_UPSTREAM_RE.search(haystack):
        return "burst"
    return "unknown"


def _parse_clock(clock_text: str) -> tuple[int, int] | None:
    """Parse "3pm" / "3:00pm" / "3:30 PM" → (hour24, minute) or None."""
    normalised = re.sub(r"\s+", " ", clock_text.strip())
    match = _CLOCK_RE.match(normalised)
    if match is None:
        return None
    try:
        hour12 = int(match.group("hour"))
    except (TypeError, ValueError):
        return None
    if hour12 < 1 or hour12 > 12:
        return None
    minute_raw = match.group("minute") or "0"
    try:
        minute = int(minute_raw)
    except ValueError:
        return None
    if minute < 0 or minute > 59:
        return None
    meridiem = (match.group("meridiem") or "").lower()
    hour24 = hour12 % 12
    if meridiem == "p":
        hour24 += 12
    return hour24, minute


def _resolve_timezone(hint: str | None) -> ZoneInfo | None:
    """Map a free-text timezone hint to a ``ZoneInfo`` or None."""
    if not hint:
        return None
    canonical = TIMEZONE_HINTS.get(hint.strip().lower())
    if canonical is None:
        return None
    try:
        return ZoneInfo(canonical)
    except ZoneInfoNotFoundError:  # pragma: no cover — system zoneinfo absent
        return None


def extract_reset_clock_time(
    text: str,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Parse "resets at 3:00pm (Pacific)" → next ``datetime`` matching.

    Returns ``None`` when no reset clue is present, the clock text
    is unparseable, or the timezone hint is missing / unrecognised
    (we never guess the operator's local TZ — that could quietly
    drift the retry by 5-12 hours, hiding the failure or hammering
    the bucket early).

    The returned datetime is the **next** occurrence of the clock
    time strictly after ``now`` (rolls forward by a day if the time
    has already passed today). ``now`` defaults to ``datetime.now(UTC)``;
    pass a fixed value in tests.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    match = _RESET_RE.search(text)
    if match is None:
        return None
    clock_text = (match.group("clock") or "").strip()
    if not clock_text:
        return None

    clock = _parse_clock(clock_text)
    if clock is None:
        return None
    hour24, minute = clock

    tz_hint = (match.group("tz") or "").strip() or None
    tz = _resolve_timezone(tz_hint)
    if tz is None:
        return None

    now_in_tz = now.astimezone(tz)
    candidate = now_in_tz.replace(hour=hour24, minute=minute, second=0, microsecond=0)
    if candidate <= now_in_tz:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(UTC)


def _backoff_for(attempt: int, schedule: tuple[float, ...]) -> float:
    """Index into a backoff schedule with attempt-clamping."""
    attempt = max(attempt, 0)
    index = min(attempt, len(schedule) - 1)
    return schedule[index]


def next_retry_at(
    *,
    stdout: str | None = None,
    stderr: str | None = None,
    error_message: str | None = None,
    attempt: int = 0,
    now: datetime | None = None,
) -> datetime | None:
    """Return the suggested retry timestamp, or ``None`` when retry is
    futile (auth required / deterministic / unknown non-transient).

    Strategy:

    1. Classify the failure
       (:func:`classify_transient`).
    2. ``"auth"`` / ``"deterministic"`` → ``None`` (don't retry).
    3. ``"quota"`` → try to extract the explicit ``resets at …`` time
       from the message; if present, return ``max(reset_time,
       now + quota_backoff[attempt])`` so a server-promised reset is
       honoured even when our schedule would wait longer. If no
       explicit time, return ``now + quota_backoff[attempt]``.
    4. ``"burst"`` / ``"unknown"`` → ``now + burst_backoff[attempt]``.

    The ``unknown`` bucket is retried on the burst schedule because
    sub-minute waits are cheap; if the failure is genuinely
    non-transient the caller will surface it after a tier or two.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    klass = classify_transient(stdout=stdout, stderr=stderr, error_message=error_message)
    if klass in ("auth", "deterministic"):
        return None

    haystack = build_haystack(stdout=stdout, stderr=stderr, error_message=error_message)
    if klass == "quota":
        schedule_wait = now + timedelta(seconds=_backoff_for(attempt, QUOTA_BACKOFF_SECONDS))
        explicit = extract_reset_clock_time(haystack, now=now)
        if explicit is not None and explicit > schedule_wait:
            return explicit
        return schedule_wait

    # burst + unknown share the sub-minute schedule.
    return now + timedelta(seconds=_backoff_for(attempt, BURST_BACKOFF_SECONDS))
