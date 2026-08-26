"""Deterministic recoverability labels over existing session evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.observability.session_timeline import SessionEventStore
from core.orchestration.tool_offload import ToolResultOffloadStore


class RecoveryStatus(StrEnum):
    EXACT = "exact"
    SUMMARY_ONLY = "summary-only"
    UNAVAILABLE = "unavailable"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class ContextEvidenceReference:
    session_id: str
    ordinal: int
    event_id: str
    stored_payload_sha256: str
    content_sha256: str
    summary: str = ""
    offload_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ContextRecoveryReceipt:
    reference: ContextEvidenceReference
    status: RecoveryStatus
    source: str


@dataclass(frozen=True, slots=True)
class ContextRecoverabilityReport:
    receipts: tuple[ContextRecoveryReceipt, ...]
    counts: tuple[tuple[RecoveryStatus, int], ...]


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_context_recoverability(
    references: Iterable[ContextEvidenceReference],
    event_store: SessionEventStore,
    offload_store: ToolResultOffloadStore | None = None,
) -> ContextRecoverabilityReport:
    """Classify exact recovery without copying either underlying store."""
    receipts = tuple(_classify(reference, event_store, offload_store) for reference in references)
    counts = tuple(
        (status, sum(receipt.status is status for receipt in receipts)) for status in RecoveryStatus
    )
    return ContextRecoverabilityReport(receipts=receipts, counts=counts)


def _classify(
    reference: ContextEvidenceReference,
    event_store: SessionEventStore,
    offload_store: ToolResultOffloadStore | None,
) -> ContextRecoveryReceipt:
    _validate_reference(reference)
    if offload_store is not None and offload_store.session_id != reference.session_id:
        raise ValueError("offload store session differs from the evidence reference")
    rows = event_store.read(
        reference.session_id,
        after_id=reference.ordinal - 1,
        limit=1,
    )
    if rows and rows[0].id == reference.ordinal:
        event = rows[0]
        if (
            event.event_id != reference.event_id
            or event.corrupt_payload
            or event.payload_hash != reference.stored_payload_sha256
        ):
            return ContextRecoveryReceipt(reference, RecoveryStatus.CORRUPT, "session-event")
        if event.payload_hash == reference.content_sha256:
            return ContextRecoveryReceipt(reference, RecoveryStatus.EXACT, "session-event")
        if event.payload.get("_truncated") is True and (
            event.payload.get("payload_hash") != reference.content_sha256
        ):
            return ContextRecoveryReceipt(reference, RecoveryStatus.CORRUPT, "session-event")

    if reference.offload_ref and offload_store is not None:
        recalled = offload_store.recall(reference.offload_ref)
        error = str(recalled.get("error", "")) if isinstance(recalled, dict) else ""
        if error.startswith("Failed to read offloaded result"):
            return ContextRecoveryReceipt(reference, RecoveryStatus.CORRUPT, "tool-offload")
        if not error:
            status = (
                RecoveryStatus.EXACT
                if canonical_json_sha256(recalled) == reference.content_sha256
                else RecoveryStatus.CORRUPT
            )
            return ContextRecoveryReceipt(reference, status, "tool-offload")

    if reference.summary.strip():
        return ContextRecoveryReceipt(reference, RecoveryStatus.SUMMARY_ONLY, "summary")
    return ContextRecoveryReceipt(reference, RecoveryStatus.UNAVAILABLE, "none")


def _validate_reference(reference: ContextEvidenceReference) -> None:
    if not reference.session_id.strip() or reference.ordinal < 1 or not reference.event_id.strip():
        raise ValueError("context evidence requires session, ordinal, and event identity")
    for digest in (reference.stored_payload_sha256, reference.content_sha256):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("context evidence requires lowercase SHA-256 digests")
