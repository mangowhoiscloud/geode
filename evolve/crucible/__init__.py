"""Frozen experiment contracts for Crucible campaigns.

The loop's two fixed surfaces (the autoresearch projection) are declared
here and pinned by ``tests/evolve/crucible/test_triad_surfaces.py`` so the
contract cannot silently re-fragment:

- ``TRIAD_TRAIN_SURFACE`` — the single mutable artifact under test;
- ``TRIAD_PREPARE`` — the one preparation entrypoint, stamped into every
  prepared config as ``prepared_by`` provenance.
"""

from .assays.tau2_live import Tau2SealedEvaluator
from .attestation.bundle import PromotionBundle
from .attestation.sealed import (
    CorePromotionDecision,
    SealedError,
    SealedEvaluationArtifacts,
    SealedEvaluator,
    SealedInfrastructureError,
    SealedPlan,
    SealedSupervisor,
)
from .contract import (
    Budget,
    ContractError,
    ExperimentContract,
    Mutation,
    PromotionRule,
    TaskUnit,
    content_sha256,
    load_contract,
    task_pack_sha256,
    tracked_tree_sha256,
    validate_candidate_diff,
    validate_checkout,
    validate_measurement_files,
    validate_shards,
    validate_test_parent,
)
from .evidence import (
    EvidenceEnvelope,
    ResourceUsage,
    TaskEvidence,
    load_evidence,
    validate_evidence_identity,
)
from .promotion import PromotionReachability, PromotionVerdict, decide, promotion_reachability
from .search.ref_journal import (
    RefIntent,
    RefJournalError,
    RefReceipt,
    commit_ref_update,
    reconcile_ref_update,
    verify_ref_update,
)
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

TRIAD_PREPARE = "evolve.crucible.prepare"
TRIAD_TRAIN_SURFACE = "evals/benchmarks/tau2/agent_policy.md"

__all__ = [
    "TRIAD_PREPARE",
    "TRIAD_TRAIN_SURFACE",
    "Budget",
    "CandidateProducer",
    "CandidateProposal",
    "ContractError",
    "CorePromotionDecision",
    "EvaluationArtifacts",
    "EvidenceEnvelope",
    "ExperimentContract",
    "FailureFeedback",
    "LoopLimits",
    "Mutation",
    "PromotionBundle",
    "PromotionReachability",
    "PromotionRule",
    "PromotionSupervisor",
    "PromotionVerdict",
    "RefIntent",
    "RefJournalError",
    "RefReceipt",
    "ResourceUsage",
    "SealedError",
    "SealedEvaluationArtifacts",
    "SealedEvaluator",
    "SealedInfrastructureError",
    "SealedPlan",
    "SealedSupervisor",
    "SupervisorConfig",
    "SupervisorError",
    "SupervisorSummary",
    "TaskEvidence",
    "TaskUnit",
    "Tau2SealedEvaluator",
    "TrainPlan",
    "TrustedEvaluator",
    "commit_ref_update",
    "content_sha256",
    "decide",
    "load_contract",
    "load_evidence",
    "promotion_reachability",
    "reconcile_ref_update",
    "run_supervisor",
    "task_pack_sha256",
    "tracked_tree_sha256",
    "validate_candidate_diff",
    "validate_checkout",
    "validate_evidence_identity",
    "validate_measurement_files",
    "validate_shards",
    "validate_test_parent",
    "verify_ref_update",
]
