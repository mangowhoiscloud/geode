"""BiasBuster: 4-step bias detection (RECOGNIZE→EXPLAIN→ALTER→EVALUATE)."""

from __future__ import annotations

import numpy as np

from geode.llm.client import call_llm_json
from geode.llm.prompts import BIASBUSTER_SYSTEM, BIASBUSTER_USER
from geode.state import AnalysisResult, BiasBusterResult, GeodeState
from geode.ui.console import console


def _run_statistical_checks(analyses: list[AnalysisResult]) -> dict:
    """Quick statistical checks for anchoring bias signals."""
    scores = [a.score for a in analyses if isinstance(a, AnalysisResult)]
    if len(scores) < 2:
        return {"mean": 0, "std": 0, "cv": 0, "min": 0, "max": 0}

    mean = float(np.mean(scores))
    std = float(np.std(scores))
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
    analyses = state.get("analyses", [])
    stats = _run_statistical_checks(analyses)

    # Quick heuristic: if CV is very low (<0.05), possible anchoring
    low_variance_flag = stats["cv"] < 0.05 and len(analyses) >= 4

    if state.get("dry_run"):
        return BiasBusterResult(
            confirmation_bias=False,
            recency_bias=False,
            anchoring_bias=low_variance_flag,
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
    data_points = "\n".join(f"- {k}: {v}" for k, v in signals.items() if not k.startswith("_"))

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
        data = call_llm_json(BIASBUSTER_SYSTEM, user)
        return BiasBusterResult(**data)
    except Exception as e:
        console.print(f"    [warning]BiasBuster LLM call failed: {e}[/warning]")
        return BiasBusterResult(
            confirmation_bias=False,
            recency_bias=False,
            anchoring_bias=low_variance_flag,
            overall_pass=not low_variance_flag,
            explanation=f"Statistical check only (LLM unavailable). CV={stats['cv']:.2f}",
        )
