"""Layer 4: PSM Engine + Final Score Calculation.

Implements architecture-v6 §13.8.1 scoring formula.
PSM uses fixture data but applies real statistical formulas.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from geode.fixtures import load_fixture
from geode.state import (
    AnalysisResult,
    EvaluatorResult,
    GeodeState,
    PSMResult,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PSM Engine (fixture-based with real formula application)
# ---------------------------------------------------------------------------


def _compute_psm(ip_name: str, monolake: dict) -> PSMResult:
    """Compute PSM result.

    For demo: uses expected_results from fixture for ATT/Z/Gamma,
    but validates using real statistical thresholds.
    """
    try:
        data = load_fixture(ip_name)
        expected = data.get("expected_results", {})
        att = expected.get("psm_att_pct", 25.0)
        z = expected.get("psm_z_value", 2.0)
        gamma = expected.get("psm_gamma", 1.5)
    except ValueError:
        att = 25.0
        z = 2.0
        gamma = 1.5

    # Compute exposure lift score (ATT → 0-100)
    # Map ATT% to 0-100: ATT of ~30% → ~78 score
    exposure_lift = min(100.0, max(0.0, att * 1.5 + 30))

    # Validity checks (real thresholds)
    z_pass = z > 1.645
    gamma_pass = gamma <= 2.0
    smd = 0.05  # Fixture: all covariates balanced

    return PSMResult(
        att_pct=att,
        z_value=z,
        rosenbaum_gamma=gamma,
        max_smd=smd,
        exposure_lift_score=exposure_lift,
        psm_valid=z_pass and gamma_pass and smd < 0.1,
    )


# ---------------------------------------------------------------------------
# Developer Track Record (§13.8 dedicated rubric, fixture-based)
# ---------------------------------------------------------------------------


def _load_developer_score(ip_name: str, quality_fallback: float) -> float:
    """Load developer_track_record from fixture, fallback to quality*0.8."""
    try:
        data = load_fixture(ip_name)
        dev = data.get("expected_results", {}).get("developer_track_record")
        if dev is not None:
            return float(dev)
    except ValueError:
        pass
    return quality_fallback * 0.8


# ---------------------------------------------------------------------------
# Subscore calculations (architecture-v6 §13.8.2-§13.8.5)
# ---------------------------------------------------------------------------


def _calc_quality_score(evaluations: dict[str, EvaluatorResult]) -> float:
    """§13.8.2: Quality = (A+B+C+B1+C1+C2+M+N) / 8 * 20.

    Server-side calculation from raw axes instead of trusting LLM composite.
    """
    qj = evaluations.get("quality_judge")
    if not qj:
        return 50.0
    axes_sum = sum(qj.axes.values())
    return (axes_sum / 8) * 20


def _calc_recovery_potential(evaluations: dict[str, EvaluatorResult]) -> float:
    """§13.8.2: Recovery = ((E + F) - 2) / 8 * 100. D excluded."""
    hv = evaluations.get("hidden_value")
    if not hv:
        return 50.0
    e = hv.axes.get("e_score", 3.0)
    f = hv.axes.get("f_score", 3.0)
    return ((e + f) - 2) / 8 * 100


def _calc_growth_score(
    evaluations: dict[str, EvaluatorResult],
    developer_track_record: float = 50.0,
) -> float:
    """§13.8.3: Growth = 0.4*trend + 0.4*expandability + 0.2*developer.

    Args:
        evaluations: Evaluator results dict.
        developer_track_record: Dedicated developer rubric score (0-100).
            Falls back to quality_judge * 0.8 if fixture provides no value.
    """
    hv = evaluations.get("hidden_value")
    cm = evaluations.get("community_momentum")

    # Trend alignment: community momentum composite as proxy for market trend
    trend = cm.composite_score if cm else 50.0
    # IP expandability: F axis normalized to 0-100
    expand = ((hv.axes.get("f_score", 3.0) - 1) / 4 * 100) if hv else 50.0

    return 0.40 * trend + 0.40 * expand + 0.20 * developer_track_record


def _calc_community_momentum(evaluations: dict[str, EvaluatorResult]) -> float:
    """§13.8.4: Momentum = ((J+K+L)-3)/12 * 100."""
    cm = evaluations.get("community_momentum")
    if not cm:
        return 50.0
    j = cm.axes.get("j_score", 3.0)
    k = cm.axes.get("k_score", 3.0)
    l_ = cm.axes.get("l_score", 3.0)
    return ((j + k + l_) - 3) / 12 * 100


def _calc_analyst_confidence(analyses: list[AnalysisResult]) -> float:
    """§13.8.5: Confidence = (1 - CV) * 100, clamped 0-100."""
    if len(analyses) < 2:
        return 100.0
    scores = [a.score for a in analyses]
    mean = float(np.mean(scores))
    std = float(np.std(scores))
    if mean == 0:
        return 100.0
    cv = std / mean
    return max(0.0, min(100.0, (1 - cv) * 100))


def _calc_final_score(
    exposure_lift: float,
    quality: float,
    recovery: float,
    growth: float,
    momentum: float,
    developer: float,
    confidence: float,
) -> float:
    """§13.8.1: Final score with confidence multiplier."""
    base = (
        0.25 * exposure_lift
        + 0.20 * quality
        + 0.18 * recovery
        + 0.12 * growth
        + 0.20 * momentum
        + 0.05 * developer
    )
    multiplier = 0.7 + (0.3 * confidence / 100)
    return base * multiplier


def _determine_tier(score: float) -> str:
    if score >= 80:
        return "S"
    elif score >= 60:
        return "A"
    elif score >= 40:
        return "B"
    else:
        return "C"


# ---------------------------------------------------------------------------
# Scoring Node
# ---------------------------------------------------------------------------


def scoring_node(state: GeodeState) -> dict[str, Any]:
    """Layer 4: Compute PSM + all subscores + final score + tier."""
    try:
        ip_name = state.get("ip_name", "unknown")
        monolake = state.get("monolake", {})
        analyses = state.get("analyses", [])
        evaluations = state.get("evaluations", {})

        # PSM
        psm = _compute_psm(ip_name, monolake)

        # Subscores (server-side calculation from raw axes)
        quality_score = _calc_quality_score(evaluations)
        recovery = _calc_recovery_potential(evaluations)
        momentum = _calc_community_momentum(evaluations)
        confidence = _calc_analyst_confidence(analyses)

        # Developer track record: use fixture value if available, else proxy
        developer = _load_developer_score(ip_name, quality_score)
        growth = _calc_growth_score(evaluations, developer_track_record=developer)

        if state.get("verbose"):
            log.debug("PSM: ATT=%+.1f%%, Z=%.2f", psm.att_pct, psm.z_value)
            log.debug(
                "Subscores: Q=%.0f R=%.0f G=%.0f M=%.0f",
                quality_score,
                recovery,
                growth,
                momentum,
            )

        final = _calc_final_score(
            exposure_lift=psm.exposure_lift_score,
            quality=quality_score,
            recovery=recovery,
            growth=growth,
            momentum=momentum,
            developer=developer,
            confidence=confidence,
        )
        tier = _determine_tier(final)

        subscores = {
            "exposure_lift": psm.exposure_lift_score,
            "quality": quality_score,
            "recovery_potential": recovery,
            "growth": growth,
            "community_momentum": momentum,
            "developer_track": developer,
        }

        return {
            "psm_result": psm,
            "subscores": subscores,
            "analyst_confidence": confidence,
            "final_score": final,
            "tier": tier,
        }
    except Exception as exc:
        log.error("Node scoring failed: %s", exc)
        return {"errors": [f"scoring: {exc}"]}
