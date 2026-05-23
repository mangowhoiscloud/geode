"""Generic cross-LLM agreement checks for structured analysis outputs."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from core.config import settings
from core.llm.prompts import CROSS_LLM_DUAL_VERIFY, CROSS_LLM_RESCORE, CROSS_LLM_SYSTEM
from core.llm.router import LLMClientPort
from core.state import GeodeState
from core.verification.stats import calculate_krippendorff_alpha

log = logging.getLogger(__name__)

DEFAULT_AGREEMENT_THRESHOLD = 0.67
_SCALE_MIN = 0.0
_SCALE_MAX = 100.0
_MAX_VARIANCE = ((_SCALE_MAX - _SCALE_MIN) / 2) ** 2
_DEFAULT_PRIMARY_MODEL = "claude-opus-4-6"
_DEFAULT_SECONDARY_MODEL = "gpt-5.4"


def _derive_model_names(
    primary_adapter: LLMClientPort | None = None,
    secondary_adapter: LLMClientPort | None = None,
) -> list[str]:
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
    """Calculate normalized agreement coefficient for interval-scale ratings."""
    if len(scores) < 2:
        return 1.0
    observed_var = float(np.var(scores, ddof=1))
    if scale_max_var == 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - observed_var / scale_max_var))


def _item_field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _analysis_scores(analyses: list[Any]) -> list[float]:
    scores: list[float] = []
    for item in analyses:
        value = _item_field(item, "score")
        if isinstance(value, int | float) and not isinstance(value, bool):
            scores.append(float(value))
    return scores


def _analysis_confidences(analyses: list[Any]) -> list[float]:
    values: list[float] = []
    for item in analyses:
        value = _item_field(item, "confidence")
        if isinstance(value, int | float) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _parse_secondary_score(response: str) -> float | None:
    digits = "".join(ch for ch in response.strip() if ch.isdigit())
    if not digits:
        return None
    return max(0.0, min(100.0, float(int(digits[:3]))))


def run_cross_llm_check(
    state: GeodeState,
    *,
    secondary_adapter: LLMClientPort | None = None,
    agreement_threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
) -> dict[str, Any]:
    """Check agreement across analysis scores and optional secondary re-score."""
    analyses = list(state.get("analyses", []))
    scores = _analysis_scores(analyses)

    if len(scores) < 2:
        log.debug("Cross-LLM check: insufficient scored analyses (<2)")
        return {
            "cross_llm_agreement": 1.0,
            "metric": "agreement_coefficient",
            "models_compared": _derive_model_names(secondary_adapter=secondary_adapter),
            "n_raters": len(scores),
            "passed": True,
            "verification_mode": "insufficient_data",
        }

    confidences = _analysis_confidences(analyses)
    score_agreement = _calc_agreement(scores)
    conf_agreement = _calc_agreement(confidences, scale_max_var=2500.0) if confidences else 1.0
    combined = 0.7 * score_agreement + 0.3 * conf_agreement
    secondary_score: float | None = None
    verification_mode = "agreement_only"

    if secondary_adapter is not None and analyses:
        verification_mode = "cross_model"
        first = analyses[0]
        subject_id = str(state.get("subject_id", "Unknown"))
        rescore_prompt = CROSS_LLM_RESCORE.format(
            subject_id=subject_id,
            analysis_name=_item_field(
                first,
                "name",
                _item_field(first, "analyst_type", "analysis"),
            ),
            key_finding=_item_field(first, "key_finding", _item_field(first, "summary", "")),
            evidence=", ".join(str(item) for item in list(_item_field(first, "evidence", []))[:3]),
        )
        try:
            response = secondary_adapter.generate(
                CROSS_LLM_SYSTEM,
                rescore_prompt,
                temperature=settings.temperature_verification,
                max_tokens=10,
            )
            secondary_score = _parse_secondary_score(response)
            if secondary_score is not None:
                rescore_agreement = 1.0 - abs(scores[0] - secondary_score) / (
                    _SCALE_MAX - _SCALE_MIN
                )
                combined = 0.5 * combined + 0.5 * max(0.0, min(1.0, rescore_agreement))
            else:
                verification_mode = "cross_model_degraded"
        except Exception as exc:
            log.warning("Secondary adapter re-score failed, using agreement only: %s", exc)
            verification_mode = "agreement_fallback"

    try:
        ratings_matrix: list[list[float | None]] = [[score] for score in scores]
        krippendorff_alpha: float | None = round(calculate_krippendorff_alpha(ratings_matrix), 4)
    except Exception:
        krippendorff_alpha = None

    passed = combined >= agreement_threshold
    result: dict[str, Any] = {
        "cross_llm_agreement": round(combined, 4),
        "score_agreement": round(score_agreement, 4),
        "confidence_agreement": round(conf_agreement, 4),
        "krippendorff_alpha": krippendorff_alpha,
        "metric": "agreement_coefficient",
        "models_compared": _derive_model_names(secondary_adapter=secondary_adapter),
        "n_raters": len(scores),
        "passed": passed,
        "threshold": agreement_threshold,
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
    agreement_threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
) -> dict[str, Any]:
    """Run agreement checks with optional primary/secondary model metadata."""
    if primary_adapter is None or secondary_adapter is None:
        fallback = run_cross_llm_check(state, agreement_threshold=agreement_threshold)
        fallback["verification_mode"] = "agreement_only"
        return fallback

    base_result = run_cross_llm_check(state, agreement_threshold=agreement_threshold)
    subject_id = str(state.get("subject_id", "Unknown"))
    result = state.get("result", {})
    raw_score = result.get("score", result.get("final_score")) if isinstance(result, dict) else None
    score = float(raw_score) if raw_score is not None else 0.0

    verification_prompt = CROSS_LLM_DUAL_VERIFY.format(
        subject_id=subject_id,
        score=score,
    )
    try:
        response = secondary_adapter.generate(
            CROSS_LLM_SYSTEM,
            verification_prompt,
            temperature=settings.temperature_verification,
            max_tokens=10,
        )
        secondary_agreement = _parse_secondary_score(response)
        if secondary_agreement is None:
            return {
                **base_result,
                "models_compared": _derive_model_names(primary_adapter, secondary_adapter),
                "verification_mode": "dual_adapter_degraded",
            }

        secondary_normalized = secondary_agreement / 100.0
        combined = 0.7 * base_result["cross_llm_agreement"] + 0.3 * secondary_normalized
        return {
            **base_result,
            "cross_llm_agreement": round(combined, 4),
            "models_compared": _derive_model_names(primary_adapter, secondary_adapter),
            "secondary_agreement": secondary_agreement,
            "secondary_normalized": round(secondary_normalized, 4),
            "verification_mode": "dual_adapter",
            "passed": combined >= agreement_threshold,
        }
    except Exception as exc:
        log.warning("Dual-adapter check failed, falling back: %s", exc)
        base_result["verification_mode"] = "agreement_fallback"
        base_result["dual_adapter_error"] = str(exc)
        return base_result
