"""Cross-LLM verification: agreement check across analyst outputs.

In production, this compares Claude vs GPT scores.
In demo mode, it calculates inter-rater agreement from analyst score
distributions using a normalized agreement coefficient.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from core.automation.expert_panel import calculate_krippendorff_alpha
from core.infrastructure.ports.llm_port import LLMClientPort
from core.state import AnalysisResult, GeodeState

log = logging.getLogger(__name__)

# Agreement threshold: >= 0.67 acceptable, >= 0.80 good
AGREEMENT_THRESHOLD = 0.67

# Scale parameters for agreement normalization
_SCALE_MIN = 1.0
_SCALE_MAX = 5.0
_MAX_VARIANCE = ((_SCALE_MAX - _SCALE_MIN) / 2) ** 2  # 4.0 — max possible variance

# Default model name when adapter info is unavailable
_DEFAULT_PRIMARY_MODEL = "claude-opus-4-6"
_DEFAULT_SECONDARY_MODEL = "gpt-5.4"


def _derive_model_names(
    primary_adapter: LLMClientPort | None = None,
    secondary_adapter: LLMClientPort | None = None,
) -> list[str]:
    """Derive model names from adapter attributes (dynamic, not hardcoded).

    Adapters may expose a ``model_name`` or ``default_model`` attribute.
    Falls back to sensible defaults when the attribute is absent.
    """
    primary = _DEFAULT_PRIMARY_MODEL
    secondary = _DEFAULT_SECONDARY_MODEL

    if primary_adapter is not None:
        primary = str(
            getattr(primary_adapter, "model_name", None)
            or getattr(primary_adapter, "default_model", _DEFAULT_PRIMARY_MODEL)
        )

    if secondary_adapter is not None:
        secondary = str(
            getattr(secondary_adapter, "model_name", None)
            or getattr(secondary_adapter, "default_model", _DEFAULT_SECONDARY_MODEL)
        )

    return [primary, secondary]


def _calc_agreement(scores: list[float], scale_max_var: float = _MAX_VARIANCE) -> float:
    """Calculate normalized agreement coefficient for interval-scale ratings.

    Formula: agreement = 1 - var(scores) / max_possible_variance

    For 1-5 scale, max variance = 4.0 (half at 1, half at 5).
    Returns 1.0 for perfect agreement, 0.0 for maximum disagreement.
    """
    if len(scores) < 2:
        return 1.0

    observed_var = float(np.var(scores, ddof=1))
    if scale_max_var == 0:
        return 1.0

    agreement = 1.0 - observed_var / scale_max_var
    return max(0.0, min(1.0, agreement))


def run_cross_llm_check(
    state: GeodeState,
    *,
    secondary_adapter: LLMClientPort | None = None,
) -> dict[str, Any]:
    """Cross-LLM agreement check using analyst score distributions.

    Uses normalized agreement coefficient to measure inter-rater reliability:
    - agreement >= 0.80: Good (strong consensus)
    - agreement >= 0.67: Acceptable (moderate consensus)
    - agreement < 0.67: Low (high variance, needs review)

    When ``secondary_adapter`` is provided, at least one dimension
    (the first analyst's key finding) is re-scored by the secondary
    model to provide true cross-model verification.  Without it the
    function falls back to single-model agreement analysis.
    """
    analyses: list[AnalysisResult] = state.get("analyses", [])

    if len(analyses) < 2:
        log.debug("Cross-LLM check: insufficient analysts (<2)")
        return {
            "cross_llm_agreement": 1.0,
            "metric": "agreement_coefficient",
            "models_compared": _derive_model_names(secondary_adapter=secondary_adapter),
            "n_raters": len(analyses),
            "passed": True,
            "verification_mode": "insufficient_data",
        }

    # Extract scores and confidence values
    scores = [a.score for a in analyses]
    confidences = [a.confidence for a in analyses]

    # Agreement on scores (1-5 scale)
    score_agreement = _calc_agreement(scores, scale_max_var=_MAX_VARIANCE)

    # Agreement on confidence (0-100 scale, max_var = 50^2 = 2500)
    conf_agreement = _calc_agreement(confidences, scale_max_var=2500.0)

    # Combined: score agreement weighted more heavily
    combined = 0.7 * score_agreement + 0.3 * conf_agreement

    # --- True cross-model re-score when secondary adapter available ---
    secondary_score: int | None = None
    verification_mode = "agreement_only"

    if secondary_adapter is not None and analyses:
        verification_mode = "cross_model"
        first = analyses[0]
        ip_name = state.get("ip_name", "Unknown")
        rescore_prompt = (
            f"Re-evaluate this analyst finding for IP '{ip_name}'. "
            f"Analyst type: {first.analyst_type}. "
            f"Key finding: {first.key_finding}. "
            f"Evidence: {', '.join(first.evidence[:3])}. "
            f"Rate the finding quality 1-5 (1=poor, 5=excellent). "
            f"Respond with ONLY a single digit."
        )
        try:
            response = secondary_adapter.generate(
                "You are a verification agent. Respond with only a single digit 1-5.",
                rescore_prompt,
                temperature=0.1,
                max_tokens=10,
            )
            digit = "".join(c for c in response.strip() if c.isdigit())
            if digit:
                secondary_score = max(1, min(5, int(digit[0])))
            else:
                secondary_score = None  # Mark as unparseable
                log.warning("Secondary LLM response unparseable, excluding from agreement")

            # Blend secondary re-score into agreement only when parseable
            if secondary_score is not None:
                rescore_agreement = 1.0 - abs(first.score - secondary_score) / (
                    _SCALE_MAX - _SCALE_MIN
                )
                rescore_agreement = max(0.0, min(1.0, rescore_agreement))

                # Re-weight: 50% intra-model agreement, 50% cross-model re-score
                combined = 0.5 * combined + 0.5 * rescore_agreement

                log.info(
                    "Cross-model re-score: secondary=%d, original=%.1f, "
                    "rescore_agreement=%.3f, combined=%.3f",
                    secondary_score,
                    first.score,
                    rescore_agreement,
                    combined,
                )
            else:
                verification_mode = "cross_model_degraded"
        except Exception as exc:
            log.warning("Secondary adapter re-score failed, using agreement only: %s", exc)
            verification_mode = "agreement_fallback"

    # Krippendorff's alpha as secondary reliability measure
    try:
        # Each analyst is a rater scoring 1 item (the IP)
        ratings_matrix: list[list[float | None]] = [[s] for s in scores]
        alpha = calculate_krippendorff_alpha(ratings_matrix)
        krippendorff_alpha: float | None = round(alpha, 4)
    except Exception:
        krippendorff_alpha = None

    passed = combined >= AGREEMENT_THRESHOLD

    log.info(
        "Cross-LLM agreement: %.3f (score=%.3f, conf=%.3f), passed=%s, mode=%s",
        combined,
        score_agreement,
        conf_agreement,
        passed,
        verification_mode,
    )

    if state.get("verbose"):
        log.debug(
            "Cross-LLM: agreement=%.3f (score=%.3f, conf=%.3f) mode=%s %s",
            combined,
            score_agreement,
            conf_agreement,
            verification_mode,
            "passed" if passed else "failed",
        )

    result: dict[str, Any] = {
        "cross_llm_agreement": round(combined, 4),
        "score_agreement": round(score_agreement, 4),
        "confidence_agreement": round(conf_agreement, 4),
        "krippendorff_alpha": krippendorff_alpha,
        "metric": "agreement_coefficient",
        "models_compared": _derive_model_names(secondary_adapter=secondary_adapter),
        "n_raters": len(analyses),
        "passed": passed,
        "threshold": AGREEMENT_THRESHOLD,
        "verification_mode": verification_mode,
    }
    if secondary_score is not None:
        result["secondary_rescore"] = secondary_score
    return result


def run_dual_adapter_check(
    state: GeodeState,
    *,
    primary_adapter: LLMClientPort | None = None,
    secondary_adapter: LLMClientPort | None = None,
) -> dict[str, Any]:
    """Cross-LLM verification using dual adapters (Claude ↔ GPT).

    When both adapters are available, runs a lightweight re-score
    on the secondary model and compares with primary results.
    Falls back to agreement-based check if adapters unavailable.

    Args:
        state: Current pipeline state with analyses.
        primary_adapter: Primary LLMClientPort (e.g. ClaudeAdapter).
        secondary_adapter: Secondary LLMClientPort (e.g. OpenAIAdapter).
    """
    # If no adapters, fall back to standard check
    if primary_adapter is None or secondary_adapter is None:
        result = run_cross_llm_check(state)
        result["verification_mode"] = "agreement_only"
        return result

    # Standard agreement check first
    base_result = run_cross_llm_check(state)

    # Dual-adapter verification: ask secondary model for a quick sanity check
    ip_name = state.get("ip_name", "Unknown")
    tier = state.get("tier", "?")
    score = state.get("final_score", 0.0)

    verification_prompt = (
        f"Verify this IP analysis result. IP: {ip_name}, Tier: {tier}, Score: {score:.1f}/100. "
        f"Rate your agreement 1-5 (1=strongly disagree, 5=strongly agree). "
        f"Respond with ONLY a single digit."
    )

    try:
        response = secondary_adapter.generate(
            "You are a verification agent. Respond with only a single digit 1-5.",
            verification_prompt,
            temperature=0.1,
            max_tokens=10,
        )
        # Parse agreement score
        digit = "".join(c for c in response.strip() if c.isdigit())
        if digit:
            secondary_agreement = int(digit[0])
            secondary_agreement = max(1, min(5, secondary_agreement))
        else:
            secondary_agreement = None
            log.warning("Dual-adapter secondary response unparseable, marking degraded")

        # Combine: base agreement (70%) + secondary cross-check (30%)
        # Skip blending when secondary is unparseable
        if secondary_agreement is not None:
            secondary_normalized = secondary_agreement / 5.0
            combined = 0.7 * base_result["cross_llm_agreement"] + 0.3 * secondary_normalized
            passed = combined >= AGREEMENT_THRESHOLD
            verification_mode = "dual_adapter"

            log.info(
                "Dual-adapter check: base=%.3f, secondary=%d/5 (%.3f), combined=%.3f",
                base_result["cross_llm_agreement"],
                secondary_agreement,
                secondary_normalized,
                combined,
            )

            return {
                **base_result,
                "cross_llm_agreement": round(combined, 4),
                "models_compared": _derive_model_names(
                    primary_adapter=primary_adapter,
                    secondary_adapter=secondary_adapter,
                ),
                "secondary_agreement": secondary_agreement,
                "secondary_normalized": round(secondary_normalized, 4),
                "verification_mode": verification_mode,
                "passed": passed,
            }
        else:
            # Degraded: secondary unparseable, use base result only
            log.warning("Dual-adapter degraded: secondary unparseable, using base agreement only")
            return {
                **base_result,
                "models_compared": _derive_model_names(
                    primary_adapter=primary_adapter,
                    secondary_adapter=secondary_adapter,
                ),
                "verification_mode": "dual_adapter_degraded",
            }

    except Exception as exc:
        log.warning("Dual-adapter check failed, falling back: %s", exc)
        base_result["verification_mode"] = "agreement_fallback"
        base_result["dual_adapter_error"] = str(exc)
        return base_result
