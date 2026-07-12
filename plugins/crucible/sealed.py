"""One-shot, authority-neutral sealed promotion execution for Crucible."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol, cast

from .artifacts import contained_path, load_json_object, write_exclusive_json
from .bundle import PromotionBundle
from .contract import ContractError, ExperimentContract, validate_test_parent
from .evidence import EvidenceEnvelope, load_evidence
from .promotion import PromotionVerdict, decide
from .ref_journal import (
    RefIntent,
    RefReceipt,
    commit_ref_update,
    load_intent,
    reconcile_ref_update,
)

SEALED_PLAN_SCHEMA = "crucible.sealed-plan.v1"
SEALED_RESPONSE_SCHEMA = "crucible.sealed-evaluation.v1"
CORE_DECISION_SCHEMA = "crucible.core-promotion-decision.v1"

_PACK_CLAIM_SCHEMA = "crucible.sealed-pack-claim.v1"
_ATTEMPT_BURN_SCHEMA = "crucible.sealed-attempt-burn.v1"
_ATTESTATION_SCHEMA = "crucible.sealed-attestation.v1"
_INVALID_SCHEMA = "crucible.sealed-invalid-attempt.v1"
_ERROR_SCHEMA = "crucible.sealed-operator-error.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_INFRA_FAILURES = frozenset(
    {
        "evaluator_io_error",
        "evaluator_timeout",
        "orphaned_after_burn",
        "provider_unavailable",
        "tau2_infrastructure_error",
        "transport_interrupted",
    }
)
_TERMINAL_FAILURES = _INFRA_FAILURES | frozenset(
    {
        "artifact_validation_failed",
        "evidence_identity_invalid",
        "evidence_invalid",
    }
)


class SealedError(ContractError):
    """A sealed promotion cannot proceed without weakening its evidence."""


class SealedInfrastructureError(RuntimeError):
    """Closed infrastructure failure emitted by a trusted evaluator."""

    def __init__(self, failure_class: str) -> None:
        if failure_class not in _INFRA_FAILURES:
            raise ValueError(f"unsupported sealed infrastructure failure: {failure_class}")
        self.failure_class = failure_class
        super().__init__(failure_class)


def _hash(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise SealedError("sealed artifact must contain canonical JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SealedError("sealed attestation must contain canonical JSON values") from exc


def _keys(
    value: Mapping[str, Any],
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - allowed)
    if missing:
        raise SealedError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise SealedError(f"{field} has unknown fields: {', '.join(unknown)}")


def _identifier(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SealedError(f"{field} has an invalid canonical identifier")
    return value


def _sha(value: object, field: str) -> str:
    return _identifier(value, field, _SHA256)


def _git_sha(value: object, field: str) -> str:
    return _identifier(value, field, _GIT_SHA)


def _retries(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise SealedError("max_infra_retries must be zero for one-shot sealed evaluation")
    return value


def _timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SealedError("wall_timeout_seconds must be a positive finite number")
    result = float(value)
    if result <= 0 or not math.isfinite(result):
        raise SealedError("wall_timeout_seconds must be a positive finite number")
    return result


def _validate_evidence_ids(values: tuple[str | None, str | None, str | None]) -> int:
    provided = sum(value is not None for value in values)
    if provided not in {0, 3}:
        raise SealedError("sealed evidence identifiers are all-or-none")
    for index, value in enumerate(values):
        if value is not None:
            _sha(value, f"sealed evidence identifier {index}")
    return provided


@dataclass(frozen=True)
class SealedPlan:
    """Frozen identity and timeout for one candidate and one-shot sealed pack."""

    bundle_id: str
    test_contract_id: str
    test_task_pack_sha256: str
    baseline_sha: str
    candidate_sha: str
    eligible_ref: str
    expected_old_sha: str
    max_infra_retries: int
    wall_timeout_seconds: float

    def __post_init__(self) -> None:
        for field in ("bundle_id", "test_contract_id", "test_task_pack_sha256"):
            _sha(getattr(self, field), f"sealed plan {field}")
        _git_sha(self.baseline_sha, "sealed plan baseline_sha")
        _git_sha(self.candidate_sha, "sealed plan candidate_sha")
        _git_sha(self.expected_old_sha, "sealed plan expected_old_sha")
        if self.baseline_sha == self.candidate_sha:
            raise SealedError("sealed candidate must differ from baseline")
        if not self.eligible_ref.startswith("refs/crucible/eligible/"):
            raise SealedError("sealed plan may publish only refs/crucible/eligible/*")
        _retries(self.max_infra_retries)
        _timeout(self.wall_timeout_seconds)
        RefIntent(
            ref=self.eligible_ref,
            expected_old_sha=self.expected_old_sha,
            new_sha=self.candidate_sha,
            subject_id=self.bundle_id,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SEALED_PLAN_SCHEMA,
            "bundle_id": self.bundle_id,
            "test_contract_id": self.test_contract_id,
            "test_task_pack_sha256": self.test_task_pack_sha256,
            "baseline_sha": self.baseline_sha,
            "candidate_sha": self.candidate_sha,
            "eligible_ref": self.eligible_ref,
            "expected_old_sha": self.expected_old_sha,
            "max_infra_retries": self.max_infra_retries,
            "wall_timeout_seconds": self.wall_timeout_seconds,
        }

    @property
    def plan_id(self) -> str:
        return _hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "plan_id": self.plan_id}

    @classmethod
    def from_mapping(cls, value: object) -> SealedPlan:
        if not isinstance(value, Mapping):
            raise SealedError("sealed plan must be an object")
        required = {
            "baseline_sha",
            "bundle_id",
            "candidate_sha",
            "eligible_ref",
            "expected_old_sha",
            "max_infra_retries",
            "schema",
            "test_contract_id",
            "test_task_pack_sha256",
            "wall_timeout_seconds",
        }
        _keys(value, "sealed plan", required, {"plan_id"})
        if value.get("schema") != SEALED_PLAN_SCHEMA:
            raise SealedError(f"sealed plan schema must be {SEALED_PLAN_SCHEMA!r}")
        eligible_ref = value.get("eligible_ref")
        if not isinstance(eligible_ref, str):
            raise SealedError("eligible_ref must be a string")
        plan = cls(
            bundle_id=_sha(value.get("bundle_id"), "sealed plan bundle_id"),
            test_contract_id=_sha(value.get("test_contract_id"), "sealed plan test_contract_id"),
            test_task_pack_sha256=_sha(
                value.get("test_task_pack_sha256"), "sealed plan test_task_pack_sha256"
            ),
            baseline_sha=_git_sha(value.get("baseline_sha"), "sealed plan baseline_sha"),
            candidate_sha=_git_sha(value.get("candidate_sha"), "sealed plan candidate_sha"),
            eligible_ref=eligible_ref,
            expected_old_sha=_git_sha(
                value.get("expected_old_sha"), "sealed plan expected_old_sha"
            ),
            max_infra_retries=_retries(value.get("max_infra_retries")),
            wall_timeout_seconds=_timeout(value.get("wall_timeout_seconds")),
        )
        supplied = value.get("plan_id")
        if supplied is not None and _sha(supplied, "sealed plan plan_id") != plan.plan_id:
            raise SealedError("plan_id does not match the canonical sealed plan")
        return plan


@dataclass(frozen=True)
class CorePromotionDecision:
    """Terminal sealed verdict; ELIGIBLE deliberately has no release authority."""

    plan_id: str
    bundle_id: str
    test_contract_id: str
    decision: Literal["ELIGIBLE", "REJECT", "INVALID"]
    release_authority: Literal["none"]
    reasons: tuple[str, ...]
    attempts_consumed: int
    baseline_evidence_id: str | None = None
    candidate_evidence_id: str | None = None
    test_verdict_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("plan_id", "bundle_id", "test_contract_id"):
            _sha(getattr(self, field), f"core decision {field}")
        if self.decision not in {"ELIGIBLE", "REJECT", "INVALID"}:
            raise SealedError("core decision is invalid")
        if self.release_authority != "none":
            raise SealedError("core decision release_authority must be 'none'")
        if self.attempts_consumed <= 0:
            raise SealedError("attempts_consumed must be positive")
        identifiers = (
            self.baseline_evidence_id,
            self.candidate_evidence_id,
            self.test_verdict_id,
        )
        provided = _validate_evidence_ids(identifiers)
        if self.decision in {"ELIGIBLE", "REJECT"} and provided != 3:
            raise SealedError("ELIGIBLE and REJECT require sealed evidence")
        if self.decision == "ELIGIBLE" and self.reasons:
            raise SealedError("ELIGIBLE cannot contain failure reasons")
        if self.decision == "REJECT" and self.reasons != ("sealed_reject",):
            raise SealedError("REJECT must expose only the closed sealed_reject reason")
        if self.decision == "INVALID" and (
            len(self.reasons) != 1 or self.reasons[0] not in _TERMINAL_FAILURES
        ):
            raise SealedError("INVALID must expose one closed failure class")

    def payload(self) -> dict[str, Any]:
        return {
            "schema": CORE_DECISION_SCHEMA,
            "plan_id": self.plan_id,
            "bundle_id": self.bundle_id,
            "test_contract_id": self.test_contract_id,
            "decision": self.decision,
            "release_authority": self.release_authority,
            "reasons": list(self.reasons),
            "attempts_consumed": self.attempts_consumed,
            "baseline_evidence_id": self.baseline_evidence_id,
            "candidate_evidence_id": self.candidate_evidence_id,
            "test_verdict_id": self.test_verdict_id,
        }

    @property
    def decision_id(self) -> str:
        return _hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "decision_id": self.decision_id}

    @classmethod
    def from_mapping(cls, value: object) -> CorePromotionDecision:
        if not isinstance(value, Mapping):
            raise SealedError("core decision must be an object")
        required = {
            "attempts_consumed",
            "baseline_evidence_id",
            "bundle_id",
            "candidate_evidence_id",
            "decision",
            "plan_id",
            "reasons",
            "release_authority",
            "schema",
            "test_contract_id",
            "test_verdict_id",
        }
        _keys(value, "core decision", required, {"decision_id"})
        if value.get("schema") != CORE_DECISION_SCHEMA:
            raise SealedError(f"core decision schema must be {CORE_DECISION_SCHEMA!r}")
        outcome = value.get("decision")
        if outcome not in {"ELIGIBLE", "REJECT", "INVALID"}:
            raise SealedError("core decision is invalid")
        reasons = value.get("reasons")
        if not isinstance(reasons, list) or not all(
            isinstance(reason, str) and reason for reason in reasons
        ):
            raise SealedError("core decision reasons must be a string list")
        attempts = value.get("attempts_consumed")
        if isinstance(attempts, bool) or not isinstance(attempts, int):
            raise SealedError("attempts_consumed must be an integer")

        def optional_id(field: str) -> str | None:
            item = value.get(field)
            return None if item is None else _sha(item, f"core decision {field}")

        decision = cls(
            plan_id=_sha(value.get("plan_id"), "core decision plan_id"),
            bundle_id=_sha(value.get("bundle_id"), "core decision bundle_id"),
            test_contract_id=_sha(value.get("test_contract_id"), "core decision test_contract_id"),
            decision=cast(Literal["ELIGIBLE", "REJECT", "INVALID"], outcome),
            release_authority=cast(Literal["none"], value.get("release_authority")),
            reasons=tuple(reasons),
            attempts_consumed=attempts,
            baseline_evidence_id=optional_id("baseline_evidence_id"),
            candidate_evidence_id=optional_id("candidate_evidence_id"),
            test_verdict_id=optional_id("test_verdict_id"),
        )
        supplied = value.get("decision_id")
        if supplied is not None and _sha(supplied, "decision_id") != decision.decision_id:
            raise SealedError("decision_id does not match the canonical core decision")
        return decision


@dataclass(frozen=True)
class SealedEvaluationArtifacts:
    baseline: EvidenceEnvelope
    candidate: EvidenceEnvelope

    @classmethod
    def load(
        cls,
        response: Path,
        *,
        root: Path,
        plan: SealedPlan,
        contract: ExperimentContract,
        attempt: int,
    ) -> SealedEvaluationArtifacts:
        root = root.resolve()
        if response.is_symlink() or not response.resolve().is_relative_to(root):
            raise SealedError("sealed response must be a contained regular file")
        row = load_json_object(response.resolve(), "sealed response", max_bytes=1024 * 1024)
        required = {
            "attempt_number",
            "baseline",
            "baseline_raw",
            "candidate",
            "candidate_raw",
            "contract_id",
            "plan_id",
            "schema",
        }
        _keys(row, "sealed response", required)
        expected = {
            "schema": SEALED_RESPONSE_SCHEMA,
            "plan_id": plan.plan_id,
            "contract_id": contract.contract_id,
            "attempt_number": attempt,
        }
        if any(row.get(field) != value for field, value in expected.items()):
            raise SealedError("sealed response identity does not match the attempt")
        paths = _response_paths(row, root)
        baseline = load_evidence(paths["baseline"])
        candidate = load_evidence(paths["candidate"])
        if _file_hash(paths["baseline_raw"]) != baseline.raw_artifact_sha256:
            raise SealedError("baseline raw hash does not match sealed evidence")
        if _file_hash(paths["candidate_raw"]) != candidate.raw_artifact_sha256:
            raise SealedError("candidate raw hash does not match sealed evidence")
        return cls(baseline, candidate)


class SealedEvaluator(Protocol):
    def evaluate(
        self,
        plan: SealedPlan,
        contract: ExperimentContract,
        *,
        attempt_number: int,
        evaluation_dir: Path,
        timeout: float,
    ) -> Path: ...


def _response_paths(row: Mapping[str, Any], root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for field in ("baseline", "candidate", "baseline_raw", "candidate_raw"):
        raw = row.get(field)
        if not isinstance(raw, str) or not raw:
            raise SealedError(f"sealed response {field} must be a relative path")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise SealedError(f"sealed response {field} escapes the attempt")
        cursor = root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise SealedError(f"sealed response {field} traverses a symlink")
        result[field] = contained_path(root, raw, field)
    if len(set(result.values())) != len(result):
        raise SealedError("sealed response paths must be distinct")
    return result


def _file_hash(path: Path) -> str:
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_size > 512 * 1024 * 1024:
            raise SealedError("sealed raw artifact must be a bounded regular file")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise SealedError(f"cannot hash sealed raw artifact: {exc}") from exc


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise SealedError(f"sealed path is not a directory: {path}")
        return
    _mkdir(path.parent)
    path.mkdir()
    _fsync_dir(path.parent)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    _mkdir(path.parent)
    try:
        write_exclusive_json(path, payload)
    except ContractError as exc:
        raise SealedError(str(exc)) from exc
    _fsync_dir(path.parent)


def _load_exact(path: Path, field: str, expected: Mapping[str, Any]) -> None:
    if load_json_object(path, field, max_bytes=1024 * 1024) != expected:
        raise SealedError(f"{field} belongs to a different sealed plan")


def _git_common_dir(repository: Path) -> Path:
    executable = shutil.which("git")
    if executable is None:
        raise SealedError("git is required for sealed promotion")
    result = subprocess.run(  # noqa: S603 - fixed executable and argv, no shell
        [executable, "rev-parse", "--git-common-dir"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise SealedError("sealed repository has no git-common-dir")
    value = Path(result.stdout.strip())
    path = value if value.is_absolute() else repository / value
    return path.resolve()


def _git(
    repository: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    executable = shutil.which("git")
    if executable is None:
        raise SealedError("git is required for sealed promotion")
    result = subprocess.run(  # noqa: S603 - fixed executable and argv, no shell
        [executable, *args],
        cwd=repository,
        check=False,
        capture_output=True,
        input=input_bytes,
    )
    if check and result.returncode != 0:
        detail = " ".join(result.stderr.decode("utf-8", errors="replace").split())[:2_000]
        raise SealedError(detail or "sealed Git operation failed")
    return result


@contextmanager
def _lock(state: Path) -> Iterator[None]:
    descriptor = os.open(state / ".sealed.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SealedError("sealed plan is already active") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@dataclass(frozen=True)
class _Invalid:
    attempt: int
    failure: str


class SealedSupervisor:
    """Execute one frozen candidate against one globally burned test pack."""

    def __init__(
        self,
        *,
        repository: Path,
        state_dir: Path,
        plan: SealedPlan,
        train_attempt_dir: Path,
        test_contract: ExperimentContract,
        evaluator: SealedEvaluator,
    ) -> None:
        self.repository = repository.resolve()
        self.state_dir = state_dir.resolve()
        self.plan = plan
        self.train_attempt_dir = train_attempt_dir.resolve()
        self.test_contract = test_contract
        self.evaluator = evaluator
        self._bundle: PromotionBundle | None = None

    @property
    def bundle(self) -> PromotionBundle:
        if self._bundle is None:  # pragma: no cover - run ordering invariant
            raise AssertionError("sealed train bundle has not been rebuilt")
        return self._bundle

    @property
    def global_pack_dir(self) -> Path:
        return (
            _git_common_dir(self.repository)
            / "crucible"
            / "sealed-packs"
            / self.plan.test_task_pack_sha256
        )

    @property
    def global_claim_path(self) -> Path:
        return self.global_pack_dir / "claim.json"

    @property
    def global_attempt_dir(self) -> Path:
        return self.global_pack_dir / "attempt"

    @property
    def global_burn_path(self) -> Path:
        return self.global_attempt_dir / "burn.json"

    @property
    def global_decision_path(self) -> Path:
        return self.global_pack_dir / "decision.json"

    @property
    def attestation_ref(self) -> str:
        return f"refs/crucible/attestations/{self.plan.test_task_pack_sha256}"

    @property
    def decision_path(self) -> Path:
        return self.state_dir / "decision.json"

    @property
    def publication_receipt_path(self) -> Path:
        return self.state_dir / "publication" / "receipt.json"

    def _read_attestation_ref(self) -> str | None:
        result = _git(
            self.repository,
            "rev-parse",
            "--verify",
            "--quiet",
            self.attestation_ref,
            check=False,
        )
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            raise SealedError("cannot inspect sealed attestation ref")
        return _git_sha(
            result.stdout.decode("ascii").strip(),
            "sealed attestation object",
        )

    def _attestation_identity(self) -> dict[str, str]:
        return {
            "schema": _ATTESTATION_SCHEMA,
            "plan_id": self.plan.plan_id,
            "bundle_id": self.bundle.bundle_id,
            "test_contract_id": self.test_contract.contract_id,
            "test_task_pack_sha256": self.test_contract.task_pack_sha256,
        }

    def _anchor_attestation(self, payload: Mapping[str, Any]) -> None:
        encoded = _canonical_bytes(payload)
        object_id = (
            _git(
                self.repository,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=encoded,
            )
            .stdout.decode("ascii")
            .strip()
        )
        _git_sha(object_id, "sealed attestation object")
        observed = self._read_attestation_ref()
        if observed is None:
            result = _git(
                self.repository,
                "update-ref",
                "--no-deref",
                self.attestation_ref,
                object_id,
                "0" * 40,
                check=False,
            )
            if result.returncode != 0:
                observed = self._read_attestation_ref()
                if observed != object_id:
                    raise SealedError("sealed attestation ref was claimed by another result")
        elif observed != object_id:
            raise SealedError("sealed attestation cannot replace the first result")

    def _load_attestation(self) -> dict[str, Any] | None:
        object_id = self._read_attestation_ref()
        if object_id is None:
            return None
        object_type = _git(self.repository, "cat-file", "-t", object_id).stdout.decode().strip()
        if object_type != "blob":
            raise SealedError("sealed attestation ref must point to a Git blob")
        raw = _git(self.repository, "cat-file", "-p", object_id).stdout
        if len(raw) > 64 * 1024 * 1024:
            raise SealedError("sealed attestation blob exceeds 64 MiB")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SealedError("sealed attestation blob is not canonical JSON") from exc
        if not isinstance(value, dict) or _canonical_bytes(value) != raw:
            raise SealedError("sealed attestation blob is not canonical")
        return value

    def _validate(self) -> None:
        if not self.repository.is_dir():
            raise SealedError("sealed repository does not exist")
        if not self.train_attempt_dir.is_dir():
            raise SealedError("sealed train attempt directory does not exist")
        if SealedPlan.from_mapping(self.plan.to_dict()) != self.plan:
            raise SealedError("sealed plan is not canonical")
        bundle = PromotionBundle.build_from_attempt(self.repository, self.train_attempt_dir)
        parent = ExperimentContract.from_mapping(
            load_json_object(self.train_attempt_dir / "contract.json", "train contract")
        )
        test = ExperimentContract.from_mapping(self.test_contract.to_dict())
        validate_test_parent(test, parent)
        expected = (
            (bundle.train_contract_id, parent.contract_id, "bundle train contract"),
            (bundle.train_task_pack_sha256, parent.task_pack_sha256, "bundle train pack"),
            (bundle.baseline_sha, parent.baseline_sha, "bundle baseline"),
            (bundle.candidate_sha, parent.candidate_sha, "bundle candidate"),
            (self.plan.bundle_id, bundle.bundle_id, "plan bundle"),
            (self.plan.test_contract_id, test.contract_id, "plan test contract"),
            (self.plan.test_task_pack_sha256, test.task_pack_sha256, "plan test pack"),
            (self.plan.baseline_sha, test.baseline_sha, "plan baseline"),
            (self.plan.candidate_sha, test.candidate_sha, "plan candidate"),
        )
        mismatch = next((label for observed, wanted, label in expected if observed != wanted), None)
        if mismatch:
            raise SealedError(f"sealed identity mismatch: {mismatch}")
        if self.plan.eligible_ref != f"refs/crucible/eligible/{bundle.campaign_id}":
            raise SealedError("eligible ref must match the train campaign")
        self._bundle = bundle

    def _initialize_local(self) -> None:
        plan_path = self.state_dir / "plan.json"
        if plan_path.exists() or plan_path.is_symlink():
            if SealedPlan.from_mapping(load_json_object(plan_path, "sealed plan")) != self.plan:
                raise SealedError("sealed state belongs to a different plan")
        else:
            unexpected = [item.name for item in self.state_dir.iterdir()]
            if unexpected:
                raise SealedError("sealed state has artifacts but no plan")
            _write(plan_path, self.plan.to_dict())

    def _claim_payload(self) -> dict[str, str]:
        return {
            "schema": _PACK_CLAIM_SCHEMA,
            "plan_id": self.plan.plan_id,
            "bundle_id": self.bundle.bundle_id,
            "test_contract_id": self.test_contract.contract_id,
            "test_task_pack_sha256": self.test_contract.task_pack_sha256,
            "baseline_sha": self.plan.baseline_sha,
            "candidate_sha": self.plan.candidate_sha,
        }

    def _claim(self) -> None:
        expected = self._claim_payload()
        local = self.state_dir / "claim.json"
        if self.global_claim_path.exists() or self.global_claim_path.is_symlink():
            _load_exact(self.global_claim_path, "global sealed-pack claim", expected)
        else:
            if local.exists() or local.is_symlink():
                raise SealedError("global sealed-pack claim is missing after execution began")
            unexpected = [
                item.name for item in self.global_pack_dir.iterdir() if item.name != ".sealed.lock"
            ]
            if unexpected:
                raise SealedError("global sealed-pack state has artifacts but no claim")
            _write(self.global_claim_path, expected)
        if local.exists() or local.is_symlink():
            _load_exact(local, "local sealed-pack claim", expected)
        else:
            _write(local, expected)

    def _burn_payload(self) -> dict[str, Any]:
        return {
            "schema": _ATTEMPT_BURN_SCHEMA,
            "plan_id": self.plan.plan_id,
            "bundle_id": self.bundle.bundle_id,
            "test_contract_id": self.test_contract.contract_id,
            "attempt_number": 1,
            "test_task_pack_sha256": self.plan.test_task_pack_sha256,
        }

    def _burn_attempt(self) -> tuple[Path, Path]:
        if self.global_attempt_dir.exists() or self.global_attempt_dir.is_symlink():
            raise SealedError("sealed test pack already consumed its one attempt")
        if self.global_decision_path.exists() or self.global_decision_path.is_symlink():
            raise SealedError("global sealed decision exists without an attempt")
        _mkdir(self.global_attempt_dir)
        _write(self.global_burn_path, self._burn_payload())
        evaluation = self.global_attempt_dir / "evaluation"
        _mkdir(evaluation)
        return self.global_attempt_dir, evaluation

    def _check_burn(self) -> None:
        _load_exact(self.global_burn_path, "global sealed attempt burn", self._burn_payload())

    def _operator_error(self, root: Path, failure: str, exc: BaseException, name: str) -> None:
        path = root / name
        if path.exists() or path.is_symlink():
            return
        message = " ".join(str(exc).split())[:2_000] or failure
        _write(
            path,
            {
                "schema": _ERROR_SCHEMA,
                "plan_id": self.plan.plan_id,
                "failure_class": failure,
                "error_type": type(exc).__name__,
                "message": message,
            },
        )

    def _write_invalid(self, failure: str) -> _Invalid:
        if failure not in _TERMINAL_FAILURES:
            raise SealedError(f"unsupported sealed terminal failure: {failure}")
        invalid = _Invalid(1, failure)
        path = self.global_attempt_dir / "invalid.json"
        payload = {
            "schema": _INVALID_SCHEMA,
            "plan_id": self.plan.plan_id,
            "attempt_number": 1,
            "failure_class": failure,
            "retryable": False,
        }
        if path.exists() or path.is_symlink():
            loaded = self._load_invalid()
            if loaded != invalid:
                raise SealedError("global sealed invalid result cannot be replaced")
            return loaded
        _write(path, payload)
        return invalid

    def _load_invalid(self) -> _Invalid | None:
        path = self.global_attempt_dir / "invalid.json"
        if not path.exists() and not path.is_symlink():
            return None
        row = load_json_object(path, "sealed invalid attempt")
        required = {"schema", "plan_id", "attempt_number", "failure_class", "retryable"}
        _keys(row, "sealed invalid attempt", required)
        failure = row.get("failure_class")
        retryable = row.get("retryable")
        if (
            row.get("schema") != _INVALID_SCHEMA
            or row.get("plan_id") != self.plan.plan_id
            or row.get("attempt_number") != 1
            or not isinstance(failure, str)
            or failure not in _TERMINAL_FAILURES
            or not isinstance(retryable, bool)
            or retryable
        ):
            raise SealedError("sealed invalid attempt is malformed")
        return _Invalid(1, failure)

    def _decision(
        self,
        outcome: Literal["ELIGIBLE", "REJECT", "INVALID"],
        attempts: int,
        reason: str | None,
        verdict: PromotionVerdict | None = None,
    ) -> CorePromotionDecision:
        reasons = () if reason is None else (reason,)
        return CorePromotionDecision(
            plan_id=self.plan.plan_id,
            bundle_id=self.bundle.bundle_id,
            test_contract_id=self.test_contract.contract_id,
            decision=outcome,
            release_authority="none",
            reasons=reasons,
            attempts_consumed=attempts,
            baseline_evidence_id=verdict.baseline_evidence_id if verdict else None,
            candidate_evidence_id=verdict.candidate_evidence_id if verdict else None,
            test_verdict_id=verdict.verdict_id if verdict else None,
        )

    def _anchor_invalid(self, failure: str) -> None:
        if failure not in _TERMINAL_FAILURES:
            raise SealedError(f"unsupported sealed terminal failure: {failure}")
        self._anchor_attestation(
            {
                **self._attestation_identity(),
                "kind": "invalid",
                "failure_class": failure,
            }
        )

    def _anchor_verdict(
        self,
        baseline: EvidenceEnvelope,
        candidate: EvidenceEnvelope,
        verdict: PromotionVerdict,
    ) -> None:
        self._anchor_attestation(
            {
                **self._attestation_identity(),
                "kind": "verdict",
                "baseline": baseline.to_dict(),
                "candidate": candidate.to_dict(),
                "verdict": verdict.to_dict(),
            }
        )

    def _attested_result(
        self,
    ) -> tuple[
        str | None, PromotionVerdict | None, EvidenceEnvelope | None, EvidenceEnvelope | None
    ]:
        row = self._load_attestation()
        if row is None:
            return None, None, None, None
        identity = self._attestation_identity()
        if any(row.get(field) != value for field, value in identity.items()):
            raise SealedError("sealed attestation belongs to a different plan")
        kind = row.get("kind")
        if kind == "invalid":
            _keys(
                row,
                "sealed invalid attestation",
                set(identity) | {"kind", "failure_class"},
            )
            failure = row.get("failure_class")
            if not isinstance(failure, str) or failure not in _TERMINAL_FAILURES:
                raise SealedError("sealed invalid attestation has an unsupported failure")
            return failure, None, None, None
        if kind != "verdict":
            raise SealedError("sealed attestation kind is invalid")
        _keys(
            row,
            "sealed verdict attestation",
            set(identity) | {"kind", "baseline", "candidate", "verdict"},
        )
        baseline = EvidenceEnvelope.from_mapping(row.get("baseline"))
        candidate = EvidenceEnvelope.from_mapping(row.get("candidate"))
        saved = PromotionVerdict.from_mapping(row.get("verdict"))
        recomputed = decide(self.test_contract, baseline, candidate)
        if saved.verdict_id != recomputed.verdict_id or saved.stage != "test":
            raise SealedError("sealed attestation verdict does not match its evidence")
        return None, recomputed, baseline, candidate

    def _persist_decision(self, decision: CorePromotionDecision) -> CorePromotionDecision:
        for path, field in (
            (self.global_decision_path, "global core decision"),
            (self.decision_path, "local core decision mirror"),
        ):
            if path.exists() or path.is_symlink():
                current = CorePromotionDecision.from_mapping(load_json_object(path, field))
                if current != decision:
                    raise SealedError(f"{field} cannot replace recomputed terminal decision")
            else:
                _write(path, decision.to_dict())
        return decision

    def _resolved_ref(self, ref: str) -> str:
        executable = shutil.which("git")
        if executable is None:  # pragma: no cover - checked by bundle path
            raise SealedError("git is required for sealed publication")
        result = subprocess.run(  # noqa: S603 - fixed executable and argv, no shell
            [executable, "rev-parse", "--verify", ref],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SealedError("eligible ref does not resolve after publication")
        return result.stdout.strip()

    def _publish(self, decision: CorePromotionDecision) -> None:
        if decision.decision != "ELIGIBLE":
            return
        root = self.state_dir / "publication"
        _mkdir(root)
        intent_path, receipt_path = root / "intent.json", root / "receipt.json"
        intent = RefIntent(
            ref=self.plan.eligible_ref,
            expected_old_sha=self.plan.expected_old_sha,
            new_sha=self.plan.candidate_sha,
            subject_id=decision.decision_id,
        )
        if intent_path.exists() or intent_path.is_symlink():
            if load_intent(intent_path) != intent:
                raise SealedError("publication intent does not match the terminal decision")
            receipt = reconcile_ref_update(
                self.repository, intent_path=intent_path, receipt_path=receipt_path
            )
        else:
            receipt = commit_ref_update(
                self.repository,
                intent,
                intent_path=intent_path,
                receipt_path=receipt_path,
            )
        if receipt != RefReceipt.from_intent(intent):
            raise SealedError("publication receipt does not match the terminal decision")
        if self._resolved_ref(intent.ref) != intent.new_sha:
            raise SealedError("eligible ref drifted from the sealed candidate")

    def _terminal(self) -> CorePromotionDecision | None:
        if not self.global_attempt_dir.exists() and not self.global_attempt_dir.is_symlink():
            if self._read_attestation_ref() is not None:
                raise SealedError("sealed attestation has no burned attempt")
            if self.global_decision_path.exists() or self.global_decision_path.is_symlink():
                raise SealedError("global sealed decision has no burned attempt")
            if self.decision_path.exists() or self.decision_path.is_symlink():
                raise SealedError("local sealed decision has no global burned attempt")
            return None
        if self.global_attempt_dir.is_symlink() or not self.global_attempt_dir.is_dir():
            raise SealedError("global sealed attempt is not a directory")
        self._check_burn()
        failure, verdict, baseline, candidate = self._attested_result()
        if failure is None and verdict is None:
            failure = "orphaned_after_burn"
            self._anchor_invalid(failure)

        invalid = self._load_invalid()
        if failure is not None:
            if invalid is None:
                invalid = self._write_invalid(failure)
            elif invalid.failure != failure:
                raise SealedError("sealed invalid mirror contradicts Git attestation")
            decision = self._decision("INVALID", 1, failure)
        elif verdict is None:  # pragma: no cover - attestation tuple invariant
            raise AssertionError("sealed attestation has neither failure nor verdict")
        elif verdict.verdict == "INVALID":
            if baseline is None or candidate is None:  # pragma: no cover - tuple invariant
                raise AssertionError("sealed invalid verdict has no evidence")
            expected_failure = self._invalid_evidence(verdict, baseline, candidate)
            if invalid is None:
                invalid = self._write_invalid(expected_failure)
            elif invalid.failure != expected_failure:
                raise SealedError("sealed invalid result does not match attested evidence")
            decision = self._decision("INVALID", 1, invalid.failure)
        else:
            if invalid is not None:
                raise SealedError("sealed semantic verdict conflicts with invalid result")
            outcome: Literal["ELIGIBLE", "REJECT"] = (
                "ELIGIBLE" if verdict.verdict == "KEEP" else "REJECT"
            )
            reason = None if outcome == "ELIGIBLE" else "sealed_reject"
            decision = self._decision(outcome, 1, reason, verdict)

        decision = self._persist_decision(decision)
        self._publish(decision)
        return decision

    @staticmethod
    def _invalid_evidence(
        verdict: PromotionVerdict, baseline: EvidenceEnvelope, candidate: EvidenceEnvelope
    ) -> str:
        if any(reason.startswith("identity_mismatch:") for reason in verdict.reasons):
            return "evidence_identity_invalid"
        failures = {
            evidence.failure_class
            for evidence in (baseline, candidate)
            if evidence.failure_class is not None
        }
        if len(failures) == 1 and next(iter(failures)) in _INFRA_FAILURES:
            return next(iter(failures))
        return "evidence_invalid"

    def _evaluate(self, attempt: Path, evaluation: Path) -> None:
        try:
            response = self.evaluator.evaluate(
                self.plan,
                self.test_contract,
                attempt_number=1,
                evaluation_dir=evaluation,
                timeout=self.plan.wall_timeout_seconds,
            )
            artifacts = SealedEvaluationArtifacts.load(
                response,
                root=evaluation,
                plan=self.plan,
                contract=self.test_contract,
                attempt=1,
            )
        except SealedInfrastructureError as exc:
            self._anchor_invalid(exc.failure_class)
            self._write_invalid(exc.failure_class)
            return
        except TimeoutError as exc:
            self._operator_error(attempt, "evaluator_timeout", exc, "error.json")
            self._anchor_invalid("evaluator_timeout")
            self._write_invalid("evaluator_timeout")
            return
        except OSError as exc:
            self._operator_error(attempt, "evaluator_io_error", exc, "error.json")
            self._anchor_invalid("evaluator_io_error")
            self._write_invalid("evaluator_io_error")
            return
        except ContractError as exc:
            self._operator_error(attempt, "artifact_validation_failed", exc, "error.json")
            self._anchor_invalid("artifact_validation_failed")
            self._write_invalid("artifact_validation_failed")
            return
        verdict = decide(self.test_contract, artifacts.baseline, artifacts.candidate)
        self._anchor_verdict(artifacts.baseline, artifacts.candidate, verdict)
        _write(attempt / "baseline.attested.json", artifacts.baseline.to_dict())
        _write(attempt / "candidate.attested.json", artifacts.candidate.to_dict())
        _write(attempt / "verdict.json", verdict.to_dict())
        if verdict.verdict == "INVALID":
            self._write_invalid(
                self._invalid_evidence(verdict, artifacts.baseline, artifacts.candidate)
            )

    def run(self) -> CorePromotionDecision:
        _mkdir(self.state_dir)
        try:
            self._validate()
        except ContractError as exc:
            self._operator_error(
                self.state_dir, "preflight_validation_failed", exc, "preflight-error.json"
            )
            raise
        _mkdir(self.global_pack_dir)
        with _lock(self.global_pack_dir):
            self._initialize_local()
            self._claim()
            terminal = self._terminal()
            if terminal:
                return terminal
            attempt, evaluation = self._burn_attempt()
            self._evaluate(attempt, evaluation)
            terminal = self._terminal()
            if terminal is None:  # pragma: no cover - burn guarantees terminal derivation
                raise AssertionError("sealed attempt did not produce a terminal decision")
            return terminal


__all__ = [
    "CORE_DECISION_SCHEMA",
    "SEALED_PLAN_SCHEMA",
    "SEALED_RESPONSE_SCHEMA",
    "CorePromotionDecision",
    "SealedError",
    "SealedEvaluationArtifacts",
    "SealedEvaluator",
    "SealedInfrastructureError",
    "SealedPlan",
    "SealedSupervisor",
]
