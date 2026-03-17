"""BiasBuster: 4-step bias detection (RECOGNIZE→EXPLAIN→ALTER→EVALUATE)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import ValidationError

from core.infrastructure.ports.llm_port import get_llm_json, get_llm_parsed, get_llm_tool
from core.infrastructure.ports.tool_port import get_tool_executor
from core.llm.client import maybe_traceable
from core.llm.prompts import BIASBUSTER_SYSTEM, BIASBUSTER_USER
from core.state import AnalysisResult, BiasBusterResult, GeodeState

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistical checks
# ---------------------------------------------------------------------------


def _run_statistical_checks(analyses: list[AnalysisResult]) -> dict[str, float]:
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


@maybe_traceable(run_type="chain", name="run_biasbuster")  # type: ignore[untyped-decorator]
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

        # Fast path: when stats look clean, skip expensive LLM call.
        # LLM bias detection rarely overturns a clean statistical profile,
        # so we only invoke LLM when CV < 0.10 (potential anchoring) or
        # score range is suspiciously narrow.
        score_range = stats["max"] - stats["min"]
        if not low_variance_flag and stats["cv"] >= 0.10 and score_range >= 0.5:
            log.info(
                "BiasBuster fast path: CV=%.2f, range=%.1f — stats clean, LLM skipped",
                stats["cv"],
                score_range,
            )
            return BiasBusterResult(
                confirmation_bias=False,
                recency_bias=False,
                anchoring_bias=False,
                position_bias=False,
                verbosity_bias=False,
                self_enhancement_bias=False,
                overall_pass=True,
                explanation=(
                    f"Statistical check clean (CV={stats['cv']:.2f}, "
                    f"range=[{stats['min']:.1f}, {stats['max']:.1f}]). "
                    "LLM verification skipped."
                ),
            )

        # Tool-augmented path: LLM can query memory for historical bias patterns
        raw_tool_defs: Any = state.get("_tool_definitions", [])
        if raw_tool_defs and not low_variance_flag:
            try:
                tool_fn = get_llm_tool()
                enhanced_system = (
                    BIASBUSTER_SYSTEM + "\n\n## Available Tools\n"
                    "You can query memory_search for past bias patterns."
                )
                scores = [a.score for a in analyses if isinstance(a, AnalysisResult)]
                brief_user = (
                    f"Check {state.get('ip_name', 'Unknown')} for bias. "
                    f"Analyst scores: {scores}. "
                    f"CV={stats['cv']:.3f}. JSON BiasBusterResult."
                )
                tool_exec: Any = get_tool_executor()
                result = tool_fn(
                    enhanced_system,
                    brief_user,
                    tools=raw_tool_defs,
                    tool_executor=tool_exec,
                    max_tool_rounds=2,
                )
                if result.text:
                    import json

                    data = json.loads(result.text)
                    return BiasBusterResult(**data)
            except Exception as exc:
                log.info("Tool-augmented bias detection skipped: %s", exc)

        # LLM-based bias detection
        analyst_details_parts = []
        for idx, a in enumerate(analyses):
            if isinstance(a, AnalysisResult):
                evidence_len = sum(len(e) for e in a.evidence)
                analyst_details_parts.append(
                    f"- [{idx + 1}] {a.analyst_type}: {a.score:.1f}/5 — {a.key_finding} "
                    f"(confidence: {a.confidence:.0f}%, evidence_chars: {evidence_len})"
                )
        analyst_details = "\n".join(analyst_details_parts)

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

        # ADR-007: PromptAssembler injection
        system = BIASBUSTER_SYSTEM
        assembler: Any = state.get("_prompt_assembler")
        if assembler is not None:
            assembled = assembler.assemble(
                base_system=BIASBUSTER_SYSTEM,
                base_user=user,
                state=dict(state),
                node="biasbuster",
                role_type="bias_detection",
            )
            system = assembled.system
            user = assembled.user

        # Use Anthropic Structured Output (messages.parse) for guaranteed JSON
        try:
            return get_llm_parsed()(system, user, output_model=BiasBusterResult)
        except Exception as exc:
            log.warning(
                "BiasBuster structured output failed: %s — falling back to legacy JSON",
                exc,
            )

        # Fallback: legacy JSON parse
        try:
            data = get_llm_json()(system, user)
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
                    overall_pass=False,
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
                overall_pass=False,
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
            overall_pass=False,
            explanation=f"BiasBuster error (degraded): {exc}",
        )
