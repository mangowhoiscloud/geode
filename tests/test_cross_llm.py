"""Tests for cross-LLM verification module."""

from __future__ import annotations

from core.state import AnalysisResult
from core.verification.cross_llm import (
    DEFAULT_AGREEMENT_THRESHOLD,
    _calc_agreement,
    run_cross_llm_check,
)

# Backward compat alias for tests
AGREEMENT_THRESHOLD = DEFAULT_AGREEMENT_THRESHOLD


class TestCalcAgreement:
    def test_perfect_agreement(self):
        assert _calc_agreement([4.0, 4.0, 4.0, 4.0]) == 1.0

    def test_single_rater(self):
        assert _calc_agreement([3.5]) == 1.0

    def test_empty_list(self):
        assert _calc_agreement([]) == 1.0

    def test_high_agreement(self):
        agreement = _calc_agreement([4.0, 4.1, 3.9, 4.0])
        assert agreement >= 0.95  # Very close scores → high agreement

    def test_low_agreement(self):
        agreement = _calc_agreement([1.0, 5.0, 1.0, 5.0])
        assert agreement < 0.5

    def test_moderate_spread(self):
        agreement = _calc_agreement([2.0, 3.0, 4.0, 5.0])
        assert 0.5 < agreement < 1.0

    def test_bounded_zero_to_one(self):
        agreement = _calc_agreement([1.0, 5.0])
        assert 0.0 <= agreement <= 1.0

    def test_two_identical(self):
        assert _calc_agreement([3.0, 3.0]) == 1.0


class TestRunCrossLLMCheck:
    def _make_analyses(
        self, scores: list[float], confidences: list[float] | None = None
    ) -> list[AnalysisResult]:
        if confidences is None:
            confidences = [80.0] * len(scores)
        return [
            AnalysisResult(
                analyst_type=f"analyst_{i}",
                score=s,
                key_finding="test",
                reasoning="test reasoning",
                confidence=c,
            )
            for i, (s, c) in enumerate(zip(scores, confidences, strict=True))
        ]

    def test_insufficient_analysts(self):
        state = {"analyses": self._make_analyses([4.0])}
        result = run_cross_llm_check(state)
        assert result["passed"] is True
        assert result["cross_llm_agreement"] == 1.0
        assert result["n_raters"] == 1

    def test_no_analyses(self):
        state: dict = {"analyses": []}
        result = run_cross_llm_check(state)
        assert result["passed"] is True

    def test_high_agreement_passes(self):
        state = {"analyses": self._make_analyses([4.0, 4.1, 3.9, 4.0])}
        result = run_cross_llm_check(state)
        assert result["passed"] is True
        assert result["cross_llm_agreement"] >= AGREEMENT_THRESHOLD

    def test_low_agreement_fails(self):
        state = {"analyses": self._make_analyses([1.0, 5.0, 1.0, 5.0], [20.0, 90.0, 20.0, 90.0])}
        result = run_cross_llm_check(state)
        assert result["passed"] is False

    def test_result_keys(self):
        state = {"analyses": self._make_analyses([3.5, 4.0, 3.8, 4.2])}
        result = run_cross_llm_check(state)
        assert "cross_llm_agreement" in result
        assert "score_agreement" in result
        assert "confidence_agreement" in result
        assert result["metric"] == "agreement_coefficient"
        assert "threshold" in result

    def test_berserk_dry_run_scores(self):
        """Test with typical Berserk dry-run analyst scores (high agreement)."""
        state = {"analyses": self._make_analyses([4.5, 4.3, 4.6, 4.2])}
        result = run_cross_llm_check(state)
        assert result["passed"] is True
        assert result["cross_llm_agreement"] >= 0.90
