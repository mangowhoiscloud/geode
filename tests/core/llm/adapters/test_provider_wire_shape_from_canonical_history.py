"""Provider wire-shape guards from GEODE's canonical tool history."""

from __future__ import annotations

from core.llm.adapters import _anthropic_common
from core.llm.adapters._openai_common import build_messages as build_chat_messages
from core.llm.adapters._openai_common import build_responses_kwargs
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec


def _canonical_request(model: str = "gpt-5.5") -> AdapterCallRequest:
    return AdapterCallRequest(
        model=model,
        system_prompt="system",
        messages=(
            Message(role="user", content="call the tool"),
            Message(
                role="assistant",
                content=[
                    {"type": "text", "text": "I will call it."},
                    {
                        "type": "tool_use",
                        "id": "call_demo_1",
                        "name": "demo_tool",
                        "input": {"value": 7},
                    },
                ],
            ),
            Message(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_demo_1",
                        "content": "demo result",
                    }
                ],
            ),
        ),
        tools=(
            ToolSpec(
                name="demo_tool",
                description="demo",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                },
            ),
        ),
    )


def test_anthropic_wire_shape_preserves_canonical_tool_blocks() -> None:
    messages = _anthropic_common.build_messages(_canonical_request("claude-opus-4-8"))

    assistant = messages[1]
    result = messages[2]
    assert assistant["role"] == "assistant"
    assert assistant["content"][1]["type"] == "tool_use"
    assert assistant["content"][1]["id"] == "call_demo_1"
    assert result == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_demo_1",
                "content": "demo result",
            }
        ],
    }


def test_glm_chat_wire_shape_reencodes_tool_blocks_for_chat_completions() -> None:
    messages = build_chat_messages(_canonical_request("glm-5.2"))

    assistant = messages[2]
    tool_result = messages[3]
    assert messages[0] == {"role": "system", "content": "system"}
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "I will call it."
    assert assistant["tool_calls"] == [
        {
            "id": "call_demo_1",
            "type": "function",
            "function": {
                "name": "demo_tool",
                "arguments": '{"value": 7}',
            },
        }
    ]
    assert tool_result == {
        "role": "tool",
        "tool_call_id": "call_demo_1",
        "content": "demo result",
    }


def test_openai_responses_wire_shape_reencodes_tool_blocks_as_typed_items() -> None:
    kwargs = build_responses_kwargs(
        _canonical_request("gpt-5.5"),
        backend="codex",
        adapter_name="codex-oauth",
    )

    resp_input = kwargs["input"]
    assert kwargs["instructions"] == "system"
    assert {"type": "function_call_output", "call_id": "call_demo_1", "output": "demo result"} in (
        resp_input
    )
    function_call = next(item for item in resp_input if item.get("type") == "function_call")
    assert function_call["call_id"] == "call_demo_1"
    assert function_call["name"] == "demo_tool"
    assert function_call["arguments"] == '{"value": 7}'
    assert all(item.get("type") != "tool_result" for item in resp_input)
