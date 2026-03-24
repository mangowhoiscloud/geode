"""Tests for L5 Report generation."""

from __future__ import annotations

import json
from typing import Any

import pytest
from core.skills.reports import (
    ReportFormat,
    ReportGenerator,
    ReportTemplate,
    _format_analyst_reasoning_html,
    _format_analyst_reasoning_md,
    _format_cross_llm_html,
    _format_cross_llm_md,
    _format_decision_tree_html,
    _format_decision_tree_md,
    _format_rights_risk_html,
    _format_rights_risk_md,
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
            "reasoning": "The core loop rewards mastery through progressive difficulty scaling.",
            "evidence": ["Steam reviews cite 'addictive loop'", "Average session 3.2h"],
            "model_provider": "claude-opus-4-6",
        },
        {
            "analyst_type": "market_position",
            "score": 3.5,
            "key_finding": "Crowded segment",
            "confidence": 78.0,
            "reasoning": "Competing against 12 titles in the same sub-genre released this quarter.",
            "evidence": ["SteamSpy genre overlap 68%", "Metacritic median 74"],
            "model_provider": "gpt-5.4",
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
        "hidden_value": {
            "evaluator_type": "hidden_value",
            "composite_score": 71.0,
            "rationale": "Strong discovery but limited monetization path.",
            "axes": {"d_score": 3.5, "e_score": 2.8, "f_score": 4.0},
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
    "cross_llm": {
        "cross_llm_agreement": 0.82,
        "models_compared": ["claude-opus-4-6", "gpt-5.4"],
        "passed": True,
        "verification_mode": "full_rescore",
        "secondary_score": 76.3,
    },
    "rights_risk": {
        "status": "NEGOTIABLE",
        "risk_score": 35,
        "concerns": [
            "Existing exclusive console license until 2027",
            "Partial rights held by third-party publisher",
        ],
        "recommendation": "Negotiate limited digital distribution rights with current holder.",
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


# ---------------------------------------------------------------------------
# Cross-LLM Verification formatter tests
# ---------------------------------------------------------------------------


class TestCrossLlmMd:
    def test_populated_data(self):
        result = _format_cross_llm_md(_SAMPLE_RESULT["cross_llm"])
        assert "## Cross-LLM Verification" in result
        assert "0.82" in result
        assert "PASS" in result
        assert "full_rescore" in result
        assert "claude-opus-4-6" in result
        assert "gpt-5.4" in result
        assert "76.3" in result

    def test_empty_data(self):
        assert _format_cross_llm_md({}) == ""

    def test_failed_agreement(self):
        data = {
            "cross_llm_agreement": 0.45,
            "models_compared": ["claude-opus-4-6", "gpt-5.4"],
            "passed": False,
            "verification_mode": "spot_check",
        }
        result = _format_cross_llm_md(data)
        assert "FAIL" in result
        assert "0.45" in result
        assert "spot_check" in result

    def test_no_secondary_score(self):
        data = {
            "cross_llm_agreement": 0.90,
            "models_compared": [],
            "passed": True,
            "verification_mode": "full_rescore",
        }
        result = _format_cross_llm_md(data)
        assert "Secondary" not in result


class TestCrossLlmHtml:
    def test_populated_data(self):
        result = _format_cross_llm_html(_SAMPLE_RESULT["cross_llm"])
        assert "Cross-LLM Verification" in result
        assert "0.82" in result
        assert "verify-pass" in result
        assert "full_rescore" in result
        assert "claude-opus-4-6, gpt-5.4" in result

    def test_empty_data(self):
        assert _format_cross_llm_html({}) == ""

    def test_failed_badge(self):
        data = {
            "cross_llm_agreement": 0.30,
            "models_compared": [],
            "passed": False,
            "verification_mode": "spot_check",
        }
        result = _format_cross_llm_html(data)
        assert "verify-fail" in result


class TestCrossLlmIntegration:
    """Cross-LLM sections appear in full detailed reports."""

    def test_detailed_md_includes_cross_llm(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Cross-LLM Verification" in report
        assert "0.82" in report

    def test_detailed_html_includes_cross_llm(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "Cross-LLM Verification" in report

    def test_detailed_json_includes_cross_llm(self, generator: ReportGenerator):
        raw = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.JSON,
            template=ReportTemplate.DETAILED,
        )
        data = json.loads(raw)
        assert "cross_llm" in data
        assert data["cross_llm"]["cross_llm_agreement"] == 0.82


# ---------------------------------------------------------------------------
# Rights Risk formatter tests
# ---------------------------------------------------------------------------


class TestRightsRiskMd:
    def test_populated_data(self):
        result = _format_rights_risk_md(_SAMPLE_RESULT["rights_risk"])
        assert "## IP Rights Risk" in result
        assert "NEGOTIABLE" in result
        assert "35/100" in result
        assert "Existing exclusive console license until 2027" in result
        assert "Partial rights held by third-party publisher" in result
        assert "Negotiate limited digital distribution" in result

    def test_empty_data(self):
        assert _format_rights_risk_md({}) == ""

    def test_clear_status(self):
        data = {"status": "CLEAR", "risk_score": 5, "concerns": []}
        result = _format_rights_risk_md(data)
        assert "CLEAR" in result
        assert "5/100" in result
        assert "Concerns" not in result

    def test_no_recommendation(self):
        data = {"status": "RESTRICTED", "risk_score": 90, "concerns": ["All rights held"]}
        result = _format_rights_risk_md(data)
        assert "RESTRICTED" in result
        assert "All rights held" in result


class TestRightsRiskHtml:
    def test_populated_data(self):
        result = _format_rights_risk_html(_SAMPLE_RESULT["rights_risk"])
        assert "IP Rights Risk" in result
        assert "NEGOTIABLE" in result
        assert "35/100" in result
        assert "Existing exclusive console license until 2027" in result
        assert "Negotiate limited digital distribution" in result

    def test_empty_data(self):
        assert _format_rights_risk_html({}) == ""

    def test_color_coding_clear(self):
        data = {"status": "CLEAR", "risk_score": 5, "concerns": []}
        result = _format_rights_risk_html(data)
        assert "#16a34a" in result  # green

    def test_color_coding_restricted(self):
        data = {"status": "RESTRICTED", "risk_score": 90, "concerns": []}
        result = _format_rights_risk_html(data)
        assert "#dc2626" in result  # red

    def test_color_coding_negotiable(self):
        data = {"status": "NEGOTIABLE", "risk_score": 40, "concerns": []}
        result = _format_rights_risk_html(data)
        assert "#eab308" in result  # yellow


class TestRightsRiskIntegration:
    """Rights risk sections appear in full detailed reports."""

    def test_detailed_md_includes_rights_risk(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "IP Rights Risk" in report
        assert "NEGOTIABLE" in report

    def test_detailed_html_includes_rights_risk(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "IP Rights Risk" in report

    def test_detailed_json_includes_rights_risk(self, generator: ReportGenerator):
        raw = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.JSON,
            template=ReportTemplate.DETAILED,
        )
        data = json.loads(raw)
        assert "rights_risk" in data
        assert data["rights_risk"]["status"] == "NEGOTIABLE"


# ---------------------------------------------------------------------------
# Analyst Reasoning formatter tests
# ---------------------------------------------------------------------------


class TestAnalystReasoningMd:
    def test_populated_data(self):
        result = _format_analyst_reasoning_md(_SAMPLE_RESULT["analyses"])
        assert "## Analyst Reasoning" in result
        assert "### game_mechanics" in result
        assert "(claude-opus-4-6)" in result
        assert "core loop rewards mastery" in result
        assert "Steam reviews cite 'addictive loop'" in result
        assert "Average session 3.2h" in result
        assert "### market_position" in result
        assert "(gpt-5.4)" in result
        assert "Competing against 12 titles" in result
        assert "SteamSpy genre overlap 68%" in result

    def test_empty_list(self):
        assert _format_analyst_reasoning_md([]) == ""

    def test_no_reasoning(self):
        """Analysts without reasoning should produce empty output."""
        analyses = [
            {"analyst_type": "test", "score": 3.0, "key_finding": "ok"},
        ]
        assert _format_analyst_reasoning_md(analyses) == ""

    def test_partial_reasoning(self):
        """Only analysts with reasoning/evidence should appear."""
        analyses = [
            {
                "analyst_type": "has_reasoning",
                "score": 4.0,
                "reasoning": "Good analysis",
                "evidence": ["ev1"],
            },
            {"analyst_type": "no_reasoning", "score": 3.0},
        ]
        result = _format_analyst_reasoning_md(analyses)
        assert "has_reasoning" in result
        assert "no_reasoning" not in result


class TestAnalystReasoningHtml:
    def test_populated_data(self):
        result = _format_analyst_reasoning_html(_SAMPLE_RESULT["analyses"])
        assert "Analyst Reasoning" in result
        assert "game_mechanics" in result
        assert "claude-opus-4-6" in result
        assert "core loop rewards mastery" in result
        assert "<li>" in result  # evidence list items
        assert "Steam reviews" in result

    def test_empty_list(self):
        assert _format_analyst_reasoning_html([]) == ""

    def test_no_reasoning(self):
        analyses = [{"analyst_type": "test", "score": 3.0}]
        assert _format_analyst_reasoning_html(analyses) == ""


class TestAnalystReasoningIntegration:
    """Analyst reasoning sections in full detailed reports."""

    def test_detailed_md_includes_reasoning(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Analyst Reasoning" in report
        assert "core loop rewards mastery" in report

    def test_detailed_html_includes_reasoning(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "Analyst Reasoning" in report

    def test_evidence_chain_in_analyses_md(self, generator: ReportGenerator):
        """The Evidence Chain sub-section should also appear in _format_analyses_md."""
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Evidence Chain" in report
        assert "Steam reviews cite 'addictive loop'" in report


# ---------------------------------------------------------------------------
# Decision Tree formatter tests
# ---------------------------------------------------------------------------


class TestDecisionTreeMd:
    def test_populated_data(self):
        result = _format_decision_tree_md(
            _SAMPLE_RESULT["synthesis"],
            _SAMPLE_RESULT["evaluations"],
        )
        assert "## Cause Classification Logic" in result
        assert "D (Discovery Difficulty): 3.5" in result
        assert "E (Monetization Capability): 2.8" in result
        assert "F (Franchise Expandability): 4.0" in result
        assert "`undermarketed`" in result
        assert "Decision Tree:" in result

    def test_empty_synthesis(self):
        assert _format_decision_tree_md({}, _SAMPLE_RESULT["evaluations"]) == ""

    def test_no_cause(self):
        synthesis = {"action_type": "marketing_boost"}
        assert _format_decision_tree_md(synthesis, _SAMPLE_RESULT["evaluations"]) == ""

    def test_no_evaluations(self):
        assert _format_decision_tree_md(_SAMPLE_RESULT["synthesis"], {}) == ""

    def test_missing_hidden_value(self):
        """When hidden_value evaluator is missing, axes default to '?'."""
        evals = {"market_evaluator": _SAMPLE_RESULT["evaluations"]["market_evaluator"]}
        result = _format_decision_tree_md(_SAMPLE_RESULT["synthesis"], evals)
        assert "D (Discovery Difficulty): ?" in result


class TestDecisionTreeHtml:
    def test_populated_data(self):
        result = _format_decision_tree_html(
            _SAMPLE_RESULT["synthesis"],
            _SAMPLE_RESULT["evaluations"],
        )
        assert "Cause Classification Logic" in result
        assert "3.5" in result  # d_score
        assert "2.8" in result  # e_score
        assert "4.0" in result  # f_score
        assert "<code>undermarketed</code>" in result

    def test_empty_synthesis(self):
        assert _format_decision_tree_html({}, _SAMPLE_RESULT["evaluations"]) == ""

    def test_no_evaluations(self):
        assert _format_decision_tree_html(_SAMPLE_RESULT["synthesis"], {}) == ""


class TestDecisionTreeIntegration:
    """Decision tree sections in full detailed reports."""

    def test_detailed_md_includes_decision_tree(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.MARKDOWN,
            template=ReportTemplate.DETAILED,
        )
        assert "Cause Classification Logic" in report
        assert "undermarketed" in report

    def test_detailed_html_includes_decision_tree(self, generator: ReportGenerator):
        report = generator.generate(
            _SAMPLE_RESULT,
            fmt=ReportFormat.HTML,
            template=ReportTemplate.DETAILED,
        )
        assert "Cause Classification Logic" in report
