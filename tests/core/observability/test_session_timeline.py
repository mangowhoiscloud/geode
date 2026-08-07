"""Storage-contract coverage for the SQLite session timeline."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.agent.loop._lifecycle import mark_session_error_async, record_timeline_end
from core.hooks import HookRegistry
from core.observability.session_timeline import (
    SESSION_EVENT_SCHEMA_ID,
    SESSION_EVENT_SCHEMA_VERSION,
    SessionEventKind,
    SessionEventPolicy,
    SessionEventStore,
    SessionEventWrite,
    SessionTimeline,
)


def _initialize_store_in_process(args: tuple[str, int]) -> str:
    db_path, index = args
    store = SessionEventStore(db_path)
    return store.append(
        SessionEventWrite(
            session_id=f"s-process-first-use-{index}",
            kind=SessionEventKind.SESSION_STARTED,
        )
    ).event_id


def test_timeline_persists_versioned_turn_and_call_correlation(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    timeline = SessionTimeline("s-1", db_path=db)
    timeline.bind_turn("t-1", session_generation=2)

    timeline.record_session_start(model="gpt-5.6", provider="openai")
    timeline.record_user_message("inspect the workspace")
    timeline.record_tool_call("read_file", {"path": "README.md"}, call_id="call-1")
    timeline.record_tool_result("read_file", "ok", "loaded", call_id="call-1")
    timeline.record_assistant_message("done")
    timeline.record_session_end(rounds=1)

    rows = SessionEventStore(db).read("s-1")
    assert [row.kind for row in rows] == [
        "session.started",
        "message.user",
        "tool.called",
        "tool.completed",
        "message.assistant",
        "session.ended",
    ]
    assert {row.turn_id for row in rows} == {"t-1"}
    assert {row.session_generation for row in rows} == {2}
    tool_rows = [row for row in rows if row.call_id]
    assert len(tool_rows) == 2
    assert {row.call_id for row in tool_rows} == {"call-1"}
    assert rows[0].as_dict()["schema_id"] == SESSION_EVENT_SCHEMA_ID
    assert rows[0].schema_version == SESSION_EVENT_SCHEMA_VERSION


def test_session_start_is_once_per_generation(tmp_path: Path) -> None:
    timeline = SessionTimeline("s-1", db_path=tmp_path / "sessions.db")
    timeline.bind_turn("t-1")
    timeline.record_session_start()
    timeline.bind_turn("t-2")
    timeline.record_session_start()
    timeline.rebind("s-1", session_generation=2)
    timeline.bind_turn("t-3", session_generation=2)
    timeline.record_session_start()

    rows = SessionEventStore(timeline.db_path).read("s-1", kinds=[SessionEventKind.SESSION_STARTED])
    assert [row.session_generation for row in rows] == [1, 2]
    assert [row.turn_id for row in rows] == ["t-1", "t-3"]


def test_verification_decision_targets_candidate_without_copying_it(tmp_path: Path) -> None:
    timeline = SessionTimeline("s-verify", db_path=tmp_path / "sessions.db")
    timeline.bind_turn("attempt-turn")
    timeline.record_verification_decision(
        candidate="private candidate",
        root_turn_id="root-turn",
        verify_attempt=1,
        built_in_passed=False,
        policy_action="revise",
        decisions=[
            {
                "surface": "PostVerify",
                "handler": "runtime_default",
                "action": "revise",
                "reason": "empty_post_verify_decision_set",
                "instruction_sha256": "abc",
                "instruction_bytes": 3,
                "evidence_refs": [],
            }
        ],
    )

    [row] = SessionEventStore(timeline.db_path).read(
        "s-verify", kinds=[SessionEventKind.VERIFICATION_DECIDED]
    )
    assert row.kind == "verification.decided"
    assert row.payload["root_turn_id"] == "root-turn"
    assert row.payload["verify_attempt"] == 1
    assert row.payload["policy_action"] == "revise"
    assert row.payload["candidate_bytes"] == len(b"private candidate")
    assert "private candidate" not in json.dumps(row.payload)


def test_read_combines_turn_kind_cursor_and_limit_filters(tmp_path: Path) -> None:
    store = SessionEventStore(tmp_path / "sessions.db")
    for turn_id, kind in (
        ("turn-1", SessionEventKind.USER_MESSAGE),
        ("turn-1", SessionEventKind.ASSISTANT_MESSAGE),
        ("turn-2", SessionEventKind.USER_MESSAGE),
        ("turn-2", SessionEventKind.ASSISTANT_MESSAGE),
    ):
        store.append(
            SessionEventWrite(
                session_id="s-filter",
                turn_id=turn_id,
                kind=kind,
                payload={"content": f"{turn_id}:{kind.value}"},
            )
        )

    rows = store.read(
        "s-filter",
        after_id=1,
        turn_id="turn-2",
        kinds=[SessionEventKind.USER_MESSAGE, SessionEventKind.ASSISTANT_MESSAGE],
        limit=1,
    )

    assert len(rows) == 1
    assert rows[0].turn_id == "turn-2"
    assert rows[0].kind == SessionEventKind.USER_MESSAGE


def test_next_generation_advances_from_durable_history(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    first_process = SessionTimeline("s-resume", db_path=db)
    first_process.rebind("s-resume", session_generation=2)
    first_process.record_session_start()

    fresh_process = SessionTimeline("new-placeholder", db_path=db)

    assert fresh_process.next_generation("s-resume") == 3


def test_payload_redacts_secrets_and_preserves_typed_tool_arguments(tmp_path: Path) -> None:
    store = SessionEventStore(tmp_path / "sessions.db")
    stored = store.append(
        SessionEventWrite(
            session_id="s-redact",
            kind=SessionEventKind.TOOL_CALLED,
            payload={
                "tool": "http",
                "arguments": {
                    "count": 3,
                    "authorization": "Bearer sk-secret-value",
                },
            },
        )
    )

    assert stored.payload["arguments"]["count"] == 3
    encoded = json.dumps(stored.payload)
    assert "sk-secret-value" not in encoded
    assert "REDACTED" in encoded


def test_schema_constrained_fields_match_sqlite_and_projection(tmp_path: Path) -> None:
    projection = tmp_path / "events.jsonl"
    store = SessionEventStore(tmp_path / "sessions.db")
    long_turn = "turn-" + ("x" * 400)
    stored = store.append(
        SessionEventWrite(
            session_id="s-fields",
            turn_id=long_turn,
            kind=SessionEventKind.USER_MESSAGE,
        )
    )

    assert len(stored.turn_id) == 256
    assert stored.turn_id == store.read("s-fields")[0].turn_id
    from core.observability.record_schema import validate_record

    validate_record(stored.as_dict())

    timeline = SessionTimeline(
        "s-projected-fields",
        db_path=tmp_path / "sessions.db",
        projection_path=projection,
    )
    timeline.bind_turn(long_turn)
    timeline.record_user_message("hello")
    projected = json.loads(projection.read_text().splitlines()[0])
    assert len(projected["turn_id"]) == 256
    validate_record(projected)


@pytest.mark.parametrize(
    "event",
    [
        SessionEventWrite(session_id="", kind=SessionEventKind.USER_MESSAGE),
        SessionEventWrite(
            session_id="s-invalid",
            kind=SessionEventKind.USER_MESSAGE,
            occurred_at=float("nan"),
        ),
        SessionEventWrite(
            session_id="s-invalid",
            event_id="x" * 129,
            kind=SessionEventKind.USER_MESSAGE,
        ),
    ],
)
def test_invalid_session_event_envelopes_fail_closed(
    tmp_path: Path,
    event: SessionEventWrite,
) -> None:
    with pytest.raises(ValueError):
        SessionEventStore(tmp_path / "sessions.db").append(event)


def test_corrupt_payload_is_explicit_without_hiding_other_rows(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    first = store.append(
        SessionEventWrite(session_id="s-corrupt", kind=SessionEventKind.USER_MESSAGE)
    )
    store.append(SessionEventWrite(session_id="s-corrupt", kind=SessionEventKind.ASSISTANT_MESSAGE))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE session_events SET payload_json = '{' WHERE id = ?", (first.id,))
        conn.commit()

    rows = store.read("s-corrupt")
    assert len(rows) == 2
    assert rows[0].corrupt_payload is True
    assert rows[0].payload == {"_corrupt_payload": True}
    assert rows[1].corrupt_payload is False


def test_valid_json_payload_tampering_is_detected_by_hash(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    stored = store.append(
        SessionEventWrite(session_id="s-tamper", kind=SessionEventKind.USER_MESSAGE)
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE session_events SET payload_json = ? WHERE id = ?",
            ('{"content":"changed"}', stored.id),
        )
        conn.commit()

    [row] = store.read("s-tamper")
    assert row.corrupt_payload is True
    assert row.payload["_corrupt_reason"] == "payload_hash_mismatch"


def test_concurrent_writers_get_unique_ids_and_database_order(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    SessionEventStore(db)

    def append(index: int) -> str:
        return (
            SessionEventStore(db)
            .append(
                SessionEventWrite(
                    session_id="s-concurrent",
                    kind=SessionEventKind.USER_MESSAGE,
                    payload={"index": index},
                )
            )
            .event_id
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        event_ids = list(pool.map(append, range(40)))

    rows = SessionEventStore(db).read("s-concurrent")
    assert len(rows) == 40
    assert len(set(event_ids)) == 40
    assert [row.id for row in rows] == sorted(row.id for row in rows)


def test_concurrent_first_use_serializes_schema_bootstrap(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"

    def initialize(index: int) -> str:
        store = SessionEventStore(db)
        return store.append(
            SessionEventWrite(
                session_id=f"s-first-use-{index}",
                kind=SessionEventKind.SESSION_STARTED,
            )
        ).event_id

    with ThreadPoolExecutor(max_workers=16) as pool:
        event_ids = list(pool.map(initialize, range(32)))

    assert len(set(event_ids)) == 32
    with sqlite3.connect(db) as conn:
        [row] = conn.execute(
            "SELECT version FROM storage_schema WHERE component = 'session_events'"
        ).fetchall()
    assert row[0] == SESSION_EVENT_SCHEMA_VERSION


def test_cross_process_first_use_retries_sqlite_bootstrap_lock(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    inputs = [(str(db), index) for index in range(8)]

    with ProcessPoolExecutor(max_workers=4, mp_context=get_context("spawn")) as pool:
        event_ids = list(pool.map(_initialize_store_in_process, inputs))

    assert len(set(event_ids)) == 8
    assert SessionEventStore(db).count("s-process-first-use-0") == 1


def test_projection_is_optional_versioned_and_explicitly_bounded(tmp_path: Path) -> None:
    projection = tmp_path / "events.jsonl"
    timeline = SessionTimeline(
        "s-projection",
        db_path=tmp_path / "sessions.db",
        projection_path=projection,
        policy=SessionEventPolicy(max_projection_bytes=1_024),
    )
    timeline.bind_turn("t-1")
    for index in range(30):
        timeline.record_user_message(f"{index}-" + ("x" * 200))

    rows = [
        json.loads(line)
        for line in projection.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert projection.stat().st_size <= 1_024
    assert rows[0]["kind"] == "projection.truncated"
    assert rows[-1]["schema_id"] == "geode.run-event@1"
    from core.observability.record_schema import validate_record

    for row in rows:
        validate_record(row)
    assert SessionEventStore(timeline.db_path).count("s-projection") == 30


def test_projected_session_event_validates_against_packaged_schema(tmp_path: Path) -> None:
    from core.observability.record_schema import validate_record

    timeline = SessionTimeline(
        "s-schema",
        db_path=tmp_path / "sessions.db",
        projection_path=tmp_path / "events.jsonl",
    )
    timeline.bind_turn("t-schema")
    timeline.record_user_message("hello")
    row = timeline.read_events()[0]

    validate_record(row)


def test_default_timeline_does_not_create_global_transcript(tmp_path: Path) -> None:
    timeline = SessionTimeline("s-no-global", db_path=tmp_path / "sessions.db")
    timeline.record_user_message("hello")
    assert timeline.projection_path is None
    assert list(tmp_path.glob("*.jsonl")) == []


def test_canonical_write_failure_is_visible_and_nonfatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    timeline = SessionTimeline("s-write-failure", db_path=tmp_path / "sessions.db")

    def fail(_event: SessionEventWrite) -> None:
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(timeline._store, "append", fail)
    timeline.record_user_message("the foreground operation must continue")

    assert timeline.record_failed is True
    assert timeline.record_failures == 1
    assert timeline.event_count == 0


def test_legacy_import_is_atomic_idempotent_and_source_is_unchanged(tmp_path: Path) -> None:
    legacy = tmp_path / "s-legacy.jsonl"
    original = (
        b'{"event":"session_start","ts":1,"session_id":"s-legacy","model":"old"}\n'
        b'{"event":"user_message","ts":2,"text":"hello"}\n'
        b'{"event":"tool_call","ts":3,"tool":"read","input":"{}",'
        b'"call_id":"call-1"}\n'
        b'{"partial":\n'
    )
    legacy.write_bytes(original)
    store = SessionEventStore(tmp_path / "sessions.db")

    assert store.import_legacy_jsonl(legacy) == 3
    assert store.import_legacy_jsonl(legacy) == 3
    assert legacy.read_bytes() == original
    rows = store.read("s-legacy")
    assert len(rows) == 3
    assert rows[1].kind == "message.user"
    assert rows[2].call_id == "call-1"
    assert rows[2].payload["arguments"] == {}
    assert all(row.source == "legacy_jsonl" for row in rows)


def test_legacy_import_deduplicates_stable_prefix_after_append(tmp_path: Path) -> None:
    legacy = tmp_path / "s-growing.jsonl"
    prefix = (
        b'{"event":"session_start","ts":1,"session_id":"s-growing"}\n'
        b'{"event":"user_message","ts":2,"text":"hello"}\n'
    )
    legacy.write_bytes(prefix)
    store = SessionEventStore(tmp_path / "sessions.db")

    assert store.import_legacy_jsonl(legacy) == 2
    legacy.write_bytes(prefix + b'{"event":"assistant_message","ts":3,"text":"world"}\n')

    assert store.import_legacy_jsonl(legacy) == 1
    assert store.count("s-growing") == 3


def test_legacy_import_preserves_turn_generation_and_contains_bad_timestamp(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "s-generations.jsonl"
    legacy.write_text(
        "\n".join(
            (
                '{"event":"session_start","ts":1,"session_id":"s-generations","turn_id":"t-1"}',
                '{"event":"session_end","ts":2,"session_id":"s-generations","turn_id":"t-1"}',
                '{"event":"session_start","ts":3,"session_id":"s-generations","turn_id":"t-2"}',
                '{"event":"user_message","ts":"bad","session_id":"s-generations",'
                '"turn_id":"t-2","text":"hello"}',
            )
        )
        + "\n"
    )
    store = SessionEventStore(tmp_path / "sessions.db")

    assert store.import_legacy_jsonl(legacy) == 4
    rows = store.read("s-generations")
    assert [row.session_generation for row in rows] == [1, 1, 2, 2]
    assert [row.turn_id for row in rows] == ["t-1", "t-1", "t-2", "t-2"]
    assert rows[-1].payload["_legacy"]["timestamp_invalid"] is True


def test_newer_component_schema_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    SessionEventStore(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE storage_schema SET version = ? WHERE component = 'session_events'",
            (SESSION_EVENT_SCHEMA_VERSION + 1,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="newer"):
        SessionEventStore(db)


def test_retention_prunes_only_explicitly_ended_old_sessions(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    store = SessionEventStore(db)
    old = time.time() - (200 * 86_400)
    store.append(
        SessionEventWrite(
            session_id="s-ended",
            kind=SessionEventKind.USER_MESSAGE,
            occurred_at=old,
        )
    )
    store.append(
        SessionEventWrite(
            session_id="s-ended",
            kind=SessionEventKind.SESSION_ENDED,
            occurred_at=old + 1,
        )
    )
    store.append(
        SessionEventWrite(
            session_id="s-stale-active",
            kind=SessionEventKind.USER_MESSAGE,
            occurred_at=old,
        )
    )
    store.append(
        SessionEventWrite(
            session_id="s-recent-ended",
            kind=SessionEventKind.SESSION_ENDED,
        )
    )
    store.append(
        SessionEventWrite(
            session_id="s-resumed",
            kind=SessionEventKind.SESSION_ENDED,
            occurred_at=old,
            session_generation=1,
        )
    )
    store.append(
        SessionEventWrite(
            session_id="s-resumed",
            kind=SessionEventKind.SESSION_STARTED,
            occurred_at=old + 1,
            session_generation=2,
        )
    )

    assert store.prune_terminal_sessions(retention_days=180) == 2
    assert store.count("s-ended") == 0
    assert store.count("s-stale-active") == 1
    assert store.count("s-recent-ended") == 1
    assert store.count("s-resumed") == 2


def test_session_end_preserves_error_terminal_status(tmp_path: Path) -> None:
    timeline = SessionTimeline("s-error", db_path=tmp_path / "sessions.db")
    timeline.record_session_end(status="error", rounds=3)

    [terminal] = SessionEventStore(timeline.db_path).read("s-error")
    assert terminal.kind == SessionEventKind.SESSION_ENDED
    assert terminal.status == "error"
    assert terminal.payload["rounds"] == 3


def test_turn_completion_does_not_close_active_session() -> None:
    captured: dict[str, object] = {}

    class TimelineRecorder:
        def record_assistant_message(self, _text: str) -> None:
            raise AssertionError("empty result text must not emit an assistant message")

        def record_session_end(self, **kwargs: object) -> None:
            captured.update(kwargs)

    loop = SimpleNamespace(_timeline=TimelineRecorder())
    result = SimpleNamespace(text="", rounds=4, error=True)

    record_timeline_end(loop, result)

    assert captured == {}


def test_error_transition_closes_durable_session_with_error_status() -> None:
    captured: dict[str, object] = {}

    class Checkpoint:
        def mark_error(self, _session_id: str) -> bool:
            return True

        def current_status(self, _session_id: str) -> str:
            return "error"

    class TimelineRecorder:
        def record_session_end(self, **kwargs: object) -> None:
            captured.update(kwargs)

    loop = SimpleNamespace(
        _checkpoint=Checkpoint(),
        _session_id="s-error",
        _timeline=TimelineRecorder(),
        _hook_registry=HookRegistry(),
        _public_session_ended=False,
    )

    asyncio.run(mark_session_error_async(loop))

    assert captured["status"] == "error"
