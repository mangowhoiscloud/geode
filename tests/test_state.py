"""Tests for GeodeState and Pydantic models."""

import pytest
from core.state import (
    AnalysisResult,
    EvaluatorResult,
    PSMResult,
    SynthesisResult,
)
from pydantic import ValidationError


class TestAnalysisResult:
    def test_valid(self):
        r = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.2,
            key_finding="Strong mechanics",
            reasoning="Good gameplay loop",
            evidence=["evidence1"],
        )
        assert r.score == 4.2

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            AnalysisResult(
                analyst_type="game_mechanics",
                score=6.0,
                key_finding="x",
                reasoning="x",
            )

    def test_score_below_range(self):
        with pytest.raises(ValidationError):
            AnalysisResult(
                analyst_type="game_mechanics",
                score=0.5,
                key_finding="x",
                reasoning="x",
            )


class TestEvaluatorResult:
    def test_valid_quality_judge_5_axes(self):
        """5 axes subset is still valid."""
        r = EvaluatorResult(
            evaluator_type="quality_judge",
            axes={"a_score": 4.0, "b_score": 3.5, "c_score": 4.1, "m_score": 3.8, "n_score": 4.0},
            composite_score=78.0,
            rationale="Solid quality",
        )
        assert r.composite_score == 78.0

    def test_valid_quality_judge_8_axes(self):
        """Full 8 axes including B.1, C.1, C.2."""
        r = EvaluatorResult(
            evaluator_type="quality_judge",
            axes={
                "a_score": 4.0,
                "b_score": 3.5,
                "c_score": 4.1,
                "b1_score": 3.9,
                "c1_score": 4.0,
                "c2_score": 3.8,
                "m_score": 3.8,
                "n_score": 4.0,
            },
            composite_score=82.0,
            rationale="Full 8-axis evaluation",
        )
        assert len(r.axes) == 8

    def test_valid_hidden_value(self):
        r = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 5.0, "e_score": 2.0, "f_score": 4.0},
            composite_score=50.0,
            rationale="High acquisition gap",
        )
        assert r.axes["d_score"] == 5.0

    def test_valid_community_momentum(self):
        r = EvaluatorResult(
            evaluator_type="community_momentum",
            axes={"j_score": 4.3, "k_score": 4.1, "l_score": 3.9},
            composite_score=78.0,
            rationale="Strong growth",
        )
        assert len(r.axes) == 3

    def test_composite_out_of_range(self):
        with pytest.raises(ValidationError):
            EvaluatorResult(
                evaluator_type="quality_judge",
                axes={},
                composite_score=150.0,
                rationale="x",
            )

    def test_invalid_axis_key(self):
        """Misspelled key should fail validation."""
        with pytest.raises(ValidationError, match="Invalid axis keys"):
            EvaluatorResult(
                evaluator_type="quality_judge",
                axes={"A_score": 4.0},  # Wrong: should be a_score
                composite_score=80.0,
                rationale="x",
            )

    def test_axis_value_out_of_range(self):
        """Axis value > 5.0 should fail validation."""
        with pytest.raises(ValidationError, match="out of range"):
            EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 6.0, "e_score": 3.0, "f_score": 3.0},
                composite_score=50.0,
                rationale="x",
            )

    def test_unknown_evaluator_type(self):
        """Unknown evaluator_type should fail."""
        with pytest.raises(ValidationError, match="Unknown evaluator_type"):
            EvaluatorResult(
                evaluator_type="nonexistent",
                axes={"x": 3.0},
                composite_score=50.0,
                rationale="x",
            )

    def test_partial_axes_allowed(self):
        """Subset of expected keys is valid (LLM may omit some)."""
        r = EvaluatorResult(
            evaluator_type="quality_judge",
            axes={"a_score": 4.0, "b_score": 3.5},  # partial
            composite_score=75.0,
            rationale="Partial evaluation",
        )
        assert len(r.axes) == 2


class TestPSMResult:
    def test_valid(self):
        r = PSMResult(
            att_pct=31.2,
            z_value=2.67,
            rosenbaum_gamma=1.8,
            max_smd=0.05,
            exposure_lift_score=78.0,
            psm_valid=True,
        )
        assert r.psm_valid is True

    def test_validity_flags(self):
        r = PSMResult(
            att_pct=10.0,
            z_value=1.2,  # fails
            rosenbaum_gamma=2.5,  # fails
            max_smd=0.05,
            exposure_lift_score=45.0,
            psm_valid=False,
        )
        assert r.psm_valid is False


class TestSynthesisResult:
    def test_valid_cause(self):
        r = SynthesisResult(
            undervaluation_cause="undermarketed",
            action_type="marketing_boost",
            value_narrative="Test narrative",
            target_gamer_segment="Achievers",
        )
        assert r.undervaluation_cause == "undermarketed"

    def test_invalid_cause(self):
        with pytest.raises(ValidationError):
            SynthesisResult(
                undervaluation_cause="invalid_cause",
                action_type="marketing_boost",
                value_narrative="x",
                target_gamer_segment="x",
            )

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            SynthesisResult(
                undervaluation_cause="undermarketed",
                action_type="nonexistent_action",
                value_narrative="x",
                target_gamer_segment="x",
            )

    def test_all_valid_cause_action_pairs(self):
        """Verify all 6 cause → 5 action pairs from §13.9.3."""
        pairs = [
            ("undermarketed", "marketing_boost"),
            ("conversion_failure", "monetization_pivot"),
            ("monetization_misfit", "monetization_pivot"),
            ("niche_gem", "platform_expansion"),
            ("timing_mismatch", "timing_optimization"),
            ("discovery_failure", "community_activation"),
        ]
        for cause, action in pairs:
            r = SynthesisResult(
                undervaluation_cause=cause,
                action_type=action,
                value_narrative=f"Test {cause}",
                target_gamer_segment="Test segment",
            )
            assert r.undervaluation_cause == cause
            assert r.action_type == action
