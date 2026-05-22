"""CSA-2 — tool_use accumulator + extract_tool_calls."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("inspect_ai", reason="audit extra required (ToolCall)")


# ---------------------------------------------------------------------------
# Event-list construction helpers
# ---------------------------------------------------------------------------


def _ev(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, "payload": payload}


def _start(
    index: int, *, id: str, name: str, input: dict[str, Any] | None = None
) -> dict[str, Any]:
    return _ev(
        "content_block_start",
        index=index,
        content_block={"type": "tool_use", "id": id, "name": name, "input": input or {}},
    )


def _delta(index: int, partial_json: str) -> dict[str, Any]:
    return _ev(
        "content_block_delta",
        index=index,
        delta={"type": "input_json_delta", "partial_json": partial_json},
    )


def _stop(index: int) -> dict[str, Any]:
    return _ev("content_block_stop", index=index)


# ---------------------------------------------------------------------------
# Accumulator basics
# ---------------------------------------------------------------------------


def test_accumulator_assembles_simple_json() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message")
    acc.partial_json_parts = ['{"messa', 'ge":', ' "hi"}']
    args, err = acc.assemble_arguments()
    assert args == {"message": "hi"}
    assert err is None


def test_accumulator_empty_partials_returns_empty_dict() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message")
    args, err = acc.assemble_arguments()
    assert args == {}
    assert err is None


def test_accumulator_uses_initial_input_when_no_deltas() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message", initial_input={"k": "v"})
    args, err = acc.assemble_arguments()
    assert args == {"k": "v"}
    assert err is None


def test_accumulator_malformed_sets_parse_error() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message")
    acc.partial_json_parts = ["{not json"]
    args, err = acc.assemble_arguments()
    assert args == {}
    assert err is not None
    assert "partial_json parse failed" in err


def test_accumulator_decoded_non_object_sets_parse_error() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message")
    acc.partial_json_parts = ["42"]
    args, err = acc.assemble_arguments()
    assert args == {}
    assert err is not None
    assert "expected object" in err


def test_accumulator_whitespace_only_partials_returns_empty() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import ToolUseAccumulator

    acc = ToolUseAccumulator(index=0, id="tu_1", name="send_message")
    acc.partial_json_parts = ["  ", "\n"]
    args, err = acc.assemble_arguments()
    assert args == {}
    assert err is None


# ---------------------------------------------------------------------------
# extract_tool_calls — single tool_use block
# ---------------------------------------------------------------------------


def test_extract_single_tool_call_via_deltas() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="send_message"),
        _delta(0, '{"body": "hello"}'),
        _stop(0),
    ]
    calls = extract_tool_calls(events)
    assert len(calls) == 1
    assert calls[0].id == "tu_1"
    assert calls[0].function == "send_message"
    assert calls[0].arguments == {"body": "hello"}
    assert calls[0].parse_error is None
    assert calls[0].type == "function"


def test_extract_strips_mcp_prefix_when_server_name_given() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="mcp__bridge__send_message"),
        _delta(0, "{}"),
        _stop(0),
    ]
    calls = extract_tool_calls(events, server_name="bridge")
    assert calls[0].function == "send_message"


def test_extract_passthrough_when_no_server_name() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="mcp__bridge__send_message"),
        _delta(0, "{}"),
        _stop(0),
    ]
    calls = extract_tool_calls(events)
    assert calls[0].function == "mcp__bridge__send_message"


def test_extract_falls_back_to_initial_input_dict() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="send_message", input={"body": "ohai"}),
        _stop(0),
    ]
    calls = extract_tool_calls(events)
    assert calls[0].arguments == {"body": "ohai"}


# ---------------------------------------------------------------------------
# extract_tool_calls — parallel tool_calls
# ---------------------------------------------------------------------------


def test_extract_two_parallel_tool_calls_preserves_order() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="send_message"),
        _start(1, id="tu_2", name="resume"),
        _delta(0, '{"a": 1}'),
        _delta(1, '{"b": 2}'),
        _stop(0),
        _stop(1),
    ]
    calls = extract_tool_calls(events)
    assert [c.function for c in calls] == ["send_message", "resume"]
    assert calls[0].arguments == {"a": 1}
    assert calls[1].arguments == {"b": 2}


def test_extract_interleaved_deltas_keyed_by_index() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="t_a"),
        _start(1, id="tu_2", name="t_b"),
        _delta(0, '{"a"'),
        _delta(1, '{"b"'),
        _delta(0, ":1}"),
        _delta(1, ":2}"),
        _stop(0),
        _stop(1),
    ]
    calls = extract_tool_calls(events)
    assert calls[0].arguments == {"a": 1}
    assert calls[1].arguments == {"b": 2}


# ---------------------------------------------------------------------------
# extract_tool_calls — robustness
# ---------------------------------------------------------------------------


def test_extract_text_only_events_returns_empty() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _ev("message_start", message={"id": "m1"}),
        _ev(
            "content_block_start",
            index=0,
            content_block={"type": "text", "text": ""},
        ),
        _ev(
            "content_block_delta",
            index=0,
            delta={"type": "text_delta", "text": "hello"},
        ),
        _ev("content_block_stop", index=0),
        _ev("message_stop"),
    ]
    assert extract_tool_calls(events) == []


def test_extract_ignores_unknown_event_types() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _ev("future_event_type", weird="payload"),
        _start(0, id="tu_1", name="send_message"),
        _delta(0, '{"x": 1}'),
        _stop(0),
        _ev("another_future_event", value=42),
    ]
    calls = extract_tool_calls(events)
    assert len(calls) == 1
    assert calls[0].arguments == {"x": 1}


def test_extract_orphan_delta_without_start_is_ignored() -> None:
    """A delta for an unknown index should not blow up — defensive."""
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _delta(99, '{"orphan": true}'),
        _start(0, id="tu_1", name="t"),
        _delta(0, "{}"),
        _stop(0),
    ]
    calls = extract_tool_calls(events)
    assert len(calls) == 1


def test_extract_orphan_stop_without_start_is_ignored() -> None:
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _stop(99),  # orphan
        _start(0, id="tu_1", name="t"),
        _delta(0, "{}"),
        _stop(0),
    ]
    calls = extract_tool_calls(events)
    assert len(calls) == 1


def test_extract_missing_stop_omits_call() -> None:
    """A tool_use block without content_block_stop is never materialised."""
    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    events = [
        _start(0, id="tu_1", name="t"),
        _delta(0, '{"x": 1}'),
        # No stop event
    ]
    calls = extract_tool_calls(events)
    assert calls == []


def test_extract_accepts_dataclass_shape_events() -> None:
    """CSA-1's parse_stream_json_events returns StreamJsonEvent
    dataclasses, not dicts. The parser must accept both."""
    from dataclasses import dataclass

    from plugins.petri_audit.mcp_bridge.stream_parser_ext import extract_tool_calls

    @dataclass(frozen=True)
    class StreamJsonEvent:
        type: str
        payload: dict[str, Any]

    events = [
        StreamJsonEvent(
            type="content_block_start",
            payload={
                "index": 0,
                "content_block": {"type": "tool_use", "id": "tu_1", "name": "t"},
            },
        ),
        StreamJsonEvent(
            type="content_block_delta",
            payload={"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"a":1}'}},
        ),
        StreamJsonEvent(type="content_block_stop", payload={"index": 0}),
    ]
    calls = extract_tool_calls(events)
    assert len(calls) == 1
    assert calls[0].arguments == {"a": 1}
