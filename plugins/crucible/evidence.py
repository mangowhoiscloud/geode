"""Immutable, assay-neutral evidence emitted after executable verification."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .artifacts import load_json_object
from .contract import ContractError, ExperimentContract

EVIDENCE_SCHEMA = "crucible.evidence.v2"


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field} must be an object")
    return value


def _keys(
    value: Mapping[str, Any],
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise ContractError(f"{field} is missing keys: {', '.join(missing)}")
    if extra:
        raise ContractError(f"{field} has unknown keys: {', '.join(extra)}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ContractError(f"{field} must be a 64-character lowercase SHA-256")
    return text


def _git_sha(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise ContractError(f"{field} must be a full 40-character lowercase git SHA")
    return text


def _non_negative_float(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ContractError(f"{field} must be a finite number greater than or equal to zero")
    return float(value)


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{field} must be a finite number")
    return float(value)


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field} must be an integer greater than or equal to zero")
    return value


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ResourceUsage:
    """Whole-arm resource totals supplied by the execution substrate."""

    wall_seconds: float
    calls: int
    tokens: int
    cost_usd: float

    @classmethod
    def from_mapping(cls, value: object) -> ResourceUsage:
        row = _mapping(value, "usage")
        _keys(
            row,
            field="usage",
            required={"calls", "cost_usd", "tokens", "wall_seconds"},
        )
        return cls(
            wall_seconds=_non_negative_float(row["wall_seconds"], "usage.wall_seconds"),
            calls=_non_negative_int(row["calls"], "usage.calls"),
            tokens=_non_negative_int(row["tokens"], "usage.tokens"),
            cost_usd=_non_negative_float(row["cost_usd"], "usage.cost_usd"),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "wall_seconds": self.wall_seconds,
            "calls": self.calls,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
        }

    def __add__(self, other: ResourceUsage) -> ResourceUsage:
        return ResourceUsage(
            wall_seconds=self.wall_seconds + other.wall_seconds,
            calls=self.calls + other.calls,
            tokens=self.tokens + other.tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True)
class TaskEvidence:
    """One task/trial result; semantic failures remain completed metric rows."""

    task_id: str
    trial: int
    status: Literal["completed", "infrastructure_error"]
    metrics: tuple[tuple[str, float], ...]
    checks: tuple[tuple[str, bool], ...]
    termination_reason: str
    failure_class: str | None = None

    @classmethod
    def from_mapping(cls, value: object, *, index: int) -> TaskEvidence:
        field = f"rows[{index}]"
        row = _mapping(value, field)
        _keys(
            row,
            field=field,
            required={
                "checks",
                "metrics",
                "status",
                "task_id",
                "termination_reason",
                "trial",
            },
            optional={"failure_class"},
        )
        status = _text(row["status"], f"{field}.status")
        if status not in {"completed", "infrastructure_error"}:
            raise ContractError(f"{field}.status must be 'completed' or 'infrastructure_error'")
        metrics_row = _mapping(row["metrics"], f"{field}.metrics")
        metrics: list[tuple[str, float]] = []
        for name, raw_value in metrics_row.items():
            metric = _text(name, f"{field}.metrics key")
            value_number = _finite_float(raw_value, f"{field}.metrics.{metric}")
            metrics.append((metric, value_number))
        if status == "completed" and not metrics:
            raise ContractError(f"{field}.metrics must not be empty for a completed row")

        checks_row = _mapping(row["checks"], f"{field}.checks")
        checks: list[tuple[str, bool]] = []
        for name, raw_value in checks_row.items():
            check = _text(name, f"{field}.checks key")
            if not isinstance(raw_value, bool):
                raise ContractError(f"{field}.checks.{check} must be a boolean")
            checks.append((check, raw_value))

        failure_raw = row.get("failure_class")
        failure_class = (
            _text(failure_raw, f"{field}.failure_class") if failure_raw is not None else None
        )
        if status == "infrastructure_error" and failure_class is None:
            raise ContractError(f"{field}.failure_class is required for infrastructure errors")
        if status == "completed" and failure_class is not None:
            raise ContractError(f"{field}.failure_class is only valid for infrastructure errors")
        return cls(
            task_id=_text(row["task_id"], f"{field}.task_id"),
            trial=_non_negative_int(row["trial"], f"{field}.trial"),
            status=cast(Literal["completed", "infrastructure_error"], status),
            metrics=tuple(sorted(metrics)),
            checks=tuple(sorted(checks)),
            termination_reason=_text(
                row["termination_reason"],
                f"{field}.termination_reason",
            ),
            failure_class=failure_class,
        )

    @property
    def pair_id(self) -> tuple[str, int]:
        return self.task_id, self.trial

    def metric(self, name: str) -> float | None:
        return dict(self.metrics).get(name)

    def check(self, name: str) -> bool | None:
        return dict(self.checks).get(name)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "trial": self.trial,
            "status": self.status,
            "termination_reason": self.termination_reason,
            "metrics": dict(self.metrics),
            "checks": dict(self.checks),
        }
        if self.failure_class is not None:
            payload["failure_class"] = self.failure_class
        return payload


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Canonical evidence for exactly one frozen experiment arm."""

    contract_id: str
    arm: Literal["baseline", "candidate"]
    revision_sha: str
    evaluator_sha256: str
    harness_sha256: str
    task_layout_sha256: str
    assay_config_sha256: str
    raw_artifact_sha256: str
    execution_status: Literal["complete", "invalid"]
    usage: ResourceUsage
    rows: tuple[TaskEvidence, ...]
    failure_class: str | None = None

    @classmethod
    def from_mapping(cls, value: object) -> EvidenceEnvelope:
        row = _mapping(value, "evidence")
        _keys(
            row,
            field="evidence",
            required={
                "arm",
                "assay_config_sha256",
                "contract_id",
                "evaluator_sha256",
                "execution_status",
                "harness_sha256",
                "raw_artifact_sha256",
                "revision_sha",
                "rows",
                "schema",
                "task_layout_sha256",
                "usage",
            },
            optional={"evidence_id", "failure_class"},
        )
        if row["schema"] != EVIDENCE_SCHEMA:
            raise ContractError(f"evidence.schema must be {EVIDENCE_SCHEMA!r}")
        arm = _text(row["arm"], "evidence.arm")
        if arm not in {"baseline", "candidate"}:
            raise ContractError("evidence.arm must be 'baseline' or 'candidate'")
        execution_status = _text(row["execution_status"], "evidence.execution_status")
        if execution_status not in {"complete", "invalid"}:
            raise ContractError("evidence.execution_status must be 'complete' or 'invalid'")
        raw_rows = row["rows"]
        if not isinstance(raw_rows, list):
            raise ContractError("evidence.rows must be a list")
        rows = tuple(
            TaskEvidence.from_mapping(item, index=index) for index, item in enumerate(raw_rows)
        )
        pair_ids = [item.pair_id for item in rows]
        if len(set(pair_ids)) != len(pair_ids):
            raise ContractError("evidence.rows contain duplicate task/trial pairs")
        failure_raw = row.get("failure_class")
        failure_class = (
            _text(failure_raw, "evidence.failure_class") if failure_raw is not None else None
        )
        if execution_status == "invalid" and failure_class is None:
            raise ContractError("invalid evidence requires evidence.failure_class")
        if execution_status == "complete" and failure_class is not None:
            raise ContractError("complete evidence cannot carry evidence.failure_class")
        evidence = cls(
            contract_id=_sha256(row["contract_id"], "evidence.contract_id"),
            arm=cast(Literal["baseline", "candidate"], arm),
            revision_sha=_git_sha(row["revision_sha"], "evidence.revision_sha"),
            evaluator_sha256=_sha256(row["evaluator_sha256"], "evidence.evaluator_sha256"),
            harness_sha256=_sha256(row["harness_sha256"], "evidence.harness_sha256"),
            task_layout_sha256=_sha256(row["task_layout_sha256"], "evidence.task_layout_sha256"),
            assay_config_sha256=_sha256(
                row["assay_config_sha256"],
                "evidence.assay_config_sha256",
            ),
            raw_artifact_sha256=_sha256(
                row["raw_artifact_sha256"],
                "evidence.raw_artifact_sha256",
            ),
            execution_status=cast(Literal["complete", "invalid"], execution_status),
            usage=ResourceUsage.from_mapping(row["usage"]),
            rows=rows,
            failure_class=failure_class,
        )
        supplied_id = row.get("evidence_id")
        if (
            supplied_id is not None
            and _sha256(supplied_id, "evidence.evidence_id") != evidence.evidence_id
        ):
            raise ContractError("evidence_id does not match the canonical evidence payload")
        return evidence

    def canonical_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": EVIDENCE_SCHEMA,
            "contract_id": self.contract_id,
            "arm": self.arm,
            "revision_sha": self.revision_sha,
            "evaluator_sha256": self.evaluator_sha256,
            "harness_sha256": self.harness_sha256,
            "task_layout_sha256": self.task_layout_sha256,
            "assay_config_sha256": self.assay_config_sha256,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "execution_status": self.execution_status,
            "usage": self.usage.to_dict(),
            "rows": [row.to_dict() for row in self.rows],
        }
        if self.failure_class is not None:
            payload["failure_class"] = self.failure_class
        return payload

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.canonical_payload(), "evidence_id": self.evidence_id}


def load_evidence(path: Path) -> EvidenceEnvelope:
    """Load and validate one normalized evidence artifact."""

    return EvidenceEnvelope.from_mapping(
        load_json_object(path, "evidence", max_bytes=64 * 1024 * 1024)
    )


def expected_pairs(contract: ExperimentContract) -> tuple[tuple[str, int], ...]:
    """Return the task-major paired observation order frozen by the contract."""

    return tuple(
        (task_id, trial)
        for task_id in contract.task_ids
        for trial in range(contract.trials_per_task)
    )


def validate_evidence_identity(
    contract: ExperimentContract,
    evidence: EvidenceEnvelope,
    *,
    arm: Literal["baseline", "candidate"],
) -> None:
    """Bind normalized evidence to one contract arm and its actual artifact."""

    expected_revision = contract.baseline_sha if arm == "baseline" else contract.candidate_sha
    expected = {
        "contract_id": contract.contract_id,
        "arm": arm,
        "revision_sha": expected_revision,
        "evaluator_sha256": contract.evaluator_sha256,
        "harness_sha256": contract.harness_sha256,
        "task_layout_sha256": contract.task_layout_sha256,
        "assay_config_sha256": contract.assay_config_sha256,
    }
    observed = {
        "contract_id": evidence.contract_id,
        "arm": evidence.arm,
        "revision_sha": evidence.revision_sha,
        "evaluator_sha256": evidence.evaluator_sha256,
        "harness_sha256": evidence.harness_sha256,
        "task_layout_sha256": evidence.task_layout_sha256,
        "assay_config_sha256": evidence.assay_config_sha256,
    }
    for field, value in expected.items():
        if observed[field] != value:
            raise ContractError(f"{arm} evidence {field} does not match the frozen contract")
