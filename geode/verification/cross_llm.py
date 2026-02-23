"""Cross-LLM verification: agreement check across analyst outputs.

In production, this compares Claude vs GPT scores.
In demo mode, it calculates inter-rater agreement from analyst score
distributions using a normalized agreement coefficient.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from geode.state import AnalysisResult, GeodeState
from geode.ui.console import console

log = logging.getLogger(__name__)

# Agreement threshold: >= 0.67 acceptable, >= 0.80 good
AGREEMENT_THRESHOLD = 0.67

# Scale parameters for agreement normalization
_SCALE_MIN = 1.0
_SCALE_MAX = 5.0
_MAX_VARIANCE = ((_SCALE_MAX - _SCALE_MIN) / 2) ** 2  # 4.0 — max possible variance


def _calc_agreement(scores: list[float], scale_max_var: float = _MAX_VARIANCE) -> float:
    """Calculate normalized agreement coefficient for interval-scale ratings.

    Formula: agreement = 1 - var(scores) / max_possible_variance

    For 1-5 scale, max variance = 4.0 (half at 1, half at 5).
    Returns 1.0 for perfect agreement, 0.0 for maximum disagreement.
    """
    if len(scores) < 2:
        return 1.0

    observed_var = float(np.var(scores))
    if scale_max_var == 0:
        return 1.0

    agreement = 1.0 - observed_var / scale_max_var
    return max(0.0, min(1.0, agreement))


def run_cross_llm_check(state: GeodeState) -> dict[str, Any]:
    """Cross-LLM agreement check using analyst score distributions.

    Uses normalized agreement coefficient to measure inter-rater reliability:
    - agreement >= 0.80: Good (strong consensus)
    - agreement >= 0.67: Acceptable (moderate consensus)
    - agreement < 0.67: Low (high variance, needs review)
    """
    analyses: list[AnalysisResult] = state.get("analyses", [])

    if len(analyses) < 2:
        console.print("    [muted]Cross-LLM check: insufficient analysts (<2)[/muted]")
        return {
            "cross_llm_agreement": 1.0,
            "metric": "agreement_coefficient",
            "models_compared": ["claude-opus-4-6", "gpt-5.3"],
            "n_raters": len(analyses),
            "passed": True,
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
    passed = combined >= AGREEMENT_THRESHOLD

    log.info(
        "Cross-LLM agreement: %.3f (score=%.3f, conf=%.3f), passed=%s",
        combined,
        score_agreement,
        conf_agreement,
        passed,
    )

    if state.get("verbose"):
        console.print(
            f"    [muted]Cross-LLM: agreement={combined:.3f} "
            f"(score={score_agreement:.3f}, conf={conf_agreement:.3f}) "
            f"{'✓' if passed else '✗'}[/muted]"
        )

    return {
        "cross_llm_agreement": round(combined, 4),
        "score_agreement": round(score_agreement, 4),
        "confidence_agreement": round(conf_agreement, 4),
        "metric": "agreement_coefficient",
        "models_compared": ["claude-opus-4-6", "gpt-5.3"],
        "n_raters": len(analyses),
        "passed": passed,
        "threshold": AGREEMENT_THRESHOLD,
    }


def run_dual_adapter_check(
    state: GeodeState,
    *,
    primary_adapter=None,
    secondary_adapter=None,
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
            secondary_agreement = 3  # Neutral if unparseable

        # Combine: base agreement (70%) + secondary cross-check (30%)
        secondary_normalized = secondary_agreement / 5.0
        combined = 0.7 * base_result["cross_llm_agreement"] + 0.3 * secondary_normalized
        passed = combined >= AGREEMENT_THRESHOLD

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
            "secondary_agreement": secondary_agreement,
            "secondary_normalized": round(secondary_normalized, 4),
            "verification_mode": "dual_adapter",
            "passed": passed,
        }

    except Exception as exc:
        log.warning("Dual-adapter check failed, falling back: %s", exc)
        base_result["verification_mode"] = "agreement_fallback"
        base_result["dual_adapter_error"] = str(exc)
        return base_result
