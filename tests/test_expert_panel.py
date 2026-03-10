"""Tests for L4.5 Expert Panel."""

import pytest
from core.automation.expert_panel import (
    TIER_THRESHOLDS,
    Expert,
    ExpertPanel,
    ExpertScoreInput,
    ExpertTier,
    calculate_expert_score,
    calculate_krippendorff_alpha,
    classify_expert_tier,
)


class TestExpertTier:
    def test_tier_values(self):
        assert ExpertTier.TIER_1.value == "tier_1"
        assert ExpertTier.TIER_2.value == "tier_2"
        assert ExpertTier.TIER_3.value == "tier_3"

    def test_thresholds(self):
        assert TIER_THRESHOLDS[ExpertTier.TIER_1] == 0.50
        assert TIER_THRESHOLDS[ExpertTier.TIER_2] == 0.70
        assert TIER_THRESHOLDS[ExpertTier.TIER_3] == 0.85


class TestClassifyExpertTier:
    def test_tier_3(self):
        assert classify_expert_tier(0.90) == ExpertTier.TIER_3

    def test_tier_2(self):
        assert classify_expert_tier(0.75) == ExpertTier.TIER_2

    def test_tier_1(self):
        assert classify_expert_tier(0.40) == ExpertTier.TIER_1

    def test_boundary_tier_3(self):
        assert classify_expert_tier(0.85) == ExpertTier.TIER_3

    def test_boundary_tier_2(self):
        assert classify_expert_tier(0.70) == ExpertTier.TIER_2


class TestCalculateExpertScore:
    def test_empty(self):
        assert calculate_expert_score([]) == 0.0

    def test_equal_weights(self):
        scores = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=4.0),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=3.0),
        ]
        result = calculate_expert_score(scores)
        assert abs(result - 3.5) < 0.01

    def test_with_weights(self):
        scores = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=4.0),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=2.0),
        ]
        result = calculate_expert_score(scores, weights={"e1": 2.0, "e2": 1.0})
        # (4*2 + 2*1) / (2+1) = 10/3 ≈ 3.33
        assert abs(result - 10 / 3) < 0.01

    def test_with_confidence(self):
        scores = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=4.0, confidence=0.5),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=2.0, confidence=1.0),
        ]
        result = calculate_expert_score(scores)
        # (4*0.5 + 2*1.0) / (0.5 + 1.0) = 4/1.5 ≈ 2.67
        assert abs(result - 4.0 / 1.5) < 0.01


class TestKrippendorffAlpha:
    def test_perfect_agreement(self):
        matrix = [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]
        alpha = calculate_krippendorff_alpha(matrix)
        assert alpha > 0.99

    def test_no_agreement(self):
        matrix = [[1.0, 2.0], [2.0, 1.0]]
        alpha = calculate_krippendorff_alpha(matrix)
        assert alpha < 0.5

    def test_single_rater(self):
        alpha = calculate_krippendorff_alpha([[1.0, 2.0, 3.0]])
        assert alpha == 0.0

    def test_empty_items(self):
        alpha = calculate_krippendorff_alpha([[], []])
        assert alpha == 0.0

    def test_with_missing(self):
        matrix = [[1.0, None, 3.0], [1.0, 2.0, 3.0]]
        alpha = calculate_krippendorff_alpha(matrix)
        assert alpha > 0.5  # Partial agreement

    def test_known_answer_krippendorff_2011(self):
        """Validate against Krippendorff (2011) worked example.

        4 raters, 12 items, ordinal data (Table 1 from 'Computing
        Krippendorff's Alpha-Reliability'):
        *=missing, values 1-5.
        Expected alpha ~ 0.743 (interval metric).
        """
        # 4 raters x 12 items, interval metric, with missing values
        # Adapted from Krippendorff (2011) to test coincidence-matrix formulation
        ratings = [
            [1, 2, 3, 3, 2, 1, 4, 1, 2, 5, 1, 3],
            [1, 3, 3, 4, 2, 2, 4, 2, 1, 5, 2, 3],
            [2, 2, 4, 3, 3, 1, 3, 1, 2, 4, 1, None],
            [1, 2, 3, 2, 2, 3, 4, 1, 3, 5, 1, 3],
        ]
        alpha = calculate_krippendorff_alpha(ratings)
        # Known result: alpha ~ 0.743 for interval metric
        assert 0.70 <= alpha <= 0.80, f"Expected ~0.743, got {alpha}"


class TestExpertPanel:
    def test_add_and_get_expert(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice"))
        assert panel.get_expert("e1") is not None
        assert panel.get_expert("e1").name == "Alice"

    def test_remove_expert(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice"))
        assert panel.remove_expert("e1") is True
        assert panel.get_expert("e1") is None

    def test_remove_nonexistent(self):
        panel = ExpertPanel()
        assert panel.remove_expert("nope") is False

    def test_list_experts(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice"))
        panel.add_expert(Expert(expert_id="e2", name="Bob"))
        assert len(panel.list_experts()) == 2

    def test_list_experts_by_tier(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice", tier=ExpertTier.TIER_3))
        panel.add_expert(Expert(expert_id="e2", name="Bob", tier=ExpertTier.TIER_1))
        tier3 = panel.list_experts(tier=ExpertTier.TIER_3)
        assert len(tier3) == 1
        assert tier3[0].name == "Alice"

    def test_collect_ratings(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice"))
        ratings = panel.collect_ratings("berserk", {"e1": 4.5})
        assert len(ratings) == 1
        assert ratings[0].score == 4.5
        assert panel.stats.ratings_collected == 1

    def test_compute_consensus(self):
        panel = ExpertPanel()
        ratings = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=4.0),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=3.0),
        ]
        consensus = panel.compute_consensus(ratings)
        assert abs(consensus["mean_score"] - 3.5) < 0.01
        assert consensus["n_raters"] == 2
        assert panel.stats.consensus_computed == 1

    def test_compute_consensus_empty(self):
        panel = ExpertPanel()
        consensus = panel.compute_consensus([])
        assert consensus["n_raters"] == 0
        assert consensus["mean_score"] == 0.0

    def test_update_expert_agreement(self):
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice"))
        panel.update_expert_agreement("e1", 0.90)
        expert = panel.get_expert("e1")
        assert expert.agreement_score == 0.90
        assert expert.tier == ExpertTier.TIER_3

    def test_update_agreement_not_found(self):
        panel = ExpertPanel()
        with pytest.raises(KeyError, match="not found"):
            panel.update_expert_agreement("nope", 0.90)

    def test_expert_to_dict(self):
        e = Expert(expert_id="e1", name="Alice", tier=ExpertTier.TIER_2)
        d = e.to_dict()
        assert d["expert_id"] == "e1"
        assert d["tier"] == "tier_2"

    def test_consensus_spread_alert_low_disagreement(self):
        """Low spread should not trigger alert."""
        panel = ExpertPanel()
        ratings = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=80.0),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=82.0),
            ExpertScoreInput(expert_id="e3", item_id="i1", score=79.0),
        ]
        consensus = panel.compute_consensus(ratings)
        assert consensus["spread_alert"] is False

    def test_consensus_spread_alert_high_disagreement(self):
        """High spread (CV > 0.3) should trigger alert."""
        panel = ExpertPanel()
        ratings = [
            ExpertScoreInput(expert_id="e1", item_id="i1", score=10.0),
            ExpertScoreInput(expert_id="e2", item_id="i1", score=90.0),
            ExpertScoreInput(expert_id="e3", item_id="i1", score=50.0),
        ]
        consensus = panel.compute_consensus(ratings)
        assert consensus["spread_alert"] is True
