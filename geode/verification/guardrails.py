"""Guardrails G1-G4: Schema, Range, Grounding, Consistency checks."""

from __future__ import annotations

import numpy as np

from geode.state import AnalysisResult, EvaluatorResult, GeodeState, GuardrailResult


def _g1_schema(state: GeodeState) -> tuple[bool, str]:
    """G1: Validate required fields exist and have correct types."""
    required = ["analyses", "evaluations", "psm_result", "tier"]
    errors = [f"Missing {f}" for f in required if not state.get(f)]
    if state.get("final_score") is None:
        errors.append("Missing final_score")
    return not errors, "; ".join(errors) or "Schema OK"


def _validate_analyst_ranges(analyses: list) -> list[str]:
    """Check analyst score ranges [1, 5]."""
    return [
        f"Analyst {a.analyst_type} score {a.score} out of range [1,5]"
        for a in analyses
        if isinstance(a, AnalysisResult) and not (1.0 <= a.score <= 5.0)
    ]


def _validate_evaluator_ranges(evaluations: dict) -> list[str]:
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


def _g3_grounding(state: GeodeState) -> tuple[bool, str]:
    """G3: Verify analyses are grounded in evidence."""
    errors: list[str] = []
    for a in state.get("analyses", []):
        if not isinstance(a, AnalysisResult):
            continue
        if not a.evidence:
            errors.append(f"Analyst {a.analyst_type} has no evidence")
        if not a.reasoning:
            errors.append(f"Analyst {a.analyst_type} has no reasoning")
    return not errors, "; ".join(errors) or "Grounding OK"


def _g4_consistency(state: GeodeState) -> tuple[bool, str]:
    """G4: Check score-text consistency (flag outliers >2σ from mean)."""
    analyses = state.get("analyses", [])
    scores = [a.score for a in analyses if isinstance(a, AnalysisResult)]
    if len(scores) < 2:
        return True, "Consistency OK"

    mean = float(np.mean(scores))
    std = float(np.std(scores))
    errors = [
        f"Analyst {a.analyst_type} score {a.score:.1f} is >2σ from mean {mean:.1f}"
        for a in analyses
        if isinstance(a, AnalysisResult) and abs(a.score - mean) > 2 * std
    ]
    return not errors, "; ".join(errors) or "Consistency OK"


def run_guardrails(state: GeodeState) -> GuardrailResult:
    """Run all 4 guardrails in order."""
    checks = [
        ("G1(Schema)", _g1_schema),
        ("G2(Range)", _g2_range),
        ("G3(Ground)", _g3_grounding),
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
