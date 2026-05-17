"""Generic guardrails G1-G4: schema, range, grounding, consistency checks."""

from __future__ import annotations

from typing import Any

import numpy as np

from core.state import GeodeState, GuardrailResult


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _item_field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _g1_schema(state: GeodeState) -> tuple[bool, str]:
    """G1: core state must contain at least a subject or result payload."""
    if state.get("subject_id") or state.get("result") or state.get("analyses"):
        return True, "Schema OK"
    return False, "Missing subject_id, result, or analyses"


def _validate_analysis_ranges(analyses: list[Any]) -> list[str]:
    """Check optional analysis score ranges when callers provide scores."""
    errors: list[str] = []
    for index, analysis in enumerate(analyses):
        score = _as_float(_item_field(analysis, "score"))
        if score is not None and not (0.0 <= score <= 100.0):
            name = _item_field(analysis, "name", _item_field(analysis, "analyst_type", index))
            errors.append(f"Analysis {name} score {score} out of range [0,100]")
        confidence = _as_float(_item_field(analysis, "confidence"))
        if confidence is not None and not (0.0 <= confidence <= 100.0):
            name = _item_field(analysis, "name", _item_field(analysis, "analyst_type", index))
            errors.append(f"Analysis {name} confidence {confidence} out of range [0,100]")
    return errors


def _validate_evaluation_ranges(evaluations: dict[str, Any]) -> list[str]:
    """Check optional evaluation score and axis ranges."""
    errors: list[str] = []
    for key, evaluation in evaluations.items():
        composite = _as_float(_item_field(evaluation, "composite_score"))
        if composite is not None and not (0.0 <= composite <= 100.0):
            errors.append(f"Evaluation {key} composite {composite} out of range [0,100]")
        axes = _item_field(evaluation, "axes", {})
        if isinstance(axes, dict):
            for axis, value in axes.items():
                axis_score = _as_float(value)
                if axis_score is not None and not (0.0 <= axis_score <= 100.0):
                    errors.append(f"Evaluation {key} axis {axis}={axis_score} out of range [0,100]")
    return errors


def _g2_range(state: GeodeState) -> tuple[bool, str]:
    """G2: validate common numeric ranges without assuming a domain schema."""
    errors: list[str] = []
    errors.extend(_validate_analysis_ranges(list(state.get("analyses", []))))
    errors.extend(_validate_evaluation_ranges(dict(state.get("evaluations", {}))))

    result = state.get("result", {})
    if isinstance(result, dict):
        for key in ("score", "final_score", "confidence"):
            value = _as_float(result.get(key))
            if value is not None and not (0.0 <= value <= 100.0):
                errors.append(f"Result {key} {value} out of range [0,100]")

    return not errors, "; ".join(errors) or "Range OK"


def _check_evidence_grounding(evidence: str, signals: dict[str, Any]) -> bool:
    """Check that evidence references provided signal keys or numeric values."""
    evidence_lower = evidence.lower()
    for key in signals:
        key_lower = key.lower()
        if key_lower in evidence_lower:
            return True
        for part in key_lower.split("_"):
            if len(part) >= 4 and part in evidence_lower:
                return True
    for value in signals.values():
        if isinstance(value, int | float) and value != 0 and str(int(value)) in evidence:
            return True
    return False


def _flatten_signals(signal_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if signal_data is None:
        return None
    flat: dict[str, Any] = {}
    for key, value in signal_data.items():
        flat[key] = value
        if isinstance(value, dict):
            flat.update(value)
    return flat


def _g3_grounding(
    state: GeodeState,
    signal_data: dict[str, Any] | None = None,
) -> tuple[bool, str, float]:
    """G3: verify optional evidence strings against optional signals."""
    errors: list[str] = []
    details: list[str] = []
    total_evidence = 0
    grounded_evidence = 0
    flat_signals = _flatten_signals(signal_data)

    for index, analysis in enumerate(state.get("analyses", [])):
        evidence = _item_field(analysis, "evidence", [])
        reasoning = _item_field(analysis, "reasoning", "")
        name = _item_field(analysis, "name", _item_field(analysis, "analyst_type", index))
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            evidence = []

        if not evidence:
            details.append(f"Analysis {name} has no evidence")
        elif flat_signals is None:
            total_evidence += len(evidence)
            grounded_evidence += len(evidence)
        else:
            total_evidence += len(evidence)
            grounded = sum(
                1 for item in evidence if _check_evidence_grounding(str(item), flat_signals)
            )
            grounded_evidence += grounded
            if grounded == 0:
                details.append(f"Analysis {name}: 0/{len(evidence)} evidence grounded")

        if evidence and not reasoning:
            errors.append(f"Analysis {name} has evidence but no reasoning")

    ratio = grounded_evidence / total_evidence if total_evidence else 0.0
    if total_evidence and flat_signals is not None:
        details.append(f"Grounding: {grounded_evidence}/{total_evidence} ({ratio:.0%})")
    messages = errors + list(dict.fromkeys(details))
    return not errors, "; ".join(messages) or "Grounding OK", ratio


def _g4_consistency(state: GeodeState) -> tuple[bool, str]:
    """G4: flag score outliers when multiple analyses provide scores."""
    scores: list[tuple[str, float]] = []
    for index, analysis in enumerate(state.get("analyses", [])):
        score = _as_float(_item_field(analysis, "score"))
        if score is not None:
            name = str(_item_field(analysis, "name", _item_field(analysis, "analyst_type", index)))
            scores.append((name, score))
    if len(scores) < 2:
        return True, "Consistency OK"

    values = [score for _, score in scores]
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std == 0:
        return True, "Consistency OK"
    errors = [
        f"Analysis {name} score {score:.1f} is >2σ from mean {mean:.1f}"
        for name, score in scores
        if abs(score - mean) > 2 * std
    ]
    return not errors, "; ".join(errors) or "Consistency OK"


def run_guardrails(
    state: GeodeState,
    *,
    signal_data: dict[str, Any] | None = None,
) -> GuardrailResult:
    """Run generic G1-G4 checks without depending on a domain schema."""
    results: dict[str, bool] = {}
    details: list[str] = []

    for label, check_fn in (
        ("G1(Schema)", _g1_schema),
        ("G2(Range)", _g2_range),
        ("G4(Consist)", _g4_consistency),
    ):
        passed, message = check_fn(state)
        key = label.split("(")[0].lower()
        results[key] = passed
        details.append(f"{label}: {'PASS' if passed else 'FAIL'} - {message}")

    g3_passed, g3_message, grounding_ratio = _g3_grounding(state, signal_data=signal_data)
    results["g3"] = g3_passed
    details.insert(2, f"G3(Ground): {'PASS' if g3_passed else 'FAIL'} - {g3_message}")

    return GuardrailResult(
        g1_schema=results["g1"],
        g2_range=results["g2"],
        g3_grounding=results["g3"],
        g4_consistency=results["g4"],
        all_passed=all(results.values()),
        details=details,
        grounding_ratio=grounding_ratio,
    )
