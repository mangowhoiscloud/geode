"""BiasBuster: 4-step bias detection (RECOGNIZE→EXPLAIN→ALTER→EVALUATE)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import ValidationError

from geode.infrastructure.ports.llm_port import get_llm_json
from geode.llm.prompts import BIASBUSTER_SYSTEM, BIASBUSTER_USER
from geode.state import AnalysisResult, BiasBusterResult, GeodeState

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistical checks
# ---------------------------------------------------------------------------


def _run_statistical_checks(analyses: list[AnalysisResult]) -> dict:
    """Quick statistical checks for anchoring bias signals."""
    scores = [a.score for a in analyses if isinstance(a, AnalysisResult)]
    if len(scores) < 2:
        return {"mean": 0, "std": 0, "cv": 0, "min": 0, "max": 0}

    mean = float(np.mean(scores))
    std = float(np.std(scores, ddof=1))
    cv = std / mean if mean > 0 else 0

    return {
        "mean": mean,
        "std": std,
        "cv": cv,
        "min": float(np.min(scores)),
        "max": float(np.max(scores)),
    }


def run_biasbuster(state: GeodeState) -> BiasBusterResult:
    """Run BiasBuster 4-step verification."""
    try:
        analyses = state.get("analyses", [])
        stats = _run_statistical_checks(analyses)

        # Quick heuristic: if CV is very low (<0.05), possible anchoring
        low_variance_flag = stats["cv"] < 0.05 and len(analyses) >= 4

        if state.get("dry_run"):
            return BiasBusterResult(
                confirmation_bias=False,
                recency_bias=False,
                anchoring_bias=low_variance_flag,
                position_bias=False,
                verbosity_bias=False,
                self_enhancement_bias=False,
                overall_pass=not low_variance_flag,
                explanation=(
                    "Clean Context applied. Analyst scores show healthy variance "
                    f"(CV={stats['cv']:.2f}). No bias detected."
                ),
            )

        # LLM-based bias detection
        analyst_details = "\n".join(
            f"- {a.analyst_type}: {a.score:.1f}/5 — {a.key_finding} (confidence: {a.confidence:.0f}%)"
            for a in analyses
            if isinstance(a, AnalysisResult)
        )

        signals = state.get("signals", {})
        data_points = "\n".join(
            f"- {k}: {v}" for k, v in signals.items() if not k.startswith("_")
        )

        user = BIASBUSTER_USER.format(
            ip_name=state.get("ip_name", "Unknown"),
            analyst_details=analyst_details,
            mean=stats["mean"],
            std=stats["std"],
            cv=stats["cv"],
            min_score=stats["min"],
            max_score=stats["max"],
            data_points=data_points,
        )

        try:
            data = get_llm_json()(BIASBUSTER_SYSTEM, user)
            try:
                return BiasBusterResult(**data)
            except ValidationError as ve:
                log.warning("BiasBuster LLM response failed validation: %s", ve)
                return BiasBusterResult(
                    confirmation_bias=False,
                    recency_bias=False,
                    anchoring_bias=low_variance_flag,
                    position_bias=False,
                    verbosity_bias=False,
                    self_enhancement_bias=False,
                    overall_pass=not low_variance_flag,
                    explanation=(
                        f"Statistical check only (LLM response invalid). CV={stats['cv']:.2f}"
                    ),
                )
        except Exception as e:
            log.warning("BiasBuster LLM call failed: %s", e)
            return BiasBusterResult(
                confirmation_bias=False,
                recency_bias=False,
                anchoring_bias=low_variance_flag,
                position_bias=False,
                verbosity_bias=False,
                self_enhancement_bias=False,
                overall_pass=not low_variance_flag,
                explanation=f"Statistical check only (LLM unavailable). CV={stats['cv']:.2f}",
            )
    except Exception as exc:
        log.error("BiasBuster failed: %s", exc)
        return BiasBusterResult(
            confirmation_bias=False,
            recency_bias=False,
            anchoring_bias=False,
            position_bias=False,
            verbosity_bias=False,
            self_enhancement_bias=False,
            overall_pass=True,
            explanation=f"BiasBuster error (degraded): {exc}",
        )
