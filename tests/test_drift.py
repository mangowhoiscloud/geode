"""Tests for L4.5 CUSUM Drift Detection."""

import pytest

from geode.automation.drift import (
    DEFAULT_METRIC_CONFIGS,
    CUSUMDetector,
    DriftAlert,
    DriftSeverity,
)


class TestDriftSeverity:
    def test_enum_values(self):
        assert DriftSeverity.NONE.value == "none"
        assert DriftSeverity.WARNING.value == "warning"
        assert DriftSeverity.CRITICAL.value == "critical"


class TestDriftAlert:
    def test_to_dict(self):
        alert = DriftAlert(
            metric_name="spearman_rho",
            severity=DriftSeverity.WARNING,
            cusum_score=3.0,
            current_value=0.3,
            baseline_mean=0.75,
            baseline_std=0.05,
        )
        d = alert.to_dict()
        assert d["metric_name"] == "spearman_rho"
        assert d["severity"] == "warning"
        assert d["cusum_score"] == 3.0


class TestDriftMetricConfig:
    def test_default_configs(self):
        assert len(DEFAULT_METRIC_CONFIGS) == 4
        names = {c.name for c in DEFAULT_METRIC_CONFIGS}
        assert "spearman_rho" in names
        assert "human_llm_alpha" in names
        assert "precision_at_10" in names
        assert "tier_accuracy" in names

    def test_threshold_values(self):
        configs = {c.name: c.threshold for c in DEFAULT_METRIC_CONFIGS}
        assert configs["spearman_rho"] == 0.50
        assert configs["human_llm_alpha"] == 0.80
        assert configs["precision_at_10"] == 0.60
        assert configs["tier_accuracy"] == 0.70


class TestCUSUMDetector:
    def test_add_baseline(self):
        detector = CUSUMDetector()
        detector.add_baseline("test", [1.0, 2.0, 3.0, 4.0])
        baseline = detector.get_baseline("test")
        assert baseline is not None
        mean, std = baseline
        assert abs(mean - 2.5) < 0.01

    def test_add_baseline_empty_raises(self):
        detector = CUSUMDetector()
        with pytest.raises(ValueError, match="Empty baseline"):
            detector.add_baseline("test", [])

    def test_detect_no_baseline_raises(self):
        detector = CUSUMDetector()
        with pytest.raises(KeyError, match="No baseline"):
            detector.detect("unknown", 0.5)

    def test_detect_normal_value(self):
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.75, 0.78, 0.80, 0.73, 0.77])
        alert = detector.detect("metric", 0.76)
        assert alert.severity == DriftSeverity.NONE

    def test_detect_warning_on_drift(self):
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.80, 0.80, 0.80, 0.80])
        # Push multiple bad values to accumulate CUSUM
        for _ in range(3):
            alert = detector.detect("metric", 0.60)
        # After several low values, should detect drift
        assert alert.severity in (DriftSeverity.WARNING, DriftSeverity.CRITICAL)

    def test_detect_critical_on_severe_drift(self):
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.80, 0.80, 0.80, 0.80])
        # Push many bad values for critical
        for _ in range(10):
            alert = detector.detect("metric", 0.30)
        assert alert.severity == DriftSeverity.CRITICAL

    def test_scan_all(self):
        detector = CUSUMDetector()
        detector.add_baseline("a", [1.0, 1.0, 1.0])
        detector.add_baseline("b", [1.0, 1.0, 1.0])
        alerts = detector.scan_all({"a": 1.0, "b": 1.0})
        # Normal values should produce no alerts
        assert len(alerts) == 0
        assert detector.stats.scans == 1

    def test_scan_all_with_drift(self):
        detector = CUSUMDetector()
        detector.add_baseline("a", [1.0, 1.0, 1.0])
        # Push repeated drift
        for _ in range(5):
            alerts = detector.scan_all({"a": -5.0})
        # Should eventually detect
        assert len(alerts) > 0

    def test_reset(self):
        detector = CUSUMDetector()
        detector.add_baseline("m", [1.0, 1.0, 1.0])
        detector.detect("m", -5.0)
        detector.reset("m")
        # After reset, normal value should be fine
        alert = detector.detect("m", 1.0)
        assert alert.severity == DriftSeverity.NONE

    def test_reset_all(self):
        detector = CUSUMDetector()
        detector.add_baseline("a", [1.0])
        detector.add_baseline("b", [1.0])
        detector.detect("a", -5.0)
        detector.detect("b", -5.0)
        detector.reset()
        assert detector.detect("a", 1.0).severity == DriftSeverity.NONE
        assert detector.detect("b", 1.0).severity == DriftSeverity.NONE

    def test_list_metrics(self):
        detector = CUSUMDetector()
        detector.add_baseline("x", [1.0])
        detector.add_baseline("y", [2.0])
        assert sorted(detector.list_metrics()) == ["x", "y"]

    def test_stats(self):
        detector = CUSUMDetector()
        stats = detector.stats
        assert stats.scans == 0
        d = stats.to_dict()
        assert "scans" in d
        assert "alerts_warning" in d
        assert "alerts_critical" in d


class TestCUSUMUpwardDrift:
    """Test CUSUM detection for upward (positive) drift."""

    def test_detect_upward_drift(self):
        """Values significantly above baseline should trigger drift via positive CUSUM."""
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.50, 0.50, 0.50, 0.50])
        # Push values well above baseline
        for _ in range(5):
            alert = detector.detect("metric", 0.90)
        assert alert.severity in (DriftSeverity.WARNING, DriftSeverity.CRITICAL)

    def test_negative_cusum_accumulates(self):
        """Verify the negative CUSUM arm accumulates for downward drift."""
        detector = CUSUMDetector()
        detector.add_baseline("metric", [0.80, 0.80, 0.80, 0.80])
        # Push values below baseline
        for _ in range(5):
            alert = detector.detect("metric", 0.40)
        assert alert.cusum_score > 0
        assert alert.severity != DriftSeverity.NONE


class TestPSI:
    def test_identical_distributions(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
        psi = CUSUMDetector.compute_psi(data, data)
        assert psi < 0.01

    def test_shifted_distribution(self):
        expected = [float(x) for x in range(100)]
        actual = [float(x + 50) for x in range(100)]
        psi = CUSUMDetector.compute_psi(expected, actual)
        assert psi > 0.25

    def test_small_input(self):
        assert CUSUMDetector.compute_psi([1.0], [2.0]) == 0.0

    def test_psi_nonnegative(self):
        import random

        random.seed(42)
        expected = [random.gauss(0, 1) for _ in range(100)]
        actual = [random.gauss(0.5, 1) for _ in range(100)]
        psi = CUSUMDetector.compute_psi(expected, actual)
        assert psi >= 0.0


class TestPSIClassification:
    def test_classify_none(self):
        assert CUSUMDetector.classify_psi(0.05) == DriftSeverity.NONE

    def test_classify_warning(self):
        assert CUSUMDetector.classify_psi(0.15) == DriftSeverity.WARNING

    def test_classify_critical(self):
        assert CUSUMDetector.classify_psi(0.30) == DriftSeverity.CRITICAL

    def test_classify_boundary_warning(self):
        assert CUSUMDetector.classify_psi(0.10) == DriftSeverity.WARNING

    def test_classify_boundary_critical(self):
        assert CUSUMDetector.classify_psi(0.25) == DriftSeverity.CRITICAL


class TestPSIKnownAnswer:
    """Siddiqi (2005) style known-answer PSI test."""

    def test_uniform_vs_shifted_uniform(self):
        """Known result: uniform [0,100) vs shifted [20,120) should produce PSI > 0.1."""
        import numpy as np

        np.random.seed(123)
        expected = np.random.uniform(0, 100, 200).tolist()
        actual = np.random.uniform(20, 120, 200).tolist()
        psi = CUSUMDetector.compute_psi(expected, actual)
        # Shifted by 20% of range → moderate to significant shift
        assert psi > 0.05
        assert psi < 2.0  # Sanity upper bound

    def test_psi_symmetric_property(self):
        """PSI is not symmetric: PSI(A,B) != PSI(B,A) in general, but both positive."""
        import numpy as np

        np.random.seed(42)
        a = np.random.normal(0, 1, 200).tolist()
        b = np.random.normal(1, 1, 200).tolist()
        psi_ab = CUSUMDetector.compute_psi(a, b)
        psi_ba = CUSUMDetector.compute_psi(b, a)
        assert psi_ab > 0
        assert psi_ba > 0
