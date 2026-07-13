"""Canonical identity for one Crucible runtime-observation regime.

Runtime forecasts may transfer family-level rates across designs, but a
distribution-free target-cycle count must be stricter: only a completed cycle
measured under the exact same evaluator, harness, assay, pack, design, stage,
and execution policy can increment it.  This module keeps that distinction in
one hashable vocabulary shared by pilots, forecasts, and evaluator receipts.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from .contract import (
    ContractError,
    ExperimentContract,
    TaskUnit,
)
from .contract import (
    task_pack_sha256 as contract_task_pack_sha256,
)

RUNTIME_REGIME_SCHEMA = "crucible.runtime-regime.v1"
RUNTIME_ARM_ORDER = "baseline_then_candidate"
RUNTIME_ARM_WALL_POLICY = "shared_deadline_remaining.v1"
RUNTIME_ACCOUNTING_SCOPE = "fresh_simulation_active_wall"


def canonical_runtime_hash(value: object) -> str:
    """Return the stable SHA-256 used by runtime-only artifacts."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def runtime_design_from_parts(
    *,
    tasks: Sequence[TaskUnit],
    trials_per_task: int,
    task_pack_sha256: str,
) -> dict[str, Any]:
    """Project the exact opaque task/family shape without exposing identities."""

    if not tasks:
        raise ContractError("runtime design requires at least one task")
    if trials_per_task <= 0:
        raise ContractError("runtime design trials_per_task must be positive")
    if task_pack_sha256 != contract_task_pack_sha256(tasks, trials_per_task):
        raise ContractError("runtime design task_pack_sha256 does not match tasks and trials")

    family_counts = Counter(task.family_id for task in tasks)
    ordered_counts = sorted(family_counts.values())
    return {
        "task_pack_sha256": task_pack_sha256,
        "task_count": len(tasks),
        "family_count": len(ordered_counts),
        "family_task_counts": ordered_counts,
        "trials_per_task": trials_per_task,
        "paired_row_count": len(tasks) * trials_per_task * 2,
    }


def runtime_design(contract: ExperimentContract) -> dict[str, Any]:
    return runtime_design_from_parts(
        tasks=contract.tasks,
        trials_per_task=contract.trials_per_task,
        task_pack_sha256=contract.task_pack_sha256,
    )


def runtime_bindings(contract: ExperimentContract) -> dict[str, str]:
    """Return every frozen implementation/route binding that can shift runtime."""

    return {
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "agent_route": contract.agent_route,
        "user_route": contract.user_route,
    }


def runtime_regime_from_parts(
    *,
    stage: Literal["train", "test"],
    bindings: Mapping[str, str],
    design: Mapping[str, Any],
    experiment_wall_seconds: float,
) -> dict[str, Any]:
    """Build the exact regime whose completed cycles may be pooled as iid evidence."""

    if not math.isfinite(experiment_wall_seconds) or experiment_wall_seconds <= 0.0:
        raise ContractError("runtime regime experiment wall must be positive and finite")

    return {
        "schema": RUNTIME_REGIME_SCHEMA,
        "stage": stage,
        "bindings": dict(bindings),
        "design": dict(design),
        "execution": {
            "arm_order": RUNTIME_ARM_ORDER,
            "arm_wall_policy": RUNTIME_ARM_WALL_POLICY,
            "accounting_scope": RUNTIME_ACCOUNTING_SCOPE,
            "experiment_wall_seconds": float(experiment_wall_seconds),
            # Row-cache hits alter marginal spend, not the fresh-simulation
            # duration projected by runtime pilots.  Keeping that exclusion in
            # the identity prevents a later implementation from silently
            # changing the estimand.
            "row_cache": "excluded_from_runtime_model",
        },
    }


def runtime_regime(
    contract: ExperimentContract,
    *,
    experiment_wall_seconds: float | None = None,
) -> dict[str, Any]:
    """Return the regime, optionally using the evaluator's effective wall.

    The contract wall is the target ceiling. A live campaign can hand the
    evaluator less time after producer work consumes the outer budget; that
    shortened censoring policy is a distinct runtime cohort.
    """

    return runtime_regime_from_parts(
        stage=contract.stage,
        bindings=runtime_bindings(contract),
        design=runtime_design(contract),
        experiment_wall_seconds=(
            contract.budget.max_wall_seconds
            if experiment_wall_seconds is None
            else experiment_wall_seconds
        ),
    )


def runtime_regime_id(
    contract: ExperimentContract,
    *,
    experiment_wall_seconds: float | None = None,
) -> str:
    return canonical_runtime_hash(
        runtime_regime(contract, experiment_wall_seconds=experiment_wall_seconds)
    )


__all__ = [
    "RUNTIME_ACCOUNTING_SCOPE",
    "RUNTIME_ARM_ORDER",
    "RUNTIME_ARM_WALL_POLICY",
    "RUNTIME_REGIME_SCHEMA",
    "canonical_runtime_hash",
    "runtime_bindings",
    "runtime_design",
    "runtime_design_from_parts",
    "runtime_regime",
    "runtime_regime_from_parts",
    "runtime_regime_id",
]
