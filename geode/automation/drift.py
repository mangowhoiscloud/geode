"""CUSUM Drift Detection — monitor pipeline quality metrics for distributional shifts.

Implements cumulative sum (CUSUM) change-point detection for continuous
monitoring of Spearman rho, human-LLM alpha, precision@10, and tier accuracy.

Architecture-v6 §4.5: Automation Layer — Drift Detection.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class DriftSeverity(Enum):
    """Severity levels for drift alerts."""

    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class DriftAlert:
    """A single drift alert for a metric."""

    metric_name: str
    severity: DriftSeverity
    cusum_score: float
    current_value: float
    baseline_mean: float
    baseline_std: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "severity": self.severity.value,
            "cusum_score": self.cusum_score,
            "current_value": self.current_value,
            "baseline_mean": self.baseline_mean,
            "baseline_std": self.baseline_std,
        }


@dataclass
class DriftMetricConfig:
    """Configuration for a single monitored metric."""

    name: str
    threshold: float  # Minimum acceptable value


# Default metric configurations (SOT values)
DEFAULT_METRIC_CONFIGS: list[DriftMetricConfig] = [
    DriftMetricConfig(name="spearman_rho", threshold=0.50),
    DriftMetricConfig(name="human_llm_alpha", threshold=0.80),
    DriftMetricConfig(name="precision_at_10", threshold=0.60),
    DriftMetricConfig(name="tier_accuracy", threshold=0.70),
]


class _DriftStats:
    """Internal instrumentation counters."""

    __slots__ = ("alerts_critical", "alerts_warning", "scans")

    def __init__(self) -> None:
        self.scans: int = 0
        self.alerts_warning: int = 0
        self.alerts_critical: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scans": self.scans,
            "alerts_warning": self.alerts_warning,
            "alerts_critical": self.alerts_critical,
        }


class CUSUMDetector:
    """Cumulative Sum (CUSUM) drift detector.

    Monitors a stream of metric values against a baseline and raises
    WARNING (cusum >= 2.5) or CRITICAL (cusum >= 4.0) alerts.

    References:
        Page, E.S. (1954). Continuous Inspection Schemes. Biometrika,
            41(1/2), 100-115. doi:10.2307/2333009

    Usage:
        detector = CUSUMDetector()
        detector.add_baseline("spearman_rho", [0.75, 0.80, 0.78, 0.82])
        alert = detector.detect("spearman_rho", 0.45)
        if alert.severity != DriftSeverity.NONE:
            print(f"Drift detected: {alert}")
    """

    WARNING_THRESHOLD = 2.5
    CRITICAL_THRESHOLD = 4.0
    DEFAULT_ALLOWANCE_K = 0.5  # CUSUM slack parameter (half-sigma)
    PSI_WARNING_THRESHOLD = 0.25

    def __init__(
        self,
        metric_configs: list[DriftMetricConfig] | None = None,
        allowance_k: float = DEFAULT_ALLOWANCE_K,
    ) -> None:
        self._configs = {c.name: c for c in (metric_configs or DEFAULT_METRIC_CONFIGS)}
        self._baselines: dict[str, tuple[float, float]] = {}  # name → (mean, std)
        self._cusum_pos: dict[str, float] = {}  # Positive CUSUM
        self._cusum_neg: dict[str, float] = {}  # Negative CUSUM
        self._allowance_k = allowance_k
        self._stats = _DriftStats()

    @property
    def stats(self) -> _DriftStats:
        return self._stats

    def add_baseline(self, metric_name: str, values: list[float]) -> None:
        """Set baseline statistics from a sample of values."""
        if not values:
            raise ValueError(f"Empty baseline for {metric_name}")
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
        std = math.sqrt(variance) if variance > 0 else 0.01  # Avoid zero std
        self._baselines[metric_name] = (mean, std)
        self._cusum_pos[metric_name] = 0.0
        self._cusum_neg[metric_name] = 0.0

    def detect(self, metric_name: str, value: float) -> DriftAlert:
        """Run CUSUM detection on a single new value.

        Returns a DriftAlert with severity NONE, WARNING, or CRITICAL.
        """
        if metric_name not in self._baselines:
            raise KeyError(f"No baseline for metric '{metric_name}'")

        mean, std = self._baselines[metric_name]

        # Normalized deviation
        z = (value - mean) / std

        # Update CUSUM accumulators with allowance k (Page 1954)
        # k acts as slack to prevent false positives from small fluctuations
        k = self._allowance_k
        self._cusum_pos[metric_name] = max(
            0.0,
            self._cusum_pos[metric_name] + z - k,
        )
        self._cusum_neg[metric_name] = max(
            0.0,
            self._cusum_neg[metric_name] - z - k,
        )

        # Use the maximum of positive and negative CUSUM
        cusum_score = max(self._cusum_pos[metric_name], self._cusum_neg[metric_name])

        # Classify severity
        if cusum_score >= self.CRITICAL_THRESHOLD:
            severity = DriftSeverity.CRITICAL
            self._stats.alerts_critical += 1
        elif cusum_score >= self.WARNING_THRESHOLD:
            severity = DriftSeverity.WARNING
            self._stats.alerts_warning += 1
        else:
            severity = DriftSeverity.NONE

        return DriftAlert(
            metric_name=metric_name,
            severity=severity,
            cusum_score=cusum_score,
            current_value=value,
            baseline_mean=mean,
            baseline_std=std,
        )

    def scan_all(self, values: dict[str, float]) -> list[DriftAlert]:
        """Scan multiple metrics at once. Returns only non-NONE alerts."""
        self._stats.scans += 1
        alerts: list[DriftAlert] = []
        for name, value in values.items():
            if name in self._baselines:
                alert = self.detect(name, value)
                if alert.severity != DriftSeverity.NONE:
                    alerts.append(alert)
        return alerts

    def reset(self, metric_name: str | None = None) -> None:
        """Reset CUSUM accumulators for one or all metrics."""
        if metric_name:
            self._cusum_pos[metric_name] = 0.0
            self._cusum_neg[metric_name] = 0.0
        else:
            for name in self._cusum_pos:
                self._cusum_pos[name] = 0.0
                self._cusum_neg[name] = 0.0

    def get_baseline(self, metric_name: str) -> tuple[float, float] | None:
        """Return (mean, std) for a metric, or None."""
        return self._baselines.get(metric_name)

    @staticmethod
    def compute_psi(expected: list[float], actual: list[float], n_bins: int = 10) -> float:
        """Compute Population Stability Index (PSI).

        PSI < 0.10: no significant shift
        PSI 0.10-0.25: moderate shift (monitoring)
        PSI > 0.25: significant shift (alert)

        References:
            Siddiqi, N. (2005). Credit Risk Scorecards. Wiley. Ch.5 PSI.
        """
        import numpy as np

        eps = 1e-4
        if len(expected) < 2 or len(actual) < 2:
            return 0.0

        # Create bins from expected distribution
        breakpoints = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
        breakpoints[0] = -np.inf
        breakpoints[-1] = np.inf
        # Remove duplicate breakpoints
        breakpoints = np.unique(breakpoints)

        expected_counts = np.histogram(expected, bins=breakpoints)[0].astype(float)
        actual_counts = np.histogram(actual, bins=breakpoints)[0].astype(float)

        expected_pct = expected_counts / expected_counts.sum() + eps
        actual_pct = actual_counts / actual_counts.sum() + eps

        psi = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
        return psi

    @staticmethod
    def classify_psi(psi_value: float) -> DriftSeverity:
        """Classify PSI value into a drift severity level.

        PSI < 0.10: NONE (no significant shift)
        PSI 0.10-0.25: WARNING (moderate shift)
        PSI > 0.25: CRITICAL (significant shift)
        """
        if psi_value >= CUSUMDetector.PSI_WARNING_THRESHOLD:
            return DriftSeverity.CRITICAL
        if psi_value >= 0.10:
            return DriftSeverity.WARNING
        return DriftSeverity.NONE

    def list_metrics(self) -> list[str]:
        """List all metrics with baselines."""
        return list(self._baselines.keys())

    def save_results(self, path: str | Path) -> None:
        """Persist detection history (baselines, CUSUM state, stats) as JSON.

        Args:
            path: File path for the output JSON.
        """
        data: dict[str, Any] = {
            "baselines": {
                name: {"mean": mean, "std": std} for name, (mean, std) in self._baselines.items()
            },
            "cusum_state": {
                name: {
                    "s_pos": self._cusum_pos.get(name, 0.0),
                    "s_neg": self._cusum_neg.get(name, 0.0),
                }
                for name in self._baselines
            },
            "stats": self._stats.to_dict(),
        }
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("Saved drift detection history to %s", dest)
