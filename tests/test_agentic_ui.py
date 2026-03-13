"""Tests for Claude Code-style agentic UI rendering."""

from __future__ import annotations

import time
from unittest.mock import patch

from core.ui.agentic_ui import (
    OperationLogger,
    SessionMeter,
    _fmt_tokens,
    get_session_meter,
    init_session_meter,
    render_plan_steps,
    render_status_line,
    render_subagent_complete,
    render_subagent_dispatch,
    render_tokens,
    render_tool_call,
    render_tool_result,
)


class TestFmtTokens:
    """Unit tests for _fmt_tokens helper."""

    def test_small_number(self) -> None:
        assert _fmt_tokens(500) == "500"

    def test_exactly_1000(self) -> None:
        assert _fmt_tokens(1000) == "1.0k"

    def test_large_number(self) -> None:
        assert _fmt_tokens(1200) == "1.2k"

    def test_zero(self) -> None:
        assert _fmt_tokens(0) == "0"

    def test_very_large(self) -> None:
        assert _fmt_tokens(15300) == "15.3k"


class TestRenderToolCall:
    """Tool call rendering: ▸ tool_name(args)."""

    @patch("core.ui.agentic_ui.console")
    def test_string_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("analyze_ip", {"ip_name": "Berserk"})
        printed = str(mock_console.print.call_args)
        assert "analyze_ip" in printed
        assert "Berserk" in printed
        assert "▸" in printed

    @patch("core.ui.agentic_ui.console")
    def test_bool_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("list_ips", {"verbose": True})
        printed = str(mock_console.print.call_args)
        assert "verbose=true" in printed

    @patch("core.ui.agentic_ui.console")
    def test_numeric_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("search_ips", {"limit": 10})
        printed = str(mock_console.print.call_args)
        assert "limit=10" in printed

    @patch("core.ui.agentic_ui.console")
    def test_dict_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("test_tool", {"config": {"key": "val"}})
        printed = str(mock_console.print.call_args)
        assert "config=" in printed

    @patch("core.ui.agentic_ui.console")
    def test_empty_args(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("list_ips", {})
        printed = str(mock_console.print.call_args)
        assert "list_ips" in printed
        assert "(" in printed


class TestRenderToolResult:
    """Tool result rendering: ✓ tool_name → summary."""

    @patch("core.ui.agentic_ui.console")
    def test_success_with_tier_score(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("analyze_ip", {"tier": "S", "score": 81.3})
        printed = str(mock_console.print.call_args)
        assert "✓" in printed
        assert "analyze_ip" in printed
        assert "S" in printed

    @patch("core.ui.agentic_ui.console")
    def test_success_with_count(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("list_ips", {"count": 5})
        printed = str(mock_console.print.call_args)
        assert "5 items" in printed

    @patch("core.ui.agentic_ui.console")
    def test_success_with_plan_id(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("create_plan", {"plan_id": "abc12345678"})
        printed = str(mock_console.print.call_args)
        assert "plan:abc12345" in printed

    @patch("core.ui.agentic_ui.console")
    def test_error_result(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("analyze_ip", {"error": "Not found"})
        printed = str(mock_console.print.call_args)
        assert "✗" in printed
        assert "Not found" in printed

    @patch("core.ui.agentic_ui.console")
    def test_empty_result_shows_ok(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("list_ips", {})
        printed = str(mock_console.print.call_args)
        assert "ok" in printed


class TestRenderTokens:
    """Token usage rendering: ✢ model · ↓in ↑out · time."""

    @patch("core.ui.agentic_ui.console")
    def test_with_elapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tokens("claude-opus-4-6", 1200, 350, elapsed_s=2.1)
        printed = str(mock_console.print.call_args)
        assert "✢" in printed
        assert "claude-opus-4-6" in printed
        assert "1.2k" in printed
        assert "350" in printed
        assert "2.1s" in printed

    @patch("core.ui.agentic_ui.console")
    def test_without_elapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tokens("claude-opus-4-6", 500, 100)
        printed = str(mock_console.print.call_args)
        assert "500" in printed
        assert "100" in printed
        assert "s" not in printed or "claude" in printed  # no time suffix


class TestRenderPlanSteps:
    """Plan step rendering: ● Plan: ip_name."""

    @patch("core.ui.agentic_ui.console")
    def test_renders_steps(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_plan_steps("Berserk", ["Analyze", "Score", "Verify"])
        calls = [str(c) for c in mock_console.print.call_args_list]
        combined = " ".join(calls)
        assert "Berserk" in combined
        assert "1." in combined
        assert "Analyze" in combined
        assert "3." in combined


class TestRenderSubagent:
    """Sub-agent dispatch/complete rendering."""

    @patch("core.ui.agentic_ui.console")
    def test_dispatch(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_subagent_dispatch("task-1", "analyze", "Analyze Berserk IP")
        printed = str(mock_console.print.call_args)
        assert "delegate_task" in printed
        assert "analyze" in printed

    @patch("core.ui.agentic_ui.console")
    def test_complete(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_subagent_complete(3, 5.2)
        calls = [str(c) for c in mock_console.print.call_args_list]
        combined = " ".join(calls)
        assert "3" in combined
        assert "5.2s" in combined


class TestSessionMeter:
    """SessionMeter timing tests."""

    def test_elapsed_seconds(self) -> None:
        meter = SessionMeter(start_time=time.monotonic() - 10)
        assert meter.elapsed_s >= 10

    def test_elapsed_display_seconds(self) -> None:
        meter = SessionMeter(start_time=time.monotonic() - 42)
        assert meter.elapsed_display == "42s"

    def test_elapsed_display_minutes(self) -> None:
        meter = SessionMeter(start_time=time.monotonic() - 125)
        assert meter.elapsed_display == "2m 5s"

    def test_init_and_get(self) -> None:
        m = init_session_meter(model="claude-sonnet-4-6")
        assert get_session_meter() is m
        assert m.model == "claude-sonnet-4-6"


class TestOperationLogger:
    """OperationLogger progressive tree rendering tests."""

    @patch("core.ui.agentic_ui.console")
    def test_below_threshold_visible(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        visible = logger.log_tool_call("analyze_ip", {"ip_name": "Berserk"})
        assert visible is True
        assert mock_console.print.called

    @patch("core.ui.agentic_ui.console")
    def test_above_threshold_collapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(OperationLogger.COLLAPSE_THRESHOLD):
            assert logger.log_tool_call(f"tool_{i}", {}) is True
        # Next call should be collapsed
        assert logger.log_tool_call("tool_extra", {}) is False

    @patch("core.ui.agentic_ui.console")
    def test_finalize_shows_collapsed_count(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(OperationLogger.COLLAPSE_THRESHOLD + 3):
            logger.log_tool_call(f"tool_{i}", {})
        logger.finalize()
        calls = [str(c) for c in mock_console.print.call_args_list]
        combined = " ".join(calls)
        assert "+3 more tool uses" in combined

    @patch("core.ui.agentic_ui.console")
    def test_finalize_no_collapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_call("tool_1", {})
        mock_console.print.reset_mock()
        logger.finalize()
        assert not mock_console.print.called

    @patch("core.ui.agentic_ui.console")
    def test_begin_round_prints_header(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.begin_round("TestRound")
        printed = str(mock_console.print.call_args)
        assert "TestRound" in printed

    @patch("core.ui.agentic_ui.console")
    def test_begin_round_only_once(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.begin_round("TestRound")
        logger.begin_round("TestRound")
        assert mock_console.print.call_count == 1

    @patch("core.ui.agentic_ui.console")
    def test_reset_clears_state(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(3):
            logger.log_tool_call(f"tool_{i}", {})
        logger.reset()
        assert logger._visible_count == 0
        assert logger._collapsed_count == 0
        assert logger._header_printed is False

    @patch("core.ui.agentic_ui.console")
    def test_log_tool_result_error(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_result("test", {"error": "fail"}, visible=True)
        printed = str(mock_console.print.call_args)
        assert "✗" in printed
        assert "fail" in printed

    @patch("core.ui.agentic_ui.console")
    def test_log_tool_result_invisible_noop(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_result("test", {"tier": "S"}, visible=False)
        assert not mock_console.print.called


class TestRenderStatusLine:
    """Status line rendering tests."""

    @patch("core.ui.agentic_ui.console")
    def test_renders_with_session_meter(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        init_session_meter(model="claude-opus-4-6")
        # Record some usage so tracker has data
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()
        tracker.record("claude-opus-4-6", 1200, 350)

        render_status_line()
        printed = str(mock_console.print.call_args)
        assert "✻" in printed
        assert "Worked for" in printed
        assert "claude-opus-4-6" in printed
        assert "context" in printed

    @patch("core.ui.agentic_ui.console")
    def test_noop_without_meter(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        # Force no meter
        import core.ui.agentic_ui as mod

        old = mod._session_meter
        mod._session_meter = None
        try:
            render_status_line()
            assert not mock_console.print.called
        finally:
            mod._session_meter = old
