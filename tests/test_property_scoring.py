"""Property-based tests for scoring formulas (boundary value approach).

Since hypothesis is not available, these tests use pytest.mark.parametrize
with systematic boundary values to cover the property-based test intent:
- Scoring weights sum to 1.0
- All subscores in [1,5] produce final_score in [0,100]
- Monotonicity: increasing subscores produce non-decreasing final_score
"""

from __future__ import annotations

import pytest
from core.domains.game_ip.nodes.scoring import (
    _calc_analyst_confidence,
    _calc_final_score,
    _determine_tier,
)


class TestScoringWeightsSum:
    """Verify that the final score weights sum to 1.0."""

    def test_weights_sum_to_one(self):
        """The six subscore weights must sum to 1.0."""
        weights = [0.25, 0.20, 0.18, 0.12, 0.20, 0.05]
        assert abs(sum(weights) - 1.0) < 1e-9


class TestFinalScoreBounds:
    """All valid subscore inputs produce final_score in [0, 100]."""

    # Boundary values for subscores (0-100 range)
    SUBSCORE_VALUES = [0.0, 1.0, 25.0, 50.0, 75.0, 99.0, 100.0]
    CONFIDENCE_VALUES = [0.0, 50.0, 100.0]

    @pytest.mark.parametrize("exposure_lift", SUBSCORE_VALUES)
    @pytest.mark.parametrize("confidence", CONFIDENCE_VALUES)
    def test_final_score_in_range(self, exposure_lift: float, confidence: float):
        """Final score should be in [0, 100] for all valid inputs."""
        score = _calc_final_score(
            exposure_lift=exposure_lift,
            quality=50.0,
            recovery=50.0,
            growth=50.0,
            momentum=50.0,
            developer=50.0,
            confidence=confidence,
        )
        assert 0.0 <= score <= 100.0, f"final_score={score} out of [0,100]"

    @pytest.mark.parametrize(
        "subscores",
        [
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),  # All minimum
            (100.0, 100.0, 100.0, 100.0, 100.0, 100.0),  # All maximum
            (50.0, 50.0, 50.0, 50.0, 50.0, 50.0),  # All middle
            (0.0, 100.0, 0.0, 100.0, 0.0, 100.0),  # Alternating
            (100.0, 0.0, 100.0, 0.0, 100.0, 0.0),  # Alternating inverse
        ],
    )
    @pytest.mark.parametrize("confidence", [0.0, 50.0, 100.0])
    def test_all_subscore_combinations(
        self,
        subscores: tuple[float, ...],
        confidence: float,
    ):
        """Final score should always be in [0, 100] across extreme combinations."""
        score = _calc_final_score(
            exposure_lift=subscores[0],
            quality=subscores[1],
            recovery=subscores[2],
            growth=subscores[3],
            momentum=subscores[4],
            developer=subscores[5],
            confidence=confidence,
        )
        assert 0.0 <= score <= 100.0

    def test_zero_inputs_produce_zero(self):
        """All-zero subscores with zero confidence should produce zero."""
        score = _calc_final_score(0, 0, 0, 0, 0, 0, confidence=0.0)
        assert score == 0.0

    def test_max_inputs_produce_max(self):
        """All-100 subscores with 100 confidence should produce 100."""
        score = _calc_final_score(100, 100, 100, 100, 100, 100, confidence=100.0)
        assert abs(score - 100.0) < 1e-9


class TestMonotonicity:
    """Increasing subscores should produce non-decreasing final_score."""

    def test_exposure_lift_monotonic(self):
        """Increasing exposure_lift should not decrease final_score."""
        prev = -1.0
        for val in range(0, 101, 10):
            score = _calc_final_score(
                exposure_lift=float(val),
                quality=50.0,
                recovery=50.0,
                growth=50.0,
                momentum=50.0,
                developer=50.0,
                confidence=80.0,
            )
            assert score >= prev, f"Monotonicity violated at exposure_lift={val}"
            prev = score

    def test_quality_monotonic(self):
        """Increasing quality should not decrease final_score."""
        prev = -1.0
        for val in range(0, 101, 10):
            score = _calc_final_score(
                exposure_lift=50.0,
                quality=float(val),
                recovery=50.0,
                growth=50.0,
                momentum=50.0,
                developer=50.0,
                confidence=80.0,
            )
            assert score >= prev, f"Monotonicity violated at quality={val}"
            prev = score

    def test_confidence_monotonic(self):
        """Increasing confidence should not decrease final_score."""
        prev = -1.0
        for val in range(0, 101, 10):
            score = _calc_final_score(
                exposure_lift=50.0,
                quality=50.0,
                recovery=50.0,
                growth=50.0,
                momentum=50.0,
                developer=50.0,
                confidence=float(val),
            )
            assert score >= prev, f"Monotonicity violated at confidence={val}"
            prev = score

    @pytest.mark.parametrize(
        "subscore_idx,label",
        [
            (0, "exposure"),
            (1, "quality"),
            (2, "recovery"),
            (3, "growth"),
            (4, "momentum"),
            (5, "developer"),
        ],
    )
    def test_each_subscore_monotonic(self, subscore_idx: int, label: str):
        """Each subscore should be individually monotonic."""
        baseline = [50.0, 50.0, 50.0, 50.0, 50.0, 50.0]
        prev = -1.0
        for val in range(0, 101, 5):
            args = list(baseline)
            args[subscore_idx] = float(val)
            score = _calc_final_score(*args, confidence=80.0)
            assert score >= prev, f"Monotonicity violated for {label} at {val}"
            prev = score


class TestTierClassification:
    """Tier boundaries should be deterministic and ordered."""

    @pytest.mark.parametrize(
        "score,expected_tier",
        [
            (0.0, "C"),
            (39.9, "C"),
            (40.0, "B"),
            (59.9, "B"),
            (60.0, "A"),
            (79.9, "A"),
            (80.0, "S"),
            (100.0, "S"),
        ],
    )
    def test_tier_boundaries(self, score: float, expected_tier: str):
        assert _determine_tier(score) == expected_tier

    def test_tier_ordering(self):
        """Higher scores should produce equal or better tiers."""
        tier_order = {"C": 0, "B": 1, "A": 2, "S": 3}
        prev_rank = -1
        for score in range(0, 101):
            tier = _determine_tier(float(score))
            rank = tier_order[tier]
            assert rank >= prev_rank, f"Tier ordering violated at score={score}"
            prev_rank = rank


class TestAnalystConfidence:
    """Analyst confidence calculation properties."""

    def test_single_analyst_returns_100(self):
        """Single analyst should return maximum confidence."""
        from core.state import AnalysisResult

        analyses = [
            AnalysisResult(
                analyst_type="test",
                score=3.0,
                key_finding="x",
                reasoning="y",
                confidence=80.0,
            ),
        ]
        # Single analysis → 50% (single-source penalty, Phase 1-A fix)
        assert _calc_analyst_confidence(analyses) == 50.0

    def test_identical_scores_high_confidence(self):
        """Identical analyst scores should produce high confidence."""
        from core.state import AnalysisResult

        analyses = [
            AnalysisResult(
                analyst_type=f"test_{i}",
                score=4.0,
                key_finding="x",
                reasoning="y",
                confidence=80.0,
            )
            for i in range(5)
        ]
        conf = _calc_analyst_confidence(analyses)
        assert conf == 100.0

    def test_high_variance_lower_confidence(self):
        """High variance in scores should produce lower confidence."""
        from core.state import AnalysisResult

        analyses = [
            AnalysisResult(
                analyst_type=f"test_{i}",
                score=s,
                key_finding="x",
                reasoning="y",
                confidence=80.0,
            )
            for i, s in enumerate([1.0, 5.0, 1.0, 5.0])
        ]
        conf = _calc_analyst_confidence(analyses)
        assert conf < 80.0  # Should be notably lower than perfect
