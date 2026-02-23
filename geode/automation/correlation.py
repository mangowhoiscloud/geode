"""Correlation Analysis — Spearman, Kendall, Precision@K (numpy-only, no scipy).

Validates pipeline quality by measuring rank correlation between
automated scores and human judgments.

References:
    Kendall, M.G. (1970). Rank Correlation Methods. 4th ed. Griffin.
    Abramowitz, M. & Stegun, I.A. (1964). Handbook of Mathematical
        Functions, Eq. 7.1.26 (normal CDF approximation).

Architecture-v6 §4.5: Automation Layer — Correlation Analysis.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorrelationResult:
    """Result of a correlation analysis (immutable value object)."""

    spearman_rho: float = 0.0
    spearman_p: float = 1.0
    kendall_tau: float = 0.0
    kendall_p: float = 1.0
    precision_at_k: float = 0.0
    quarter: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spearman_rho": self.spearman_rho,
            "spearman_p": self.spearman_p,
            "kendall_tau": self.kendall_tau,
            "kendall_p": self.kendall_p,
            "precision_at_k": self.precision_at_k,
            "quarter": self.quarter,
        }


# Quarterly target ramp-up (SOT)
QUARTERLY_TARGETS: dict[str, dict[str, float]] = {
    "Q1": {"spearman_rho": 0.40, "precision_at_k": 0.50},
    "Q2": {"spearman_rho": 0.55, "precision_at_k": 0.60},
    "Q3": {"spearman_rho": 0.65, "precision_at_k": 0.70},
    "Q4": {"spearman_rho": 0.75, "precision_at_k": 0.80},
}


def _rankdata(arr: np.ndarray) -> np.ndarray:
    """Assign ranks to data, handling ties with average rank (no scipy)."""
    n = len(arr)
    sorted_indices = np.argsort(arr, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)

    i = 0
    while i < n:
        j = i
        # Find group of ties
        while j < n - 1 and abs(arr[sorted_indices[j]] - arr[sorted_indices[j + 1]]) < 1e-12:
            j += 1
        # Average rank for tied group
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[sorted_indices[k]] = avg_rank
        i = j + 1

    return ranks


def _normal_cdf(z: float) -> float:
    """Standard normal CDF approximation (Abramowitz and Stegun)."""
    if z < -8.0:
        return 0.0
    if z > 8.0:
        return 1.0
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = 1.0 if z >= 0 else -1.0
    x = abs(z) / math.sqrt(2.0)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def _inv_normal_cdf(p: float) -> float:
    """Inverse standard normal CDF (rational approximation).

    Abramowitz & Stegun (1964) approximation 26.2.23.
    Accurate to ~4.5e-4 for 0.5 < p < 1.
    """
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    if p < 0.5:
        return -_inv_normal_cdf(1.0 - p)

    # Rational approximation for 0.5 <= p < 1.0
    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


class _CorrelationStats:
    """Internal instrumentation counters."""

    __slots__ = ("analyses_run", "targets_checked", "targets_passed")

    def __init__(self) -> None:
        self.analyses_run: int = 0
        self.targets_checked: int = 0
        self.targets_passed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "analyses_run": self.analyses_run,
            "targets_checked": self.targets_checked,
            "targets_passed": self.targets_passed,
        }


class CorrelationAnalyzer:
    """Compute rank correlations between automated scores and human judgments.

    Usage:
        analyzer = CorrelationAnalyzer()
        result = analyzer.full_analysis(
            auto_scores=[4.2, 3.1, 4.8, 2.5],
            human_scores=[4.0, 3.5, 4.5, 2.0],
            k=2,
            quarter="Q1",
        )
    """

    def __init__(self) -> None:
        self._stats = _CorrelationStats()

    @property
    def stats(self) -> _CorrelationStats:
        return self._stats

    def compute_spearman(
        self,
        x: list[float],
        y: list[float],
    ) -> tuple[float, float]:
        """Compute Spearman rank correlation coefficient and p-value.

        Returns (rho, p_value).
        """
        n = len(x)
        if n != len(y):
            raise ValueError("Input arrays must have equal length")
        if n < 3:
            return (0.0, 1.0)

        x_arr = np.array(x, dtype=np.float64)
        y_arr = np.array(y, dtype=np.float64)

        rx = _rankdata(x_arr)
        ry = _rankdata(y_arr)

        # Pearson correlation on ranks (correct with ties, unlike d² shortcut)
        rx_mean = float(np.mean(rx))
        ry_mean = float(np.mean(ry))
        rx_dev = rx - rx_mean
        ry_dev = ry - ry_mean
        num = float(np.sum(rx_dev * ry_dev))
        denom = float(np.sqrt(np.sum(rx_dev**2) * np.sum(ry_dev**2)))
        rho = num / denom if denom > 0 else 0.0
        rho = max(-1.0, min(1.0, rho))  # Clamp

        # Approximate p-value using t-distribution → normal for large n
        if abs(rho) >= 1.0:
            p_value = 0.0
        else:
            t_stat = rho * math.sqrt((n - 2) / (1.0 - rho * rho))
            p_value = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))

        return (rho, p_value)

    def compute_kendall(
        self,
        x: list[float],
        y: list[float],
    ) -> tuple[float, float]:
        """Compute Kendall tau-b rank correlation and p-value.

        Returns (tau, p_value).
        """
        n = len(x)
        if n != len(y):
            raise ValueError("Input arrays must have equal length")
        if n < 3:
            return (0.0, 1.0)

        # Count concordant and discordant pairs
        concordant = 0
        discordant = 0
        tied_x = 0
        tied_y = 0

        for i in range(n):
            for j in range(i + 1, n):
                x_diff = x[i] - x[j]
                y_diff = y[i] - y[j]

                if abs(x_diff) < 1e-12 and abs(y_diff) < 1e-12:
                    tied_x += 1
                    tied_y += 1
                elif abs(x_diff) < 1e-12:
                    tied_x += 1
                elif abs(y_diff) < 1e-12:
                    tied_y += 1
                elif (x_diff > 0 and y_diff > 0) or (x_diff < 0 and y_diff < 0):
                    concordant += 1
                else:
                    discordant += 1

        n_pairs = n * (n - 1) // 2
        denom = math.sqrt((n_pairs - tied_x) * (n_pairs - tied_y))
        if denom == 0:
            return (0.0, 1.0)

        tau = (concordant - discordant) / denom
        tau = max(-1.0, min(1.0, tau))

        # P-value with tie-corrected variance (Kendall 1970)
        # Group ties: t_i = size of i-th tie group in x, u_j in y
        x_counts = list(Counter(x).values())
        y_counts = list(Counter(y).values())
        t0 = n * (n - 1.0)
        v0 = n * (n - 1.0) * (2.0 * n + 5.0)
        vt = sum(tc * (tc - 1.0) * (2.0 * tc + 5.0) for tc in x_counts)
        vu = sum(uc * (uc - 1.0) * (2.0 * uc + 5.0) for uc in y_counts)
        v1 = sum(tc * (tc - 1.0) for tc in x_counts) * sum(
            uc * (uc - 1.0) for uc in y_counts
        )
        v2 = sum(tc * (tc - 1.0) * (tc - 2.0) for tc in x_counts) * sum(
            uc * (uc - 1.0) * (uc - 2.0) for uc in y_counts
        )
        var_num = (
            v0 - vt - vu
        ) / 18.0 + v1 / (2.0 * t0) + v2 / (9.0 * t0 * (n - 2.0))
        var = max(var_num, 1e-12)
        z = (concordant - discordant) / math.sqrt(var)
        p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))

        return (tau, p_value)

    def compute_precision_at_k(
        self,
        auto_scores: list[float],
        human_scores: list[float],
        k: int,
    ) -> float:
        """Compute Precision@K: overlap of top-K items between two rankings.

        Returns precision as float (0.0 to 1.0).
        """
        n = len(auto_scores)
        if n != len(human_scores):
            raise ValueError("Input arrays must have equal length")
        if k <= 0 or k > n:
            k = min(max(k, 1), n)

        # Get indices of top-k in each ranking (highest scores first)
        auto_topk = set(np.argsort(auto_scores)[-k:].tolist())
        human_topk = set(np.argsort(human_scores)[-k:].tolist())

        overlap = len(auto_topk & human_topk)
        return overlap / k

    @staticmethod
    def compute_ece(
        confidences: list[float],
        accuracies: list[float],
        n_bins: int = 10,
    ) -> float:
        """Compute Expected Calibration Error (ECE).

        Measures calibration: how well confidence scores predict accuracy.
        ECE = sum(|bin_acc - bin_conf| * bin_weight) across bins.

        Args:
            confidences: Model confidence scores (0-1).
            accuracies: Binary accuracy indicators (0 or 1).
            n_bins: Number of calibration bins (default 10).

        Returns:
            ECE value (0 = perfectly calibrated, 1 = worst).

        Reference:
            Naeini et al. (2015). "Obtaining Well Calibrated Probabilities
            Using Bayesian Binning into Quantiles."
        """
        if not confidences or len(confidences) != len(accuracies):
            return 0.0

        n = len(confidences)
        bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
        ece = 0.0

        for i in range(n_bins):
            lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
            # Items in this bin
            indices = [
                j for j in range(n)
                if (lo <= confidences[j] < hi) or (i == n_bins - 1 and confidences[j] == hi)
            ]
            if not indices:
                continue
            bin_weight = len(indices) / n
            bin_conf = sum(confidences[j] for j in indices) / len(indices)
            bin_acc = sum(accuracies[j] for j in indices) / len(indices)
            ece += abs(bin_acc - bin_conf) * bin_weight

        return ece

    def full_analysis(
        self,
        auto_scores: list[float],
        human_scores: list[float],
        k: int = 10,
        quarter: str = "",
    ) -> CorrelationResult:
        """Run full correlation analysis."""
        self._stats.analyses_run += 1
        rho, rho_p = self.compute_spearman(auto_scores, human_scores)
        tau, tau_p = self.compute_kendall(auto_scores, human_scores)

        effective_k = min(k, len(auto_scores))
        p_at_k = self.compute_precision_at_k(auto_scores, human_scores, effective_k)

        return CorrelationResult(
            spearman_rho=rho,
            spearman_p=rho_p,
            kendall_tau=tau,
            kendall_p=tau_p,
            precision_at_k=p_at_k,
            quarter=quarter,
        )

    @staticmethod
    def required_sample_size(
        effect_size: float = 0.5,
        alpha: float = 0.05,
        power: float = 0.80,
    ) -> int:
        """Estimate required sample size for Spearman correlation test.

        Uses the asymptotic normal approximation for rank correlation:
            n ≈ ((z_alpha + z_power) / arctanh(rho))^2 + 3

        Based on Cohen (1988), Statistical Power Analysis for the
        Behavioral Sciences, 2nd ed.

        Args:
            effect_size: Expected |rho| to detect (0.1=small, 0.3=medium, 0.5=large).
            alpha: Significance level (two-tailed).
            power: Desired statistical power.

        Returns:
            Minimum sample size (integer).
        """
        if effect_size <= 0 or effect_size >= 1:
            raise ValueError("effect_size must be in (0, 1)")

        # z-scores from standard normal
        z_alpha = abs(_inv_normal_cdf(alpha / 2.0))
        z_power = abs(_inv_normal_cdf(1.0 - power))

        # Fisher z-transform of rho
        z_rho = math.atanh(effect_size)
        n = ((z_alpha + z_power) / z_rho) ** 2 + 3
        return int(math.ceil(n))

    def check_targets(
        self,
        result: CorrelationResult,
        quarter: str | None = None,
    ) -> dict[str, bool]:
        """Check if correlation results meet quarterly targets.

        Returns dict of metric → passed boolean.
        """
        q = quarter or result.quarter
        targets = QUARTERLY_TARGETS.get(q, QUARTERLY_TARGETS["Q1"])

        self._stats.targets_checked += 1
        checks = {
            "spearman_rho": result.spearman_rho >= targets["spearman_rho"],
            "precision_at_k": result.precision_at_k >= targets["precision_at_k"],
        }
        if all(checks.values()):
            self._stats.targets_passed += 1
        return checks
