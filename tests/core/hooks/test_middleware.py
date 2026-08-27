from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import wraps
from typing import Any, cast

import pytest
from core.hooks import (
    InvalidMiddlewareResultError,
    LlmCallRequest,
    MiddlewareRegistry,
    NextCallAlreadyUsedError,
    ToolCallRequest,
)
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    LLMAdapter,
    UsageSummary,
)


def _async_test(func: Callable[[], Awaitable[None]]) -> Callable[[], None]:
    @wraps(func)
    def run() -> None:
        asyncio.run(func())

    return run


class _ToolRename:
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix

    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
        return request.with_arguments(
            {"value": f"{request.arguments.get('value', '')}{self.suffix}"}
        )


class _ToolExecution:
    def __init__(self, label: str, order: list[str]) -> None:
        self.label = label
        self.order = order

    async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
        self.order.append(f"{self.label}:in")
        result = await next_call(request)
        self.order.append(f"{self.label}:out")
        return result


class _DoubleNext:
    async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
        await next_call(request)
        return await next_call(request)


class _ShortCircuit:
    async def tool_execution(self, _request: ToolCallRequest, _next_call: Any) -> dict[str, Any]:
        return {"short": True}


class _ToolExecutionTransform:
    async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
        return await next_call(request.with_arguments({"value": "changed"}))


class _LlmRequest:
    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
        return request.with_request(replace(request.request, model="changed"))


class _CacheSensitiveLlmRequest:
    def __init__(self, *, reason: str = "") -> None:
        self.reason = reason

    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
        metadata = dict(request.request.metadata)
        if self.reason:
            metadata["cache_invalidation_reason"] = self.reason
        return request.with_request(
            replace(
                request.request,
                system_prompt=f"{request.request.system_prompt} changed",
                metadata=metadata,
            )
        )


class _MutatingToolRequest:
    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
        cast(dict[str, Any], request.arguments)["value"] = "mutated"
        return request


class _LlmExecution:
    async def llm_execution(self, request: LlmCallRequest, next_call: Any) -> AdapterCallResult:
        result = await next_call(request)
        return replace(result, text=f"[{result.text}]")


class _LlmExecutionTransform:
    async def llm_execution(
        self,
        request: LlmCallRequest,
        next_call: Any,
    ) -> AdapterCallResult:
        return await next_call(request.with_request(replace(request.request, model="changed")))


class _CancelAfterNext:
    def __init__(self, entered: asyncio.Event) -> None:
        self.entered = entered

    async def _wait(self, result: Any) -> Any:
        self.entered.set()
        await asyncio.sleep(3600)
        return result

    async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
        return cast(dict[str, Any], await self._wait(await next_call(request)))

    async def llm_execution(
        self,
        request: LlmCallRequest,
        next_call: Any,
    ) -> AdapterCallResult:
        return cast(AdapterCallResult, await self._wait(await next_call(request)))


class _Adapter:
    name = "fake"
    provider = "fake"
    source = "adapter"
    billing_type = AdapterBillingType.FIXED

    def __init__(self) -> None:
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(req)
        return AdapterCallResult(
            text=req.model,
            usage=UsageSummary(),
            stop_reason="end_turn",
        )


@_async_test
async def test_tool_request_middleware_composes_n_to_n_plus_one() -> None:
    registry = MiddlewareRegistry()
    registry.register_tool_request(_ToolRename("-a"), name="a")
    registry.register_tool_request(_ToolRename("-b"), name="b")

    result = await registry.tool_request(
        ToolCallRequest(tool_name="demo", arguments={"value": "start"})
    )

    assert result.arguments == {"value": "start-a-b"}


@_async_test
async def test_request_transforms_preserve_physical_correlation() -> None:
    class RebuildToolRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return ToolCallRequest(request.tool_name, request.arguments)

    class RebuildLlmRequest:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            return LlmCallRequest(request.adapter, request.request)

    registry = MiddlewareRegistry()
    registry.register_tool_request(RebuildToolRequest())
    registry.register_llm_request(RebuildLlmRequest())
    context = object()
    correlation = {"step_id": "turn-1:step-1"}

    tool = await registry.tool_request(
        ToolCallRequest("demo", context=context, correlation=correlation)
    )
    llm = await registry.llm_request(
        LlmCallRequest(
            cast(LLMAdapter, _Adapter()),
            AdapterCallRequest(model="model", messages=()),
            correlation,
        )
    )

    assert tool.context is context
    assert tool.correlation == correlation
    assert llm.correlation == correlation


@_async_test
async def test_request_middleware_rejects_in_place_physical_correlation_mutation() -> None:
    class Context:
        step_id = "turn-1:step-1"

    class MutateToolCorrelation:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            cast(dict[str, Any], request.correlation)["step_id"] = "spoofed"
            request.context.step_id = "spoofed-context"
            return request

    class MutateLlmCorrelation:
        async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
            cast(dict[str, Any], request.correlation)["step_id"] = "spoofed"
            return request

    context = Context()
    correlation = {"step_id": "turn-1:step-1"}
    tool_registry = MiddlewareRegistry()
    tool_registry.register_tool_request(MutateToolCorrelation())
    llm_registry = MiddlewareRegistry()
    llm_registry.register_llm_request(MutateLlmCorrelation())

    with pytest.raises(InvalidMiddlewareResultError, match="physical correlation"):
        await tool_registry.tool_request(
            ToolCallRequest("demo", context=context, correlation=correlation)
        )
    with pytest.raises(InvalidMiddlewareResultError, match="physical correlation"):
        await llm_registry.llm_request(
            LlmCallRequest(
                cast(LLMAdapter, _Adapter()),
                AdapterCallRequest(model="model", messages=()),
                correlation,
            )
        )

    assert context.step_id == "turn-1:step-1"
    assert correlation == {"step_id": "turn-1:step-1"}


@_async_test
async def test_tool_execution_is_an_onion_and_terminal_runs_once() -> None:
    order: list[str] = []
    registry = MiddlewareRegistry()
    registry.register_tool_execution(_ToolExecution("a", order), name="a")
    registry.register_tool_execution(_ToolExecution("b", order), name="b")
    terminal_calls = 0

    async def terminal(request: ToolCallRequest) -> dict[str, Any]:
        nonlocal terminal_calls
        terminal_calls += 1
        order.append("terminal")
        return {"arguments": dict(request.arguments)}

    result = await registry.tool_execution(
        ToolCallRequest(tool_name="demo", arguments={"value": 1}),
        terminal,
    )

    assert result == {"arguments": {"value": 1}}
    assert terminal_calls == 1
    assert order == ["a:in", "b:in", "terminal", "b:out", "a:out"]


@_async_test
async def test_execution_next_call_is_single_use() -> None:
    registry = MiddlewareRegistry()
    registry.register_tool_execution(_DoubleNext(), name="double")

    async def terminal(_request: ToolCallRequest) -> dict[str, Any]:
        return {"ok": True}

    with pytest.raises(NextCallAlreadyUsedError):
        await registry.tool_execution(ToolCallRequest(tool_name="demo"), terminal)


@_async_test
async def test_execution_middleware_rejects_in_place_identity_mutation() -> None:
    class Context:
        step_id = "turn-1:step-1"

    class MutateToolIdentity:
        async def tool_execution(self, request: ToolCallRequest, next_call: Any) -> dict[str, Any]:
            cast(dict[str, Any], request.correlation)["step_id"] = "spoofed"
            request.context.step_id = "spoofed-context"
            return await next_call(request)

    class MutateLlmIdentity:
        async def llm_execution(
            self,
            request: LlmCallRequest,
            next_call: Any,
        ) -> AdapterCallResult:
            cast(dict[str, Any], request.correlation)["step_id"] = "spoofed"
            return await next_call(request)

    context = Context()
    tool_registry = MiddlewareRegistry()
    tool_registry.register_tool_execution(MutateToolIdentity())
    llm_registry = MiddlewareRegistry()
    llm_registry.register_llm_execution(MutateLlmIdentity())
    tool_correlation = {"step_id": "turn-1:step-1"}
    llm_correlation = {"step_id": "turn-1:step-1"}

    with pytest.raises(InvalidMiddlewareResultError, match="tool_execution"):
        await tool_registry.tool_execution(
            ToolCallRequest(
                "demo",
                context=context,
                correlation=tool_correlation,
            ),
            lambda _request: pytest.fail("mutated tool identity reached the terminal"),
        )
    with pytest.raises(InvalidMiddlewareResultError, match="llm_execution"):
        await llm_registry.llm_execution(
            LlmCallRequest(
                cast(LLMAdapter, _Adapter()),
                AdapterCallRequest(model="model", messages=()),
                llm_correlation,
            ),
            lambda _request: pytest.fail("mutated LLM identity reached the terminal"),
        )
    assert context.step_id == "turn-1:step-1"
    assert tool_correlation == {"step_id": "turn-1:step-1"}
    assert llm_correlation == {"step_id": "turn-1:step-1"}


@_async_test
async def test_short_circuit_does_not_call_terminal() -> None:
    registry = MiddlewareRegistry()
    registry.register_tool_execution(_ShortCircuit(), name="short")
    terminal_called = False

    async def terminal(_request: ToolCallRequest) -> dict[str, Any]:
        nonlocal terminal_called
        terminal_called = True
        return {"ok": True}

    result = await registry.tool_execution(ToolCallRequest(tool_name="demo"), terminal)

    assert result == {"short": True}
    assert terminal_called is False


@_async_test
async def test_tool_execution_cannot_transform_an_approved_request() -> None:
    registry = MiddlewareRegistry()
    registry.register_tool_execution(_ToolExecutionTransform(), name="transform")

    async def terminal(_request: ToolCallRequest) -> dict[str, Any]:
        return {"ok": True}

    with pytest.raises(InvalidMiddlewareResultError, match="use tool_request"):
        await registry.tool_execution(
            ToolCallRequest(tool_name="demo", arguments={"value": "original"}),
            terminal,
        )


@_async_test
async def test_downstream_exception_identity_is_preserved() -> None:
    registry = MiddlewareRegistry()
    order: list[str] = []
    registry.register_tool_execution(_ToolExecution("a", order), name="a")
    expected = RuntimeError("terminal failed")

    async def terminal(_request: ToolCallRequest) -> dict[str, Any]:
        raise expected

    with pytest.raises(RuntimeError) as caught:
        await registry.tool_execution(ToolCallRequest(tool_name="demo"), terminal)

    assert caught.value is expected


@_async_test
async def test_cancellation_identity_is_preserved() -> None:
    registry = MiddlewareRegistry()
    order: list[str] = []
    registry.register_tool_execution(_ToolExecution("a", order), name="a")
    expected = asyncio.CancelledError("cancelled")

    async def terminal(_request: ToolCallRequest) -> dict[str, Any]:
        raise expected

    with pytest.raises(asyncio.CancelledError) as caught:
        await registry.tool_execution(ToolCallRequest(tool_name="demo"), terminal)

    assert caught.value is expected


@_async_test
async def test_cancellation_after_next_call_is_not_converted_to_success() -> None:
    async def assert_cancelled(awaitable: Awaitable[Any], entered: asyncio.Event) -> None:
        task = asyncio.create_task(awaitable)
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    tool_entered = asyncio.Event()
    tool_registry = MiddlewareRegistry()
    tool_registry.register_tool_execution(_CancelAfterNext(tool_entered))
    await assert_cancelled(
        tool_registry.tool_execution(
            ToolCallRequest(tool_name="demo"),
            lambda _request: asyncio.sleep(0, result={"ok": True}),
        ),
        tool_entered,
    )

    llm_entered = asyncio.Event()
    llm_registry = MiddlewareRegistry()
    llm_registry.register_llm_execution(_CancelAfterNext(llm_entered))
    await assert_cancelled(
        llm_registry.call_llm(
            cast(LLMAdapter, _Adapter()),
            AdapterCallRequest(model="model", messages=()),
        ),
        llm_entered,
    )


@_async_test
async def test_request_input_mutation_is_rejected_and_original_survives() -> None:
    registry = MiddlewareRegistry()
    registry.register_tool_request(_MutatingToolRequest(), name="mutator")
    original = ToolCallRequest(tool_name="demo", arguments={"value": "original"})

    with pytest.raises(InvalidMiddlewareResultError, match="mutated its immutable"):
        await registry.tool_request(original)

    assert original.arguments == {"value": "original"}


@_async_test
async def test_call_llm_runs_request_and_execution_join_points() -> None:
    registry = MiddlewareRegistry()
    registry.register_llm_request(_LlmRequest(), name="request")
    registry.register_llm_execution(_LlmExecution(), name="execution")
    adapter = _Adapter()

    result = await registry.call_llm(
        cast(LLMAdapter, adapter),
        AdapterCallRequest(model="original", messages=()),
    )

    assert adapter.requests[0].model == "changed"
    assert result.text == "[changed]"


@_async_test
async def test_llm_execution_cannot_transform_the_adapter_request() -> None:
    registry = MiddlewareRegistry()
    registry.register_llm_execution(_LlmExecutionTransform(), name="transform")
    adapter = _Adapter()

    with pytest.raises(InvalidMiddlewareResultError, match="use llm_request"):
        await registry.llm_execution(
            LlmCallRequest(
                adapter=cast(LLMAdapter, adapter),
                request=AdapterCallRequest(model="original", messages=()),
            ),
            lambda request: request.adapter.acomplete(request.request),
        )


@_async_test
async def test_llm_cache_sensitive_change_requires_capability() -> None:
    registry = MiddlewareRegistry()
    registry.register_llm_request(_CacheSensitiveLlmRequest(reason="policy"), name="cache")

    with pytest.raises(InvalidMiddlewareResultError, match="allow_cache_invalidation"):
        await registry.llm_request(
            LlmCallRequest(
                adapter=cast(LLMAdapter, _Adapter()),
                request=AdapterCallRequest(
                    model="model",
                    messages=(),
                    system_prompt="system",
                ),
            )
        )


@_async_test
async def test_llm_cache_sensitive_change_requires_reason() -> None:
    registry = MiddlewareRegistry()
    registry.register_llm_request(
        _CacheSensitiveLlmRequest(),
        name="cache",
        allow_cache_invalidation=True,
    )

    with pytest.raises(InvalidMiddlewareResultError, match="cache_invalidation_reason"):
        await registry.llm_request(
            LlmCallRequest(
                adapter=cast(LLMAdapter, _Adapter()),
                request=AdapterCallRequest(
                    model="model",
                    messages=(),
                    system_prompt="system",
                ),
            )
        )


@_async_test
async def test_llm_cache_sensitive_change_with_capability_and_reason() -> None:
    registry = MiddlewareRegistry()
    registry.register_llm_request(
        _CacheSensitiveLlmRequest(reason="project policy changed"),
        name="cache",
        allow_cache_invalidation=True,
    )

    transformed = await registry.llm_request(
        LlmCallRequest(
            adapter=cast(LLMAdapter, _Adapter()),
            request=AdapterCallRequest(
                model="model",
                messages=(),
                system_prompt="system",
            ),
        )
    )

    assert transformed.request.system_prompt == "system changed"
    assert transformed.request.metadata["cache_invalidation_reason"] == "project policy changed"
