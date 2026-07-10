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
