"""Versioned GEODE trajectories plus legacy K3/Codex adapters.

``geode.trajectory@1`` is the public evaluation artifact contract. Canonical
GEODE sessions and benchmark runs are built from
``sessions.db:session_events``. The older
K3-shaped projection and Codex rollout reader remain adapters: they do not own
the persisted schema.

Legacy discovery still accepts GEODE transcript JSONL and Codex rollout JSONL.
Those readers feed the retained K3 channel/tool-index adapter; new exports use
the schema-backed trajectory builder.

The two legacy readers fail in opposite directions, which is
why the format has to carry both cases rather than assume the better one:

* ``geode`` — ``~/.geode/transcripts/``. No thinking event exists, so ``think``
  is always empty, and ``record_tool_result`` carries no call id, so calls and
  results are paired by order.
* ``codex`` — ``~/.codex/sessions/``. Emits ``reasoning`` items that fill
  ``think``, and every tool item carries ``call_id``, so pairing is exact.

Three roles, mirroring K3's channel split:

    {"role": "user",      "content": str}
    {"role": "assistant", "think": str, "response": str,
                          "tools": [{"tool": str, "index": int, "arguments": dict}]}
    {"role": "tool",      "results": [{"tool": str, "index": int,
                                       "status": str, "summary": str}]}

``index`` numbers the parallel calls *within one assistant message* and the
matching result repeats it, which is what makes a result attributable to its
call when several are in flight. ``think`` is always present even when empty,
because K3 keeps the channel so message structure stays constant across turns.

Export is atomic and validates the complete artifact before replacing the
destination. Source SQLite rows and legacy files are never rewritten.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.memory.atomic_write import atomic_write_json
from core.paths import GEODE_HOME, GLOBAL_TRANSCRIPTS_DIR

TRAJECTORY_SCHEMA_ID = "geode.trajectory@1"
TRAJECTORY_SCHEMA_VERSION = 1

__all__ = [
    "TRAJECTORY_SCHEMA_ID",
    "TRAJECTORY_SCHEMA_VERSION",
    "build_trajectory",
    "discover",
    "export_trajectory",
    "load",
    "merge",
    "normalize_trajectory_artifact",
    "resolve",
    "to_k3",
    "trajectory_from_session",
    "trajectory_from_sessions",
    "verify_trajectory_integrity",
]

_DIALOGUE_EVENTS = {"user_message", "assistant_message", "tool_call", "tool_result"}
_TOOL_CALL_KINDS = {"tool.called", "tool_call"}
_TOOL_RESULT_KINDS = {"tool.completed", "tool_result"}
_CONTROL_STATE_KINDS = {
    "grill.started",
    "grill.updated",
    "grill.completed",
    "geo.started",
    "geo.updated",
    "geo.completed",
}
_TURN_SCOPED_KINDS = {
    "message.user",
    "message.assistant",
    "user_message",
    "assistant_message",
    *_TOOL_CALL_KINDS,
    *_TOOL_RESULT_KINDS,
    "turn.completed",
    "verification.decided",
    "verification.continued",
    "verification.evidence",
    "verification.pending",
    "plan.created",
    "plan.progressed",
    "plan.replanned",
    "plan.abandoned",
    "plan.completed",
    "goal.created",
    "goal.updated",
    "goal.continued",
    *_CONTROL_STATE_KINDS,
}


CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def _iso_timestamp(value: Any) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = candidate[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                pass
            else:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid trajectory timestamp: {value!r}") from exc
    if not math.isfinite(timestamp):
        raise ValueError(f"invalid trajectory timestamp: {value!r}")
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def _trajectory_event(
    raw: Mapping[str, Any],
    *,
    ordinal: int,
    default_session_id: str,
    fallback_occurred_at: str,
) -> dict[str, Any]:
    from core.observability.session_timeline import bound_session_payload

    payload_raw = raw.get("payload")
    payload = dict(payload_raw) if isinstance(payload_raw, Mapping) else {}
    session_id = str(raw.get("session_id") or payload.get("session_id") or default_session_id)
    turn_id = str(raw.get("turn_id") or payload.get("turn_id") or "")
    call_id = str(raw.get("call_id") or payload.get("call_id") or "")
    kind = str(raw.get("kind") or raw.get("event") or "event.unknown")
    actor = str(raw.get("actor") or raw.get("role") or raw.get("actor_type") or "system")
    occurred_at_raw = raw.get("occurred_at")
    if occurred_at_raw is None:
        occurred_at_raw = raw.get("timestamp")
    if occurred_at_raw is None:
        occurred_at_raw = raw.get("ts")
    if occurred_at_raw is None:
        occurred_at_raw = fallback_occurred_at
    occurred_at = _iso_timestamp(occurred_at_raw)
    event_id = str(raw.get("event_id") or "")
    if not event_id:
        canonical = json.dumps(
            {
                "actor": actor,
                "call_id": call_id,
                "kind": kind,
                "occurred_at": occurred_at,
                "ordinal": ordinal,
                "payload": payload,
                "session_id": session_id,
                "turn_id": turn_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        event_id = sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return {
        "event_id": event_id,
        "ordinal": ordinal,
        "occurred_at": occurred_at,
        "kind": kind,
        "actor": actor,
        "session_id": session_id,
        "turn_id": turn_id,
        "call_id": call_id,
        "payload": bound_session_payload(payload),
    }


def build_trajectory(
    *,
    trajectory_id: str,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any],
    provenance: Mapping[str, Any],
    privacy: Mapping[str, Any],
    captured_at: str | float | None = None,
    published_at: str | float | None = None,
    observed_on: str | None = None,
    trajectory_class: Sequence[str] = (),
    integrity: Mapping[str, Any] | None = None,
    runtime_event_refs: Sequence[Mapping[str, Any]] = (),
    evidence_refs: Sequence[Mapping[str, Any]] = (),
    artifact_digests: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build and validate one immutable public trajectory artifact."""
    captured = _iso_timestamp(captured_at)
    default_session_id = str(source.get("session") or "")
    normalized = [
        _trajectory_event(
            row,
            ordinal=index,
            default_session_id=default_session_id,
            fallback_occurred_at=captured,
        )
        for index, row in enumerate(events, start=1)
    ]
    quality = _trajectory_quality(normalized)
    integrity_payload = dict(integrity or {})
    integrity_payload["record_count"] = len(normalized)
    legacy_complete = bool(integrity_payload.get("complete", True))
    declared_scope_complete = bool(integrity_payload.get("scope_complete", legacy_complete))
    declared_replay_complete = bool(integrity_payload.get("replay_complete", legacy_complete))
    legacy_incompleteness = _string_list(integrity_payload.get("incompleteness"))
    declared_scope_reasons = _string_list(
        integrity_payload.get("scope_incompleteness", legacy_incompleteness)
    )
    declared_replay_reasons = _string_list(integrity_payload.get("replay_incompleteness"))
    computed_scope_reasons = list(quality.pop("_scope_incompleteness"))
    computed_replay_reasons = list(quality.pop("_replay_incompleteness"))
    automatic_replay_reasons = _declared_replay_reduction_reasons(
        privacy=privacy,
        integrity=integrity_payload,
    )
    scope_reasons = list(dict.fromkeys([*declared_scope_reasons, *computed_scope_reasons]))
    replay_reasons = list(
        dict.fromkeys(
            [
                *declared_replay_reasons,
                *computed_replay_reasons,
                *automatic_replay_reasons,
            ]
        )
    )
    if not declared_scope_complete and not scope_reasons:
        scope_reasons.append("producer declared trajectory scope incomplete")
    if not declared_replay_complete and not replay_reasons:
        replay_reasons.append("producer declared trajectory replay incomplete")
    scope_complete = declared_scope_complete and not scope_reasons
    replay_complete = scope_complete and declared_replay_complete and not replay_reasons
    integrity_payload["scope_complete"] = scope_complete
    integrity_payload["replay_complete"] = replay_complete
    # ``complete`` remains a conservative compatibility alias. Publication
    # gates interpret it as byte-replay completeness, never merely "all
    # allowlisted rows were present".
    integrity_payload["complete"] = replay_complete
    integrity_payload["scope_incompleteness"] = scope_reasons
    integrity_payload["replay_incompleteness"] = replay_reasons
    integrity_payload["incompleteness"] = list(dict.fromkeys([*scope_reasons, *replay_reasons]))
    integrity_payload["quality"] = quality
    artifact: dict[str, Any] = {
        "schema_id": TRAJECTORY_SCHEMA_ID,
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "trajectory_id": trajectory_id,
        "captured_at": captured,
        "trajectory_class": list(dict.fromkeys(str(item) for item in trajectory_class)),
        "source": dict(source),
        "events": normalized,
        "outcome": dict(outcome),
        "integrity": integrity_payload,
        "privacy": dict(privacy),
        "provenance": dict(provenance),
        "runtime_event_refs": [dict(item) for item in runtime_event_refs],
        "evidence_refs": [dict(item) for item in evidence_refs],
        "artifact_digests": [dict(item) for item in artifact_digests],
    }
    if published_at is not None:
        artifact["published_at"] = _iso_timestamp(published_at)
    if observed_on is not None:
        artifact["observed_on"] = observed_on
    from core.observability.record_schema import validate_record

    validate_record(artifact)
    verify_trajectory_integrity(artifact)
    return artifact


def _trajectory_quality(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute replay and join quality from the normalized event stream."""
    event_ids = [str(event.get("event_id") or "") for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("trajectory event_id values must be unique")
    ordinals = [event.get("ordinal") for event in events]
    expected_ordinals = list(range(1, len(events) + 1))
    if ordinals != expected_ordinals:
        raise ValueError("trajectory ordinals must be contiguous from one")

    open_calls: dict[tuple[str, str, str], int] = {}
    call_count = 0
    result_count = 0
    paired = 0
    orphan_results = 0
    tool_events = 0
    missing_tool_call_ids = 0
    missing_control_call_ids = 0
    turn_scoped_events = 0
    missing_turn_ids = 0
    payload_issue_events = 0
    for event in events:
        kind = str(event.get("kind") or "")
        call_id = str(event.get("call_id") or "")
        if kind in _TURN_SCOPED_KINDS:
            turn_scoped_events += 1
            if not event.get("turn_id"):
                missing_turn_ids += 1
        if kind in _TOOL_CALL_KINDS | _TOOL_RESULT_KINDS:
            tool_events += 1
            if kind in _TOOL_CALL_KINDS:
                call_count += 1
            else:
                result_count += 1
            if not call_id:
                missing_tool_call_ids += 1
            else:
                key = (
                    str(event.get("session_id") or ""),
                    str(event.get("turn_id") or ""),
                    call_id,
                )
                if kind in _TOOL_CALL_KINDS:
                    open_calls[key] = open_calls.get(key, 0) + 1
                elif open_calls.get(key, 0):
                    paired += 1
                    open_calls[key] -= 1
                else:
                    orphan_results += 1
        if (
            kind in _CONTROL_STATE_KINDS
            and str((event.get("payload") or {}).get("trigger") or "").startswith(
                ("update_grill:", "update_geo:")
            )
            and not call_id
        ):
            missing_control_call_ids += 1
        if _payload_has_quality_issue(event.get("payload")):
            payload_issue_events += 1

    orphan_calls = sum(open_calls.values())
    scope_incompleteness = []
    replay_incompleteness = []
    if not events:
        scope_incompleteness.append("trajectory contains no events")
    if missing_tool_call_ids:
        scope_incompleteness.append(f"{missing_tool_call_ids} tool event(s) lack call_id")
    if missing_control_call_ids:
        scope_incompleteness.append(
            f"{missing_control_call_ids} tool-driven control event(s) lack call_id"
        )
    if missing_turn_ids:
        scope_incompleteness.append(f"{missing_turn_ids} turn-scoped event(s) lack turn_id")
    if orphan_calls:
        scope_incompleteness.append(f"{orphan_calls} tool call(s) lack a result")
    if orphan_results:
        scope_incompleteness.append(f"{orphan_results} tool result(s) lack a call")
    if payload_issue_events:
        replay_incompleteness.append(
            f"{payload_issue_events} event payload(s) are truncated, corrupt, or omitted"
        )

    return {
        "event_id_unique": True,
        "ordinal_contiguous": True,
        "correlation": {
            "session_id_present": sum(bool(event.get("session_id")) for event in events),
            "turn_id_present": sum(bool(event.get("turn_id")) for event in events),
            "turn_id_required": turn_scoped_events,
            "turn_id_missing": missing_turn_ids,
            "tool_call_id_present": tool_events - missing_tool_call_ids,
            "control_call_id_missing": missing_control_call_ids,
            "event_count": len(events),
        },
        "tool_pairing": {
            "calls": call_count,
            "results": result_count,
            "paired": paired,
            "orphan_calls": orphan_calls,
            "orphan_results": orphan_results,
            "missing_call_ids": missing_tool_call_ids,
        },
        "payload_issue_events": payload_issue_events,
        "replay_fidelity": "full" if payload_issue_events == 0 else "reduced",
        "_scope_incompleteness": scope_incompleteness,
        "_replay_incompleteness": replay_incompleteness,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [str(item) for item in value if str(item)]


def _declared_replay_reduction_reasons(
    *,
    privacy: Mapping[str, Any],
    integrity: Mapping[str, Any],
) -> list[str]:
    """Turn explicit publication reductions into machine-enforced quality."""
    reasons: list[str] = []
    redactions = privacy.get("redactions")
    if isinstance(redactions, Sequence) and not isinstance(redactions, str | bytes | bytearray):
        for redaction in redactions:
            if (
                isinstance(redaction, Mapping)
                and str(redaction.get("type") or "") == "content_reduction"
            ):
                reasons.append("privacy policy declares content reduction")
                break
    fidelity = str(integrity.get("fidelity") or "").strip()
    fidelity_lower = fidelity.lower()
    if fidelity and any(
        marker in fidelity_lower
        for marker in (
            "unpublished",
            "excluded",
            "content reduction",
            "digest instead",
            "reduced",
            "truncated",
        )
    ):
        reasons.append(f"declared fidelity limits replay: {fidelity[:256]}")
    return reasons


def _payload_has_quality_issue(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(
            key in value
            for key in (
                "_corrupt_payload",
                "_content_omitted",
                "_omitted_type",
                "_personal_data_omitted",
                "_timestamp_invalid",
                "_timestamp_missing",
                "_truncated",
                "_truncated_items",
            )
        ):
            return True
        return any(_payload_has_quality_issue(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_payload_has_quality_issue(item) for item in value)
    return isinstance(value, str) and (
        "…[truncated:" in value or value in {"<REDACTED>", "[REDACTED]"}
    )


def verify_trajectory_integrity(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute and verify integrity claims instead of trusting the producer."""
    from core.observability.record_schema import validate_record

    payload = dict(trajectory)
    validate_record(payload, schema_id=TRAJECTORY_SCHEMA_ID)
    events_raw = payload["events"]
    events = [dict(event) for event in events_raw]
    computed = _trajectory_quality(events)
    computed_scope_reasons = list(computed.pop("_scope_incompleteness"))
    computed_replay_reasons = list(computed.pop("_replay_incompleteness"))
    integrity = payload["integrity"]
    if integrity["record_count"] != len(events):
        raise ValueError("trajectory integrity record_count does not match events")
    if integrity["quality"] != computed:
        raise ValueError("trajectory integrity quality does not match recomputed events")
    scope_reasons = _string_list(integrity["scope_incompleteness"])
    replay_reasons = _string_list(integrity["replay_incompleteness"])
    if any(reason not in scope_reasons for reason in computed_scope_reasons):
        raise ValueError("trajectory integrity omits computed scope incompleteness")
    automatic_replay_reasons = _declared_replay_reduction_reasons(
        privacy=payload["privacy"],
        integrity=integrity,
    )
    if any(
        reason not in replay_reasons
        for reason in [*computed_replay_reasons, *automatic_replay_reasons]
    ):
        raise ValueError("trajectory integrity omits computed replay incompleteness")
    expected_scope_complete = not scope_reasons
    expected_replay_complete = expected_scope_complete and not replay_reasons
    if bool(integrity["scope_complete"]) != expected_scope_complete:
        raise ValueError("trajectory scope_complete contradicts scope incompleteness")
    if bool(integrity["replay_complete"]) != expected_replay_complete:
        raise ValueError("trajectory replay_complete contradicts replay incompleteness")
    if bool(integrity["complete"]) != expected_replay_complete:
        raise ValueError("trajectory complete alias contradicts replay completeness")
    combined_reasons = list(dict.fromkeys([*scope_reasons, *replay_reasons]))
    if _string_list(integrity["incompleteness"]) != combined_reasons:
        raise ValueError("trajectory incompleteness union does not match scoped reasons")
    digest_paths = [str(row["path"]) for row in payload.get("artifact_digests", [])]
    if len(digest_paths) != len(set(digest_paths)):
        raise ValueError("trajectory artifact digest paths must be unique")
    for field in ("runtime_event_refs", "evidence_refs"):
        references = [(str(row["kind"]), str(row["reference"])) for row in payload.get(field, [])]
        if len(references) != len(set(references)):
            raise ValueError(f"trajectory {field} identities must be unique")
    return {
        "record_count": len(events),
        "evidence_ref_count": len(payload.get("evidence_refs", [])),
        "runtime_event_ref_count": len(payload.get("runtime_event_refs", [])),
        "source_digest_ref_count": len(digest_paths),
        "complete": bool(integrity["complete"]),
        "scope_complete": bool(integrity["scope_complete"]),
        "replay_complete": bool(integrity["replay_complete"]),
    }


def trajectory_from_sessions(
    session_ids: Sequence[str],
    *,
    trajectory_id: str,
    source: Mapping[str, Any],
    db_path: Path | str | None = None,
    outcome: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    privacy: Mapping[str, Any] | None = None,
    artifact_digests: Sequence[Mapping[str, Any]] = (),
    runtime_event_refs: Sequence[Mapping[str, Any]] = (),
    evidence_refs: Sequence[Mapping[str, Any]] = (),
    content_policy: str = "full",
    runtime_event_db_path: Path | str | None = None,
    trajectory_class: Sequence[str] = ("dialogue", "tool", "lifecycle"),
) -> dict[str, Any]:
    """Build one validated trajectory from one or more canonical sessions."""
    from core.observability.session_timeline import SessionEventStore

    ordered_session_ids = list(dict.fromkeys(str(value) for value in session_ids if value))
    store = SessionEventStore(db_path)
    rows_by_session = {session_id: store.read(session_id) for session_id in ordered_session_ids}
    rows = [row for session_id in ordered_session_ids for row in rows_by_session[session_id]]
    rows.sort(key=lambda row: row.id)
    if content_policy not in {"full", "digest"}:
        raise ValueError("trajectory content_policy must be 'full' or 'digest'")
    events = []
    for row in rows:
        event_payload: dict[str, Any] = {
            **row.payload,
            "model": row.model,
            "provider": row.provider,
            "status": row.status,
            "source": row.source,
            "session_generation": row.session_generation,
            "parent_event_id": row.parent_event_id,
            "source_payload_hash": row.payload_hash,
        }
        if content_policy == "digest":
            event_payload = _digest_private_event_payload(row.kind, event_payload)
        events.append(
            {
                "event_id": row.event_id,
                "occurred_at": row.occurred_at,
                "kind": row.kind,
                "actor": row.role or "agent",
                "session_id": row.session_id,
                "turn_id": row.turn_id,
                "call_id": row.call_id,
                "payload": event_payload,
            }
        )
    incompleteness = []
    if not ordered_session_ids:
        incompleteness.append("source carried no GEODE session identifiers")
    for session_id, session_rows in rows_by_session.items():
        if not session_rows:
            incompleteness.append(f"session {session_id} has no canonical events")
            continue
        if session_rows[-1].kind != "session.ended":
            incompleteness.append(f"session {session_id} has no terminal event")
        terminal_payload = session_rows[-1].payload
        if int(terminal_payload.get("record_failures", 0) or 0) > 0:
            incompleteness.append(f"session {session_id} reports canonical write failures")
    automatic_runtime_refs = _runtime_event_references(
        Path(runtime_event_db_path) if runtime_event_db_path is not None else store.db_path,
        ordered_session_ids,
    )
    automatic_evidence_refs = _verification_evidence_references(rows)
    return build_trajectory(
        trajectory_id=trajectory_id,
        source=source,
        events=events,
        outcome=outcome or {"scored": False},
        provenance=provenance or {"store": "sessions.db:session_events"},
        privacy=privacy or {"review_state": "local"},
        trajectory_class=trajectory_class,
        integrity={
            "scope_complete": bool(rows) and not incompleteness,
            "replay_complete": bool(rows) and not incompleteness,
            "scope_incompleteness": incompleteness,
        },
        artifact_digests=artifact_digests,
        runtime_event_refs=_dedupe_external_references(
            (*runtime_event_refs, *automatic_runtime_refs)
        ),
        evidence_refs=_dedupe_external_references((*evidence_refs, *automatic_evidence_refs)),
    )


def _dedupe_external_references(
    references: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for reference in references:
        row = dict(reference)
        identity = (str(row.get("kind") or ""), str(row.get("reference") or ""))
        unique.setdefault(identity, row)
    return tuple(unique.values())


def _verification_evidence_references(
    rows: Sequence[Any],
) -> tuple[dict[str, Any], ...]:
    references: list[Mapping[str, Any]] = []
    for row in rows:
        if row.kind not in {
            "verification.evidence",
            "verification.pending",
        }:
            continue
        raw = row.payload.get("references")
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
            continue
        references.extend(item for item in raw if isinstance(item, Mapping))
    return _dedupe_external_references(references)


def _runtime_event_references(
    db_path: Path,
    session_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Bind indexed hook-event cohorts without embedding the private store."""
    if not db_path.is_file() or not session_ids:
        return ()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(hook_events)").fetchall()}
        required = {
            "id",
            "event",
            "payload_hash",
            "session_id",
            "turn_id",
            "tool_call_id",
            "llm_call_id",
            "llm_attempt_id",
        }
        if not required.issubset(columns):
            return ()
        references: list[dict[str, Any]] = []
        for session_id in session_ids:
            rows = conn.execute(
                """\
                SELECT id, event, payload_hash, turn_id, tool_call_id,
                       llm_call_id, llm_attempt_id
                FROM hook_events
                WHERE session_id = ?
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
            if not rows:
                continue
            canonical = json.dumps(
                [dict(row) for row in rows],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            digest = sha256(canonical).hexdigest()
            references.append(
                {
                    "kind": "runtime_event",
                    "schema_id": "geode.hook-event@3",
                    "authority": "GEODE local runtime hook event store",
                    "reference": f"hook-events-sha256:{digest}",
                    "session_id": session_id,
                    "record_count": len(rows),
                    "sha256": digest,
                }
            )
        return tuple(references)
    finally:
        conn.close()


def _digest_private_event_payload(
    kind: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Allowlist structural fields and digest every other benchmark payload."""
    protected = dict(payload)
    structural = {
        "model",
        "provider",
        "status",
        "source",
        "session_generation",
        "parent_event_id",
        "source_payload_hash",
    }
    safe_by_kind = {
        "session.ended": {
            "duration_s",
            "total_cost_usd",
            "rounds",
            "prompt_tokens",
            "completion_tokens",
            "record_failures",
            "projection_failed",
        },
        "turn.completed": {
            "termination_reason",
            "rounds",
            "tool_call_count",
            "failed",
            "successful",
        },
        "tool.called": {"tool"},
        "tool.completed": {"tool"},
        "usage.recorded": {"input_tokens", "output_tokens", "cost_usd"},
        "error.recorded": {"error_type"},
        "verification.evidence": {
            "references",
            "root_turn_id",
            "verify_attempt",
            "policy_action",
        },
        "verification.pending": {
            "candidate_sha256",
            "candidate_bytes",
            "root_turn_id",
            "verify_attempt",
            "references",
        },
    }
    plan_fields = {
        "plan_id",
        "revision",
        "current_step_id",
        "step_count",
        "completed_step_ids",
        "abandoned_step_ids",
        "changed_step_ids",
        "trigger",
    }
    control_fields = {"trigger"}
    allowed = structural | (
        plan_fields
        if kind.startswith("plan.")
        else control_fields
        if kind in _CONTROL_STATE_KINDS
        else safe_by_kind.get(kind, set())
    )
    omitted_payload = {field: protected.pop(field) for field in sorted(set(protected) - allowed)}
    if omitted_payload:
        raw = json.dumps(
            omitted_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        protected["_omitted_payload_sha256"] = sha256(raw).hexdigest()
        protected["_omitted_payload_bytes"] = len(raw)
        protected["_content_omitted"] = sorted(omitted_payload)
    return protected


def trajectory_from_session(
    session_id: str,
    *,
    db_path: Path | str | None = None,
    outcome: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    privacy: Mapping[str, Any] | None = None,
    artifact_digests: Sequence[Mapping[str, Any]] = (),
    runtime_event_refs: Sequence[Mapping[str, Any]] = (),
    evidence_refs: Sequence[Mapping[str, Any]] = (),
    content_policy: str = "full",
) -> dict[str, Any]:
    """Build a validated trajectory directly from canonical SQLite history."""
    return trajectory_from_sessions(
        (session_id,),
        trajectory_id=f"geode-session-{session_id}",
        source={"harness": "geode", "run": session_id, "session": session_id, "parents": None},
        db_path=db_path,
        outcome=outcome,
        provenance=provenance,
        privacy=privacy,
        artifact_digests=artifact_digests,
        runtime_event_refs=runtime_event_refs,
        evidence_refs=evidence_refs,
        content_policy=content_policy,
    )


def export_trajectory(path: Path | str, trajectory: Mapping[str, Any]) -> Path:
    """Validate then atomically write one trajectory JSON artifact."""
    payload = dict(trajectory)
    from core.observability.record_schema import validate_record

    validate_record(payload, schema_id=TRAJECTORY_SCHEMA_ID)
    verify_trajectory_integrity(payload)
    destination = Path(path)
    atomic_write_json(destination, payload, indent=2)
    return destination


def normalize_trajectory_artifact(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    """Read current or dated artifact-repository trajectories as ``@1``.

    Published dated releases are immutable. This adapter migrates their
    ``sequence``/``timestamp`` event names in memory and never rewrites the
    original artifact.
    """
    schema_id = str(trajectory.get("schema_id") or "")
    if schema_id == TRAJECTORY_SCHEMA_ID:
        payload = dict(trajectory)
        from core.observability.record_schema import validate_record

        validate_record(payload, schema_id=TRAJECTORY_SCHEMA_ID)
        return payload
    if not schema_id.startswith("geode.trajectory@20"):
        raise ValueError(f"unsupported trajectory schema: {schema_id!r}")
    source_raw = trajectory.get("source")
    source = dict(source_raw) if isinstance(source_raw, Mapping) else {}
    trajectory_id = str(trajectory.get("trajectory_id") or "")
    source["session"] = str(
        source.get("session") or source.get("run") or trajectory_id or "legacy-publication"
    )
    raw_events = trajectory.get("events")
    events = []
    if isinstance(raw_events, Sequence) and not isinstance(raw_events, str | bytes):
        for raw in raw_events:
            if not isinstance(raw, Mapping):
                continue
            payload_raw = raw.get("payload")
            payload = dict(payload_raw) if isinstance(payload_raw, Mapping) else {}
            legacy_occurred_at = (
                raw.get("occurred_at")
                if raw.get("occurred_at") is not None
                else (raw.get("timestamp") if raw.get("timestamp") is not None else raw.get("ts"))
            )
            if legacy_occurred_at is None:
                payload["_timestamp_missing"] = True
            else:
                try:
                    _iso_timestamp(legacy_occurred_at)
                except ValueError:
                    payload["_timestamp_invalid"] = True
                    legacy_occurred_at = None
            events.append(
                {
                    "event_id": raw.get("event_id"),
                    "occurred_at": legacy_occurred_at,
                    "kind": raw.get("kind"),
                    "actor": raw.get("actor"),
                    "session_id": raw.get("session_id", source["session"]),
                    "turn_id": raw.get("turn_id", ""),
                    "call_id": raw.get("call_id", payload.get("call_id", "")),
                    "payload": payload,
                }
            )
    provenance_raw = trajectory.get("provenance")
    provenance = dict(provenance_raw) if isinstance(provenance_raw, Mapping) else {}
    provenance["migrated_from_schema_id"] = schema_id
    integrity_raw = trajectory.get("integrity")
    legacy_integrity = dict(integrity_raw) if isinstance(integrity_raw, Mapping) else {}
    privacy_raw = trajectory.get("privacy")
    legacy_incompleteness_raw = legacy_integrity.get("incompleteness")
    legacy_incompleteness = (
        [str(item) for item in legacy_incompleteness_raw if str(item)]
        if isinstance(legacy_incompleteness_raw, Sequence)
        and not isinstance(legacy_incompleteness_raw, str | bytes)
        else []
    )
    legacy_fidelity = str(legacy_integrity.get("fidelity") or "").strip()
    legacy_privacy = privacy_raw if isinstance(privacy_raw, Mapping) else {}
    legacy_redactions = legacy_privacy.get("redactions")
    if "complete" not in legacy_integrity:
        legacy_incompleteness.append("legacy publication does not declare replay completeness")
    if legacy_fidelity:
        legacy_incompleteness.append(f"legacy fidelity scope: {legacy_fidelity[:256]}")
    if (
        isinstance(legacy_redactions, Sequence)
        and not isinstance(legacy_redactions, str | bytes)
        and legacy_redactions
    ):
        legacy_incompleteness.append("legacy publication declares privacy redactions")
    trajectory_class_raw = trajectory.get("trajectory_class")
    trajectory_class = (
        trajectory_class_raw
        if isinstance(trajectory_class_raw, Sequence)
        and not isinstance(trajectory_class_raw, str | bytes)
        else ()
    )
    outcome_raw = trajectory.get("outcome")
    artifact_digests_raw = trajectory.get("artifact_digests")
    runtime_event_refs_raw = trajectory.get("runtime_event_refs")
    evidence_refs_raw = trajectory.get("evidence_refs")
    return build_trajectory(
        trajectory_id=trajectory_id or f"migrated-{sha256(schema_id.encode()).hexdigest()[:16]}",
        captured_at=trajectory.get("captured_at"),
        published_at=trajectory.get("published_at"),
        observed_on=(
            str(trajectory["observed_on"]) if trajectory.get("observed_on") is not None else None
        ),
        trajectory_class=trajectory_class,
        source=source,
        events=events,
        outcome=outcome_raw if isinstance(outcome_raw, Mapping) else {"scored": False},
        provenance=provenance,
        privacy=(privacy_raw if isinstance(privacy_raw, Mapping) else {"review_state": "unknown"}),
        integrity={
            "scope_complete": True,
            "replay_complete": False,
            "scope_incompleteness": [],
            "replay_incompleteness": legacy_incompleteness,
            "fidelity": legacy_fidelity,
            "legacy_integrity": legacy_integrity,
        },
        artifact_digests=(
            artifact_digests_raw
            if isinstance(artifact_digests_raw, Sequence)
            and not isinstance(artifact_digests_raw, str | bytes)
            else ()
        ),
        runtime_event_refs=_normalize_legacy_references(
            runtime_event_refs_raw,
            default_kind="runtime_event",
        ),
        evidence_refs=_normalize_legacy_references(
            evidence_refs_raw,
            default_kind="legacy",
        ),
    )


def _normalize_legacy_references(
    raw_refs: Any,
    *,
    default_kind: str,
) -> tuple[dict[str, Any], ...]:
    """Upgrade dated free-form refs to the typed external-join contract."""
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, str | bytes):
        return ()
    normalized = []
    for index, raw in enumerate(raw_refs, start=1):
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        canonical = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        row.setdefault("kind", default_kind)
        row.setdefault("schema_id", "legacy.external-reference")
        row.setdefault("authority", "immutable legacy publication")
        row.setdefault(
            "reference",
            str(
                row.get("path")
                or row.get("id")
                or row.get("contract_id")
                or f"legacy-{index}-{sha256(canonical.encode()).hexdigest()[:16]}"
            ),
        )
        normalized.append(row)
    return tuple(normalized)


def to_k3(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a ``geode.trajectory@1`` artifact to the retained K3 shape."""
    if trajectory.get("schema_id") != TRAJECTORY_SCHEMA_ID:
        raise ValueError("to_k3 requires geode.trajectory@1")
    from core.observability.record_paths import normalize_event_row

    rows = []
    for event in trajectory.get("events", []):
        if not isinstance(event, dict):
            continue
        row = normalize_event_row(
            {
                "schema_id": "geode.session-event@1",
                "occurred_at": event.get("occurred_at"),
                "ordinal": event.get("ordinal"),
                "kind": event.get("kind"),
                "session_id": event.get("session_id"),
                "turn_id": event.get("turn_id"),
                "call_id": event.get("call_id"),
                "payload": event.get("payload", {}),
            }
        )
        rows.append(row)
    messages = _messages(rows)
    return {
        "schema": "k3-shaped/1",
        "source_schema": TRAJECTORY_SCHEMA_ID,
        "trajectory_id": trajectory.get("trajectory_id", ""),
        "pairing": _pairing(messages),
        "messages": messages,
    }


def resolve(session: str | Path) -> Path:
    """Return the trajectory file for a session id, or the path itself."""
    p = Path(session)
    if p.is_file():
        return p
    hits = sorted(GLOBAL_TRANSCRIPTS_DIR.glob(f"*/{session}.jsonl"))
    if hits:
        return hits[0]
    hits = sorted(CODEX_SESSIONS_DIR.glob(f"**/*{session}*.jsonl"))
    if hits:
        return hits[0]
    raise FileNotFoundError(f"no trajectory for session {session!r}")


def discover(harness: str) -> list[Path]:
    """Every trajectory file for one harness, oldest first by mtime."""
    if harness == "geode":
        paths = GLOBAL_TRANSCRIPTS_DIR.glob("*/*.jsonl")
    elif harness == "codex":
        paths = CODEX_SESSIONS_DIR.glob("**/*.jsonl")
    else:
        raise ValueError(f"unknown harness {harness!r}")
    return sorted(paths, key=lambda p: p.stat().st_mtime)


def _arguments(raw: Any) -> dict[str, Any]:
    """Recover typed tool arguments from the transcript's serialized ``input``.

    ``record_tool_call`` stores ``json.dumps(...)`` truncated to 300 chars, so
    long arguments reach disk as a fragment that no longer parses. Restoring the
    dict when it does parse keeps K3's typed-argument property; flagging it when
    it does not stops a truncated blob from being read as real arguments.
    """
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_truncated": str(raw)}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _rows(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a truncated tail row must not sink the whole replay
    # ``seq`` restarted at 1 for every retired transcript-writer instance, so a session id
    # reused across runs produces repeating and decreasing seq within one file
    # (189 of 14,970 decrease, 357 repeat). Ordering by seq alone interleaves
    # those runs; ``ts`` separates them and the stable sort keeps append order
    # for rows written inside the same clock tick.
    out.sort(key=lambda r: (r.get("ts", 0.0), r.get("seq", 0)))
    return out


def _messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    asst: dict[str, Any] | None = None
    tool: dict[str, Any] | None = None
    pending: list[tuple[str, int]] = []  # (tool name, index) awaiting a result
    by_call_id: dict[str, int] = {}
    starts = 0
    ended = False

    def run() -> int:
        # dialogue after session_end with no new session_start belongs to its own
        # run, not to the one that already closed
        return max(0, starts - 1) + (1 if ended else 0)

    def open_asst() -> dict[str, Any]:
        nonlocal asst
        if asst is None:
            # turn_id stays empty: GEODE records no turn key, and dropping the
            # field would make the gap invisible once both harnesses are merged
            asst = {
                "role": "assistant",
                "run": run(),
                "turn_id": "",
                "think": "",
                "response": "",
                "tools": [],
            }
            msgs.append(asst)
        return asst

    for r in rows:
        event = r.get("event")

        if event in ("session_start", "session_end"):
            # One transcript file accumulates every run that reused this
            # session_id, so a flat message list would splice separate
            # conversations into one. Runs are numbered, not merged.
            # session_end closes the run too: 7 files continue emitting dialogue
            # after an end with no following start, and those 23 events would
            # otherwise be attributed to the run that already finished.
            starts += 1 if event == "session_start" else 0
            ended = event == "session_end"
            asst = tool = None
            pending.clear()
            by_call_id.clear()
            continue

        if event not in _DIALOGUE_EVENTS:
            continue

        if ended:
            starts += 1
            ended = False

        if event == "user_message":
            asst = tool = None
            msgs.append({"role": "user", "run": run(), "turn_id": "", "content": r.get("text", "")})

        elif event == "tool_call":
            tool = None
            m = open_asst()
            index = len(m["tools"])
            name = r.get("tool", "")
            call_id = r.get("call_id") or ""
            m["tools"].append(
                {
                    "tool": name,
                    "index": index,
                    "call_id": call_id,
                    "arguments": _arguments(r.get("input")),
                }
            )
            pending.append((name, index))
            if call_id:
                by_call_id[call_id] = index

        elif event == "tool_result":
            asst = None
            if tool is None:
                tool = {"role": "tool", "run": run(), "turn_id": "", "results": []}
                msgs.append(tool)
            name = r.get("tool", "")
            call_id = r.get("call_id") or ""
            if call_id and call_id in by_call_id:
                index = by_call_id.pop(call_id)
            else:
                # Rows written before call_id was threaded through carry no id, so
                # order is the only signal left. Two concurrent calls to the same
                # tool returning out of order will cross; ``pairing`` reports which
                # rule produced each index so a consumer can tell them apart.
                index = len(tool["results"])
                for i, (pname, pindex) in enumerate(pending):
                    if pname == name:
                        index = pindex
                        pending.pop(i)
                        break
            tool["results"].append(
                {
                    "tool": name,
                    "index": index,
                    "call_id": call_id,
                    "status": r.get("status", ""),
                    "summary": r.get("summary", ""),
                }
            )

        elif event == "assistant_message":
            tool = None
            open_asst()["response"] = r.get("text", "")
            asst = None  # a text response closes the message

    return msgs


_CODEX_CALLS = {"function_call", "custom_tool_call", "tool_search_call", "local_shell_call"}
_CODEX_OUTPUTS = {
    "function_call_output",
    "custom_tool_call_output",
    "tool_search_output",
    "local_shell_call_output",
}


def _codex_text(content: Any) -> str:
    """Flatten a Responses-API content list into plain text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


def _codex_call_args(payload: dict[str, Any]) -> dict[str, Any]:
    """Arguments for one Codex tool call, keeping free-form text unescaped.

    ``custom_tool_call`` carries its argument as raw text (an ``apply_patch``
    hunk, a shell script) rather than JSON. Running it through the JSON parser
    would flag valid input as malformed, so the raw form is kept under ``input``
    — which is also K3's stated reason for typing arguments instead of nesting
    an escaped JSON string.
    """
    if payload.get("type") == "custom_tool_call":
        return {"input": payload.get("input", "")}
    raw = payload.get("arguments")
    if isinstance(raw, dict):
        return raw
    return _arguments(raw)


def _turn(payload: dict[str, Any]) -> str:
    """Codex's turn key, the middle level of its session → turn → call hierarchy.

    GEODE has no equivalent: a transcript carries only a session id and a
    per-row ``seq``, so a group of rows cannot be attributed to one turn. Keeping
    the field here makes the gap visible rather than flattening both harnesses to
    the weaker key.
    """
    meta = payload.get("internal_chat_message_metadata_passthrough") or {}
    return meta.get("turn_id", "") if isinstance(meta, dict) else ""


def _codex_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a Codex rollout onto the same message list as a GEODE session."""
    msgs: list[dict[str, Any]] = []
    asst: dict[str, Any] | None = None
    tool: dict[str, Any] | None = None
    think: list[str] = []
    index_of: dict[str, int] = {}  # call_id -> index within its assistant message
    name_of: dict[str, str] = {}
    turn = ""

    def open_asst() -> dict[str, Any]:
        nonlocal asst
        if asst is None:
            asst = {
                "role": "assistant",
                "run": 0,
                "turn_id": turn,
                "think": "",
                "response": "",
                "tools": [],
            }
            msgs.append(asst)
        if think:
            # append: several reasoning items can land in one assistant message
            # when parallel calls are interleaved, and assigning would drop all
            # but the last
            joined = "\n".join(think).strip()
            asst["think"] = f"{asst['think']}\n{joined}".strip() if asst["think"] else joined
            think.clear()
        return asst

    for r in rows:
        if r.get("type") != "response_item":
            continue
        p = r.get("payload") or {}
        kind = p.get("type")
        turn = _turn(p) or turn

        if kind == "reasoning":
            # encrypted_content is opaque to us; the summary is the readable trace
            think.extend(
                s.get("text", "")
                for s in (p.get("summary") or [])
                if isinstance(s, dict) and s.get("text")
            )

        elif kind == "message":
            role = p.get("role")
            text = _codex_text(p.get("content"))
            if role == "assistant":
                tool = None
                open_asst()["response"] = text
                asst = None
            else:
                asst = tool = None
                msgs.append(
                    {
                        "role": "system" if role == "developer" else "user",
                        "run": 0,
                        "turn_id": turn,
                        "content": text,
                    }
                )

        elif kind in _CODEX_CALLS:
            tool = None
            m = open_asst()
            index = len(m["tools"])
            name = p.get("name") or kind
            call_id = p.get("call_id") or ""
            m["tools"].append(
                {
                    "tool": name,
                    "index": index,
                    "arguments": _codex_call_args(p),
                    "call_id": call_id,
                }
            )
            index_of[call_id] = index
            name_of[call_id] = name

        elif kind in _CODEX_OUTPUTS:
            asst = None
            if tool is None:
                tool = {"role": "tool", "run": 0, "turn_id": turn, "results": []}
                msgs.append(tool)
            call_id = p.get("call_id") or ""
            output = p.get("output")
            if output is None and p.get("tools") is not None:
                output = json.dumps(p["tools"], ensure_ascii=False)
            tool["results"].append(
                {
                    "tool": name_of.get(call_id, kind),
                    "index": index_of.get(call_id, len(tool["results"])),
                    "status": p.get("status", "") or "",
                    "summary": output if isinstance(output, str) else "",
                    "call_id": call_id,
                }
            )

    return msgs


_MODELLED_EVENTS = _DIALOGUE_EVENTS | {"session_start", "session_end", "task_preflight"}


def _preflight(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-run environment snapshot — GEODE's analogue of Codex ``turn_context``.

    ``task_preflight`` is 18.4% of all transcript rows (185,688 of 1,009,468) and
    records the capability graph and required evidence the run started under. It
    is not conversation, so it stays out of the message list, but dropping it
    loses the answer to "what was this run configured to do".
    """
    out: list[dict[str, Any]] = []
    graphs: dict[str, Any] = {}
    run = 0
    for r in rows:
        event = r.get("event")
        if event == "session_start":
            run += 1
        elif event == "task_preflight":
            payload = dict(r.get("payload") or {})
            # The writer emits the capability graph once and then references it
            # by digest, so a later row carries only the hash. Resolving it here
            # keeps every entry self-contained without storing 43.4 MB of
            # repeated graph across 19 distinct values.
            digest = payload.get("capability_graph_sha256")
            if "capability_graph" in payload:
                if digest:
                    graphs[str(digest)] = payload["capability_graph"]
            elif digest and str(digest) in graphs:
                payload["capability_graph"] = graphs[str(digest)]
            out.append({"run": max(0, run - 1), "payload": payload})
    return out


def _unmodelled(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Events this projection drops, counted rather than silently discarded."""
    counts: dict[str, int] = {}
    for r in rows:
        event = r.get("event")
        if event and event not in _MODELLED_EVENTS:
            counts[str(event)] = counts.get(str(event), 0) + 1
    return counts


def _pairing(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """How each tool result got its index — exactly, or by guessing at order.

    A consumer cannot otherwise tell the two apart: both produce the same
    ``index`` field, but only the id-matched one is a fact.
    """
    results = [r for m in messages if m["role"] == "tool" for r in m["results"]]
    exact = sum(1 for r in results if r.get("call_id"))
    return {
        "results": len(results),
        "by_call_id": exact,
        "positional": len(results) - exact,
        "mode": "call_id" if exact == len(results) and results else "positional",
    }


def _codex_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for r in rows:
        if r.get("type") == "session_meta":
            p = r.get("payload") or {}
            return {
                "session_id": p.get("session_id") or p.get("id") or "",
                "cwd": p.get("cwd", ""),
                "cli_version": p.get("cli_version", ""),
                "originator": p.get("originator", ""),
                "forked_from_id": p.get("forked_from_id") or "",
            }
    return {}


def _is_codex(rows: list[dict[str, Any]]) -> bool:
    return any(r.get("type") in {"session_meta", "response_item"} for r in rows[:20])


def load(session: str | Path, *, evidence: bool = True) -> dict[str, Any]:
    """Replay one session as a K3-shaped trajectory.

    ``evidence`` rows are returned alongside rather than interleaved: they are
    judgment records keyed by ``kind``, not conversation turns, and folding them
    into the message list would imply an ordering the writers never guaranteed.
    """
    path = resolve(session)
    rows = _rows(path)

    if _is_codex(rows):
        meta = _codex_meta(rows)
        codex_msgs = _codex_messages(rows)
        return {
            "harness": "codex",
            "session_id": meta.get("session_id") or path.stem,
            "source": str(path),
            "meta": meta,
            "pairing": _pairing(codex_msgs),
            "messages": codex_msgs,
        }

    session_id = path.stem
    messages = _messages(rows)
    out: dict[str, Any] = {
        "harness": "geode",
        "session_id": session_id,
        "source": str(path),
        "meta": {
            "runs": max((m["run"] for m in messages), default=-1) + 1,
            "preflight": _preflight(rows),
            "unmodelled_events": _unmodelled(rows),
        },
        "pairing": _pairing(messages),
        "messages": messages,
    }
    if evidence:
        ev = GEODE_HOME / "evidence" / f"{session_id}.jsonl"
        out["evidence"] = _rows(ev) if ev.is_file() else []
        out["hooks"] = _hooks(session_id)
    return out


def _hooks(session_id: str) -> list[dict[str, Any]]:
    """Hook events for one session, joined on the trajectory's own key.

    ``hook_events`` names the column ``session_key`` while the transcript calls
    the same value ``session_id``; the delegate writer fills both from one
    source, so this is a real join rather than a guess. The orchestrator lane
    (``subject:*``) uses ``session_key`` for a different thing and simply misses,
    which is the correct outcome — it has no transcript to attach to.
    """
    try:
        from core.memory.session_manager import _get_default_db_path

        db = _get_default_db_path()
        if not db.exists():
            return []
        # read-only: this database is live, and a reader must never lock it
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            cur = con.execute(
                "SELECT occurred_at, event, action, entity_type, entity_id, status, "
                "level, blocked, block_reason, run_id FROM hook_events "
                "WHERE session_key = ? ORDER BY occurred_at, id",
                (session_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        finally:
            con.close()
    except sqlite3.Error:
        return []


def merge(
    limit: int | None = None, harnesses: tuple[str, ...] = ("geode", "codex")
) -> dict[str, Any]:
    """Every discoverable trajectory in one object, newest ``limit`` per harness.

    ``coverage`` reports how many files each harness has and how many were read,
    so a bounded export never reads as a complete one. Files that fail to parse
    are counted in ``failed`` rather than dropped silently.
    """
    out: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for harness in harnesses:
        found = discover(harness)
        picked = found[-limit:] if limit else found
        failed = 0
        for path in picked:
            try:
                out.append(load(path))
            except Exception:
                failed += 1
        coverage[harness] = {
            "available": len(found),
            "read": len(picked) - failed,
            "skipped_by_limit": len(found) - len(picked),
            "failed": failed,
        }
    msgs = sum(len(t["messages"]) for t in out)
    calls = sum(len(m["tools"]) for t in out for m in t["messages"] if m["role"] == "assistant")
    return {
        "schema": "k3-shaped/1",
        "coverage": coverage,
        "totals": {"trajectories": len(out), "messages": msgs, "tool_calls": calls},
        "trajectories": out,
    }


def _self_check() -> None:
    # one transcript file, two runs that reused the session id
    two_runs = _messages(
        [
            {"seq": 1, "event": "session_start"},
            {"seq": 2, "event": "tool_call", "tool": "Read", "input": "{}"},
            {"seq": 3, "event": "tool_result", "tool": "Read", "status": "ok"},
            {"seq": 4, "event": "session_end"},
            {"seq": 5, "event": "session_start"},
            {"seq": 6, "event": "tool_call", "tool": "Read", "input": "{}"},
        ]
    )
    assert [m["run"] for m in two_runs] == [0, 0, 1], two_runs
    # a call left open by run 0 must not absorb run 1's result
    assert two_runs[0]["tools"][0]["index"] == 0 and two_runs[2]["tools"][0]["index"] == 0

    # call_id, once written, outranks order even when results come back swapped
    paired = _messages(
        [
            {"seq": 1, "event": "tool_call", "tool": "Bash", "input": "{}", "call_id": "a"},
            {"seq": 2, "event": "tool_call", "tool": "Bash", "input": "{}", "call_id": "b"},
            {"seq": 3, "event": "tool_result", "tool": "Bash", "status": "ok", "call_id": "b"},
            {"seq": 4, "event": "tool_result", "tool": "Bash", "status": "ok", "call_id": "a"},
        ]
    )
    assert [r["index"] for r in paired[1]["results"]] == [1, 0], paired[1]
    assert _pairing(paired)["mode"] == "call_id"
    assert _pairing(two_runs)["positional"] == 1

    rows = [
        {"seq": 1, "event": "user_message", "text": "hi"},
        {"seq": 2, "event": "tool_call", "tool": "Read", "input": '{"p": "a"}'},
        {"seq": 3, "event": "tool_call", "tool": "Grep", "input": '{"q": "x"'},
        {"seq": 4, "event": "tool_result", "tool": "Grep", "status": "ok", "summary": "g"},
        {"seq": 5, "event": "tool_result", "tool": "Read", "status": "ok", "summary": "r"},
        {"seq": 6, "event": "assistant_message", "text": "done"},
    ]
    m = _messages(rows)
    assert [x["role"] for x in m] == ["user", "assistant", "tool", "assistant"], m
    assert m[1]["tools"] == [
        {"tool": "Read", "index": 0, "call_id": "", "arguments": {"p": "a"}},
        # truncated on write, so it is flagged rather than passed off as arguments
        {"tool": "Grep", "index": 1, "call_id": "", "arguments": {"_truncated": '{"q": "x"'}},
    ]
    # out-of-order results keep their call's index, not their arrival position
    assert [(r["tool"], r["index"]) for r in m[2]["results"]] == [("Grep", 1), ("Read", 0)]
    assert m[3]["response"] == "done" and m[3]["think"] == ""

    def item(payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": "response_item", "payload": payload}

    def reasoning(text: str) -> dict[str, Any]:
        return item({"type": "reasoning", "summary": [{"type": "summary_text", "text": text}]})

    c = _codex_messages(
        [
            item({"type": "message", "role": "user", "content": [{"text": "go"}]}),
            reasoning("first"),
            item(
                {
                    "type": "function_call",
                    "name": "shell",
                    "call_id": "c1",
                    "arguments": '{"cmd": "ls"}',
                }
            ),
            reasoning("second"),
            item(
                {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "c2",
                    "input": "*** Begin Patch",
                }
            ),
            item({"type": "function_call_output", "call_id": "c2", "output": "patched"}),
            item({"type": "function_call_output", "call_id": "c1", "output": "a\nb"}),
            item({"type": "message", "role": "assistant", "content": [{"text": "ok"}]}),
        ]
    )
    assert [x["role"] for x in c] == ["user", "assistant", "tool", "assistant"], c
    # both reasoning blocks survive; assigning instead of appending dropped "first"
    assert c[1]["think"] == "first\nsecond", c[1]["think"]
    assert [(t["tool"], t["index"]) for t in c[1]["tools"]] == [("shell", 0), ("apply_patch", 1)]
    # a patch hunk is raw text, not JSON, and must not be flagged as malformed
    assert c[1]["tools"][1]["arguments"] == {"input": "*** Begin Patch"}
    # call_id pairing survives out-of-order returns
    assert [(r["tool"], r["index"]) for r in c[2]["results"]] == [("apply_patch", 1), ("shell", 0)]
    assert c[3]["response"] == "ok"

    # every message carries turn_id in both harnesses, empty where GEODE has none
    assert all("turn_id" in x for x in m + c)
    t = _codex_messages(
        [
            item(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"text": "go"}],
                    "internal_chat_message_metadata_passthrough": {"turn_id": "t1"},
                }
            ),
            item({"type": "function_call", "name": "shell", "call_id": "c1", "arguments": "{}"}),
        ]
    )
    # the turn key carries forward to rows that omit it
    assert [x["turn_id"] for x in t] == ["t1", "t1"], t
    print("ok")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--self-check" in args:
        _self_check()
    elif "--merge" in args:
        rest = [a for a in args if a != "--merge"]
        limit = int(rest[0]) if rest else None
        print(json.dumps(merge(limit), ensure_ascii=False, indent=2))
    elif args:
        print(json.dumps(load(args[0]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
