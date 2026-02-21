"""Tests for evaluator node (dry-run mode)."""

from __future__ import annotations

from geode.nodes.evaluators import (
    EVALUATOR_TYPES,
    _dry_run_result,
    _format_axes_schema,
)


class TestEvaluatorTypes:
    def test_three_evaluators(self):
        assert len(EVALUATOR_TYPES) == 3

    def test_expected_names(self):
        expected = {"quality_judge", "hidden_value", "community_momentum"}
        assert set(EVALUATOR_TYPES) == expected


class TestDryRunResult:
    def test_cowboy_bebop_quality(self):
        result = _dry_run_result("quality_judge", "Cowboy Bebop")
        assert result.evaluator_type == "quality_judge"
        assert result.composite_score == 82.0
        assert "a_score" in result.axes
        assert len(result.axes) == 8  # Full 8-axis

    def test_cowboy_bebop_hidden(self):
        result = _dry_run_result("hidden_value", "Cowboy Bebop")
        assert result.axes["d_score"] == 5.0  # Extreme acquisition gap

    def test_berserk_quality_s_tier(self):
        result = _dry_run_result("quality_judge", "Berserk")
        assert result.composite_score == 80.0
        assert len(result.axes) == 8

    def test_berserk_momentum(self):
        result = _dry_run_result("community_momentum", "Berserk")
        assert result.composite_score == 92.0

    def test_ghost_hidden_low(self):
        result = _dry_run_result("hidden_value", "Ghost in the Shell")
        assert result.composite_score == 25.0

    def test_all_ips_all_evaluators(self):
        ips = ["Cowboy Bebop", "Berserk", "Ghost in the Shell"]
        for ip in ips:
            for etype in EVALUATOR_TYPES:
                result = _dry_run_result(etype, ip)
                assert 0 <= result.composite_score <= 100
                for val in result.axes.values():
                    assert 1.0 <= val <= 5.0

    def test_unknown_ip_falls_back(self):
        result = _dry_run_result("quality_judge", "Unknown")
        assert result.composite_score == 82.0  # Cowboy Bebop default


class TestFormatAxesSchema:
    def test_quality_judge_schema(self):
        schema = _format_axes_schema("quality_judge")
        assert "a_score" in schema
        assert "float 1-5" in schema

    def test_hidden_value_schema(self):
        schema = _format_axes_schema("hidden_value")
        assert "d_score" in schema
