"""Durable, recoverable compare-and-swap updates for private Crucible refs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import load_json_object, write_exclusive_json
from .contract import ContractError

INTENT_SCHEMA = "crucible.ref-intent.v2"
RECEIPT_SCHEMA = "crucible.ref-receipt.v2"

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ALLOWED_PREFIXES = ("refs/crucible/search/", "refs/crucible/eligible/")
_WITNESS_PREFIX = "refs/crucible/applied/"
_ZERO_SHA = "0" * 40


class RefJournalError(ContractError):
    """A private ref transaction is malformed or cannot be reconciled."""


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_keys(
    value: Mapping[str, Any],
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - allowed)
    if missing:
        raise RefJournalError(f"{field} is missing fields: {', '.join(missing)}")
    if unknown:
        raise RefJournalError(f"{field} has unknown fields: {', '.join(unknown)}")


def _identifier(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RefJournalError(f"{field} has an invalid canonical identifier")
    return value


def _git_sha(value: object, field: str) -> str:
    return _identifier(value, field, _GIT_SHA)


def _sha256(value: object, field: str) -> str:
    return _identifier(value, field, _SHA256)


def _ref_name(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(_ALLOWED_PREFIXES):
        raise RefJournalError("ref must be below refs/crucible/search/ or refs/crucible/eligible/")
    prefix = next(prefix for prefix in _ALLOWED_PREFIXES if value.startswith(prefix))
    suffix = value.removeprefix(prefix)
    parts = PurePosixPath(suffix).parts
    forbidden = set(" ~^:?*[\\")
    if (
        not suffix
        or suffix.startswith("/")
        or suffix.endswith(("/", ".", ".lock"))
        or "//" in suffix
        or ".." in suffix
        or "@{" in suffix
        or any(
            part in {"", ".", ".."} or part.startswith(".") or part.endswith((".", ".lock"))
            for part in parts
        )
        or any(ord(char) < 32 or ord(char) == 127 or char in forbidden for char in suffix)
    ):
        raise RefJournalError("ref is not a canonical private Crucible ref")
    return value


def _applied_ref(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(_WITNESS_PREFIX):
        raise RefJournalError("witness_ref must be below refs/crucible/applied/")
    suffix = value.removeprefix(_WITNESS_PREFIX)
    parts = PurePosixPath(suffix).parts
    forbidden = set(" ~^:?*[\\")
    if (
        len(parts) < 2
        or not suffix
        or suffix.startswith("/")
        or suffix.endswith(("/", ".", ".lock"))
        or "//" in suffix
        or ".." in suffix
        or "@{" in suffix
        or any(
            part in {"", ".", ".."} or part.startswith(".") or part.endswith((".", ".lock"))
            for part in parts
        )
        or any(ord(char) < 32 or ord(char) == 127 or char in forbidden for char in suffix)
    ):
        raise RefJournalError("witness_ref is not a canonical applied ref")
    return value


def _optional_applied_ref(value: object) -> str | None:
    return None if value is None else _applied_ref(value)


@dataclass(frozen=True)
class RefIntent:
    """Immutable authority to perform one private Git-ref CAS."""

    ref: str
    expected_old_sha: str
    new_sha: str
    subject_id: str
    witness_ref: str | None = None

    def __post_init__(self) -> None:
        _ref_name(self.ref)
        _git_sha(self.expected_old_sha, "intent.expected_old_sha")
        _git_sha(self.new_sha, "intent.new_sha")
        _sha256(self.subject_id, "intent.subject_id")
        if self.new_sha == _ZERO_SHA:
            raise RefJournalError("intent.new_sha must name a commit")
        if self.new_sha == self.expected_old_sha:
            raise RefJournalError("intent.new_sha must differ from expected_old_sha")
        if self.ref.startswith("refs/crucible/search/"):
            campaign = self.ref.removeprefix("refs/crucible/search/")
            expected_witness = f"{_WITNESS_PREFIX}{campaign}/{self.subject_id}"
            if self.witness_ref != expected_witness:
                raise RefJournalError(
                    "search-ref intent requires its record-bound applied witness ref"
                )
            _applied_ref(self.witness_ref)
        elif self.witness_ref is not None:
            raise RefJournalError("eligible-ref intent cannot carry an applied witness")

    def canonical_payload(self) -> dict[str, str | None]:
        return {
            "schema": INTENT_SCHEMA,
            "ref": self.ref,
            "expected_old_sha": self.expected_old_sha,
            "new_sha": self.new_sha,
            "subject_id": self.subject_id,
            "witness_ref": self.witness_ref,
        }

    @property
    def intent_id(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, str | None]:
        return {**self.canonical_payload(), "intent_id": self.intent_id}

    @classmethod
    def from_mapping(cls, value: object) -> RefIntent:
        if not isinstance(value, Mapping):
            raise RefJournalError("ref intent must be a JSON object")
        _strict_keys(
            value,
            field="ref intent",
            required={
                "expected_old_sha",
                "new_sha",
                "ref",
                "schema",
                "subject_id",
                "witness_ref",
            },
            optional={"intent_id"},
        )
        if value.get("schema") != INTENT_SCHEMA:
            raise RefJournalError(f"ref intent schema must be {INTENT_SCHEMA!r}")
        intent = cls(
            ref=_ref_name(value.get("ref")),
            expected_old_sha=_git_sha(value.get("expected_old_sha"), "intent.expected_old_sha"),
            new_sha=_git_sha(value.get("new_sha"), "intent.new_sha"),
            subject_id=_sha256(value.get("subject_id"), "intent.subject_id"),
            witness_ref=_optional_applied_ref(value.get("witness_ref")),
        )
        supplied_id = value.get("intent_id")
        if supplied_id is not None and _sha256(supplied_id, "intent.intent_id") != intent.intent_id:
            raise RefJournalError("intent_id does not match the canonical ref intent")
        return intent


@dataclass(frozen=True)
class RefReceipt:
    """Canonical proof that one persisted intent reached its requested ref value."""

    intent_id: str
    ref: str
    expected_old_sha: str
    new_sha: str
    subject_id: str
    witness_ref: str | None = None
    status: str = "committed"

    def __post_init__(self) -> None:
        _sha256(self.intent_id, "receipt.intent_id")
        _ref_name(self.ref)
        _git_sha(self.expected_old_sha, "receipt.expected_old_sha")
        _git_sha(self.new_sha, "receipt.new_sha")
        _sha256(self.subject_id, "receipt.subject_id")
        if self.status != "committed":
            raise RefJournalError("receipt.status must be 'committed'")
        expected_intent_id = RefIntent(
            ref=self.ref,
            expected_old_sha=self.expected_old_sha,
            new_sha=self.new_sha,
            subject_id=self.subject_id,
            witness_ref=self.witness_ref,
        ).intent_id
        if self.intent_id != expected_intent_id:
            raise RefJournalError("receipt.intent_id does not match the canonical ref intent")

    @classmethod
    def from_intent(cls, intent: RefIntent) -> RefReceipt:
        return cls(
            intent_id=intent.intent_id,
            ref=intent.ref,
            expected_old_sha=intent.expected_old_sha,
            new_sha=intent.new_sha,
            subject_id=intent.subject_id,
            witness_ref=intent.witness_ref,
        )

    def canonical_payload(self) -> dict[str, str | None]:
        return {
            "schema": RECEIPT_SCHEMA,
            "intent_id": self.intent_id,
            "ref": self.ref,
            "expected_old_sha": self.expected_old_sha,
            "new_sha": self.new_sha,
            "subject_id": self.subject_id,
            "witness_ref": self.witness_ref,
            "status": self.status,
        }

    @property
    def receipt_id(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def to_dict(self) -> dict[str, str | None]:
        return {**self.canonical_payload(), "receipt_id": self.receipt_id}

    @classmethod
    def from_mapping(cls, value: object) -> RefReceipt:
        if not isinstance(value, Mapping):
            raise RefJournalError("ref receipt must be a JSON object")
        _strict_keys(
            value,
            field="ref receipt",
            required={
                "expected_old_sha",
                "intent_id",
                "new_sha",
                "ref",
                "schema",
                "status",
                "subject_id",
                "witness_ref",
            },
            optional={"receipt_id"},
        )
        if value.get("schema") != RECEIPT_SCHEMA:
            raise RefJournalError(f"ref receipt schema must be {RECEIPT_SCHEMA!r}")
        status = value.get("status")
        if not isinstance(status, str):
            raise RefJournalError("receipt.status must be 'committed'")
        receipt = cls(
            intent_id=_sha256(value.get("intent_id"), "receipt.intent_id"),
            ref=_ref_name(value.get("ref")),
            expected_old_sha=_git_sha(
                value.get("expected_old_sha"),
                "receipt.expected_old_sha",
            ),
            new_sha=_git_sha(value.get("new_sha"), "receipt.new_sha"),
            subject_id=_sha256(value.get("subject_id"), "receipt.subject_id"),
            witness_ref=_optional_applied_ref(value.get("witness_ref")),
            status=status,
        )
        supplied_id = value.get("receipt_id")
        if (
            supplied_id is not None
            and _sha256(supplied_id, "receipt.receipt_id") != receipt.receipt_id
        ):
            raise RefJournalError("receipt_id does not match the canonical ref receipt")
        return receipt


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def persist_intent(path: Path, intent: RefIntent) -> None:
    """Persist an immutable intent durably before any authority mutation."""

    try:
        write_exclusive_json(path, intent.to_dict())
    except ContractError as exc:
        raise RefJournalError(str(exc)) from exc
    _fsync_directory(path.parent)


def load_intent(path: Path) -> RefIntent:
    return RefIntent.from_mapping(load_json_object(path, "ref intent", max_bytes=1024 * 1024))


def load_receipt(path: Path) -> RefReceipt:
    return RefReceipt.from_mapping(load_json_object(path, "ref receipt", max_bytes=1024 * 1024))


def _git(
    repository: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    if executable is None:
        raise RefJournalError("git is required for a ref transaction")
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable and argv, no shell
            [executable, *args],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except OSError as exc:
        raise RefJournalError(f"cannot execute git for ref transaction: {exc}") from exc
    if check and result.returncode != 0:
        reason = " ".join((result.stderr.strip() or "git command failed").split())[:2_000]
        raise RefJournalError(reason)
    return result


def _resolved_commit(repository: Path, sha: str, field: str) -> str:
    result = _git(repository, "rev-parse", "--verify", f"{sha}^{{commit}}")
    resolved = result.stdout.strip()
    if resolved != sha:
        raise RefJournalError(f"{field} is not the resolved commit")
    return resolved


def _read_ref(repository: Path, ref: str) -> str:
    symbolic = _git(repository, "symbolic-ref", "--quiet", ref, check=False)
    if symbolic.returncode == 0:
        raise RefJournalError("private Crucible refs must not be symbolic refs")
    if symbolic.returncode != 1:
        reason = " ".join((symbolic.stderr.strip() or "cannot inspect symbolic ref").split())[
            :2_000
        ]
        raise RefJournalError(reason)
    result = _git(repository, "rev-parse", "--verify", "--quiet", ref, check=False)
    if result.returncode == 1:
        return _ZERO_SHA
    if result.returncode != 0:
        reason = " ".join((result.stderr.strip() or "cannot read ref").split())[:2_000]
        raise RefJournalError(reason)
    return _git_sha(result.stdout.strip(), "observed ref SHA")


def _validate_receipt_for_intent(receipt: RefReceipt, intent: RefIntent) -> None:
    expected = RefReceipt.from_intent(intent)
    if receipt != expected:
        raise RefJournalError("ref receipt does not match the persisted intent")


def reconcile_ref_update(
    repository: Path,
    *,
    intent_path: Path,
    receipt_path: Path,
) -> RefReceipt:
    """Finish or recover one persisted private-ref compare-and-swap.

    If a matching receipt already exists, it is the immutable proof of an
    earlier successful CAS. Without a receipt, an old ref is advanced, a ref
    already at the new SHA is treated as post-CAS recovery, and every other
    value is a conflict.
    """

    if receipt_path.exists() or receipt_path.is_symlink():
        return verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )

    intent = load_intent(intent_path)

    repository = repository.resolve()
    if not repository.is_dir():
        raise RefJournalError("ref transaction repository does not exist")
    _resolved_commit(repository, intent.new_sha, "intent.new_sha")
    if intent.expected_old_sha != _ZERO_SHA:
        _resolved_commit(repository, intent.expected_old_sha, "intent.expected_old_sha")

    observed = _read_ref(repository, intent.ref)
    witnessed = _read_ref(repository, intent.witness_ref) if intent.witness_ref else None
    if observed == intent.expected_old_sha and witnessed in {None, _ZERO_SHA}:
        if intent.witness_ref is None:
            _git(
                repository,
                "update-ref",
                "--no-deref",
                intent.ref,
                intent.new_sha,
                intent.expected_old_sha,
            )
        else:
            transaction = "\n".join(
                (
                    "start",
                    f"update {intent.ref} {intent.new_sha} {intent.expected_old_sha}",
                    f"create {intent.witness_ref} {intent.new_sha}",
                    "prepare",
                    "commit",
                    "",
                )
            )
            _git(
                repository,
                "update-ref",
                "--no-deref",
                "--stdin",
                input_text=transaction,
            )
    elif observed != intent.new_sha or witnessed not in {None, intent.new_sha}:
        raise RefJournalError(
            f"ref CAS conflict: expected {intent.expected_old_sha} or recovered "
            f"{intent.new_sha}, observed target={observed}, witness={witnessed}"
        )

    receipt = RefReceipt.from_intent(intent)
    try:
        write_exclusive_json(receipt_path, receipt.to_dict())
    except ContractError as exc:
        raise RefJournalError(str(exc)) from exc
    _fsync_directory(receipt_path.parent)
    return receipt


def verify_ref_update(
    repository: Path,
    *,
    intent_path: Path,
    receipt_path: Path,
) -> RefReceipt:
    """Verify a persisted receipt against its intent and the current Git ref.

    This is deliberately read-only. A canonical JSON receipt is not proof of a
    compare-and-swap by itself; the persisted intent must match it and the
    private ref must still resolve to the requested commit.
    """

    intent = load_intent(intent_path)
    receipt = load_receipt(receipt_path)
    _validate_receipt_for_intent(receipt, intent)
    repository = repository.resolve()
    if not repository.is_dir():
        raise RefJournalError("ref transaction repository does not exist")
    _resolved_commit(repository, intent.new_sha, "intent.new_sha")
    if intent.expected_old_sha != _ZERO_SHA:
        _resolved_commit(repository, intent.expected_old_sha, "intent.expected_old_sha")
    observed = _read_ref(repository, intent.ref)
    if observed != intent.new_sha:
        raise RefJournalError(
            f"committed ref receipt is stale: expected {intent.new_sha}, observed {observed}"
        )
    if intent.witness_ref is not None:
        witnessed = _read_ref(repository, intent.witness_ref)
        if witnessed != intent.new_sha:
            raise RefJournalError(
                f"applied witness is stale: expected {intent.new_sha}, observed {witnessed}"
            )
    return receipt


def commit_ref_update(
    repository: Path,
    intent: RefIntent,
    *,
    intent_path: Path,
    receipt_path: Path,
) -> RefReceipt:
    """Durably prepare an intent, then execute its recoverable CAS."""

    persist_intent(intent_path, intent)
    return reconcile_ref_update(
        repository,
        intent_path=intent_path,
        receipt_path=receipt_path,
    )
