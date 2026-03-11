"""Tests for Claude Code-style agentic UI rendering."""

from __future__ import annotations

from unittest.mock import patch

from core.ui.agentic_ui import (
    _fmt_tokens,
    render_plan_steps,
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
