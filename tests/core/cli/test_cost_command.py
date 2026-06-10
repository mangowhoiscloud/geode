"""Tests for /cost command — LLM cost dashboard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.cli.commands import cmd_cost


@pytest.fixture
def mock_tracker():
    """Mock token tracker with sample accumulator."""
    tracker = MagicMock()
    acc = MagicMock()
    acc.calls = [MagicMock(), MagicMock()]
    acc.total_input_tokens = 1500
    acc.total_output_tokens = 300
    acc.total_cost_usd = 0.0234
    tracker.accumulator = acc
    return tracker


@pytest.fixture
def mock_store():
    """Mock usage store with sample summaries."""
    store = MagicMock()
    store.get_monthly_summary.return_value = {
        "total_calls": 42,
        "total_cost": 1.23,
        "by_model": {
            "claude-opus-4-6": {"calls": 30, "cost": 1.00},
            "claude-haiku-4-5-20251001": {"calls": 12, "cost": 0.23},
        },
    }
    store.get_daily_summary.return_value = {
        "date": "2026-03-18",
        "total_calls": 5,
        "total_cost": 0.15,
        "by_model": {"claude-opus-4-6": {"calls": 5, "cost": 0.15}},
    }
    rec = MagicMock()
    rec.ts = 1742292000.0
    rec.model = "claude-opus-4-6"
    rec.input_tokens = 500
    rec.output_tokens = 100
    rec.cost_usd = 0.005
    store.get_recent_records.return_value = [rec]
    return store


class TestCmdCost:
    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_session_summary(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("")  # no error

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_session_no_calls(self, mock_gt, mock_gs, mock_store):
        tracker = MagicMock()
        tracker.accumulator.calls = []
        mock_gt.return_value = tracker
        mock_gs.return_value = mock_store
        cmd_cost("session")  # no error, shows "no calls yet"

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_daily_subcommand(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("daily")  # no error
        mock_store.get_daily_summary.assert_called_once()

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_today_alias(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("today")
        mock_store.get_daily_summary.assert_called_once()

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_recent_subcommand(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("recent")  # no error
        mock_store.get_recent_records.assert_called_once_with(10)

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_recent_empty(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_store.get_recent_records.return_value = []
        mock_gs.return_value = mock_store
        cmd_cost("recent")  # no error, shows "No recent records"

    @patch("core.cli.commands._set_cost_budget")
    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_budget_set(self, mock_gt, mock_gs, mock_set, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("budget 50.00")
        mock_set.assert_called_once_with(50.0)

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_budget_invalid(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("budget abc")  # no crash

    @patch("core.cli.commands._get_cost_budget")
    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_budget_show(self, mock_gt, mock_gs, mock_get, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        mock_get.return_value = 100.0
        cmd_cost("budget")  # no error

    @patch("core.llm.usage_store.get_usage_store")
    @patch("core.llm.token_tracker.get_tracker")
    def test_unknown_subcommand(self, mock_gt, mock_gs, mock_tracker, mock_store):
        mock_gt.return_value = mock_tracker
        mock_gs.return_value = mock_store
        cmd_cost("foobar")  # shows usage


class TestBudgetBar:
    def test_budget_bar_green(self):
        from core.cli.commands import _budget_bar

        bar = _budget_bar(30.0)
        assert "success" in bar
        assert "30%" in bar

    def test_budget_bar_warning(self):
        from core.cli.commands import _budget_bar

        bar = _budget_bar(75.0)
        assert "warning" in bar

    def test_budget_bar_critical(self):
        from core.cli.commands import _budget_bar

        bar = _budget_bar(95.0)
        assert "error" in bar

    def test_budget_bar_over_100(self):
        from core.cli.commands import _budget_bar

        bar = _budget_bar(120.0)
        assert "120%" in bar  # shows actual percentage, bar capped at 100%


class TestBudgetPersistence:
    def test_get_budget_no_file(self, tmp_path, monkeypatch):
        from core.cli.commands import _get_cost_budget

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GEODE_MONTHLY_BUDGET", raising=False)
        assert _get_cost_budget() == 0.0

    def test_get_budget_from_env(self, monkeypatch):
        from core.cli.commands import _get_cost_budget

        monkeypatch.setenv("GEODE_MONTHLY_BUDGET", "42.50")
        assert _get_cost_budget() == 42.50

    def test_set_and_get_budget(self, tmp_path, monkeypatch):
        from core.cli.commands import _get_cost_budget, _set_cost_budget

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GEODE_MONTHLY_BUDGET", raising=False)
        _set_cost_budget(75.0)
        assert _get_cost_budget() == 75.0

    def test_set_budget_creates_dir(self, tmp_path, monkeypatch):
        from core.cli.commands import _set_cost_budget

        monkeypatch.chdir(tmp_path)
        _set_cost_budget(100.0)
        assert (tmp_path / ".geode" / "config.toml").exists()
