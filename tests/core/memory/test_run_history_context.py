"""Tests for SQL-backed operational history context injection."""

from __future__ import annotations

import time
from pathlib import Path

from core.hooks.catalog import EventRetentionClass
from core.memory.context import ContextAssembler
from core.observability.event_store import HookEventStore, HookEventWrite
from core.time_format import format_age as _format_age


class TestFormatAge:
    def test_now(self) -> None:
        assert _format_age(0) == "now"

    def test_negative(self) -> None:
        assert _format_age(-10) == "now"

    def test_seconds(self) -> None:
        assert _format_age(30) == "now"

    def test_minutes(self) -> None:
        assert _format_age(300) == "5m ago"

    def test_hours(self) -> None:
        assert _format_age(7200) == "2h ago"

    def test_days(self) -> None:
        assert _format_age(172800) == "2d ago"

    def test_one_minute(self) -> None:
        assert _format_age(60) == "1m ago"

    def test_one_hour(self) -> None:
        assert _format_age(3600) == "1h ago"

    def test_one_day(self) -> None:
        assert _format_age(86400) == "1d ago"


def _append_event(
    store: HookEventStore,
    *,
    occurred_at: float,
    session_key: str,
    event: str = "session_end",
    status: str = "ok",
) -> None:
    store.append(
        HookEventWrite(
            occurred_at=occurred_at,
            session_key=session_key,
            run_id="run-1",
            event=event,
            dispatch_mode="observe",
            status=status,
            retention_class=EventRetentionClass.STANDARD,
            handler_count=0,
            handler_error_count=0,
            blocked=False,
            block_reason="",
            actor_type="orchestrator",
            actor_id="runtime",
            action="session.ended",
            entity_type="session",
            entity_id="s-1",
            task_id=None,
            level="info",
        )
    )


class TestRunHistoryInjection:
    def test_no_event_store(self) -> None:
        assembler = ContextAssembler()
        ctx = assembler.assemble("sess-1", "Project Atlas")
        assert "_run_history" not in ctx

    def test_empty_event_store(self, tmp_path: Path) -> None:
        store = HookEventStore(tmp_path / "events.db")
        assembler = ContextAssembler(event_store=store)
        assert "_run_history" not in assembler.assemble("sess-1", "Project Atlas")
        store.close()

    def test_injects_session_end_entries(self, tmp_path: Path) -> None:
        store = HookEventStore(tmp_path / "events.db")
        _append_event(
            store,
            occurred_at=time.time() - 3600,
            session_key="subject:demo:analysis",
        )

        ctx = ContextAssembler(event_store=store).assemble("sess-1", "demo")
        assert "subject:demo:analysis completed (1h ago)" in ctx["_run_history"]
        store.close()

    def test_only_session_end_events_are_injected(self, tmp_path: Path) -> None:
        store = HookEventStore(tmp_path / "events.db")
        _append_event(
            store,
            occurred_at=time.time(),
            session_key="subject:test:analysis",
            event="tool_exec_end",
        )
        ctx = ContextAssembler(event_store=store).assemble("sess-1", "test")
        assert "_run_history" not in ctx
        store.close()

    def test_history_is_newest_first_and_bounded(self, tmp_path: Path) -> None:
        store = HookEventStore(tmp_path / "events.db")
        now = time.time()
        for index in range(5):
            _append_event(
                store,
                occurred_at=now - index * 3600,
                session_key=f"subject:{index}:analysis",
                status="failed" if index == 0 else "ok",
            )

        history = ContextAssembler(event_store=store).assemble("sess-1", "test")["_run_history"]
        assert history.count("|") == 2
        assert history.index("subject:0:analysis failed") < history.index(
            "subject:1:analysis completed"
        )
        assert "subject:3:analysis" not in history
        store.close()

    def test_closed_store_fails_soft(self, tmp_path: Path) -> None:
        store = HookEventStore(tmp_path / "events.db")
        assembler = ContextAssembler(event_store=store)
        store.close()
        assert "_run_history" not in assembler.assemble("sess-1", "test")
