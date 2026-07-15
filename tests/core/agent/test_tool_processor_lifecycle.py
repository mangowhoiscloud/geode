"""Canonical start/end coverage for every ToolCallProcessor path."""

from __future__ import annotations

import asyncio
import json
import logging
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


def test_personal_failure_is_omitted_from_hooks_logs_and_event_store(tmp_path, caplog) -> None:
    from core.memory.episodic import EpisodicStore, get_episodic_store, set_episodic_store
    from core.tools.personal_data import PERSONAL_DATA_ERROR_OMITTED
    from core.wiring.bootstrap import build_hooks

    private_error = "private-cell-value-4f93bd"
    executor = MagicMock(spec=ToolExecutor)
    executor.aexecute = AsyncMock(
        return_value={
            "error": private_error,
            "error_type": "connection",
            "recoverable": True,
        }
    )
    error_recovery = MagicMock()
    error_recovery.arecover = AsyncMock()
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    previous_episodic_store = get_episodic_store()
    set_episodic_store(EpisodicStore(path=tmp_path / "episodes.jsonl"))
    hooks, event_store, _metrics = build_hooks(
        session_key="privacy-test", run_id="privacy-run", log_dir=tmp_path
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
                        tool_input={"spreadsheet_id": "private-sheet"},
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
