"""Digest-bound wall-clock admission for prepared Crucible experiments.

Crucible's statistical power audit asks whether a frozen task/family design can
open its promotion gate.  This module asks the orthogonal question: can the
same paired experiment finish inside its preregistered wall budget?

The audit consumes an explicit pilot artifact.  Pilot samples are grouped into
opaque task/family blocks so the bootstrap preserves between-workflow runtime
heterogeneity.  Semantic timeouts remain runtime observations; infrastructure
failures are counted but excluded because a 401/429/transport interruption is
not a sample from the assay's semantic runtime distribution.  Reports contain
only counts, digests, and aggregate timings—never task identities or rows.

The first campaign under a new evaluator digest has no matching pilot by
definition.  ``contract_ceiling`` mode closes that bootstrap gap without
inventing observations: it multiplies the frozen assay timeout by the exact
paired row count, then adds preregistered evaluator and campaign overhead.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import load_json_object
from .contract import ContractError, TaskUnit

RUNTIME_PILOT_SCHEMA = "crucible.runtime-pilot.v1"
RUNTIME_SPEC_SCHEMA = "crucible.runtime-budget-spec.v1"
RUNTIME_REPORT_SCHEMA = "crucible.runtime-budget-report.v1"
RUNTIME_METHOD = "opaque-family-block-upper-bootstrap.v1"
RUNTIME_CEILING_METHOD = "contract-timeout-ceiling.v1"
RUNTIME_ACCOUNTING_METHOD = "sum-finalized-simulation-elapsed.v1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_SIMULATIONS = 200_000


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_fields(value: Mapping[str, Any], field: str, required: set[str]) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - required)
    if missing:
        raise ContractError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unknown fields: {', '.join(unknown)}")


def _text(value: object, field: str, *, max_bytes: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result.encode("utf-8")) > max_bytes:
        raise ContractError(f"{field} exceeds {max_bytes} UTF-8 bytes")
    return result


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContractError(f"{field} must be a SHA-256")
    if value == "0" * 64:
        raise ContractError(f"{field} must not be the zero digest")
    return value


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


def _positive_number(value: object, field: str) -> float:
    result = _nonnegative_number(value, field)
    if result == 0.0:
        raise ContractError(f"{field} must be positive")
    return result


def _probability(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a probability in [0.5, 1)")
    result = float(value)
    if not math.isfinite(result) or result < 0.5 or result >= 1.0:
        raise ContractError(f"{field} must be a probability in [0.5, 1)")
    return result


def _resolve_pilot(
    value: object,
    *,
    basis_root: Path,
    expected_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    raw = _text(value, "runtime_audit.pilot_file")
    path = Path(raw).expanduser()
    resolved = (basis_root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        actual_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError(f"runtime_audit.pilot_file cannot be read: {exc}") from exc
    if actual_sha256 != expected_sha256:
        raise ContractError("runtime_audit.pilot_file does not match pilot_sha256")
    return resolved, load_json_object(resolved, "runtime pilot")


def _pilot_block_rates(
    pilot: Mapping[str, Any],
) -> tuple[list[float], dict[str, int]]:
    blocks = pilot.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ContractError("runtime pilot blocks must be a non-empty list")

    rates: list[float] = []
    counts = {
        "block_count": len(blocks),
        "usable_block_count": 0,
        "complete_sample_count": 0,
        "semantic_timeout_sample_count": 0,
        "infrastructure_sample_count_excluded": 0,
    }
    for block_index, block in enumerate(blocks):
        field = f"runtime pilot blocks[{block_index}]"
        if not isinstance(block, Mapping):
            raise ContractError(f"{field} must be an object")
        _require_fields(block, field, {"samples"})
        samples = block.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ContractError(f"{field}.samples must be a non-empty list")
        semantic_seconds: list[float] = []
        for sample_index, sample in enumerate(samples):
            sample_field = f"{field}.samples[{sample_index}]"
            if not isinstance(sample, Mapping):
                raise ContractError(f"{sample_field} must be an object")
            _require_fields(sample, sample_field, {"outcome", "wall_seconds"})
            outcome = _text(sample.get("outcome"), f"{sample_field}.outcome", max_bytes=50)
            seconds = _positive_number(sample.get("wall_seconds"), f"{sample_field}.wall_seconds")
            if outcome == "infrastructure_failure":
                counts["infrastructure_sample_count_excluded"] += 1
                continue
            if outcome == "complete":
                counts["complete_sample_count"] += 1
            elif outcome == "semantic_timeout":
                counts["semantic_timeout_sample_count"] += 1
            else:
                raise ContractError(
                    f"{sample_field}.outcome must be complete, semantic_timeout, "
                    "or infrastructure_failure"
                )
            semantic_seconds.append(seconds)
        if semantic_seconds:
            counts["usable_block_count"] += 1
            # Wall admission is a capacity question, not an estimate of mean
            # latency. Preserve each opaque block's slowest semantic row, then
            # bootstrap those block-level upper rates across the target design.
            rates.append(max(semantic_seconds))
    return rates, counts


def _nearest_rank(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _wall_admission(
    *,
    required_experiment_wall_seconds: int,
    campaign_overhead_seconds: float,
    configured_experiment_wall_seconds: float,
    configured_campaign_wall_seconds: float | None,
) -> tuple[dict[str, Any], bool]:
    required_campaign_wall_seconds = math.ceil(
        required_experiment_wall_seconds + campaign_overhead_seconds
    )
    configured_experiment = _positive_number(
        configured_experiment_wall_seconds,
        "configured_experiment_wall_seconds",
    )
    configured_campaign = (
        None
        if configured_campaign_wall_seconds is None
        else _positive_number(
            configured_campaign_wall_seconds,
            "configured_campaign_wall_seconds",
        )
    )
    experiment_passes = configured_experiment >= required_experiment_wall_seconds
    campaign_passes = (
        configured_campaign is None or configured_campaign >= required_campaign_wall_seconds
    )
    return (
        {
            "required_experiment_wall_seconds": required_experiment_wall_seconds,
            "configured_experiment_wall_seconds": configured_experiment,
            "experiment_passes": experiment_passes,
            "required_campaign_wall_seconds": required_campaign_wall_seconds,
            "configured_campaign_wall_seconds": configured_campaign,
            "campaign_passes": campaign_passes,
        },
        experiment_passes and campaign_passes,
    )


def audit_runtime_budget(
    *,
    tasks: Sequence[TaskUnit],
    trials_per_task: int,
    evaluator_sha256: str,
    harness_sha256: str,
    agent_route: str,
    user_route: str,
    assay_config: Mapping[str, Any],
    configured_experiment_wall_seconds: float,
    configured_campaign_wall_seconds: float | None,
    specification: Mapping[str, Any],
    basis_root: Path,
) -> dict[str, Any]:
    """Derive and admit a wall envelope for one exact paired design."""

    if specification.get("schema") != RUNTIME_SPEC_SCHEMA:
        raise ContractError(f"runtime_audit.schema must be {RUNTIME_SPEC_SCHEMA!r}")
    if not tasks:
        raise ContractError("runtime audit requires at least one task")
    if trials_per_task <= 0:
        raise ContractError("runtime audit trials_per_task must be positive")
    evaluator_digest = _sha256(evaluator_sha256, "runtime audit evaluator_sha256")
    harness_digest = _sha256(harness_sha256, "runtime audit harness_sha256")
    assay_config_sha256 = _canonical_hash(assay_config)
    bindings = {
        "evaluator_sha256": evaluator_digest,
        "harness_sha256": harness_digest,
        "assay_config_sha256": assay_config_sha256,
        "agent_route": _text(agent_route, "runtime audit agent_route"),
        "user_route": _text(user_route, "runtime audit user_route"),
    }
    family_task_counts: dict[str, int] = {}
    for task in tasks:
        family_task_counts[task.family_id] = family_task_counts.get(task.family_id, 0) + 1
    ordered_counts = tuple(sorted(family_task_counts.values()))
    rows_per_task = 2 * trials_per_task
    paired_row_count = len(tasks) * rows_per_task
    design = {
        "task_count": len(tasks),
        "family_count": len(ordered_counts),
        "family_task_counts": list(ordered_counts),
        "trials_per_task": trials_per_task,
        "paired_row_count": paired_row_count,
    }
    mode = specification.get("mode", "pilot_bootstrap")
    if mode == "contract_ceiling":
        _require_fields(
            specification,
            "runtime_audit",
            {
                "campaign_overhead_seconds",
                "experiment_overhead_seconds",
                "headroom_ratio",
                "mode",
                "schema",
                "source",
            },
        )
        source = _text(specification.get("source"), "runtime_audit.source")
        headroom = _nonnegative_number(
            specification.get("headroom_ratio"),
            "runtime_audit.headroom_ratio",
        )
        if headroom > 10.0:
            raise ContractError("runtime_audit.headroom_ratio must not exceed 10")
        experiment_overhead = _nonnegative_number(
            specification.get("experiment_overhead_seconds"),
            "runtime_audit.experiment_overhead_seconds",
        )
        campaign_overhead = _nonnegative_number(
            specification.get("campaign_overhead_seconds"),
            "runtime_audit.campaign_overhead_seconds",
        )
        timeout_seconds = _positive_number(
            assay_config.get("timeout"),
            "assay_config.timeout",
        )
        paired_row_ceiling = paired_row_count * timeout_seconds
        required_experiment_wall = math.ceil(
            (paired_row_ceiling + experiment_overhead) * (1.0 + headroom)
        )
        admission, passes = _wall_admission(
            required_experiment_wall_seconds=required_experiment_wall,
            campaign_overhead_seconds=campaign_overhead,
            configured_experiment_wall_seconds=configured_experiment_wall_seconds,
            configured_campaign_wall_seconds=configured_campaign_wall_seconds,
        )
        ceiling_payload: dict[str, Any] = {
            "schema": RUNTIME_REPORT_SCHEMA,
            "method": RUNTIME_CEILING_METHOD,
            "scope": "paired_baseline_candidate_wall_envelope",
            "source": source,
            "bindings": bindings,
            "design": design,
            "ceiling": {
                "timeout_seconds_per_row": timeout_seconds,
                "paired_row_ceiling_seconds": paired_row_ceiling,
                "experiment_overhead_seconds": experiment_overhead,
                "headroom_ratio": headroom,
                "campaign_overhead_seconds": campaign_overhead,
            },
            "admission": admission,
            "passes": passes,
        }
        return {
            **ceiling_payload,
            "runtime_audit_id": _canonical_hash(ceiling_payload),
        }
    if mode != "pilot_bootstrap":
        raise ContractError("runtime_audit.mode must be contract_ceiling or pilot_bootstrap")

    pilot_fields = {
        "admission_quantile",
        "campaign_overhead_seconds",
        "experiment_overhead_seconds",
        "headroom_ratio",
        "minimum_usable_blocks",
        "pilot_file",
        "pilot_sha256",
        "schema",
        "seed",
        "simulations",
        "source",
    }
    if "mode" in specification:
        pilot_fields.add("mode")
    _require_fields(
        specification,
        "runtime_audit",
        pilot_fields,
    )
    simulations = _positive_int(specification.get("simulations"), "runtime_audit.simulations")
    if simulations < 1_000 or simulations > _MAX_SIMULATIONS:
        raise ContractError(
            f"runtime_audit.simulations must be between 1000 and {_MAX_SIMULATIONS}"
        )
    seed = specification.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ContractError("runtime_audit.seed must be a non-negative integer")
    quantile = _probability(
        specification.get("admission_quantile"),
        "runtime_audit.admission_quantile",
    )
    headroom = _nonnegative_number(
        specification.get("headroom_ratio"),
        "runtime_audit.headroom_ratio",
    )
    if headroom > 10.0:
        raise ContractError("runtime_audit.headroom_ratio must not exceed 10")
    experiment_overhead = _nonnegative_number(
        specification.get("experiment_overhead_seconds"),
        "runtime_audit.experiment_overhead_seconds",
    )
    campaign_overhead = _nonnegative_number(
        specification.get("campaign_overhead_seconds"),
        "runtime_audit.campaign_overhead_seconds",
    )
    minimum_blocks = _positive_int(
        specification.get("minimum_usable_blocks"),
        "runtime_audit.minimum_usable_blocks",
    )
    source = _text(specification.get("source"), "runtime_audit.source")
    pilot_sha256 = _sha256(specification.get("pilot_sha256"), "runtime_audit.pilot_sha256")
    _pilot_path, pilot = _resolve_pilot(
        specification.get("pilot_file"),
        basis_root=basis_root,
        expected_sha256=pilot_sha256,
    )

    _require_fields(
        pilot,
        "runtime pilot",
        {
            "accounting_method",
            "agent_route",
            "assay_config_sha256",
            "blocks",
            "evaluator_sha256",
            "harness_sha256",
            "schema",
            "user_route",
        },
    )
    if pilot.get("schema") != RUNTIME_PILOT_SCHEMA:
        raise ContractError(f"runtime pilot schema must be {RUNTIME_PILOT_SCHEMA!r}")
    if pilot.get("accounting_method") != RUNTIME_ACCOUNTING_METHOD:
        raise ContractError(
            f"runtime pilot accounting_method must be {RUNTIME_ACCOUNTING_METHOD!r}"
        )
    for field, expected in bindings.items():
        if pilot.get(field) != expected:
            raise ContractError(f"runtime pilot {field} does not match the prepared plan")

    block_rates, pilot_counts = _pilot_block_rates(pilot)
    if len(block_rates) < minimum_blocks:
        raise ContractError(
            "runtime pilot has fewer usable blocks than minimum_usable_blocks: "
            f"{len(block_rates)} < {minimum_blocks}"
        )

    rng = random.Random(seed)
    totals: list[float] = []
    for _simulation in range(simulations):
        total = 0.0
        for task_count in ordered_counts:
            sampled_seconds_per_row = block_rates[rng.randrange(len(block_rates))]
            total += sampled_seconds_per_row * task_count * rows_per_task
        totals.append(total)

    bootstrap_quantile = _nearest_rank(totals, quantile)
    admitted_experiment_wall = math.ceil(
        (bootstrap_quantile + experiment_overhead) * (1.0 + headroom)
    )
    admission, passes = _wall_admission(
        required_experiment_wall_seconds=admitted_experiment_wall,
        campaign_overhead_seconds=campaign_overhead,
        configured_experiment_wall_seconds=configured_experiment_wall_seconds,
        configured_campaign_wall_seconds=configured_campaign_wall_seconds,
    )

    payload: dict[str, Any] = {
        "schema": RUNTIME_REPORT_SCHEMA,
        "method": RUNTIME_METHOD,
        "scope": "paired_baseline_candidate_wall_envelope",
        "source": source,
        "pilot_sha256": pilot_sha256,
        "bindings": bindings,
        "design": design,
        "pilot": pilot_counts,
        "bootstrap": {
            "simulations": simulations,
            "seed": seed,
            "admission_quantile": quantile,
            "mean_seconds": math.fsum(totals) / len(totals),
            "quantile_seconds": bootstrap_quantile,
            "maximum_seconds": max(totals),
            "experiment_overhead_seconds": experiment_overhead,
            "headroom_ratio": headroom,
            "campaign_overhead_seconds": campaign_overhead,
        },
        "admission": admission,
        "passes": passes,
    }
    return {**payload, "runtime_audit_id": _canonical_hash(payload)}


__all__ = [
    "RUNTIME_ACCOUNTING_METHOD",
    "RUNTIME_CEILING_METHOD",
    "RUNTIME_METHOD",
    "RUNTIME_PILOT_SCHEMA",
    "RUNTIME_REPORT_SCHEMA",
    "RUNTIME_SPEC_SCHEMA",
    "audit_runtime_budget",
]
