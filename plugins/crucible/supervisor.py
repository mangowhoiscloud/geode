"""Standalone, authority-neutral search loop for Crucible train experiments.

The supervisor owns the train plan, disposable candidate checkouts, git refs,
contract construction, preflight, verdict derivation, campaign budget, and
ledger. Candidate generation and assay execution are separate commands. The
loop never imports ``core.self_improving`` and never grants release authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from .artifacts import (
    append_jsonl,
    atomic_write_json,
    contained_path,
    load_json_object,
    write_exclusive_json,
)
from .candidate_dedup import (
    CANDIDATE_FINGERPRINT_OBSERVATION_SCHEMA,
    CANDIDATE_FINGERPRINT_SCHEMA,
    CandidateFingerprintStore,
)
from .contract import (
    EXPERIMENT_SCHEMA,
    ContractError,
    ExperimentContract,
    Mutation,
    validate_candidate_diff,
    validate_checkout,
    validate_measurement_files,
)
from .evidence import EvidenceEnvelope, ResourceUsage, load_evidence
from .promotion import PromotionVerdict, decide
from .ref_journal import RefIntent, persist_intent, reconcile_ref_update

CONFIG_SCHEMA = "crucible.supervisor.v4"
TRAIN_PLAN_SCHEMA = "crucible.train-plan.v3"
REQUEST_SCHEMA = "crucible.proposal-request.v3"
PROPOSAL_SCHEMA = "crucible.candidate.v2"
EVALUATION_SCHEMA = "crucible.train-evaluation.v3"
FEEDBACK_SCHEMA = "crucible.failure-feedback.v3"
SUPERVISOR_FEEDBACK_SCHEMA = "crucible.supervisor-feedback.v3"
RECORD_SCHEMA = "crucible.loop-record.v2"
STATE_SCHEMA = "crucible.loop-state.v2"
SUMMARY_SCHEMA = "crucible.loop-summary.v2"
ATTEMPT_ERROR_SCHEMA = "crucible.attempt-error.v1"
PRODUCER_ERROR_SCHEMA = "crucible.producer-error.v1"

_SHA = re.compile(r"[0-9a-f]{40}")
_CAMPAIGN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TRAIN_DENIED_ENV = re.compile(
    r"(?:HELD_?OUT|SEALED|TEST_?PACK|AUTORESEARCH|GEODE_STATE_ROOT)",
    re.IGNORECASE,
)
_BASE_ENV = (
    "LANG",
    "LC_ALL",
    "PATH",
    "SSL_CERT_FILE",
)
_ZERO_SHA = "0" * 40
_FAILURE_CODES = frozenset(
    {
        "quality",
        "required_user_action",
        "duplicate_candidate",
        "safety",
        "state_correctness",
        "termination",
        "tool_contract",
        "workflow_completion",
    }
)
_FEEDBACK_MAX_TASK_IDS = 64
_FEEDBACK_MAX_TASK_ID_BYTES = 64 * 1024
_PRODUCER_OBJECTIVE_MAX_BYTES = 16 * 1024


class SupervisorError(ValueError):
    """The outer loop cannot safely continue."""


class _DuplicateCandidateError(RuntimeError):
    """A valid train verdict already exists for the same stable patch."""

    def __init__(self, fingerprint: str, fingerprint_ref: str) -> None:
        self.fingerprint = fingerprint
        self.fingerprint_ref = fingerprint_ref
        super().__init__("candidate patch already has a valid train verdict")


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SupervisorError(f"{field} must be a non-empty string")
    return value.strip()


def _sha(value: object, field: str) -> str:
    result = _text(value, field).lower()
    if _SHA.fullmatch(result) is None:
        raise SupervisorError(f"{field} must be a full lowercase git SHA")
    return result


def _positive(value: object, field: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool):
        raise SupervisorError(f"{field} must be positive")
    if integer:
        if not isinstance(value, int):
            raise SupervisorError(f"{field} must be a positive integer")
        result: float | int = value
    else:
        if not isinstance(value, (int, float)):
            raise SupervisorError(f"{field} must be positive")
        result = float(value)
    if result <= 0 or not math.isfinite(float(result)):
        raise SupervisorError(f"{field} must be positive and finite")
    return result


def _strings(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise SupervisorError(f"{field} must be {qualifier}")
    result = tuple(_text(item, f"{field}[]") for item in value)
    if len(set(result)) != len(result):
        raise SupervisorError(f"{field} contains duplicates")
    return result


def _require_fields(
    value: Mapping[str, Any],
    field: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - allowed)
    if missing:
        raise SupervisorError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise SupervisorError(f"{field} has unknown fields: {', '.join(unknown)}")


def _search_objective(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SupervisorError("search must be an object")
    _require_fields(value, "search", required={"objective"})
    objective = _text(value.get("objective"), "search.objective")
    if len(objective.encode("utf-8")) > _PRODUCER_OBJECTIVE_MAX_BYTES:
        raise SupervisorError(
            f"search.objective exceeds {_PRODUCER_OBJECTIVE_MAX_BYTES} UTF-8 bytes"
        )
    return objective


def _prepared_by(value: object) -> Mapping[str, Any] | None:
    """Preparation provenance travels with the config file but stays out of
    ``payload()`` so it never perturbs the config_id identity hash."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise SupervisorError("prepared_by must be an object when present")
    return dict(value)


def _validate_string_sequence(
    field: str,
    values: Sequence[str],
    *,
    allow_empty: bool,
) -> None:
    if not values and not allow_empty:
        raise SupervisorError(f"{field} must be non-empty")
    if len(set(values)) != len(values):
        raise SupervisorError(f"{field} contains duplicates")
    for value in values:
        _text(value, f"{field}[]")


def _validate_train_environment(producer: Sequence[str], evaluator: Sequence[str]) -> None:
    names = (*producer, *evaluator)
    for name in names:
        if _ENV_NAME.fullmatch(name) is None:
            raise SupervisorError(f"invalid environment variable name: {name}")
    denied = [name for name in names if _TRAIN_DENIED_ENV.search(name)]
    if denied:
        raise SupervisorError(
            "train subprocess environment exposes adaptive or sealed state: "
            + ", ".join(sorted(denied))
        )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _repo_path_is_within(path: str, frozen: str) -> bool:
    candidate = PurePosixPath(path)
    root = PurePosixPath(frozen)
    return candidate == root or root in candidate.parents


def _file_sha256(path: Path, field: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise SupervisorError(f"{field} must be a regular file")
    if path.stat().st_size > 512 * 1024 * 1024:
        raise SupervisorError(f"{field} exceeds 536870912 bytes")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LoopLimits:
    max_attempts: int
    max_consecutive_invalid: int
    max_wall_seconds: float
    max_calls: int
    max_tokens: int
    max_cost_usd: float

    @classmethod
    def from_mapping(cls, value: object) -> LoopLimits:
        if not isinstance(value, Mapping):
            raise SupervisorError("limits must be an object")
        _require_fields(
            value,
            "limits",
            required={
                "max_attempts",
                "max_calls",
                "max_consecutive_invalid",
                "max_cost_usd",
                "max_tokens",
                "max_wall_seconds",
            },
        )
        return cls(
            max_attempts=int(_positive(value.get("max_attempts"), "max_attempts", integer=True)),
            max_consecutive_invalid=int(
                _positive(
                    value.get("max_consecutive_invalid"),
                    "max_consecutive_invalid",
                    integer=True,
                )
            ),
            max_wall_seconds=float(_positive(value.get("max_wall_seconds"), "max_wall_seconds")),
            max_calls=int(_positive(value.get("max_calls"), "max_calls", integer=True)),
            max_tokens=int(_positive(value.get("max_tokens"), "max_tokens", integer=True)),
            max_cost_usd=float(_positive(value.get("max_cost_usd"), "max_cost_usd")),
        )

    def to_dict(self) -> dict[str, float | int]:
        return dict(vars(self))

    def validate(self) -> None:
        _positive(self.max_attempts, "max_attempts", integer=True)
        _positive(self.max_consecutive_invalid, "max_consecutive_invalid", integer=True)
        _positive(self.max_wall_seconds, "max_wall_seconds")
        _positive(self.max_calls, "max_calls", integer=True)
        _positive(self.max_tokens, "max_tokens", integer=True)
        _positive(self.max_cost_usd, "max_cost_usd")

    def remaining(self, usage: ResourceUsage, elapsed: float) -> dict[str, float | int]:
        return {
            "wall_seconds": max(0.0, self.max_wall_seconds - elapsed),
            "calls": max(0, self.max_calls - usage.calls),
            "tokens": max(0, self.max_tokens - usage.tokens),
            "cost_usd": max(0.0, self.max_cost_usd - usage.cost_usd),
        }

    def exceeded(self, usage: ResourceUsage, elapsed: float) -> bool:
        return (
            elapsed > self.max_wall_seconds
            or usage.calls > self.max_calls
            or usage.tokens > self.max_tokens
            or usage.cost_usd > self.max_cost_usd
        )


@dataclass(frozen=True)
class TrainPlan:
    """Supervisor-owned fixed contract fields shared by every train attempt."""

    payload_json: str

    @classmethod
    def from_mapping(cls, value: object) -> TrainPlan:
        if not isinstance(value, Mapping):
            raise SupervisorError("train_plan must be an object")
        if value.get("schema") != TRAIN_PLAN_SCHEMA:
            raise SupervisorError(f"train_plan.schema must be {TRAIN_PLAN_SCHEMA!r}")
        forbidden = {
            "baseline_sha",
            "candidate_sha",
            "champion_ref",
            "contract_id",
            "mutations",
            "stage",
        }
        present = sorted(forbidden & set(value))
        if present:
            raise SupervisorError("train_plan contains attempt-owned fields: " + ", ".join(present))
        payload = {key: item for key, item in value.items() if key != "schema"}
        return cls(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise AssertionError("train plan payload is not an object")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {"schema": TRAIN_PLAN_SCHEMA, **self.payload}

    def contract(
        self,
        *,
        champion_ref: str,
        baseline_sha: str,
        candidate_sha: str,
        mutation: Mutation,
    ) -> ExperimentContract:
        return ExperimentContract.from_mapping(
            {
                "schema": EXPERIMENT_SCHEMA,
                "stage": "train",
                "champion_ref": champion_ref,
                "baseline_sha": baseline_sha,
                "candidate_sha": candidate_sha,
                "mutations": [mutation.to_dict()],
                **self.payload,
            }
        )


@dataclass(frozen=True)
class SupervisorConfig:
    campaign_id: str
    initial_search_head_sha: str
    repository: Path
    harness_root: Path
    state_dir: Path
    allowed_surfaces: tuple[str, ...]
    producer_command: tuple[str, ...]
    evaluator_entrypoint: str
    producer_environment: tuple[str, ...]
    evaluator_environment: tuple[str, ...]
    train_plan: TrainPlan
    limits: LoopLimits
    producer_objective: str | None = None
    initial_feedback: FailureFeedback | None = None
    prepared_by: Mapping[str, Any] | None = None

    @classmethod
    def load(cls, path: Path) -> SupervisorConfig:
        row = load_json_object(path, "supervisor config")
        _require_fields(
            row,
            "supervisor config",
            required={
                "allowed_surfaces",
                "campaign_id",
                "evaluator_entrypoint",
                "evaluator_environment",
                "harness_root",
                "initial_search_head_sha",
                "limits",
                "producer_command",
                "producer_environment",
                "repository",
                "schema",
                "state_dir",
                "train_plan",
            },
            optional={"config_id", "initial_feedback", "prepared_by", "search"},
        )
        if row.get("schema") != CONFIG_SCHEMA:
            raise SupervisorError(f"schema must be {CONFIG_SCHEMA!r}")
        campaign_id = _text(row.get("campaign_id"), "campaign_id")
        if _CAMPAIGN.fullmatch(campaign_id) is None:
            raise SupervisorError("campaign_id must be filesystem-safe")
        base = path.resolve().parent

        def resolve(raw: object, field: str) -> Path:
            value = Path(_text(raw, field)).expanduser()
            return (base / value).resolve() if not value.is_absolute() else value.resolve()

        producer_environment = _strings(
            row.get("producer_environment", []),
            "producer_environment",
            allow_empty=True,
        )
        evaluator_environment = _strings(
            row.get("evaluator_environment", []),
            "evaluator_environment",
            allow_empty=True,
        )
        config = cls(
            campaign_id=campaign_id,
            initial_search_head_sha=_sha(
                row.get("initial_search_head_sha"), "initial_search_head_sha"
            ),
            repository=resolve(row.get("repository"), "repository"),
            harness_root=resolve(row.get("harness_root"), "harness_root"),
            state_dir=resolve(row.get("state_dir"), "state_dir"),
            allowed_surfaces=_strings(row.get("allowed_surfaces"), "allowed_surfaces"),
            producer_command=_strings(row.get("producer_command"), "producer_command"),
            evaluator_entrypoint=_text(
                row.get("evaluator_entrypoint"),
                "evaluator_entrypoint",
            ),
            producer_environment=producer_environment,
            evaluator_environment=evaluator_environment,
            train_plan=TrainPlan.from_mapping(row.get("train_plan")),
            limits=LoopLimits.from_mapping(row.get("limits")),
            producer_objective=_search_objective(row.get("search")),
            initial_feedback=(
                None
                if row.get("initial_feedback") is None
                else FailureFeedback.from_mapping(row.get("initial_feedback"))
            ),
            prepared_by=_prepared_by(row.get("prepared_by")),
        )
        config.validate()
        supplied_id = row.get("config_id")
        if supplied_id is not None and supplied_id != config.config_id:
            raise SupervisorError("config_id does not match the configuration")
        return config

    def validate(self) -> None:
        if _CAMPAIGN.fullmatch(self.campaign_id) is None:
            raise SupervisorError("campaign_id must be filesystem-safe")
        _sha(self.initial_search_head_sha, "initial_search_head_sha")
        for field, values, allow_empty in (
            ("allowed_surfaces", self.allowed_surfaces, False),
            ("producer_command", self.producer_command, False),
            ("producer_environment", self.producer_environment, True),
            ("evaluator_environment", self.evaluator_environment, True),
        ):
            _validate_string_sequence(field, values, allow_empty=allow_empty)
        self.limits.validate()
        if self.producer_objective is not None:
            _search_objective({"objective": self.producer_objective})
        _validate_train_environment(self.producer_environment, self.evaluator_environment)
        entrypoint = PurePosixPath(self.evaluator_entrypoint)
        if entrypoint.is_absolute() or ".." in entrypoint.parts:
            raise SupervisorError("evaluator_entrypoint must be repository-relative")
        for surface in self.allowed_surfaces:
            validation_contract = self.train_plan.contract(
                champion_ref="refs/crucible/validation",
                baseline_sha="1" * 40,
                candidate_sha="2" * 40,
                mutation=Mutation(surface=surface, hypothesis="plan validation"),
            )
            if not any(
                _repo_path_is_within(self.evaluator_entrypoint, frozen)
                for frozen in validation_contract.evaluator_paths
            ):
                raise SupervisorError("evaluator_entrypoint is not in evaluator_paths")
        if self.initial_feedback is not None:
            self.initial_feedback.validate_for(validation_contract)

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": CONFIG_SCHEMA,
            "campaign_id": self.campaign_id,
            "initial_search_head_sha": self.initial_search_head_sha,
            "repository": str(self.repository),
            "harness_root": str(self.harness_root),
            "state_dir": str(self.state_dir),
            "allowed_surfaces": list(self.allowed_surfaces),
            "producer_command": list(self.producer_command),
            "evaluator_entrypoint": self.evaluator_entrypoint,
            "producer_environment": list(self.producer_environment),
            "evaluator_environment": list(self.evaluator_environment),
            "train_plan": self.train_plan.to_dict(),
            "limits": self.limits.to_dict(),
        }
        if self.initial_feedback is not None:
            payload["initial_feedback"] = self.initial_feedback.to_dict()
        if self.producer_objective is not None:
            payload["search"] = {"objective": self.producer_objective}
        return payload

    @property
    def config_id(self) -> str:
        return _hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        serialized = {**self.payload(), "config_id": self.config_id}
        if self.prepared_by is not None:
            serialized["prepared_by"] = dict(self.prepared_by)
        return serialized


@dataclass(frozen=True)
class ProposalRequest:
    campaign_id: str
    config_id: str
    attempt_id: str
    iteration: int
    parent_sha: str
    allowed_surfaces: tuple[str, ...]
    attempt_dir: Path
    worktree: Path
    producer_dir: Path
    feedback: Mapping[str, Any] | None
    remaining_budget: Mapping[str, float | int]
    objective: str | None = None

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": REQUEST_SCHEMA,
            "campaign_id": self.campaign_id,
            "config_id": self.config_id,
            "attempt_id": self.attempt_id,
            "iteration": self.iteration,
            "parent_sha": self.parent_sha,
            "allowed_surfaces": list(self.allowed_surfaces),
            "feedback": dict(self.feedback) if self.feedback is not None else None,
            "remaining_budget": dict(self.remaining_budget),
        }
        if self.objective is not None:
            payload["objective"] = self.objective
        return payload

    @property
    def request_id(self) -> str:
        return _hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "request_id": self.request_id}

    def to_producer_dict(self) -> dict[str, Any]:
        """Return the authority-bound request without evaluator task identity."""

        payload = self.to_dict()
        feedback: object = self.feedback
        if isinstance(feedback, Mapping) and feedback.get("schema") == SUPERVISOR_FEEDBACK_SCHEMA:
            feedback = feedback.get("evaluator")
        raw_codes = (
            feedback.get("failure_codes")
            if isinstance(feedback, Mapping) and feedback.get("schema") == FEEDBACK_SCHEMA
            else None
        )
        payload["feedback"] = (
            {
                "schema": FEEDBACK_SCHEMA,
                "failure_codes": [
                    code for code in raw_codes if isinstance(code, str) and code in _FAILURE_CODES
                ],
            }
            if isinstance(raw_codes, list)
            else None
        )
        return payload


@dataclass(frozen=True)
class CandidateProposal:
    attempt_id: str
    request_id: str
    parent_sha: str
    candidate_sha: str
    mutation: Mutation
    usage: ResourceUsage

    @classmethod
    def load(cls, path: Path, *, request: ProposalRequest) -> CandidateProposal:
        row = load_json_object(path, "candidate proposal", max_bytes=1024 * 1024)
        _require_fields(
            row,
            "candidate proposal",
            required={
                "attempt_id",
                "candidate_sha",
                "mutation",
                "parent_sha",
                "request_id",
                "schema",
                "usage",
            },
            optional={"proposal_id"},
        )
        if row.get("schema") != PROPOSAL_SCHEMA:
            raise SupervisorError(f"proposal schema must be {PROPOSAL_SCHEMA!r}")
        proposal = cls(
            attempt_id=_text(row.get("attempt_id"), "attempt_id"),
            request_id=_text(row.get("request_id"), "request_id"),
            parent_sha=_sha(row.get("parent_sha"), "parent_sha"),
            candidate_sha=_sha(row.get("candidate_sha"), "candidate_sha"),
            mutation=Mutation.from_mapping(row.get("mutation")),
            usage=ResourceUsage.from_mapping(row.get("usage")),
        )
        if proposal.attempt_id != request.attempt_id or proposal.request_id != request.request_id:
            raise SupervisorError("candidate proposal does not match the current request")
        if proposal.parent_sha != request.parent_sha:
            raise SupervisorError("candidate parent does not match the search head")
        if proposal.parent_sha == proposal.candidate_sha:
            raise SupervisorError("candidate_sha must differ from parent_sha")
        supplied_id = row.get("proposal_id")
        if supplied_id is not None and supplied_id != proposal.proposal_id:
            raise SupervisorError("proposal_id does not match the proposal")
        return proposal

    def payload(self) -> dict[str, Any]:
        return {
            "schema": PROPOSAL_SCHEMA,
            "attempt_id": self.attempt_id,
            "request_id": self.request_id,
            "parent_sha": self.parent_sha,
            "candidate_sha": self.candidate_sha,
            "mutation": self.mutation.to_dict(),
            "usage": self.usage.to_dict(),
        }

    @property
    def proposal_id(self) -> str:
        return _hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "proposal_id": self.proposal_id}


@dataclass(frozen=True)
class FailureFeedback:
    """Bounded evaluator feedback forwarded to the next producer.

    v3 may identify which frozen train tasks failed and classify them with a
    closed code set. It cannot transport free text, trajectories, task
    payloads, gold actions, or expected values. The task cap is a transport
    limit, not a gate parameter.
    """

    failure_codes: tuple[str, ...]
    failed_task_ids: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> FailureFeedback:
        if not isinstance(value, Mapping) or value.get("schema") != FEEDBACK_SCHEMA:
            raise SupervisorError(f"feedback must use {FEEDBACK_SCHEMA!r}")
        allowed = {"schema", "failure_codes", "failed_task_ids"}
        unknown = sorted(str(key) for key in set(value) - allowed)
        if unknown:
            raise SupervisorError("feedback has unknown fields: " + ", ".join(unknown))
        codes = _strings(
            value.get("failure_codes", []),
            "feedback.failure_codes",
            allow_empty=True,
        )
        unsupported = sorted(set(codes) - _FAILURE_CODES)
        if unsupported:
            raise SupervisorError(
                "feedback.failure_codes are unsupported: " + ", ".join(unsupported)
            )
        failed_task_ids = _strings(
            value.get("failed_task_ids", []),
            "feedback.failed_task_ids",
            allow_empty=True,
        )
        encoded_task_id_bytes = sum(len(item.encode("utf-8")) for item in failed_task_ids)
        if (
            len(failed_task_ids) > _FEEDBACK_MAX_TASK_IDS
            or encoded_task_id_bytes > _FEEDBACK_MAX_TASK_ID_BYTES
        ):
            raise SupervisorError("feedback.failed_task_ids exceeds its boundary")
        return cls(
            failure_codes=codes,
            failed_task_ids=failed_task_ids,
        )

    def validate_for(self, contract: ExperimentContract) -> None:
        unknown = sorted(set(self.failed_task_ids) - set(contract.task_ids))
        if unknown:
            raise SupervisorError(
                "feedback.failed_task_ids are outside the train contract: " + ", ".join(unknown)
            )

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "schema": FEEDBACK_SCHEMA,
            "failure_codes": list(self.failure_codes),
        }
        if self.failed_task_ids:
            row["failed_task_ids"] = list(self.failed_task_ids)
        return row


@dataclass(frozen=True)
class EvaluationArtifacts:
    baseline: EvidenceEnvelope
    candidate: EvidenceEnvelope
    marginal_usage: ResourceUsage
    feedback: FailureFeedback | None

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        attempt_dir: Path,
        request: ProposalRequest,
        proposal: CandidateProposal,
        contract: ExperimentContract,
    ) -> EvaluationArtifacts:
        row = load_json_object(path, "train evaluation", max_bytes=1024 * 1024)
        _require_fields(
            row,
            "train evaluation",
            required={
                "attempt_id",
                "baseline",
                "baseline_raw",
                "candidate",
                "candidate_raw",
                "proposal_id",
                "request_id",
                "schema",
            },
            optional={"feedback", "marginal_usage"},
        )
        if row.get("schema") != EVALUATION_SCHEMA:
            raise SupervisorError(f"evaluation schema must be {EVALUATION_SCHEMA!r}")
        expected = {
            "attempt_id": request.attempt_id,
            "request_id": request.request_id,
            "proposal_id": proposal.proposal_id,
        }
        if any(row.get(field) != value for field, value in expected.items()):
            raise SupervisorError("evaluation does not match the current request and proposal")
        baseline_path = contained_path(
            attempt_dir,
            _text(row.get("baseline"), "baseline"),
            "baseline",
        )
        candidate_path = contained_path(
            attempt_dir,
            _text(row.get("candidate"), "candidate"),
            "candidate",
        )
        baseline_raw_path = contained_path(
            attempt_dir,
            _text(row.get("baseline_raw"), "baseline_raw"),
            "baseline_raw",
        )
        candidate_raw_path = contained_path(
            attempt_dir,
            _text(row.get("candidate_raw"), "candidate_raw"),
            "candidate_raw",
        )
        feedback_raw = row.get("feedback")
        feedback = FailureFeedback.from_mapping(feedback_raw) if feedback_raw is not None else None
        if feedback is not None:
            feedback.validate_for(contract)
        baseline = load_evidence(baseline_path)
        candidate = load_evidence(candidate_path)
        if _file_sha256(baseline_raw_path, "baseline_raw") != baseline.raw_artifact_sha256:
            raise SupervisorError("baseline raw artifact hash does not match evidence")
        if _file_sha256(candidate_raw_path, "candidate_raw") != candidate.raw_artifact_sha256:
            raise SupervisorError("candidate raw artifact hash does not match evidence")
        marginal_raw = row.get("marginal_usage")
        marginal_usage = (
            baseline.usage + candidate.usage
            if marginal_raw is None
            else ResourceUsage.from_mapping(marginal_raw)
        )
        if marginal_raw is not None and marginal_usage.to_dict() != marginal_raw:
            raise SupervisorError("train evaluation marginal_usage is not canonical")
        return cls(
            baseline=baseline,
            candidate=candidate,
            marginal_usage=marginal_usage,
            feedback=feedback,
        )


class CandidateProducer(Protocol):
    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal: ...


class TrustedEvaluator(Protocol):
    def evaluate(
        self,
        request: ProposalRequest,
        proposal: CandidateProposal,
        contract: ExperimentContract,
        *,
        checkout: Path,
        timeout: float,
    ) -> Path: ...


def _role_environment(
    names: Sequence[str],
    *,
    attempt_dir: Path,
    role: Literal["producer", "evaluator"],
    extra: Mapping[str, str],
) -> dict[str, str]:
    environment = {name: os.environ[name] for name in _BASE_ENV if name in os.environ}
    environment.update({name: os.environ[name] for name in names if name in os.environ})
    home = attempt_dir / f"{role}-home"
    temp = attempt_dir / f"{role}-tmp"
    state = attempt_dir / f"{role}-state"
    for path in (home, temp, state):
        path.mkdir(exist_ok=True)
    environment.update(
        {
            "CRUCIBLE_ROLE": role,
            "GEODE_STATE_ROOT": str(state),
            "HOME": str(home),
            "TMPDIR": str(temp),
            **extra,
        }
    )
    return environment


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float,
) -> None:
    try:
        process = subprocess.Popen(  # noqa: S603 - operator-owned argv, no shell
            list(command),
            cwd=cwd,
            env=dict(environment),
            start_new_session=True,
        )
    except OSError as exc:
        raise SupervisorError(f"cannot start subprocess: {exc}") from exc
    timed_out = False
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        return_code = -signal.SIGTERM
    finally:
        # The command is a session leader. Reap ordinary background children on
        # success as well as timeout so one role cannot keep writing after its
        # protocol response has been accepted.
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                # macOS reports EPERM for a group member mid exec/exit
                # transition; the group still exists, so keep waiting.
                pass
            time.sleep(0.01)
        else:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.wait()
    if timed_out:
        raise SupervisorError("subprocess timed out")
    if return_code != 0:
        raise SupervisorError(f"subprocess exited with status {return_code}")


def _producer_error_detail(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        row = load_json_object(path, "producer error", max_bytes=16 * 1024)
        _require_fields(
            row,
            "producer error",
            required={"error_type", "message", "schema"},
        )
        if row.get("schema") != PRODUCER_ERROR_SCHEMA:
            return None
        message = _text(row.get("message"), "producer error message")
    except (ContractError, SupervisorError):
        return None
    return " ".join(message.split())[:2_000]


class GitWorkspace:
    """Authority refs plus disposable candidate repositories for one campaign."""

    def __init__(self, repository: Path, campaign_id: str) -> None:
        git = shutil.which("git")
        if git is None:
            raise SupervisorError("git is required for a Crucible campaign")
        self.git = git
        self.repository = repository.resolve()
        self.search_ref = f"refs/crucible/search/{campaign_id}"
        self.baseline_prefix = f"refs/crucible/baselines/{campaign_id}"
        self.candidate_prefix = f"refs/crucible/candidates/{campaign_id}"
        self.fingerprints = CandidateFingerprintStore(self.repository, self.git)

    def run(self, *args: str, check: bool = True) -> str:
        return self.run_at(self.repository, *args, check=check)

    def run_at(self, path: Path, *args: str, check: bool = True) -> str:
        try:
            result = subprocess.run(  # noqa: S603 - fixed git executable and argv
                [self.git, *args],
                cwd=path,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SupervisorError("cannot inspect the campaign repository") from exc
        if check and result.returncode != 0:
            reason = result.stderr.strip() or "git command failed"
            raise SupervisorError(reason)
        return result.stdout.strip()

    def validate_initial_head(self, initial_sha: str) -> None:
        """Validate campaign authority inputs without changing repository state."""

        if not self.repository.is_dir():
            raise SupervisorError("repository does not exist")
        if self.run("status", "--porcelain", "--untracked-files=all"):
            raise SupervisorError("campaign repository must be clean")
        resolved = self.run(
            "rev-parse",
            "--verify",
            "--quiet",
            f"{initial_sha}^{{commit}}",
            check=False,
        )
        if not resolved:
            raise SupervisorError("initial_search_head_sha does not resolve to a commit")
        if resolved != initial_sha:
            raise SupervisorError("initial_search_head_sha is not the resolved commit")
        if self.run("rev-parse", "--verify", "--quiet", self.search_ref, check=False):
            raise SupervisorError("campaign search ref already exists")

    def initialize(self, initial_sha: str) -> None:
        self.validate_initial_head(initial_sha)
        self.run("update-ref", self.search_ref, initial_sha, _ZERO_SHA)

    def create_candidate_checkout(self, path: Path, head: str) -> None:
        """Create a no-remote disposable repository containing only ``head``."""

        path.mkdir()
        self.run_at(path, "init", "-q")
        # Producer processes run with an isolated HOME, so ambient git
        # identity/signing config is unavailable by design; candidate commits
        # need a checkout-local identity to succeed at all.
        self.run_at(path, "config", "user.name", "crucible-producer")
        self.run_at(path, "config", "user.email", "crucible-producer@localhost")
        self.run_at(path, "config", "commit.gpgsign", "false")
        self.run_at(
            path,
            "fetch",
            "--quiet",
            "--no-tags",
            "--depth=1",
            str(self.repository),
            head,
        )
        self.run_at(path, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        (path / ".git" / "FETCH_HEAD").unlink(missing_ok=True)

    def import_candidate(self, attempt_id: str, candidate_sha: str, source: Path) -> str:
        ref = f"{self.candidate_prefix}/{attempt_id}"
        self.run(
            "fetch",
            "--quiet",
            "--no-tags",
            str(source),
            f"{candidate_sha}:{ref}",
        )
        return ref

    def validate_imported_candidate(self, *, parent_sha: str, candidate_sha: str) -> None:
        parents = self.run(
            "--no-replace-objects",
            "rev-list",
            "--parents",
            "-n",
            "1",
            candidate_sha,
        ).split()
        if parents != [candidate_sha, parent_sha]:
            raise SupervisorError("candidate must be one single-parent commit after parent_sha")

    def create_measurement_checkout(
        self,
        path: Path,
        *,
        candidate_sha: str,
        baseline_sha: str,
        baseline_ref: str,
    ) -> None:
        """Materialize a producer-independent checkout from authority objects."""

        path.mkdir()
        self.run_at(path, "init", "-q")
        self.run_at(
            path,
            "fetch",
            "--quiet",
            "--no-tags",
            "--depth=2",
            str(self.repository),
            candidate_sha,
        )
        self.run_at(path, "checkout", "--quiet", "--detach", candidate_sha)
        (path / ".git" / "FETCH_HEAD").unlink(missing_ok=True)
        self.run_at(path, "update-ref", baseline_ref, baseline_sha, _ZERO_SHA)

    def pin_baseline(self, attempt_id: str, baseline_sha: str) -> str:
        ref = f"{self.baseline_prefix}/{attempt_id}"
        self.run("update-ref", ref, baseline_sha, _ZERO_SHA)
        return ref

    def assert_head(self, expected_sha: str) -> None:
        if self.run("rev-parse", "--verify", self.search_ref) != expected_sha:
            raise SupervisorError("campaign search ref changed outside the supervisor")

    def candidate_fingerprint(
        self,
        *,
        contract: ExperimentContract,
        surfaces: Sequence[str],
    ) -> str:
        return self.fingerprints.fingerprint(contract=contract, surfaces=surfaces)

    def fingerprint_ref(self, fingerprint: str) -> str:
        return self.fingerprints.reference(fingerprint)

    def load_candidate_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self.fingerprints.load(fingerprint)

    def persist_candidate_fingerprint(
        self,
        fingerprint: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        return self.fingerprints.persist(fingerprint, payload)

    def validate_candidate(
        self,
        worktree: Path,
        *,
        parent_sha: str,
        candidate_sha: str,
    ) -> None:
        if self.run_at(worktree, "rev-parse", "HEAD") != candidate_sha:
            raise SupervisorError("candidate checkout HEAD does not match candidate_sha")
        if self.run_at(worktree, "status", "--porcelain", "--untracked-files=all"):
            raise SupervisorError("candidate checkout must be clean")
        parents = self.run_at(
            worktree,
            "rev-list",
            "--parents",
            "-n",
            "1",
            candidate_sha,
        ).split()
        if parents != [candidate_sha, parent_sha]:
            raise SupervisorError("candidate must be one single-parent commit after parent_sha")


class CommandProducer:
    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config

    def propose(self, request: ProposalRequest, *, timeout: float) -> CandidateProposal:
        request.producer_dir.mkdir()
        request_path = request.producer_dir / "request.json"
        output = request.producer_dir / "candidate-response.json"
        error_output = request.producer_dir / "producer-error.json"
        write_exclusive_json(request_path, request.to_producer_dict())
        if output.exists() or output.is_symlink():
            raise SupervisorError("candidate response already exists")
        environment = _role_environment(
            self.config.producer_environment,
            attempt_dir=request.producer_dir,
            role="producer",
            extra={
                "CRUCIBLE_PROPOSAL_REQUEST": str(request_path),
                "CRUCIBLE_CANDIDATE_OUTPUT": str(output),
                "CRUCIBLE_ERROR_OUTPUT": str(error_output),
            },
        )
        try:
            _run_process(
                self.config.producer_command,
                cwd=request.worktree,
                environment=environment,
                timeout=timeout,
            )
        except SupervisorError as exc:
            detail = _producer_error_detail(error_output)
            if detail is not None:
                raise SupervisorError(f"producer failed: {detail}") from exc
            raise
        if output.is_symlink():
            raise SupervisorError("candidate response must not be a symlink")
        return CandidateProposal.load(output, request=request)


class CommandEvaluator:
    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config

    def evaluate(
        self,
        request: ProposalRequest,
        proposal: CandidateProposal,
        contract: ExperimentContract,
        *,
        checkout: Path,
        timeout: float,
    ) -> Path:
        checkout = checkout.resolve()
        relative_entrypoint = PurePosixPath(self.config.evaluator_entrypoint)
        cursor = checkout
        for part in relative_entrypoint.parts[:-1]:
            cursor /= part
            if cursor.is_symlink():
                raise SupervisorError("evaluator_entrypoint traverses a symlink")
        entrypoint = checkout.joinpath(*relative_entrypoint.parts)
        if (
            entrypoint.is_symlink()
            or not entrypoint.is_file()
            or not entrypoint.resolve().is_relative_to(checkout)
            or not os.access(entrypoint, os.X_OK)
        ):
            raise SupervisorError("evaluator_entrypoint must be a frozen executable file")
        evaluation_dir = request.attempt_dir / f"evaluation-{uuid.uuid4().hex}"
        evaluation_dir.mkdir()
        request_path = evaluation_dir / "request.json"
        candidate_path = evaluation_dir / "candidate.json"
        contract_path = evaluation_dir / "contract.json"
        output = evaluation_dir / "evaluation-response.json"
        write_exclusive_json(request_path, request.to_dict())
        write_exclusive_json(candidate_path, proposal.to_dict())
        write_exclusive_json(contract_path, contract.to_dict())
        if output.exists() or output.is_symlink():  # pragma: no cover - fresh directory invariant
            raise SupervisorError("evaluation response already exists")
        environment = _role_environment(
            self.config.evaluator_environment,
            attempt_dir=evaluation_dir,
            role="evaluator",
            extra={
                "CRUCIBLE_PROPOSAL_REQUEST": str(request_path),
                "CRUCIBLE_CANDIDATE": str(candidate_path),
                "CRUCIBLE_CONTRACT": str(contract_path),
                "CRUCIBLE_EVALUATION_OUTPUT": str(output),
            },
        )
        _run_process(
            (str(entrypoint),),
            cwd=checkout,
            environment=environment,
            timeout=timeout,
        )
        if output.is_symlink():
            raise SupervisorError("evaluation response must not be a symlink")
        return output


@dataclass(frozen=True)
class _AttemptResult:
    proposal: CandidateProposal | None
    verdict: PromotionVerdict | None
    contract: ExperimentContract | None
    evaluator_feedback: FailureFeedback | None
    candidate_ref: str | None
    baseline_ref: str | None
    candidate_fingerprint: str | None
    candidate_fingerprint_ref: str | None
    usage: ResourceUsage
    evidence_usage: ResourceUsage
    outcome: Literal["KEEP", "REJECT", "INVALID"]
    reasons: tuple[str, ...]
    next_head: str
    wall_seconds: float


@dataclass(frozen=True)
class SupervisorSummary:
    campaign_id: str
    search_ref: str
    initial_search_head_sha: str
    final_search_head_sha: str
    attempts: int
    keeps: int
    rejects: int
    invalids: int
    stop_reason: str
    usage: ResourceUsage
    evidence_usage: ResourceUsage
    elapsed_seconds: float
    state_dir: Path

    def to_dict(self) -> dict[str, Any]:
        payload = dict(vars(self))
        payload["schema"] = SUMMARY_SCHEMA
        payload["usage"] = self.usage.to_dict()
        payload["evidence_usage"] = self.evidence_usage.to_dict()
        payload["state_dir"] = str(self.state_dir)
        return payload


class PromotionSupervisor:
    """Bounded train loop whose only mutable authority is a private git ref."""

    def __init__(
        self,
        config: SupervisorConfig,
        *,
        producer: CandidateProducer | None = None,
        evaluator: TrustedEvaluator | None = None,
    ) -> None:
        self.config = config
        self.producer = producer or CommandProducer(config)
        self.evaluator = evaluator or CommandEvaluator(config)

    def _limit(
        self,
        attempts: int,
        invalid_streak: int,
        usage: ResourceUsage,
        elapsed: float,
    ) -> str | None:
        limits = self.config.limits
        checks = (
            (attempts >= limits.max_attempts, "max_attempts"),
            (invalid_streak >= limits.max_consecutive_invalid, "consecutive_invalid"),
            (elapsed >= limits.max_wall_seconds, "wall_budget"),
            (usage.calls >= limits.max_calls, "call_budget"),
            (usage.tokens >= limits.max_tokens, "token_budget"),
            (usage.cost_usd >= limits.max_cost_usd, "cost_budget"),
        )
        return next((name for reached, name in checks if reached), None)

    def _state(
        self,
        *,
        status: str,
        workspace: GitWorkspace,
        head: str,
        counts: Mapping[str, int],
        usage: ResourceUsage,
        evidence_usage: ResourceUsage,
        elapsed: float,
        record_id: str | None,
        stop_reason: str | None,
    ) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "campaign_id": self.config.campaign_id,
            "config_id": self.config.config_id,
            "status": status,
            "search_ref": workspace.search_ref,
            "search_head_sha": head,
            **counts,
            "usage": usage.to_dict(),
            "evidence_usage": evidence_usage.to_dict(),
            "elapsed_seconds": elapsed,
            "last_record_id": record_id,
            "stop_reason": stop_reason,
            "updated_at": _utc_now(),
        }

    def _preflight(
        self,
        workspace: GitWorkspace,
        checkout: Path,
        proposal: CandidateProposal,
        contract: ExperimentContract,
    ) -> None:
        workspace.validate_candidate(
            checkout,
            parent_sha=proposal.parent_sha,
            candidate_sha=proposal.candidate_sha,
        )
        validate_checkout(contract, checkout, arm="candidate")
        validate_candidate_diff(contract, checkout)
        validate_measurement_files(
            contract,
            repo_root=checkout,
            harness_root=self.config.harness_root,
        )

    def _execute_attempt(
        self,
        workspace: GitWorkspace,
        *,
        attempt_dir: Path,
        attempt_id: str,
        iteration: int,
        head: str,
        feedback: Mapping[str, Any] | None,
        campaign_usage: ResourceUsage,
        elapsed: float,
        campaign_started: float,
    ) -> _AttemptResult:
        config = self.config
        zero = ResourceUsage(0.0, 0, 0, 0.0)
        worktree_root = Path(tempfile.mkdtemp(prefix=f"crucible-{attempt_id}-"))
        candidate_worktree = worktree_root / "producer-checkout"
        measurement_checkout = worktree_root / f"measurement-{uuid.uuid4().hex}"
        producer_dir = worktree_root / "producer"
        try:
            workspace.create_candidate_checkout(candidate_worktree, head)
        except Exception:
            shutil.rmtree(worktree_root, ignore_errors=True)
            raise
        request = ProposalRequest(
            campaign_id=config.campaign_id,
            config_id=config.config_id,
            attempt_id=attempt_id,
            iteration=iteration,
            parent_sha=head,
            allowed_surfaces=config.allowed_surfaces,
            attempt_dir=attempt_dir,
            worktree=candidate_worktree,
            producer_dir=producer_dir,
            feedback=feedback,
            remaining_budget=config.limits.remaining(campaign_usage, elapsed),
            objective=config.producer_objective,
        )
        proposal: CandidateProposal | None = None
        verdict: PromotionVerdict | None = None
        contract: ExperimentContract | None = None
        evaluator_feedback: FailureFeedback | None = None
        candidate_ref: str | None = None
        baseline_ref: str | None = None
        candidate_fingerprint: str | None = None
        candidate_fingerprint_ref: str | None = None
        attempt_usage = zero
        attempt_evidence_usage = zero
        outcome: Literal["KEEP", "REJECT", "INVALID"] = "INVALID"
        reasons: tuple[str, ...] = ()
        next_head = head
        attempt_started = time.monotonic()
        try:
            write_exclusive_json(attempt_dir / "request.json", request.to_dict())
            proposal = self.producer.propose(
                request,
                timeout=float(request.remaining_budget["wall_seconds"]),
            )
            attempt_usage = proposal.usage
            attempt_evidence_usage = proposal.usage
            write_exclusive_json(attempt_dir / "candidate.json", proposal.to_dict())
            if proposal.mutation.surface not in config.allowed_surfaces:
                raise SupervisorError("proposal surface is not allowed")
            candidate_ref = workspace.import_candidate(
                attempt_id,
                proposal.candidate_sha,
                candidate_worktree,
            )
            workspace.validate_imported_candidate(
                parent_sha=proposal.parent_sha,
                candidate_sha=proposal.candidate_sha,
            )
            baseline_ref = workspace.pin_baseline(attempt_id, proposal.parent_sha)
            contract = config.train_plan.contract(
                champion_ref=baseline_ref,
                baseline_sha=proposal.parent_sha,
                candidate_sha=proposal.candidate_sha,
                mutation=proposal.mutation,
            )
            write_exclusive_json(attempt_dir / "contract.json", contract.to_dict())
            workspace.create_measurement_checkout(
                measurement_checkout,
                candidate_sha=proposal.candidate_sha,
                baseline_sha=proposal.parent_sha,
                baseline_ref=baseline_ref,
            )
            self._preflight(workspace, measurement_checkout, proposal, contract)
            candidate_fingerprint = workspace.candidate_fingerprint(
                contract=contract,
                surfaces=config.allowed_surfaces,
            )
            candidate_fingerprint_ref = workspace.fingerprint_ref(candidate_fingerprint)
            prior_fingerprint = workspace.load_candidate_fingerprint(candidate_fingerprint)
            if prior_fingerprint is not None:
                write_exclusive_json(
                    attempt_dir / "candidate-fingerprint.json",
                    {
                        "schema": CANDIDATE_FINGERPRINT_OBSERVATION_SCHEMA,
                        "status": "duplicate",
                        "fingerprint_sha256": candidate_fingerprint,
                        "fingerprint_ref": candidate_fingerprint_ref,
                        "candidate_sha": proposal.candidate_sha,
                        "prior": prior_fingerprint,
                    },
                )
                raise _DuplicateCandidateError(candidate_fingerprint, candidate_fingerprint_ref)
            if config.limits.exceeded(
                campaign_usage + proposal.usage,
                time.monotonic() - campaign_started,
            ):
                raise SupervisorError("producer exhausted the campaign budget")
            remaining = config.limits.max_wall_seconds - (time.monotonic() - campaign_started)
            evaluation_response = self.evaluator.evaluate(
                request,
                proposal,
                contract,
                checkout=measurement_checkout,
                timeout=remaining,
            )
            artifacts = EvaluationArtifacts.load(
                evaluation_response,
                attempt_dir=evaluation_response.parent,
                request=request,
                proposal=proposal,
                contract=contract,
            )
            attempt_usage = proposal.usage + artifacts.marginal_usage
            attempt_evidence_usage = (
                proposal.usage + artifacts.baseline.usage + artifacts.candidate.usage
            )
            self._preflight(workspace, measurement_checkout, proposal, contract)
            verdict = decide(contract, artifacts.baseline, artifacts.candidate)
            write_exclusive_json(
                attempt_dir / "baseline.attested.json",
                artifacts.baseline.to_dict(),
            )
            write_exclusive_json(
                attempt_dir / "candidate.attested.json",
                artifacts.candidate.to_dict(),
            )
            write_exclusive_json(attempt_dir / "verdict.json", verdict.to_dict())
            outcome = verdict.verdict
            reasons = verdict.reasons
            if outcome == "KEEP" and config.limits.exceeded(
                campaign_usage + attempt_usage,
                time.monotonic() - campaign_started,
            ):
                outcome = "REJECT"
                reasons = (*reasons, "campaign_budget_exceeded")
            if verdict.verdict != "INVALID":
                fingerprint_receipt = {
                    "schema": CANDIDATE_FINGERPRINT_SCHEMA,
                    "fingerprint_sha256": candidate_fingerprint,
                    "candidate_sha": proposal.candidate_sha,
                    "contract_id": contract.contract_id,
                    "verdict_id": verdict.verdict_id,
                    "verdict": verdict.verdict,
                }
                prior_fingerprint = workspace.persist_candidate_fingerprint(
                    candidate_fingerprint,
                    fingerprint_receipt,
                )
                if prior_fingerprint is not None:
                    write_exclusive_json(
                        attempt_dir / "candidate-fingerprint.json",
                        {
                            "schema": CANDIDATE_FINGERPRINT_OBSERVATION_SCHEMA,
                            "status": "duplicate",
                            "fingerprint_sha256": candidate_fingerprint,
                            "fingerprint_ref": candidate_fingerprint_ref,
                            "candidate_sha": proposal.candidate_sha,
                            "prior": prior_fingerprint,
                        },
                    )
                    raise _DuplicateCandidateError(
                        candidate_fingerprint,
                        candidate_fingerprint_ref,
                    )
                write_exclusive_json(
                    attempt_dir / "candidate-fingerprint.json",
                    {
                        "schema": CANDIDATE_FINGERPRINT_OBSERVATION_SCHEMA,
                        "status": "recorded",
                        "fingerprint_sha256": candidate_fingerprint,
                        "fingerprint_ref": candidate_fingerprint_ref,
                        "candidate_sha": proposal.candidate_sha,
                        "receipt": fingerprint_receipt,
                    },
                )
            if outcome == "KEEP":
                next_head = proposal.candidate_sha
            if outcome != "INVALID":
                evaluator_feedback = artifacts.feedback
        except _DuplicateCandidateError:
            evaluator_feedback = FailureFeedback(("duplicate_candidate",))
            reasons = ("duplicate_candidate",)
            outcome = "REJECT"
        except (ContractError, OSError, SupervisorError) as exc:
            detail = " ".join(str(exc).split())[:2_000] or "invalid attempt"
            with suppress(OSError, SupervisorError):
                write_exclusive_json(
                    attempt_dir / "error.json",
                    {
                        "schema": ATTEMPT_ERROR_SCHEMA,
                        "error_type": type(exc).__name__,
                        "message": detail,
                    },
                )
            reasons = ("invalid_attempt",)
            outcome = "INVALID"
        finally:
            shutil.rmtree(worktree_root)
        return _AttemptResult(
            proposal=proposal,
            verdict=verdict,
            contract=contract,
            evaluator_feedback=evaluator_feedback,
            candidate_ref=candidate_ref,
            baseline_ref=baseline_ref,
            candidate_fingerprint=candidate_fingerprint,
            candidate_fingerprint_ref=candidate_fingerprint_ref,
            usage=attempt_usage,
            evidence_usage=attempt_evidence_usage,
            outcome=outcome,
            reasons=reasons,
            next_head=next_head,
            wall_seconds=time.monotonic() - attempt_started,
        )

    def run(self) -> SupervisorSummary:
        config = self.config
        config.validate()
        if not config.repository.is_dir() or not config.harness_root.is_dir():
            raise SupervisorError("repository and harness_root must exist")
        if _paths_overlap(config.state_dir, config.repository) or _paths_overlap(
            config.state_dir, config.harness_root
        ):
            raise SupervisorError("state_dir must be outside repository and harness_root")
        if config.state_dir.exists():
            raise SupervisorError("state_dir already exists; choose a fresh campaign")

        workspace = GitWorkspace(config.repository, config.campaign_id)
        workspace.validate_initial_head(config.initial_search_head_sha)
        config.state_dir.mkdir(parents=True)
        attempts_root = config.state_dir / "attempts"
        attempts_root.mkdir()
        write_exclusive_json(config.state_dir / "config.json", config.to_dict())
        workspace.initialize(config.initial_search_head_sha)

        zero = ResourceUsage(0.0, 0, 0, 0.0)
        usage = zero
        evidence_usage = zero
        head = config.initial_search_head_sha
        feedback: Mapping[str, Any] | None = (
            config.initial_feedback.to_dict() if config.initial_feedback is not None else None
        )
        previous_record: str | None = None
        counts = {"attempts": 0, "keeps": 0, "rejects": 0, "invalids": 0}
        invalid_streak = 0
        started = time.monotonic()
        stop_reason: str | None = None
        atomic_write_json(
            config.state_dir / "state.json",
            self._state(
                status="running",
                workspace=workspace,
                head=head,
                counts=counts,
                usage=usage,
                evidence_usage=evidence_usage,
                elapsed=0.0,
                record_id=None,
                stop_reason=None,
            ),
        )

        while stop_reason is None:
            elapsed = time.monotonic() - started
            stop_reason = self._limit(counts["attempts"], invalid_streak, usage, elapsed)
            if stop_reason:
                break
            workspace.assert_head(head)
            iteration = counts["attempts"] + 1
            attempt_id = f"{iteration:04d}-{uuid.uuid4().hex[:12]}"
            attempt_dir = attempts_root / attempt_id
            attempt_dir.mkdir()
            before = head
            result = self._execute_attempt(
                workspace,
                attempt_dir=attempt_dir,
                attempt_id=attempt_id,
                iteration=iteration,
                head=head,
                feedback=feedback,
                campaign_usage=usage,
                elapsed=elapsed,
                campaign_started=started,
            )
            proposal = result.proposal
            verdict = result.verdict
            contract = result.contract
            outcome = result.outcome
            reasons = result.reasons
            next_head = result.next_head
            attempt_usage = result.usage
            feedback_payload: dict[str, Any] = {
                "schema": SUPERVISOR_FEEDBACK_SCHEMA,
                "attempt_id": attempt_id,
                "outcome": outcome,
                "reasons": list(reasons),
                "search_head_sha": next_head,
            }
            if result.evaluator_feedback is not None:
                feedback_payload["evaluator"] = result.evaluator_feedback.to_dict()
            feedback_path = attempt_dir / "feedback.json"
            record_payload = {
                "schema": RECORD_SCHEMA,
                "timestamp": _utc_now(),
                "component": "plugins.crucible.supervisor",
                "kind": "train_attempt",
                "campaign_id": config.campaign_id,
                "attempt_id": attempt_id,
                "previous_record_id": previous_record,
                "proposal_id": proposal.proposal_id if proposal else None,
                "contract_id": contract.contract_id if contract else None,
                "verdict_id": verdict.verdict_id if verdict else None,
                "candidate_ref": result.candidate_ref,
                "baseline_ref": result.baseline_ref,
                "outcome": outcome,
                "reasons": list(reasons),
                "search_head_before": before,
                "search_head_after": next_head,
                "usage": result.evidence_usage.to_dict(),
                "marginal_usage": attempt_usage.to_dict(),
                "wall_seconds": result.wall_seconds,
            }
            if result.candidate_fingerprint is not None:
                record_payload["candidate_fingerprint"] = result.candidate_fingerprint
                record_payload["candidate_fingerprint_ref"] = result.candidate_fingerprint_ref
            record_id = _hash(record_payload)
            record = {**record_payload, "record_id": record_id}
            write_exclusive_json(feedback_path, feedback_payload)
            feedback = feedback_payload
            write_exclusive_json(attempt_dir / "record.json", record)
            if outcome == "KEEP":
                intent_path = attempt_dir / "search-ref.intent.json"
                receipt_path = attempt_dir / "search-ref.receipt.json"
                persist_intent(
                    intent_path,
                    RefIntent(
                        ref=workspace.search_ref,
                        expected_old_sha=head,
                        new_sha=next_head,
                        subject_id=record_id,
                        witness_ref=(f"refs/crucible/applied/{config.campaign_id}/{record_id}"),
                    ),
                )
                reconcile_ref_update(
                    config.repository,
                    intent_path=intent_path,
                    receipt_path=receipt_path,
                )
                head = next_head
            else:
                workspace.assert_head(head)
            append_jsonl(config.state_dir / "ledger.jsonl", record)
            previous_record = record_id
            counts["attempts"] += 1
            if outcome == "KEEP":
                counts["keeps"] += 1
                invalid_streak = 0
            elif outcome == "REJECT":
                counts["rejects"] += 1
                invalid_streak = 0
            else:
                counts["invalids"] += 1
                invalid_streak += 1
            usage = usage + attempt_usage
            evidence_usage = evidence_usage + result.evidence_usage
            atomic_write_json(
                config.state_dir / "state.json",
                self._state(
                    status="running",
                    workspace=workspace,
                    head=head,
                    counts=counts,
                    usage=usage,
                    evidence_usage=evidence_usage,
                    elapsed=time.monotonic() - started,
                    record_id=previous_record,
                    stop_reason=None,
                ),
            )
        final_elapsed = time.monotonic() - started
        workspace.assert_head(head)
        summary = SupervisorSummary(
            campaign_id=config.campaign_id,
            search_ref=workspace.search_ref,
            initial_search_head_sha=config.initial_search_head_sha,
            final_search_head_sha=head,
            attempts=counts["attempts"],
            keeps=counts["keeps"],
            rejects=counts["rejects"],
            invalids=counts["invalids"],
            stop_reason=stop_reason or "complete",
            usage=usage,
            evidence_usage=evidence_usage,
            elapsed_seconds=final_elapsed,
            state_dir=config.state_dir,
        )
        write_exclusive_json(config.state_dir / "summary.json", summary.to_dict())
        atomic_write_json(
            config.state_dir / "state.json",
            self._state(
                status="complete",
                workspace=workspace,
                head=head,
                counts=counts,
                usage=usage,
                evidence_usage=evidence_usage,
                elapsed=final_elapsed,
                record_id=previous_record,
                stop_reason=summary.stop_reason,
            ),
        )
        return summary


def run_supervisor(config_path: Path) -> SupervisorSummary:
    return PromotionSupervisor(SupervisorConfig.load(config_path)).run()
