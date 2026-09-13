"""Canonical start/end coverage for every ToolCallProcessor path."""

from __future__ import annotations

import asyncio
import json
import logging
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
)


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
