"""Tests for GeodeStatus — Claude Code-style spinner UI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.config import ANTHROPIC_PRIMARY
from core.llm.client import LLMUsage, LLMUsageAccumulator
from core.ui.status import GeodeStatus, _snapshot, _UsageSnapshot

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
# GeodeStatus context manager
# ---------------------------------------------------------------------------


class TestGeodeStatusContextManager:
    """Enter/exit lifecycle, update, and stop."""

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_enter_exit(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Context manager enters and exits without error."""
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Testing...", model="test-model"):
            pass  # auto-exit prints summary

        mock_console.status.assert_called_once()
        mock_status.__enter__.assert_called_once()
        # __exit__ called once by stop (or auto-exit)
        mock_status.__exit__.assert_called_once()

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_update_changes_spinner(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """update() calls status.update on the Rich Status object."""
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Step 1") as status:
            status.update("Step 2")
            status.stop("done")

        mock_status.update.assert_called_once()
        call_arg = mock_status.update.call_args[0][0]
        assert "Step 2" in call_arg

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_stop_prints_summary(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """stop() prints a line with checkmark and summary."""
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Working...") as status:
            status.stop("analyze · Berserk")

        # Find the console.print call with our summary
        printed = [str(c) for c in mock_console.print.call_args_list]
        summary_found = any("analyze · Berserk" in p for p in printed)
        assert summary_found, f"Summary not found in prints: {printed}"

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_stop_idempotent(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Calling stop() twice does not double-print."""
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Working...") as status:
            status.stop("result")
            status.stop("result again")

        # console.print for summary should be called once (from explicit stop)
        # __exit__ sees _stopped=True and skips
        print_calls = mock_console.print.call_args_list
        summary_count = sum(1 for c in print_calls if "result" in str(c))
        assert summary_count == 1

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_auto_exit_summary(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """If stop() is never called, __exit__ prints a generic summary."""
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

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

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_delta_calculation(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        """Token delta = after - before."""
        acc = LLMUsageAccumulator()
        acc.record(LLMUsage(model="m", input_tokens=100, output_tokens=20, cost_usd=0.005))
        mock_acc_fn.return_value = acc

        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Test") as status:
            # Simulate an LLM call recording additional tokens
            acc.record(LLMUsage(model="m", input_tokens=200, output_tokens=50, cost_usd=0.010))
            delta = status._get_token_delta()

        assert delta.input_tokens == 200
        assert delta.output_tokens == 50
        assert delta.cost_usd == pytest.approx(0.010)

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_delta_zero_when_no_calls(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """No LLM calls during context → zero delta."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc

        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

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

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_summary_includes_tokens_and_cost(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """When there are tokens, the summary shows ↑in ↓out $cost."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Test") as status:
            acc.record(LLMUsage(model="m", input_tokens=150, output_tokens=30, cost_usd=0.004))
            status.stop("analyze · Berserk")

        # Inspect the printed line
        print_args = [str(c) for c in mock_console.print.call_args_list]
        summary_line = next((p for p in print_args if "analyze" in p), "")
        assert "↑150" in summary_line
        assert "↓30" in summary_line
        assert "$0.004" in summary_line

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_summary_no_tokens_still_shows_time(
        self, mock_acc_fn: MagicMock, mock_console: MagicMock
    ) -> None:
        """Offline fallback: no tokens, still shows elapsed time."""
        acc = LLMUsageAccumulator()
        mock_acc_fn.return_value = acc
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Test") as status:
            # No LLM calls — simulates offline
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

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_model_in_spinner(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Classifying...", model=ANTHROPIC_PRIMARY) as status:
            status.stop("done")

        init_call = mock_console.status.call_args[0][0]
        assert ANTHROPIC_PRIMARY in init_call

    @patch("core.ui.status.console")
    @patch("core.ui.status.get_usage_accumulator")
    def test_no_model(self, mock_acc_fn: MagicMock, mock_console: MagicMock) -> None:
        mock_acc_fn.return_value = LLMUsageAccumulator()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        with GeodeStatus("Working...") as status:
            status.stop("done")

        init_call = mock_console.status.call_args[0][0]
        assert "Working..." in init_call
