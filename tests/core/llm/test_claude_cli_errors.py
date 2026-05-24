"""Tests for ``core.llm.claude_cli_errors`` — Phase 4 of the LaneQueue
plan.

Coverage map:

* :class:`TestIsTransientUpstream` — paperclip ``isClaudeTransient`` parity
  on a smattering of real ``claude --print`` stderr clips.
* :class:`TestClassifyTransient` — precedence rules
  (deterministic > auth > quota > burst > unknown).
* :class:`TestExtractResetClockTime` — clock parsing + timezone
  resolution + day rollover.
* :class:`TestNextRetryAt` — full integration (classification +
  reset extraction + schedule choice).
* :class:`TestBackoffSchedules` — schedule shape + attempt clamping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from core.llm.claude_cli_errors import (
    BURST_BACKOFF_SECONDS,
    QUOTA_BACKOFF_SECONDS,
    TIMEZONE_HINTS,
    build_haystack,
    classify_transient,
    extract_reset_clock_time,
    is_transient_upstream,
    next_retry_at,
)


class TestBuildHaystack:
    def test_concatenates_three_sources(self) -> None:
        assert build_haystack(stdout="out", stderr="err", error_message="msg") == "out\nerr\nmsg"

    def test_skips_none_and_empty(self) -> None:
        assert build_haystack(stdout=None, stderr="err", error_message="") == "err"

    def test_empty_input_returns_empty(self) -> None:
        assert build_haystack() == ""


class TestIsTransientUpstream:
    @pytest.mark.parametrize(
        "stderr",
        [
            "Error: 429 Too Many Requests",
            "rate_limit_error: token bucket empty",
            "overloaded_error: server overloaded",
            "HTTP 529 — high demand",
            "5-hour limit reached, resets at 3:00pm (Pacific)",
            "weekly limit reached. resets at 9am (UTC)",
            "Out of extra usage. Top up at claude.ai.",
            "throttlingexception: please try again later",
        ],
    )
    def test_known_transient_clips_classify_as_retryable(self, stderr: str) -> None:
        assert is_transient_upstream(stderr=stderr) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "Authentication required. Please run `claude login`.",
            "Login required: not logged in.",
            "unauthorized: api key invalid",
        ],
    )
    def test_auth_failures_short_circuit_to_false(self, stderr: str) -> None:
        assert is_transient_upstream(stderr=stderr) is False

    @pytest.mark.parametrize(
        "stderr",
        [
            "Model not found: claude-opus-99",
            "max-turns exceeded",
            "Invalid API key",
        ],
    )
    def test_deterministic_failures_short_circuit_to_false(self, stderr: str) -> None:
        assert is_transient_upstream(stderr=stderr) is False

    def test_empty_input_is_not_transient(self) -> None:
        assert is_transient_upstream() is False
        assert is_transient_upstream(stderr="") is False

    @pytest.mark.parametrize(
        "stdout",
        [
            # PR-PRT-STATUS (2026-05-25) — claude-cli emits an
            # INFORMATIONAL ``rate_limit_event`` JSON line on every
            # turn with ``status="allowed"`` + ``isUsingOverage=false``.
            # Pre-fix the regex matched the camelCase ``rateLimitType``
            # inside that payload as a rejection signal, producing the
            # v0.99.53 smoke false-positive that clipped every generator
            # candidate with a fake "rate_limit" classification.
            '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1779639600,"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false}}',
            '"rateLimitType":"five_hour"',
            '"rate_limit_event"',
            "rate_limit_event",
            "rate_limit_info",
            "rateLimit",
        ],
    )
    def test_informational_rate_limit_event_is_not_transient(self, stdout: str) -> None:
        """Regression pin: the informational ``rate_limit_event`` event
        type + its ``rateLimitType`` / ``rate_limit_info`` sub-fields
        must NOT be classified as a transient upstream rejection. Only
        actual ``rate_limit`` / ``rate-limit`` / ``rate_limit_error``
        text counts (see TestIsTransientUpstream above for the
        positive cases)."""
        assert is_transient_upstream(stdout=stdout) is False


class TestClassifyTransient:
    def test_classifies_burst(self) -> None:
        assert classify_transient(stderr="429 rate limit") == "burst"

    def test_classifies_quota(self) -> None:
        assert classify_transient(stderr="5-hour limit reached") == "quota"

    def test_classifies_auth(self) -> None:
        assert classify_transient(stderr="please log in") == "auth"

    def test_classifies_deterministic(self) -> None:
        assert classify_transient(stderr="model not found: x") == "deterministic"

    def test_unknown_returns_unknown(self) -> None:
        assert classify_transient(stderr="something else") == "unknown"

    def test_empty_input_is_unknown(self) -> None:
        assert classify_transient() == "unknown"

    def test_deterministic_beats_auth(self) -> None:
        # Deterministic precedes auth because model-not-found is a
        # contract failure (operator typed wrong id) the operator
        # must fix before any retry, regardless of login state.
        assert classify_transient(stderr="model not found; please log in") == "deterministic"

    def test_auth_beats_quota(self) -> None:
        assert classify_transient(stderr="5-hour limit reached. please log in") == "auth"

    def test_quota_beats_burst(self) -> None:
        assert classify_transient(stderr="5-hour limit reached, 429 too many requests") == "quota"


class TestExtractResetClockTime:
    _NOW_UTC = datetime(2026, 5, 22, 18, 0, 0, tzinfo=UTC)
    # 18:00 UTC = 11:00 Pacific (PDT in May), 14:00 Eastern.

    def test_extract_pacific_3pm(self) -> None:
        msg = "5-hour limit reached, resets at 3:00pm (Pacific)"
        result = extract_reset_clock_time(msg, now=self._NOW_UTC)
        assert result is not None
        result_in_pt = result.astimezone(ZoneInfo("America/Los_Angeles"))
        assert (result_in_pt.hour, result_in_pt.minute) == (15, 0)

    def test_extract_handles_no_minutes(self) -> None:
        msg = "usage limit reached. resets at 9am (Eastern)"
        result = extract_reset_clock_time(msg, now=self._NOW_UTC)
        assert result is not None
        result_in_et = result.astimezone(ZoneInfo("America/New_York"))
        assert (result_in_et.hour, result_in_et.minute) == (9, 0)

    def test_extract_rolls_forward_when_clock_already_passed(self) -> None:
        # At 18:00 UTC = 11:00 PDT, "resets at 9am Pacific" has already
        # happened today → roll to tomorrow.
        msg = "5-hour limit reached, resets at 9am (Pacific)"
        result = extract_reset_clock_time(msg, now=self._NOW_UTC)
        assert result is not None
        result_in_pt = result.astimezone(ZoneInfo("America/Los_Angeles"))
        # 11:00 PT now → next 09:00 PT is tomorrow.
        assert result_in_pt.day == self._NOW_UTC.astimezone(ZoneInfo("America/Los_Angeles")).day + 1
        assert (result_in_pt.hour, result_in_pt.minute) == (9, 0)

    def test_no_reset_phrase_returns_none(self) -> None:
        assert extract_reset_clock_time("just some unrelated text") is None

    def test_unrecognised_timezone_returns_none(self) -> None:
        # "Atlantic" isn't in TIMEZONE_HINTS — refuse to guess.
        msg = "5-hour limit reached, resets at 3pm (Atlantic)"
        assert extract_reset_clock_time(msg, now=self._NOW_UTC) is None

    def test_missing_timezone_returns_none(self) -> None:
        msg = "5-hour limit reached, resets at 3pm"
        assert extract_reset_clock_time(msg, now=self._NOW_UTC) is None

    def test_naive_now_is_treated_as_utc(self) -> None:
        msg = "5-hour limit reached, resets at 9am (UTC)"
        naive_now = datetime(2026, 5, 22, 8, 0, 0)  # 08:00, no tzinfo
        result = extract_reset_clock_time(msg, now=naive_now)
        assert result is not None
        assert result.hour == 9
        assert result.tzinfo is not None

    def test_timezone_hints_covers_pacific_pst_pdt(self) -> None:
        # Sanity check that the hint table normalises common claude CLI
        # spellings.
        assert TIMEZONE_HINTS["pacific"] == "America/Los_Angeles"
        assert TIMEZONE_HINTS["pdt"] == "America/Los_Angeles"
        assert TIMEZONE_HINTS["utc"] == "UTC"


class TestNextRetryAt:
    _NOW = datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC)

    def test_auth_returns_none(self) -> None:
        assert next_retry_at(stderr="please log in", attempt=0, now=self._NOW) is None

    def test_deterministic_returns_none(self) -> None:
        assert next_retry_at(stderr="model not found: x", now=self._NOW) is None

    def test_burst_uses_sub_minute_schedule(self) -> None:
        result = next_retry_at(stderr="429 rate limit", attempt=0, now=self._NOW)
        assert result is not None
        delta = result - self._NOW
        assert delta == timedelta(seconds=BURST_BACKOFF_SECONDS[0])

    def test_burst_clamps_at_last_tier(self) -> None:
        result = next_retry_at(stderr="429 rate limit", attempt=99, now=self._NOW)
        assert result is not None
        delta = result - self._NOW
        assert delta == timedelta(seconds=BURST_BACKOFF_SECONDS[-1])

    def test_quota_schedule_when_no_explicit_reset(self) -> None:
        # "5-hour limit reached" without a clock → use schedule.
        result = next_retry_at(stderr="5-hour limit reached.", attempt=0, now=self._NOW)
        assert result is not None
        delta = result - self._NOW
        assert delta == timedelta(seconds=QUOTA_BACKOFF_SECONDS[0])

    def test_quota_honours_explicit_reset_when_later_than_schedule(self) -> None:
        # 12:00 UTC = 05:00 Pacific (PDT). "resets at 3pm Pacific" = 22:00 UTC
        # = 10 hours away → longer than the 2-minute first-tier schedule.
        msg = "5-hour limit reached, resets at 3pm (Pacific)"
        result = next_retry_at(stderr=msg, attempt=0, now=self._NOW)
        assert result is not None
        # Should equal the extracted reset, not now + 2min.
        expected = extract_reset_clock_time(msg, now=self._NOW)
        assert result == expected

    def test_quota_uses_schedule_when_reset_is_in_past(self) -> None:
        # "resets at 1pm Pacific" → already past relative to 12:00 UTC =
        # 05:00 PDT? No — 13:00 PT is in the future from 05:00 PT.
        # Construct a case where the explicit reset is sooner than the
        # schedule: use attempt=3 (schedule = 2 hours) and a reset
        # only 10 minutes away.
        now = datetime(2026, 5, 22, 19, 50, 0, tzinfo=UTC)  # 12:50 Pacific
        msg = "5-hour limit reached, resets at 1pm (Pacific)"  # 13:00 PT = 20:00 UTC
        result = next_retry_at(stderr=msg, attempt=3, now=now)
        assert result is not None
        # Schedule attempt=3 = 2 hours; explicit reset = 10 min.
        # We pick the LATER (schedule wait), not the earlier.
        schedule_wait = now + timedelta(seconds=QUOTA_BACKOFF_SECONDS[3])
        assert result == schedule_wait

    def test_unknown_uses_burst_schedule(self) -> None:
        # No transient keyword → "unknown" → burst sub-minute backoff.
        result = next_retry_at(stderr="strange error text", attempt=2, now=self._NOW)
        assert result is not None
        delta = result - self._NOW
        assert delta == timedelta(seconds=BURST_BACKOFF_SECONDS[2])


class TestBackoffSchedules:
    def test_quota_schedule_shape(self) -> None:
        assert QUOTA_BACKOFF_SECONDS == (120.0, 600.0, 1800.0, 7200.0)

    def test_burst_schedule_shape(self) -> None:
        assert BURST_BACKOFF_SECONDS == (1.0, 2.0, 4.0, 8.0, 16.0)

    def test_burst_under_quota_first_tier(self) -> None:
        """Cheap retries first — the burst schedule's last tier should
        still be cheaper than the quota schedule's first."""
        assert BURST_BACKOFF_SECONDS[-1] < QUOTA_BACKOFF_SECONDS[0]
