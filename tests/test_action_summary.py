"""Tests for Tier 1 deterministic action summary."""

from __future__ import annotations

from unittest.mock import patch

from core.cli.ui.agentic_ui import render_action_summary


class TestRenderActionSummary:
    """render_action_summary produces structured per-tool summaries."""

    def test_empty_tools_returns_empty(self) -> None:
        assert render_action_summary([], 0, 0.0, 0.0) == ""

    @patch("core.cli.ui.agentic_ui.console")
    def test_basic_summary(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        tool_calls = [
            {"name": "web_search", "input": {"query": "ML Engineer"}, "result": {"status": "ok"}},
            {"name": "memory_save", "input": {"key": "result"}, "result": {"status": "saved"}},
        ]
        summary = render_action_summary(tool_calls, 2, 3.5, 0.01)
        assert "web_search" in summary
        assert "memory_save" in summary
        assert "2 rounds" in summary
        assert "2 tools" in summary
        assert "3.5s" in summary
        assert "$0.010" in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_cap_at_10(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        tool_calls = [{"name": f"tool_{i}", "input": {}, "result": {}} for i in range(15)]
        summary = render_action_summary(tool_calls, 1, 1.0, 0.0)
        assert "+5 more" in summary
        # First 10 tools present
        assert "tool_0" in summary
        assert "tool_9" in summary
        # 11th tool NOT present directly
        assert "tool_10" not in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_error_result(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        tool_calls = [{"name": "fail_tool", "input": {}, "result": {"error": "timeout"}}]
        summary = render_action_summary(tool_calls, 1, 0.5, 0.0)
        assert "ERROR" in summary
        assert "timeout" in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_no_cost_omits_dollar(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        tool_calls = [{"name": "t", "input": {}, "result": {"status": "ok"}}]
        summary = render_action_summary(tool_calls, 1, 1.0, 0.0)
        assert "$" not in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_arg_preview_truncated(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        long_query = "a" * 100
        tool_calls = [
            {"name": "search", "input": {"query": long_query}, "result": {"status": "ok"}}
        ]
        summary = render_action_summary(tool_calls, 1, 0.5, 0.0)
        # Arg preview capped at 40 chars
        assert "a" * 40 in summary
        assert "a" * 41 not in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_result_preview_dict_key(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        """When result has a custom key (not error/result/status), show key=value."""
        tool_calls = [{"name": "calc", "input": {}, "result": {"answer": 42}}]
        summary = render_action_summary(tool_calls, 1, 0.1, 0.0)
        assert "answer=42" in summary

    @patch("core.cli.ui.agentic_ui.console")
    def test_console_print_called(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        """Each line of the summary is printed to console."""
        tool_calls = [{"name": "t1", "input": {}, "result": {"status": "done"}}]
        render_action_summary(tool_calls, 1, 1.0, 0.0)
        # Header + stats + blank + tool line + footer = 5 lines
        assert mock_console.print.call_count == 5

    @patch("core.cli.ui.agentic_ui.console")
    def test_action_summary_header(self, mock_console) -> None:  # type: ignore[no-untyped-def]
        tool_calls = [{"name": "t", "input": {}, "result": {}}]
        summary = render_action_summary(tool_calls, 1, 0.5, 0.0)
        assert "Action Summary" in summary
