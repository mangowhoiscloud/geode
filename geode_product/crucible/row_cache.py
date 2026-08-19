"""Hash-bound row cache: salvage completed tau2 simulations across relaunches.

The r23 incident: quota died at pair 7 of 12 and the 18 completed arm-task
executions were discarded wholesale, because the kernel (correctly) refuses
partial verdicts and (until now) had no way to prove that a previously
measured row belongs to the identical experiment. This module is the
checkpoint sidecar the kernel's boundary rules already anticipated:

    "Resume remains disabled until a checkpoint sidecar can prove the same
    contract, revision, evaluator, harness, and task-pack hashes before
    loading any row."

A cached row is keyed and stored with the full measurement identity —
revision SHA, evaluator/harness/task-pack/assay-config SHA-256 — plus a
content hash of the simulation payload. On relaunch the evaluator reuses only
rows whose stored identity equals the *current* contract's identity and whose
payload matches its stored hash; anything else is ignored, never repaired.
Verdict discipline is untouched: scoring still requires exact full coverage,
so the cache changes what a rerun costs, not what it proves. tau2 finalizes
each simulation into ``results.json`` incrementally (its checkpoint file), so
an interrupted arm still yields its completed rows for harvest; in-flight
tasks are never persisted by tau2 and therefore can never be salvaged.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError, ExperimentContract
from .evidence import expected_pairs
from .verifiers.tau2 import (
    SNAPSHOT_SCHEMA,
    TAU2_ADAPTER,
    tau2_has_infrastructure_contamination,
)

ROW_SCHEMA = "crucible.cached-row.v1"
CONTEXT_SCHEMA = "crucible.cached-arm-context.v2"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _identity(contract: ExperimentContract, revision_sha: str) -> dict[str, str]:
    return {
        "revision_sha": revision_sha,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
    }


def _shard_dir(cache_root: Path, contract: ExperimentContract, revision_sha: str) -> Path:
    return cache_root / _canonical_sha256(_identity(contract, revision_sha))


def _row_filename(task_id: str, trial: int) -> str:
    safe = _UNSAFE.sub("_", task_id)[:160]
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"{safe}__{digest}__{trial}.json"


def _cacheable_simulation(row: Mapping[str, Any]) -> bool:
    """Return whether one finalized row is safe to reuse as a measurement."""

    reason = str(row.get("termination_reason") or "").strip()
    if not reason:
        return False
    try:
        if TAU2_ADAPTER.classify_termination(reason) != "semantic":
            return False
        return not tau2_has_infrastructure_contamination({"simulations": [row]})
    except ContractError:
        return False


def _completed_simulations(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only finalized semantic rows that may be reused as measurements.

    Tau2 writes ``infrastructure_error`` placeholders for the active and
    unstarted tail when a batch aborts.  Presence of ``termination_reason`` is
    therefore not sufficient evidence that a task ran.  Reuse the adapter's
    frozen termination taxonomy so the cache cannot turn r23-style quota
    placeholders into completed rows.
    """

    simulations = raw.get("simulations")
    if not isinstance(simulations, list):
        return []
    rows: list[Mapping[str, Any]] = []
    for row in simulations:
        if not isinstance(row, Mapping):
            continue
        if not isinstance(row.get("task_id"), (str, int)):
            continue
        if isinstance(row.get("trial"), bool) or not isinstance(row.get("trial"), int):
            continue
        if not _cacheable_simulation(row):
            continue
        rows.append(row)
    return rows


def _context_payload(raw_results: Mapping[str, Any]) -> dict[str, Any] | None:
    info = raw_results.get("info")
    tasks = raw_results.get("tasks")
    if not isinstance(info, Mapping) or not isinstance(tasks, list):
        return None
    return {
        "info": json.loads(json.dumps(info)),
        "tasks": json.loads(json.dumps(tasks)),
    }


def harvest_arm_rows(
    cache_root: Path,
    contract: ExperimentContract,
    *,
    revision_sha: str,
    raw_results: Mapping[str, Any],
) -> int:
    """Store every finalized simulation from ``raw_results`` (partial files welcome).

    Also stores one arm-context blob (the run's ``info`` and ``tasks`` sections)
    the first time an identity is seen, so a later full-cache synthesis or a
    subset-merge can rebuild a results file that carries the frozen task
    objects and run metadata the tau2 verifier checks.
    """
    shard = _shard_dir(cache_root, contract, revision_sha)
    shard.mkdir(parents=True, exist_ok=True)
    identity = _identity(contract, revision_sha)
    context_path = shard / "context.json"
    context_payload = _context_payload(raw_results)
    if not context_path.exists() and context_payload is not None:
        write_exclusive_json(
            context_path,
            {
                "schema": CONTEXT_SCHEMA,
                **identity,
                "context_sha256": _canonical_sha256(context_payload),
                **context_payload,
            },
        )
    stored = 0
    for row in _completed_simulations(raw_results):
        row_path = shard / _row_filename(str(row["task_id"]), int(row["trial"]))
        if row_path.exists():
            continue
        payload = json.loads(json.dumps(row))
        write_exclusive_json(
            row_path,
            {
                "schema": ROW_SCHEMA,
                **identity,
                "task_id": str(row["task_id"]),
                "trial": int(row["trial"]),
                "row_sha256": _canonical_sha256(payload),
                "simulation": payload,
            },
        )
        stored += 1
    return stored


def _verified_row(path: Path, identity: Mapping[str, str]) -> Mapping[str, Any] | None:
    try:
        stored = load_json_object(path, "cached row", max_bytes=64 * 1024 * 1024)
    except (ContractError, OSError):
        return None
    if stored.get("schema") != ROW_SCHEMA:
        return None
    for field, value in identity.items():
        if stored.get(field) != value:
            return None
    simulation = stored.get("simulation")
    if not isinstance(simulation, Mapping):
        return None
    task_id = simulation.get("task_id")
    trial = simulation.get("trial")
    if not isinstance(task_id, (str, int)) or isinstance(trial, bool) or not isinstance(trial, int):
        return None
    if stored.get("task_id") != str(task_id) or stored.get("trial") != trial:
        return None
    if stored.get("row_sha256") != _canonical_sha256(json.loads(json.dumps(simulation))):
        return None
    if not _cacheable_simulation(simulation):
        return None
    return simulation


def cached_rows(
    cache_root: Path,
    contract: ExperimentContract,
    *,
    revision_sha: str,
) -> dict[tuple[str, int], Mapping[str, Any]]:
    """All identity-proven rows for this contract arm, keyed by (task_id, trial)."""
    shard = _shard_dir(cache_root, contract, revision_sha)
    if not shard.is_dir():
        return {}
    identity = _identity(contract, revision_sha)
    rows: dict[tuple[str, int], Mapping[str, Any]] = {}
    for path in sorted(shard.glob("*.json")):
        if path.name == "context.json":
            continue
        simulation = _verified_row(path, identity)
        if simulation is None:
            continue
        rows[(str(simulation["task_id"]), int(simulation["trial"]))] = simulation
    return rows


def cached_context(
    cache_root: Path,
    contract: ExperimentContract,
    *,
    revision_sha: str,
) -> Mapping[str, Any] | None:
    path = _shard_dir(cache_root, contract, revision_sha) / "context.json"
    if not path.is_file():
        return None
    try:
        stored = load_json_object(path, "cached arm context", max_bytes=64 * 1024 * 1024)
    except (ContractError, OSError):
        return None
    if stored.get("schema") != CONTEXT_SCHEMA:
        return None
    for field, value in _identity(contract, revision_sha).items():
        if stored.get(field) != value:
            return None
    context_payload = _context_payload(stored)
    if context_payload is None:
        return None
    if stored.get("context_sha256") != _canonical_sha256(context_payload):
        return None
    return stored


def merge_results(
    context: Mapping[str, Any],
    rows: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild a tau2 results payload from a context blob plus cached/fresh rows."""
    task_order = {
        str(task.get("id")): index
        for index, task in enumerate(context["tasks"])
        if isinstance(task, Mapping) and task.get("id") is not None
    }
    ordered = [
        rows[key]
        for key in sorted(
            rows,
            key=lambda pair: (task_order.get(pair[0], len(task_order)), pair[1], pair[0]),
        )
    ]
    return {
        "info": json.loads(json.dumps(context["info"])),
        "tasks": json.loads(json.dumps(context["tasks"])),
        "simulations": [json.loads(json.dumps(row)) for row in ordered],
    }


def selected_expected_rows(
    contract: ExperimentContract,
    rows: Mapping[tuple[str, int], Mapping[str, Any]],
) -> dict[tuple[str, int], Mapping[str, Any]]:
    """Restrict cached rows to exactly the contract's expected pairs."""
    return {pair: rows[pair] for pair in expected_pairs(contract) if pair in rows}


def missing_task_ids(
    contract: ExperimentContract,
    rows: Mapping[tuple[str, int], Mapping[str, Any]],
) -> list[str]:
    """Task IDs with any uncached trial, in frozen execution order."""
    missing: list[str] = []
    for task_id in contract.task_ids:
        if any((task_id, trial) not in rows for trial in range(contract.trials_per_task)):
            missing.append(task_id)
    return missing


def synthesized_snapshot(
    contract: ExperimentContract,
    *,
    arm: Literal["baseline", "candidate"],
    raw_sha256: str,
) -> dict[str, Any]:
    """Snapshot payload for a results file the evaluator rebuilt from cache.

    Field-for-field what the tau2 runner writes and the verifier checks; the
    frozen evaluator is the trusted party either way, so a snapshot it signs
    over merged bytes carries the same authority as one signed by its own
    subprocess.
    """
    revision_field = "baseline_sha" if arm == "baseline" else "candidate_sha"
    revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    return {
        "schema": SNAPSHOT_SCHEMA,
        "experiment_contract_id": contract.contract_id,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_pack_sha256": contract.task_pack_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
        "arm": arm,
        revision_field: revision,
        "raw_artifact_sha256": raw_sha256,
        "assay_config": json.loads(json.dumps(contract.assay_config)),
        "execution_status": "complete",
        "row_cache": {"schema": ROW_SCHEMA, "synthesized": True},
    }
