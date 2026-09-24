"""GLM request parity and subscription policy without network calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from core.config import settings
from core.llm.adapters.base import AdapterCallRequest, Message, ToolSpec
from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter
from core.llm.adapters.glm_payg import GlmPaygAdapter
from core.llm.errors import ModelSourceUnavailableError
from core.llm.providers.glm import (
    build_glm_reasoning_extra_body,
    get_glm_model_spec,
)


@pytest.mark.parametrize("model", ("glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"))
@pytest.mark.parametrize(
    ("effort", "native"),
    (
        ("low", "low"),
        ("high", "high"),
        ("max", "max"),
        ("none", "low"),
        ("minimal", "low"),
        ("medium", "high"),
        ("xhigh", "max"),
    ),
)
def test_always_on_reasoning_never_sends_disabled(model: str, effort: str, native: str) -> None:
    assert build_glm_reasoning_extra_body(model, effort=effort) == {
        "reasoning_effort": native,
        "thinking": {"type": "enabled"},
    }


def test_model_spec_is_exact_and_request_overrides_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "glm_reasoning_effort", "none")
    spec = get_glm_model_spec("glm-5.3-flash")
    assert spec is not None
    assert spec.supports_vision is True
    assert spec.max_output_tokens == 131_072
    assert spec.reasoning_effort_values == ("low", "high", "max")
    assert get_glm_model_spec("glm-5.3-future") is None
    assert build_glm_reasoning_extra_body("glm-5.3", effort="max") == {
        "reasoning_effort": "max",
        "thinking": {"type": "enabled"},
    }


def _response() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="done", tool_calls=None, reasoning_content="state"),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


def test_completion_and_text_share_glm_reasoning_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = GlmPaygAdapter()
    create = AsyncMock(return_value=_response())
    monkeypatch.setattr(
        adapter,
        "_get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    monkeypatch.setattr(settings, "glm_reasoning_effort", "max")
    asyncio.run(
        adapter.acomplete(
            AdapterCallRequest(
                model="glm-5.3",
                messages=(Message("user", "hi"),),
                effort="low",
            )
        )
    )
    assert create.call_args.kwargs["extra_body"]["reasoning_effort"] == "low"
    result = asyncio.run(adapter.acomplete_text("hi", model="glm-5.3"))
    assert result.text == "done"
    assert create.call_args.kwargs["extra_body"]["reasoning_effort"] == "max"


async def _chunks() -> AsyncIterator[SimpleNamespace]:
    for delta, finish in (
        (
            SimpleNamespace(
                reasoning_content="consider",
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=0, id="call", function=SimpleNamespace(name="read", arguments="{")
                    )
                ],
            ),
            None,
        ),
        (
            SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=0, id=None, function=SimpleNamespace(name=None, arguments='"p":"a"}')
                    )
                ],
            ),
            "tool_calls",
        ),
    ):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def test_stream_preserves_request_tools_reasoning_and_fragmented_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GlmPaygAdapter()
    create = AsyncMock(return_value=_chunks())
    monkeypatch.setattr(
        adapter,
        "_get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    request = AdapterCallRequest(
        model="glm-5.3-flash",
        messages=(Message("user", "read"),),
        effort="high",
        tools=(ToolSpec(name="read", description="Read a file", input_schema={"type": "object"}),),
        stop_sequences=("STOP",),
    )

    async def collect() -> list[Any]:
        return [event async for event in adapter.astream(request)]

    events = asyncio.run(collect())
    kwargs = create.call_args.kwargs
    assert kwargs["tools"][0]["function"]["name"] == "read"
    assert kwargs["stop"] == ["STOP"]
    assert kwargs["extra_body"]["reasoning_effort"] == "high"
    assert kwargs["extra_body"]["tool_stream"] is True
    assert [event.kind for event in events] == ["thinking", "tool_use", "stop"]
    assert events[1].payload == {"id": "call", "name": "read", "input": '{"p":"a"}'}


@pytest.mark.parametrize("operation", ("complete", "text", "stream", "client"))
def test_subscription_policy_rejects_before_credentials_or_network(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GlmCodingPlanAdapter()
    resolve = Mock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr("core.llm.adapters.glm_coding_plan._resolve_coding_plan_endpoint", resolve)
    request = AdapterCallRequest(model="glm-5.3", messages=(Message("user", "hi"),))

    async def invoke() -> None:
        if operation == "complete":
            await adapter.acomplete(request)
        elif operation == "text":
            await adapter.acomplete_text("hi", model="glm-5.3")
        elif operation == "client":
            adapter._get_client()
        else:
            async for _ in adapter.astream(request):
                pass

    with pytest.raises(ModelSourceUnavailableError, match="GEODE"):
        asyncio.run(invoke())
    resolve.assert_not_called()


def test_subscription_search_and_discovery_do_not_claim_api_parity() -> None:
    adapter = GlmCodingPlanAdapter()
    assert adapter.supports_web_search is False
    with pytest.raises(NotImplementedError, match="MCP"):
        asyncio.run(adapter.aweb_search("test"))
    assert adapter.list_models() == []
    assert adapter.detect_credential() is None
    assert adapter.test_environment().ok is False


def test_configured_model_discovery_preserves_payg_and_subscription_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import config

    monkeypatch.setattr(config, "GLM_PRIMARY", "glm-private-deployment")
    monkeypatch.setattr(config, "GLM_FALLBACK_CHAIN", ["glm-private-deployment", "glm-5.3"])
    ids = [model.id for model in GlmPaygAdapter().list_models()]
    assert ids.count("glm-private-deployment") == 1
    assert ids.count("glm-5.3") == 1
    assert GlmCodingPlanAdapter().list_models() == []


@pytest.mark.parametrize("stream", [False, True])
def test_glm_output_limit_and_tool_free_turn(stream: bool) -> None:
    from core.llm.providers.glm import build_glm_chat_kwargs

    request = AdapterCallRequest(
        model="glm-5.3",
        messages=(),
        max_tokens=200_000,
        tool_choice="none",
        tools=(ToolSpec(name="read", description="Read", input_schema={"type": "object"}),),
    )
    kwargs = build_glm_chat_kwargs(request, adapter_name="test", source="payg", stream=stream)
    assert kwargs["max_tokens"] == 131_072
    assert "tools" not in kwargs and "tool_choice" not in kwargs
    assert "tool_stream" not in kwargs.get("extra_body", {})


@pytest.mark.parametrize("choice", ["required", {"type": "tool", "name": "read"}])
def test_glm_rejects_undocumented_forced_tool_choice(choice: Any) -> None:
    from core.llm.errors import LLMRequestValidationError
    from core.llm.providers.glm import build_glm_chat_kwargs

    request = AdapterCallRequest(
        model="glm-5.3",
        messages=(),
        tool_choice=choice,
        tools=(ToolSpec(name="read", description="Read", input_schema={"type": "object"}),),
    )
    with pytest.raises(LLMRequestValidationError, match="automatic tool selection"):
        build_glm_chat_kwargs(request, adapter_name="test", source="payg")


@pytest.mark.parametrize("limit", [0, -1])
def test_glm_rejects_nonpositive_output_budget(limit: int) -> None:
    from core.llm.errors import LLMRequestValidationError
    from core.llm.providers.glm import build_glm_chat_kwargs

    with pytest.raises(LLMRequestValidationError, match="must be positive"):
        build_glm_chat_kwargs(
            AdapterCallRequest(model="glm-5.3", messages=(), max_tokens=limit),
            adapter_name="test",
            source="payg",
        )


@pytest.mark.parametrize(
    "model", ["glm-5.1", "glm-5", "glm-4.7", "glm-4.7-flash", "glm-4.7-flashx"]
)
def test_hybrid_thinking_does_not_advertise_graded_effort(model: str) -> None:
    from core.llm.model_catalog import model_spec_for_adapter

    spec = get_glm_model_spec(model)
    assert spec is not None and spec.supports_thinking
    assert spec.reasoning_effort_values == ()
    assert build_glm_reasoning_extra_body(model, effort="high") is None
    assert model_spec_for_adapter(model, provider="glm").supports_thinking


def test_stream_usage_retains_presence_and_precedes_terminal_stop() -> None:
    from core.llm.providers.glm import translate_glm_stream

    async def chunks() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(choices=[SimpleNamespace(delta=None, finish_reason="stop")])
        yield SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=0,
                completion_tokens=3,
                prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )

    async def collect() -> list[Any]:
        return [event async for event in translate_glm_stream(chunks())]

    events = asyncio.run(collect())
    assert [event.kind for event in events] == ["usage", "stop"]
    assert events[0].payload == {
        "input_tokens": 0,
        "output_tokens": 3,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "cache_write_tokens": 0,
        "reported_cost_usd": None,
        "input_tokens_present": True,
        "output_tokens_present": True,
        "cached_input_tokens_present": True,
        "reasoning_tokens_present": True,
        "cache_write_tokens_present": False,
        "cache_write_1h_tokens": None,
    }


def test_stream_eof_without_finish_reason_is_not_completion() -> None:
    from core.llm.providers.glm import translate_glm_stream

    async def chunks() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"), finish_reason=None)]
        )

    async def collect() -> None:
        async for _ in translate_glm_stream(chunks()):
            pass

    with pytest.raises(RuntimeError, match="without a finish reason"):
        asyncio.run(collect())


@pytest.mark.parametrize("reason", ["length", "network_error", "sensitive", "stop"])
def test_stream_never_executes_tools_on_non_tool_finish(reason: str) -> None:
    from core.llm.providers.glm import translate_glm_stream

    async def chunks() -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="partial",
                                function=SimpleNamespace(name="read", arguments="{"),
                            )
                        ]
                    ),
                    finish_reason=reason,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1),
        )

    async def collect() -> list[Any]:
        return [event async for event in translate_glm_stream(chunks())]

    events = asyncio.run(collect())
    assert [event.kind for event in events] == ["usage", "stop"]
    assert events[0].payload["output_tokens"] == 1
    assert events[-1].payload == {"stop_reason": reason}


@pytest.mark.parametrize("text", ["results", ""])
def test_hosted_search_retains_usage_on_success_and_empty_output(text: str) -> None:
    from core.llm.adapters._capability_impls import glm_web_search
    from core.llm.adapters.base import EmptyModelOutputError

    response = _response()
    response.choices[0].message.content = text
    response.usage = SimpleNamespace(
        prompt_tokens=12,
        completion_tokens=0,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    )
    call = glm_web_search(
        client, query="q", max_results=5, model="glm-5.3", adapter_name="glm-payg"
    )
    if text:
        result = asyncio.run(call)
    else:
        with pytest.raises(EmptyModelOutputError) as raised:
            asyncio.run(call)
        result = raised.value.completed_result
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 0 and result.usage.output_tokens_present
    assert result.usage.cached_input_tokens == 0 and result.usage.cached_input_tokens_present
