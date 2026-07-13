"""Hash-bound runtime receipts for shared-deadline Crucible evaluations."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError, ExperimentContract
from .runtime_identity import (
    RUNTIME_ARM_WALL_POLICY,
    canonical_runtime_hash,
    runtime_regime_id,
)

RUNTIME_RECEIPT_SCHEMA = "crucible.runtime-receipt.v1"

RuntimeStatus = Literal[
    "complete",
    "right_censored",
    "infrastructure_invalid",
    "operator_invalid",
]
ArmOutcome = Literal["complete", "skipped", "screened", "invalid", "right_censored"]
_RUNTIME_STATUSES = {
    "complete",
    "right_censored",
    "infrastructure_invalid",
    "operator_invalid",
}
_ARM_OUTCOMES = {"complete", "skipped", "screened", "invalid", "right_censored"}
_UNMEASURED_CLEANUP_SCOPES = [
    "outer_evaluator_process_startup_and_request_parse",
    "outer_supervisor_process_reap",
    "ledger_and_ref_finalization",
]


def _require_fields(value: Mapping[str, Any], field: str, required: set[str]) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - required)
    if missing:
        raise ContractError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"{field} has unknown fields: {', '.join(unknown)}")


def _bounded_text(value: object, field: str, *, max_bytes: int = 100) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result.encode("utf-8")) > max_bytes:
        raise ContractError(f"{field} exceeds {max_bytes} UTF-8 bytes")
    return result


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field} must be a non-negative finite number")
    result = float(value)
    if result < 0.0 or not math.isfinite(result):
        raise ContractError(f"{field} must be a non-negative finite number")
    return result


def _finite_positive(value: object, field: str) -> float:
    result = _finite_nonnegative(value, field)
    if result == 0.0:
        raise ContractError(f"{field} must be positive")
    return result


@dataclass(frozen=True)
class ArmClock:
    arm: Literal["baseline", "candidate"]
    allocated_wall_seconds: float
    started_seconds: float


class SharedRuntimeDeadline:
    """One monotonic deadline whose unused baseline budget flows to candidate."""

    def __init__(
        self,
        contract: ExperimentContract,
        budget_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(budget_seconds) or budget_seconds <= 0.0:
            raise ContractError("runtime deadline budget_seconds must be positive and finite")
        self.contract = contract
        self.budget_seconds = float(budget_seconds)
        self._clock = clock
        self._started = clock()
        self._deadline = self._started + self.budget_seconds
        self._arms: list[dict[str, Any]] = []
        self._cleanup: list[dict[str, Any]] = []
        self._active_arm: ArmClock | None = None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started)

    def remaining_seconds(self) -> float:
        remaining = self._deadline - self._clock()
        if remaining <= 0.0:
            raise TimeoutError("shared evaluation deadline exhausted")
        return remaining

    def begin_arm(self, arm: Literal["baseline", "candidate"]) -> ArmClock:
        if self._active_arm is not None:
            raise ContractError("runtime receipt already has an active arm")
        expected = "baseline" if not self._arms else "candidate"
        if len(self._arms) >= 2 or arm != expected:
            raise ContractError(f"runtime arm order requires {expected!r}")
        started = self._clock()
        remaining = self._deadline - started
        if remaining <= 0.0:
            raise TimeoutError("shared evaluation deadline exhausted")
        timer = ArmClock(
            arm=arm,
            allocated_wall_seconds=remaining,
            started_seconds=started,
        )
        self._active_arm = timer
        return timer

    def finish_arm(self, timer: ArmClock, outcome: ArmOutcome) -> None:
        if self._active_arm != timer:
            raise ContractError("runtime arm timer is not active")
        self._arms.append(
            {
                "arm": timer.arm,
                "allocated_wall_seconds": timer.allocated_wall_seconds,
                "observed_wall_seconds": max(0.0, self._clock() - timer.started_seconds),
                "outcome": outcome,
            }
        )
        self._active_arm = None

    def record_synthetic_arm(
        self,
        arm: Literal["baseline", "candidate"],
        outcome: Literal["skipped", "screened"],
    ) -> None:
        if self._active_arm is not None:
            raise ContractError("cannot synthesize an arm while another arm is active")
        expected = "baseline" if not self._arms else "candidate"
        if len(self._arms) >= 2 or arm != expected:
            raise ContractError(f"runtime arm order requires {expected!r}")
        self._arms.append(
            {
                "arm": arm,
                "allocated_wall_seconds": 0.0,
                "observed_wall_seconds": 0.0,
                "outcome": outcome,
            }
        )

    def record_cleanup(self, name: str, started_seconds: float) -> None:
        if not name or len(name.encode("utf-8")) > 100:
            raise ContractError("runtime cleanup phase name must be bounded and non-empty")
        self._cleanup.append(
            {
                "name": name,
                "observed_wall_seconds": max(0.0, self._clock() - started_seconds),
            }
        )

    def payload(
        self,
        status: RuntimeStatus,
        *,
        censoring_reason: str | None = None,
    ) -> dict[str, Any]:
        if self._active_arm is not None:
            raise ContractError("cannot finalize a runtime receipt with an active arm")
        observed = self.elapsed_seconds
        if status == "complete" and observed > self.budget_seconds + 1e-9:
            raise ContractError("complete runtime receipt exceeds its configured experiment wall")
        observation: dict[str, Any] = {
            "status": status,
            "observed_wall_seconds": observed,
        }
        if status == "right_censored":
            if not censoring_reason:
                raise ContractError("right-censored runtime receipt requires a reason")
            observation["censoring"] = {
                "kind": "right",
                "limit_seconds": self.budget_seconds,
                "reason": censoring_reason,
            }
        elif censoring_reason is not None:
            raise ContractError("only a right-censored runtime receipt may carry censoring")

        cleanup_total = math.fsum(float(item["observed_wall_seconds"]) for item in self._cleanup)
        return {
            "schema": RUNTIME_RECEIPT_SCHEMA,
            "contract_id": self.contract.contract_id,
            "runtime_regime_id": runtime_regime_id(
                self.contract,
                experiment_wall_seconds=self.budget_seconds,
            ),
            "wall_policy": RUNTIME_ARM_WALL_POLICY,
            "configured_experiment_wall_seconds": self.budget_seconds,
            "observation": observation,
            "arms": list(self._arms),
            "cleanup": {
                "measured_scope": "evaluator_inner",
                "phases": list(self._cleanup),
                "observed_wall_seconds": cleanup_total,
                "unmeasured_scopes": [
                    *_UNMEASURED_CLEANUP_SCOPES,
                ],
            },
        }

    def write(
        self,
        path: Path,
        status: RuntimeStatus,
        *,
        censoring_reason: str | None = None,
    ) -> dict[str, Any]:
        payload = self.payload(status, censoring_reason=censoring_reason)
        receipt = {**payload, "runtime_receipt_id": canonical_runtime_hash(payload)}
        write_exclusive_json(path, receipt)
        return receipt


def load_runtime_receipt(
    path: Path,
    *,
    contract: ExperimentContract,
) -> dict[str, Any]:
    """Validate a contained receipt before trusting its timing classification."""

    row = load_json_object(path, "runtime receipt", max_bytes=1024 * 1024)
    _require_fields(
        row,
        "runtime receipt",
        {
            "arms",
            "cleanup",
            "configured_experiment_wall_seconds",
            "contract_id",
            "observation",
            "runtime_receipt_id",
            "runtime_regime_id",
            "schema",
            "wall_policy",
        },
    )
    supplied_id = row.get("runtime_receipt_id")
    payload = {key: value for key, value in row.items() if key != "runtime_receipt_id"}
    if row.get("schema") != RUNTIME_RECEIPT_SCHEMA:
        raise ContractError(f"runtime receipt schema must be {RUNTIME_RECEIPT_SCHEMA!r}")
    if supplied_id != canonical_runtime_hash(payload):
        raise ContractError("runtime_receipt_id does not match the canonical receipt")
    if row.get("contract_id") != contract.contract_id:
        raise ContractError("runtime receipt contract_id does not match the evaluation")
    if row.get("wall_policy") != RUNTIME_ARM_WALL_POLICY:
        raise ContractError("runtime receipt wall policy is unsupported")
    configured_wall = _finite_positive(
        row.get("configured_experiment_wall_seconds"),
        "runtime receipt configured_experiment_wall_seconds",
    )
    if configured_wall > contract.budget.max_wall_seconds + 1e-9:
        raise ContractError("runtime receipt configured wall exceeds the frozen contract wall")
    if row.get("runtime_regime_id") != runtime_regime_id(
        contract,
        experiment_wall_seconds=configured_wall,
    ):
        raise ContractError("runtime receipt regime does not match the effective evaluation wall")
    observation = row.get("observation")
    if not isinstance(observation, Mapping):
        raise ContractError("runtime receipt observation must be an object")
    status = observation.get("status")
    if status not in _RUNTIME_STATUSES:
        raise ContractError("runtime receipt observation.status is invalid")
    expected_observation_fields = {"status", "observed_wall_seconds"}
    if status == "right_censored":
        expected_observation_fields.add("censoring")
    _require_fields(observation, "runtime receipt observation", expected_observation_fields)
    observed_wall = _finite_nonnegative(
        observation.get("observed_wall_seconds"),
        "runtime receipt observation.observed_wall_seconds",
    )
    if status == "complete" and observed_wall > configured_wall + 1e-9:
        raise ContractError("complete runtime receipt exceeds its configured experiment wall")
    if status == "right_censored":
        censoring = observation.get("censoring")
        if not isinstance(censoring, Mapping):
            raise ContractError("runtime receipt observation.censoring must be an object")
        _require_fields(
            censoring,
            "runtime receipt observation.censoring",
            {"kind", "limit_seconds", "reason"},
        )
        if censoring.get("kind") != "right":
            raise ContractError("runtime receipt censoring.kind must be 'right'")
        censoring_limit = _finite_positive(
            censoring.get("limit_seconds"),
            "runtime receipt observation.censoring.limit_seconds",
        )
        if not math.isclose(censoring_limit, configured_wall, rel_tol=0.0, abs_tol=1e-9):
            raise ContractError("runtime receipt censoring limit must equal configured wall")
        _bounded_text(
            censoring.get("reason"),
            "runtime receipt observation.censoring.reason",
        )

    arms = row.get("arms")
    if not isinstance(arms, list) or len(arms) > 2:
        raise ContractError("runtime receipt arms must be a list with at most two entries")
    observed_components: list[float] = []
    for index, arm in enumerate(arms):
        field = f"runtime receipt arms[{index}]"
        if not isinstance(arm, Mapping):
            raise ContractError(f"{field} must be an object")
        _require_fields(
            arm,
            field,
            {"allocated_wall_seconds", "arm", "observed_wall_seconds", "outcome"},
        )
        expected_arm = "baseline" if index == 0 else "candidate"
        if arm.get("arm") != expected_arm:
            raise ContractError("runtime receipt arms are not in baseline/candidate order")
        outcome = arm.get("outcome")
        if outcome not in _ARM_OUTCOMES:
            raise ContractError(f"{field}.outcome is invalid")
        allocated = _finite_nonnegative(
            arm.get("allocated_wall_seconds"),
            f"{field}.allocated_wall_seconds",
        )
        arm_observed = _finite_nonnegative(
            arm.get("observed_wall_seconds"),
            f"{field}.observed_wall_seconds",
        )
        if outcome in {"skipped", "screened"} and (allocated != 0.0 or arm_observed != 0.0):
            raise ContractError(f"{field} synthetic outcomes must have zero timing")
        if outcome not in {"skipped", "screened"} and allocated <= 0.0:
            raise ContractError(f"{field} measured outcomes require positive allocation")
        if allocated > configured_wall + 1e-9:
            raise ContractError(f"{field}.allocated_wall_seconds exceeds configured wall")
        observed_components.append(arm_observed)

    outcomes = [arm.get("outcome") for arm in arms if isinstance(arm, Mapping)]
    if len(arms) == 2:
        baseline_allocation = float(arms[0]["allocated_wall_seconds"])
        baseline_observed = float(arms[0]["observed_wall_seconds"])
        candidate_allocation = float(arms[1]["allocated_wall_seconds"])
        if candidate_allocation > max(0.0, baseline_allocation - baseline_observed) + 1e-9:
            raise ContractError(
                "runtime receipt candidate allocation exceeds the shared baseline remainder"
            )
    if status == "complete" and (
        len(outcomes) != 2
        or outcomes[0] != "complete"
        or outcomes[1] not in {"complete", "screened"}
    ):
        raise ContractError("complete runtime receipt requires completed baseline and candidate")
    if status == "infrastructure_invalid" and not any(
        outcome in {"invalid", "skipped"} for outcome in outcomes
    ):
        raise ContractError("infrastructure-invalid runtime receipt lacks an invalid arm")
    if status == "right_censored" and len(outcomes) == 2 and "right_censored" not in outcomes:
        raise ContractError("right-censored runtime receipt lacks a censored arm")

    cleanup = row.get("cleanup")
    if not isinstance(cleanup, Mapping):
        raise ContractError("runtime receipt cleanup must be an object")
    _require_fields(
        cleanup,
        "runtime receipt cleanup",
        {"measured_scope", "observed_wall_seconds", "phases", "unmeasured_scopes"},
    )
    if cleanup.get("measured_scope") != "evaluator_inner":
        raise ContractError("runtime receipt cleanup.measured_scope is unsupported")
    if cleanup.get("unmeasured_scopes") != _UNMEASURED_CLEANUP_SCOPES:
        raise ContractError("runtime receipt cleanup.unmeasured_scopes is unsupported")
    phases = cleanup.get("phases")
    if not isinstance(phases, list):
        raise ContractError("runtime receipt cleanup.phases must be a list")
    cleanup_values: list[float] = []
    for index, phase in enumerate(phases):
        field = f"runtime receipt cleanup.phases[{index}]"
        if not isinstance(phase, Mapping):
            raise ContractError(f"{field} must be an object")
        _require_fields(phase, field, {"name", "observed_wall_seconds"})
        _bounded_text(phase.get("name"), f"{field}.name")
        cleanup_values.append(
            _finite_nonnegative(
                phase.get("observed_wall_seconds"),
                f"{field}.observed_wall_seconds",
            )
        )
    cleanup_total = _finite_nonnegative(
        cleanup.get("observed_wall_seconds"),
        "runtime receipt cleanup.observed_wall_seconds",
    )
    if not math.isclose(cleanup_total, math.fsum(cleanup_values), rel_tol=0.0, abs_tol=1e-9):
        raise ContractError("runtime receipt cleanup total does not match its phases")
    accounted_wall = math.fsum([*observed_components, cleanup_total])
    if observed_wall + 1e-9 < accounted_wall:
        raise ContractError("runtime receipt observation is shorter than arm and cleanup timings")
    return row


__all__ = [
    "RUNTIME_RECEIPT_SCHEMA",
    "SharedRuntimeDeadline",
    "load_runtime_receipt",
]
