"""Tests for ``geode history`` CLI subcommand."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli import app
from core.llm.usage_store import UsageStore
from typer.testing import CliRunner


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def usage_store(tmp_path: Path) -> UsageStore:
    return UsageStore(usage_dir=tmp_path / "usage")


class TestHistoryCommand:
    """Tests for the history CLI subcommand."""

    def test_history_no_data(self, runner: CliRunner, usage_store: UsageStore):
        with patch("core.llm.usage_store.UsageStore", return_value=usage_store):
            result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "No usage data" in result.output

    def test_history_with_data(self, runner: CliRunner, usage_store: UsageStore):
        usage_store.record("claude-opus-4-6", 1000, 200, 0.0148)
        usage_store.record("gpt-5.4", 500, 100, 0.005)
        with patch("core.llm.usage_store.UsageStore", return_value=usage_store):
            result = runner.invoke(app, ["history"])
        assert result.exit_code == 0
        assert "claude-opus-4-6" in result.output
        assert "gpt-5.4" in result.output
        # Should show total
        assert "Total" in result.output

    def test_history_limit(self, runner: CliRunner, usage_store: UsageStore):
        for i in range(5):
            usage_store.record(f"model-{i}", 100, 50, 0.01)
        with patch("core.llm.usage_store.UsageStore", return_value=usage_store):
            result = runner.invoke(app, ["history", "--limit", "2"])
        assert result.exit_code == 0

    def test_history_invalid_month(self, runner: CliRunner, usage_store: UsageStore):
        with patch("core.llm.usage_store.UsageStore", return_value=usage_store):
            result = runner.invoke(app, ["history", "--month", "bad"])
        assert result.exit_code == 0
        assert "Invalid month format" in result.output

    def test_history_specific_month(self, runner: CliRunner, usage_store: UsageStore):
        with patch("core.llm.usage_store.UsageStore", return_value=usage_store):
            result = runner.invoke(app, ["history", "--month", "2020-01"])
        assert result.exit_code == 0
        assert "No usage data" in result.output


class TestHistoryCommandDirect:
    """Direct tests for history output formatting (no CLI runner)."""

    def test_usage_store_monthly_summary_structure(self, tmp_path: Path):
        store = UsageStore(usage_dir=tmp_path)
        store.record("claude-opus-4-6", 1000, 200, 0.015)
        summary = store.get_monthly_summary()

        assert "year" in summary
        assert "month" in summary
        assert "total_cost" in summary
        assert "total_calls" in summary
        assert "total_input_tokens" in summary
        assert "total_output_tokens" in summary
        assert "by_model" in summary
        assert summary["total_calls"] == 1

    def test_usage_store_recent_records(self, tmp_path: Path):
        store = UsageStore(usage_dir=tmp_path)
        store.record("claude-opus-4-6", 1000, 200, 0.015)
        store.record("gpt-5.4", 500, 100, 0.005)

        recent = store.get_recent_records(limit=5)
        assert len(recent) == 2
        # Newest first
        assert recent[0].model == "gpt-5.4"
        assert recent[1].model == "claude-opus-4-6"
