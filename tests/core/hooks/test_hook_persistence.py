"""Integration contract between HookSystem, SQLite, and run projections."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from core.hooks import (
    HookCorrelation,
    HookEvent,
    HookName,
    HookRegistry,
    HookSystem,
)
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from evals.run_timeline import (
    RunTimeline,
    current_run_timeline,
    run_timeline_scope,
)


def _wired_hooks(tmp_path: Path) -> tuple[HookSystem, HookEventStore]:
    store = HookEventStore(tmp_path / "events.db")
    hooks = HookSystem()
    hooks.register_sink(
        HookPersistenceSink(
            store,
            session_key="subject:test:analysis",
            run_id="run-1",
            activity_sink_provider=current_run_timeline,
        ),
        name="hook_persistence",
    )
    return hooks, store


def _timeline(tmp_path: Path) -> RunTimeline:
    return RunTimeline(
        session_id="run-1",
        gen_tag="gen1",
        component="test",
        path=tmp_path / "events.jsonl",
    )


def _read_timeline(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_one_dispatch_writes_one_sql_and_one_timeline_row(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    hooks.register(HookEvent.USER_INPUT_RECEIVED, lambda _e, _d: None, name="one")
    hooks.register(HookEvent.USER_INPUT_RECEIVED, lambda _e, _d: None, name="two")

    with run_timeline_scope(_timeline(tmp_path)):
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
    assert len(_read_timeline(tmp_path / "events.jsonl")) == 1
    hooks.close()


def test_compatibility_event_reaches_handlers_without_durable_duplicate(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)
    seen: list[str] = []
    hooks.register(
        HookEvent.TOOL_RESULT_TRANSFORM,
        lambda event, _data: seen.append(event.value),
        name="compat_handler",
    )

    with run_timeline_scope(_timeline(tmp_path)):
        hooks.trigger_with_result(
            HookEvent.TOOL_RESULT_TRANSFORM,
            {"tool_name": "read_file", "result": {"content": "private"}},
        )

    assert seen == [HookEvent.TOOL_RESULT_TRANSFORM.value]
    assert store.count() == 0
    assert not (tmp_path / "events.jsonl").exists()
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


def test_public_extension_audit_uses_sqlite_and_active_timeline_only(
    tmp_path: Path,
) -> None:
    hooks, store = _wired_hooks(tmp_path)
    public_hooks = HookRegistry(events=hooks)
    public_hooks.register(HookName.SESSION_END, lambda _invocation: None, name="audit-probe")

    asyncio.run(
        public_hooks.invoke(
            HookName.SESSION_END,
            payload={"reason": "completed", "status": "completed"},
            correlation=HookCorrelation(
                session_id="s-1",
                turn_id="t-1",
                step_id="t-1:step-1",
                run_id="run-1",
            ),
        )
    )

    row = store.read()[0]
    assert row.event == HookEvent.EXTENSION_INVOKED.value
    assert row.action == "extension.invoked"
    assert row.payload == {
        "surface": "hook",
        "name": HookName.SESSION_END.value,
        "extension": "audit-probe",
        "status": "ok",
        "duration_ms": row.payload["duration_ms"],
        "session_id": "s-1",
        "turn_id": "t-1",
        "step_id": "t-1:step-1",
        "session_generation": 0,
        "verify_attempt": 0,
        "activity_schema_version": 9,
        "_dispatch_duration_ms": row.payload["_dispatch_duration_ms"],
    }
    assert not (tmp_path / "events.jsonl").exists()

    with run_timeline_scope(_timeline(tmp_path)):
        asyncio.run(
            public_hooks.invoke(
                HookName.SESSION_END,
                payload={"reason": "completed", "status": "completed"},
                correlation=HookCorrelation(
                    session_id="s-1",
                    turn_id="t-2",
                    step_id="t-2:step-1",
                    run_id="run-1",
                ),
            )
        )

    timeline_rows = _read_timeline(tmp_path / "events.jsonl")
    assert len(timeline_rows) == 1
    assert timeline_rows[0]["event"] == HookEvent.EXTENSION_INVOKED.value
    assert timeline_rows[0]["payload"]["turn_id"] == "t-2"
    assert timeline_rows[0]["payload"]["step_id"] == "t-2:step-1"
    hooks.close()


def test_tool_correlation_survives_sqlite_and_timeline_projection(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)

    with run_timeline_scope(_timeline(tmp_path)):
        hooks.trigger(
            HookEvent.TOOL_EXEC_ENDED,
            {
                "session_id": "s-tool",
                "turn_id": "t-tool",
                "step_id": "t-tool:step-2",
                "session_generation": 3,
                "verify_attempt": 1,
                "tool_call_id": "call-tool",
                "tool_name": "check",
                "duration_ms": 1.0,
                "has_error": False,
            },
        )

    row = store.read(step_id="t-tool:step-2")[0]
    assert row.session_id == "s-tool"
    assert row.turn_id == "t-tool"
    assert row.step_id == "t-tool:step-2"
    assert row.tool_call_id == "call-tool"
    assert row.payload["step_id"] == "t-tool:step-2"
    assert row.payload["session_generation"] == 3
    assert row.payload["verify_attempt"] == 1
    timeline_row = _read_timeline(tmp_path / "events.jsonl")[0]
    assert timeline_row["payload"]["session_id"] == "s-tool"
    assert timeline_row["payload"]["turn_id"] == "t-tool"
    assert timeline_row["payload"]["step_id"] == "t-tool:step-2"
    assert timeline_row["payload"]["session_generation"] == 3
    assert timeline_row["payload"]["verify_attempt"] == 1
    hooks.close()


def test_llm_route_charge_and_usage_survive_durable_projection(tmp_path: Path) -> None:
    hooks, store = _wired_hooks(tmp_path)

    with run_timeline_scope(_timeline(tmp_path)):
        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                "session_id": "s-llm",
                "turn_id": "t-llm",
                "llm_call_id": "call-llm",
                "llm_attempt_id": "call-llm:attempt-1",
                "model": "openrouter/deepseek/deepseek-v4-flash-0731",
                "provider": "openrouter",
                "adapter": "openrouter-payg",
                "latency_ms": 123.5,
                "error": None,
                "usage": {
                    "input_tokens": 101,
                    "output_tokens": 23,
                    "cached_input_tokens": 7,
                    "reasoning_tokens": 11,
                    "cache_write_tokens": 3,
                },
                "cost_usd": 0.00012,
                "response_id": "generation-1",
                "response_model": "deepseek/deepseek-v4-flash-0731",
                "response_provider": "OpenInference",
                "routing_strategy": "direct",
                "routing_attempt": 1,
            },
        )

    row = store.read()[0]
    assert row.status == "ok"
    assert row.entity_id == "call-llm"
    assert row.payload["duration_ms"] == 123.5
    assert row.payload["model"] == "openrouter/deepseek/deepseek-v4-flash-0731"
    assert row.payload["provider"] == "openrouter"
    assert row.payload["adapter"] == "openrouter-payg"
    assert row.payload["usage"] == {
        "input_tokens": 101,
        "output_tokens": 23,
        "cached_input_tokens": 7,
        "reasoning_tokens": 11,
        "cache_write_tokens": 3,
    }
    assert row.payload["cost_usd"] == 0.00012
    assert row.payload["response_id"] == "generation-1"
    assert row.payload["response_model"] == "deepseek/deepseek-v4-flash-0731"
    assert row.payload["response_provider"] == "OpenInference"
    assert row.payload["routing_strategy"] == "direct"
    assert row.payload["routing_attempt"] == 1
    assert row.payload["activity_schema_version"] == 9
    timeline_payload = _read_timeline(tmp_path / "events.jsonl")[0]["payload"]
    assert timeline_payload["response_provider"] == "OpenInference"
    assert timeline_payload["cost_usd"] == 0.00012
    assert timeline_payload["activity_schema_version"] == 9
    hooks.close()


@pytest.mark.parametrize("receipt_state", ["missing", "zero", "malformed"])
def test_optional_image_receipt_preserves_usage_without_fabricating_zero(
    tmp_path: Path, receipt_state: str
) -> None:
    hooks, store = _wired_hooks(tmp_path)
    receipt = {
        "scope": "responses-input-images",
        "image_count": 0,
        "encoded_image_bytes": 0,
        "complete": True,
        "rows_omitted": 0,
        "refs": [],
    }
    data = {
        "session_id": "synthetic-session",
        "llm_call_id": "synthetic-call",
        "llm_attempt_id": "synthetic-call:attempt-1",
        "latency_ms": 1,
        "error": None,
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    if receipt_state != "missing":
        data["request_image_receipt"] = receipt
    if receipt_state == "malformed":
        receipt["input"] = "SYNTHETIC_PRIVATE_DATA"
    with run_timeline_scope(_timeline(tmp_path)):
        hooks.trigger(HookEvent.LLM_CALL_ENDED, data)
    row = store.read()[0]
    expected = receipt if receipt_state == "zero" else None
    assert row.payload["request_image_receipt"] == expected
    assert row.payload["usage"]["input_tokens"] == 2
    assert row.payload["usage"]["output_tokens"] == 1
    assert "SYNTHETIC_PRIVATE_DATA" not in json.dumps(row.payload)
    mirror = _read_timeline(tmp_path / "events.jsonl")[0]["payload"]
    assert mirror["request_image_receipt"] == expected
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
            "session_id": "session-1",
            "turn_id": "turn-1",
            "tool_call_id": "tool-call-1",
        },
    )

    row = store.read()[0]
    assert row.session_id == "session-1"
    assert row.turn_id == "turn-1"
    assert row.tool_call_id == "tool-call-1"
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


@pytest.mark.parametrize("event", [HookEvent.LLM_CALL_STARTED, HookEvent.LLM_CALL_ENDED])
@pytest.mark.parametrize(
    "method", ["trigger_async", "trigger_with_result_async", "trigger_interceptor_async"]
)
def test_cancelled_observer_persists_failed_dispatch_before_propagation(
    tmp_path: Path, event: HookEvent, method: str
) -> None:
    async def scenario() -> None:
        hooks, store = _wired_hooks(tmp_path)
        entered = asyncio.Event()
        seen: list[object] = []
        tail: list[str] = []

        async def waiting(_event, _data):
            entered.set()
            await asyncio.Event().wait()

        hooks.register(event, waiting, name="waiting", priority=1)
        hooks.register(event, lambda _event, _data: tail.append("not-run"), name="tail", priority=2)
        hooks.register_sink(seen.append, name="capture")
        payload = {
            "session_id": "s-cancel",
            "llm_call_id": "call-cancel",
            "llm_attempt_id": "call-cancel:attempt-1",
            "latency_ms": 1.0,
            "usage": {"input_tokens": 7, "output_tokens": 1},
        }
        try:
            task = asyncio.create_task(getattr(hooks, method)(event, payload))
            await entered.wait()
            task.cancel("private cancellation reason")
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
            assert tail == []
            rows = store.read()
            assert len(rows) == 1 and len(seen) == 1
            row = rows[0]
            assert row.event == event.value
            assert row.status == "handler_error"
            assert row.handler_count == row.handler_error_count == 1
            assert row.payload["_failed_handlers"] == ["waiting"]
            assert row.llm_attempt_id == payload["llm_attempt_id"]
            assert "private cancellation reason" not in str(row.payload)
            # A failed observer is not a provider/model cancellation result.
            assert row.payload.get("error_type") is None
            if event is HookEvent.LLM_CALL_ENDED:
                assert row.payload["usage"]["input_tokens"] == 7
            assert hooks.has_sink_failures is False
        finally:
            hooks.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("persistence_first", [False, True])
def test_sink_interruption_does_not_replace_original_observer_cancellation(
    tmp_path: Path, persistence_first: bool
) -> None:
    original = asyncio.CancelledError("private original cancellation")
    secondary = asyncio.CancelledError("private sink cancellation")
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "sink-order.db")

    async def cancelled(_event, _data):
        raise original

    def failing_sink(_dispatch):
        raise secondary

    hooks.register(HookEvent.LLM_CALL_STARTED, cancelled, name="cancelled")
    sink = HookPersistenceSink(store, session_key="synthetic", run_id="run-sinks")
    if persistence_first:
        hooks.register_sink(sink, name="persistence")
    hooks.register_sink(failing_sink, name="failing")
    if not persistence_first:
        hooks.register_sink(sink, name="persistence")
    try:
        with pytest.raises(asyncio.CancelledError) as raised:
            asyncio.run(hooks.trigger_async(HookEvent.LLM_CALL_STARTED, {"llm_call_id": "c"}))
        assert raised.value is original
        assert len(store.read()) == 1
        assert hooks.has_sink_failures is True
    finally:
        hooks.close()
    assert hooks.has_sink_failures is True
