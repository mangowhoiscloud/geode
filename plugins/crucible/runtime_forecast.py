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
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import DEFAULT_JSON_LIMIT_BYTES
from .contract import ContractError, ExperimentContract
from .runtime_budget import (
    LEGACY_RUNTIME_PILOT_SCHEMA,
    RUNTIME_ACCOUNTING_METHOD,
    RUNTIME_PILOT_SCHEMA,
    runtime_pilot_block_rates,
    validate_runtime_cycle_observation,
)
from .runtime_identity import (
    RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS,
    canonical_runtime_hash,
    runtime_bindings,
    runtime_design,
    runtime_regime,
    runtime_regime_id,
)

RUNTIME_FORECAST_SCHEMA = "crucible.runtime-forecast.v2"
RUNTIME_FORECAST_METHOD = "opaque-campaign-family-upper-bootstrap.v2"

_MAX_SIMULATIONS = 200_000
_MAX_EXACT_COMPOSITIONS = 200_000
_MAX_EXACT_COMPOSITION_CELLS = 2_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PILOT_V1_FIELDS = {
    "accounting_method",
    "agent_route",
    "assay_config_sha256",
    "blocks",
    "evaluator_sha256",
    "harness_sha256",
    "schema",
    "user_route",
}
_PILOT_V2_FIELDS = _PILOT_V1_FIELDS | {
    "cycle_observation",
    "runtime_regime",
    "runtime_regime_id",
    "source_contract_id",
    "source_runtime_receipt_id",
}
_BINDING_FIELDS = (
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


def _validate_pilot(
    pilot: Mapping[str, Any], field: str
) -> tuple[
    dict[str, str],
    str | None,
    str | None,
    str | None,
    str | None,
]:
    schema = pilot.get("schema")
    if schema == RUNTIME_PILOT_SCHEMA:
        expected_fields = _PILOT_V2_FIELDS
    elif schema == LEGACY_RUNTIME_PILOT_SCHEMA:
        expected_fields = _PILOT_V1_FIELDS
    else:
        raise ContractError(
            f"{field}.schema must be {RUNTIME_PILOT_SCHEMA!r} or {LEGACY_RUNTIME_PILOT_SCHEMA!r}"
        )
    missing = sorted(expected_fields - set(pilot))
    unknown = sorted(str(key) for key in set(pilot) - expected_fields)
    if missing:
        raise ContractError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unknown fields: {', '.join(unknown)}")
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
    if schema == LEGACY_RUNTIME_PILOT_SCHEMA:
        return bindings, None, None, None, None

    source_contract_id = pilot.get("source_contract_id")
    if not isinstance(source_contract_id, str) or _SHA256.fullmatch(source_contract_id) is None:
        raise ContractError(f"{field}.source_contract_id must be a SHA-256")
    source_runtime_receipt_id = pilot.get("source_runtime_receipt_id")
    if (
        not isinstance(source_runtime_receipt_id, str)
        or _SHA256.fullmatch(source_runtime_receipt_id) is None
    ):
        raise ContractError(f"{field}.source_runtime_receipt_id must be a SHA-256")

    regime = pilot.get("runtime_regime")
    if not isinstance(regime, Mapping):
        raise ContractError(f"{field}.runtime_regime must be an object")
    regime_digest = pilot.get("runtime_regime_id")
    if not isinstance(regime_digest, str) or _SHA256.fullmatch(regime_digest) is None:
        raise ContractError(f"{field}.runtime_regime_id must be a SHA-256")
    if canonical_runtime_hash(regime) != regime_digest:
        raise ContractError(f"{field}.runtime_regime_id does not match runtime_regime")
    if regime.get("bindings") != bindings:
        raise ContractError(f"{field}.runtime_regime bindings do not match pilot bindings")
    observation = pilot.get("cycle_observation")
    if not isinstance(observation, Mapping):
        raise ContractError(f"{field}.cycle_observation must be an object")
    status = observation.get("status")
    if status not in {"complete", "right_censored", "infrastructure_invalid"}:
        raise ContractError(f"{field}.cycle_observation.status is invalid")
    return (
        bindings,
        regime_digest,
        str(status),
        source_contract_id,
        source_runtime_receipt_id,
    )


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


def _compositions(total: int, parts: int) -> Iterator[tuple[int, ...]]:
    """Yield weak compositions in O(parts) work per state and O(parts) memory."""

    if total < 0 or parts <= 0:
        raise ContractError("composition dimensions must be non-negative and non-empty")
    counts = [0] * parts
    counts[-1] = total
    while True:
        yield tuple(counts)
        if counts[0] == total:
            return

        # Find the rightmost non-empty part, move one item left, and place
        # the remainder in the final part.  Unlike materializing a length-
        # ``total`` multiset for every state, this cost follows the number of
        # rates and stays bounded by ``exact_state_cells``.
        source = parts - 1
        while counts[source] == 0:
            source -= 1
        remainder = counts[source] - 1
        counts[source] = 0
        counts[source - 1] += 1
        counts[-1] = remainder


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
    values: list[tuple[float, float]] = []
    if family_count == 1:
        for cluster in clusters:
            sample_probability = cluster_probability / len(cluster)
            values.extend((rows_per_family * rate, sample_probability) for rate in cluster)
        return values

    for cluster in clusters:
        log_denominator = family_count * math.log(len(cluster))
        log_factorial = math.lgamma(family_count + 1)
        cluster_values: list[tuple[float, float]] = []
        for counts in _compositions(family_count, len(cluster)):
            log_probability = (
                log_factorial
                - math.fsum(math.lgamma(count + 1) for count in counts)
                - log_denominator
            )
            seconds = rows_per_family * math.fsum(
                count * rate for count, rate in zip(counts, cluster, strict=True)
            )
            cluster_values.append((seconds, log_probability))
        maximum_log_probability = max(
            log_probability for _seconds, log_probability in cluster_values
        )
        scaled_weights = [
            math.exp(log_probability - maximum_log_probability)
            for _seconds, log_probability in cluster_values
        ]
        normalization = math.fsum(scaled_weights)
        values.extend(
            (seconds, cluster_probability * weight / normalization)
            for (seconds, _log_probability), weight in zip(
                cluster_values,
                scaled_weights,
                strict=True,
            )
        )
    return values


def forecast_runtime(
    pilots: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    target_contract: ExperimentContract,
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
    target_design = runtime_design(target_contract)
    family_count = _positive_int(target_design["family_count"], "target family_count")
    family_task_counts = tuple(
        _positive_int(value, "target family_task_counts")
        for value in target_design["family_task_counts"]
    )
    trials = _positive_int(target_contract.trials_per_task, "target trials_per_task")
    target_bindings = runtime_bindings(target_contract)
    target_regime = runtime_regime(target_contract)
    target_regime_digest = runtime_regime_id(target_contract)
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

    clusters: list[list[float]] = []
    aggregate_counts = {
        "block_count": 0,
        "usable_block_count": 0,
        "complete_sample_count": 0,
        "right_censored_sample_count": 0,
        "right_censored_block_count": 0,
        "infrastructure_sample_count_excluded": 0,
        "infrastructure_block_count_excluded": 0,
    }
    matching_cycle_digests: list[str] = []
    matching_cycle_contract_ids: list[str] = []
    matching_cycle_evaluator_walls: list[float] = []
    observed_source_runtime_receipt_ids: set[str] = set()
    for index, (digest, pilot) in enumerate(ordered_pilots):
        field = f"runtime pilots[{index}]"
        (
            bindings,
            pilot_regime_id,
            cycle_status,
            source_contract_id,
            source_runtime_receipt_id,
        ) = _validate_pilot(pilot, field)
        if source_runtime_receipt_id is not None:
            if source_runtime_receipt_id in observed_source_runtime_receipt_ids:
                raise ContractError(
                    "runtime forecast refuses duplicate source_runtime_receipt_id values"
                )
            observed_source_runtime_receipt_ids.add(source_runtime_receipt_id)
        if bindings != target_bindings:
            differing = sorted(
                name for name in _BINDING_FIELDS if bindings[name] != target_bindings[name]
            )
            raise ContractError(
                "runtime forecast pilot bindings differ from target: " + ", ".join(differing)
            )
        rates, counts = runtime_pilot_block_rates(pilot)
        if pilot.get("schema") == RUNTIME_PILOT_SCHEMA:
            validated_status = validate_runtime_cycle_observation(pilot, counts)
            if validated_status != cycle_status:  # pragma: no cover - shared validator invariant
                raise ContractError(f"{field}.cycle_observation status changed during validation")
        if not rates:
            raise ContractError(f"{field} has no usable family blocks")
        clusters.append(rates)
        for name in aggregate_counts:
            aggregate_counts[name] += counts[name]
        observation = pilot.get("cycle_observation")
        fresh_measurement = (
            isinstance(observation, Mapping) and observation.get("fresh_measurement") is True
        )
        if (
            pilot_regime_id == target_regime_digest
            and source_contract_id == target_contract.contract_id
            and cycle_status == "complete"
            and fresh_measurement
        ):
            matching_cycle_digests.append(digest)
            if source_contract_id is None:  # pragma: no cover - v2 regime invariant
                raise ContractError(f"{field} matching cycle lacks source_contract_id")
            matching_cycle_contract_ids.append(source_contract_id)
            if not isinstance(observation, Mapping):  # pragma: no cover - validated above
                raise ContractError(f"{field} matching cycle lacks cycle_observation")
            matching_cycle_evaluator_walls.append(
                _nonnegative_number(
                    observation.get("completed_evaluator_wall_seconds"),
                    f"{field}.cycle_observation.completed_evaluator_wall_seconds",
                )
            )

    matching_cycles = len(matching_cycle_digests)
    uniform_tasks_per_family = len(set(family_task_counts)) == 1
    possible_compositions = (
        sum(math.comb(family_count + len(cluster) - 1, len(cluster) - 1) for cluster in clusters)
        if uniform_tasks_per_family
        else _MAX_EXACT_COMPOSITIONS + 1
    )
    exact_state_cells = (
        sum(
            (
                len(cluster)
                if family_count == 1
                else math.comb(family_count + len(cluster) - 1, len(cluster) - 1) * len(cluster)
            )
            for cluster in clusters
        )
        if uniform_tasks_per_family
        else _MAX_EXACT_COMPOSITION_CELLS + 1
    )
    exact_distribution: list[tuple[float, float]] | None = None
    cycle_totals: list[float] | None = None
    if (
        uniform_tasks_per_family
        and possible_compositions <= _MAX_EXACT_COMPOSITIONS
        and exact_state_cells <= _MAX_EXACT_COMPOSITION_CELLS
    ):
        exact_distribution = _exact_cycle_distribution(
            clusters,
            family_count=family_count,
            tasks_per_family=family_task_counts[0],
            trials_per_task=trials,
        )
        cycle_summary = _weighted_seconds_summary(exact_distribution)
        distribution_evaluation = "exact_multinomial"
        evaluated_draw_count = len(exact_distribution)
    else:
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
    mean_campaign_active = cycle_summary["mean_seconds"] + experiment_overhead + campaign_overhead

    planning_markers: list[dict[str, Any]] = []
    cycle_plans: list[dict[str, Any]] = []
    for coverage in sorted(coverage_values):
        required = _wilks_minimum_sample_size(coverage, confidence_value)
        cycle_quantile = (
            _weighted_quantile(exact_distribution, coverage)
            if exact_distribution is not None
            else _nearest_rank(cycle_totals or (), coverage)
        )
        experiment_wall = math.ceil(
            cycle_quantile + experiment_overhead + RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS
        )
        campaign_wall = math.ceil(experiment_wall + campaign_overhead)
        planning_markers.append(
            {
                "coverage_marker": coverage,
                "class": "model_based_transferred_predictive_quantile",
                "active_compute_quantile_seconds": cycle_quantile,
                "experiment_marker_seconds": experiment_wall,
                "campaign_marker_seconds": campaign_wall,
                "planning_only": True,
                "distribution_free": False,
                "confidence_bound": None,
            }
        )

        additional_target_cycles = max(0, required - matching_cycles)
        confidence_qualified = matching_cycles >= required
        observed_max_evaluator_wall = (
            max(matching_cycle_evaluator_walls) if matching_cycle_evaluator_walls else None
        )
        evaluator_upper_bound = observed_max_evaluator_wall if confidence_qualified else None
        cycle_plans.append(
            {
                "coverage": coverage,
                "confidence": confidence_value,
                "required_independent_target_cycles": required,
                "observed_matching_target_cycles": matching_cycles,
                "observed_max_coverage_confidence": 1.0 - coverage**matching_cycles,
                "additional_target_cycles": additional_target_cycles,
                "confidence_qualified": confidence_qualified,
                "observed_sample_max_evaluator_wall_seconds": observed_max_evaluator_wall,
                "evaluator_wall_upper_tolerance_bound_seconds": evaluator_upper_bound,
                "experiment_wall_upper_tolerance_bound_seconds": (
                    None
                    if evaluator_upper_bound is None
                    else math.ceil(evaluator_upper_bound + RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS)
                ),
                "campaign_wall_upper_tolerance_bound_seconds": (
                    None
                    if evaluator_upper_bound is None
                    else math.ceil(
                        evaluator_upper_bound
                        + RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS
                        + campaign_overhead
                    )
                ),
                "model_based_expected_collection_active_time": _active_time(
                    mean_campaign_active,
                    additional_target_cycles,
                ),
                "model_based_point_wall_product_time": _active_time(
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
            "matching_target_cycle_sha256": matching_cycle_digests,
            "matching_target_cycle_contract_id": matching_cycle_contract_ids,
            "matching_target_cycle_evaluator_wall_seconds": matching_cycle_evaluator_walls,
        },
        "bindings": target_bindings,
        "runtime_regime": target_regime,
        "runtime_regime_id": target_regime_digest,
        "design": {
            **target_design,
            "matching_target_cycle_count": matching_cycles,
        },
        "sampling": {
            "distribution_evaluation": distribution_evaluation,
            "possible_composition_count": possible_compositions,
            "exact_state_cell_count": exact_state_cells,
            "evaluated_draw_count": evaluated_draw_count,
            "monte_carlo_fallback_simulations": simulation_count,
            "monte_carlo_seed": seed,
            "cluster_resampling": "pilot_campaign_then_family",
            "family_rate": "slowest_complete_row_in_fully_observed_family_block",
            "censoring_policy": (
                "right-censored blocks are preserved in counts but excluded from point models"
            ),
        },
        "pilot": aggregate_counts,
        "observed_block_upper_rate_seconds": _seconds_summary(
            [rate for cluster in clusters for rate in cluster]
        ),
        "model_based_target_cycle_active_seconds": cycle_summary,
        "overhead": {
            "experiment_seconds_per_cycle": experiment_overhead,
            "outer_finalization_grace_seconds_per_cycle": (
                RUNTIME_OUTER_FINALIZATION_GRACE_SECONDS
            ),
            "campaign_seconds_per_cycle": campaign_overhead,
        },
        "model_based_planning_markers": planning_markers,
        "distribution_free_target_cycle_plans": cycle_plans,
        "limitations": [
            "block plans assume family exchangeability inside each source campaign",
            "source campaign clusters are resampled but their count may be small",
            "family blocks inside one campaign are not independent Wilks observations",
            "distribution-free cycle plans require the exact frozen source contract",
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
