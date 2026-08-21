from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Iterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.agent.approval import ApprovalWorkflow
from core.agent.cognitive_state_ctx import set_session_id, set_turn_id
from core.agent.loop import _lifecycle
from core.agent.sub_agent import SubAgentManager, SubTask
from core.agent.tool_executor import ToolExecutor
from core.hooks import (
    HookAction,
    HookDecision,
    HookName,
    HookRegistry,
    MiddlewareRegistry,
    RuntimeEvent,
    RuntimeEventBus,
)
from core.orchestration.isolated_execution import IsolatedRunner


@pytest.fixture(autouse=True)
def _reset_hook_correlation_context() -> Iterator[None]:
    set_session_id("")
    set_turn_id("")
    yield
    set_session_id("")
    set_turn_id("")


def test_public_session_start_is_after_initial_durable_checkpoint() -> None:
    from core.agent.loop.agent_loop import AgenticLoop

    source = inspect.getsource(AgenticLoop._open_turn)
    assert source.index("if self._save_checkpoint(") < source.index("emit_public_session_start(")


def test_public_session_start_and_end_have_durable_cardinality() -> None:
    observed: list[tuple[HookName, str]] = []
    registry = HookRegistry()
    checkpoint = SimpleNamespace(status="")

    def observe(invocation: Any) -> None:
        observed.append((invocation.name, checkpoint.status))

    registry.register(HookName.SESSION_START, observe)
    registry.register(HookName.SESSION_END, observe)

    def mark_completed(_session_id: str) -> bool:
        checkpoint.status = "completed"
        return True

    checkpoint.mark_completed = mark_completed
    checkpoint.current_status = lambda _session_id: checkpoint.status
    loop = SimpleNamespace(
        _hook_registry=registry,
        _checkpoint=checkpoint,
        _session_id="s-1",
        _turn_id="t-1",
        _session_generation=1,
        _public_session_started=False,
        _public_session_ended=False,
        _parent_session_key="",
        model="gpt",
        _provider="openai",
    )

    async def run() -> None:
        await _lifecycle.emit_public_session_start(loop)
        await _lifecycle.emit_public_session_start(loop)
        await _lifecycle.mark_session_completed_async(loop)
        await _lifecycle.mark_session_completed_async(loop)

    asyncio.run(run())

    assert observed == [
        (HookName.SESSION_START, ""),
        (HookName.SESSION_END, "completed"),
    ]


def test_permission_request_can_deny_without_prompting_human() -> None:
    prompted = False
    registry = HookRegistry()
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.DENY),
    )

    def callback(*_args: object) -> str:
        nonlocal prompted
        prompted = True
        return "y"

    workflow = ApprovalWorkflow(
        hitl_level=2,
        hook_registry=registry,
        approval_callback=callback,
    )
    approved = asyncio.run(
        workflow.confirm_write_async(
            "memory_save",
            {"key": "k", "content": "v"},
        )
    )

    assert approved is False
    assert prompted is False


def test_hard_deny_precedes_public_permission_allow() -> None:
    registry = HookRegistry()
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(action=HookAction.REQUEST_PERMISSION),
    )
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    executor = ToolExecutor(
        action_handlers={"check": lambda **_kwargs: {"ok": True}},
        hook_registry=registry,
        denied_tools=frozenset({"check"}),
    )

    result = asyncio.run(executor.aexecute("check", {}))

    assert result["denied"] is True


def test_blocked_pre_tool_use_never_emits_execution_started() -> None:
    events = RuntimeEventBus()
    starts: list[dict[str, Any]] = []
    events.subscribe(
        RuntimeEvent.TOOL_EXEC_STARTED,
        lambda _event, payload: starts.append(payload),
        name="starts",
    )
    registry = HookRegistry(events=events)
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(
            action=HookAction.BLOCK,
            reason="blocked",
        ),
    )
    executor = ToolExecutor(
        action_handlers={"check": lambda **_kwargs: {"ok": True}},
        hooks=events,
        hook_registry=registry,
    )

    result = asyncio.run(executor.aexecute("check", {}))

    assert result["blocked_by_hook"] is True
    assert starts == []


def test_tool_runtime_events_keep_session_correlation() -> None:
    events = RuntimeEventBus()
    observed: list[dict[str, Any]] = []
    for event in (RuntimeEvent.TOOL_EXEC_STARTED, RuntimeEvent.TOOL_EXEC_ENDED):
        events.subscribe(
            event,
            lambda _event, payload: observed.append(payload),
            name=event.value,
        )
    set_session_id("session-1")
    set_turn_id("turn-1")
    executor = ToolExecutor(
        action_handlers={"check": lambda **_kwargs: {"ok": True}},
        hooks=events,
    )

    assert asyncio.run(executor.aexecute("check", {})) == {"ok": True}
    assert [(row["session_id"], row["turn_id"]) for row in observed] == [
        ("session-1", "turn-1"),
        ("session-1", "turn-1"),
    ]


def test_pre_tool_use_rewrite_reaches_the_effective_handler_request() -> None:
    observed: list[str] = []
    registry = HookRegistry()
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(
            action=HookAction.REWRITE,
            updates={"arguments": {"value": "rewritten"}},
        ),
    )
    executor = ToolExecutor(
        action_handlers={"check": lambda value: observed.append(value) or {"value": value}},
        hook_registry=registry,
    )

    result = asyncio.run(executor.aexecute("check", {"value": "original"}))

    assert result == {"value": "rewritten"}
    assert observed == ["rewritten"]


def test_large_tool_result_does_not_break_post_tool_use_projection() -> None:
    executor = ToolExecutor(
        action_handlers={
            "check": lambda **_kwargs: {f"row-{index}": "x" * 4_096 for index in range(20)}
        },
    )

    result = asyncio.run(executor.aexecute("check", {}))

    assert len(result) == 20


def test_personal_tool_partial_rewrite_preserves_private_arguments() -> None:
    observed: list[dict[str, Any]] = []
    registry = HookRegistry()
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(
            action=HookAction.REWRITE,
            updates={"tool_name": "google_sheets_read"},
        ),
    )
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    executor = ToolExecutor(
        action_handlers={
            "google_sheets_read": lambda **kwargs: observed.append(kwargs) or {"ok": True}
        },
        hook_registry=registry,
    )

    result = asyncio.run(
        executor.aexecute(
            "google_sheets_read",
            {"spreadsheet_id": "private-sheet", "range": "Sheet1!A1"},
        )
    )

    assert result == {"ok": True}
    assert observed[0]["spreadsheet_id"] == "private-sheet"


def test_personal_data_classification_cannot_be_downgraded_by_rewrite() -> None:
    class RewriteToSafe:
        async def tool_request(self, request: Any) -> Any:
            return replace(request, tool_name="check")

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteToSafe(), name="rewrite-safe")
    public_handler = MagicMock()
    hooks = HookRegistry()
    hooks.register(HookName.PRE_TOOL_USE, public_handler, name="public")
    safe_handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"check": safe_handler},
        hook_registry=hooks,
        middleware_registry=middleware,
    )

    result = asyncio.run(
        executor.aexecute(
            "google_sheets_read",
            {"spreadsheet_id": "private-sheet", "range": "Sheet1!A1"},
        )
    )

    assert result["error_type"] == "privacy_classification_downgrade"
    public_handler.assert_not_called()
    safe_handler.assert_not_called()


def test_headless_hook_permission_request_fails_closed_without_console() -> None:
    registry = HookRegistry()
    registry.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(action=HookAction.REQUEST_PERMISSION),
    )
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"check": handler},
        hook_registry=registry,
        interactive_approval=False,
    )

    with patch.object(
        executor._approval,
        "prompt_with_always",
        side_effect=AssertionError("headless path attempted console input"),
    ):
        result = asyncio.run(executor.aexecute("check", {}))

    assert result["denied"] is True
    handler.assert_not_called()


def test_goal_token_budget_fails_closed_without_explicit_permission() -> None:
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"create_goal": handler},
        interactive_approval=False,
    )

    result = asyncio.run(
        executor.aexecute(
            "create_goal",
            {"objective": "Finish the task", "token_budget": 1},
        )
    )

    assert result == {
        "error": (
            "token_budget requires explicit PermissionRequest approval; "
            "retry create_goal without token_budget when no budget was requested"
        ),
        "denied": True,
        "recoverable": True,
    }
    handler.assert_not_called()


def test_null_goal_token_budget_needs_no_permission() -> None:
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"create_goal": handler},
        interactive_approval=False,
    )

    result = asyncio.run(
        executor.aexecute(
            "create_goal",
            {"objective": "Finish the task", "token_budget": None},
        )
    )

    assert result == {"ok": True}
    handler.assert_called_once_with(objective="Finish the task", token_budget=None)


def test_goal_token_budget_permission_hook_can_authorize() -> None:
    observed: list[tuple[str, str]] = []
    registry = HookRegistry()

    def allow(invocation: Any) -> HookDecision:
        observed.append(
            (
                str(invocation.payload["safety_level"]),
                str(invocation.payload["detail"]),
            )
        )
        return HookDecision(action=HookAction.ALLOW)

    registry.register(HookName.PERMISSION_REQUEST, allow)
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"create_goal": handler},
        hook_registry=registry,
        interactive_approval=False,
    )

    result = asyncio.run(
        executor.aexecute(
            "create_goal",
            {"objective": "Finish the task", "token_budget": 200_000},
        )
    )

    assert result == {"ok": True}
    assert observed == [("goal_budget", "token_budget=200000")]
    handler.assert_called_once_with(objective="Finish the task", token_budget=200_000)


def test_headless_rewritten_mcp_permission_fails_closed_without_console() -> None:
    class RewriteToMcp:
        async def tool_request(self, request: Any) -> Any:
            return replace(request, tool_name="restricted_mcp", arguments={})

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteToMcp(), name="rewrite-mcp")
    mcp = MagicMock()
    mcp.find_server_for_tool.return_value = "restricted-server"
    mcp.acall_tool = MagicMock(side_effect=AssertionError("unapproved MCP tool executed"))
    executor = ToolExecutor(
        mcp_manager=mcp,
        middleware_registry=middleware,
        interactive_approval=False,
    )

    with patch.object(
        executor._approval,
        "prompt_with_always",
        side_effect=AssertionError("headless path attempted console input"),
    ):
        result = asyncio.run(executor.aexecute("check", {}))

    assert result["denied"] is True
    mcp.acall_tool.assert_not_called()


def test_execution_short_circuit_records_skipped_not_executed() -> None:
    class ShortCircuit:
        async def tool_execution(self, _request: Any, _next_call: Any) -> dict[str, Any]:
            return {"short": True}

    events = RuntimeEventBus()
    starts: list[dict[str, Any]] = []
    events.subscribe(
        RuntimeEvent.TOOL_EXEC_STARTED,
        lambda _event, payload: starts.append(payload),
        name="starts",
    )
    hooks = HookRegistry(events=events)
    hooks.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    middleware = MiddlewareRegistry(events=events)
    middleware.register_tool_execution(ShortCircuit(), name="short")
    executor = ToolExecutor(
        action_handlers={"memory_save": lambda **_kwargs: {"ok": True}},
        hooks=events,
        hook_registry=hooks,
        middleware_registry=middleware,
    )
    records: list[Any] = []
    original_begin = executor._approval.begin_record

    def capture_record(tool_name: str, **kwargs: Any) -> Any:
        record = original_begin(tool_name, **kwargs)
        records.append(record)
        return record

    with patch.object(executor._approval, "begin_record", side_effect=capture_record):
        result = asyncio.run(executor.aexecute("memory_save", {"key": "k", "content": "value"}))

    assert result == {"short": True}
    assert starts == []
    assert records[0].state == "skipped"
    assert records[0].transitions[-1].detail == "middleware-short-circuit"


def test_personal_tool_payload_is_omitted_from_public_hooks() -> None:
    captured: list[dict[str, Any]] = []
    registry = HookRegistry()

    def capture(invocation: Any) -> None:
        captured.append(dict(invocation.payload))

    registry.register(HookName.PRE_TOOL_USE, capture)
    registry.register(HookName.POST_TOOL_USE, capture)
    registry.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    executor = ToolExecutor(
        action_handlers={
            "google_sheets_read": lambda **_kwargs: {"values": [["private-cell-value"]]}
        },
        hook_registry=registry,
    )

    result = asyncio.run(
        executor.aexecute(
            "google_sheets_read",
            {"spreadsheet_id": "private-sheet", "range": "Sheet1!A1"},
        )
    )

    assert result["values"] == [["private-cell-value"]]
    public_payloads = json.dumps(captured)
    assert "private-sheet" not in public_payloads
    assert "private-cell-value" not in public_payloads
    assert "_personal_data_omitted" in public_payloads


def test_subagent_public_projection_pairs_start_and_stop() -> None:
    observed: list[tuple[HookName, dict[str, Any]]] = []
    registry = HookRegistry()

    def observe(invocation: Any) -> None:
        observed.append((invocation.name, dict(invocation.payload)))

    registry.register(HookName.SUBAGENT_START, observe)
    registry.register(HookName.SUBAGENT_STOP, observe)
    manager = SubAgentManager(
        IsolatedRunner(),
        task_handler=lambda *_args, **_kwargs: {"summary": "done"},
        timeout_s=10,
        hook_registry=registry,
    )
    set_session_id("s-parent")
    set_turn_id("t-parent")

    results = asyncio.run(
        manager.adelegate([SubTask("child-1", "Analyze", "analysis", {"subject": "repo"})])
    )

    assert results[0].success is True
    assert [name for name, _payload in observed] == [
        HookName.SUBAGENT_START,
        HookName.SUBAGENT_STOP,
    ]
    assert observed[0][1]["child_session_key"]
    assert observed[1][1]["success"] is True
