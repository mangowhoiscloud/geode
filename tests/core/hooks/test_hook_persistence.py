"""Integration contract between HookSystem, SQLite, and run transcripts."""

from __future__ import annotations

import json
from pathlib import Path

from core.hooks import HookEvent, HookSystem
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from core.self_improving.loop.observe.run_transcript import RunTranscript, run_transcript_scope


def _wired_hooks(tmp_path: Path) -> tuple[HookSystem, HookEventStore]:
    store = HookEventStore(tmp_path / "events.db")
    hooks = HookSystem()
    hooks.register_sink(
        HookPersistenceSink(
            store,
            session_key="subject:test:analysis",
            run_id="run-1",
        ),
        name="hook_persistence",
    )
    return hooks, store


def _transcript(tmp_path: Path) -> RunTranscript:
    return RunTranscript(
        session_id="run-1",
        gen_tag="gen1",
        component="test",
        path=tmp_path / "transcript.jsonl",
    )


def _read_transcript(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_one_dispatch_writes_one_sql_and_one_transcript_row(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    hooks.register(HookEvent.USER_INPUT_RECEIVED, lambda _e, _d: None, name="one")
    hooks.register(HookEvent.USER_INPUT_RECEIVED, lambda _e, _d: None, name="two")

    with run_transcript_scope(_transcript(tmp_path)):
        results = hooks.trigger_interceptor(
            HookEvent.USER_INPUT_RECEIVED,
            {"session_id": "s-1", "user_input": "private input"},
        )

    assert results.blocked is False
    rows = store.read()
    assert len(rows) == 1
    assert rows[0].handler_count == 2
    assert rows[0].payload["input_len"] == len("private input")
    assert "private input" not in str(rows[0].payload)
    assert len(_read_transcript(tmp_path / "transcript.jsonl")) == 1
    hooks.close()


def test_compatibility_event_reaches_handlers_without_durable_duplicate(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    seen: list[str] = []
    hooks.register(
        HookEvent.TOOL_RESULT_TRANSFORM,
        lambda event, _data: seen.append(event.value),
        name="compat_handler",
    )

    with run_transcript_scope(_transcript(tmp_path)):
        hooks.trigger_with_result(
            HookEvent.TOOL_RESULT_TRANSFORM,
            {"tool_name": "read_file", "result": {"content": "private"}},
        )

    assert seen == [HookEvent.TOOL_RESULT_TRANSFORM.value]
    assert store.count() == 0
    assert not (tmp_path / "transcript.jsonl").exists()
    hooks.close()


def test_blocked_dispatch_persists_classification_not_raw_reason(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)

    def _block(_event: HookEvent, _data: dict) -> dict:
        return {"block": True, "reason": "secret policy detail"}

    hooks.register(HookEvent.USER_INPUT_RECEIVED, _block, name="policy_gate")
    result = hooks.trigger_interceptor(
        HookEvent.USER_INPUT_RECEIVED,
        {"session_id": "s-1", "user_input": "private input"},
    )

    assert result.reason == "secret policy detail"
    row = store.read()[0]
    assert row.status == "blocked"
    assert row.block_reason == "blocked_by:policy_gate"
    assert "secret policy detail" not in str(row.payload)
    hooks.close()


def test_handler_failure_is_counted_without_dropping_dispatch(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)

    def _broken(_event: HookEvent, _data: dict) -> None:
        raise RuntimeError("sensitive failure detail")

    hooks.register(HookEvent.SESSION_STARTED, _broken, name="broken")
    result = hooks.trigger(HookEvent.SESSION_STARTED, {"session_id": "s-1"})

    assert result[0].success is False
    row = store.read()[0]
    assert row.status == "handler_error"
    assert row.handler_error_count == 1
    assert row.payload["_failed_handlers"] == ["broken"]
    assert "sensitive failure detail" not in str(row.payload)
    hooks.close()


def test_result_feedback_uses_opaque_subject_identifier(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    subject = "private pasted result body"

    hooks.trigger(
        HookEvent.RESULT_FEEDBACK,
        {
            "subject": subject,
            "verdict": "rejected",
            "reason": "contains private details",
            "comment": "also private",
        },
    )

    row = store.read()[0]
    assert row.entity_id.startswith("result:")
    assert subject not in row.entity_id
    assert subject not in str(row.payload)
    assert "private details" not in str(row.payload)
    assert row.payload["verdict"] == "rejected"
    hooks.close()


def test_hook_system_close_closes_owned_sink(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    hooks.close()
    hooks.close()
    assert hooks.closed is True
    assert store.closed is True
