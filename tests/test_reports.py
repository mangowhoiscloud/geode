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
    "analyst_confidence": 82.0,
    "subscores": {
        "psm": 75.0,
        "quality": 82.0,
        "recovery": 71.0,
        "growth": 85.0,
        "momentum": 76.0,
        "dev": 60.0,
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
            "confidence": 85.0,
        },
        {
            "analyst_type": "market_position",
            "score": 3.5,
            "key_finding": "Crowded segment",
            "confidence": 78.0,
        },
    ],
    "evaluations": {
        "market_evaluator": {
            "evaluator_type": "market_evaluator",
            "composite_score": 72.5,
            "rationale": "Strong market signals but limited platform reach.",
            "axes": {"d_score": 3.8, "e_score": 3.2, "f_score": 4.1},
        },
        "quality_evaluator": {
            "evaluator_type": "quality_evaluator",
            "composite_score": 80.0,
            "rationale": "High production value with polished mechanics.",
            "axes": {"a_score": 4.5, "b_score": 3.9},
        },
    },
    "psm_result": {
        "att_pct": 31.2,
        "z_value": 2.45,
        "rosenbaum_gamma": 1.82,
        "max_smd": 0.048,
        "exposure_lift_score": 75.0,
        "psm_valid": True,
    },
    "guardrails": {
        "all_passed": True,
        "g1_schema": True,
        "g2_range": True,
        "g3_grounding": True,
        "g4_consistency": True,
        "grounding_ratio": 0.85,
        "details": ["Schema OK", "Range OK"],
    },
    "biasbuster": {
        "overall_pass": True,
        "confirmation_bias": False,
        "recency_bias": False,
        "anchoring_bias": False,
        "position_bias": False,
        "verbosity_bias": False,
        "self_enhancement_bias": False,
        "explanation": "No significant bias detected across all dimensions.",
    },
    "signals": {
        "youtube_views": 25000000,
        "reddit_subscribers": 520000,
        "fan_art_yoy_pct": 65.0,
        "google_trends_index": 78,
        "twitter_mentions_monthly": 120000,
        "cosplay_events_annual": 200,
        "mod_patch_activity": "medium",
        "genre_fit_keywords": ["action RPG", "souls-like"],
        "game_sales_data": "~100K units",
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
        assert "Guardrails" in report

    def test_detailed_includes_evaluators(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Evaluator Results" in report
        assert "market_evaluator" in report
        assert "quality_evaluator" in report
        assert "Axis Breakdown" in report

    def test_detailed_includes_psm(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "PSM Engine" in report
        assert "VALID" in report
        assert "31.2" in report
        assert "2.45" in report

    def test_detailed_includes_scoring_breakdown(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Scoring Breakdown" in report
        assert "Weight" in report
        assert "Weighted" in report
        assert "Confidence Multiplier" in report

    def test_detailed_includes_biasbuster(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "BiasBuster" in report
        assert "Confirmation" in report
        assert "no bias detected" in report.lower() or "PASS" in report

    def test_detailed_includes_signals(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "External Signals" in report
        assert "YouTube Views" in report
        assert "Reddit Subscribers" in report
        assert "Google Trends Index" in report

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
        assert "evaluations" in data
        assert "psm_result" in data
        assert "guardrails" in data
        assert "biasbuster" in data
        assert "signals" in data
        assert "analyst_confidence" in data

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
        assert "Guardrails" in report

    def test_detailed_html_has_evaluators(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "Evaluator Results" in report
        assert "market_evaluator" in report
        assert "72.5" in report

    def test_detailed_html_has_psm(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "PSM Engine" in report
        assert "VALID" in report
        assert "+31.2%" in report

    def test_detailed_html_has_scoring_breakdown(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "Scoring Breakdown" in report
        assert "Weighted Sum" in report

    def test_detailed_html_has_biasbuster(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "BiasBuster" in report
        assert "NO BIAS DETECTED" in report

    def test_detailed_html_has_signals(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "External Signals" in report
        assert "YouTube Views" in report

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
