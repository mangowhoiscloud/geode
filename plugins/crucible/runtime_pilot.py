"""Build opaque runtime pilots from verified Crucible arm artifacts."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .artifacts import load_json_object
from .contract import ContractError, ExperimentContract
from .evidence import EvidenceEnvelope, expected_pairs, validate_evidence_identity
from .runtime_budget import RUNTIME_ACCOUNTING_METHOD, RUNTIME_PILOT_SCHEMA


def _raw_durations(path: Path, field: str) -> tuple[str, dict[tuple[str, int], float]]:
    raw_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = load_json_object(path, field, max_bytes=512 * 1024 * 1024)
    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        raise ContractError(f"{field}.simulations must be a list")
    durations: dict[tuple[str, int], float] = {}
    for index, value in enumerate(simulations):
        row_field = f"{field}.simulations[{index}]"
        if not isinstance(value, Mapping):
            raise ContractError(f"{row_field} must be an object")
        task_id = value.get("task_id")
        trial = value.get("trial")
        duration = value.get("duration")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ContractError(f"{row_field}.task_id must be a non-empty string")
        if isinstance(trial, bool) or not isinstance(trial, int) or trial < 0:
            raise ContractError(f"{row_field}.trial must be non-negative")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ContractError(f"{row_field}.duration must be positive and finite")
        pair = task_id.strip(), trial
        if pair in durations:
            raise ContractError(f"{field} repeats pair {pair[0]!r}/{pair[1]}")
        durations[pair] = float(duration)
    return raw_sha256, durations


def _arm_samples(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    results_path: Path,
    evidence: EvidenceEnvelope,
) -> dict[tuple[str, int], dict[str, float | str]]:
    validate_evidence_identity(contract, evidence, arm=arm)
    raw_sha256, durations = _raw_durations(results_path, f"{arm} results")
    if evidence.raw_artifact_sha256 != raw_sha256:
        raise ContractError(f"{arm} evidence raw_artifact_sha256 does not match results")
    expected = expected_pairs(contract)
    rows = {row.pair_id: row for row in evidence.rows}
    if set(rows) != set(expected) or set(durations) != set(expected):
        raise ContractError(f"{arm} runtime pilot artifacts do not have exact task coverage")

    samples: dict[tuple[str, int], dict[str, float | str]] = {}
    for pair in expected:
        row = rows[pair]
        if row.status == "infrastructure_error":
            outcome = "infrastructure_failure"
        elif row.termination_reason == "timeout":
            outcome = "semantic_timeout"
        else:
            outcome = "complete"
        samples[pair] = {
            "outcome": outcome,
            "wall_seconds": durations[pair],
        }
    return samples


def build_runtime_pilot(
    contract: ExperimentContract,
    *,
    baseline_results_path: Path,
    baseline_evidence: EvidenceEnvelope,
    candidate_results_path: Path,
    candidate_evidence: EvidenceEnvelope,
) -> dict[str, Any]:
    """Project verified paired arm artifacts into identity-free family blocks."""

    baseline = _arm_samples(
        contract,
        arm="baseline",
        results_path=baseline_results_path,
        evidence=baseline_evidence,
    )
    candidate = _arm_samples(
        contract,
        arm="candidate",
        results_path=candidate_results_path,
        evidence=candidate_evidence,
    )
    family_samples: dict[str, list[dict[str, float | str]]] = {}
    family_order: list[str] = []
    for task in contract.tasks:
        if task.family_id not in family_samples:
            family_samples[task.family_id] = []
            family_order.append(task.family_id)
        for trial in range(contract.trials_per_task):
            pair = task.task_id, trial
            family_samples[task.family_id].append(baseline[pair])
            family_samples[task.family_id].append(candidate[pair])

    return {
        "schema": RUNTIME_PILOT_SCHEMA,
        "accounting_method": RUNTIME_ACCOUNTING_METHOD,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "agent_route": contract.agent_route,
        "user_route": contract.user_route,
        "blocks": [{"samples": family_samples[family]} for family in family_order],
    }


__all__ = ["build_runtime_pilot"]
