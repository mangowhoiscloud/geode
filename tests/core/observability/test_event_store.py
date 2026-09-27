"""Tests for bounded SQLite HookEvent persistence."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import core.observability.event_store as event_store_module
import pytest
from core.hooks.catalog import EventRetentionClass
from core.memory.session_manager import SessionManager
from core.observability.event_store import (
    EventRetentionPolicy,
    HookEventStore,
    HookEventWrite,
    read_hook_event_references,
)


def _record(
    *,
    occurred_at: float | None = None,
    event: str = "session_start",
    retention: EventRetentionClass = EventRetentionClass.STANDARD,
    payload: dict | None = None,
) -> HookEventWrite:
    return HookEventWrite(
        occurred_at=time.time() if occurred_at is None else occurred_at,
        session_key="subject:test:analysis",
        run_id="run-1",
        event=event,
        dispatch_mode="observe",
        status="ok",
        retention_class=retention,
        handler_count=1,
        handler_error_count=0,
        blocked=False,
        block_reason="",
        actor_type="system",
        actor_id="test",
        action="session.started",
        entity_type="session",
        entity_id="s-1",
        task_id=None,
        level="info",
        payload=payload or {},
    )


def test_session_manager_owns_additive_hook_event_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    manager = SessionManager(db_path=db_path)
    manager.close()

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "hook_events" in tables


def test_trajectory_references_keep_mixed_persisted_hook_versions(tmp_path: Path) -> None:
    from core.observability.session_timeline import SessionTimeline
    from core.observability.trajectory import trajectory_from_session, verify_trajectory_integrity

    db_path = tmp_path / "sessions.db"
    timeline = SessionTimeline("s-1", db_path=db_path)
    timeline.record_session_start()
    timeline.record_session_end()
    store = HookEventStore(db_path)
    record = replace(_record(), session_id="s-1", turn_id="t-1")
    store.append(record)
    store.append(replace(record, step_id="step-2"))
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE hook_events SET schema_version = 3 WHERE id = 1")
        original = conn.execute("SELECT * FROM hook_events ORDER BY id").fetchall()

    trajectory = trajectory_from_session("s-1", db_path=db_path)
    refs = trajectory["runtime_event_refs"]
    assert [row["schema_id"] for row in refs] == [
        "geode.hook-event@3",
        f"geode.hook-event@{event_store_module.EVENT_SCHEMA_VERSION}",
    ]
    assert [row["record_count"] for row in refs] == [1, 1]
    assert refs == list(read_hook_event_references(db_path, ("s-1", "s-1")))
    assert verify_trajectory_integrity(trajectory)["runtime_event_ref_count"] == 2
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT * FROM hook_events ORDER BY id").fetchall() == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 4),
        ("session_id", "s-2"),
        ("step_id", "step-changed"),
        ("turn_id", "turn-changed"),
        ("tool_call_id", "tool-changed"),
        ("llm_call_id", "llm-changed"),
        ("llm_attempt_id", "attempt-changed"),
        ("payload_hash", "f" * 64),
    ],
)
def test_hook_reference_digest_binds_schema_and_correlation(
    tmp_path: Path, field: str, value: str | int
) -> None:
    db_path = tmp_path / "sessions.db"
    store = HookEventStore(db_path)
    store.append(replace(_record(), session_id="s-1", step_id="step-1"))
    store.close()
    before = read_hook_event_references(db_path, ("s-1",))[0]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        values = dict(conn.execute("SELECT * FROM hook_events").fetchone())
        values[field] = value
        conn.execute(
            "UPDATE hook_events SET schema_version = :schema_version, session_id = :session_id, "
            "step_id = :step_id, turn_id = :turn_id, tool_call_id = :tool_call_id, "
            "llm_call_id = :llm_call_id, llm_attempt_id = :llm_attempt_id, "
            "payload_hash = :payload_hash",
            values,
        )
    session_id = str(value) if field == "session_id" else "s-1"
    after = read_hook_event_references(db_path, (session_id,))[0]
    assert before["sha256"] != after["sha256"]
    assert after["reference"] == f"hook-events-sha256:{after['sha256']}"


def test_legacy_hook_reference_survives_additive_step_column(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE hook_events (id INTEGER, schema_version INTEGER, "
            "session_id TEXT, event TEXT, payload_hash TEXT, turn_id TEXT, "
            "tool_call_id TEXT, llm_call_id TEXT, llm_attempt_id TEXT)"
        )
        conn.execute(
            "INSERT INTO hook_events VALUES (1, 3, 's-1', 'session_started', ?, '', '', '', '')",
            ("a" * 64,),
        )
    before = read_hook_event_references(db_path, ("s-1",))
    assert before[0]["schema_id"] == "geode.hook-event@3"
    with sqlite3.connect(db_path) as conn:
        assert "step_id" not in {row[1] for row in conn.execute("PRAGMA table_info(hook_events)")}
        conn.execute("ALTER TABLE hook_events ADD COLUMN step_id TEXT NOT NULL DEFAULT ''")
    assert read_hook_event_references(db_path, ("s-1",)) == before


def test_hook_references_do_not_invent_missing_schema_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.db"
    assert read_hook_event_references(db_path, ("s-1",)) == ()
    assert not db_path.exists()
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
    assert read_hook_event_references(db_path, ("s-1",)) == ()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE hook_events (id INTEGER, session_id TEXT, event TEXT, "
            "payload_hash TEXT, turn_id TEXT, tool_call_id TEXT, llm_call_id TEXT, "
            "llm_attempt_id TEXT)"
        )
        conn.execute(
            "INSERT INTO hook_events VALUES (1, 's-1', 'session_started', ?, '', '', '', '')",
            ("a" * 64,),
        )
    assert read_hook_event_references(db_path, ("s-1",)) == ()


@pytest.mark.parametrize(
    "version,reason",
    [(0, "positive integer"), ("legacy", "positive integer"), (5, "step_id")],
)
def test_invalid_hook_schema_metadata_fails_reference_export(
    tmp_path: Path, version: int | str, reason: str
) -> None:
    db_path = tmp_path / "sessions.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE hook_events (id INTEGER, schema_version INTEGER, session_id TEXT, "
            "event TEXT, payload_hash TEXT, turn_id TEXT, tool_call_id TEXT, "
            "llm_call_id TEXT, llm_attempt_id TEXT)"
        )
        conn.execute(
            "INSERT INTO hook_events VALUES (1, ?, 's-1', 'session_started', ?, '', '', '', '')",
            (version, "a" * 64),
        )
    with pytest.raises(ValueError, match=reason):
        read_hook_event_references(db_path, ("s-1",))


def test_append_redacts_raw_fields_secrets_and_large_payloads(tmp_path: Path) -> None:
    policy = EventRetentionPolicy(max_payload_bytes=100, max_string_chars=80)
    store = HookEventStore(tmp_path / "events.db", retention=policy)
    store.append(
        _record(
            payload={
                "tool_input": {"query": "private"},
                "message": "private message",
                "safe": "sk-ant-" + "a" * 32,
                "padding": "x" * 2_000,
            }
        )
    )

    row = store.read(limit=1)[0]
    assert "tool_input" not in row.payload
    assert "message" not in row.payload
    assert "private" not in str(row.payload)
    assert "sk-ant-" not in str(row.payload)
    assert row.payload.get("_truncated") is True
    assert len(row.payload_hash) == 64
    store.close()


def test_prune_applies_retention_buckets_and_global_cap(tmp_path: Path) -> None:
    now = 2_000_000.0
    policy = EventRetentionPolicy(
        high_volume_days=1,
        standard_days=10,
        audit_days=100,
        max_rows=2,
        prune_every=0,
    )
    store = HookEventStore(tmp_path / "events.db", retention=policy)
    store.append(
        _record(
            occurred_at=now - 2 * 86_400,
            event="llm_call_end",
            retention=EventRetentionClass.HIGH_VOLUME,
        )
    )
    for index in range(3):
        store.append(_record(occurred_at=now + index, event=f"event-{index}"))

    removed = store.prune(now=now + 3)
    assert removed == 2
    assert [row.event for row in store.read(limit=10)] == ["event-2", "event-1"]
    store.close()


def test_store_serializes_concurrent_writers(tmp_path: Path) -> None:
    store = HookEventStore(
        tmp_path / "events.db",
        retention=EventRetentionPolicy(prune_every=0),
    )

    def _write(worker: int) -> None:
        for index in range(25):
            store.append(_record(event=f"worker-{worker}-{index}"))

    threads = [threading.Thread(target=_write, args=(worker,)) for worker in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert store.count() == 100
    store.close()


def test_read_combines_indexable_filters(tmp_path: Path) -> None:
    store = HookEventStore(tmp_path / "events.db")
    store.append(
        replace(
            _record(occurred_at=100.0, event="session_end"),
            session_key="subject:a",
            run_id="run-a",
            status="failed",
        )
    )
    store.append(
        replace(
            _record(occurred_at=200.0, event="session_end"),
            session_key="subject:a",
            run_id="run-a",
            step_id="turn-1:step-1",
            status="ok",
        )
    )
    store.append(
        replace(
            _record(occurred_at=300.0, event="tool_exec_end"),
            session_key="subject:b",
            run_id="run-b",
            status="ok",
        )
    )

    rows = store.read(
        session_key="subject:a",
        run_id="run-a",
        step_id="turn-1:step-1",
        event_filter="session_end",
        status_filter="ok",
        occurred_after=150.0,
        occurred_before=250.0,
    )

    assert [row.occurred_at for row in rows] == [200.0]
    store.close()


def test_close_is_idempotent_and_rejects_new_operations(tmp_path: Path) -> None:
    store = HookEventStore(tmp_path / "events.db")
    store.close()
    store.close()
    assert store.closed is True
    with pytest.raises(RuntimeError, match="closed"):
        store.append(_record())


def test_each_operation_closes_its_sqlite_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_connect = sqlite3.connect
    opened = 0
    closed = 0

    class _TrackedConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        @property
        def row_factory(self):
            return self._conn.row_factory

        @row_factory.setter
        def row_factory(self, value) -> None:
            self._conn.row_factory = value

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

        def close(self) -> None:
            nonlocal closed
            closed += 1
            self._conn.close()

    def _connect(*args, **kwargs):
        nonlocal opened
        opened += 1
        return _TrackedConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(event_store_module.sqlite3, "connect", _connect)
    store = HookEventStore(tmp_path / "events.db")
    assert opened == closed

    store.append(_record())
    store.read()
    store.count()
    store.prune()
    store.clear()

    assert opened == closed
    store.close()
