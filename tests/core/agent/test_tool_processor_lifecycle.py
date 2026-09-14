"""Canonical start/end coverage for every ToolCallProcessor path."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.agent.error_recovery import ErrorRecoveryStrategy, RecoveryResult, RecoveryStrategy
from core.agent.tool_executor import ToolExecutor
from core.agent.tool_executor.processor import ToolCallProcessor
from core.hooks import (
    HookAction,
    HookDecision,
    HookEvent,
    HookName,
    HookRegistry,
    HookSystem,
    MiddlewareRegistry,
)
from core.hooks.middleware import NextCallAlreadyUsedError
from core.observability.activity import LifecycleCompletedDetails, ToolExecEndedRow
from core.observability.activity_registry import map_hook_to_activity
from core.observability.event_store import HookEventStore
from core.observability.hook_persistence import HookPersistenceSink
from core.tools.base import ToolContext


def _processor(
    *,
    executor_result: dict | None = None,
    executor_error: Exception | None = None,
    recovery: RecoveryResult | None = None,
) -> tuple[ToolCallProcessor, HookSystem, MagicMock]:
    executor = MagicMock(spec=ToolExecutor)
    if executor_error is not None:
        executor.aexecute = AsyncMock(side_effect=executor_error)
    else:
        executor.aexecute = AsyncMock(return_value=executor_result or {"ok": True})
    error_recovery = MagicMock()
    error_recovery.arecover = AsyncMock(
        return_value=recovery
        or RecoveryResult(
            recovered=False,
            final_result={"error": "not recovered"},
        )
    )
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    hooks = HookSystem()
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=error_recovery,
        hooks=hooks,
    )
    return processor, hooks, executor


def _block(
    *,
    name: str = "read_file",
    tool_input: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        name=name,
        input=tool_input or {"path": "notes.md"},
        id="tool-1",
    )


def _capture_events(hooks: HookSystem) -> list[HookEvent]:
    events: list[HookEvent] = []
    hooks.register_sink(lambda dispatch: events.append(dispatch.event), name="capture")
    return events


@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "error",
        "raised",
        "cancelled",
        "pre_cancelled",
        "blocked",
        "short",
        "timeout",
        "uncertain",
        "deferred",
    ],
)
def test_executor_terminal_pair_survives_real_persistence(tmp_path: Path, outcome: str) -> None:
    async def scenario() -> None:
        hooks = HookSystem()
        store = HookEventStore(tmp_path / "tool-events.db")
        hooks.register_sink(
            HookPersistenceSink(store, session_key="synthetic", run_id="run-tool"),
            name="persistence",
        )
        entered = asyncio.Event()
        original_error = NextCallAlreadyUsedError("private original exception")
        registry = HookRegistry(events=hooks)
        middleware = MiddlewareRegistry(events=hooks)
        if outcome == "blocked":
            registry.register(
                HookName.PRE_TOOL_USE,
                lambda _invocation: HookDecision(action=HookAction.BLOCK, reason="policy"),
                name="block",
            )

        class ExecutionMiddleware:
            async def tool_execution(self, request, next_call):
                if outcome == "short":
                    return {"short": True}
                result = await next_call(request)
                # Ordinary post-dispatch errors preserve the downstream result;
                # this contract error deliberately propagates without replay.
                if outcome == "raised":
                    raise original_error
                return result

        middleware.register_tool_execution(ExecutionMiddleware(), name="synthetic")

        async def handler(**_kwargs):
            entered.set()
            if outcome == "cancelled":
                await asyncio.Event().wait()
            if outcome == "error":
                return {"error": "private error result", "error_type": "synthetic_failure"}
            if outcome == "timeout":
                return {"error": "private timeout result", "timeout": True}
            if outcome == "uncertain":
                return {"error": "private uncertain result", "outcome_uncertain": True}
            if outcome == "deferred":
                return {"external_execution": "deferred"}
            return {"content": "private successful result"}

        executor = ToolExecutor(
            action_handlers={"read_file": handler},
            hooks=hooks,
            hook_registry=registry,
            middleware_registry=middleware,
        )
        cancellation = asyncio.Event()
        if outcome == "pre_cancelled":
            cancellation.set()
        context = ToolContext(
            session_id="session-tool",
            turn_id="turn-tool",
            step_id="step-tool",
            tool_call_id="call-tool",
            cancellation=cancellation,
        )
        try:
            task = asyncio.create_task(
                executor.aexecute("read_file", {"path": "private input path"}, context=context)
            )
            if outcome == "cancelled":
                await entered.wait()
                task.cancel("private cancellation reason")
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled()
            elif outcome == "raised":
                with pytest.raises(RuntimeError) as caught:
                    await task
                assert caught.value is original_error
            else:
                await task

            rows = list(reversed(store.read()))
            tool_rows = [row for row in rows if row.action.startswith("tool.exec.")]
            if outcome in {"blocked", "pre_cancelled", "short"}:
                assert not entered.is_set()
                assert tool_rows == []
                return

            assert [row.action for row in tool_rows] == ["tool.exec.started", "tool.exec.ended"]
            assert all(row.session_id == "session-tool" for row in tool_rows)
            assert all(row.turn_id == "turn-tool" for row in tool_rows)
            assert all(row.step_id == "step-tool" for row in tool_rows)
            assert all(row.tool_call_id == "call-tool" for row in tool_rows)
            ended = tool_rows[-1]
            assert ended.status == ("ok" if outcome in {"success", "deferred"} else "failed")
            assert ended.payload["success"] is (outcome in {"success", "deferred"})
            assert ended.payload["tool_name"] == "read_file"
            assert ended.payload["executed"] is (
                None
                if outcome in {"raised", "cancelled", "timeout", "uncertain", "deferred"}
                else True
            )
            assert (
                ended.payload["terminal_status"]
                == {
                    "success": "completed",
                    "error": "failed",
                    "raised": "failed",
                    "cancelled": "cancelled",
                    "timeout": "failed",
                    "uncertain": "failed",
                    "deferred": "completed",
                }[outcome]
            )
            assert (
                ended.payload["error_type"]
                == {
                    "success": None,
                    "error": "synthetic_failure",
                    "raised": "NextCallAlreadyUsedError",
                    "cancelled": "CancelledError",
                    "timeout": None,
                    "uncertain": None,
                    "deferred": None,
                }[outcome]
            )
            assert ended.payload["duration_ms"] >= 0
            assert "private" not in str([row.payload for row in rows])
        finally:
            hooks.close()
            store.close()

    asyncio.run(scenario())


def test_gated_tool_terminal_precedes_approval_observer_cancellation(tmp_path: Path) -> None:
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "approval-events.db")
    hooks.register_sink(
        HookPersistenceSink(store, session_key="synthetic", run_id="run-tool"),
        name="persistence",
    )
    cancellation = asyncio.CancelledError("private approval observer cancellation")
    handler = AsyncMock(return_value={"saved": True})

    def cancel_executed_approval(_event, payload):
        if payload["state"] == "executed":
            raise cancellation

    hooks.register(HookEvent.APPROVAL_TRANSITION, cancel_executed_approval, name="cancel-approval")
    executor = ToolExecutor(
        action_handlers={"memory_save": handler},
        approval_callback=lambda *_args: "y",
        hooks=hooks,
    )
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            asyncio.run(
                executor.aexecute(
                    "memory_save",
                    {"key": "synthetic", "content": "private input"},
                    context=ToolContext(session_id="s-tool", tool_call_id="c-tool"),
                )
            )
        assert caught.value is cancellation
        handler.assert_awaited_once()
        rows = [
            row
            for row in reversed(store.read(tool_call_id="c-tool"))
            if row.action.startswith("tool.exec.")
        ]
        assert [row.action for row in rows] == ["tool.exec.started", "tool.exec.ended"]
        assert rows[-1].status == "ok"
        assert rows[-1].payload["success"] is True
        assert rows[-1].payload["executed"] is True
        assert rows[-1].payload["terminal_status"] == "completed"
        assert rows[-1].payload["error_type"] is None
        assert "private" not in str([row.payload for row in rows])
    finally:
        hooks.close()
        store.close()


@pytest.mark.parametrize("observer_event", [HookEvent.TOOL_EXEC_ENDED, HookEvent.TOOL_EXEC_FAILED])
def test_failure_observer_cancellation_preserves_original_exception(
    tmp_path: Path,
    observer_event: HookEvent,
) -> None:
    original_error = NextCallAlreadyUsedError("original failure")
    hooks = HookSystem()
    store = HookEventStore(tmp_path / "observer-events.db")
    hooks.register_sink(
        HookPersistenceSink(store, session_key="synthetic", run_id="run-tool"),
        name="persistence",
    )
    middleware = MiddlewareRegistry(events=hooks)

    class RaiseAfterDispatch:
        async def tool_execution(self, request, next_call):
            await next_call(request)
            raise original_error

    async def cancel_observer(_event, _payload):
        raise asyncio.CancelledError("observer cancelled")

    middleware.register_tool_execution(RaiseAfterDispatch(), name="raise-after-dispatch")
    hooks.register(observer_event, cancel_observer, name="cancel-observer")
    executor = ToolExecutor(
        action_handlers={"read_file": lambda **_kwargs: {"ok": True}},
        hooks=hooks,
        middleware_registry=middleware,
    )
    try:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(
                executor.aexecute(
                    "read_file", {}, context=ToolContext(session_id="s-tool", tool_call_id="c-tool")
                )
            )
        assert caught.value is original_error
        rows = [
            row
            for row in reversed(store.read(tool_call_id="c-tool"))
            if row.action.startswith("tool.exec.")
        ]
        assert [row.action for row in rows] == ["tool.exec.started", "tool.exec.ended"]
        assert rows[-1].payload["success"] is False
        assert rows[-1].payload["error_type"] == "NextCallAlreadyUsedError"
        assert rows[-1].status == "failed"
        assert "observer cancelled" not in str(rows[-1].payload)
    finally:
        hooks.close()
        store.close()


@pytest.mark.parametrize("terminal_status", [None, {}, []])
def test_tool_terminal_legacy_mapper_keeps_missing_distinct_and_drops_private_fields(
    terminal_status: object,
) -> None:
    row = map_hook_to_activity(
        HookEvent.TOOL_EXEC_ENDED,
        {
            "tool_call_id": "legacy-call",
            "has_error": True,
            "terminal_status": terminal_status,
            "error_type": "private error text with spaces",
            "tool_input": {"secret": "private input"},
            "result": {"error": "private result"},
        },
        run_id="legacy-run",
    )
    assert isinstance(row, ToolExecEndedRow)
    assert row.details.success is False
    assert row.details.executed is None
    assert row.details.terminal_status is None
    assert row.details.error_type is None
    assert "private" not in row.model_dump_json()
    restored = ToolExecEndedRow.model_validate(
        {**row.model_dump(), "schema_version": 5, "details": {"duration_ms": 1.0, "success": True}}
    )
    assert restored.schema_version == 5
    assert restored.details.executed is None
    assert restored.details.terminal_status is None
    constructed = ToolExecEndedRow.model_validate(
        {**row.model_dump(), "details": LifecycleCompletedDetails(duration_ms=1.0)}
    )
    assert constructed.details.success is True
    assert constructed.details.executed is None


def test_public_block_never_emits_execution_started() -> None:
    hooks = HookSystem()
    registry = HookRegistry(events=hooks)
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(
            action=HookAction.BLOCK,
            reason="policy",
        ),
        name="policy",
    )
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"read_file": handler},
        hooks=hooks,
        hook_registry=registry,
    )
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=MagicMock(),
        error_recovery=MagicMock(),
        hooks=hooks,
    )
    events = _capture_events(hooks)

    asyncio.run(processor._execute_single(_block()))

    assert HookEvent.TOOL_EXEC_STARTED not in events
    assert HookEvent.TOOL_EXEC_ENDED not in events
    assert HookEvent.TOOL_EXEC_FAILED not in events
    handler.assert_not_called()


def test_adaptive_recovery_is_inside_tool_lifecycle_pair() -> None:
    recovered = RecoveryResult(
        recovered=True,
        final_result={"ok": True},
        strategy_used=RecoveryStrategy.RETRY,
    )
    processor, hooks, executor = _processor(recovery=recovered)
    processor._consecutive_failures["read_file"] = processor.MAX_CONSECUTIVE_FAILURES
    events = _capture_events(hooks)

    asyncio.run(processor._execute_single(_block()))

    assert events == [
        HookEvent.TOOL_RECOVERY_ATTEMPTED,
        HookEvent.TOOL_RECOVERY_SUCCEEDED,
    ]
    executor.aexecute.assert_not_awaited()


def test_executor_exception_becomes_failed_terminal_result() -> None:
    processor, hooks, _executor = _processor(executor_error=RuntimeError("boom"))
    events = _capture_events(hooks)

    result = asyncio.run(processor._execute_single(_block()))

    assert events == []
    assert "boom" in result["content"]


def test_session_tool_start_is_durable_before_handler_execution() -> None:
    order: list[str] = []

    class Timeline:
        def record_tool_call(
            self,
            _name: str,
            _arguments: dict,
            *,
            call_id: str,
        ) -> None:
            assert call_id == "tool-1"
            order.append("tool.called")

        def record_tool_result(
            self,
            _name: str,
            _status: str,
            _summary: str,
            *,
            call_id: str,
            result: object,
        ) -> None:
            assert call_id == "tool-1"
            assert result == {"ok": True}
            order.append("tool.completed")

    async def handler(**_kwargs: object) -> dict[str, bool]:
        assert order == ["tool.called"]
        order.append("handler")
        return {"ok": True}

    executor = ToolExecutor(action_handlers={"read_file": handler})
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=MagicMock(),
        timeline=Timeline(),
    )

    asyncio.run(processor._execute_single(_block()))

    assert order == ["tool.called", "handler", "tool.completed"]


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("recording_fails", [False, True])
def test_cancelled_tool_closes_only_a_started_call(
    recovery: bool, started: bool, recording_fails: bool
) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        timeline = MagicMock()
        if recording_fails:
            timeline.record_tool_result.side_effect = OSError("private persistence failure")
        executor = MagicMock(spec=ToolExecutor)
        executor._contains_restricted_data.return_value = False

        async def execute(name, arguments, *, context, on_execution_started):
            if started:
                on_execution_started(name, arguments)
            entered.set()
            await asyncio.Event().wait()

        executor.aexecute = execute
        processor = ToolCallProcessor(
            executor=executor,
            op_logger=MagicMock(),
            error_recovery=ErrorRecoveryStrategy(executor, retry_base_delay=0),
            timeline=timeline,
        )
        if recovery:
            processor._consecutive_failures["read_file"] = processor.MAX_CONSECUTIVE_FAILURES
        task = asyncio.create_task(processor._safe_execute_single(_block()))
        await entered.wait()
        task.cancel("private cancellation reason")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert timeline.record_tool_call.call_count == int(started)
        assert timeline.record_tool_result.call_count == int(started)
        if started:
            event = timeline.record_tool_result.call_args
            assert event.args[1] == "error"
            assert event.kwargs["call_id"] == ("tool-1:recovery:1" if recovery else "tool-1")
            assert event.kwargs["result"]["error_type"] == "CancelledError"
            assert "private cancellation reason" not in str(event)

    asyncio.run(scenario())


def test_parallel_cancellation_waits_for_sibling_cleanup() -> None:
    async def scenario() -> None:
        processor, _hooks, _executor = _processor()
        entered = asyncio.Event()
        cleaned: list[str] = []

        async def execute(block, **_kwargs):
            if block.id == "cancelled":
                await entered.wait()
                raise asyncio.CancelledError
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.append(block.id)

        processor._safe_execute_single = execute
        blocks = [_block(), _block()]
        blocks[0].id, blocks[1].id = "cancelled", "sibling"
        with pytest.raises(asyncio.CancelledError):
            await processor._execute_parallel(blocks)
        assert cleaned == ["sibling"]

    asyncio.run(scenario())


def test_cancelled_private_tool_keeps_arguments_out_of_completion() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        timeline = MagicMock()
        processor, _hooks, executor = _processor()
        processor._timeline = timeline
        executor._contains_restricted_data.return_value = False

        async def execute(name, arguments, *, context, on_execution_started):
            context.contains_personal_data = True
            on_execution_started(name, {"omitted": True})
            entered.set()
            await asyncio.Event().wait()

        executor.aexecute = execute
        task = asyncio.create_task(
            processor._execute_single(_block(tool_input={"path": "private-path-marker"}))
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert timeline.record_tool_result.call_count == 1
        assert "private-path-marker" not in str(timeline.mock_calls)
        assert "private-path-marker" not in str(processor.tool_log)

    asyncio.run(scenario())


def test_external_execution_ack_does_not_claim_tool_completion() -> None:
    order: list[str] = []

    class Timeline:
        def record_tool_call(
            self,
            _name: str,
            _arguments: dict,
            *,
            call_id: str,
        ) -> None:
            assert call_id == "tool-1"
            order.append("tool.called")

        def record_tool_result(self, *_args: object, **_kwargs: object) -> None:
            order.append("tool.completed")

    async def handler(**_kwargs: object) -> dict[str, object]:
        return {"external_execution": "deferred", "projected_to_tau2": True}

    executor = ToolExecutor(action_handlers={"read_file": handler})
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=MagicMock(),
        timeline=Timeline(),
    )

    asyncio.run(processor._execute_single(_block()))

    assert order == ["tool.called"]


def test_personal_failure_is_omitted_from_hooks_logs_and_event_store(tmp_path, caplog) -> None:
    from core.memory.episodic import EpisodicStore, get_episodic_store, set_episodic_store
    from core.tools.personal_data import PERSONAL_DATA_ERROR_OMITTED
    from core.wiring.bootstrap import build_hooks

    private_error = "private-cell-value-4f93bd"

    def personal_handler(**_kwargs: object) -> dict[str, object]:
        return {
            "error": private_error,
            "error_type": "connection",
            "recoverable": True,
        }

    error_recovery = MagicMock()
    error_recovery.arecover = AsyncMock()
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    previous_episodic_store = get_episodic_store()
    set_episodic_store(EpisodicStore(path=tmp_path / "episodes.jsonl"))
    hooks, event_store, _metrics = build_hooks(
        session_key="privacy-test", run_id="privacy-run", log_dir=tmp_path
    )
    registry = HookRegistry(events=hooks)
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    executor = ToolExecutor(
        action_handlers={"google_sheets_read": personal_handler},
        hooks=hooks,
        hook_registry=registry,
    )
    failed_payloads: list[dict] = []
    hooks.register(
        HookEvent.TOOL_EXEC_FAILED,
        lambda _event, data: failed_payloads.append(dict(data)),
        name="privacy_capture",
        priority=85,
    )
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=error_recovery,
        hooks=hooks,
    )

    try:
        with caplog.at_level(logging.INFO, logger="core.wiring.bootstrap"):
            result = asyncio.run(
                processor._execute_single(
                    _block(
                        name="google_sheets_read",
                        tool_input={
                            "spreadsheet_id": "private-sheet",
                            "range": "Sheet1!A1",
                        },
                    )
                )
            )
        persisted = event_store.read(limit=100)
    finally:
        hooks.close()
        set_episodic_store(previous_episodic_store)

    assert private_error in result["content"]
    assert private_error not in json.dumps(failed_payloads)
    assert PERSONAL_DATA_ERROR_OMITTED in failed_payloads[0]["error"]
    assert private_error not in caplog.text
    assert "private-sheet" not in caplog.text
    assert PERSONAL_DATA_ERROR_OMITTED in caplog.text
    persisted_payload = json.dumps([row.payload for row in persisted])
    assert private_error not in persisted_payload
    assert "private-sheet" not in persisted_payload
