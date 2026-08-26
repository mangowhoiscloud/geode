from __future__ import annotations

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
    report = evaluate_context_recoverability((reference,), SessionEventStore(db))

    assert report.receipts[0].status is RecoveryStatus.EXACT
    assert report.receipts[0].source == "session-event"
    assert dict(report.counts)[RecoveryStatus.EXACT] == 1


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
