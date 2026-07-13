"""Forecast Crucible wall budgets and runtime-calibration effort from pilots.

The forecast keeps the two uncertainty questions separate:

* a hierarchical campaign-then-family bootstrap estimates the active wall for
  one target paired design; and
* Wilks' one-sided distribution-free formula states how many independent
  observations are required before calling a p95/p99 upper tolerance bound
  confidence-qualified.

Inputs are opaque runtime pilots produced from verified paired arm artifacts.
Task and family identities never enter the report.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import DEFAULT_JSON_LIMIT_BYTES
from .contract import ContractError
from .runtime_budget import (
    RUNTIME_ACCOUNTING_METHOD,
    RUNTIME_PILOT_SCHEMA,
    runtime_pilot_block_rates,
)

RUNTIME_FORECAST_SCHEMA = "crucible.runtime-forecast.v1"
RUNTIME_FORECAST_METHOD = "opaque-campaign-family-upper-bootstrap.v1"

_MAX_SIMULATIONS = 200_000
_MAX_EXACT_COMPOSITIONS = 200_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PILOT_FIELDS = {
    "accounting_method",
    "agent_route",
    "assay_config_sha256",
    "blocks",
    "evaluator_sha256",
    "harness_sha256",
    "schema",
    "user_route",
}
_BINDING_FIELDS = (
    "accounting_method",
    "agent_route",
    "assay_config_sha256",
    "evaluator_sha256",
    "harness_sha256",
    "user_route",
)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field} must be a non-negative integer")
    return value


def _nonnegative_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a non-negative finite number")
    result = float(value)
    if result < 0.0 or not math.isfinite(result):
        raise ContractError(f"{field} must be a non-negative finite number")
    return result


def _probability(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a probability in (0, 1)")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0 or result >= 1.0:
        raise ContractError(f"{field} must be a probability in (0, 1)")
    return result


def _nearest_rank(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _seconds_summary(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ContractError("runtime forecast cannot summarize an empty sample")
    ordered = sorted(values)
    return {
        "mean_seconds": math.fsum(ordered) / len(ordered),
        "p50_seconds": _nearest_rank(ordered, 0.50),
        "p90_seconds": _nearest_rank(ordered, 0.90),
        "p95_seconds": _nearest_rank(ordered, 0.95),
        "p99_seconds": _nearest_rank(ordered, 0.99),
        "maximum_seconds": ordered[-1],
    }


def _weighted_quantile(
    values: Sequence[tuple[float, float]],
    probability: float,
) -> float:
    ordered = sorted(values)
    total_probability = math.fsum(weight for _seconds, weight in ordered)
    threshold = probability * total_probability
    cumulative = 0.0
    for seconds, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return seconds
    return ordered[-1][0]


def _weighted_seconds_summary(
    values: Sequence[tuple[float, float]],
) -> dict[str, float]:
    if not values:
        raise ContractError("runtime forecast cannot summarize an empty distribution")
    total_probability = math.fsum(weight for _seconds, weight in values)
    if not math.isclose(total_probability, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ContractError("runtime forecast exact probabilities do not sum to one")
    return {
        "mean_seconds": math.fsum(seconds * weight for seconds, weight in values)
        / total_probability,
        "p50_seconds": _weighted_quantile(values, 0.50),
        "p90_seconds": _weighted_quantile(values, 0.90),
        "p95_seconds": _weighted_quantile(values, 0.95),
        "p99_seconds": _weighted_quantile(values, 0.99),
        "maximum_seconds": max(seconds for seconds, _weight in values),
    }


def _wilks_minimum_sample_size(coverage: float, confidence: float) -> int:
    """First-order one-sided Wilks size using the sample maximum.

    Wilks, S. S. (1941), doi:10.1214/aoms/1177731788.
    """

    return math.ceil(math.log1p(-confidence) / math.log(coverage))


def _active_time(seconds_per_cycle: float, cycle_count: int) -> dict[str, float]:
    total = seconds_per_cycle * cycle_count
    return {
        "seconds": total,
        "hours": total / 3_600.0,
        "continuous_days": total / 86_400.0,
    }


def load_runtime_pilot(path: Path) -> tuple[str, dict[str, Any]]:
    """Read and hash one regular pilot file from the same byte snapshot."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise ContractError(f"cannot read runtime pilot {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(f"runtime pilot must be a regular file: {path}")
    if info.st_size > DEFAULT_JSON_LIMIT_BYTES:
        raise ContractError(f"runtime pilot exceeds {DEFAULT_JSON_LIMIT_BYTES} bytes: {path}")
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read runtime pilot {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"runtime pilot must be a JSON object: {path}")
    return hashlib.sha256(encoded).hexdigest(), value


def _validate_pilot(pilot: Mapping[str, Any], field: str) -> dict[str, str]:
    missing = sorted(_PILOT_FIELDS - set(pilot))
    unknown = sorted(str(key) for key in set(pilot) - _PILOT_FIELDS)
    if missing:
        raise ContractError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unknown fields: {', '.join(unknown)}")
    if pilot.get("schema") != RUNTIME_PILOT_SCHEMA:
        raise ContractError(f"{field}.schema must be {RUNTIME_PILOT_SCHEMA!r}")
    if pilot.get("accounting_method") != RUNTIME_ACCOUNTING_METHOD:
        raise ContractError(f"{field}.accounting_method must be {RUNTIME_ACCOUNTING_METHOD!r}")

    bindings: dict[str, str] = {}
    for name in _BINDING_FIELDS:
        value = pilot.get(name)
        if not isinstance(value, str) or not value:
            raise ContractError(f"{field}.{name} must be a non-empty string")
        if name.endswith("sha256") and _SHA256.fullmatch(value) is None:
            raise ContractError(f"{field}.{name} must be a SHA-256")
        bindings[name] = value
    return bindings


def _simulate_cycle_totals(
    clusters: Sequence[Sequence[float]],
    *,
    family_task_counts: Sequence[int],
    trials_per_task: int,
    simulations: int,
    seed: int,
) -> list[float]:
    rng = random.Random(seed)
    rows_per_task = 2 * trials_per_task
    totals: list[float] = []
    for _simulation in range(simulations):
        # One source pilot represents one campaign/runtime regime. Keep that
        # shared regime while resampling families inside the simulated cycle.
        cluster = clusters[rng.randrange(len(clusters))]
        total = 0.0
        for task_count in family_task_counts:
            total += cluster[rng.randrange(len(cluster))] * task_count * rows_per_task
        totals.append(total)
    return totals


def _compositions(total: int, parts: int) -> Sequence[tuple[int, ...]]:
    if parts == 1:
        return ((total,),)
    return tuple(
        (head, *tail)
        for head in range(total + 1)
        for tail in _compositions(total - head, parts - 1)
    )


def _exact_cycle_distribution(
    clusters: Sequence[Sequence[float]],
    *,
    family_count: int,
    tasks_per_family: int,
    trials_per_task: int,
) -> list[tuple[float, float]]:
    """Enumerate the empirical hierarchical bootstrap when it is tractable."""

    rows_per_family = tasks_per_family * 2 * trials_per_task
    cluster_probability = 1.0 / len(clusters)
    factorial = math.factorial(family_count)
    values: list[tuple[float, float]] = []
    for cluster in clusters:
        denominator = len(cluster) ** family_count
        for counts in _compositions(family_count, len(cluster)):
            ways = factorial // math.prod(math.factorial(count) for count in counts)
            seconds = rows_per_family * math.fsum(
                count * rate for count, rate in zip(counts, cluster, strict=True)
            )
            values.append((seconds, cluster_probability * ways / denominator))
    return values


def forecast_runtime(
    pilots: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    target_family_count: int,
    tasks_per_family: int,
    trials_per_task: int,
    matching_target_cycle_count: int,
    simulations: int,
    seed: int,
    confidence: float,
    coverages: Sequence[float],
    experiment_overhead_seconds: float,
    campaign_overhead_seconds: float,
) -> dict[str, Any]:
    """Produce an identity-free target-cycle and calibration-time forecast."""

    if not pilots:
        raise ContractError("runtime forecast requires at least one pilot")
    family_count = _positive_int(target_family_count, "target_family_count")
    per_family = _positive_int(tasks_per_family, "tasks_per_family")
    trials = _positive_int(trials_per_task, "trials_per_task")
    matching_cycles = _nonnegative_int(
        matching_target_cycle_count,
        "matching_target_cycle_count",
    )
    simulation_count = _positive_int(simulations, "simulations")
    if simulation_count < 1_000 or simulation_count > _MAX_SIMULATIONS:
        raise ContractError(f"simulations must be between 1000 and {_MAX_SIMULATIONS}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ContractError("seed must be a non-negative integer")
    confidence_value = _probability(confidence, "confidence")
    coverage_values = tuple(_probability(value, "coverage") for value in coverages)
    if not coverage_values:
        raise ContractError("runtime forecast requires at least one coverage")
    if len(set(coverage_values)) != len(coverage_values):
        raise ContractError("runtime forecast coverages must not repeat")
    experiment_overhead = _nonnegative_number(
        experiment_overhead_seconds,
        "experiment_overhead_seconds",
    )
    campaign_overhead = _nonnegative_number(
        campaign_overhead_seconds,
        "campaign_overhead_seconds",
    )

    ordered_pilots = sorted(pilots, key=lambda item: item[0])
    digests = [digest for digest, _pilot in ordered_pilots]
    if any(_SHA256.fullmatch(digest) is None for digest in digests):
        raise ContractError("runtime forecast pilot digests must be SHA-256 values")
    if len(set(digests)) != len(digests):
        raise ContractError("runtime forecast refuses duplicate pilot digests")

    expected_bindings: dict[str, str] | None = None
    clusters: list[list[float]] = []
    aggregate_counts = {
        "block_count": 0,
        "usable_block_count": 0,
        "complete_sample_count": 0,
        "semantic_timeout_sample_count": 0,
        "infrastructure_sample_count_excluded": 0,
    }
    for index, (_digest, pilot) in enumerate(ordered_pilots):
        field = f"runtime pilots[{index}]"
        bindings = _validate_pilot(pilot, field)
        if expected_bindings is None:
            expected_bindings = bindings
        elif bindings != expected_bindings:
            differing = sorted(
                name for name in _BINDING_FIELDS if bindings[name] != expected_bindings[name]
            )
            raise ContractError("runtime forecast pilot bindings differ: " + ", ".join(differing))
        rates, counts = runtime_pilot_block_rates(pilot)
        if not rates:
            raise ContractError(f"{field} has no usable family blocks")
        clusters.append(rates)
        for name in aggregate_counts:
            aggregate_counts[name] += counts[name]

    assert expected_bindings is not None  # pilots is non-empty
    possible_compositions = sum(
        math.comb(family_count + len(cluster) - 1, len(cluster) - 1) for cluster in clusters
    )
    exact_distribution: list[tuple[float, float]] | None = None
    cycle_totals: list[float] | None = None
    if possible_compositions <= _MAX_EXACT_COMPOSITIONS:
        exact_distribution = _exact_cycle_distribution(
            clusters,
            family_count=family_count,
            tasks_per_family=per_family,
            trials_per_task=trials,
        )
        cycle_summary = _weighted_seconds_summary(exact_distribution)
        distribution_evaluation = "exact_multinomial"
        evaluated_draw_count = len(exact_distribution)
    else:
        family_task_counts = (per_family,) * family_count
        cycle_totals = _simulate_cycle_totals(
            clusters,
            family_task_counts=family_task_counts,
            trials_per_task=trials,
            simulations=simulation_count,
            seed=seed,
        )
        cycle_summary = _seconds_summary(cycle_totals)
        distribution_evaluation = "deterministic_monte_carlo"
        evaluated_draw_count = simulation_count
    observed_blocks = aggregate_counts["usable_block_count"]
    mean_campaign_active = cycle_summary["mean_seconds"] + experiment_overhead + campaign_overhead

    block_plans: list[dict[str, Any]] = []
    cycle_plans: list[dict[str, Any]] = []
    for coverage in sorted(coverage_values):
        required = _wilks_minimum_sample_size(coverage, confidence_value)
        cycle_quantile = (
            _weighted_quantile(exact_distribution, coverage)
            if exact_distribution is not None
            else _nearest_rank(cycle_totals or (), coverage)
        )
        experiment_wall = math.ceil(cycle_quantile + experiment_overhead)
        campaign_wall = math.ceil(experiment_wall + campaign_overhead)

        additional_blocks = max(0, required - observed_blocks)
        additional_block_cycles = math.ceil(additional_blocks / family_count)
        block_plans.append(
            {
                "coverage": coverage,
                "confidence": confidence_value,
                "required_independent_blocks": required,
                "observed_usable_blocks": observed_blocks,
                "iid_block_assumption_max_coverage_confidence": (1.0 - coverage**observed_blocks),
                "additional_blocks": additional_blocks,
                "optimistic_additional_full_cycles": additional_block_cycles,
                "point_cycle_row_quantile_seconds": cycle_quantile,
                "point_experiment_wall_seconds": experiment_wall,
                "point_campaign_wall_seconds": campaign_wall,
                "expected_collection_active_time": _active_time(
                    mean_campaign_active,
                    additional_block_cycles,
                ),
                "point_wall_product_time": _active_time(
                    float(campaign_wall),
                    additional_block_cycles,
                ),
            }
        )

        additional_target_cycles = max(0, required - matching_cycles)
        cycle_plans.append(
            {
                "coverage": coverage,
                "confidence": confidence_value,
                "required_independent_target_cycles": required,
                "observed_matching_target_cycles": matching_cycles,
                "observed_max_coverage_confidence": 1.0 - coverage**matching_cycles,
                "additional_target_cycles": additional_target_cycles,
                "expected_collection_active_time": _active_time(
                    mean_campaign_active,
                    additional_target_cycles,
                ),
                "point_wall_product_time": _active_time(
                    float(campaign_wall),
                    additional_target_cycles,
                ),
            }
        )

    payload: dict[str, Any] = {
        "schema": RUNTIME_FORECAST_SCHEMA,
        "method": RUNTIME_FORECAST_METHOD,
        "source_pilots": {
            "campaign_cluster_count": len(clusters),
            "sha256": digests,
        },
        "bindings": expected_bindings,
        "design": {
            "target_family_count": family_count,
            "tasks_per_family": per_family,
            "trials_per_task": trials,
            "paired_row_count": family_count * per_family * trials * 2,
            "matching_target_cycle_count": matching_cycles,
        },
        "sampling": {
            "distribution_evaluation": distribution_evaluation,
            "possible_composition_count": possible_compositions,
            "evaluated_draw_count": evaluated_draw_count,
            "monte_carlo_fallback_simulations": simulation_count,
            "monte_carlo_seed": seed,
            "cluster_resampling": "pilot_campaign_then_family",
            "family_rate": "slowest_semantic_row_in_verified_family_block",
        },
        "pilot": aggregate_counts,
        "observed_block_upper_rate_seconds": _seconds_summary(
            [rate for cluster in clusters for rate in cluster]
        ),
        "target_cycle_row_wall_seconds": cycle_summary,
        "overhead": {
            "experiment_seconds_per_cycle": experiment_overhead,
            "campaign_seconds_per_cycle": campaign_overhead,
        },
        "model_based_block_plans": block_plans,
        "distribution_free_target_cycle_plans": cycle_plans,
        "limitations": [
            "block plans assume family exchangeability inside each source campaign",
            "source campaign clusters are resampled but their count may be small",
            "distribution-free cycle plans count only exact matching target cycles",
            "calendar diversity and provider-capacity waits are outside active wall time",
        ],
    }
    return {**payload, "runtime_forecast_id": _canonical_hash(payload)}


__all__ = [
    "RUNTIME_FORECAST_METHOD",
    "RUNTIME_FORECAST_SCHEMA",
    "forecast_runtime",
    "load_runtime_pilot",
]
