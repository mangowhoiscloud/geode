"""Calibration: Ground Truth comparison for GEODE evaluation pipeline.

Compares pipeline output against expert-annotated Golden Set reference scores.
Calculates per-axis agreement, tier match, cause classification match,
and overall calibration score.

Architecture-v6 §5 Quality Evaluation — Level 1 Ground Truth.

Swiss Cheese Layer 5: orthogonal to G1-G4 (structural), BiasBuster (cognitive),
Cross-LLM (inter-model). Calibration validates against external expert consensus.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from geode.state import (
    AxisCalibration,
    CalibrationReport,
    CalibrationResult,
    EvaluatorCalibration,
    EvaluatorResult,
    GeodeState,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds and constants
# ---------------------------------------------------------------------------

# Overall calibration must exceed this to pass (stricter than Cross-LLM's 0.67
# because ground-truth comparison demands higher accuracy than inter-model agreement)
CALIBRATION_PASS_THRESHOLD = 80.0

# Tolerance band for per-axis range check (±0.5 on 1-5 scale = 10% tolerance,
# accounts for LLM non-determinism within expert-annotated reference ranges)
AXIS_TOLERANCE = 0.5

# Graduated penalty multiplier for final_score_range deviations.
# Converts distance-from-midpoint into a 0-100 deduction
# (e.g., 25-pt gap × 2 = 50-pt penalty). Chosen to make ±50 deviation yield 0%.
SCORE_RANGE_PENALTY_MULTIPLIER = 2.0

# Axis counts per evaluator (from state.py EvaluatorResult.validate_axes).
# Used for weighted scoring so quality_judge (8 axes, ~57% weight) contributes
# proportionally more than hidden_value or community_momentum (3 axes each, ~21%).
_EVALUATOR_AXIS_COUNTS: dict[str, int] = {
    "quality_judge": 8,
    "hidden_value": 3,
    "community_momentum": 3,
}

# Default golden set path
_GOLDEN_SET_PATH = Path(__file__).parent.parent / "fixtures" / "_golden_set.json"


# ---------------------------------------------------------------------------
# Golden Set loader
# ---------------------------------------------------------------------------


def load_golden_set(path: Path | None = None) -> dict[str, Any]:
    """Load golden set from JSON fixture file.

    Args:
        path: Optional path override. Uses default fixtures/_golden_set.json if None.

    Raises:
        FileNotFoundError: If golden set file does not exist.
    """
    gs_path = path or _GOLDEN_SET_PATH
    if not gs_path.exists():
        raise FileNotFoundError(f"Golden set not found: {gs_path}")
    return json.loads(gs_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------


def _calibrate_axes(
    actual_axes: dict[str, float],
    ref_axes: dict[str, list[float]],
) -> list[AxisCalibration]:
    """Compare actual axis scores against reference [low, high] ranges.

    Each axis is checked within ref range ± AXIS_TOLERANCE.
    Missing axes receive maximum penalty (deviation = ref_low).
    """
    results: list[AxisCalibration] = []
    for axis_key, ref_range in ref_axes.items():
        ref_low, ref_high = ref_range[0], ref_range[1]
        actual = actual_axes.get(axis_key)
        if actual is None:
            results.append(
                AxisCalibration(
                    axis=axis_key,
                    actual=0.0,
                    ref_low=ref_low,
                    ref_high=ref_high,
                    in_range=False,
                    deviation=ref_low,
                )
            )
            continue

        in_range = ref_low - AXIS_TOLERANCE <= actual <= ref_high + AXIS_TOLERANCE
        if actual < ref_low - AXIS_TOLERANCE:
            deviation = ref_low - AXIS_TOLERANCE - actual
        elif actual > ref_high + AXIS_TOLERANCE:
            deviation = actual - ref_high - AXIS_TOLERANCE
        else:
            deviation = 0.0

        results.append(
            AxisCalibration(
                axis=axis_key,
                actual=actual,
                ref_low=ref_low,
                ref_high=ref_high,
                in_range=in_range,
                deviation=deviation,
            )
        )
    return results


def _calibrate_evaluator(
    evaluator_type: str,
    actual_result: EvaluatorResult | None,
    ref_axes: dict[str, list[float]],
) -> EvaluatorCalibration:
    """Calibrate a single evaluator against reference ranges.

    Args:
        evaluator_type: Name of the evaluator (quality_judge, hidden_value, etc.).
        actual_result: Pipeline evaluator output. None triggers max penalty.
        ref_axes: Reference ranges per axis from Golden Set.
    """
    if actual_result is None:
        # Max penalty: 0% in-range, mean_deviation = max scale distance (4.0 on 1-5 scale)
        return EvaluatorCalibration(
            evaluator_type=evaluator_type,
            axes=[],
            axes_in_range_pct=0.0,
            mean_deviation=4.0,
        )

    axes_results = _calibrate_axes(actual_result.axes, ref_axes)
    in_range_count = sum(1 for a in axes_results if a.in_range)
    total = len(axes_results)
    pct = (in_range_count / total * 100) if total > 0 else 0.0
    deviations = [a.deviation for a in axes_results]
    mean_dev = float(np.mean(deviations)) if deviations else 0.0

    return EvaluatorCalibration(
        evaluator_type=evaluator_type,
        axes=axes_results,
        axes_in_range_pct=pct,
        mean_deviation=mean_dev,
    )


def run_calibration_check(
    state: GeodeState,
    golden_set: dict[str, Any] | None = None,
) -> CalibrationResult:
    """Run Ground Truth calibration check for a single IP.

    Follows the same API pattern as run_guardrails() and run_biasbuster().

    Scoring weights (sum=100%):
    - Tier match: 20% — coarse-grained classification accuracy
    - Cause match: 20% — D-E-F decision tree accuracy
    - Score range: 20% — final score within expert-expected band
    - Axes accuracy: 40% — most granular signal, weighted by axis count per evaluator

    Args:
        state: Pipeline state after full execution.
        golden_set: Pre-loaded golden set dict. Loaded from default path if None.

    Returns:
        CalibrationResult with per-axis, tier, cause, and overall scores.
    """
    if golden_set is None:
        golden_set = load_golden_set()

    ip_name = state.get("ip_name", "").lower().strip()
    ips = golden_set.get("ips", {})
    ref = ips.get(ip_name)

    if ref is None:
        return CalibrationResult(
            ip_name=ip_name,
            tier_match=False,
            tier_actual=state.get("tier", "?"),
            tier_expected="?",
            cause_match=False,
            cause_actual="",
            cause_expected="",
            final_score_in_range=False,
            final_score_actual=state.get("final_score", 0.0),
            final_score_range=[0.0, 0.0],
            overall_score=0.0,
            passed=False,
            details=[f"IP '{ip_name}' not found in Golden Set"],
        )

    # --- Tier match (20%) ---
    tier_actual = state.get("tier", "?")
    tier_expected = ref["tier"]
    tier_match = tier_actual == tier_expected

    # --- Cause classification match (20%) ---
    synthesis = state.get("synthesis")
    cause_actual = ""
    if synthesis is not None:
        cause_actual = getattr(synthesis, "undervaluation_cause", "")
    cause_expected = ref["cause"]
    cause_match = cause_actual == cause_expected

    # --- Final score range (20%) ---
    # Apply same tolerance band as axis checks for consistency
    score_range = ref["final_score_range"]
    final_score = state.get("final_score", 0.0)
    score_tolerance = AXIS_TOLERANCE * 20  # Scale 1-5 tolerance to 0-100 scale
    score_in_range = (
        score_range[0] - score_tolerance <= final_score <= score_range[1] + score_tolerance
    )

    # Smooth graduated penalty: distance from nearest range edge, no binary jump.
    # Scores within [low, high] get 100%; scores outside lose points linearly.
    if final_score < score_range[0]:
        range_score = max(
            0.0,
            100.0 - (score_range[0] - final_score) * SCORE_RANGE_PENALTY_MULTIPLIER,
        )
    elif final_score > score_range[1]:
        range_score = max(
            0.0,
            100.0 - (final_score - score_range[1]) * SCORE_RANGE_PENALTY_MULTIPLIER,
        )
    else:
        range_score = 100.0

    # --- Per-evaluator axis calibration (40%) ---
    evaluations = state.get("evaluations", {})
    ref_axes = ref.get("axes", {})
    evaluator_results: list[EvaluatorCalibration] = []
    details: list[str] = []

    for eval_type, eval_ref_axes in ref_axes.items():
        actual_eval = evaluations.get(eval_type)
        cal = _calibrate_evaluator(eval_type, actual_eval, eval_ref_axes)
        evaluator_results.append(cal)

        for ax in cal.axes:
            status = "OK" if ax.in_range else f"DEVIATION {ax.deviation:.2f}"
            details.append(
                f"{eval_type}.{ax.axis}: {ax.actual:.1f} "
                f"(ref [{ax.ref_low:.1f}, {ax.ref_high:.1f}]) — {status}"
            )

    # Weighted axes score: weight each evaluator by its axis count
    # quality_judge (8 axes, 57%) > hidden_value (3 axes, 21%) ≈ community_momentum (3 axes, 21%)
    if evaluator_results:
        total_weight = 0.0
        weighted_sum = 0.0
        for er in evaluator_results:
            weight = _EVALUATOR_AXIS_COUNTS.get(er.evaluator_type)
            if weight is None:
                log.warning(
                    "Unknown evaluator type '%s' in calibration — "
                    "using default weight 3 (same as hidden_value)",
                    er.evaluator_type,
                )
                weight = 3
            weighted_sum += er.axes_in_range_pct * weight
            total_weight += weight
        axes_score = weighted_sum / total_weight if total_weight > 0 else 0.0
    else:
        axes_score = 0.0

    # --- Overall calibration score ---
    tier_score = 100.0 if tier_match else 0.0
    cause_score = 100.0 if cause_match else 0.0
    overall = 0.20 * tier_score + 0.20 * cause_score + 0.20 * range_score + 0.40 * axes_score
    passed = overall >= CALIBRATION_PASS_THRESHOLD

    # Prepend summary details
    tier_status = "MATCH" if tier_match else "MISMATCH"
    cause_status = "MATCH" if cause_match else "MISMATCH"
    details.insert(0, f"Tier: {tier_actual} vs {tier_expected} — {tier_status}")
    details.insert(1, f"Cause: {cause_actual} vs {cause_expected} — {cause_status}")
    details.insert(
        2,
        f"Final Score: {final_score:.1f} (ref [{score_range[0]:.0f}, {score_range[1]:.0f}]) "
        f"— {'IN RANGE' if score_in_range else 'OUT OF RANGE'}",
    )

    return CalibrationResult(
        ip_name=ip_name,
        tier_match=tier_match,
        tier_actual=tier_actual,
        tier_expected=tier_expected,
        cause_match=cause_match,
        cause_actual=cause_actual,
        cause_expected=cause_expected,
        final_score_in_range=score_in_range,
        final_score_actual=final_score,
        final_score_range=[score_range[0], score_range[1]],
        evaluator_results=evaluator_results,
        overall_score=overall,
        passed=passed,
        details=details,
    )


def run_calibration(
    states: list[GeodeState],
    golden_set_path: Path | None = None,
) -> CalibrationReport:
    """Run calibration across multiple IP pipeline outputs.

    Batch wrapper around run_calibration_check() for regression testing.

    Args:
        states: List of pipeline states (one per IP).
        golden_set_path: Optional path to golden set JSON.

    Returns:
        CalibrationReport with per-IP results and aggregate score.
    """
    golden_set = load_golden_set(golden_set_path)
    results: list[CalibrationResult] = []

    for state in states:
        result = run_calibration_check(state, golden_set=golden_set)
        results.append(result)
        log.info(
            "Calibration [%s]: %.1f/100 (tier=%s, cause=%s, score=%s)",
            result.ip_name,
            result.overall_score,
            "MATCH" if result.tier_match else "MISS",
            "MATCH" if result.cause_match else "MISS",
            "IN" if result.final_score_in_range else "OUT",
        )

    overall = float(np.mean([r.overall_score for r in results])) if results else 0.0

    passed = overall >= CALIBRATION_PASS_THRESHOLD

    n_tier = sum(1 for r in results if r.tier_match)
    n_cause = sum(1 for r in results if r.cause_match)
    n_score = sum(1 for r in results if r.final_score_in_range)
    total = len(results)
    summary = (
        f"Calibration: {overall:.1f}/100 ({'PASS' if passed else 'FAIL'}) | "
        f"Tier: {n_tier}/{total} | Cause: {n_cause}/{total} | "
        f"Score Range: {n_score}/{total}"
    )

    return CalibrationReport(
        results=results,
        overall_score=overall,
        passed=passed,
        summary=summary,
    )
