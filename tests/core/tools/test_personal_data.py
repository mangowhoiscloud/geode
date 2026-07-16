"""Durable-persistence redaction for personal Workspace tool data."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from core.agent.tool_executor.processor import ToolCallProcessor
from core.orchestration.tool_offload import (
    ToolResultOffloadStore,
    get_offload_store,
    set_offload_store,
)
from core.tools.personal_data import sanitize_personal_data_payload


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
        transcript=transcript,
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
    processor = ToolCallProcessor(
        executor=MagicMock(),
        op_logger=MagicMock(),
        error_recovery=MagicMock(),
    )
    previous = get_offload_store()
    store = ToolResultOffloadStore(
        session_id="personal",
        threshold=1,
        base_dir=tmp_path,
    )
    try:
        set_offload_store(store)
        block = asyncio.run(
            processor._serialize_tool_result(
                {"messages": [{"body": "private body " * 100}]},
                "call-4",
                "gmail_search",
            )
        )
    finally:
        set_offload_store(previous)

    assert "private body" in block["content"]
    assert "_offloaded" not in block["content"]
    assert list(tmp_path.rglob("*.json")) == []
