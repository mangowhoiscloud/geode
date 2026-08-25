"""Compatibility facade for the stable Crucible loop component path."""

from .search.supervisor import (
    CandidateProducer,
    CandidateProposal,
    EvaluationArtifacts,
    FailureFeedback,
    LoopLimits,
    PromotionSupervisor,
    SupervisorConfig,
    SupervisorError,
    SupervisorSummary,
    TrainPlan,
    TrustedEvaluator,
    run_supervisor,
)

__all__ = [
    "CandidateProducer",
    "CandidateProposal",
    "EvaluationArtifacts",
    "FailureFeedback",
    "LoopLimits",
    "PromotionSupervisor",
    "SupervisorConfig",
    "SupervisorError",
    "SupervisorSummary",
    "TrainPlan",
    "TrustedEvaluator",
    "run_supervisor",
]
