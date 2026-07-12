"""Frozen experiment contracts for Crucible campaigns.

The loop's three fixed surfaces (the autoresearch projection) are declared
here and pinned by ``tests/plugins/crucible/test_triad_surfaces.py`` so the
triad cannot silently re-fragment:

- ``TRIAD_PROGRAM`` — the producer's instruction document (program.md);
- ``TRIAD_TRAIN_SURFACE`` — the single mutable artifact under test;
- ``TRIAD_PREPARE`` — the one preparation entrypoint, stamped into every
  prepared config as ``prepared_by`` provenance.
"""

from pathlib import Path as _Path

from .bundle import PromotionBundle
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
from .ref_journal import (
    RefIntent,
    RefJournalError,
    RefReceipt,
    commit_ref_update,
    reconcile_ref_update,
    verify_ref_update,
)
from .sealed import (
    CorePromotionDecision,
    SealedError,
    SealedEvaluationArtifacts,
    SealedEvaluator,
    SealedInfrastructureError,
    SealedPlan,
    SealedSupervisor,
)
from .supervisor import (
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
from .tau2_live import Tau2SealedEvaluator

TRIAD_PROGRAM = _Path(__file__).with_name("program.md")
TRIAD_PREPARE = "plugins.crucible.prepare"
TRIAD_TRAIN_SURFACE = "plugins/benchmark_harness/tau2_agent_policy.md"

__all__ = [
    "TRIAD_PREPARE",
    "TRIAD_PROGRAM",
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
