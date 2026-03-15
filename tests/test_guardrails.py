"""Tests for guardrails G1-G4 and BiasBuster."""

from __future__ import annotations

from core.state import (
    AnalysisResult,
    EvaluatorResult,
    GuardrailResult,
    PSMResult,
)
from core.verification.guardrails import (
    _g1_schema,
    _g2_range,
    _g3_grounding,
    _g4_consistency,
    _validate_analyst_ranges,
    _validate_evaluator_ranges,
    run_guardrails,
)


def _make_analysis(analyst_type: str = "game_mechanics", score: float = 4.0) -> AnalysisResult:
    return AnalysisResult(
        analyst_type=analyst_type,
        score=score,
        key_finding="test",
        reasoning="test reasoning",
        evidence=["evidence1"],
    )


def _make_full_state(**overrides) -> dict:
    """Create a complete state dict that passes all guardrails."""
    base = {
        "analyses": [_make_analysis("game_mechanics", 4.2), _make_analysis("discovery", 3.8)],
        "evaluations": {
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={
                    "a_score": 4.0,
                    "b_score": 3.5,
                    "c_score": 4.0,
                    "m_score": 3.8,
                    "n_score": 4.0,
                },
                composite_score=78.0,
                rationale="test",
            ),
        },
        "psm_result": PSMResult(
            att_pct=31.2,
            z_value=2.67,
            rosenbaum_gamma=1.8,
            max_smd=0.05,
            exposure_lift_score=78.0,
            psm_valid=True,
        ),
        "final_score": 76.2,
        "tier": "A",
    }
    base.update(overrides)
    return base


class TestG1Schema:
    def test_all_present(self):
        state = _make_full_state()
        passed, msg = _g1_schema(state)
        assert passed
        assert "Schema OK" in msg

    def test_missing_analyses(self):
        state = _make_full_state(analyses=[])
        passed, msg = _g1_schema(state)
        assert not passed
        assert "Missing analyses" in msg

    def test_missing_final_score(self):
        state = _make_full_state()
        del state["final_score"]
        passed, msg = _g1_schema(state)
        assert not passed


class TestG2Range:
    def test_valid_ranges(self):
        state = _make_full_state()
        passed, msg = _g2_range(state)
        assert passed

    def test_final_score_out_of_range(self):
        state = _make_full_state(final_score=150.0)
        passed, msg = _g2_range(state)
        assert not passed
        assert "Final score" in msg


class TestValidateAnalystRanges:
    def test_valid(self):
        analyses = [_make_analysis(score=4.0)]
        errors = _validate_analyst_ranges(analyses)
        assert len(errors) == 0


class TestValidateEvaluatorRanges:
    def test_valid(self):
        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 3.0, "e_score": 4.0, "f_score": 2.0},
                composite_score=50.0,
                rationale="test",
            ),
        }
        errors = _validate_evaluator_ranges(evaluations)
        assert len(errors) == 0


class TestG3Grounding:
    def test_grounded(self):
        state = _make_full_state()
        passed, msg, ratio = _g3_grounding(state)
        assert passed

    def test_missing_evidence(self):
        analysis = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=[],
        )
        state = _make_full_state(analyses=[analysis])
        passed, msg, ratio = _g3_grounding(state)
        assert not passed
        assert "no evidence" in msg

    def test_grounding_ratio_with_signals(self):
        analyses = [
            AnalysisResult(
                analyst_type="growth_potential",
                score=4.0,
                key_finding="test",
                reasoning="test reasoning",
                evidence=["YouTube 25M views", "ungrounded claim"],
            ),
        ]
        state = _make_full_state(analyses=analyses)
        signals = {"youtube_views": 25000000, "reddit_subscribers": 520000}
        passed, msg, ratio = _g3_grounding(state, signal_data=signals)
        assert passed
        assert 0.0 < ratio <= 1.0
        assert "Grounding:" in msg

    def test_ungrounded_evidence_soft_warning(self):
        """Ungrounded evidence triggers soft warning, not hard fail."""
        analyses = [
            AnalysisResult(
                analyst_type="growth_potential",
                score=4.0,
                key_finding="test",
                reasoning="test reasoning",
                evidence=["completely fabricated claim"],
            ),
        ]
        state = _make_full_state(analyses=analyses)
        signals = {"youtube_views": 25000000}
        passed, msg, ratio = _g3_grounding(state, signal_data=signals)
        assert passed  # soft warning, not hard fail
        assert "review recommended" in msg
        assert ratio == 0.0


class TestG4Consistency:
    def test_consistent(self):
        state = _make_full_state()
        passed, msg = _g4_consistency(state)
        assert passed

    def test_single_analyst(self):
        state = _make_full_state(analyses=[_make_analysis(score=4.0)])
        passed, msg = _g4_consistency(state)
        assert passed  # < 2 analysts → OK


class TestRunGuardrails:
    def test_all_pass(self):
        state = _make_full_state()
        result = run_guardrails(state)
        assert isinstance(result, GuardrailResult)
        assert result.all_passed
        assert result.g1_schema
        assert result.g2_range
        assert result.g3_grounding
        assert result.g4_consistency
        assert len(result.details) == 4
