"""Family-aware statistical power admission for prepared Crucible campaigns.

The scorer freezes an operator-selected promotion rule; it does not invent a
noise model.  This module keeps that boundary intact.  A preparation spec must
name explicit, digest-bound pilot assumptions, and this audit estimates how
often the *actual* family-bootstrap rule would issue KEEP under those
assumptions.  The report contains counts and hashes only—never task identities,
payloads, trajectories, or sealed rows.
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

from .contract import ContractError, PromotionRule, TaskUnit
from .promotion import paired_bootstrap_lower_bound

POWER_SPEC_SCHEMA = "crucible.family-power-spec.v1"
POWER_REPORT_SCHEMA = "crucible.family-power-report.v1"
POWER_METHOD = "paired-bernoulli-monte-carlo.v1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_SIMULATIONS = 200_000
_MAX_BASIS_BYTES = 64 * 1024 * 1024
_MONTE_CARLO_Z_95 = 1.959963984540054


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_fields(
    value: Mapping[str, Any],
    field: str,
    *,
    required: set[str],
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - required)
    if missing:
        raise ContractError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unknown fields: {', '.join(unknown)}")


def _probability(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a probability")
    result = float(value)
    lower_ok = result > 0.0 if positive else result >= 0.0
    if not math.isfinite(result) or not lower_ok or result > 1.0:
        qualifier = "in (0, 1]" if positive else "in [0, 1]"
        raise ContractError(f"{field} must be {qualifier}")
    return result


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _text(value: object, field: str, *, max_bytes: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result.encode("utf-8")) > max_bytes:
        raise ContractError(f"{field} exceeds {max_bytes} UTF-8 bytes")
    return result


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _scenario_seed(seed: int, name: str) -> int:
    return int(hashlib.sha256(f"{seed}:{name}".encode()).hexdigest()[:16], 16)


def _verify_basis_file(
    value: object,
    *,
    basis_root: Path,
    expected_sha256: str,
    field: str,
) -> None:
    raw = _text(value, field)
    path = Path(raw).expanduser()
    resolved = (basis_root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        info = resolved.lstat()
    except OSError as exc:
        raise ContractError(f"{field} cannot be read: {exc}") from exc
    if resolved.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ContractError(f"{field} must be a regular non-symlink file")
    if info.st_size > _MAX_BASIS_BYTES:
        raise ContractError(f"{field} exceeds {_MAX_BASIS_BYTES} bytes")
    actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ContractError(f"{field} does not match basis_sha256")


def _wilson_lower_bound(successes: int, total: int) -> float:
    probability = successes / total
    z_squared = _MONTE_CARLO_Z_95**2
    denominator = 1.0 + z_squared / total
    center = probability + z_squared / (2.0 * total)
    radius = _MONTE_CARLO_Z_95 * math.sqrt(
        probability * (1.0 - probability) / total + z_squared / (4.0 * total**2)
    )
    return (center - radius) / denominator


def _scenario_power(
    *,
    family_task_counts: Sequence[int],
    trials_per_task: int,
    promotion: PromotionRule,
    simulations: int,
    seed: int,
    baseline_pass_probability: float,
    target_improvement_pp: float,
    regression_probability: float,
) -> dict[str, Any]:
    if baseline_pass_probability >= 1.0:
        raise ContractError("power scenario baseline_pass_probability must be below 1")
    candidate_pass_probability = baseline_pass_probability + target_improvement_pp
    if candidate_pass_probability > 1.0:
        raise ContractError("power scenario target improvement makes candidate mean exceed 1")
    gain_probability = (
        target_improvement_pp + baseline_pass_probability * regression_probability
    ) / (1.0 - baseline_pass_probability)
    if gain_probability > 1.0:
        raise ContractError(
            "power scenario target improvement and regression require an "
            "impossible gain probability"
        )

    rng = random.Random(seed)
    lower_bound_cache: dict[tuple[float, ...], float] = {}

    def lower_bound(deltas: Sequence[float]) -> float:
        key = tuple(sorted(deltas))
        cached = lower_bound_cache.get(key)
        if cached is None:
            cached = paired_bootstrap_lower_bound(
                key,
                samples=promotion.bootstrap_samples,
                confidence_level=promotion.confidence_level,
            )
            lower_bound_cache[key] = cached
        return cached

    reachable_count = 0
    keep_count = 0
    below_floor_count = 0
    below_materiality_count = 0
    nonpositive_bound_count = 0
    for _simulation in range(simulations):
        baseline_families: list[float] = []
        candidate_families: list[float] = []
        for task_count in family_task_counts:
            observations = task_count * trials_per_task
            baseline_passes = 0
            candidate_passes = 0
            for _observation in range(observations):
                baseline_pass = rng.random() < baseline_pass_probability
                if baseline_pass:
                    candidate_pass = rng.random() >= regression_probability
                else:
                    candidate_pass = rng.random() < gain_probability
                baseline_passes += int(baseline_pass)
                candidate_passes += int(candidate_pass)
            baseline_families.append(baseline_passes / observations)
            candidate_families.append(candidate_passes / observations)

        reachability_deltas = [1.0 - value for value in baseline_families]
        reachable = (
            promotion.minimum_candidate_mean <= 1.0
            and _mean(reachability_deltas) >= promotion.materiality_pp
            and lower_bound(reachability_deltas) > 0.0
        )
        if not reachable:
            continue
        reachable_count += 1

        deltas = [
            candidate - baseline
            for baseline, candidate in zip(
                baseline_families,
                candidate_families,
                strict=True,
            )
        ]
        candidate_mean = _mean(candidate_families)
        improvement = _mean(deltas)
        improvement_lower_bound = lower_bound(deltas)
        below_floor = candidate_mean < promotion.minimum_candidate_mean
        below_materiality = improvement < promotion.materiality_pp
        nonpositive_bound = improvement_lower_bound <= 0.0
        below_floor_count += int(below_floor)
        below_materiality_count += int(below_materiality)
        nonpositive_bound_count += int(nonpositive_bound)
        if not below_floor and not below_materiality and not nonpositive_bound:
            keep_count += 1

    keep_probability = keep_count / simulations
    reachable_probability = reachable_count / simulations
    power_lower_bound = _wilson_lower_bound(keep_count, simulations)
    return {
        "baseline_pass_probability": baseline_pass_probability,
        "target_improvement_pp": target_improvement_pp,
        "regression_probability_on_baseline_success": regression_probability,
        "derived_gain_probability_on_baseline_failure": gain_probability,
        "derived_candidate_pass_probability": candidate_pass_probability,
        "results": {
            "keep_count": keep_count,
            "keep_probability": keep_probability,
            "keep_probability_95pct_lower_bound": power_lower_bound,
            "reachable_count": reachable_count,
            "reachable_probability": reachable_probability,
            "keep_probability_given_reachable": (
                keep_count / reachable_count if reachable_count else 0.0
            ),
            "candidate_below_floor_probability": below_floor_count / simulations,
            "improvement_below_materiality_probability": (below_materiality_count / simulations),
            "confidence_bound_not_positive_probability": (nonpositive_bound_count / simulations),
            "monte_carlo_standard_error": math.sqrt(
                keep_probability * (1.0 - keep_probability) / simulations
            ),
        },
    }


def audit_family_power(
    *,
    tasks: Sequence[TaskUnit],
    trials_per_task: int,
    task_pack_sha256: str,
    promotion: PromotionRule,
    specification: Mapping[str, Any],
    basis_root: Path,
) -> dict[str, Any]:
    """Estimate statistical KEEP power for the exact prepared family design."""

    _require_fields(
        specification,
        "power_audit",
        required={"minimum_power", "scenarios", "schema", "seed", "simulations"},
    )
    if specification.get("schema") != POWER_SPEC_SCHEMA:
        raise ContractError(f"power_audit.schema must be {POWER_SPEC_SCHEMA!r}")
    simulations = _positive_int(specification.get("simulations"), "power_audit.simulations")
    if simulations < 1_000 or simulations > _MAX_SIMULATIONS:
        raise ContractError(f"power_audit.simulations must be between 1000 and {_MAX_SIMULATIONS}")
    seed = specification.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ContractError("power_audit.seed must be a non-negative integer")
    minimum_power = _probability(
        specification.get("minimum_power"),
        "power_audit.minimum_power",
        positive=True,
    )
    if not tasks:
        raise ContractError("power audit requires at least one task")
    if trials_per_task <= 0:
        raise ContractError("power audit trials_per_task must be positive")
    if _SHA256.fullmatch(task_pack_sha256) is None:
        raise ContractError("power audit task_pack_sha256 must be a SHA-256")
    if promotion.primary_metric != "reward":
        raise ContractError("family power audit currently requires binary reward")

    family_task_counts: dict[str, int] = {}
    for task in tasks:
        family_task_counts[task.family_id] = family_task_counts.get(task.family_id, 0) + 1
    family_count = len(family_task_counts)
    if len(tasks) < promotion.minimum_tasks:
        raise ContractError("power audit design has fewer tasks than promotion.minimum_tasks")
    if family_count < promotion.minimum_families:
        raise ContractError("power audit design has fewer families than promotion.minimum_families")

    scenarios_raw = specification.get("scenarios")
    if not isinstance(scenarios_raw, list) or not scenarios_raw:
        raise ContractError("power_audit.scenarios must be a non-empty list")
    names: set[str] = set()
    scenarios: list[dict[str, Any]] = []
    for index, raw in enumerate(scenarios_raw):
        field = f"power_audit.scenarios[{index}]"
        if not isinstance(raw, Mapping):
            raise ContractError(f"{field} must be an object")
        _require_fields(
            raw,
            field,
            required={
                "baseline_pass_probability",
                "basis_file",
                "basis_sha256",
                "name",
                "regression_probability_on_baseline_success",
                "source",
                "target_improvement_pp",
            },
        )
        name = _text(raw.get("name"), f"{field}.name", max_bytes=200)
        if name in names:
            raise ContractError(f"power_audit scenario name is duplicated: {name}")
        names.add(name)
        source = _text(raw.get("source"), f"{field}.source")
        basis_sha256 = raw.get("basis_sha256")
        if not isinstance(basis_sha256, str) or _SHA256.fullmatch(basis_sha256) is None:
            raise ContractError(f"{field}.basis_sha256 must be a SHA-256")
        if basis_sha256 == "0" * 64:
            raise ContractError(f"{field}.basis_sha256 must not be the zero digest")
        _verify_basis_file(
            raw.get("basis_file"),
            basis_root=basis_root,
            expected_sha256=basis_sha256,
            field=f"{field}.basis_file",
        )
        baseline_probability = _probability(
            raw.get("baseline_pass_probability"),
            f"{field}.baseline_pass_probability",
        )
        target_improvement = _probability(
            raw.get("target_improvement_pp"),
            f"{field}.target_improvement_pp",
            positive=True,
        )
        regression_probability = _probability(
            raw.get("regression_probability_on_baseline_success"),
            f"{field}.regression_probability_on_baseline_success",
        )
        result = _scenario_power(
            family_task_counts=tuple(family_task_counts.values()),
            trials_per_task=trials_per_task,
            promotion=promotion,
            simulations=simulations,
            seed=_scenario_seed(seed, name),
            baseline_pass_probability=baseline_probability,
            target_improvement_pp=target_improvement,
            regression_probability=regression_probability,
        )
        power_lower_bound = result["results"]["keep_probability_95pct_lower_bound"]
        assert isinstance(power_lower_bound, float)
        scenarios.append(
            {
                "name": name,
                "source": source,
                "basis_sha256": basis_sha256,
                **result,
                "minimum_power": minimum_power,
                "passes": power_lower_bound >= minimum_power,
            }
        )

    payload: dict[str, Any] = {
        "schema": POWER_REPORT_SCHEMA,
        "method": POWER_METHOD,
        "scope": "statistical_gate_conditional_on_all_nonstatistical_vetoes_passing",
        "task_pack_sha256": task_pack_sha256,
        "design": {
            "task_count": len(tasks),
            "family_count": family_count,
            "family_task_counts": sorted(family_task_counts.values()),
            "trials_per_task": trials_per_task,
        },
        "promotion": promotion.to_dict(),
        "simulations": simulations,
        "monte_carlo_confidence_level": 0.95,
        "seed": seed,
        "minimum_power": minimum_power,
        "scenarios": scenarios,
        "passes": all(bool(scenario["passes"]) for scenario in scenarios),
    }
    return {**payload, "power_audit_id": _canonical_hash(payload)}
