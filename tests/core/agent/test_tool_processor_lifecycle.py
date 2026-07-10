"""Canonical start/end coverage for every ToolCallProcessor path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from core.agent.error_recovery import RecoveryResult, RecoveryStrategy
from core.agent.tool_executor import ToolExecutor
from core.agent.tool_executor.processor import ToolCallProcessor
from core.hooks import HookEvent, HookSystem


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


def _block() -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use",
        name="read_file",
        input={"path": "notes.md"},
        id="tool-1",
    )


def _capture_events(hooks: HookSystem) -> list[HookEvent]:
    events: list[HookEvent] = []
    hooks.register_sink(lambda dispatch: events.append(dispatch.event), name="capture")
    return events


def test_interceptor_block_still_emits_terminal_end_and_failure() -> None:
    processor, hooks, executor = _processor()
    events = _capture_events(hooks)
    hooks.register(
        HookEvent.TOOL_EXEC_STARTED,
        lambda _event, _data: {"block": True, "reason": "policy"},
        name="policy",
        priority=1,
    )

    asyncio.run(processor._execute_single(_block()))

    assert events == [
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_RESULT_TRANSFORM,
        HookEvent.TOOL_EXEC_ENDED,
        HookEvent.TOOL_EXEC_FAILED,
    ]
    executor.aexecute.assert_not_awaited()


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
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_RECOVERY_ATTEMPTED,
        HookEvent.TOOL_RECOVERY_SUCCEEDED,
        HookEvent.TOOL_RESULT_TRANSFORM,
        HookEvent.TOOL_EXEC_ENDED,
    ]
    executor.aexecute.assert_not_awaited()


def test_executor_exception_becomes_failed_terminal_result() -> None:
    processor, hooks, _executor = _processor(executor_error=RuntimeError("boom"))
    events = _capture_events(hooks)

    result = asyncio.run(processor._execute_single(_block()))

    assert events == [
        HookEvent.TOOL_EXEC_STARTED,
        HookEvent.TOOL_RESULT_TRANSFORM,
        HookEvent.TOOL_EXEC_ENDED,
        HookEvent.TOOL_EXEC_FAILED,
    ]
    assert "boom" in result["content"]
