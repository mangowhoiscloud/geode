"""Tests for scoring formulas."""

from core.nodes.scoring import (
    _calc_analyst_confidence,
    _calc_community_momentum,
    _calc_final_score,
    _calc_recovery_potential,
    _determine_tier,
)
from core.state import AnalysisResult, EvaluatorResult


class TestTierDetermination:
    def test_s_tier(self):
        assert _determine_tier(80.0) == "S"
        assert _determine_tier(95.0) == "S"

    def test_a_tier(self):
        assert _determine_tier(76.2) == "A"
        assert _determine_tier(60.0) == "A"

    def test_b_tier(self):
        assert _determine_tier(40.0) == "B"
        assert _determine_tier(59.9) == "B"

    def test_c_tier(self):
        assert _determine_tier(39.9) == "C"
        assert _determine_tier(0.0) == "C"


class TestRecoveryPotential:
    def test_formula(self):
        ev = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.2, "e_score": 3.8, "f_score": 4.0},
            composite_score=72.5,
            rationale="test",
        )
        # ((3.8 + 4.0) - 2) / 8 * 100 = 5.8 / 8 * 100 = 72.5
        result = _calc_recovery_potential({"hidden_value": ev})
        assert abs(result - 72.5) < 0.1

    def test_min_values(self):
        ev = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 1.0, "e_score": 1.0, "f_score": 1.0},
            composite_score=0,
            rationale="test",
        )
        result = _calc_recovery_potential({"hidden_value": ev})
        assert result == 0.0

    def test_max_values(self):
        ev = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 5.0, "e_score": 5.0, "f_score": 5.0},
            composite_score=100,
            rationale="test",
        )
        result = _calc_recovery_potential({"hidden_value": ev})
        assert result == 100.0


class TestCommunityMomentum:
    def test_formula(self):
        ev = EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.3, "k_score": 4.1, "l_score": 3.9},
            composite_score=78.0,
            rationale="test",
        )
        # ((4.3+4.1+3.9) - 3) / 12 * 100 = 9.3/12*100 = 77.5
        result = _calc_community_momentum({"community_momentum": ev})
        assert abs(result - 77.5) < 0.1


class TestAnalystConfidence:
    def test_uniform_scores(self):
        analyses = [
            AnalysisResult(analyst_type="a", score=4.0, key_finding="x", reasoning="x"),
            AnalysisResult(analyst_type="b", score=4.0, key_finding="x", reasoning="x"),
        ]
        conf = _calc_analyst_confidence(analyses)
        assert conf == 100.0  # zero variance

    def test_varied_scores(self):
        analyses = [
            AnalysisResult(analyst_type="a", score=4.2, key_finding="x", reasoning="x"),
            AnalysisResult(analyst_type="b", score=4.0, key_finding="x", reasoning="x"),
            AnalysisResult(analyst_type="c", score=4.5, key_finding="x", reasoning="x"),
            AnalysisResult(analyst_type="d", score=3.8, key_finding="x", reasoning="x"),
        ]
        conf = _calc_analyst_confidence(analyses)
        assert 85 < conf < 100  # should be high but not 100

    def test_single_analyst(self):
        analyses = [
            AnalysisResult(analyst_type="a", score=4.0, key_finding="x", reasoning="x"),
        ]
        # Single analysis → 50% (single-source penalty, Phase 1-A fix)
        assert _calc_analyst_confidence(analyses) == 50.0


class TestFinalScore:
    def test_formula(self):
        score = _calc_final_score(
            exposure_lift=78.0,
            quality=82.0,
            recovery=72.5,
            growth=68.0,
            momentum=78.0,
            developer=65.0,
            confidence=93.0,
        )
        # base = 0.25*78 + 0.20*82 + 0.18*72.5 + 0.12*68 + 0.20*78 + 0.05*65
        # = 19.5 + 16.4 + 13.05 + 8.16 + 15.6 + 3.25 = 75.96
        # multiplier = 0.7 + 0.3*93/100 = 0.7 + 0.279 = 0.979
        # final = 75.96 * 0.979 ≈ 74.36
        assert 73 < score < 77

    def test_cowboy_bebop_range(self):
        """Final score should be in A-tier range for Cowboy Bebop data."""
        score = _calc_final_score(
            exposure_lift=98.0,
            quality=82.0,
            recovery=72.5,
            growth=68.0,
            momentum=77.5,
            developer=65.6,
            confidence=95.0,
        )
        assert 60 <= score < 80  # A-tier
