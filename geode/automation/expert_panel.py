"""Expert Panel — human expert management, scoring, and consensus.

Tracks expert reliability tiers, collects ratings, and computes
inter-rater agreement using Krippendorff's alpha (ordinal, numpy-only).

Architecture-v6 §4.5: Automation Layer — Expert Panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


class ExpertTier(Enum):
    """Expert reliability tiers based on agreement score."""

    TIER_1 = "tier_1"  # >= 0.50
    TIER_2 = "tier_2"  # >= 0.70
    TIER_3 = "tier_3"  # >= 0.85


# Tier thresholds (lower bound inclusive)
TIER_THRESHOLDS: dict[ExpertTier, float] = {
    ExpertTier.TIER_1: 0.50,
    ExpertTier.TIER_2: 0.70,
    ExpertTier.TIER_3: 0.85,
}


@dataclass
class Expert:
    """A registered human expert."""

    expert_id: str
    name: str
    domain: str = ""
    agreement_score: float = 0.0
    total_ratings: int = 0
    tier: ExpertTier = ExpertTier.TIER_1

    def to_dict(self) -> dict[str, Any]:
        return {
            "expert_id": self.expert_id,
            "name": self.name,
            "domain": self.domain,
            "agreement_score": self.agreement_score,
            "total_ratings": self.total_ratings,
            "tier": self.tier.value,
        }


@dataclass
class ExpertScoreInput:
    """A single expert's score submission."""

    expert_id: str
    item_id: str
    score: float
    confidence: float = 1.0
    notes: str = ""


def classify_expert_tier(agreement_score: float) -> ExpertTier:
    """Classify an expert into a tier based on agreement score."""
    if agreement_score >= TIER_THRESHOLDS[ExpertTier.TIER_3]:
        return ExpertTier.TIER_3
    elif agreement_score >= TIER_THRESHOLDS[ExpertTier.TIER_2]:
        return ExpertTier.TIER_2
    else:
        return ExpertTier.TIER_1


def calculate_expert_score(
    scores: list[ExpertScoreInput],
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate weighted average score from expert submissions.

    If no weights provided, uses equal weighting.
    """
    if not scores:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for s in scores:
        w = weights.get(s.expert_id, 1.0) if weights else 1.0
        w *= s.confidence
        weighted_sum += s.score * w
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def calculate_krippendorff_alpha(
    ratings_matrix: list[list[float | None]],
) -> float:
    """Compute Krippendorff's alpha using coincidence matrix (numpy-only).

    Uses the ordinal-compatible squared-difference metric function.
    Follows Krippendorff (2011) coincidence matrix formulation where
    each item with m_u raters contributes 1/(m_u-1) to each pair.

    References:
        Krippendorff, K. (2011). Computing Krippendorff's Alpha-Reliability.
            https://repository.upenn.edu/asc_papers/43
        Hayes, A.F. & Krippendorff, K. (2007). Answering the Call for a
            Standard Reliability Measure for Coding Data. Communication
            Methods and Measures, 1(1), 77-89. doi:10.1080/19312450709336664

    Args:
        ratings_matrix: List of raters, each with list of scores per item.
            None = missing rating.

    Returns:
        Alpha coefficient (-1.0 to 1.0). 1.0 = perfect agreement.
    """
    n_raters = len(ratings_matrix)
    if n_raters < 2:
        return 0.0

    n_items = len(ratings_matrix[0])
    if n_items == 0:
        return 0.0

    # Collect pairable values per item and build coincidence matrix
    all_values: list[float] = []
    items_data: list[list[float]] = []

    for item_idx in range(n_items):
        item_values: list[float] = [
            ratings_matrix[r][item_idx]  # type: ignore[misc]
            for r in range(n_raters)
            if ratings_matrix[r][item_idx] is not None
        ]
        if len(item_values) >= 2:
            items_data.append(item_values)
            all_values.extend(item_values)

    if not items_data or len(all_values) < 2:
        return 0.0

    n_total = len(all_values)

    # Observed disagreement (D_o) via coincidence matrix
    # Each item contributes pairs weighted by 1/(m_u - 1)
    observed_disagreement = 0.0
    for item_values in items_data:
        m = len(item_values)
        weight = 1.0 / (m - 1)
        for i in range(m):
            for j in range(i + 1, m):
                observed_disagreement += (
                    (item_values[i] - item_values[j]) ** 2 * 2.0 * weight
                )

    # Expected disagreement (D_e) from marginal frequencies
    # D_e = 1/(n-1) * sum over all c,k pairs of n_c * n_k * delta(c,k)
    # For interval/ordinal squared-difference: delta(c,k) = (c-k)^2
    arr = np.array(all_values, dtype=np.float64)
    # Use vectorized pairwise: sum of (x_i - x_j)^2 for all i<j
    # = n * sum(x^2) - (sum(x))^2 ... via identity
    sum_sq = float(np.sum(arr**2))
    sum_val = float(np.sum(arr))
    expected_disagreement = (
        2.0 * (n_total * sum_sq - sum_val**2) / (n_total * (n_total - 1))
    )

    if abs(expected_disagreement) < 1e-12:
        return 1.0  # Perfect agreement (no variance)

    # Canonical: alpha = 1 - D_o / D_e  (Krippendorff 2011)
    # observed_disagreement is accumulated raw; divide by n_total for mean per-value
    alpha = 1.0 - (observed_disagreement / n_total) / expected_disagreement
    return float(np.clip(alpha, -1.0, 1.0))


@dataclass
class _PanelStats:
    """Internal instrumentation."""

    ratings_collected: int = 0
    consensus_computed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "ratings_collected": self.ratings_collected,
            "consensus_computed": self.consensus_computed,
        }


class ExpertPanel:
    """Manage a panel of human experts for IP evaluation.

    Usage:
        panel = ExpertPanel()
        panel.add_expert(Expert(expert_id="e1", name="Alice", domain="anime"))
        ratings = panel.collect_ratings("berserk", {"e1": 4.5, "e2": 4.0})
        consensus = panel.compute_consensus(ratings)
    """

    def __init__(self) -> None:
        self._experts: dict[str, Expert] = {}
        self._ratings: dict[str, list[ExpertScoreInput]] = {}  # item_id → ratings
        self._stats = _PanelStats()

    @property
    def stats(self) -> _PanelStats:
        return self._stats

    def add_expert(self, expert: Expert) -> None:
        """Register an expert to the panel."""
        self._experts[expert.expert_id] = expert

    def remove_expert(self, expert_id: str) -> bool:
        """Remove an expert. Returns True if found."""
        return self._experts.pop(expert_id, None) is not None

    def get_expert(self, expert_id: str) -> Expert | None:
        """Look up an expert by ID."""
        return self._experts.get(expert_id)

    def list_experts(self, tier: ExpertTier | None = None) -> list[Expert]:
        """List all experts, optionally filtered by tier."""
        experts = list(self._experts.values())
        if tier is not None:
            experts = [e for e in experts if e.tier == tier]
        return experts

    def collect_ratings(
        self,
        item_id: str,
        scores: dict[str, float],
        confidences: dict[str, float] | None = None,
    ) -> list[ExpertScoreInput]:
        """Collect expert ratings for an item.

        Args:
            item_id: The item being rated.
            scores: expert_id → score mapping.
            confidences: Optional expert_id → confidence mapping.

        Returns:
            List of ExpertScoreInput records.
        """
        confidences = confidences or {}
        inputs: list[ExpertScoreInput] = []
        for expert_id, score in scores.items():
            inp = ExpertScoreInput(
                expert_id=expert_id,
                item_id=item_id,
                score=score,
                confidence=confidences.get(expert_id, 1.0),
            )
            inputs.append(inp)
            self._stats.ratings_collected += 1

        if item_id not in self._ratings:
            self._ratings[item_id] = []
        self._ratings[item_id].extend(inputs)

        # Update expert total_ratings
        for inp in inputs:
            expert = self._experts.get(inp.expert_id)
            if expert:
                expert.total_ratings += 1

        return inputs

    def compute_consensus(
        self,
        ratings: list[ExpertScoreInput],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Compute consensus score from ratings.

        Returns dict with: mean_score, weighted_score, n_raters, spread (std).
        """
        self._stats.consensus_computed += 1
        if not ratings:
            return {"mean_score": 0.0, "weighted_score": 0.0, "n_raters": 0, "spread": 0.0}

        scores = [r.score for r in ratings]
        arr = np.array(scores, dtype=np.float64)
        spread = float(np.std(arr, ddof=1)) if len(scores) > 1 else 0.0
        mean_score = float(np.mean(arr))

        # Consensus quality monitoring: flag high disagreement
        spread_alert = False
        if len(scores) > 1 and mean_score > 0:
            # Alert if spread exceeds 30% of mean (coefficient of variation > 0.3)
            cv = spread / abs(mean_score) if abs(mean_score) > 1e-9 else 0.0
            if cv > 0.3:
                spread_alert = True
                log.warning(
                    "High expert disagreement: spread=%.2f, CV=%.2f (n=%d raters)",
                    spread, cv, len(scores),
                )

        return {
            "mean_score": mean_score,
            "weighted_score": calculate_expert_score(ratings, weights),
            "n_raters": len(ratings),
            "spread": spread,
            "spread_alert": spread_alert,
        }

    def get_ratings(self, item_id: str) -> list[ExpertScoreInput]:
        """Retrieve all ratings for an item."""
        return self._ratings.get(item_id, [])

    def update_expert_agreement(self, expert_id: str, agreement_score: float) -> None:
        """Update an expert's agreement score and reclassify tier."""
        expert = self._experts.get(expert_id)
        if expert is None:
            raise KeyError(f"Expert '{expert_id}' not found")
        expert.agreement_score = agreement_score
        expert.tier = classify_expert_tier(agreement_score)


def create_pipeline_panel() -> ExpertPanel:
    """Factory: create an ExpertPanel pre-configured for GEODE pipeline verification.

    Returns a panel with three default expert slots corresponding to
    the GEODE architecture-v6 evaluation dimensions:

    - quality_expert: Evaluates game quality signals (art, gameplay, audio).
    - market_expert: Evaluates market potential and community momentum.
    - technical_expert: Evaluates technical health, platform, and developer track record.

    These slots can be replaced or augmented with real expert profiles
    before collecting ratings.

    Usage:
        panel = create_pipeline_panel()
        panel.collect_ratings("berserk", {"quality_expert": 4.2, "market_expert": 3.8})
    """
    panel = ExpertPanel()
    panel.add_expert(Expert(
        expert_id="quality_expert",
        name="Quality Expert",
        domain="game_quality",
        agreement_score=0.85,
        tier=ExpertTier.TIER_3,
    ))
    panel.add_expert(Expert(
        expert_id="market_expert",
        name="Market Expert",
        domain="market_analysis",
        agreement_score=0.75,
        tier=ExpertTier.TIER_2,
    ))
    panel.add_expert(Expert(
        expert_id="technical_expert",
        name="Technical Expert",
        domain="technical_health",
        agreement_score=0.70,
        tier=ExpertTier.TIER_2,
    ))
    log.info(
        "Created pipeline panel with %d experts: %s",
        len(panel.list_experts()),
        [e.expert_id for e in panel.list_experts()],
    )
    return panel
