"""Native toolset → executor → tool result replay, without desktop effects."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from core.agent.tool_executor.processor import ToolCallProcessor
from core.llm.adapters._anthropic_common import (
    build_create_kwargs,
    build_messages,
    build_stream_kwargs,
    translate_response,
)
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.errors import LLMResponseValidationError
from core.tools.handlers.single_tool import _build_computer_use_handler


def _request() -> AdapterCallRequest:
    return AdapterCallRequest(
        model="claude-opus-5-5",
        messages=(),
        executable_tool_names=frozenset({"computer"}),
        tools=(ToolSpec(name="computer", description="Desktop", input_schema={"type": "object"}),),
    )


def test_toolset_wire_is_serial_and_withholds_unimplemented_members() -> None:
    with patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=True):
        kwargs = build_create_kwargs(_request())
        assert kwargs == build_stream_kwargs(_request())
        tool = kwargs["tools"][0]
        assert len(kwargs["tools"]) == 1
        assert tool == {
            "type": "computer_toolset_20260801",
            "configs": {
                name: {"enabled": False}
                for name in ("zoom", "hold_key", "left_mouse_down", "left_mouse_up")
            },
        }
        assert kwargs["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
        assert "computer-use-" not in kwargs["extra_headers"]["anthropic-beta"]
        none = build_create_kwargs(replace(_request(), tool_choice="none"))
        assert none["tool_choice"] == {"type": "none"}


def _response(blocks: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(**block) for block in blocks],
        usage=None,
        model_dump=lambda **_: {"content": blocks},
    )


def test_native_member_executes_and_replays_with_toolset_identity() -> None:
    native = [
        {
            "type": "tool_use",
            "id": "tool-1",
            "name": "left_click",
            "toolset_name": "computer",
            "input": {"coordinate": [120, 240]},
        }
    ]
    result = translate_response(_response(native))
    assert result.tool_uses[0]["name"] == "computer"
    assert result.anthropic_content == tuple(native)
    fake = AsyncMock(return_value={"result": "success", "screenshot": "jpeg"})
    with (
        patch("core.llm.providers.anthropic.is_computer_use_enabled", return_value=True),
        patch("core.tools.computer_use.ComputerUseHarness.aexecute", fake),
    ):
        handler = dict(_build_computer_use_handler())["computer"]
        action_result = asyncio.run(handler(**result.tool_uses[0]["input"]))
    fake.assert_awaited_once_with("left_click", x=120, y=240)
    tool_result = ToolCallProcessor._serialize_computer_result(action_result, "tool-1")
    request = replace(
        _request(),
        messages=(
            Message(role="assistant", content="", anthropic_content=result.anthropic_content),
            Message(role="user", content=[tool_result]),
        ),
    )
    messages = build_messages(request)
    assert messages[0]["content"] == native
    assert messages[1]["content"][0]["toolset_name"] == "computer"
    assert messages[1]["content"][0]["content"][1]["type"] == "image"
    assert "toolset_name" not in tool_result  # no mutation of stored result


def test_custom_member_name_is_not_routed_as_computer() -> None:
    result = translate_response(
        _response(
            [{"type": "tool_use", "id": "ordinary", "name": "left_click", "input": {"value": 1}}]
        )
    )
    assert result.tool_uses[0]["name"] == "left_click"
    assert result.tool_uses[0]["input"] == {"value": 1}


def test_installed_sdk_preserves_native_toolset_fields() -> None:
    from anthropic.types import Message as AnthropicMessage

    native = {
        "type": "tool_use",
        "id": "one",
        "name": "screenshot",
        "toolset_name": "computer",
        "input": {},
    }
    response = AnthropicMessage.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [native],
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "stop_reason": "tool_use",
            "stop_sequence": None,
        }
    )
    result = translate_response(response)
    assert result.tool_uses[0]["name"] == "computer"
    assert result.tool_uses[0]["input"] == {"action": "screenshot"}
    assert result.anthropic_content[0]["toolset_name"] == "computer"


def test_unexpected_batch_fails_before_any_action_can_dispatch() -> None:
    block = {
        "type": "tool_use",
        "id": "one",
        "name": "left_click",
        "toolset_name": "computer",
        "input": {},
    }
    with pytest.raises(LLMResponseValidationError, match="multiple actions"):
        translate_response(_response([block, {**block, "id": "two"}]))


@pytest.mark.parametrize(("strict", "mixed", "cache"), [(False, False, 0), (True, True, None)])
def test_rejected_native_batch_keeps_paid_usage_without_retry_or_action(
    monkeypatch: pytest.MonkeyPatch, strict: bool, mixed: bool, cache: int | None
) -> None:
    import httpx
    from anthropic import AsyncAnthropic
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.hooks import HookEvent, HookSystem
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.fallback import RetryAction, classify_retry_error, interactive_retry_policy
    from core.llm.providers.anthropic import _build_httpx_timeout

    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1" if strict else "")
    native = {
        "type": "tool_use",
        "id": "one",
        "name": "screenshot",
        "toolset_name": "computer",
        "input": {},
    }
    second = (
        {"type": "tool_use", "id": "two", "name": "custom", "input": {}}
        if mixed
        else {**native, "id": "two"}
    )
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [native, second],
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 3,
                    "cache_read_input_tokens": cache,
                    "cache_creation_input_tokens": 7,
                },
                "stop_reason": "tool_use",
                "stop_sequence": None,
            },
        )

    hooks = HookSystem()
    ended: list[dict] = []
    hooks.register(HookEvent.LLM_CALL_ENDED, lambda _event, data: ended.append(data))
    action = AsyncMock()
    adapter = AnthropicPaygAdapter()
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={"computer": action, "custom": action}),
        hooks=hooks,
        config=AgenticLoopConfig(source="anthropic-payg"),
        model="claude-opus-5-5",
        provider="anthropic",
        quiet=True,
    )
    loop._new_adapter = adapter

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="synthetic-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond), timeout=_build_httpx_timeout()
            ),
        ) as client:
            with patch.object(adapter, "_get_client", return_value=client):
                if strict:
                    with pytest.raises(LLMResponseValidationError):
                        await loop.arun("Take one screenshot")
                else:
                    result = await loop.arun("Take one screenshot")
                    assert result.termination_reason == "model_action_required"
                    assert "Provider response failed validation" in result.text

    asyncio.run(run())
    assert len(requests) == 1
    action.assert_not_awaited()
    assert len(ended) == 1
    assert ended[0]["error_type"] == "LLMResponseValidationError"
    assert ended[0]["usage"] == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cached_input_tokens": cache,
        "cache_write_tokens": 7,
        "reasoning_tokens": None,
        "cache_write_1h_tokens": None,
    }
    assert ended[0]["cost_usd"] > 0
    assert "content" not in ended[0]
    error = adapter._last_error
    assert isinstance(error, LLMResponseValidationError)
    assert error.completed_result.anthropic_content[0]["toolset_name"] == "computer"
    assert (
        interactive_retry_policy().action_for(classify_retry_error(error)) is RetryAction.TERMINAL
    )


def test_rejected_sdk_stream_emits_usage_before_error_without_tools_or_stop() -> None:
    import json

    import httpx
    from anthropic import AsyncAnthropic
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter

    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 0, "cache_read_input_tokens": 0},
            },
        }
    ]
    for index in range(2):
        events.extend(
            [
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": f"tool-{index}",
                        "name": "screenshot",
                        "toolset_name": "computer",
                        "input": {},
                    },
                },
                {"type": "content_block_stop", "index": index},
            ]
        )
    events.extend(
        [
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 3},
            },
            {"type": "message_stop"},
        ]
    )
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    async def run() -> None:
        async with AsyncAnthropic(
            api_key="synthetic-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            adapter = AnthropicPaygAdapter()
            emitted = []
            with (
                patch.object(adapter, "_get_client", return_value=client),
                pytest.raises(LLMResponseValidationError),
            ):
                async for event in adapter.astream(_request()):
                    emitted.append(event)
            assert [event.kind for event in emitted] == ["usage"]
            assert emitted[0].payload["input_tokens"] == 12
            assert emitted[0].payload["output_tokens"] == 3
            assert emitted[0].payload["cached_input_tokens_present"] is True
            assert emitted[0].payload["cached_input_tokens"] == 0
            assert emitted[0].payload["cache_write_tokens_present"] is False

    asyncio.run(run())


def test_computer_error_is_native_error_result() -> None:
    # The error branch precedes processor services; a plain instance isolates it.
    processor = object.__new__(ToolCallProcessor)
    block = asyncio.run(
        processor._serialize_tool_result({"error": "unsupported member"}, "id", "computer")
    )
    assert block["is_error"] is True
    assert "unsupported member" in block["content"]


def test_role_tool_results_also_echo_toolset() -> None:
    native = (
        {
            "type": "tool_use",
            "id": "one",
            "name": "key",
            "toolset_name": "computer",
            "input": {"text": "Tab"},
        },
    )
    messages = build_messages(
        replace(
            _request(),
            messages=(
                Message(role="assistant", content="", anthropic_content=native),
                Message(role="tool", content="OK", tool_use_id="one"),
            ),
        )
    )
    assert messages[-1]["content"][0]["toolset_name"] == "computer"
