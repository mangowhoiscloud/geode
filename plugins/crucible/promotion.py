"""Pure paired promotion decision over normalized Crucible evidence."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from .contract import ContractError, ExperimentContract
from .evidence import (
    EvidenceEnvelope,
    ResourceUsage,
    expected_pairs,
    validate_evidence_identity,
)

VERDICT_SCHEMA = "crucible.verdict.v3"
_COMPUTED_VETOES = frozenset({"budget", "infra_clean", "task_coverage"})


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def _paired_bootstrap_lower_bound(
    deltas: list[float],
    *,
    samples: int,
    confidence_level: float,
    seed: int,
) -> float:
    """Deterministic one-sided percentile bound over paired task resampling."""

    if len(set(deltas)) == 1:
        return deltas[0]
    rng = random.Random(seed)
    count = len(deltas)
    bootstrap_means = [
        math.fsum(deltas[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(samples)
    ]
    bootstrap_means.sort()
    alpha = 1.0 - confidence_level
    index = max(0, math.ceil(alpha * samples) - 1)
    return bootstrap_means[index]


@dataclass(frozen=True)
class PromotionVerdict:
    """Immutable KEEP/REJECT/INVALID decision with no side effects."""

    contract_id: str
    stage: Literal["train", "test"]
    baseline_evidence_id: str
    candidate_evidence_id: str
    verdict: Literal["KEEP", "REJECT", "INVALID"]
    promotion_authority: Literal["none"]
    reasons: tuple[str, ...]
    vetoes: tuple[tuple[str, bool], ...]
    usage: ResourceUsage
    pair_count: int
    task_count: int
    family_count: int
    trials_per_task: int
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    paired_improvement: float | None = None
    improvement_lower_bound: float | None = None

    def canonical_payload(self) -> dict[str, Any]:
        metric: dict[str, float | int | None] = {
            "paired_rows": self.pair_count,
            "task_units": self.task_count,
            "family_units": self.family_count,
            "trials_per_task": self.trials_per_task,
            "baseline_mean": self.baseline_mean,
            "candidate_mean": self.candidate_mean,
            "paired_improvement": self.paired_improvement,
            "improvement_lower_bound": self.improvement_lower_bound,
        }
        return {
            "schema": VERDICT_SCHEMA,
            "contract_id": self.contract_id,
            "stage": self.stage,
            "baseline_evidence_id": self.baseline_evidence_id,
            "candidate_evidence_id": self.candidate_evidence_id,
            "verdict": self.verdict,
            "promotion_authority": self.promotion_authority,
            "reasons": list(self.reasons),
            "vetoes": dict(self.vetoes),
            "usage": self.usage.to_dict(),
            "metric": metric,
        }

    @property
    def verdict_id(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "verdict_id": self.verdict_id}

    @classmethod
    def from_mapping(cls, value: object) -> PromotionVerdict:
        """Load a canonical verdict emitted by a trusted evaluator process."""

        if not isinstance(value, Mapping):
            raise ContractError("verdict must be a JSON object")
        if value.get("schema") != VERDICT_SCHEMA:
            raise ContractError(f"verdict.schema must be {VERDICT_SCHEMA!r}")
        stage_raw = value.get("stage")
        verdict_raw = value.get("verdict")
        authority_raw = value.get("promotion_authority")
        if stage_raw not in {"train", "test"}:
            raise ContractError("verdict.stage must be 'train' or 'test'")
        if verdict_raw not in {"KEEP", "REJECT", "INVALID"}:
            raise ContractError("verdict.verdict must be KEEP, REJECT, or INVALID")
        if authority_raw != "none":
            raise ContractError("verdict.promotion_authority must be 'none'")
        reasons_raw = value.get("reasons")
        if not isinstance(reasons_raw, list) or not all(
            isinstance(reason, str) for reason in reasons_raw
        ):
            raise ContractError("verdict.reasons must be a string list")
        vetoes_raw = value.get("vetoes")
        if not isinstance(vetoes_raw, Mapping) or not all(
            isinstance(name, str) and isinstance(result, bool)
            for name, result in vetoes_raw.items()
        ):
            raise ContractError("verdict.vetoes must be a boolean object")
        metric = value.get("metric")
        if not isinstance(metric, Mapping):
            raise ContractError("verdict.metric must be an object")
        pairs = metric.get("paired_rows")
        if isinstance(pairs, bool) or not isinstance(pairs, int) or pairs < 0:
            raise ContractError("verdict.metric.paired_rows must be non-negative")
        task_units = metric.get("task_units")
        if isinstance(task_units, bool) or not isinstance(task_units, int) or task_units < 0:
            raise ContractError("verdict.metric.task_units must be non-negative")
        family_units = metric.get("family_units")
        if isinstance(family_units, bool) or not isinstance(family_units, int) or family_units < 0:
            raise ContractError("verdict.metric.family_units must be non-negative")
        trials_per_task = metric.get("trials_per_task")
        if (
            isinstance(trials_per_task, bool)
            or not isinstance(trials_per_task, int)
            or trials_per_task <= 0
        ):
            raise ContractError("verdict.metric.trials_per_task must be positive")

        def optional_float(field: str) -> float | None:
            raw = metric.get(field)
            if raw is None:
                return None
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ContractError(f"verdict.metric.{field} must be numeric or null")
            number = float(raw)
            if not math.isfinite(number):
                raise ContractError(f"verdict.metric.{field} must be finite")
            return number

        def identifier(field: str) -> str:
            raw = value.get(field)
            if not isinstance(raw, str) or len(raw) != 64:
                raise ContractError(f"verdict.{field} must be a SHA-256")
            try:
                int(raw, 16)
            except ValueError as exc:
                raise ContractError(f"verdict.{field} must be a SHA-256") from exc
            return raw

        loaded = cls(
            contract_id=identifier("contract_id"),
            stage=cast(Literal["train", "test"], stage_raw),
            baseline_evidence_id=identifier("baseline_evidence_id"),
            candidate_evidence_id=identifier("candidate_evidence_id"),
            verdict=cast(Literal["KEEP", "REJECT", "INVALID"], verdict_raw),
            promotion_authority="none",
            reasons=tuple(reasons_raw),
            vetoes=tuple(sorted(vetoes_raw.items())),
            usage=ResourceUsage.from_mapping(value.get("usage")),
            pair_count=pairs,
            task_count=task_units,
            family_count=family_units,
            trials_per_task=trials_per_task,
            baseline_mean=optional_float("baseline_mean"),
            candidate_mean=optional_float("candidate_mean"),
            paired_improvement=optional_float("paired_improvement"),
            improvement_lower_bound=optional_float("improvement_lower_bound"),
        )
        supplied_id = value.get("verdict_id")
        if supplied_id is not None and supplied_id != loaded.verdict_id:
            raise ContractError("verdict_id does not match the canonical verdict")
        return loaded


def decide(
    contract: ExperimentContract,
    baseline: EvidenceEnvelope,
    candidate: EvidenceEnvelope,
) -> PromotionVerdict:
    """Apply the frozen paired rule and non-exchangeable vetoes."""

    usage = baseline.usage + candidate.usage
    reasons: list[str] = []
    identity_clean = True
    evidence_arms: tuple[tuple[EvidenceEnvelope, Literal["baseline", "candidate"]], ...] = (
        (baseline, "baseline"),
        (candidate, "candidate"),
    )
    for evidence, arm in evidence_arms:
        try:
            validate_evidence_identity(contract, evidence, arm=arm)
        except ContractError as exc:
            identity_clean = False
            reasons.append(f"identity_mismatch:{exc}")

    expected = expected_pairs(contract)
    baseline_pairs = tuple(row.pair_id for row in baseline.rows)
    candidate_pairs = tuple(row.pair_id for row in candidate.rows)
    coverage_clean = set(baseline_pairs) == set(expected) and set(candidate_pairs) == set(expected)
    if not coverage_clean:
        reasons.append("task_coverage_incomplete")

    infra_clean = (
        baseline.execution_status == "complete"
        and candidate.execution_status == "complete"
        and all(row.status == "completed" for row in (*baseline.rows, *candidate.rows))
    )
    if not infra_clean:
        reasons.append("infrastructure_contamination")

    budget_clean = (
        usage.wall_seconds <= contract.budget.max_wall_seconds
        and usage.calls <= contract.budget.max_calls
        and usage.tokens <= contract.budget.max_tokens
        and usage.cost_usd <= contract.budget.max_cost_usd
    )
    if not budget_clean:
        reasons.append("budget_exceeded")

    veto_results: dict[str, bool] = {
        "budget": budget_clean,
        "infra_clean": infra_clean,
        "task_coverage": coverage_clean,
    }
    custom_vetoes = sorted(set(contract.vetoes) - _COMPUTED_VETOES)

    if not identity_clean or not coverage_clean or not infra_clean:
        for veto in custom_vetoes:
            veto_results[veto] = False
        return PromotionVerdict(
            contract_id=contract.contract_id,
            stage=contract.stage,
            baseline_evidence_id=baseline.evidence_id,
            candidate_evidence_id=candidate.evidence_id,
            verdict="INVALID",
            promotion_authority="none",
            reasons=tuple(reasons),
            vetoes=tuple(sorted(veto_results.items())),
            usage=usage,
            pair_count=0,
            task_count=0,
            family_count=0,
            trials_per_task=contract.trials_per_task,
        )

    baseline_by_pair = {row.pair_id: row for row in baseline.rows}
    candidate_by_pair = {row.pair_id: row for row in candidate.rows}
    metric_name = contract.promotion.primary_metric
    baseline_by_task_values: dict[str, list[float]] = {task_id: [] for task_id in contract.task_ids}
    candidate_by_task_values: dict[str, list[float]] = {
        task_id: [] for task_id in contract.task_ids
    }
    invalid_metric = False
    missing_checks: set[str] = set()
    for pair_id in expected:
        baseline_row = baseline_by_pair[pair_id]
        candidate_row = candidate_by_pair[pair_id]
        baseline_metric = baseline_row.metric(metric_name)
        candidate_metric = candidate_row.metric(metric_name)
        if baseline_metric is None or candidate_metric is None:
            invalid_metric = True
        else:
            task_id, _trial = pair_id
            baseline_by_task_values[task_id].append(baseline_metric)
            candidate_by_task_values[task_id].append(candidate_metric)
        for veto in custom_vetoes:
            candidate_check = candidate_row.check(veto)
            if candidate_check is None:
                missing_checks.add(veto)

    if invalid_metric:
        reasons.append(f"missing_primary_metric:{metric_name}")
    if missing_checks:
        reasons.extend(f"missing_veto_check:{name}" for name in sorted(missing_checks))
    if invalid_metric or missing_checks:
        for veto in custom_vetoes:
            veto_results[veto] = False
        return PromotionVerdict(
            contract_id=contract.contract_id,
            stage=contract.stage,
            baseline_evidence_id=baseline.evidence_id,
            candidate_evidence_id=candidate.evidence_id,
            verdict="INVALID",
            promotion_authority="none",
            reasons=tuple(reasons),
            vetoes=tuple(sorted(veto_results.items())),
            usage=usage,
            pair_count=len(expected),
            task_count=0,
            family_count=0,
            trials_per_task=contract.trials_per_task,
        )

    for veto in custom_vetoes:
        veto_results[veto] = all(
            candidate_by_pair[pair_id].check(veto) is True for pair_id in expected
        )
        if not veto_results[veto]:
            reasons.append(f"veto_failed:{veto}")

    baseline_task_means = {
        task_id: _mean(baseline_by_task_values[task_id]) for task_id in contract.task_ids
    }
    candidate_task_means = {
        task_id: _mean(candidate_by_task_values[task_id]) for task_id in contract.task_ids
    }
    family_order = tuple(dict.fromkeys(contract.family_ids))
    tasks_by_family: dict[str, list[str]] = {family_id: [] for family_id in family_order}
    for task in contract.tasks:
        tasks_by_family[task.family_id].append(task.task_id)
    baseline_values = [
        _mean([baseline_task_means[task_id] for task_id in tasks_by_family[family_id]])
        for family_id in family_order
    ]
    candidate_values = [
        _mean([candidate_task_means[task_id] for task_id in tasks_by_family[family_id]])
        for family_id in family_order
    ]
    baseline_mean = _mean(baseline_values)
    candidate_mean = _mean(candidate_values)
    deltas = [
        candidate_value - baseline_value
        for baseline_value, candidate_value in zip(
            baseline_values,
            candidate_values,
            strict=True,
        )
    ]
    paired_improvement = _mean(deltas)
    seed_payload = json.dumps(deltas, separators=(",", ":")).encode("utf-8")
    bootstrap_seed = int(hashlib.sha256(seed_payload).hexdigest()[:16], 16)
    lower_bound = _paired_bootstrap_lower_bound(
        deltas,
        samples=contract.promotion.bootstrap_samples,
        confidence_level=contract.promotion.confidence_level,
        seed=bootstrap_seed,
    )

    if len(contract.task_ids) < contract.promotion.minimum_tasks:
        reasons.append("insufficient_tasks")
    if len(family_order) < contract.promotion.minimum_families:
        reasons.append("insufficient_families")
    if candidate_mean < contract.promotion.minimum_candidate_mean:
        reasons.append("candidate_below_absolute_floor")
    if paired_improvement < contract.promotion.materiality_pp:
        reasons.append("improvement_below_materiality")
    if lower_bound <= 0:
        reasons.append("confidence_bound_not_positive")

    keep = not reasons and all(veto_results.values())
    verdict: Literal["KEEP", "REJECT"] = "KEEP" if keep else "REJECT"
    return PromotionVerdict(
        contract_id=contract.contract_id,
        stage=contract.stage,
        baseline_evidence_id=baseline.evidence_id,
        candidate_evidence_id=candidate.evidence_id,
        verdict=verdict,
        # Authority stays closed until a test contract is bound to both a
        # parent train KEEP verdict and a committed, one-shot test pack.
        promotion_authority="none",
        reasons=tuple(reasons),
        vetoes=tuple(sorted(veto_results.items())),
        usage=usage,
        pair_count=len(expected),
        task_count=len(contract.task_ids),
        family_count=len(family_order),
        trials_per_task=contract.trials_per_task,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        paired_improvement=paired_improvement,
        improvement_lower_bound=lower_bound,
    )
