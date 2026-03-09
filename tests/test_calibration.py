"""Tests for geode.verification.calibration — Ground Truth comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from geode.state import (
    AnalysisResult,
    AxisCalibration,
    CalibrationReport,
    CalibrationResult,
    EvaluatorCalibration,
    EvaluatorResult,
    SynthesisResult,
)
from geode.verification.calibration import (
    AXIS_TOLERANCE,
    CALIBRATION_PASS_THRESHOLD,
    SCORE_RANGE_PENALTY_MULTIPLIER,
    _calibrate_axes,
    _calibrate_evaluator,
    load_golden_set,
    run_calibration,
    run_calibration_check,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOLDEN_SET_PATH = Path(__file__).parent.parent / "geode" / "fixtures" / "_golden_set.json"


@pytest.fixture
def golden_set() -> dict:
    return load_golden_set(GOLDEN_SET_PATH)


@pytest.fixture
def berserk_state() -> dict:
    """Berserk dry-run pipeline state (should match golden set)."""
    return {
        "ip_name": "Berserk",
        "tier": "S",
        "final_score": 82.2,
        "evaluations": {
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={
                    "a_score": 4.5,
                    "b_score": 4.2,
                    "c_score": 4.4,
                    "b1_score": 3.8,
                    "c1_score": 3.8,
                    "c2_score": 3.6,
                    "m_score": 3.8,
                    "n_score": 4.0,
                },
                composite_score=75.31,
                rationale="Strong dark fantasy IP.",
            ),
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 4.5, "f_score": 4.5},
                composite_score=87.50,
                rationale="Massive conversion gap.",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 4.8, "k_score": 4.6, "l_score": 4.5},
                composite_score=90.83,
                rationale="Exceptionally strong community.",
            ),
        },
        "synthesis": SynthesisResult(
            undervaluation_cause="conversion_failure",
            action_type="marketing_boost",
            value_narrative="Berserk needs AAA game adaptation.",
            target_gamer_segment="Souls-like fans",
        ),
        "analyses": [
            AnalysisResult(
                analyst_type="game_mechanics",
                score=4.2,
                key_finding="Souls-like potential",
                reasoning="...",
            ),
        ],
    }


@pytest.fixture
def cowboy_bebop_state() -> dict:
    """Cowboy Bebop dry-run pipeline state."""
    return {
        "ip_name": "Cowboy Bebop",
        "tier": "A",
        "final_score": 69.4,
        "evaluations": {
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={
                    "a_score": 4.2,
                    "b_score": 4.0,
                    "c_score": 4.3,
                    "b1_score": 3.9,
                    "c1_score": 4.1,
                    "c2_score": 4.0,
                    "m_score": 3.8,
                    "n_score": 4.2,
                },
                composite_score=76.56,
                rationale="Strong adaptation potential.",
            ),
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 5.0, "e_score": 2.0, "f_score": 4.0},
                composite_score=50.0,
                rationale="Extreme acquisition gap.",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 4.3, "k_score": 4.1, "l_score": 3.9},
                composite_score=77.50,
                rationale="Active organic community.",
            ),
        },
        "synthesis": SynthesisResult(
            undervaluation_cause="undermarketed",
            action_type="marketing_boost",
            value_narrative="Cowboy Bebop needs marketing push.",
            target_gamer_segment="Sci-fi RPG fans",
        ),
        "analyses": [],
    }


@pytest.fixture
def ghost_state() -> dict:
    """Ghost in the Shell dry-run pipeline state."""
    return {
        "ip_name": "Ghost in the Shell",
        "tier": "B",
        "final_score": 54.0,
        "evaluations": {
            "quality_judge": EvaluatorResult(
                evaluator_type="quality_judge",
                axes={
                    "a_score": 3.8,
                    "b_score": 3.5,
                    "c_score": 3.6,
                    "b1_score": 3.3,
                    "c1_score": 3.4,
                    "c2_score": 3.2,
                    "m_score": 3.4,
                    "n_score": 3.5,
                },
                composite_score=61.56,
                rationale="Good IP-game fit for stealth.",
            ),
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 2.0, "e_score": 2.0, "f_score": 2.0},
                composite_score=25.0,
                rationale="No dominant undervaluation axis.",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 3.5, "k_score": 3.3, "l_score": 3.0},
                composite_score=56.67,
                rationale="Moderate community presence.",
            ),
        },
        "synthesis": SynthesisResult(
            undervaluation_cause="discovery_failure",
            action_type="platform_expansion",
            value_narrative="Ghost in the Shell needs discovery.",
            target_gamer_segment="Cyberpunk fans",
        ),
        "analyses": [],
    }


# ---------------------------------------------------------------------------
# Golden Set loading
# ---------------------------------------------------------------------------


class TestLoadGoldenSet:
    def test_load_success(self, golden_set: dict) -> None:
        assert "ips" in golden_set
        assert "version" in golden_set
        assert len(golden_set["ips"]) == 6

    def test_load_has_all_fixture_ips(self, golden_set: dict) -> None:
        ips = golden_set["ips"]
        assert "berserk" in ips
        assert "cowboy bebop" in ips
        assert "ghost in the shell" in ips

    def test_load_has_synthetic_ips(self, golden_set: dict) -> None:
        """Synthetic IPs cover missing D-E-F branches."""
        ips = golden_set["ips"]
        assert "dragon quest" in ips  # monetization_misfit
        assert "katamari damacy" in ips  # niche_gem

    def test_load_ip_structure(self, golden_set: dict) -> None:
        berserk = golden_set["ips"]["berserk"]
        assert berserk["tier"] == "S"
        assert berserk["cause"] == "conversion_failure"
        assert len(berserk["final_score_range"]) == 2
        assert "axes" in berserk
        assert "subscores" in berserk
        assert "quality_judge" in berserk["axes"]
        assert "hidden_value" in berserk["axes"]
        assert "community_momentum" in berserk["axes"]

    def test_load_axes_are_ranges(self, golden_set: dict) -> None:
        """Each axis reference is a [low, high] pair."""
        axes = golden_set["ips"]["berserk"]["axes"]["quality_judge"]
        for key, val in axes.items():
            assert isinstance(val, list), f"{key} should be a list"
            assert len(val) == 2, f"{key} should have [low, high]"
            assert val[0] <= val[1], f"{key}: low > high"

    def test_load_subscores_are_ranges(self, golden_set: dict) -> None:
        """Subscore references are [low, high] pairs."""
        subscores = golden_set["ips"]["berserk"]["subscores"]
        for key, val in subscores.items():
            assert isinstance(val, list), f"{key} should be a list"
            assert len(val) == 2, f"{key} should have [low, high]"

    def test_decision_tree_coverage(self, golden_set: dict) -> None:
        """Golden set covers all 6 D-E-F branches."""
        causes = {ip["cause"] for ip in golden_set["ips"].values()}
        assert "conversion_failure" in causes
        assert "undermarketed" in causes
        assert "discovery_failure" in causes
        assert "monetization_misfit" in causes
        assert "niche_gem" in causes
        assert "timing_mismatch" in causes

    def test_load_has_timing_mismatch_ip(self, golden_set: dict) -> None:
        """Shenmue covers the timing_mismatch branch."""
        ips = golden_set["ips"]
        assert "shenmue" in ips
        assert ips["shenmue"]["cause"] == "timing_mismatch"
        assert ips["shenmue"]["action"] == "timing_optimization"

    def test_load_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_golden_set(Path("/nonexistent/golden_set.json"))


# ---------------------------------------------------------------------------
# Axis calibration
# ---------------------------------------------------------------------------


class TestCalibrateAxes:
    def test_all_in_range(self) -> None:
        actual = {"a_score": 4.5, "b_score": 4.0}
        ref = {"a_score": [4.0, 5.0], "b_score": [3.5, 4.5]}
        results = _calibrate_axes(actual, ref)
        assert len(results) == 2
        assert all(r.in_range for r in results)
        assert all(r.deviation == 0.0 for r in results)

    def test_out_of_range_low(self) -> None:
        actual = {"a_score": 2.0}
        ref = {"a_score": [4.0, 5.0]}
        results = _calibrate_axes(actual, ref)
        assert not results[0].in_range
        assert results[0].deviation > 0

    def test_out_of_range_high(self) -> None:
        actual = {"a_score": 5.0}
        ref = {"a_score": [1.0, 2.0]}
        results = _calibrate_axes(actual, ref)
        assert not results[0].in_range
        assert results[0].deviation > 0

    def test_within_tolerance(self) -> None:
        """Score just outside range but within AXIS_TOLERANCE should pass."""
        actual = {"a_score": 3.6}
        ref = {"a_score": [4.0, 5.0]}
        results = _calibrate_axes(actual, ref)
        # 3.6 >= 4.0 - 0.5 = 3.5 → in range (with tolerance)
        assert results[0].in_range

    def test_missing_axis(self) -> None:
        actual: dict[str, float] = {}
        ref = {"a_score": [4.0, 5.0]}
        results = _calibrate_axes(actual, ref)
        assert not results[0].in_range
        assert results[0].actual == 0.0

    def test_returns_pydantic_models(self) -> None:
        """AxisCalibration is a Pydantic BaseModel, not a dataclass."""
        actual = {"a_score": 4.5}
        ref = {"a_score": [4.0, 5.0]}
        results = _calibrate_axes(actual, ref)
        assert isinstance(results[0], AxisCalibration)
        # Pydantic model has model_dump
        dumped = results[0].model_dump()
        assert "axis" in dumped
        assert "deviation" in dumped


# ---------------------------------------------------------------------------
# Evaluator calibration
# ---------------------------------------------------------------------------


class TestCalibrateEvaluator:
    def test_perfect_match(self) -> None:
        result = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.0, "e_score": 4.5, "f_score": 4.5},
            composite_score=87.5,
            rationale="...",
        )
        ref = {"d_score": [3.5, 4.5], "e_score": [4.0, 5.0], "f_score": [4.0, 5.0]}
        cal = _calibrate_evaluator("hidden_value", result, ref)
        assert cal.axes_in_range_pct == 100.0
        assert cal.mean_deviation == 0.0

    def test_none_evaluator(self) -> None:
        ref = {"d_score": [3.5, 4.5]}
        cal = _calibrate_evaluator("hidden_value", None, ref)
        assert cal.axes_in_range_pct == 0.0
        assert cal.mean_deviation == 4.0  # Max scale distance on 1-5

    def test_partial_match(self) -> None:
        result = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.0, "e_score": 1.0, "f_score": 4.5},
            composite_score=50.0,
            rationale="...",
        )
        ref = {"d_score": [3.5, 4.5], "e_score": [4.0, 5.0], "f_score": [4.0, 5.0]}
        cal = _calibrate_evaluator("hidden_value", result, ref)
        assert cal.axes_in_range_pct == pytest.approx(66.67, abs=0.1)
        assert cal.mean_deviation > 0

    def test_returns_pydantic_model(self) -> None:
        """EvaluatorCalibration is a Pydantic BaseModel."""
        result = EvaluatorResult(
            evaluator_type="hidden_value",
            axes={"d_score": 4.0, "e_score": 4.5, "f_score": 4.5},
            composite_score=87.5,
            rationale="...",
        )
        ref = {"d_score": [3.5, 4.5], "e_score": [4.0, 5.0], "f_score": [4.0, 5.0]}
        cal = _calibrate_evaluator("hidden_value", result, ref)
        assert isinstance(cal, EvaluatorCalibration)
        dumped = cal.model_dump()
        assert "evaluator_type" in dumped
        assert "axes" in dumped


# ---------------------------------------------------------------------------
# Single IP calibration
# ---------------------------------------------------------------------------


class TestRunCalibrationCheck:
    def test_berserk_calibration(self, berserk_state: dict, golden_set: dict) -> None:
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert result.ip_name == "berserk"
        assert result.tier_match is True
        assert result.cause_match is True
        assert result.final_score_in_range is True
        assert result.overall_score >= 80.0
        assert result.passed is True
        assert len(result.evaluator_results) == 3

    def test_cowboy_bebop_calibration(self, cowboy_bebop_state: dict, golden_set: dict) -> None:
        result = run_calibration_check(cowboy_bebop_state, golden_set=golden_set)
        assert result.ip_name == "cowboy bebop"
        assert result.tier_match is True
        assert result.cause_match is True
        assert result.final_score_in_range is True

    def test_ghost_calibration(self, ghost_state: dict, golden_set: dict) -> None:
        result = run_calibration_check(ghost_state, golden_set=golden_set)
        assert result.ip_name == "ghost in the shell"
        assert result.tier_match is True
        assert result.cause_match is True
        assert result.final_score_in_range is True

    def test_unknown_ip(self, golden_set: dict) -> None:
        state: dict = {"ip_name": "Unknown IP", "tier": "C", "final_score": 30.0}
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.overall_score == 0.0
        assert result.passed is False
        assert "not found" in result.details[0]

    def test_tier_mismatch(self, berserk_state: dict, golden_set: dict) -> None:
        berserk_state["tier"] = "C"
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert result.tier_match is False
        assert result.overall_score < 100.0

    def test_cause_mismatch(self, berserk_state: dict, golden_set: dict) -> None:
        berserk_state["synthesis"] = SynthesisResult(
            undervaluation_cause="discovery_failure",
            action_type="platform_expansion",
            value_narrative="Wrong cause.",
            target_gamer_segment="...",
        )
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert result.cause_match is False

    def test_score_out_of_range(self, berserk_state: dict, golden_set: dict) -> None:
        berserk_state["final_score"] = 30.0
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert result.final_score_in_range is False

    def test_no_synthesis_state(self, golden_set: dict) -> None:
        """State without synthesis should handle cause gracefully."""
        state: dict = {
            "ip_name": "Berserk",
            "tier": "S",
            "final_score": 82.0,
            "evaluations": {},
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.cause_actual == ""
        assert result.cause_match is False

    def test_details_populated(self, berserk_state: dict, golden_set: dict) -> None:
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert len(result.details) > 0
        assert any("Tier:" in d for d in result.details)
        assert any("Cause:" in d for d in result.details)
        assert any("Final Score:" in d for d in result.details)

    def test_result_is_pydantic(self, berserk_state: dict, golden_set: dict) -> None:
        """CalibrationResult is a Pydantic BaseModel with model_dump."""
        result = run_calibration_check(berserk_state, golden_set=golden_set)
        assert isinstance(result, CalibrationResult)
        dumped = result.model_dump()
        assert "tier_match" in dumped
        assert "final_score_range" in dumped
        assert isinstance(dumped["final_score_range"], list)

    def test_failing_calibration(self, golden_set: dict) -> None:
        """Deliberately miscalibrated state should produce passed=False."""
        state: dict = {
            "ip_name": "Berserk",
            "tier": "C",
            "final_score": 20.0,
            "evaluations": {
                "quality_judge": EvaluatorResult(
                    evaluator_type="quality_judge",
                    axes={
                        "a_score": 1.0,
                        "b_score": 1.0,
                        "c_score": 1.0,
                        "b1_score": 1.0,
                        "c1_score": 1.0,
                        "c2_score": 1.0,
                        "m_score": 1.0,
                        "n_score": 1.0,
                    },
                    composite_score=0.0,
                    rationale="...",
                ),
            },
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.passed is False
        assert result.overall_score < CALIBRATION_PASS_THRESHOLD


# ---------------------------------------------------------------------------
# Multi-IP calibration report
# ---------------------------------------------------------------------------


class TestRunCalibration:
    def test_all_three_ips(
        self,
        berserk_state: dict,
        cowboy_bebop_state: dict,
        ghost_state: dict,
    ) -> None:
        report = run_calibration(
            [berserk_state, cowboy_bebop_state, ghost_state],
            golden_set_path=GOLDEN_SET_PATH,
        )
        assert len(report.results) == 3
        assert report.overall_score > 0
        assert report.summary != ""

    def test_passing_report(
        self,
        berserk_state: dict,
        cowboy_bebop_state: dict,
        ghost_state: dict,
    ) -> None:
        report = run_calibration(
            [berserk_state, cowboy_bebop_state, ghost_state],
            golden_set_path=GOLDEN_SET_PATH,
        )
        assert report.passed is True
        assert report.overall_score >= CALIBRATION_PASS_THRESHOLD

    def test_empty_states(self) -> None:
        report = run_calibration([], golden_set_path=GOLDEN_SET_PATH)
        assert len(report.results) == 0
        assert report.overall_score == 0.0
        assert report.passed is False

    def test_single_ip(self, berserk_state: dict) -> None:
        report = run_calibration([berserk_state], golden_set_path=GOLDEN_SET_PATH)
        assert len(report.results) == 1

    def test_summary_format(
        self,
        berserk_state: dict,
        cowboy_bebop_state: dict,
        ghost_state: dict,
    ) -> None:
        report = run_calibration(
            [berserk_state, cowboy_bebop_state, ghost_state],
            golden_set_path=GOLDEN_SET_PATH,
        )
        assert "Calibration:" in report.summary
        assert "Tier:" in report.summary
        assert "Cause:" in report.summary

    def test_report_is_pydantic(
        self,
        berserk_state: dict,
    ) -> None:
        report = run_calibration([berserk_state], golden_set_path=GOLDEN_SET_PATH)
        assert isinstance(report, CalibrationReport)
        dumped = report.model_dump()
        assert "results" in dumped
        assert "overall_score" in dumped


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_case_insensitive_ip_name(self, golden_set: dict) -> None:
        state: dict = {
            "ip_name": "BERSERK",
            "tier": "S",
            "final_score": 82.2,
            "evaluations": {},
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.ip_name == "berserk"
        assert result.tier_match is True

    def test_whitespace_ip_name(self, golden_set: dict) -> None:
        state: dict = {
            "ip_name": "  Berserk  ",
            "tier": "S",
            "final_score": 82.2,
            "evaluations": {},
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.tier_match is True

    def test_empty_evaluations(self, golden_set: dict) -> None:
        state: dict = {
            "ip_name": "Berserk",
            "tier": "S",
            "final_score": 82.2,
            "evaluations": {},
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.tier_match is True
        assert result.overall_score < 100.0

    def test_axis_tolerance_boundary(self) -> None:
        """Test exact boundary of AXIS_TOLERANCE."""
        actual = {"a_score": 4.0 - AXIS_TOLERANCE}
        ref = {"a_score": [4.0, 5.0]}
        results = _calibrate_axes(actual, ref)
        assert results[0].in_range is True

        actual = {"a_score": 4.0 - AXIS_TOLERANCE - 0.01}
        results = _calibrate_axes(actual, ref)
        assert results[0].in_range is False

    def test_score_range_tolerance(self, golden_set: dict) -> None:
        """Final score range uses scaled tolerance for consistency with axis checks."""
        # Berserk range is [80, 86], tolerance = 0.5 * 20 = 10
        # So 70.0 should be within [80-10, 86+10] = [70, 96]
        state: dict = {
            "ip_name": "Berserk",
            "tier": "S",
            "final_score": 70.0,
            "evaluations": {},
            "synthesis": SynthesisResult(
                undervaluation_cause="conversion_failure",
                action_type="marketing_boost",
                value_narrative="...",
                target_gamer_segment="...",
            ),
        }
        result = run_calibration_check(state, golden_set=golden_set)
        assert result.final_score_in_range is True

    def test_score_range_penalty_multiplier(self, golden_set: dict) -> None:
        """SCORE_RANGE_PENALTY_MULTIPLIER is used (not magic number 2)."""
        assert SCORE_RANGE_PENALTY_MULTIPLIER == 2.0

    def test_weighted_evaluator_scoring(self, golden_set: dict) -> None:
        """quality_judge (8 axes) should have more weight than hidden_value (3 axes)."""
        # All quality_judge axes in range, hidden_value all out of range
        state: dict = {
            "ip_name": "Berserk",
            "tier": "S",
            "final_score": 82.2,
            "evaluations": {
                "quality_judge": EvaluatorResult(
                    evaluator_type="quality_judge",
                    axes={
                        "a_score": 4.5,
                        "b_score": 4.2,
                        "c_score": 4.4,
                        "b1_score": 3.8,
                        "c1_score": 3.8,
                        "c2_score": 3.6,
                        "m_score": 3.8,
                        "n_score": 4.0,
                    },
                    composite_score=75.0,
                    rationale="...",
                ),
                "hidden_value": EvaluatorResult(
                    evaluator_type="hidden_value",
                    axes={"d_score": 1.0, "e_score": 1.0, "f_score": 1.0},
                    composite_score=0.0,
                    rationale="...",
                ),
                "community_momentum": EvaluatorResult(
                    evaluator_type="community_momentum",
                    axes={"j_score": 4.8, "k_score": 4.6, "l_score": 4.5},
                    composite_score=90.0,
                    rationale="...",
                ),
            },
            "synthesis": SynthesisResult(
                undervaluation_cause="conversion_failure",
                action_type="marketing_boost",
                value_narrative="...",
                target_gamer_segment="...",
            ),
        }
        result = run_calibration_check(state, golden_set=golden_set)
        # quality_judge (8w) = 100%, hidden_value (3w) = 0%, community (3w) = 100%
        # Weighted axes = (100*8 + 0*3 + 100*3) / 14 ≈ 78.6%
        # Overall = 20+20+20 + 0.4*78.6 ≈ 91.4
        assert result.overall_score > 85.0  # Would be lower with equal weighting
