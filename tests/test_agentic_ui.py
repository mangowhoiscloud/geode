"""Tests for Claude Code-style agentic UI rendering."""

from __future__ import annotations

import time
from unittest.mock import patch

from core.cli.ui.agentic_ui import (
    OperationLogger,
    SessionMeter,
    _fmt_tokens,
    get_session_meter,
    init_session_meter,
    mark_turn_start,
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

    @patch("core.cli.ui.agentic_ui.console")
    def test_string_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("analyze_ip", {"ip_name": "Berserk"})
        printed = str(mock_console.print.call_args)
        assert "analyze_ip" in printed
        assert "Berserk" in printed
        assert "▸" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_bool_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("list_ips", {"verbose": True})
        printed = str(mock_console.print.call_args)
        assert "verbose=true" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_numeric_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("search_ips", {"limit": 10})
        printed = str(mock_console.print.call_args)
        assert "limit=10" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_dict_arg(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("test_tool", {"config": {"key": "val"}})
        printed = str(mock_console.print.call_args)
        assert "config=" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_empty_args(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_call("list_ips", {})
        printed = str(mock_console.print.call_args)
        assert "list_ips" in printed
        assert "(" in printed


class TestRenderToolResult:
    """Tool result rendering: ✓ tool_name → summary."""

    @patch("core.cli.ui.agentic_ui.console")
    def test_success_with_tier_score(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("analyze_ip", {"tier": "S", "score": 81.3})
        printed = str(mock_console.print.call_args)
        assert "✓" in printed
        assert "analyze_ip" in printed
        assert "S" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_success_with_count(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("list_ips", {"count": 5})
        printed = str(mock_console.print.call_args)
        assert "5 items" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_success_with_plan_id(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("create_plan", {"plan_id": "abc12345678"})
        printed = str(mock_console.print.call_args)
        assert "plan:abc12345" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_error_result(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("analyze_ip", {"error": "Not found"})
        printed = str(mock_console.print.call_args)
        assert "✗" in printed
        assert "Not found" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_empty_result_shows_ok(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tool_result("list_ips", {})
        printed = str(mock_console.print.call_args)
        assert "ok" in printed


class TestRenderTokens:
    """Token usage rendering: ✢ model · ↓in ↑out · time."""

    @patch("core.cli.ui.agentic_ui.console")
    def test_with_elapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tokens("claude-opus-4-6", 1200, 350, elapsed_s=2.1)
        printed = str(mock_console.print.call_args)
        assert "✢" in printed
        assert "claude-opus-4-6" in printed
        assert "1.2k" in printed
        assert "350" in printed
        assert "2.1s" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_without_elapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_tokens("claude-opus-4-6", 500, 100)
        printed = str(mock_console.print.call_args)
        assert "500" in printed
        assert "100" in printed
        assert "s" not in printed or "claude" in printed  # no time suffix


class TestRenderPlanSteps:
    """Plan step rendering: ● Plan: ip_name."""

    @patch("core.cli.ui.agentic_ui.console")
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

    @patch("core.cli.ui.agentic_ui.console")
    def test_dispatch(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        render_subagent_dispatch("task-1", "analyze", "Analyze Berserk IP")
        printed = str(mock_console.print.call_args)
        assert "delegate_task" in printed
        assert "analyze" in printed

    @patch("core.cli.ui.agentic_ui.console")
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

    def test_turn_elapsed_resets_on_mark(self) -> None:
        """mark_turn_start() should reset the per-turn timer."""
        meter = SessionMeter(start_time=time.monotonic() - 600)
        # Session elapsed is ~600s, but turn elapsed matches session initially
        assert meter.turn_elapsed_s >= 600
        # Mark new turn
        meter.mark_turn_start()
        assert meter.turn_elapsed_s < 1  # just reset, should be near 0
        # Session elapsed unchanged
        assert meter.elapsed_s >= 600

    def test_turn_elapsed_display(self) -> None:
        meter = SessionMeter(start_time=time.monotonic() - 600)
        meter.mark_turn_start()
        # Just reset, should show "0s"
        assert meter.turn_elapsed_display == "0s"
        # Session elapsed still shows minutes
        assert "m" in meter.elapsed_display


class TestOperationLogger:
    """OperationLogger progressive tree rendering tests."""

    @patch("core.cli.ui.agentic_ui.console")
    def test_below_threshold_visible(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        visible = logger.log_tool_call("analyze_ip", {"ip_name": "Berserk"})
        assert visible is True
        assert mock_console.print.called

    @patch("core.cli.ui.agentic_ui.console")
    def test_above_threshold_collapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(OperationLogger.COLLAPSE_THRESHOLD):
            assert logger.log_tool_call(f"tool_{i}", {}) is True
        # Next call should be collapsed
        assert logger.log_tool_call("tool_extra", {}) is False

    @patch("core.cli.ui.agentic_ui.console")
    def test_finalize_shows_collapsed_count(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(OperationLogger.COLLAPSE_THRESHOLD + 3):
            logger.log_tool_call(f"tool_{i}", {})
        logger.finalize()
        calls = [str(c) for c in mock_console.print.call_args_list]
        combined = " ".join(calls)
        assert "+3 more tool uses" in combined

    @patch("core.cli.ui.agentic_ui.console")
    def test_finalize_no_collapsed(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_call("tool_1", {})
        mock_console.print.reset_mock()
        logger.finalize()
        assert not mock_console.print.called

    @patch("core.cli.ui.agentic_ui.console")
    def test_begin_round_prints_header(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.begin_round("TestRound")
        printed = str(mock_console.print.call_args)
        assert "TestRound" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_begin_round_only_once(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.begin_round("TestRound")
        logger.begin_round("TestRound")
        assert mock_console.print.call_count == 1

    @patch("core.cli.ui.agentic_ui.console")
    def test_reset_clears_state(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        for i in range(3):
            logger.log_tool_call(f"tool_{i}", {})
        logger.reset()
        assert logger._visible_count == 0
        assert logger._collapsed_count == 0
        assert logger._header_printed is False

    @patch("core.cli.ui.agentic_ui.console")
    def test_log_tool_result_error(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_result("test", {"error": "fail"}, visible=True)
        printed = str(mock_console.print.call_args)
        assert "✗" in printed
        assert "fail" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_log_tool_result_invisible_noop(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        logger = OperationLogger()
        logger.log_tool_result("test", {"tier": "S"}, visible=False)
        assert not mock_console.print.called


class TestRenderStatusLine:
    """Status line rendering tests."""

    @patch("core.cli.ui.agentic_ui.console")
    def test_renders_with_session_meter(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        init_session_meter(model="claude-opus-4-6")
        # Record some usage so tracker has data
        from core.llm.token_tracker import get_tracker

        tracker = get_tracker()
        tracker.record("claude-opus-4-6", 1200, 350)

        render_status_line()
        printed = str(mock_console.print.call_args)
        assert "✢" in printed
        assert "Worked for" in printed
        assert "claude-opus-4-6" in printed
        assert "context" in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_noop_without_meter(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        # Force no meter
        import core.cli.ui.agentic_ui as mod

        old = mod._session_meter
        mod._session_meter = None
        try:
            render_status_line()
            assert not mock_console.print.called
        finally:
            mod._session_meter = old

    @patch("core.cli.ui.agentic_ui.console")
    def test_status_line_shows_per_turn_delta(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        """After mark_turn_start(), status line should show only the turn's tokens."""
        from core.llm.token_tracker import get_tracker, reset_tracker

        reset_tracker()
        init_session_meter(model="claude-opus-4-6")
        tracker = get_tracker()

        # Simulate turn 1: record 10000 input, 2000 output
        tracker.record("claude-opus-4-6", 10000, 2000)

        # Now start turn 2
        mark_turn_start()

        # Simulate turn 2: record only 500 input, 100 output
        tracker.record("claude-opus-4-6", 500, 100)

        render_status_line()
        printed = str(mock_console.print.call_args)
        # Should show turn 2's 500 tokens, NOT cumulative 10500
        assert "500" in printed
        assert "100" in printed
        # Should NOT show "10.0k" or "10.5k" (cumulative)
        assert "10.0k" not in printed
        assert "10.5k" not in printed

    @patch("core.cli.ui.agentic_ui.console")
    def test_status_line_no_snapshot_uses_cumulative(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        """Without mark_turn_start(), status line falls back to cumulative."""
        import core.cli.ui.agentic_ui as mod
        from core.llm.token_tracker import get_tracker, reset_tracker

        reset_tracker()
        init_session_meter(model="claude-opus-4-6")
        tracker = get_tracker()

        # Clear snapshot
        mod._turn_snapshot = None

        tracker.record("claude-opus-4-6", 5000, 1000)
        render_status_line()
        printed = str(mock_console.print.call_args)
        assert "5.0k" in printed
        assert "1.0k" in printed


class TestTokenTrackerSnapshotDelta:
    """Tests for TokenTracker.snapshot() and delta_since()."""

    def test_snapshot_captures_current_state(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record("claude-opus-4-6", 1000, 200)
        snap = tracker.snapshot()
        assert snap.total_input_tokens == 1000
        assert snap.total_output_tokens == 200
        assert snap.call_count == 1
        assert snap.total_cost_usd > 0

    def test_delta_since_computes_difference(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        # Turn 1
        tracker.record("claude-opus-4-6", 5000, 1000)
        snap = tracker.snapshot()

        # Turn 2
        tracker.record("claude-opus-4-6", 800, 200)
        delta = tracker.delta_since(snap)

        assert delta.total_input_tokens == 800
        assert delta.total_output_tokens == 200
        assert delta.call_count == 1
        assert delta.total_cost_usd > 0

    def test_delta_with_no_new_calls(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record("claude-opus-4-6", 1000, 200)
        snap = tracker.snapshot()
        # No new calls
        delta = tracker.delta_since(snap)
        assert delta.total_input_tokens == 0
        assert delta.total_output_tokens == 0
        assert delta.call_count == 0
        assert delta.total_cost_usd == 0.0

    def test_delta_with_multiple_calls_in_turn(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        tracker.record("claude-opus-4-6", 3000, 500)
        snap = tracker.snapshot()

        # Multiple calls in turn 2
        tracker.record("claude-opus-4-6", 400, 100)
        tracker.record("claude-opus-4-6", 600, 150)
        delta = tracker.delta_since(snap)

        assert delta.total_input_tokens == 1000
        assert delta.total_output_tokens == 250
        assert delta.call_count == 2

    def test_context_usage_pct_for(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        # 10000 tokens out of 1M context = 1%
        pct = tracker.context_usage_pct_for("claude-opus-4-6", 10000)
        assert abs(pct - 1.0) < 0.1

    def test_context_usage_pct_for_capped_at_100(self) -> None:
        from core.llm.token_tracker import TokenTracker

        tracker = TokenTracker()
        pct = tracker.context_usage_pct_for("claude-opus-4-6", 2_000_000)
        assert pct == 100.0


class TestMarkTurnStart:
    """Tests for the module-level mark_turn_start() function."""

    def test_mark_turn_start_sets_snapshot(self) -> None:
        import core.cli.ui.agentic_ui as mod
        from core.llm.token_tracker import get_tracker, reset_tracker

        reset_tracker()
        init_session_meter(model="claude-opus-4-6")
        tracker = get_tracker()
        tracker.record("claude-opus-4-6", 1000, 200)

        mark_turn_start()
        assert mod._turn_snapshot is not None
        assert mod._turn_snapshot.total_input_tokens == 1000
        assert mod._turn_snapshot.total_output_tokens == 200

    def test_mark_turn_start_resets_meter_turn(self) -> None:
        meter = init_session_meter(model="claude-opus-4-6")
        # Simulate old session by backdating start
        meter.start_time = time.monotonic() - 300
        meter._turn_start = time.monotonic() - 300
        assert meter.turn_elapsed_s >= 300

        mark_turn_start()
        assert meter.turn_elapsed_s < 1
