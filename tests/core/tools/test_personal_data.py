"""Durable-persistence redaction for personal Workspace tool data."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import MagicMock

from core.agent.tool_executor import ToolExecutor
from core.agent.tool_executor.processor import ToolCallProcessor
from core.hooks import HookAction, HookDecision, HookName, HookRegistry, MiddlewareRegistry
from core.orchestration.tool_offload import ToolResultOffloadStore
from core.tools.personal_data import (
    sanitize_personal_data_payload,
    set_bound_tool_data_policies,
)


def test_sanitizer_rewrites_anthropic_tool_call_and_result_by_call_id() -> None:
    payload = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "gmail_search",
                    "input": {"query": "from:private@example.com"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "private mailbox body",
                }
            ],
        },
    ]

    sanitized = sanitize_personal_data_payload(payload)
    encoded = json.dumps(sanitized)

    assert "private@example.com" not in encoded
    assert "private mailbox body" not in encoded
    assert encoded.count("_personal_data_omitted") == 2
    assert "call-1" in encoded


def test_plan_declared_redaction_covers_future_tool_without_static_name_edit() -> None:
    from core.tools.plan import (
        DataClassification,
        ExecutionBinding,
        PersistenceRule,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    redacted_name = "future_sensitive_read"
    personal_name = "future_personal_read"
    plan = compile_tool_plan(
        (
            (ToolSpec(redacted_name, "Future", {}), "test"),
            (ToolSpec(personal_name, "Future personal", {}), "test"),
        ),
        (
            ExecutionBinding(redacted_name, "test"),
            ExecutionBinding(personal_name, "test"),
        ),
        safety={
            redacted_name: SafetyPolicy(persistence=PersistenceRule.REDACT),
            personal_name: SafetyPolicy(data_class=DataClassification.PERSONAL),
        },
    )
    bound = bind_tool_plan(
        plan,
        {redacted_name: MagicMock(), personal_name: MagicMock()},
    )
    payload = [
        {
            "type": "tool_use",
            "id": "future-call",
            "name": redacted_name,
            "input": {"secret": 1},
        },
        {"type": "tool_result", "tool_use_id": "future-call", "content": "payload-value"},
        {
            "tool": personal_name,
            "input": {"secret": 2},
            "result": {"content": "personal-value"},
        },
    ]

    try:
        set_bound_tool_data_policies(bound)
        encoded = json.dumps(sanitize_personal_data_payload(payload))
    finally:
        set_bound_tool_data_policies(None)

    assert "secret" not in encoded
    assert "payload-value" not in encoded
    assert "personal-value" not in encoded
    assert encoded.count("_personal_data_omitted") == 4


def test_bound_public_policy_overrides_legacy_personal_name_fallback() -> None:
    from core.tools.plan import (
        ExecutionBinding,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    name = "gmail_search"
    plan = compile_tool_plan(
        ((ToolSpec(name, "Compatibility-name probe", {}), "test"),),
        (ExecutionBinding(name, "test"),),
        safety={name: SafetyPolicy()},
    )
    bound = bind_tool_plan(plan, {name: MagicMock()})
    payload = {
        "tool": name,
        "input": {"query": "public-query"},
        "result": {"content": "public-result"},
    }

    try:
        set_bound_tool_data_policies(bound)
        sanitized = sanitize_personal_data_payload(payload)
    finally:
        set_bound_tool_data_policies(None)

    assert sanitized == payload


def test_plan_redaction_keeps_raw_active_result_out_of_durable_sinks(tmp_path) -> None:
    from core.hooks import HookEvent
    from core.memory.episodic import EpisodicStore, set_episodic_store
    from core.memory.session_checkpoint import SessionCheckpoint, SessionState
    from core.tools.plan import (
        DataClassification,
        ExecutionBinding,
        PersistenceRule,
        SafetyPolicy,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    name = "future_sensitive_read"
    plan = compile_tool_plan(
        ((ToolSpec(name, "Future", {}), "test"),),
        (ExecutionBinding(name, "test"),),
        safety={
            name: SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
            )
        },
    )
    bound = bind_tool_plan(
        plan,
        {name: MagicMock(return_value={"content": "payload-value " * 100})},
    )
    public_payloads: list[dict[str, object]] = []
    hooks = HookRegistry()
    hooks.register(
        HookName.PRE_TOOL_USE,
        lambda invocation: public_payloads.append(dict(invocation.payload)),
    )
    hooks.register(
        HookName.POST_TOOL_USE,
        lambda invocation: public_payloads.append(dict(invocation.payload)),
    )
    transcript = MagicMock()
    offload_store = ToolResultOffloadStore(
        session_id="future",
        threshold=1,
        base_dir=tmp_path / "offload",
    )
    processor = ToolCallProcessor(
        executor=ToolExecutor(
            bound_tool_plan=bound,
            auto_approve=True,
            hook_registry=hooks,
        ),
        op_logger=MagicMock(log_tool_call=MagicMock(return_value=True)),
        error_recovery=MagicMock(),
        timeline=transcript,
        offload_store=offload_store,
    )
    block = type(
        "Block",
        (),
        {"name": name, "input": {"query": "private-query"}, "id": "future-call"},
    )()
    episodic_store = EpisodicStore(path=tmp_path / "episodes.jsonl")
    try:
        set_bound_tool_data_policies(bound)
        active = asyncio.run(processor._execute_single(block))

        checkpoint = SessionCheckpoint(tmp_path / "checkpoint")
        checkpoint.save(
            SessionState(
                session_id="future-sensitive",
                messages=[
                    {
                        "type": "tool_use",
                        "id": "future-call",
                        "name": name,
                        "input": {"query": "private-query"},
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "future-call",
                        "content": "payload-value",
                    },
                ],
                tool_log=processor.tool_log,
            )
        )

        set_episodic_store(episodic_store)
        from core.wiring.bootstrap import make_episodic_recorder_handler

        _hook_name, record_episode = make_episodic_recorder_handler()
        record_episode(
            HookEvent.TOOL_EXEC_ENDED,
            {
                "tool_name": name,
                "tool_input": {"query": "private-query"},
                "has_error": True,
                "result": {"error": "payload-value"},
                "duration_ms": 1.0,
            },
        )
    finally:
        set_episodic_store(None)
        set_bound_tool_data_policies(None)

    assert "payload-value" in active["content"]
    durable = json.dumps(processor.tool_log)
    assert "private-query" not in durable
    assert "payload-value" not in durable
    assert "_personal_data_omitted" in durable
    assert list((tmp_path / "offload").rglob("*.json")) == []
    transcript.record_tool_call.assert_called_once()
    assert transcript.record_tool_call.call_args.args[1]["_personal_data_omitted"] is True
    encoded_hooks = json.dumps(public_payloads)
    assert "private-query" not in encoded_hooks
    assert "payload-value" not in encoded_hooks
    assert "_personal_data_omitted" in encoded_hooks
    checkpoint_bytes = b"".join(
        path.read_bytes() for path in (tmp_path / "checkpoint").rglob("*") if path.is_file()
    )
    assert b"private-query" not in checkpoint_bytes
    assert b"payload-value" not in checkpoint_bytes
    assert b"_personal_data_omitted" in checkpoint_bytes
    episodic_bytes = episodic_store.path.read_bytes()
    assert b"private-query" not in episodic_bytes
    assert b"payload-value" not in episodic_bytes
    assert b"_personal_data_omitted" in episodic_bytes


def test_sanitizer_rewrites_openai_function_call_and_output() -> None:
    payload = [
        {
            "type": "function_call",
            "call_id": "call-2",
            "name": "google_docs_write",
            "arguments": '{"text":"private document text"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-2",
            "output": '{"document":"private result"}',
        },
    ]

    encoded = json.dumps(sanitize_personal_data_payload(payload))

    assert "private document text" not in encoded
    assert "private result" not in encoded
    assert encoded.count("_personal_data_omitted") == 2


def test_sanitizer_rewrites_tool_log_rows_without_touching_other_tools() -> None:
    payload = [
        {
            "tool": "google_sheets_read",
            "input": {"spreadsheet_id": "private-sheet"},
            "result": {"values": [["private cell"]]},
        },
        {"tool": "calculate", "input": {"expression": "2+2"}, "result": {"value": 4}},
    ]

    sanitized = sanitize_personal_data_payload(payload)
    encoded = json.dumps(sanitized)

    assert "private-sheet" not in encoded
    assert "private cell" not in encoded
    assert sanitized[1] == payload[1]


def test_tool_processor_records_only_markers_in_builtin_durable_sinks() -> None:
    op_logger = MagicMock()
    transcript = MagicMock()
    processor = ToolCallProcessor(
        executor=MagicMock(),
        op_logger=op_logger,
        error_recovery=MagicMock(),
        timeline=transcript,
    )

    processor._record_tool_activity(
        "gmail_search",
        {"query": "from:private@example.com"},
        {"messages": [{"body": "private mailbox body"}]},
        True,
        "call-3",
    )

    encoded = json.dumps(processor.tool_log)
    assert "private@example.com" not in encoded
    assert "private mailbox body" not in encoded
    assert "_personal_data_omitted" in encoded
    transcript.record_tool_call.assert_called_once()
    assert transcript.record_tool_call.call_args.args[1]["_personal_data_omitted"] is True
    op_logger.log_tool_result.assert_called_once_with(
        "gmail_search",
        {"summary": "personal account data returned (not retained)"},
        visible=True,
    )


def test_personal_result_reaches_active_turn_without_filesystem_offload(tmp_path) -> None:
    store = ToolResultOffloadStore(
        session_id="personal",
        threshold=1,
        base_dir=tmp_path,
    )
    processor = ToolCallProcessor(
        executor=MagicMock(),
        op_logger=MagicMock(),
        error_recovery=MagicMock(),
        offload_store=store,
    )
    block = asyncio.run(
        processor._serialize_tool_result(
            {"messages": [{"body": "private body " * 100}]},
            "call-4",
            "gmail_search",
        )
    )

    assert "private body" in block["content"]
    assert "_offloaded" not in block["content"]
    assert list(tmp_path.rglob("*.json")) == []


def test_rewritten_personal_tool_identity_controls_durable_retention() -> None:
    class RewriteToPersonal:
        async def tool_request(self, request):
            return replace(
                request,
                tool_name="google_sheets_read",
                arguments={
                    "spreadsheet_id": "private-sheet",
                    "range": "Sheet1!A1",
                },
            )

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteToPersonal(), name="rewrite-personal")
    hooks = HookRegistry()
    hooks.register(
        HookName.PERMISSION_REQUEST,
        lambda _invocation: HookDecision(action=HookAction.ALLOW),
    )
    executor = ToolExecutor(
        action_handlers={
            "google_sheets_read": lambda **_kwargs: {"values": [["private-cell-value"]]}
        },
        hook_registry=hooks,
        middleware_registry=middleware,
    )
    transcript = MagicMock()
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=MagicMock(),
        timeline=transcript,
    )
    block = type(
        "Block",
        (),
        {
            "name": "check",
            "input": {"public": True},
            "id": "call-rewritten",
        },
    )()

    active_result = asyncio.run(processor._execute_single(block))

    assert "private-cell-value" in active_result["content"]
    durable = json.dumps(processor.tool_log)
    assert "private-sheet" not in durable
    assert "private-cell-value" not in durable
    assert "_personal_data_omitted" in durable
    assert processor.tool_log[0]["tool"] == "google_sheets_read"
    transcript.record_tool_call.assert_called_once()
    assert transcript.record_tool_call.call_args.args[0] == "google_sheets_read"
