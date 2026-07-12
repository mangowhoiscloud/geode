"""Canonical train-promotion bundle for one applied Crucible search ref."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifacts import load_json_object
from .contract import ContractError, ExperimentContract, Mutation
from .evidence import EvidenceEnvelope, ResourceUsage, load_evidence
from .promotion import PromotionVerdict, decide
from .ref_journal import RefIntent, RefReceipt, load_intent, verify_ref_update

BUNDLE_SCHEMA = "crucible.promotion-bundle.v1"

_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CAMPAIGN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PROPOSAL_FIELDS = {
    "attempt_id",
    "candidate_sha",
    "mutation",
    "parent_sha",
    "proposal_id",
    "request_id",
    "schema",
    "usage",
}
_REQUEST_FIELDS = {
    "allowed_surfaces",
    "campaign_id",
    "config_id",
    "feedback",
    "attempt_id",
    "iteration",
    "parent_sha",
    "remaining_budget",
    "request_id",
    "schema",
}
_REQUEST_OPTIONAL_FIELDS = {"objective"}
_RECORD_FIELDS = {
    "attempt_id",
    "baseline_ref",
    "campaign_id",
    "candidate_ref",
    "component",
    "contract_id",
    "kind",
    "outcome",
    "previous_record_id",
    "proposal_id",
    "reasons",
    "record_id",
    "schema",
    "search_head_after",
    "search_head_before",
    "timestamp",
    "usage",
    "verdict_id",
    "wall_seconds",
}
_RECORD_OPTIONAL_FIELDS = {
    "candidate_fingerprint",
    "candidate_fingerprint_ref",
    "marginal_usage",
}


def _canonical_hash(payload: Mapping[str, Any], field: str) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field} must contain canonical JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ContractError(f"{field} has an invalid canonical identifier")
    return value


def _sha256(value: object, field: str) -> str:
    return _identifier(value, field, _SHA256)


def _git_sha(value: object, field: str) -> str:
    return _identifier(value, field, _GIT_SHA)


def _campaign_id(value: object) -> str:
    return _identifier(value, "promotion bundle campaign_id", _CAMPAIGN)


def _strict_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(str(key) for key in set(value) - allowed)
    if missing:
        raise ContractError(f"promotion bundle is missing fields: {', '.join(missing)}")
    if unknown:
        raise ContractError(f"promotion bundle has unknown fields: {', '.join(unknown)}")


def _task_pack_sha256(contract: ExperimentContract) -> str:
    """Read the content-bound task identity frozen by the train contract."""

    return _sha256(contract.task_pack_sha256, "train contract task-pack SHA-256")


def _canonical_record_id(record: Mapping[str, Any]) -> str:
    from .supervisor import RECORD_SCHEMA

    missing = sorted(_RECORD_FIELDS - set(record))
    unknown = sorted(str(key) for key in set(record) - _RECORD_FIELDS - _RECORD_OPTIONAL_FIELDS)
    if missing:
        raise ContractError("supervisor record is missing fields: " + ", ".join(missing))
    if unknown:
        raise ContractError("supervisor record has unknown fields: " + ", ".join(unknown))
    if record.get("schema") != RECORD_SCHEMA:
        raise ContractError(f"supervisor record schema must be {RECORD_SCHEMA!r}")
    supplied_id = _sha256(record.get("record_id"), "supervisor record_id")
    payload = dict(record)
    del payload["record_id"]
    if _canonical_hash(payload, "supervisor record") != supplied_id:
        raise ContractError("record_id does not match the canonical supervisor record")
    return supplied_id


def _validate_record(
    record: object,
    *,
    contract: ExperimentContract,
    verdict: PromotionVerdict,
) -> tuple[str, str, ResourceUsage]:
    if not isinstance(record, Mapping):
        raise ContractError("supervisor record must be a JSON object")
    record_id = _canonical_record_id(record)
    if record.get("component") != "plugins.crucible.supervisor":
        raise ContractError("promotion requires a Crucible supervisor record")
    if record.get("kind") != "train_attempt":
        raise ContractError("promotion requires a train_attempt supervisor record")
    timestamp = record.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise ContractError("supervisor record timestamp is required")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ContractError("supervisor record timestamp must be ISO-8601") from exc
    if parsed_timestamp.tzinfo is None:
        raise ContractError("supervisor record timestamp must include a timezone")
    _sha256(record.get("proposal_id"), "supervisor record proposal_id")
    previous = record.get("previous_record_id")
    if previous is not None:
        _sha256(previous, "supervisor record previous_record_id")
    if record.get("contract_id") != contract.contract_id:
        raise ContractError("supervisor record contract_id does not match the train contract")
    if record.get("verdict_id") != verdict.verdict_id:
        raise ContractError("supervisor record verdict_id does not match the train KEEP verdict")
    reasons = record.get("reasons")
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        raise ContractError("supervisor record reasons must be a string list")
    if "campaign_budget_exceeded" in reasons:
        raise ContractError("budget-downgraded train KEEP cannot form a promotion bundle")
    if record.get("outcome") != "KEEP":
        raise ContractError("supervisor record outcome must be KEEP")
    if tuple(reasons) != verdict.reasons:
        raise ContractError("supervisor record reasons do not match the train KEEP verdict")
    usage = ResourceUsage.from_mapping(record.get("usage"))
    if usage.to_dict() != record.get("usage"):
        raise ContractError("supervisor record usage is not canonical")
    marginal_raw = record.get("marginal_usage")
    if marginal_raw is not None:
        marginal_usage = ResourceUsage.from_mapping(marginal_raw)
        if marginal_usage.to_dict() != marginal_raw:
            raise ContractError("supervisor record marginal_usage is not canonical")
    fingerprint = record.get("candidate_fingerprint")
    fingerprint_ref = record.get("candidate_fingerprint_ref")
    if (fingerprint is None) != (fingerprint_ref is None):
        raise ContractError("supervisor record candidate fingerprint fields must travel together")
    if fingerprint is not None:
        fingerprint = _sha256(fingerprint, "supervisor record candidate_fingerprint")
        expected_fingerprint_ref = f"refs/crucible/candidate-fingerprints/{fingerprint}"
        if fingerprint_ref != expected_fingerprint_ref:
            raise ContractError("supervisor record candidate_fingerprint_ref does not match")
    wall_seconds = record.get("wall_seconds")
    if (
        isinstance(wall_seconds, bool)
        or not isinstance(wall_seconds, (int, float))
        or not math.isfinite(float(wall_seconds))
        or float(wall_seconds) < 0
    ):
        raise ContractError("supervisor record wall_seconds must be non-negative and finite")
    if record.get("search_head_before") != contract.baseline_sha:
        raise ContractError("supervisor record search_head_before does not match baseline_sha")
    if record.get("search_head_after") != contract.candidate_sha:
        raise ContractError("supervisor record search_head_after does not match candidate_sha")
    campaign_id = _campaign_id(record.get("campaign_id"))
    attempt_id = record.get("attempt_id")
    if not isinstance(attempt_id, str) or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ContractError("supervisor record attempt_id is invalid")
    expected_candidate_ref = f"refs/crucible/candidates/{campaign_id}/{attempt_id}"
    expected_baseline_ref = f"refs/crucible/baselines/{campaign_id}/{attempt_id}"
    if record.get("candidate_ref") != expected_candidate_ref:
        raise ContractError("supervisor record candidate_ref does not match the train attempt")
    if record.get("baseline_ref") != expected_baseline_ref:
        raise ContractError("supervisor record baseline_ref does not match the train attempt")
    if contract.champion_ref != expected_baseline_ref:
        raise ContractError(
            "train contract champion_ref does not match the supervisor baseline ref"
        )
    return record_id, campaign_id, usage


def _validate_proposal_lineage(
    request: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    contract: ExperimentContract,
) -> ResourceUsage:
    from .supervisor import PROPOSAL_SCHEMA, REQUEST_SCHEMA

    unknown_request_fields = set(request) - _REQUEST_FIELDS - _REQUEST_OPTIONAL_FIELDS
    if not _REQUEST_FIELDS.issubset(request) or unknown_request_fields:
        raise ContractError("proposal request fields do not match the supervisor schema")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ContractError(f"proposal request schema must be {REQUEST_SCHEMA!r}")
    objective = request.get("objective")
    if objective is not None and (
        not isinstance(objective, str)
        or not objective.strip()
        or len(objective.encode("utf-8")) > 16 * 1024
    ):
        raise ContractError("proposal request objective must be a bounded non-empty string")
    request_id = _sha256(request.get("request_id"), "proposal request_id")
    request_payload = dict(request)
    del request_payload["request_id"]
    if _canonical_hash(request_payload, "proposal request") != request_id:
        raise ContractError("request_id does not match the canonical proposal request")
    if request.get("campaign_id") != record.get("campaign_id"):
        raise ContractError("proposal request campaign_id does not match the record")
    if request.get("attempt_id") != record.get("attempt_id"):
        raise ContractError("proposal request attempt_id does not match the record")
    if request.get("parent_sha") != contract.baseline_sha:
        raise ContractError("proposal request parent_sha does not match the train contract")
    allowed = request.get("allowed_surfaces")
    if not isinstance(allowed, list) or not all(isinstance(item, str) and item for item in allowed):
        raise ContractError("proposal request allowed_surfaces must be a string list")
    if contract.mutation.surface not in allowed:
        raise ContractError("train mutation is outside proposal request allowed_surfaces")

    if set(proposal) != _PROPOSAL_FIELDS:
        raise ContractError("candidate proposal fields do not match the supervisor schema")
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise ContractError(f"candidate proposal schema must be {PROPOSAL_SCHEMA!r}")
    proposal_id = _sha256(proposal.get("proposal_id"), "candidate proposal_id")
    proposal_payload = dict(proposal)
    del proposal_payload["proposal_id"]
    if _canonical_hash(proposal_payload, "candidate proposal") != proposal_id:
        raise ContractError("proposal_id does not match the canonical candidate proposal")
    if proposal_id != record.get("proposal_id"):
        raise ContractError("candidate proposal_id does not match the supervisor record")
    expected = {
        "attempt_id": record.get("attempt_id"),
        "request_id": request_id,
        "parent_sha": contract.baseline_sha,
        "candidate_sha": contract.candidate_sha,
    }
    mismatch = next(
        (field for field, value in expected.items() if proposal.get(field) != value),
        None,
    )
    if mismatch:
        raise ContractError(f"candidate proposal {mismatch} does not match its train lineage")
    if contract.mutation != Mutation.from_mapping(proposal.get("mutation")):
        raise ContractError("candidate proposal mutation does not match the train contract")
    usage = ResourceUsage.from_mapping(proposal.get("usage"))
    if usage.to_dict() != proposal.get("usage"):
        raise ContractError("candidate proposal usage is not canonical")
    return usage


def _validate_receipt(
    receipt: RefReceipt | None,
    *,
    record_id: str,
    campaign_id: str,
    baseline_sha: str,
    candidate_sha: str,
) -> RefReceipt:
    if receipt is None:
        raise ContractError("promotion bundle requires an applied ref receipt")
    if not isinstance(receipt, RefReceipt):
        raise ContractError("promotion bundle receipt must be a RefReceipt")
    canonical = RefReceipt.from_mapping(receipt.to_dict())
    if canonical != receipt:
        raise ContractError("ref receipt does not match its canonical payload")
    if receipt.status != "committed":
        raise ContractError("promotion bundle requires a committed ref receipt")
    expected_ref = f"refs/crucible/search/{campaign_id}"
    if receipt.ref != expected_ref:
        raise ContractError("ref receipt does not apply the campaign search ref")
    if receipt.expected_old_sha != baseline_sha:
        raise ContractError("ref receipt expected_old_sha does not match baseline_sha")
    if receipt.new_sha != candidate_sha:
        raise ContractError("ref receipt new_sha does not match candidate_sha")
    if receipt.subject_id != record_id:
        raise ContractError("ref receipt subject_id does not match the supervisor record_id")
    return canonical


@dataclass(frozen=True)
class PromotionBundle:
    """Immutable proof chain from train evidence through one applied search ref."""

    train_contract_id: str
    train_baseline_evidence_id: str
    train_candidate_evidence_id: str
    train_verdict_id: str
    train_record_id: str
    train_ref_receipt_id: str
    campaign_id: str
    train_search_ref: str
    baseline_sha: str
    candidate_sha: str
    train_task_pack_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "train_contract_id",
            "train_baseline_evidence_id",
            "train_candidate_evidence_id",
            "train_verdict_id",
            "train_record_id",
            "train_ref_receipt_id",
            "train_task_pack_sha256",
        ):
            _sha256(getattr(self, name), f"promotion bundle {name}")
        _git_sha(self.baseline_sha, "promotion bundle baseline_sha")
        _git_sha(self.candidate_sha, "promotion bundle candidate_sha")
        campaign_id = _campaign_id(self.campaign_id)
        if self.baseline_sha == self.candidate_sha:
            raise ContractError("promotion bundle candidate_sha must differ from baseline_sha")
        if self.train_search_ref != f"refs/crucible/search/{campaign_id}":
            raise ContractError("promotion bundle train_search_ref does not match campaign_id")

    @classmethod
    def _build(
        cls,
        contract: ExperimentContract,
        baseline: EvidenceEnvelope,
        candidate: EvidenceEnvelope,
        verdict: PromotionVerdict,
        request: Mapping[str, Any],
        proposal: Mapping[str, Any],
        record: Mapping[str, Any],
        receipt: RefReceipt | None,
    ) -> PromotionBundle:
        """Validate and bind the complete authority-neutral train KEEP chain."""

        contract = ExperimentContract.from_mapping(contract.to_dict())
        baseline = EvidenceEnvelope.from_mapping(baseline.to_dict())
        candidate = EvidenceEnvelope.from_mapping(candidate.to_dict())
        verdict = PromotionVerdict.from_mapping(verdict.to_dict())
        if contract.stage != "train":
            raise ContractError("promotion bundle requires a train experiment contract")
        recomputed = decide(contract, baseline, candidate)
        if verdict.stage != "train" or verdict.verdict != "KEEP":
            raise ContractError("supplied train verdict must be KEEP")
        if recomputed.verdict != "KEEP":
            raise ContractError("recomputed train verdict must be KEEP")
        if verdict.verdict_id != recomputed.verdict_id:
            raise ContractError("supplied verdict_id does not match the recomputed train verdict")

        record_id, campaign_id, record_usage = _validate_record(
            record,
            contract=contract,
            verdict=recomputed,
        )
        proposal_usage = _validate_proposal_lineage(
            request,
            proposal,
            record=record,
            contract=contract,
        )
        if record_usage != recomputed.usage + proposal_usage:
            raise ContractError("supervisor record usage does not match proposal plus verdict")
        canonical_receipt = _validate_receipt(
            receipt,
            record_id=record_id,
            campaign_id=campaign_id,
            baseline_sha=contract.baseline_sha,
            candidate_sha=contract.candidate_sha,
        )
        return cls(
            train_contract_id=contract.contract_id,
            train_baseline_evidence_id=baseline.evidence_id,
            train_candidate_evidence_id=candidate.evidence_id,
            train_verdict_id=recomputed.verdict_id,
            train_record_id=record_id,
            train_ref_receipt_id=canonical_receipt.receipt_id,
            campaign_id=campaign_id,
            train_search_ref=canonical_receipt.ref,
            baseline_sha=contract.baseline_sha,
            candidate_sha=contract.candidate_sha,
            train_task_pack_sha256=_task_pack_sha256(contract),
        )

    @classmethod
    def build_from_attempt(cls, repository: Path, attempt_dir: Path) -> PromotionBundle:
        """Rebuild a train KEEP chain from one supervisor-owned attempt.

        Fixed artifact names keep the authority surface small. The receipt is
        accepted only when its persisted intent matches and the current search
        ref still resolves to the candidate commit.
        """

        try:
            attempt_dir.lstat()
        except OSError as exc:
            raise ContractError(f"cannot inspect train attempt: {exc}") from exc
        if attempt_dir.is_symlink() or not attempt_dir.is_dir():
            raise ContractError("train attempt must be a regular directory")
        attempt_dir = attempt_dir.resolve()
        contract = ExperimentContract.from_mapping(
            load_json_object(attempt_dir / "contract.json", "train contract")
        )
        baseline = load_evidence(attempt_dir / "baseline.attested.json")
        candidate = load_evidence(attempt_dir / "candidate.attested.json")
        verdict = PromotionVerdict.from_mapping(
            load_json_object(attempt_dir / "verdict.json", "train verdict")
        )
        request = load_json_object(attempt_dir / "request.json", "proposal request")
        proposal = load_json_object(attempt_dir / "candidate.json", "candidate proposal")
        record = load_json_object(attempt_dir / "record.json", "supervisor record")
        intent_path = attempt_dir / "search-ref.intent.json"
        receipt_path = attempt_dir / "search-ref.receipt.json"
        intent = load_intent(intent_path)
        receipt = verify_ref_update(
            repository,
            intent_path=intent_path,
            receipt_path=receipt_path,
        )
        record_id, campaign_id, _record_usage = _validate_record(
            record,
            contract=contract,
            verdict=decide(contract, baseline, candidate),
        )
        expected_intent = RefIntent(
            ref=f"refs/crucible/search/{campaign_id}",
            expected_old_sha=contract.baseline_sha,
            new_sha=contract.candidate_sha,
            subject_id=record_id,
            witness_ref=f"refs/crucible/applied/{campaign_id}/{record_id}",
        )
        if intent != expected_intent:
            raise ContractError("persisted search-ref intent does not match the train record")
        return cls._build(
            contract,
            baseline,
            candidate,
            verdict,
            request,
            proposal,
            record,
            receipt,
        )

    def canonical_payload(self) -> dict[str, str]:
        return {
            "schema": BUNDLE_SCHEMA,
            "train_contract_id": self.train_contract_id,
            "train_baseline_evidence_id": self.train_baseline_evidence_id,
            "train_candidate_evidence_id": self.train_candidate_evidence_id,
            "train_verdict_id": self.train_verdict_id,
            "train_record_id": self.train_record_id,
            "train_ref_receipt_id": self.train_ref_receipt_id,
            "campaign_id": self.campaign_id,
            "train_search_ref": self.train_search_ref,
            "baseline_sha": self.baseline_sha,
            "candidate_sha": self.candidate_sha,
            "train_task_pack_sha256": self.train_task_pack_sha256,
        }

    @property
    def bundle_id(self) -> str:
        return _canonical_hash(self.canonical_payload(), "promotion bundle")

    def to_dict(self) -> dict[str, str]:
        return {**self.canonical_payload(), "bundle_id": self.bundle_id}

    @classmethod
    def from_mapping(cls, value: object) -> PromotionBundle:
        if not isinstance(value, Mapping):
            raise ContractError("promotion bundle must be a JSON object")
        required = {
            "baseline_sha",
            "campaign_id",
            "candidate_sha",
            "schema",
            "train_baseline_evidence_id",
            "train_candidate_evidence_id",
            "train_contract_id",
            "train_record_id",
            "train_ref_receipt_id",
            "train_search_ref",
            "train_task_pack_sha256",
            "train_verdict_id",
        }
        _strict_keys(value, required=required, optional={"bundle_id"})
        if value.get("schema") != BUNDLE_SCHEMA:
            raise ContractError(f"promotion bundle schema must be {BUNDLE_SCHEMA!r}")
        bundle = cls(
            train_contract_id=_sha256(
                value.get("train_contract_id"),
                "promotion bundle train_contract_id",
            ),
            train_baseline_evidence_id=_sha256(
                value.get("train_baseline_evidence_id"),
                "promotion bundle train_baseline_evidence_id",
            ),
            train_candidate_evidence_id=_sha256(
                value.get("train_candidate_evidence_id"),
                "promotion bundle train_candidate_evidence_id",
            ),
            train_verdict_id=_sha256(
                value.get("train_verdict_id"),
                "promotion bundle train_verdict_id",
            ),
            train_record_id=_sha256(
                value.get("train_record_id"),
                "promotion bundle train_record_id",
            ),
            train_ref_receipt_id=_sha256(
                value.get("train_ref_receipt_id"),
                "promotion bundle train_ref_receipt_id",
            ),
            campaign_id=_campaign_id(value.get("campaign_id")),
            train_search_ref=str(value.get("train_search_ref", "")),
            baseline_sha=_git_sha(
                value.get("baseline_sha"),
                "promotion bundle baseline_sha",
            ),
            candidate_sha=_git_sha(
                value.get("candidate_sha"),
                "promotion bundle candidate_sha",
            ),
            train_task_pack_sha256=_sha256(
                value.get("train_task_pack_sha256"),
                "promotion bundle train_task_pack_sha256",
            ),
        )
        supplied_id = value.get("bundle_id")
        if (
            supplied_id is not None
            and _sha256(
                supplied_id,
                "promotion bundle bundle_id",
            )
            != bundle.bundle_id
        ):
            raise ContractError("bundle_id does not match the canonical promotion bundle")
        return bundle


__all__ = [
    "BUNDLE_SCHEMA",
    "PromotionBundle",
]
