"""Tests for NL Schedule Parser — Natural Language -> Structured Job (P6)."""

from __future__ import annotations

import time

import pytest
from core.scheduler.nl_scheduler import NLJobNormalizer, NLScheduleParser
from core.scheduler.scheduler import ScheduleKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def parser() -> NLScheduleParser:
    return NLScheduleParser()


def _now_ms() -> float:
    return time.time() * 1000


# ===========================================================================
# ParseResult basics
# ===========================================================================


class TestParseResult:
    def test_success_with_valid_input(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success is True
        assert result.job is not None
        assert result.error is None
        assert result.inferred_kind == ScheduleKind.EVERY

    def test_error_with_empty_input(self, parser: NLScheduleParser) -> None:
        result = parser.parse("")
        assert result.success is False
        assert result.job is None
        assert result.error is not None
        assert "empty" in result.error

    def test_error_with_whitespace_only(self, parser: NLScheduleParser) -> None:
        result = parser.parse("   ")
        assert result.success is False
        assert result.error is not None

    def test_error_with_garbage(self, parser: NLScheduleParser) -> None:
        result = parser.parse("xyzzy foobar baz")
        assert result.success is False
        assert result.error is not None

    def test_original_text_preserved(self, parser: NLScheduleParser) -> None:
        result = parser.parse("  Every 5 Minutes  ")
        assert result.original_text == "  Every 5 Minutes  "

    def test_normalized_text_set(self, parser: NLScheduleParser) -> None:
        result = parser.parse("  Every 5 Minutes  ")
        assert result.normalized_text == "every 5 minutes"


# ===========================================================================
# Duration parsing (EVERY kind)
# ===========================================================================


class TestDurationParsing:
    def test_every_5_minutes(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.EVERY
        assert result.job is not None
        assert result.job.schedule.every_ms == 300_000

    def test_every_2_hours(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 2 hours")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 7_200_000

    def test_every_30s(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 30s")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 30_000

    def test_every_1d(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 1d")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 86_400_000

    def test_every_5m_shorthand(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5m")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 300_000

    def test_every_10_sec(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 10 sec")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 10_000

    def test_every_1_hour(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 1 hour")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 3_600_000

    def test_very_large_interval(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 999 days")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 999 * 86_400_000

    def test_every_sets_anchor(self, parser: NLScheduleParser) -> None:
        before = _now_ms()
        result = parser.parse("every 5 minutes")
        after = _now_ms()
        assert result.job is not None
        assert before <= result.job.schedule.anchor_ms <= after


# ===========================================================================
# Cron inference
# ===========================================================================


class TestCronInference:
    def test_hourly(self, parser: NLScheduleParser) -> None:
        result = parser.parse("hourly")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.CRON
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 * * * *"

    def test_daily_at_9_00(self, parser: NLScheduleParser) -> None:
        result = parser.parse("daily at 9:00")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 9 * * *"

    def test_daily_at_3pm(self, parser: NLScheduleParser) -> None:
        result = parser.parse("daily at 3pm")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 15 * * *"

    def test_daily_no_time(self, parser: NLScheduleParser) -> None:
        result = parser.parse("daily")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 * * *"

    def test_weekly_on_monday(self, parser: NLScheduleParser) -> None:
        result = parser.parse("weekly on monday")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 * * 1"

    def test_weekly_default(self, parser: NLScheduleParser) -> None:
        result = parser.parse("weekly")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 * * 1"

    def test_every_weekday_at_14_00(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every weekday at 14:00")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 14 * * 1-5"

    def test_every_weekday_no_time(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every weekday")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 * * 1-5"

    def test_monthly(self, parser: NLScheduleParser) -> None:
        result = parser.parse("monthly")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 1 * *"

    def test_weekly_on_friday(self, parser: NLScheduleParser) -> None:
        result = parser.parse("weekly on friday")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 0 * * 5"

    def test_every_monday_at_9(self, parser: NLScheduleParser) -> None:
        """'every monday at 9:00' should be CRON weekly, not AT one-shot."""
        result = parser.parse("every monday at 9:00")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.CRON
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 9 * * 1"
        assert result.job.delete_after_run is False

    def test_every_friday_at_6pm(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every friday at 6pm")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.CRON
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 18 * * 5"

    def test_every_sunday(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every sunday at 10:00")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.CRON
        assert result.job is not None
        assert result.job.schedule.cron_expr == "0 10 * * 0"


# ===========================================================================
# AT parsing (one-shot)
# ===========================================================================


class TestATParsing:
    def test_in_30_minutes(self, parser: NLScheduleParser) -> None:
        before = _now_ms()
        result = parser.parse("in 30 minutes")
        after = _now_ms()
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.AT
        assert result.job is not None
        expected_min = before + 30 * 60_000
        expected_max = after + 30 * 60_000
        assert expected_min <= result.job.schedule.at_ms <= expected_max

    def test_in_2_hours(self, parser: NLScheduleParser) -> None:
        before = _now_ms()
        result = parser.parse("in 2 hours")
        after = _now_ms()
        assert result.success is True
        assert result.job is not None
        expected_min = before + 2 * 3_600_000
        expected_max = after + 2 * 3_600_000
        assert expected_min <= result.job.schedule.at_ms <= expected_max

    def test_once_at_15_00(self, parser: NLScheduleParser) -> None:
        result = parser.parse("once at 15:00")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.AT
        assert result.job is not None
        # Should be a future timestamp
        assert result.job.schedule.at_ms > 0

    def test_at_9am(self, parser: NLScheduleParser) -> None:
        result = parser.parse("at 9am")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.AT
        assert result.job is not None
        assert result.job.schedule.at_ms > 0

    def test_at_job_delete_after_run(self, parser: NLScheduleParser) -> None:
        result = parser.parse("in 30 minutes")
        assert result.job is not None
        assert result.job.delete_after_run is True

    def test_every_job_no_delete(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.job is not None
        assert result.job.delete_after_run is False


# ===========================================================================
# Active hours
# ===========================================================================


class TestActiveHours:
    def test_during_24h(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes during 09:00-22:00")
        assert result.success is True
        assert result.job is not None
        assert result.job.active_hours is not None
        assert result.job.active_hours.start == "09:00"
        assert result.job.active_hours.end == "22:00"
        assert result.job.schedule.every_ms == 300_000

    def test_between_ampm(self, parser: NLScheduleParser) -> None:
        result = parser.parse("hourly between 8am-6pm")
        assert result.success is True
        assert result.job is not None
        assert result.job.active_hours is not None
        assert result.job.active_hours.start == "08:00"
        assert result.job.active_hours.end == "18:00"
        assert result.job.schedule.cron_expr == "0 * * * *"

    def test_no_active_hours(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success is True
        assert result.job is not None
        assert result.job.active_hours is None

    def test_during_with_daily(self, parser: NLScheduleParser) -> None:
        result = parser.parse("daily at 9:00 during 08:00-20:00")
        assert result.success is True
        assert result.job is not None
        assert result.job.active_hours is not None
        assert result.job.active_hours.start == "08:00"
        assert result.job.active_hours.end == "20:00"


# ===========================================================================
# Job naming
# ===========================================================================


class TestJobNaming:
    def test_run_analysis(self, parser: NLScheduleParser) -> None:
        result = parser.parse("run analysis every 5 minutes")
        assert result.success is True
        assert result.job is not None
        assert "analysis" in result.job.name

    def test_check_drift(self, parser: NLScheduleParser) -> None:
        result = parser.parse("check drift hourly")
        assert result.success is True
        assert result.job is not None
        assert "check" in result.job.name
        assert "drift" in result.job.name

    def test_auto_generated_name(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success is True
        assert result.job is not None
        assert result.job.name != ""

    def test_auto_name_not_stop_word(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 10 seconds")
        assert result.success is True
        assert result.job is not None
        # "every" and "seconds" are stop words but "10" is not a word
        # The auto-name should still produce something
        assert result.job.name != ""


# ===========================================================================
# Agent ID injection
# ===========================================================================


class TestAgentId:
    def test_with_agent_id(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes", agent_id="monitor")
        assert result.success is True
        assert result.job is not None
        assert result.job.job_id.startswith("monitor_")

    def test_without_agent_id(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.success is True
        assert result.job is not None
        assert result.job.job_id.startswith("nl_")

    def test_job_id_unique(self, parser: NLScheduleParser) -> None:
        r1 = parser.parse("every 5 minutes")
        r2 = parser.parse("every 5 minutes")
        assert r1.job is not None
        assert r2.job is not None
        assert r1.job.job_id != r2.job.job_id


# ===========================================================================
# NLJobNormalizer
# ===========================================================================


class TestNLJobNormalizer:
    """Tests for the NLJobNormalizer helper class."""

    # -- Timezone normalization --

    def test_timezone_kst(self) -> None:
        assert NLJobNormalizer.normalize_timezone("KST") == "Asia/Seoul"

    def test_timezone_pst(self) -> None:
        assert NLJobNormalizer.normalize_timezone("PST") == "America/Los_Angeles"

    def test_timezone_est(self) -> None:
        assert NLJobNormalizer.normalize_timezone("EST") == "America/New_York"

    def test_timezone_jst(self) -> None:
        assert NLJobNormalizer.normalize_timezone("JST") == "Asia/Tokyo"

    def test_timezone_utc(self) -> None:
        assert NLJobNormalizer.normalize_timezone("UTC") == "UTC"

    def test_timezone_gmt(self) -> None:
        assert NLJobNormalizer.normalize_timezone("GMT") == "UTC"

    def test_timezone_case_insensitive(self) -> None:
        assert NLJobNormalizer.normalize_timezone("kst") == "Asia/Seoul"
        assert NLJobNormalizer.normalize_timezone("Pst") == "America/Los_Angeles"

    def test_timezone_unknown_passthrough(self) -> None:
        assert NLJobNormalizer.normalize_timezone("UNKNOWN") == "UNKNOWN"
        assert NLJobNormalizer.normalize_timezone("Europe/Berlin") == "Europe/Berlin"

    def test_timezone_strip_whitespace(self) -> None:
        assert NLJobNormalizer.normalize_timezone("  KST  ") == "Asia/Seoul"

    # -- Duration normalization --

    def test_duration_5min(self) -> None:
        assert NLJobNormalizer.normalize_duration("5min") == "5 minutes"

    def test_duration_2hr(self) -> None:
        assert NLJobNormalizer.normalize_duration("2hr") == "2 hours"

    def test_duration_30s(self) -> None:
        assert NLJobNormalizer.normalize_duration("30s") == "30 seconds"

    def test_duration_1d(self) -> None:
        assert NLJobNormalizer.normalize_duration("1d") == "1 days"

    def test_duration_already_expanded(self) -> None:
        assert NLJobNormalizer.normalize_duration("5 minutes") == "5 minutes"

    def test_duration_mixed_text(self) -> None:
        result = NLJobNormalizer.normalize_duration("every 5min during 09:00-22:00")
        assert "5 minutes" in result
        assert "during" in result

    # -- Cron normalization --

    def test_cron_valid_passthrough(self) -> None:
        assert NLJobNormalizer.normalize_cron("0 9 * * *") == "0 9 * * *"

    def test_cron_6_field_drops_seconds(self) -> None:
        result = NLJobNormalizer.normalize_cron("0 0 9 * * *")
        assert result == "0 9 * * *"

    def test_cron_invalid_returns_none(self) -> None:
        assert NLJobNormalizer.normalize_cron("invalid") is None
        assert NLJobNormalizer.normalize_cron("* *") is None

    def test_cron_strips_whitespace(self) -> None:
        result = NLJobNormalizer.normalize_cron("  0 9 * * *  ")
        assert result == "0 9 * * *"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_case_insensitive(self, parser: NLScheduleParser) -> None:
        result = parser.parse("Every 5 Minutes")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 300_000

    def test_mixed_case(self, parser: NLScheduleParser) -> None:
        result = parser.parse("HOURLY")
        assert result.success is True
        assert result.inferred_kind == ScheduleKind.CRON

    def test_multiple_whitespace(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every   5    minutes")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 300_000

    def test_leading_trailing_whitespace(self, parser: NLScheduleParser) -> None:
        result = parser.parse("   every 5 minutes   ")
        assert result.success is True

    def test_metadata_contains_original(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.job is not None
        assert result.job.metadata["source"] == "nl_parser"
        assert result.job.metadata["original_text"] == "every 5 minutes"

    def test_created_at_set(self, parser: NLScheduleParser) -> None:
        before = _now_ms()
        result = parser.parse("every 5 minutes")
        after = _now_ms()
        assert result.job is not None
        assert before <= result.job.created_at_ms <= after

    def test_enabled_by_default(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 5 minutes")
        assert result.job is not None
        assert result.job.enabled is True

    def test_every_with_mins_abbrev(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 10mins")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 600_000

    def test_every_with_hrs_abbrev(self, parser: NLScheduleParser) -> None:
        result = parser.parse("every 3hrs")
        assert result.success is True
        assert result.job is not None
        assert result.job.schedule.every_ms == 3 * 3_600_000


# ===========================================================================
# Action stores original text (LLM does extraction at fire time)
# ===========================================================================


class TestActionEmpty:
    """NL parser sets action="" — caller (tool handler) provides the action."""

    @pytest.fixture
    def parser(self) -> NLScheduleParser:
        return NLScheduleParser()

    def test_action_is_empty_by_default(self, parser: NLScheduleParser) -> None:
        text = "remind me to check emails every 5 minutes"
        result = parser.parse(text)
        assert result.success
        assert result.job is not None
        assert result.job.action == ""

    def test_action_empty_for_schedule_only(self, parser: NLScheduleParser) -> None:
        text = "every 5 minutes"
        result = parser.parse(text)
        assert result.success
        assert result.job is not None
        assert result.job.action == ""

    def test_caller_can_set_action(self, parser: NLScheduleParser) -> None:
        text = "daily at 9:00"
        result = parser.parse(text)
        assert result.success
        assert result.job is not None
        assert result.job.action == ""
        result.job.action = "generate daily standup summary"
        assert result.job.action == "generate daily standup summary"
