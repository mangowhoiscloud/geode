from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from core.memory.session_manager import SessionManager
from core.observability.session_timeline import (
    PersistedSessionEvent,
    SessionEventKind,
    SessionEventPolicy,
    SessionEventStore,
    SessionEventWrite,
    session_payload_content_sha256,
)
from core.orchestration.tool_offload import ToolResultOffloadStore
from evals.benchmarks.context_recoverability import (
    ContextEvidenceReference,
    RecoveryStatus,
    canonical_json_sha256,
    evaluate_context_recoverability,
)


def _reference(
    stored: PersistedSessionEvent,
    *,
    content: object,
    summary: str = "",
    offload_ref: str | None = None,
) -> ContextEvidenceReference:
    return ContextEvidenceReference(
        session_id=stored.session_id,
        ordinal=stored.id,
        event_id=stored.event_id,
        stored_payload_sha256=stored.payload_hash,
        content_sha256=canonical_json_sha256(content),
        summary=summary,
        offload_ref=offload_ref,
    )


def test_exact_event_survives_restart_compaction_summary_and_far_updates(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    payload = {"fact": "release-sha", "value": "abc123"}
    stored = store.append(
        SessionEventWrite(
            session_id="session-1",
            event_id="fact-v1",
            kind=SessionEventKind.USER_MESSAGE,
            payload=payload,
        )
    )
    for index in range(25):
        store.append(
            SessionEventWrite(
                session_id="session-1",
                kind=SessionEventKind.USER_MESSAGE,
                payload={"fact": "release-sha", "value": f"conflict-{index}"},
            )
        )

    reference = _reference(stored, content=payload, summary="compacted: release SHA was abc123")
    assert stored.payload_hash != reference.content_sha256
    assert session_payload_content_sha256(stored.payload) == reference.content_sha256
    report = evaluate_context_recoverability((reference,), SessionEventStore(db))

    assert report.receipts[0].status is RecoveryStatus.EXACT
    assert report.receipts[0].source == "session-event"
    assert dict(report.counts)[RecoveryStatus.EXACT] == 1
    whole_stored_reference = _reference(stored, content=stored.payload)
    assert (
        evaluate_context_recoverability((whole_stored_reference,), store).receipts[0].status
        is RecoveryStatus.EXACT
    )


def test_tampered_session_event_is_corrupt(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    payload = {"value": "trusted"}
    stored = store.append(
        SessionEventWrite(
            session_id="session-corrupt",
            kind=SessionEventKind.TOOL_COMPLETED,
            payload=payload,
        )
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE session_events SET payload_json = ? WHERE id = ?",
            ('{"value":"tampered"}', stored.id),
        )

    receipt = evaluate_context_recoverability(
        (_reference(stored, content=payload),),
        SessionEventStore(db),
    ).receipts[0]
    assert receipt.status is RecoveryStatus.CORRUPT


def test_offload_store_must_match_the_referenced_session(tmp_path: Path) -> None:
    store = SessionEventStore(tmp_path / "sessions.db")
    payload = {"value": "trusted"}
    stored = store.append(
        SessionEventWrite(
            session_id="session-a",
            kind=SessionEventKind.TOOL_COMPLETED,
            payload=payload,
        )
    )
    other = ToolResultOffloadStore(session_id="session-b", base_dir=tmp_path / "offload")

    with pytest.raises(ValueError, match="offload store session"):
        evaluate_context_recoverability((_reference(stored, content=payload),), store, other)


def test_compaction_artifact_from_existing_session_search_is_summary_only(
    tmp_path: Path,
) -> None:
    db = tmp_path / "sessions.db"
    manager = SessionManager(db)
    manager.upsert_context_artifact(
        session_id="session-summary",
        kind="compaction_summary",
        content="The release SHA was abc123 before the earlier detail expired.",
        source_start_seq=1,
        source_end_seq=20,
    )
    [hit] = manager.search_context_artifacts(
        "release SHA",
        session_id="session-summary",
        kinds=["compaction_summary"],
    )
    manager.close()
    missing_digest = canonical_json_sha256({"release_sha": "abc123"})
    reference = ContextEvidenceReference(
        session_id="session-summary",
        ordinal=999,
        event_id="expired-event",
        stored_payload_sha256=missing_digest,
        content_sha256=missing_digest,
        summary=str(hit["content"]),
    )

    receipt = evaluate_context_recoverability(
        (reference,),
        SessionEventStore(db),
    ).receipts[0]
    assert receipt.status is RecoveryStatus.SUMMARY_ONLY


def test_large_offload_transitions_exact_summary_only_unavailable_and_corrupt(
    tmp_path: Path,
) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db, policy=SessionEventPolicy(max_payload_bytes=64))
    content = {"data": "x" * 500}
    stored = store.append(
        SessionEventWrite(
            session_id="session-large",
            kind=SessionEventKind.TOOL_COMPLETED,
            payload=content,
        )
    )
    offload_root = tmp_path / "offload"
    offload = ToolResultOffloadStore(
        session_id="session-large",
        ttl_hours=1,
        base_dir=offload_root,
    )
    offload.offload("large-1", content)
    reference = _reference(
        stored,
        content=content,
        summary="large result contained 500 x characters",
        offload_ref="large-1",
    )
    assert stored.payload["content_sha256"] == reference.content_sha256
    assert stored.payload["payload_hash"] != reference.content_sha256

    exact = evaluate_context_recoverability((reference,), store, offload).receipts[0]
    assert (exact.status, exact.source) == (RecoveryStatus.EXACT, "tool-offload")

    expired_store = ToolResultOffloadStore(
        session_id="session-large",
        ttl_hours=-1,
        base_dir=offload_root,
    )
    summary = evaluate_context_recoverability((reference,), store, expired_store).receipts[0]
    assert summary.status is RecoveryStatus.SUMMARY_ONLY

    unavailable = evaluate_context_recoverability(
        (replace(reference, summary=""),),
        store,
        expired_store,
    ).receipts[0]
    assert unavailable.status is RecoveryStatus.UNAVAILABLE

    offload.offload("large-1", content)
    (offload_root / "session-large" / "large-1.json").write_text("{", encoding="utf-8")
    corrupt = evaluate_context_recoverability((reference,), store, offload).receipts[0]
    assert corrupt.status is RecoveryStatus.CORRUPT


@pytest.mark.parametrize("field", ["value", "_capture_quality"])
def test_content_and_capture_metadata_tampering_are_both_corrupt(
    tmp_path: Path, field: str
) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    content = {"value": "trusted"}
    stored = store.append(
        SessionEventWrite(
            session_id="s-tamper",
            kind=SessionEventKind.USER_MESSAGE,
            payload=content,
        )
    )
    changed = dict(stored.payload)
    changed[field] = "tampered" if field == "value" else {"version": 1, "content_reduced": True}
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE session_events SET payload_json=? WHERE id=?", (json.dumps(changed), stored.id)
        )
    receipt = evaluate_context_recoverability(
        (_reference(stored, content=content),), store
    ).receipts[0]
    assert receipt.status is RecoveryStatus.CORRUPT


@pytest.mark.parametrize("new_anchor", [None, False, "0" * 64])
def test_bad_new_content_anchor_cannot_fall_back_to_legacy_hash(tmp_path: Path, new_anchor) -> None:
    content = {"value": "offloaded"}
    store = SessionEventStore(tmp_path / "sessions.db")
    stored = store.append(
        SessionEventWrite(
            session_id="s-anchor",
            kind=SessionEventKind.TOOL_COMPLETED,
            payload={
                "_truncated": True,
                "payload_hash": canonical_json_sha256(content),
                "content_sha256": new_anchor,
            },
        )
    )
    offload = ToolResultOffloadStore(session_id="s-anchor", base_dir=tmp_path / "offload")
    offload.offload("result", content)
    receipt = evaluate_context_recoverability(
        (_reference(stored, content=content, offload_ref="result"),),
        store,
        offload,
    ).receipts[0]
    assert receipt.status is RecoveryStatus.CORRUPT
    assert receipt.source == "session-event"


@pytest.mark.parametrize("offload_matches", [False, True])
def test_legacy_truncation_anchor_still_requires_exact_offload(
    tmp_path: Path, offload_matches
) -> None:
    content = {"data": "x" * 500}
    store = SessionEventStore(tmp_path / "sessions.db")
    stored = store.append(
        SessionEventWrite(
            session_id="s-legacy",
            kind=SessionEventKind.TOOL_COMPLETED,
            source="legacy_jsonl",
            payload={
                "_truncated": True,
                "payload_hash": canonical_json_sha256(content),
                "original_bytes": 511,
                "keys": ["data"],
            },
        )
    )
    offload = ToolResultOffloadStore(session_id="s-legacy", base_dir=tmp_path / "offload")
    offload.offload("result", content if offload_matches else {"data": "wrong"})
    receipt = evaluate_context_recoverability(
        (_reference(stored, content=content, offload_ref="result"),),
        store,
        offload,
    ).receipts[0]
    assert receipt.status is (RecoveryStatus.EXACT if offload_matches else RecoveryStatus.CORRUPT)
    assert receipt.source == "tool-offload"


@pytest.mark.parametrize(
    "capture",
    [
        {"version": 2, "content_reduced": False},
        {"version": True, "content_reduced": False},
        {"version": 1, "content_reduced": 0},
        {"version": 1, "content_reduced": False, "extra": "data"},
    ],
)
def test_unknown_capture_metadata_is_not_removed_from_content_hash(capture) -> None:
    payload = {"value": "retained", "_capture_quality": capture}
    assert session_payload_content_sha256(payload) == canonical_json_sha256(payload)


def test_content_hash_preserves_nested_metadata_as_part_of_referenced_content() -> None:
    original = {
        "nested": {
            "value": "retained",
            "_capture_quality": {
                "version": 1,
                "content_reduced": True,
            },
        }
    }
    stored = {**original, "_capture_quality": {"version": 1, "content_reduced": False}}
    assert session_payload_content_sha256(stored) == canonical_json_sha256(original)
