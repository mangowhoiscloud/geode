"""Tests for L5 Report generation."""

from __future__ import annotations

import json
from typing import Any

import pytest
from core.extensibility.reports import (
    ReportFormat,
    ReportGenerator,
    ReportTemplate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_RESULT: dict[str, Any] = {
    "ip_name": "TestGame",
    "final_score": 78.5,
    "tier": "A",
    "subscores": {
        "quality": 82.0,
        "recovery": 71.0,
        "growth": 85.0,
        "momentum": 76.0,
    },
    "synthesis": {
        "undervaluation_cause": "undermarketed",
        "action_type": "marketing_boost",
        "value_narrative": "TestGame has strong mechanics but low visibility.",
        "target_segment": "Achievers",
    },
    "analyses": [
        {
            "analyst_type": "game_mechanics",
            "score": 4.2,
            "key_finding": "Strong gameplay loop",
        },
        {
            "analyst_type": "market_position",
            "score": 3.5,
            "key_finding": "Crowded segment",
        },
    ],
    "guardrails": {
        "all_passed": True,
        "details": ["Schema OK", "Range OK"],
    },
}

_MINIMAL_RESULT: dict[str, Any] = {
    "ip_name": "MinimalIP",
    "final_score": 50.0,
    "tier": "C",
}


@pytest.fixture
def generator() -> ReportGenerator:
    return ReportGenerator()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReportFormat:
    def test_enum_values(self):
        assert ReportFormat.HTML.value == "html"
        assert ReportFormat.JSON.value == "json"
        assert ReportFormat.MARKDOWN.value == "markdown"


class TestReportTemplate:
    def test_enum_values(self):
        assert ReportTemplate.SUMMARY.value == "summary"
        assert ReportTemplate.DETAILED.value == "detailed"
        assert ReportTemplate.EXECUTIVE.value == "executive"


class TestMarkdownReport:
    def test_summary(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.SUMMARY,
        )
        assert "# GEODE Analysis" in report
        assert "TestGame" in report
        assert "78.5" in report
        assert "**A**" in report
        # Summary should NOT have sub-scores
        assert "Sub-Scores" not in report

    def test_detailed_includes_analyses(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Analyst Results" in report
        assert "game_mechanics" in report
        assert "market_position" in report
        assert "Verification" in report

    def test_executive_includes_subscores(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.EXECUTIVE,
        )
        assert "Sub-Scores" in report
        assert "Quality" in report
        assert "Synthesis" in report

    def test_minimal_result(self, generator: ReportGenerator):
        report = generator.generate(
            _MINIMAL_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.SUMMARY,
        )
        assert "MinimalIP" in report
        assert "50.0" in report


class TestJsonReport:
    def test_summary_json(self, generator: ReportGenerator):
        raw = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.JSON,
            template=ReportTemplate.SUMMARY,
        )
        data = json.loads(raw)
        assert data["ip_name"] == "TestGame"
        assert data["final_score"] == 78.5
        assert data["report_type"] == "summary"
        # Summary should NOT include subscores
        assert "subscores" not in data

    def test_detailed_json_includes_analyses(self, generator: ReportGenerator):
        raw = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.JSON,
            template=ReportTemplate.DETAILED,
        )
        data = json.loads(raw)
        assert "analyses" in data
        assert len(data["analyses"]) == 2
        assert "subscores" in data

    def test_executive_json_has_subscores_no_analyses(self, generator: ReportGenerator):
        raw = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.JSON,
            template=ReportTemplate.EXECUTIVE,
        )
        data = json.loads(raw)
        assert "subscores" in data
        assert "analyses" not in data


class TestHtmlReport:
    def test_summary_html(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.SUMMARY,
        )
        assert "<!DOCTYPE html>" in report
        assert "TestGame" in report
        assert "78.5" in report
        assert "<style>" in report  # Inline CSS

    def test_detailed_html_has_tables(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "<table>" in report
        assert "game_mechanics" in report
        assert "Verification" in report

    def test_tier_class_high(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.SUMMARY,
        )
        assert "tier-badge-a" in report

    def test_tier_class_low(self, generator: ReportGenerator):
        result = {**_SAMPLE_RESULT, "tier": "C"}
        report = generator.generate(
            result,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.SUMMARY,
        )
        assert "tier-badge-c" in report

    def test_empty_result(self, generator: ReportGenerator):
        report = generator.generate(
            {},
            fmt=ReportFormat.HTML,
            template=ReportTemplate.SUMMARY,
        )
        assert "Unknown IP" in report
        assert "0.0" in report
