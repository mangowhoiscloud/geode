"""Tests for L4.5 5-Phase RLHF Feedback Loop."""

import pytest

from geode.automation.correlation import CorrelationAnalyzer
from geode.automation.drift import CUSUMDetector
from geode.automation.expert_panel import ExpertPanel
from geode.automation.feedback_loop import (
    FeedbackCycleInput,
    FeedbackCycleResult,
    FeedbackLoop,
    FeedbackPhase,
    ImprovementCandidate,
)
from geode.automation.model_registry import ModelRegistry


class TestFeedbackPhase:
    def test_all_phases(self):
        assert len(FeedbackPhase) == 5
        assert FeedbackPhase.COLLECTION.value == "collection"
        assert FeedbackPhase.ANALYSIS.value == "analysis"
        assert FeedbackPhase.IMPROVEMENT.value == "improvement"
        assert FeedbackPhase.VALIDATION.value == "validation"
        assert FeedbackPhase.RLAIF.value == "rlaif"


class TestFeedbackCycleInput:
    def test_to_dict(self):
        inp = FeedbackCycleInput(
            cycle_id="cycle-1",
            auto_scores=(4.0, 3.0),
            human_scores=(4.5, 2.5),
        )
        d = inp.to_dict()
        assert d["cycle_id"] == "cycle-1"
        assert len(d["auto_scores"]) == 2

    def test_frozen(self):
        """FeedbackCycleInput should be immutable."""
        inp = FeedbackCycleInput(cycle_id="c1", auto_scores=(1.0,))
        with pytest.raises(AttributeError):
            inp.cycle_id = "changed"  # type: ignore[misc]


class TestFeedbackLoop:
    def _make_loop(self):
        detector = CUSUMDetector()
        detector.add_baseline("spearman_rho", [0.8, 0.82, 0.78, 0.81])
        return FeedbackLoop(
            model_registry=ModelRegistry(),
            expert_panel=ExpertPanel(),
            correlation_analyzer=CorrelationAnalyzer(),
            drift_detector=detector,
        )

    def test_collect(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="c1",
            auto_scores=(4.0, 3.0, 4.5),
            human_scores=(4.2, 2.8, 4.3),
        )
        result = loop.collect(inp)
        assert result["phase"] == "collection"
        assert result["n_auto_scores"] == 3
        assert result["data_quality"] == "marginal"  # n=3 < MIN_SAMPLE_SIZE(10)
        assert result["power_level"] == "low"

    def test_collect_insufficient_data(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(cycle_id="c1", auto_scores=(1.0,), human_scores=())
        result = loop.collect(inp)
        assert result["data_quality"] == "insufficient"  # n_paired=0

    def test_analyze_with_correlation(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="c1",
            auto_scores=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
            human_scores=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0),
            metric_values={"spearman_rho": 0.80},
        )
        result = loop.analyze(inp)
        assert result["phase"] == "analysis"
        assert result["spearman_rho"] > 0.9

    def test_analyze_with_drift(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="c1",
            auto_scores=(1.0, 2.0, 3.0),
            human_scores=(1.0, 2.0, 3.0),
            metric_values={"spearman_rho": 0.2},  # Low → drift
        )
        result = loop.analyze(inp)
        # May or may not detect drift on first value (depends on CUSUM accumulation)
        assert "drift_alerts" in result

    def test_propose_improvement_low_correlation(self):
        loop = self._make_loop()
        analysis = {"spearman_rho": 0.3, "drift_alerts": []}
        candidates = loop.propose_improvement(analysis)
        assert len(candidates) >= 1
        assert candidates[0].candidate_id == "imp-correlation"

    def test_propose_improvement_with_drift(self):
        loop = self._make_loop()
        analysis = {
            "spearman_rho": 0.8,
            "drift_alerts": [{"metric_name": "tier_accuracy"}],
        }
        candidates = loop.propose_improvement(analysis)
        assert any(c.candidate_id == "imp-drift" for c in candidates)

    def test_validate_all_passed(self):
        loop = self._make_loop()
        candidates = [
            ImprovementCandidate(
                candidate_id="c1",
                description="test",
                metric_target="rho",
                expected_improvement=0.5,
            )
        ]
        result = loop.validate_and_deploy(candidates, {"rho": 0.6})
        assert result["all_passed"] is True

    def test_validate_failed(self):
        loop = self._make_loop()
        candidates = [
            ImprovementCandidate(
                candidate_id="c1",
                description="test",
                metric_target="rho",
                expected_improvement=0.9,
            )
        ]
        result = loop.validate_and_deploy(candidates, {"rho": 0.5})
        assert result["all_passed"] is False

    def test_run_cycle(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="full-1",
            auto_scores=(1.0, 2.0, 3.0, 4.0, 5.0),
            human_scores=(1.2, 1.8, 3.2, 3.9, 5.1),
            metric_values={"spearman_rho": 0.80},
        )
        result = loop.run_cycle(inp)
        assert isinstance(result, FeedbackCycleResult)
        assert result.cycle_id == "full-1"
        assert "collection" in result.phase_results
        assert "rlaif" in result.phase_results

    def test_rlaif_integration(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="rlaif-1",
            auto_scores=(1.0, 2.0, 3.0, 4.0, 5.0),
            human_scores=(1.2, 1.8, 3.2, 3.9, 5.1),
            expert_ratings={"expert_a": 0.8, "expert_b": 0.7, "expert_c": 0.9},
        )
        validation = {"all_passed": True, "candidates": []}
        candidates = [
            ImprovementCandidate(
                candidate_id="c1",
                description="test improvement",
            ),
        ]
        result = loop.rlaif_integration(inp, validation, candidates)
        assert result["phase"] == "rlaif"
        assert result["synthetic_pairs_generated"] >= 1
        assert len(result["constitutional_checks"]) == 4
        assert all(c["passed"] for c in result["constitutional_checks"])
        assert result["ai_feedback_signals"]["n_improvements_evaluated"] == 1

    def test_rlaif_flags_failed_validation(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="rlaif-fail",
            auto_scores=(1.0, 2.0, 3.0),
            human_scores=(1.0,),
        )
        validation = {"all_passed": False, "candidates": []}
        result = loop.rlaif_integration(inp, validation, [])
        # Constitutional checks should flag failure
        assert any(not c["passed"] for c in result["constitutional_checks"])
        assert result["ai_feedback_signals"]["augmentation_needed"] is True

    def test_apply_improvement_retune(self):
        loop = self._make_loop()
        candidate = ImprovementCandidate(
            candidate_id="imp-correlation",
            description="Retune weights",
            configs={"action": "retune_weights"},
        )
        result = loop.apply_improvement(candidate)
        assert result["applied"] is True

    def test_apply_improvement_recalibrate(self):
        loop = self._make_loop()
        candidate = ImprovementCandidate(
            candidate_id="imp-drift",
            description="Recalibrate",
            configs={"action": "recalibrate", "metrics": ["spearman_rho"]},
        )
        result = loop.apply_improvement(candidate)
        assert result["applied"] is True

    def test_apply_improvement_returns_adjustment_factor(self):
        """retune_weights should compute adjustment_factor from rho gap."""
        loop = self._make_loop()
        candidate = ImprovementCandidate(
            candidate_id="imp-adj",
            description="Retune",
            configs={
                "action": "retune_weights",
                "target_rho": 0.7,
                "current_rho": 0.3,
            },
        )
        result = loop.apply_improvement(candidate)
        assert result["applied"] is True
        assert "adjustment_factor" in result
        assert result["adjustment_factor"] > 0

    def test_analyze_skips_correlation_when_insufficient_data(self):
        """Power gate: skip correlation analysis when n < MIN_SAMPLE_SIZE."""
        loop = self._make_loop()
        # Only 2 samples — below MIN_SAMPLE_SIZE (10)
        inp = FeedbackCycleInput(
            cycle_id="low-power",
            auto_scores=(1.0, 2.0),
            human_scores=(1.0, 2.0),
        )
        result = loop.analyze(inp)
        # Correlation should be None because n=2 < 10
        assert result["correlation"] is None
        assert result["spearman_rho"] == 0.0

    def test_get_history(self):
        loop = self._make_loop()
        inp = FeedbackCycleInput(
            cycle_id="h1",
            auto_scores=(1.0, 2.0, 3.0),
            human_scores=(1.0, 2.0, 3.0),
        )
        loop.run_cycle(inp)
        history = loop.get_history()
        assert len(history) == 1
