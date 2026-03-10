"""Property-based tests for CUSUM drift detection (boundary value approach).

Since hypothesis is not available, these tests use pytest.mark.parametrize
with systematic boundary values to cover the property-based test intent:
- CUSUM non-negativity: S_pos and S_neg always >= 0
- Constant values never trigger drift
- PSI self-comparison ~= 0
"""

from __future__ import annotations

import pytest
from core.automation.drift import CUSUMDetector, DriftSeverity


class TestCUSUMNonNegativity:
    """S_pos and S_neg should always be >= 0 after any sequence of updates."""

    @pytest.mark.parametrize(
        "values",
        [
            [0.5, 0.5, 0.5],  # Constant at baseline
            [1.0, 0.0, 1.0, 0.0],  # Oscillating
            [0.0, 0.0, 0.0, 0.0],  # All zeros
            [1.0, 1.0, 1.0, 1.0],  # All ones
            [0.1, 0.2, 0.3, 0.4, 0.5],  # Increasing
            [0.9, 0.7, 0.5, 0.3, 0.1],  # Decreasing
            [-1.0, -2.0, -3.0],  # All negative
            [100.0, -100.0, 50.0, -50.0],  # Extreme swings
        ],
    )
    def test_cusum_always_non_negative(self, values: list[float]):
        """CUSUM accumulators must be >= 0 after every update."""
        detector = CUSUMDetector()
        detector.add_baseline("test_metric", [0.5, 0.5, 0.5, 0.5])

        for val in values:
            alert = detector.detect("test_metric", val)
            assert alert.cusum_score >= 0.0, (
                f"CUSUM score went negative: {alert.cusum_score} for value={val}"
            )
            # Also verify internal state directly
            assert detector._cusum_pos["test_metric"] >= 0.0
            assert detector._cusum_neg["test_metric"] >= 0.0


class TestConstantValuesNoDrift:
    """Feeding constant values at the baseline mean should never trigger drift."""

    @pytest.mark.parametrize("baseline_mean", [0.1, 0.5, 1.0, 5.0, 50.0])
    @pytest.mark.parametrize("n_observations", [10, 50, 100])
    def test_constant_at_mean_no_drift(
        self,
        baseline_mean: float,
        n_observations: int,
    ):
        """Constant values at baseline mean should never exceed WARNING threshold."""
        detector = CUSUMDetector()
        baseline = [baseline_mean] * 20
        detector.add_baseline("metric", baseline)

        for _ in range(n_observations):
            alert = detector.detect("metric", baseline_mean)
            assert alert.severity == DriftSeverity.NONE, (
                f"Drift detected at constant value: cusum={alert.cusum_score}"
            )

    @pytest.mark.parametrize("baseline_mean", [0.5, 1.0, 10.0])
    def test_near_mean_no_critical(self, baseline_mean: float):
        """Values very close to mean should not trigger CRITICAL alerts."""
        detector = CUSUMDetector()
        baseline = [baseline_mean] * 20
        detector.add_baseline("metric", baseline)

        # Small perturbation around mean (within 0.1 std)
        std_approx = 0.01  # Very low std from constant baseline
        for _ in range(50):
            val = baseline_mean + std_approx * 0.1
            alert = detector.detect("metric", val)
            assert alert.severity != DriftSeverity.CRITICAL


class TestDriftDetection:
    """Large deviations from baseline should trigger drift alerts."""

    def test_large_drop_triggers_drift(self):
        """A sustained large drop should eventually trigger WARNING or CRITICAL."""
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.8, 0.82, 0.78, 0.81, 0.79])

        # Feed values far below baseline
        severities = []
        for _ in range(20):
            alert = detector.detect("metric", 0.2)
            severities.append(alert.severity)

        # Should eventually hit at least WARNING
        assert DriftSeverity.WARNING in severities or DriftSeverity.CRITICAL in severities

    def test_large_spike_triggers_drift(self):
        """A sustained large spike should eventually trigger drift."""
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.5, 0.5, 0.5, 0.5])

        severities = []
        for _ in range(20):
            alert = detector.detect("metric", 5.0)
            severities.append(alert.severity)

        assert DriftSeverity.WARNING in severities or DriftSeverity.CRITICAL in severities

    def test_reset_clears_cusum(self):
        """After reset, CUSUM should start from zero."""
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.5, 0.5, 0.5, 0.5])

        # Build up CUSUM
        for _ in range(10):
            detector.detect("metric", 5.0)

        detector.reset("metric")
        assert detector._cusum_pos["metric"] == 0.0
        assert detector._cusum_neg["metric"] == 0.0


class TestPSIProperties:
    """Properties of Population Stability Index (PSI)."""

    def test_psi_self_comparison_near_zero(self):
        """PSI(P, P) should be approximately zero."""
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        psi = CUSUMDetector.compute_psi(data, data)
        assert psi < 0.01, f"PSI self-comparison should be near 0, got {psi}"

    def test_psi_non_negative(self):
        """PSI should always be >= 0."""
        expected = [1.0, 2.0, 3.0, 4.0, 5.0]
        actual = [3.0, 4.0, 5.0, 6.0, 7.0]
        psi = CUSUMDetector.compute_psi(expected, actual)
        assert psi >= 0.0

    @pytest.mark.parametrize(
        "expected,actual",
        [
            ([1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0]),
            ([1.0, 1.0, 2.0, 2.0], [5.0, 5.0, 6.0, 6.0]),
            ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]),
        ],
    )
    def test_psi_large_shift_high(self, expected: list[float], actual: list[float]):
        """Large distributional shifts should produce high PSI (> 0).

        Note: constant-value distributions are excluded because
        np.percentile collapses all bin boundaries, yielding PSI=0.
        """
        psi = CUSUMDetector.compute_psi(expected, actual)
        assert psi > 0.0

    def test_psi_approximate_symmetry(self):
        """PSI(P,Q) and PSI(Q,P) should be in the same ballpark.

        PSI is NOT mathematically symmetric (bins are from expected),
        but for similar distributions the difference should be bounded.
        """
        p = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        q = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
        psi_pq = CUSUMDetector.compute_psi(p, q)
        psi_qp = CUSUMDetector.compute_psi(q, p)
        # Both should be positive and in the same order of magnitude
        assert psi_pq > 0.0
        assert psi_qp > 0.0
        # Within 10x of each other (loose bound for asymmetric measure)
        if psi_pq > 0 and psi_qp > 0:
            ratio = max(psi_pq, psi_qp) / min(psi_pq, psi_qp)
            assert ratio < 10.0, f"PSI asymmetry too large: {psi_pq} vs {psi_qp}"

    def test_psi_empty_returns_zero(self):
        """PSI of empty distributions should be 0."""
        assert CUSUMDetector.compute_psi([], []) == 0.0
        assert CUSUMDetector.compute_psi([1.0], [1.0]) == 0.0


class TestPSIClassification:
    """PSI classification thresholds."""

    @pytest.mark.parametrize(
        "psi_value,expected",
        [
            (0.0, DriftSeverity.NONE),
            (0.05, DriftSeverity.NONE),
            (0.09, DriftSeverity.NONE),
            (0.10, DriftSeverity.WARNING),
            (0.15, DriftSeverity.WARNING),
            (0.24, DriftSeverity.WARNING),
            (0.25, DriftSeverity.CRITICAL),
            (0.50, DriftSeverity.CRITICAL),
            (1.0, DriftSeverity.CRITICAL),
        ],
    )
    def test_classify_psi_boundaries(self, psi_value: float, expected: DriftSeverity):
        assert CUSUMDetector.classify_psi(psi_value) == expected


class TestSaveResults:
    """Test that save_results persists data correctly."""

    def test_save_results_creates_file(self, tmp_path):
        """save_results should create a valid JSON file."""
        import json

        detector = CUSUMDetector()
        detector.add_baseline("spearman_rho", [0.75, 0.80, 0.78])
        detector.detect("spearman_rho", 0.5)

        path = tmp_path / "drift_results.json"
        detector.save_results(path)

        assert path.exists()
        data = json.loads(path.read_text())
        assert "baselines" in data
        assert "cusum_state" in data
        assert "stats" in data
        assert "spearman_rho" in data["baselines"]
