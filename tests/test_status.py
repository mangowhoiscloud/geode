"""Tests for GeodeStatus -- TextSpinner-based spinner UI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.config import ANTHROPIC_PRIMARY
from core.llm.client import LLMUsage, LLMUsageAccumulator
from core.cli.ui.status import GeodeStatus, TextSpinner, _snapshot, _UsageSnapshot

# ---------------------------------------------------------------------------
# _snapshot / _UsageSnapshot
# ---------------------------------------------------------------------------


class TestUsageSnapshot:
    """Snapshot captures accumulator totals immutably."""

    def test_snapshot_empty_accumulator(self) -> None:
        acc = LLMUsageAccumulator()
        snap = _snapshot(acc)
        assert snap.input_tokens == 0
        assert snap.output_tokens == 0
        assert snap.cost_usd == 0.0

    def test_snapshot_with_usage(self) -> None:
        acc = LLMUsageAccumulator()
        acc.record(LLMUsage(model="test", input_tokens=100, output_tokens=50, cost_usd=0.01))
        snap = _snapshot(acc)
        assert snap.input_tokens == 100
        assert snap.output_tokens == 50
        assert snap.cost_usd == pytest.approx(0.01)

    def test_snapshot_is_frozen(self) -> None:
        snap = _UsageSnapshot(input_tokens=10, output_tokens=5, cost_usd=0.001)
        with pytest.raises(AttributeError):
            snap.input_tokens = 20  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TextSpinner
# ---------------------------------------------------------------------------


class TestTextSpinner:
    """TextSpinner starts, updates, and stops cleanly."""

    def test_start_stop(self) -> None:
        """Spinner can start and stop without error."""
        spinner = TextSpinner("Loading...")
        spinner.start()
        spinner.stop()

    def test_stop_with_final_message(self) -> None:
        """Stop with a final message writes it to stdout."""
        spinner = TextSpinner("Loading...")
        spinner.start()
        spinner.stop("Done!")

    def test_update_message(self) -> None:
        """update() changes the message."""
        spinner = TextSpinner("Step 1")
        spinner.update("Step 2")
        assert spinner._message == "Step 2"


# ---------------------------------------------------------------------------
# GeodeStatus context manager
# ---------------------------------------------------------------------------


class TestGeodeStatusContextManager:
    """Enter/exit lifecycle, update, and stop."""

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_enter_exit(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Context manager enters and exits without error."""
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Testing...", model="test-model"):
            pass  # auto-exit prints summary

        # Auto-exit should print a summary via console.print
        mock_console.print.assert_called_once()
        printed = str(mock_console.print.call_args)
        assert "done" in printed

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_update_changes_spinner(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """update() changes the internal spinner message."""
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Step 1") as status:
            status.update("Step 2")
            # Verify the spinner's message was updated
            assert status._spinner is not None
            assert status._spinner._message == "✢ Step 2"
            status.stop("done")

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_stop_prints_summary(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """stop() prints a line with checkmark and summary."""
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Working...") as status:
            status.stop("analyze · Berserk")

        # Find the console.print call with our summary
        printed = [str(c) for c in mock_console.print.call_args_list]
        summary_found = any("analyze · Berserk" in p for p in printed)
        assert summary_found, f"Summary not found in prints: {printed}"

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_stop_idempotent(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Calling stop() twice does not double-print."""
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Working...") as status:
            status.stop("result")
            status.stop("result again")

        # console.print for summary should be called once (from explicit stop)
        # __exit__ sees _stopped=True and skips
        print_calls = mock_console.print.call_args_list
        summary_count = sum(1 for c in print_calls if "result" in str(c))
        assert summary_count == 1

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_auto_exit_summary(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """If stop() is never called, __exit__ prints a generic summary."""
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Working..."):
            pass  # no explicit stop

        printed = [str(c) for c in mock_console.print.call_args_list]
        done_found = any("done" in p for p in printed)
        assert done_found


# ---------------------------------------------------------------------------
# Token delta calculation
# ---------------------------------------------------------------------------


class TestTokenDelta:
    """Verify _get_token_delta computes before/after difference."""

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_delta_calculation(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Token delta = after - before."""
        acc = LLMUsageAccumulator()
        acc.record(LLMUsage(model="m", input_tokens=100, output_tokens=20, cost_usd=0.005))
        mock_acc_fn.return_value = acc

        with GeodeStatus("Test") as status:
            # Simulate an LLM call recording additional tokens
            acc.record(LLMUsage(model="m", input_tokens=200, output_tokens=50, cost_usd=0.010))
            delta = status._get_token_delta()

        assert delta.input_tokens == 200
        assert delta.output_tokens == 50
        assert delta.cost_usd == pytest.approx(0.010)

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_delta_zero_when_no_calls(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """No LLM calls during context -> zero delta."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc

        with GeodeStatus("Test") as status:
            delta = status._get_token_delta()

        assert delta.input_tokens == 0
        assert delta.output_tokens == 0
        assert delta.cost_usd == 0.0


# ---------------------------------------------------------------------------
# Summary line formatting
# ---------------------------------------------------------------------------


class TestSummaryFormatting:
    """Verify the summary line includes token info and elapsed time."""

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_summary_includes_tokens_and_cost(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """When there are tokens, the summary shows arrows and cost."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc

        with GeodeStatus("Test") as status:
            acc.record(LLMUsage(model="m", input_tokens=150, output_tokens=30, cost_usd=0.004))
            status.stop("analyze · Berserk")

        # Inspect the printed line
        print_args = [str(c) for c in mock_console.print.call_args_list]
        summary_line = next((p for p in print_args if "analyze" in p), "")
        assert "↓150" in summary_line  # input tokens
        assert "↑30" in summary_line  # output tokens
        assert "$0.004" in summary_line

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_summary_no_tokens_still_shows_time(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """Offline fallback: no tokens, still shows elapsed time."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc

        with GeodeStatus("Test") as status:
            # No LLM calls -- simulates offline
            status.stop("help (offline)")

        print_args = [str(c) for c in mock_console.print.call_args_list]
        summary_line = next((p for p in print_args if "help" in p), "")
        assert "help (offline)" in summary_line
        # Should have elapsed time but no token info
        assert "s" in summary_line  # e.g. "0.0s"


# ---------------------------------------------------------------------------
# Model display
# ---------------------------------------------------------------------------


class TestModelDisplay:
    """Spinner message includes model name when provided."""

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_model_in_spinner(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Classifying...", model=ANTHROPIC_PRIMARY) as status:
            # Verify model appears in the spinner format string
            fmt = status._format_spinner("Classifying...")
            assert ANTHROPIC_PRIMARY in fmt
            status.stop("done")

    @patch("core.cli.ui.status.console")
    @patch("core.cli.ui.status.get_usage_accumulator")
    def test_no_model(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        mock_acc_fn.return_value = LLMUsageAccumulator()

        with GeodeStatus("Working...") as status:
            fmt = status._format_spinner("Working...")
            assert "Working..." in fmt
            status.stop("done")
