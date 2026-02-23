"""4-Phase RLHF Feedback Loop — collect, analyze, improve, validate.

Orchestrates the feedback cycle across ModelRegistry, ExpertPanel,
CorrelationAnalyzer, and CUSUMDetector to continuously improve
pipeline quality.

Architecture-v6 §4.5: Automation Layer — Feedback Loop.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from geode.automation.correlation import CorrelationAnalyzer
from geode.automation.drift import CUSUMDetector
from geode.automation.expert_panel import ExpertPanel
from geode.automation.model_registry import ModelRegistry

if TYPE_CHECKING:
    from geode.infrastructure.ports.hook_port import HookSystemPort

log = logging.getLogger(__name__)

# Power analysis thresholds (Cohen 1988, Statistical Power Analysis)
# For Spearman rho test at alpha=0.05, power=0.80:
#   Detecting rho=0.50 requires n >= 29 (≈30)
#   Detecting rho=0.30 requires n >= 84
# MIN_SAMPLE_SIZE=10: absolute floor for rank correlation stability
# RECOMMENDED_SAMPLE_SIZE=30: targets 80% power for medium effects (rho≈0.5)
MIN_SAMPLE_SIZE = 10  # Below this, correlation estimates are unreliable
RECOMMENDED_SAMPLE_SIZE = 30  # Normal approximation for p-values


class FeedbackPhase(Enum):
    """Phases of the RLHF feedback cycle."""

    COLLECTION = "collection"
    ANALYSIS = "analysis"
    IMPROVEMENT = "improvement"
    VALIDATION = "validation"


@dataclass(frozen=True)
class FeedbackCycleInput:
    """Input data for a feedback cycle (immutable value object)."""

    cycle_id: str
    auto_scores: tuple[float, ...] = ()
    human_scores: tuple[float, ...] = ()
    expert_ratings: dict[str, float] = field(default_factory=dict)
    metric_values: dict[str, float] = field(default_factory=dict)
    model_version_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "auto_scores": list(self.auto_scores),
            "human_scores": list(self.human_scores),
            "expert_ratings": self.expert_ratings,
            "metric_values": self.metric_values,
            "model_version_id": self.model_version_id,
        }


@dataclass(frozen=True)
class ImprovementCandidate:
    """A proposed improvement from the analysis phase (immutable)."""

    candidate_id: str
    description: str
    metric_target: str = ""
    expected_improvement: float = 0.0
    configs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedbackCycleResult:
    """Result of a complete feedback cycle."""

    cycle_id: str
    phase_results: dict[str, Any] = field(default_factory=dict)
    improvements_applied: list[str] = field(default_factory=list)
    correlation_before: float = 0.0
    correlation_after: float = 0.0
    drift_alerts: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "phase_results": self.phase_results,
            "improvements_applied": self.improvements_applied,
            "correlation_before": self.correlation_before,
            "correlation_after": self.correlation_after,
            "drift_alerts": self.drift_alerts,
            "success": self.success,
            "completed_at": self.completed_at,
        }


class _FeedbackStats:
    """Internal instrumentation counters."""

    __slots__ = ("cycles_run", "cycles_passed", "drift_events", "improvements_applied")

    def __init__(self) -> None:
        self.cycles_run: int = 0
        self.cycles_passed: int = 0
        self.drift_events: int = 0
        self.improvements_applied: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "cycles_run": self.cycles_run,
            "cycles_passed": self.cycles_passed,
            "drift_events": self.drift_events,
            "improvements_applied": self.improvements_applied,
        }


class FeedbackLoop:
    """4-phase RLHF feedback loop for pipeline quality improvement.

    Phases:
        1. COLLECTION: Gather auto scores, human ratings, expert feedback
        2. ANALYSIS: Compute correlations, detect drift, assess quality
        3. IMPROVEMENT: Propose and apply configuration improvements
        4. VALIDATION: Verify improvements meet quality targets

    Usage:
        from geode.automation.model_registry import ModelRegistry
        from geode.automation.expert_panel import ExpertPanel
        from geode.automation.correlation import CorrelationAnalyzer
        from geode.automation.drift import CUSUMDetector

        loop = FeedbackLoop(
            model_registry=ModelRegistry(),
            expert_panel=ExpertPanel(),
            correlation_analyzer=CorrelationAnalyzer(),
            drift_detector=CUSUMDetector(),
        )
        result = loop.run_cycle(input_data)
    """

    def __init__(
        self,
        *,
        model_registry: ModelRegistry | None = None,
        expert_panel: ExpertPanel | None = None,
        correlation_analyzer: CorrelationAnalyzer | None = None,
        drift_detector: CUSUMDetector | None = None,
        hooks: HookSystemPort | None = None,
    ) -> None:
        self._model_registry = model_registry
        self._expert_panel = expert_panel
        self._correlation_analyzer = correlation_analyzer
        self._drift_detector = drift_detector
        self._hooks = hooks
        self._history: list[FeedbackCycleResult] = []
        self._stats = _FeedbackStats()

    @property
    def stats(self) -> _FeedbackStats:
        return self._stats

    def collect(self, cycle_input: FeedbackCycleInput) -> dict[str, Any]:
        """Phase 1: Collect and validate input data with power analysis.

        Returns collection summary with data quality metrics and
        statistical power assessment.
        """
        n_auto = len(cycle_input.auto_scores)
        n_human = len(cycle_input.human_scores)
        n_experts = len(cycle_input.expert_ratings)
        n_paired = min(n_auto, n_human)

        # Statistical power assessment
        if n_paired >= RECOMMENDED_SAMPLE_SIZE:
            power_level = "high"
            data_quality = "good"
        elif n_paired >= MIN_SAMPLE_SIZE:
            power_level = "moderate"
            data_quality = "good"
        elif n_paired >= 3:
            power_level = "low"
            data_quality = "marginal"
        else:
            power_level = "insufficient"
            data_quality = "insufficient"

        result = {
            "phase": FeedbackPhase.COLLECTION.value,
            "n_auto_scores": n_auto,
            "n_human_scores": n_human,
            "n_paired": n_paired,
            "n_expert_ratings": n_experts,
            "has_metrics": len(cycle_input.metric_values) > 0,
            "data_quality": data_quality,
            "power_level": power_level,
            "min_recommended": RECOMMENDED_SAMPLE_SIZE,
        }

        if power_level == "insufficient":
            log.warning(
                "Insufficient sample size: n=%d < %d (skipping correlation in analysis)",
                n_paired, MIN_SAMPLE_SIZE,
            )
        elif power_level == "low":
            log.warning(
                "Low statistical power: n=%d (recommend >= %d for reliable p-values)",
                n_paired, RECOMMENDED_SAMPLE_SIZE,
            )

        log.info(
            "Feedback collection: %d auto, %d human, %d expert ratings (power=%s)",
            n_auto, n_human, n_experts, power_level,
        )
        return result

    def analyze(self, cycle_input: FeedbackCycleInput) -> dict[str, Any]:
        """Phase 2: Analyze correlations and detect drift.

        Enforces statistical power gate: skips correlation when
        n_paired < MIN_SAMPLE_SIZE (insufficient data for reliable p-values).

        Returns analysis results with correlation metrics and drift alerts.
        """
        result: dict[str, Any] = {"phase": FeedbackPhase.ANALYSIS.value}

        n_paired = min(len(cycle_input.auto_scores), len(cycle_input.human_scores))

        # Correlation analysis (with power gate)
        if (
            self._correlation_analyzer
            and cycle_input.auto_scores
            and cycle_input.human_scores
            and len(cycle_input.auto_scores) == len(cycle_input.human_scores)
            and n_paired >= MIN_SAMPLE_SIZE
        ):
            corr = self._correlation_analyzer.full_analysis(
                list(cycle_input.auto_scores),
                list(cycle_input.human_scores),
            )
            result["correlation"] = corr.to_dict()
            result["spearman_rho"] = corr.spearman_rho
        else:
            result["correlation"] = None
            result["spearman_rho"] = 0.0

        # Drift detection
        if self._drift_detector and cycle_input.metric_values:
            alerts = self._drift_detector.scan_all(cycle_input.metric_values)
            result["drift_alerts"] = [a.to_dict() for a in alerts]
        else:
            result["drift_alerts"] = []

        return result

    def propose_improvement(
        self,
        analysis_result: dict[str, Any],
    ) -> list[ImprovementCandidate]:
        """Phase 3: Propose improvements based on analysis.

        Returns list of improvement candidates.
        """
        candidates: list[ImprovementCandidate] = []

        rho = analysis_result.get("spearman_rho", 0.0)
        if rho < 0.5:
            candidates.append(ImprovementCandidate(
                candidate_id="imp-correlation",
                description="Retune scoring weights to improve human-auto correlation",
                metric_target="spearman_rho",
                expected_improvement=0.1,
                configs={"action": "retune_weights"},
            ))

        drift_alerts = analysis_result.get("drift_alerts", [])
        if drift_alerts:
            candidates.append(ImprovementCandidate(
                candidate_id="imp-drift",
                description="Recalibrate baselines for drifted metrics",
                metric_target="drift_reduction",
                expected_improvement=0.0,
                configs={
                    "action": "recalibrate",
                    "metrics": [a["metric_name"] for a in drift_alerts],
                },
            ))

        return candidates

    def apply_improvement(self, candidate: ImprovementCandidate) -> dict[str, Any]:
        """Apply an improvement candidate by executing its action.

        Supported actions:
          - retune_weights: Reset drift baselines and adjust weight hints
            for w_ml/w_llm rebalancing. New weights stored in candidate configs.
          - recalibrate: Reset CUSUM accumulators for drifted metrics and
            update metric baselines for re-calibration.

        Returns a dict with the action taken and any side effects.
        """
        action = candidate.configs.get("action", "")
        result: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "action": action,
            "applied": False,
        }

        if action == "retune_weights" and candidate.configs:
            # Reset drift baselines so new weight regime starts clean
            if self._drift_detector:
                self._drift_detector.reset()

            # Compute suggested weight adjustment from correlation gap
            target_rho = candidate.configs.get("target_rho", 0.5)
            current_rho = candidate.configs.get("current_rho", 0.0)
            rho_gap = max(0, target_rho - current_rho)
            # Heuristic: shift weight toward the more accurate tier
            adjustment_factor = min(rho_gap * 0.2, 0.1)  # Max 10% shift per cycle

            result["applied"] = True
            result["detail"] = (
                f"Reset drift baselines for weight retuning; "
                f"suggested adjustment_factor={adjustment_factor:.3f} "
                f"(rho_gap={rho_gap:.3f})"
            )
            result["adjustment_factor"] = adjustment_factor

        elif action == "recalibrate" and self._drift_detector:
            metrics = candidate.configs.get("metrics", [])
            reset_results: list[str] = []
            for metric_name in metrics:
                self._drift_detector.reset(metric_name)
                reset_results.append(metric_name)
            result["applied"] = True
            result["detail"] = f"Reset CUSUM accumulators for {reset_results}"
            result["metrics_reset"] = reset_results

        return result

    def validate_and_deploy(
        self,
        candidates: list[ImprovementCandidate],
        validation_scores: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Phase 4: Validate improvements and optionally deploy.

        Returns validation result with pass/fail for each candidate.
        """
        validation_scores = validation_scores or {}
        results: dict[str, Any] = {"phase": FeedbackPhase.VALIDATION.value, "candidates": []}

        for candidate in candidates:
            target = candidate.metric_target
            actual = validation_scores.get(target, 0.0)
            passed = actual >= candidate.expected_improvement

            results["candidates"].append({
                "candidate_id": candidate.candidate_id,
                "metric_target": target,
                "expected": candidate.expected_improvement,
                "actual": actual,
                "passed": passed,
            })

        candidates_list = results["candidates"]
        results["all_passed"] = (
            all(c["passed"] for c in candidates_list) if candidates_list else True
        )
        return results

    def run_cycle(self, cycle_input: FeedbackCycleInput) -> FeedbackCycleResult:
        """Run a complete 4-phase feedback cycle."""
        # Phase 1: Collection
        collection = self.collect(cycle_input)

        # Phase 2: Analysis
        analysis = self.analyze(cycle_input)

        # Phase 3: Improvement
        candidates = self.propose_improvement(analysis)

        # Phase 4: Validation (with current metrics as validation scores)
        validation = self.validate_and_deploy(candidates, cycle_input.metric_values)

        # Compute correlation_after: if validation passed and we have scores,
        # re-measure correlation using validation_scores as proxy improvement
        correlation_before = analysis.get("spearman_rho", 0.0)
        correlation_after = correlation_before
        if (
            validation.get("all_passed", False)
            and "spearman_rho" in cycle_input.metric_values
        ):
            correlation_after = cycle_input.metric_values["spearman_rho"]

        result = FeedbackCycleResult(
            cycle_id=cycle_input.cycle_id,
            phase_results={
                "collection": collection,
                "analysis": analysis,
                "improvement": [c.candidate_id for c in candidates],
                "validation": validation,
            },
            improvements_applied=[
                c.candidate_id for c in candidates
                if validation.get("all_passed", False)
            ],
            correlation_before=correlation_before,
            correlation_after=correlation_after,
            drift_alerts=analysis.get("drift_alerts", []),
            success=validation.get("all_passed", False),
        )

        # Apply improvements
        for candidate in candidates:
            self.apply_improvement(candidate)

        self._history.append(result)

        # Update stats
        self._stats.cycles_run += 1
        if result.success:
            self._stats.cycles_passed += 1
            self._stats.improvements_applied += len(result.improvements_applied)

            # Promote model version if registry available and version specified
            if self._model_registry and cycle_input.model_version_id:
                try:
                    from geode.automation.model_registry import PromotionStage

                    current = self._model_registry.get_version(
                        cycle_input.model_version_id,
                    )
                    if current and current.stage == PromotionStage.STAGING:
                        self._model_registry.promote(
                            cycle_input.model_version_id,
                            PromotionStage.CANARY,
                        )
                except Exception as exc:
                    log.warning("Model promotion skipped: %s", exc)

        if result.drift_alerts:
            self._stats.drift_events += len(result.drift_alerts)

        # Emit hook events for observability
        if self._hooks:
            from geode.orchestration.hooks import HookEvent

            if result.drift_alerts:
                self._hooks.trigger(HookEvent.DRIFT_DETECTED, {
                    "cycle_id": cycle_input.cycle_id,
                    "alerts": result.drift_alerts,
                })
            if result.success and result.improvements_applied:
                self._hooks.trigger(HookEvent.OUTCOME_COLLECTED, {
                    "cycle_id": cycle_input.cycle_id,
                    "improvements": result.improvements_applied,
                    "correlation_after": result.correlation_after,
                })

        log.info(
            "Feedback cycle %s completed: success=%s",
            cycle_input.cycle_id, result.success,
        )
        return result

    def get_history(self, limit: int = 10) -> list[FeedbackCycleResult]:
        """Get recent feedback cycle results."""
        return self._history[-limit:]
