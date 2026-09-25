"""Context admission follows transformed requests and preserves history ownership."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, _phases
from core.agent.loop.models import TurnState, _ContextExhaustedError
from core.agent.tool_executor import ToolExecutor
from core.hooks import LlmCallRequest, MiddlewareRegistry
from core.llm.adapters import bootstrap_builtins
from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, Message, UsageSummary
from core.orchestration.context_monitor import estimate_tool_tokens
from core.tools.plan import ToolSpec
from openai import BadRequestError


class _Adapter:
    name = "offline-capture"
    provider = "openai"

    def __init__(self, source: str = "payg", reject: bool = False) -> None:
        self.source = source
        self.reject = reject
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        if self.reject:
            raise BadRequestError(
                "maximum context length exceeded",
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://offline.invalid")
                ),
                body={"error": {"code": "context_length_exceeded"}},
            )
        return AdapterCallResult(text="ok", stop_reason="end_turn", usage=UsageSummary())


def _loop_for(
    messages: list[dict[str, Any]],
    source: str = "payg",
    middleware: MiddlewareRegistry | None = None,
) -> AgenticLoop:
    bootstrap_builtins()
    loop = AgenticLoop(
        ConversationContext(messages=messages),
        ToolExecutor(action_handlers={}, middleware_registry=middleware),
        config=AgenticLoopConfig(source=source, max_rounds=0),
        model="gpt-6-sol",
        provider="openai",
        quiet=True,
    )
    loop._new_adapter = _Adapter(source)
    return loop


def test_final_transformed_error_metadata_and_codex_reserve() -> None:
    adapter = _Adapter("subscription", reject=True)
    tools = (ToolSpec(name="search", description="d" * 1000, input_schema={"type": "object"}),)
    native = ({"type": "reasoning", "encrypted_content": "opaque" * 20},)

    class Transform:
        async def llm_request(self, current: LlmCallRequest) -> LlmCallRequest:
            request = replace(
                current.request,
                model="gpt-6-astra",
                system_prompt="final system",
                max_tokens=999_999,
                tools=tools,
                messages=(
                    Message(role="assistant", content="answer", codex_reasoning_items=native),
                    Message(
                        role="tool",
                        content=[
                            {"type": "text", "text": "observation"},
                            {"type": "image", "source": {"type": "base64", "data": "fake"}},
                        ],
                        tool_use_id="t1",
                    ),
                ),
                metadata={"cache_invalidation_reason": "offline transformed request"},
            )
            return replace(current, adapter=adapter, request=request)

    middleware = MiddlewareRegistry()
    middleware.register_llm_request(Transform(), allow_cache_invalidation=True)
    messages = [{"role": "user", "content": "original"}]
    loop = _loop_for(messages, middleware=middleware)
    with pytest.raises(_ContextExhaustedError) as caught:
        asyncio.run(loop._call_llm("original system", messages))
    exc = caught.value
    sent = adapter.requests[0]
    assert exc.policy is not None
    assert exc.provider_rejected and exc.policy.model == "gpt-6-astra"
    assert exc.policy.provider == "openai" and exc.policy.source == "subscription"
    assert exc.policy.output_reserve_tokens == 20_000
    from core.llm.adapters._openai_common import effective_output_tokens

    assert effective_output_tokens(sent, backend="codex") is None
    assert exc.system_prompt == sent.system_prompt == "final system"
    assert exc.tools_tokens == estimate_tool_tokens(sent.tools) > 0
    assert sent.messages[0].codex_reasoning_items == native
    assert messages == [{"role": "user", "content": "original"}]


def test_larger_middleware_route_is_selected_before_context_maintenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    adapter = _Adapter("payg")
    transforms: list[LlmCallRequest] = []

    class Upgrade:
        async def llm_request(self, current: LlmCallRequest) -> LlmCallRequest:
            transforms.append(current)
            return replace(current, adapter=adapter)

    middleware = MiddlewareRegistry()
    middleware.register_llm_request(Upgrade())
    messages = [{"role": "user", "content": "x" * 800_000, "metadata": {"origin": "user_input"}}]
    loop = _loop_for(messages, source="subscription", middleware=middleware)
    original = deepcopy(messages)
    response = asyncio.run(loop._call_llm("", messages))
    assert response is not None and response.text == "ok"
    assert len(transforms) == len(adapter.requests) == 1
    assert messages == original
    assert adapter.requests[0].messages[0].content == original[0]["content"]


def test_transformed_history_overflow_never_compacts_the_original_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"root-{i}: " + "x" * 1500}
        for i in range(20)
    ]
    original = deepcopy(root_messages)
    adapter = _Adapter(reject=True)

    class ReplaceMessages:
        async def llm_request(self, current: LlmCallRequest) -> LlmCallRequest:
            return replace(
                current,
                adapter=adapter,
                request=replace(
                    current.request,
                    messages=(Message(role="user", content="unrelated replacement"),),
                    metadata={"cache_invalidation_reason": "offline replacement"},
                ),
            )

    middleware = MiddlewareRegistry()
    middleware.register_llm_request(ReplaceMessages(), allow_cache_invalidation=True)
    loop = _loop_for(root_messages, middleware=middleware)
    loop._turn_id = "offline-turn"
    loop._turn_state = TurnState(turn_id=loop._turn_id, messages=root_messages)
    loop._save_checkpoint = Mock()
    loop._afinalize_and_return = AsyncMock(side_effect=lambda result, *_args: result)
    summary = AsyncMock(return_value="root history summarized")
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
    turn = _phases.PreparedTurn(
        user_input="task",
        messages=root_messages,
        turn_state=loop._turn_state,
        system_prompt="",
        reflection_hint="",
        verification_hint="",
        verification_continuation=False,
    )
    call = _phases.PreparedModelCall(
        system_prompt="", spinner=SimpleNamespace(stop=lambda: None), ipc_writer=None
    )
    outcome = asyncio.run(_phases.call_provider(loop, turn, call, 0))
    assert outcome is not None and outcome.termination_reason == "context_exhausted"
    summary.assert_not_awaited()
    assert adapter.requests[0].messages == (Message(role="user", content="unrelated replacement"),)
    assert root_messages == original
    assert loop.context.messages == original
    loop._save_checkpoint.assert_not_called()


def test_auxiliary_failure_does_not_replace_root_history() -> None:
    root = [{"role": "user", "content": "physical root"}]
    loop = _loop_for(root, source="subscription")
    loop._new_adapter = _Adapter("subscription")
    loop._turn_id = "offline-turn"
    loop._turn_state = TurnState(turn_id=loop._turn_id, messages=root)
    auxiliary = [{"role": "user", "content": "x" * 1_000_000}]
    with pytest.raises(_ContextExhaustedError):
        asyncio.run(
            loop._call_llm("judge", auxiliary, allow_tools=False, purpose="turn_verification")
        )
    assert loop.context.messages == root == [{"role": "user", "content": "physical root"}]
    assert loop._turn_state.messages is root
