"""Layer 4: PSM Engine + Final Score Calculation.

Implements architecture-v6 §13.8.1 scoring formula.
PSM uses fixture data but applies real statistical formulas.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from core.fixtures import load_fixture
from core.infrastructure.ports.domain_port import get_domain_or_none
from core.infrastructure.ports.tool_port import get_tool_executor
from core.state import (
    AnalysisResult,
    EvaluatorResult,
    GeodeState,
    PSMResult,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PSM Engine (fixture-based with real formula application)
# ---------------------------------------------------------------------------


def _logistic_propensity(X: np.ndarray, y: np.ndarray, max_iter: int = 100) -> np.ndarray:
    """Simple logistic regression for propensity score estimation (numpy-only).

    Uses iteratively reweighted least squares (IRLS) for stable convergence.
    Returns predicted probabilities P(treatment=1|X).
    """
    n, k = X.shape
    # Add intercept
    X_aug = np.column_stack([np.ones(n), X])
    beta = np.zeros(X_aug.shape[1])

    for _ in range(max_iter):
        z = X_aug @ beta
        # Clip to prevent overflow in exp
        z = np.clip(z, -20.0, 20.0)
        p = 1.0 / (1.0 + np.exp(-z))
        p = np.clip(p, 1e-6, 1 - 1e-6)

        # IRLS update
        W = np.diag(p * (1 - p))
        try:
            beta_new = beta + np.linalg.solve(X_aug.T @ W @ X_aug, X_aug.T @ (y - p))
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(beta_new - beta)) < 1e-6:
            beta = beta_new
            break
        beta = beta_new

    z = np.clip(X_aug @ beta, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-z))


def _nn_match_with_caliper(
    ps_treated: np.ndarray,
    ps_control: np.ndarray,
    caliper: float,
) -> list[tuple[int, int]]:
    """1:1 nearest-neighbor matching with caliper constraint.

    Returns list of (treated_idx, control_idx) matched pairs.
    """
    matches: list[tuple[int, int]] = []
    used_control: set[int] = set()

    for t_idx in range(len(ps_treated)):
        best_dist = float("inf")
        best_c_idx = -1
        for c_idx in range(len(ps_control)):
            if c_idx in used_control:
                continue
            dist = abs(ps_treated[t_idx] - ps_control[c_idx])
            if dist < best_dist and dist <= caliper:
                best_dist = dist
                best_c_idx = c_idx
        if best_c_idx >= 0:
            matches.append((t_idx, best_c_idx))
            used_control.add(best_c_idx)

    return matches


def _compute_smd(treated: np.ndarray, control: np.ndarray) -> float:
    """Standardized Mean Difference for balance check."""
    mean_diff = np.mean(treated) - np.mean(control)
    pooled_var = (np.var(treated) + np.var(control)) / 2
    if pooled_var < 1e-12:
        return 0.0
    return abs(float(mean_diff / np.sqrt(pooled_var)))


def _compute_psm(ip_name: str, monolake: dict[str, Any]) -> PSMResult:
    """Compute PSM result with simulation engine.

    If monolake contains covariate data (treated/control groups), runs full
    PSM simulation: logistic PS estimation → 1:1 NN matching → SMD balance
    check → ATT calculation → z-value → Rosenbaum Gamma bounds.

    Falls back to fixture-based results when covariates are unavailable.
    """
    # Try simulation if monolake has covariates
    covariates = monolake.get("psm_covariates")
    if covariates is not None:
        try:
            X = np.array(covariates["X"], dtype=np.float64)
            y = np.array(covariates["treatment"], dtype=np.float64)
            outcomes = np.array(covariates["outcome"], dtype=np.float64)

            # Step 1: Propensity Score estimation
            ps = _logistic_propensity(X, y)

            # Step 2: 1:1 NN Matching with caliper (0.2 × SD(PS))
            treated_mask = y == 1
            control_mask = y == 0
            ps_treated = ps[treated_mask]
            ps_control = ps[control_mask]
            caliper = 0.2 * float(np.std(ps))
            if caliper < 1e-6:
                caliper = 0.05  # Floor

            matches = _nn_match_with_caliper(ps_treated, ps_control, caliper)

            if len(matches) < 3:
                log.warning("PSM: too few matches (%d), falling back to fixture", len(matches))
                raise ValueError("Insufficient matches for PSM")

            # Extract matched samples
            t_indices = np.where(treated_mask)[0]
            c_indices = np.where(control_mask)[0]
            matched_t = np.array([t_indices[m[0]] for m in matches])
            matched_c = np.array([c_indices[m[1]] for m in matches])

            # Step 3: SMD balance check (< 0.1 for all covariates)
            max_smd = 0.0
            for col in range(X.shape[1]):
                smd = _compute_smd(X[matched_t, col], X[matched_c, col])
                max_smd = max(max_smd, smd)

            # Step 4: ATT calculation
            att = float(np.mean(outcomes[matched_t]) - np.mean(outcomes[matched_c]))
            att_pct = att * 100  # Convert to percentage

            # Step 5: z-value (Wald test)
            diff = outcomes[matched_t] - outcomes[matched_c]
            se = float(np.std(diff)) / np.sqrt(len(diff)) if len(diff) > 0 else 1.0
            z_value = float(np.mean(diff) / se) if se > 1e-12 else 0.0

            # Step 6: Rosenbaum Gamma bounds (sensitivity analysis)
            # Approximate: if z > 1.96, gamma ≈ exp(z/sqrt(n_matches))
            n_matches = len(matches)
            gamma = float(np.exp(abs(z_value) / np.sqrt(n_matches))) if n_matches > 0 else 1.0

            exposure_lift = min(100.0, max(0.0, att_pct * 1.5 + 30))
            z_pass = abs(z_value) > 1.645
            gamma_pass = gamma <= 2.0

            return PSMResult(
                att_pct=att_pct,
                z_value=z_value,
                rosenbaum_gamma=gamma,
                max_smd=max_smd,
                exposure_lift_score=exposure_lift,
                psm_valid=z_pass and gamma_pass and max_smd < 0.1,
            )
        except (KeyError, ValueError, np.linalg.LinAlgError) as exc:
            log.warning("PSM simulation failed for %s: %s — falling back to fixture", ip_name, exc)

    # Graceful degradation: fixture-based fallback
    try:
        data = load_fixture(ip_name)
        expected = data.get("expected_results", {})
        att = expected.get("psm_att_pct", 25.0)
        z = expected.get("psm_z_value", 2.0)
        gamma = expected.get("psm_gamma", 1.5)
    except ValueError as ve:
        log.warning("PSM fixture load failed for %s: %s", ip_name, ve)
        att = 25.0
        z = 2.0
        gamma = 1.5

    # Compute exposure lift score (ATT → 0-100)
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
    except ValueError as ve:
        log.warning("Developer score fixture load failed: %s", ve)

    return quality_fallback * 0.8


# ---------------------------------------------------------------------------
# Subscore calculations (architecture-v6 §13.8.2-§13.8.5)
# ---------------------------------------------------------------------------


def _calc_quality_score(evaluations: dict[str, EvaluatorResult]) -> float:
    """§13.8.2: Quality = (axes_sum - 8) / 32 * 100.

    Server-side calculation from raw axes instead of trusting LLM composite.
    Normalizes 8-axis sum from [8, 40] → [0, 100]. Missing axes padded with 3.0 (neutral).
    """
    qj = evaluations.get("quality_judge")
    if not qj:
        return 50.0
    expected_count = 8
    # Pad missing axes with neutral score (3.0)
    axes_values = list(qj.axes.values())
    if len(axes_values) < expected_count:
        log.warning(
            "Quality score: expected %d axes, got %d — padding with 3.0",
            expected_count,
            len(axes_values),
        )
        axes_values.extend([3.0] * (expected_count - len(axes_values)))
    axes_sum = sum(axes_values)
    return (axes_sum - 8) / 32 * 100


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
    momentum: float | None = None,
) -> float:
    """§13.8.3: Growth = 0.4*trend + 0.4*expandability + 0.2*developer.

    Args:
        evaluations: Evaluator results dict.
        developer_track_record: Dedicated developer rubric score (0-100).
            Falls back to quality_judge * 0.8 if fixture provides no value.
        momentum: Pre-computed community momentum score. If None, computed
            from evaluations (avoids double calculation in scoring_node).
    """
    hv = evaluations.get("hidden_value")

    # Trend alignment: server-side momentum calc (not LLM composite_score)
    trend = momentum if momentum is not None else _calc_community_momentum(evaluations)
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
    """§13.8.5: Confidence = (1 - CV) * 100, clamped 0-100.

    Edge cases:
    - 0 analyses → 0% (no data = no confidence)
    - 1 analysis → 50% (single-source penalty)
    - mean==0    → 10% (all-zero scores = minimal confidence)
    """
    if len(analyses) == 0:
        return 0.0
    if len(analyses) == 1:
        return 50.0
    scores = [a.score for a in analyses]
    mean = float(np.mean(scores))
    std = float(np.std(scores))
    if mean == 0:
        return 10.0
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
    """§13.8.1: Final score with confidence multiplier.

    Domain-aware: when a DomainPort is active, uses domain-provided weights
    and confidence multiplier params. Falls back to hardcoded game-IP defaults.
    """
    domain = get_domain_or_none()
    if domain is not None:
        weights = domain.get_scoring_weights()
        base_m, scale_m = domain.get_confidence_multiplier_params()
    else:
        weights = {
            "exposure_lift": 0.25,
            "quality": 0.20,
            "recovery": 0.18,
            "growth": 0.12,
            "momentum": 0.20,
            "developer": 0.05,
        }
        base_m, scale_m = 0.7, 0.3

    base = (
        weights.get("exposure_lift", 0.25) * exposure_lift
        + weights.get("quality", 0.20) * quality
        + weights.get("recovery", 0.18) * recovery
        + weights.get("growth", 0.12) * growth
        + weights.get("momentum", 0.20) * momentum
        + weights.get("developer", 0.05) * developer
    )
    multiplier = base_m + (scale_m * confidence / 100)
    return base * multiplier


def _calc_prospect_score(evaluations: dict[str, EvaluatorResult]) -> float:
    """Prospect IP scoring: (axes_sum - 9) / 36 * 100.

    9-axis evaluation for non-gamified IPs. Missing axes padded with 3.0 (neutral).
    """
    pj = evaluations.get("prospect_judge")
    if not pj:
        return 50.0
    expected_count = 9
    axes_values = list(pj.axes.values())
    if len(axes_values) < expected_count:
        log.warning(
            "Prospect score: expected %d axes, got %d — padding with 3.0",
            expected_count,
            len(axes_values),
        )
        axes_values.extend([3.0] * (expected_count - len(axes_values)))
    axes_sum = sum(axes_values)
    return (axes_sum - 9) / 36 * 100


def _determine_tier(score: float) -> str:
    """Determine tier from score.

    Domain-aware: when a DomainPort is active, uses domain-provided thresholds.
    Falls back to hardcoded game-IP thresholds (S/A/B/C).
    """
    domain = get_domain_or_none()
    if domain is not None:
        for threshold, tier_name in domain.get_tier_thresholds():
            if score >= threshold:
                return tier_name
        return domain.get_tier_fallback()
    # Fallback: hardcoded game IP thresholds
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


def _enrich_from_tools(ip_name: str, state: GeodeState) -> dict[str, Any]:
    """Optionally enrich scoring with tool data (memory_search, psm_calculate).

    Returns dict of extra context; empty dict if tools unavailable.
    """
    tool_defs: Any = state.get("_tool_definitions", [])
    tool_executor = get_tool_executor()
    if not tool_defs or tool_executor is None:
        return {}
    enrichment: dict[str, Any] = {}
    # Query past scores from memory for calibration reference
    try:
        mem_result = tool_executor("memory_search", query=f"scoring {ip_name}", limit=3)
        if mem_result and not mem_result.get("error"):
            enrichment["historical_scores"] = mem_result
    except Exception as exc:
        log.debug("Scoring tool enrichment (memory_search) failed: %s", exc)
    return enrichment


def scoring_node(state: GeodeState) -> dict[str, Any]:
    """Layer 4: Compute PSM + all subscores + final score + tier.

    Handles both standard (gamified, 14-axis) and prospect (9-axis) pipelines.
    """
    try:
        ip_name = state.get("ip_name", "unknown")
        monolake = state.get("monolake", {})
        analyses = state.get("analyses", [])
        evaluations = state.get("evaluations", {})
        mode = state.get("pipeline_mode", "full_pipeline")

        # Tool enrichment (Phase 2-C): query memory for historical context.
        # Result logged for observability; not yet integrated into formula.
        _enrich_from_tools(ip_name, state)

        # Prospect mode: simplified scoring using 9-axis prospect_judge
        if mode == "prospect":
            prospect_score = _calc_prospect_score(evaluations)
            confidence = _calc_analyst_confidence(analyses)
            prospect_score = max(0.0, min(100.0, prospect_score))
            confidence = max(0.0, min(100.0, confidence))
            multiplier = 0.7 + (0.3 * confidence / 100)
            final = prospect_score * multiplier
            tier = _determine_tier(final)
            return {
                "subscores": {"prospect_score": prospect_score},
                "analyst_confidence": confidence,
                "final_score": final,
                "tier": tier,
            }

        # PSM
        psm = _compute_psm(ip_name, monolake)

        # Subscores (server-side calculation from raw axes)
        quality_score = _calc_quality_score(evaluations)
        recovery = _calc_recovery_potential(evaluations)
        momentum = _calc_community_momentum(evaluations)
        confidence = _calc_analyst_confidence(analyses)

        # Developer track record: use fixture value if available, else proxy
        developer = _load_developer_score(ip_name, quality_score)
        growth = _calc_growth_score(
            evaluations,
            developer_track_record=developer,
            momentum=momentum,
        )

        # Clamp all subscores to [0, 100] for normalization safety
        quality_score = max(0.0, min(100.0, quality_score))
        recovery = max(0.0, min(100.0, recovery))
        momentum = max(0.0, min(100.0, momentum))
        confidence = max(0.0, min(100.0, confidence))
        developer = max(0.0, min(100.0, developer))
        growth = max(0.0, min(100.0, growth))

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

        result: dict[str, Any] = {
            "psm_result": psm,
            "subscores": subscores,
            "analyst_confidence": confidence,
            "final_score": final,
            "tier": tier,
        }

        # Dynamic Graph: determine post-scoring path based on score extremity
        skip_nodes = list(state.get("skip_nodes", []))

        if final >= 90 or final <= 20:
            # Extreme scores (S>=90 or C<=20): high confidence in result,
            # skip verification and go straight to synthesizer
            if "verification" not in skip_nodes:
                skip_nodes.append("verification")
                log.info(
                    "Dynamic Graph: extreme score %.1f → skipping verification",
                    final,
                )
            result["skip_nodes"] = skip_nodes
        elif 40 <= final <= 80:
            # Mid-range scores: ambiguous zone, flag for enrichment
            result["enrichment_needed"] = True
            log.info(
                "Dynamic Graph: mid-range score %.1f → enrichment_needed=True",
                final,
            )

        return result
    except Exception as exc:
        log.exception("Scoring node failed: %s", exc)
        return {"errors": [f"scoring: {type(exc).__name__}: {exc}"]}
