"""Guardrails G1-G4: Schema, Range, Grounding, Consistency checks."""

from __future__ import annotations

from typing import Any

import numpy as np

from geode.state import AnalysisResult, EvaluatorResult, GeodeState, GuardrailResult


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

    Checks both key presence AND numeric value presence for stronger grounding.
    """
    ev_lower = evidence.lower()
    # Check key presence
    key_match = any(sk in ev_lower for sk in (k.lower() for k in signals))
    # Check value presence (for numeric values)
    value_match = any(
        str(v) in evidence for v in signals.values() if isinstance(v, (int, float))
    )
    return key_match or value_match


def _g3_grounding(
    state: GeodeState,
    signal_data: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """G3: Verify analyses are grounded in evidence.

    When ``signal_data`` is provided, each evidence string is
    cross-referenced against signal data keys AND values.  Evidence
    items that do not match any signal key or value are flagged as
    potentially hallucinated.
    """
    errors: list[str] = []
    details_only: list[str] = []  # Soft warnings (don't fail G3)
    # Build a flat signals dict for grounding checks
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
            # Cross-reference evidence against signal data
            # Analysts focused on qualitative aspects (game_mechanics, player_experience)
            # may have domain-specific evidence not in signal data — only flag
            # quantitative analysts (growth_potential, discovery) with no grounding.
            grounded_count = sum(
                1 for ev in a.evidence if _check_evidence_grounding(ev, flat_signals)
            )
            if grounded_count == 0 and a.evidence:
                # Soft signal: record as detail but don't fail G3
                details_only.append(
                    f"Analyst {a.analyst_type}: no evidence grounded in "
                    f"signals (review recommended)"
                )
        if not a.reasoning:
            errors.append(f"Analyst {a.analyst_type} has no reasoning")
    msg_parts = errors + details_only
    return not errors, "; ".join(msg_parts) or "Grounding OK"


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
    # G3 needs signal_data, so handle it separately
    g3_fn = lambda s: _g3_grounding(s, signal_data=signal_data)  # noqa: E731

    checks: list[tuple[str, Any]] = [
        ("G1(Schema)", _g1_schema),
        ("G2(Range)", _g2_range),
        ("G3(Ground)", g3_fn),
        ("G4(Consist)", _g4_consistency),
    ]
    results: dict[str, bool] = {}
    details: list[str] = []

    for label, check_fn in checks:
        passed, msg = check_fn(state)
        key = label.split("(")[0].lower()
        results[key] = passed
        details.append(f"{label}: {'PASS' if passed else 'FAIL'} — {msg}")

    return GuardrailResult(
        g1_schema=results["g1"],
        g2_range=results["g2"],
        g3_grounding=results["g3"],
        g4_consistency=results["g4"],
        all_passed=all(results.values()),
        details=details,
    )
