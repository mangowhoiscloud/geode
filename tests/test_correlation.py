"""Tests for L4.5 Correlation Analysis (numpy-only)."""

import pytest
from core.automation.correlation import (
    QUARTERLY_TARGETS,
    CorrelationAnalyzer,
    CorrelationResult,
)


class TestCorrelationResult:
    def test_to_dict(self):
        r = CorrelationResult(spearman_rho=0.85, quarter="Q2")
        d = r.to_dict()
        assert d["spearman_rho"] == 0.85
        assert d["quarter"] == "Q2"

    def test_frozen(self):
        """CorrelationResult should be immutable."""
        r = CorrelationResult(spearman_rho=0.85)
        with pytest.raises(AttributeError):
            r.spearman_rho = 0.5  # type: ignore[misc]


class TestQuarterlyTargets:
    def test_all_quarters(self):
        assert "Q1" in QUARTERLY_TARGETS
        assert "Q2" in QUARTERLY_TARGETS
        assert "Q3" in QUARTERLY_TARGETS
        assert "Q4" in QUARTERLY_TARGETS

    def test_ramp_up(self):
        assert QUARTERLY_TARGETS["Q1"]["spearman_rho"] < QUARTERLY_TARGETS["Q4"]["spearman_rho"]


class TestSpearman:
    def test_perfect_correlation(self):
        analyzer = CorrelationAnalyzer()
        rho, p = analyzer.compute_spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert abs(rho - 1.0) < 0.01
        assert p < 0.05

    def test_inverse_correlation(self):
        analyzer = CorrelationAnalyzer()
        rho, p = analyzer.compute_spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert abs(rho - (-1.0)) < 0.01

    def test_no_correlation(self):
        analyzer = CorrelationAnalyzer()
        rho, _ = analyzer.compute_spearman([1, 2, 3, 4], [2, 4, 1, 3])
        assert abs(rho) < 0.5

    def test_too_few_values(self):
        analyzer = CorrelationAnalyzer()
        rho, p = analyzer.compute_spearman([1, 2], [1, 2])
        assert rho == 0.0
        assert p == 1.0

    def test_unequal_length_raises(self):
        analyzer = CorrelationAnalyzer()
        with pytest.raises(ValueError, match="equal length"):
            analyzer.compute_spearman([1, 2, 3], [1, 2])

    def test_ties_in_data(self):
        analyzer = CorrelationAnalyzer()
        rho, p = analyzer.compute_spearman([1, 1, 2, 3, 4], [1, 2, 3, 4, 5])
        assert 0.5 < rho < 1.0  # Ties reduce from perfect 1.0


class TestKendall:
    def test_perfect_correlation(self):
        analyzer = CorrelationAnalyzer()
        tau, p = analyzer.compute_kendall([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert abs(tau - 1.0) < 0.01

    def test_inverse_correlation(self):
        analyzer = CorrelationAnalyzer()
        tau, _ = analyzer.compute_kendall([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert abs(tau - (-1.0)) < 0.01

    def test_too_few_values(self):
        analyzer = CorrelationAnalyzer()
        tau, p = analyzer.compute_kendall([1, 2], [1, 2])
        assert tau == 0.0

    def test_ties_in_x(self):
        analyzer = CorrelationAnalyzer()
        tau, p = analyzer.compute_kendall([1, 1, 2, 3, 4], [1, 2, 3, 4, 5])
        assert 0.5 < tau < 1.0  # Tau-b with ties reduces from 1.0

    def test_all_tied(self):
        analyzer = CorrelationAnalyzer()
        tau, p = analyzer.compute_kendall([1, 1, 1, 1], [2, 2, 2, 2])
        assert tau == 0.0
        assert p == 1.0


class TestPrecisionAtK:
    def test_perfect_overlap(self):
        analyzer = CorrelationAnalyzer()
        p = analyzer.compute_precision_at_k([5, 4, 3, 2, 1], [5, 4, 3, 2, 1], k=3)
        assert p == 1.0

    def test_no_overlap(self):
        analyzer = CorrelationAnalyzer()
        p = analyzer.compute_precision_at_k([5, 4, 3, 2, 1], [1, 2, 3, 4, 5], k=2)
        assert p == 0.0

    def test_partial_overlap(self):
        analyzer = CorrelationAnalyzer()
        p = analyzer.compute_precision_at_k([5, 4, 3, 2, 1], [5, 3, 4, 2, 1], k=3)
        assert 0.0 < p <= 1.0


class TestFullAnalysis:
    def test_full_analysis(self):
        analyzer = CorrelationAnalyzer()
        result = analyzer.full_analysis(
            auto_scores=[4.2, 3.1, 4.8, 2.5, 3.7],
            human_scores=[4.0, 3.5, 4.5, 2.0, 3.8],
            k=3,
            quarter="Q1",
        )
        assert isinstance(result, CorrelationResult)
        assert result.quarter == "Q1"
        assert result.spearman_rho > 0.5  # Should have positive correlation


class TestCheckTargets:
    def test_meets_q1_targets(self):
        analyzer = CorrelationAnalyzer()
        result = CorrelationResult(spearman_rho=0.60, precision_at_k=0.70, quarter="Q1")
        checks = analyzer.check_targets(result)
        assert checks["spearman_rho"] is True
        assert checks["precision_at_k"] is True

    def test_fails_q4_targets(self):
        analyzer = CorrelationAnalyzer()
        result = CorrelationResult(spearman_rho=0.60, precision_at_k=0.70, quarter="Q4")
        checks = analyzer.check_targets(result)
        assert checks["spearman_rho"] is False  # Q4 needs 0.75
        assert checks["precision_at_k"] is False  # Q4 needs 0.80


class TestECE:
    def test_perfectly_calibrated(self):
        """Perfect calibration: confidences match accuracies."""
        confs = [0.1, 0.3, 0.5, 0.7, 0.9]
        # If conf=0.9 predicts correctly and conf=0.1 predicts incorrectly
        accs = [0.0, 0.0, 1.0, 1.0, 1.0]
        ece = CorrelationAnalyzer.compute_ece(confs, accs, n_bins=5)
        assert ece < 0.3  # Reasonably calibrated

    def test_worst_calibration(self):
        """High confidence but always wrong → high ECE."""
        confs = [0.9, 0.9, 0.9, 0.9, 0.9]
        accs = [0.0, 0.0, 0.0, 0.0, 0.0]
        ece = CorrelationAnalyzer.compute_ece(confs, accs, n_bins=5)
        assert ece > 0.5  # Badly calibrated

    def test_empty_input(self):
        assert CorrelationAnalyzer.compute_ece([], []) == 0.0

    def test_ece_bounded(self):
        """ECE should always be in [0, 1]."""
        import random as rng

        rng.seed(42)
        confs = [rng.random() for _ in range(100)]
        accs = [float(rng.random() > 0.5) for _ in range(100)]
        ece = CorrelationAnalyzer.compute_ece(confs, accs)
        assert 0.0 <= ece <= 1.0


class TestRequiredSampleSize:
    def test_medium_effect(self):
        """Medium effect (rho=0.5) at 80% power → n ≈ 29."""
        n = CorrelationAnalyzer.required_sample_size(effect_size=0.5, alpha=0.05, power=0.80)
        assert 25 <= n <= 35  # Cohen (1988): ~29

    def test_small_effect_needs_more(self):
        """Smaller effect → needs more samples."""
        n_small = CorrelationAnalyzer.required_sample_size(effect_size=0.3)
        n_large = CorrelationAnalyzer.required_sample_size(effect_size=0.5)
        assert n_small > n_large

    def test_higher_power_needs_more(self):
        n_80 = CorrelationAnalyzer.required_sample_size(power=0.80)
        n_95 = CorrelationAnalyzer.required_sample_size(power=0.95)
        assert n_95 > n_80

    def test_invalid_effect_raises(self):
        with pytest.raises(ValueError, match="effect_size"):
            CorrelationAnalyzer.required_sample_size(effect_size=0.0)
        with pytest.raises(ValueError, match="effect_size"):
            CorrelationAnalyzer.required_sample_size(effect_size=1.0)


class TestCorrelationAnalyzer:
    def test_known_answer_spearman(self):
        """Known-answer: perfect ranking -> rho=1.0, reversed -> rho=-1.0."""
        analyzer = CorrelationAnalyzer()
        # Perfect agreement
        rho, p = analyzer.compute_spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert abs(rho - 1.0) < 1e-10
        assert p < 0.05
        # Perfect disagreement
        rho, p = analyzer.compute_spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        assert abs(rho - (-1.0)) < 1e-10

    def test_known_answer_kendall(self):
        """Known-answer: Kendall tau-b for simple cases.

        For [1,2,3,4] vs [1,2,3,4]: all concordant, tau=1.0
        For [1,2,3,4] vs [4,3,2,1]: all discordant, tau=-1.0
        For [1,2,3,4] vs [1,3,2,4]: 4 concordant, 2 discordant, tau=1/3
        """
        analyzer = CorrelationAnalyzer()
        tau, _ = analyzer.compute_kendall([1, 2, 3, 4], [1, 2, 3, 4])
        assert abs(tau - 1.0) < 1e-10

        tau, _ = analyzer.compute_kendall([1, 2, 3, 4], [4, 3, 2, 1])
        assert abs(tau - (-1.0)) < 1e-10

        # [1,2,3,4] vs [1,3,2,4]: C=5, D=1, n=4, pairs=6, tau=(5-1)/6=2/3
        tau, _ = analyzer.compute_kendall([1, 2, 3, 4], [1, 3, 2, 4])
        assert abs(tau - (2.0 / 3.0)) < 0.05  # Allow small tolerance
