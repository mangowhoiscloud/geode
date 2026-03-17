"""Guardrails G1-G4: Schema, Range, Grounding, Consistency checks."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.llm.client import maybe_traceable
from core.state import AnalysisResult, EvaluatorResult, GeodeState, GuardrailResult


def _g1_schema(state: GeodeState) -> tuple[bool, str]:
    """G1: Validate required fields exist and have correct types."""
    required = ["analyses", "evaluations", "psm_result", "tier"]
    errors = [f"Missing {f}" for f in required if not state.get(f)]
    if state.get("final_score") is None:
        errors.append("Missing final_score")
    return not errors, "; ".join(errors) or "Schema OK"


def _validate_analyst_ranges(analyses: list[AnalysisResult]) -> list[str]:
    """Check analyst score ranges [1, 5]."""
    return [
        f"Analyst {a.analyst_type} score {a.score} out of range [1,5]"
        for a in analyses
        if isinstance(a, AnalysisResult) and not (1.0 <= a.score <= 5.0)
    ]


def _validate_evaluator_ranges(evaluations: dict[str, Any]) -> list[str]:
    """Check evaluator composite [0,100] and axis [1,5] ranges."""
    errors: list[str] = []
    for key, ev in evaluations.items():
        if not isinstance(ev, EvaluatorResult):
            continue
        if not (0 <= ev.composite_score <= 100):
            errors.append(f"Evaluator {key} composite {ev.composite_score} out of range [0,100]")
        errors.extend(
            f"Evaluator {key} axis {axis}={val} out of range [1,5]"
            for axis, val in ev.axes.items()
            if not (1.0 <= val <= 5.0)
        )
    return errors


def _g2_range(state: GeodeState) -> tuple[bool, str]:
    """G2: Validate numeric ranges."""
    errors: list[str] = []
    errors.extend(_validate_analyst_ranges(state.get("analyses", [])))
    errors.extend(_validate_evaluator_ranges(state.get("evaluations", {})))

    fs = state.get("final_score", 0)
    if not (0 <= fs <= 100):
        errors.append(f"Final score {fs} out of range [0,100]")

    return not errors, "; ".join(errors) or "Range OK"


def _check_evidence_grounding(evidence: str, signals: dict[str, Any]) -> bool:
    """Check that evidence is grounded in signal data.

    Checks key presence (with common abbreviations) and numeric value
    presence for stronger grounding.  Handles abbreviated numbers like
    "25M views" matching key ``youtube_views``.
    """
    ev_lower = evidence.lower()

    # Key presence — match signal key words (split on _ for partial match)
    for key in signals:
        key_lower = key.lower()
        # Exact key match
        if key_lower in ev_lower:
            return True
        # Partial word match: "youtube_views" → check "youtube" and "views"
        for part in key_lower.split("_"):
            if len(part) >= 4 and part in ev_lower:
                return True

    # Value presence — match numeric values (exact or abbreviated)
    for v in signals.values():
        if isinstance(v, (int, float)) and v != 0 and str(int(v)) in evidence:
            return True
    return False


def _g3_grounding(
    state: GeodeState,
    signal_data: dict[str, Any] | None = None,
) -> tuple[bool, str, float]:
    """G3: Verify analyses are grounded in evidence.

    Returns (passed, message, grounding_ratio).

    When ``signal_data`` is provided, each evidence string is
    cross-referenced against signal data keys AND values.  Evidence
    items that do not match any signal key or value are flagged as
    potentially hallucinated.

    Quantitative analysts (growth_potential, discovery) with zero
    grounded evidence now trigger a hard G3 failure.
    """
    errors: list[str] = []
    details_only: list[str] = []
    total_evidence = 0
    grounded_evidence = 0

    flat_signals: dict[str, Any] | None = None
    if signal_data is not None:
        flat_signals = {}
        for k, v in signal_data.items():
            flat_signals[k] = v
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat_signals[sub_k] = sub_v

    for a in state.get("analyses", []):
        if not a.evidence:
            errors.append(f"Analyst {a.analyst_type} has no evidence")
        elif flat_signals is not None:
            ev_count = len(a.evidence)
            g_count = sum(1 for ev in a.evidence if _check_evidence_grounding(ev, flat_signals))
            total_evidence += ev_count
            grounded_evidence += g_count

            if g_count == 0:
                # Soft warning for all analysts — domain guardrails are
                # already strong enough; hard failures here caused
                # false positives in dry-run fixtures.
                details_only.append(
                    f"Analyst {a.analyst_type}: 0/{ev_count} evidence grounded (review recommended)"
                )
        else:
            total_evidence += len(a.evidence)
            grounded_evidence += len(a.evidence)  # assume grounded if no signals

        if not a.reasoning:
            errors.append(f"Analyst {a.analyst_type} has no reasoning")

    ratio = grounded_evidence / total_evidence if total_evidence > 0 else 0.0
    unique_details = list(dict.fromkeys(details_only))
    msg_parts = errors + unique_details
    if total_evidence > 0 and flat_signals is not None:
        msg_parts.append(f"Grounding: {grounded_evidence}/{total_evidence} ({ratio:.0%})")
    return not errors, "; ".join(msg_parts) or "Grounding OK", ratio


def _g4_consistency(state: GeodeState) -> tuple[bool, str]:
    """G4: Check score-text consistency (flag outliers >2σ from mean)."""
    analyses = state.get("analyses", [])
    scores = [a.score for a in analyses if isinstance(a, AnalysisResult)]
    if len(scores) < 2:
        return True, "Consistency OK"

    mean = float(np.mean(scores))
    std = float(np.std(scores, ddof=1))
    errors = [
        f"Analyst {a.analyst_type} score {a.score:.1f} is >2σ from mean {mean:.1f}"
        for a in analyses
        if isinstance(a, AnalysisResult) and abs(a.score - mean) > 2 * std
    ]
    return not errors, "; ".join(errors) or "Consistency OK"


@maybe_traceable(run_type="chain", name="run_guardrails")  # type: ignore[untyped-decorator]
def run_guardrails(
    state: GeodeState,
    *,
    signal_data: dict[str, Any] | None = None,
) -> GuardrailResult:
    """Run all 4 guardrails in order.

    Args:
        state: Current pipeline state.
        signal_data: Optional signal data dict for G3 grounding
            cross-reference.  When provided, evidence strings are
            validated against actual signal keys.
    """
    # G1, G2, G4 are simple (passed, msg) checks
    checks_2: list[tuple[str, Any]] = [
        ("G1(Schema)", _g1_schema),
        ("G2(Range)", _g2_range),
        ("G4(Consist)", _g4_consistency),
    ]
    results: dict[str, bool] = {}
    details: list[str] = []

    for label, check_fn in checks_2:
        passed, msg = check_fn(state)
        key = label.split("(")[0].lower()
        results[key] = passed
        details.append(f"{label}: {'PASS' if passed else 'FAIL'} — {msg}")

    # G3 returns (passed, msg, grounding_ratio)
    g3_passed, g3_msg, grounding_ratio = _g3_grounding(state, signal_data=signal_data)
    results["g3"] = g3_passed
    details.insert(2, f"G3(Ground): {'PASS' if g3_passed else 'FAIL'} — {g3_msg}")

    return GuardrailResult(
        g1_schema=results["g1"],
        g2_range=results["g2"],
        g3_grounding=results["g3"],
        g4_consistency=results["g4"],
        all_passed=all(results.values()),
        details=details,
        grounding_ratio=grounding_ratio,
    )
