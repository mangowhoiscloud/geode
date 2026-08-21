"""Trusted request transforms and execution middleware.

Four typed join points are intentionally owned by one registry. Request
middleware composes N -> N+1; execution middleware forms an async onion around
the already-approved terminal call.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import inspect
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from core.hooks.system import RuntimeEvent, RuntimeEventBus
from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    LLMAdapter,
)
from core.observability.redaction import redact_secrets

log = logging.getLogger(__name__)

REQUEST_MIDDLEWARE_DEFAULT_TIMEOUT_S = 10.0
TOOL_EXECUTION_MIDDLEWARE_DEFAULT_TIMEOUT_S = 300.0
LLM_EXECUTION_MIDDLEWARE_DEFAULT_TIMEOUT_S = 900.0


class DuplicateMiddlewareError(ValueError):
    """Raised when a middleware name collides at one join point."""


class InvalidMiddlewareResultError(TypeError):
    """Raised when middleware returns the wrong request/result type."""


class NextCallAlreadyUsedError(RuntimeError):
    """Raised when one execution middleware calls ``next_call`` twice."""


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """Immutable tool invocation carried across both tool join points."""

    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    context: Any = None
    correlation: Mapping[str, Any] = field(default_factory=dict)

    def with_arguments(self, arguments: Mapping[str, Any]) -> ToolCallRequest:
        return replace(self, arguments=dict(arguments))


@dataclass(frozen=True, slots=True)
class LlmCallRequest:
    """Adapter identity plus the provider-agnostic request envelope."""

    adapter: LLMAdapter
    request: AdapterCallRequest
    correlation: Mapping[str, Any] = field(default_factory=dict)

    def with_request(self, request: AdapterCallRequest) -> LlmCallRequest:
        return replace(self, request=request)


ToolNextCall = Callable[[ToolCallRequest], Awaitable[dict[str, Any]]]
LlmNextCall = Callable[[LlmCallRequest], Awaitable[AdapterCallResult]]


class ToolRequestMiddleware(Protocol):
    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest: ...


class ToolExecutionMiddleware(Protocol):
    async def tool_execution(
        self,
        request: ToolCallRequest,
        next_call: ToolNextCall,
    ) -> dict[str, Any]: ...


class LlmRequestMiddleware(Protocol):
    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest: ...


class LlmExecutionMiddleware(Protocol):
    async def llm_execution(
        self,
        request: LlmCallRequest,
        next_call: LlmNextCall,
    ) -> AdapterCallResult: ...


@dataclass(frozen=True, slots=True)
class _Registration:
    middleware: Any
    name: str
    priority: int
    timeout_s: float
    capabilities: frozenset[str] = frozenset()


class MiddlewareRegistry:
    """Own registration and execution for the four trusted join points."""

    def __init__(self, *, events: RuntimeEventBus | None = None) -> None:
        self._events = events
        self._tool_request: list[_Registration] = []
        self._tool_execution: list[_Registration] = []
        self._llm_request: list[_Registration] = []
        self._llm_execution: list[_Registration] = []
        self._lock = threading.Lock()

    def register_tool_request(
        self,
        middleware: ToolRequestMiddleware,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout_s: float | None = None,
    ) -> None:
        self._register(
            self._tool_request,
            middleware,
            name=name,
            priority=priority,
            timeout_s=(REQUEST_MIDDLEWARE_DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s),
            capabilities=frozenset(),
        )

    def register_tool_execution(
        self,
        middleware: ToolExecutionMiddleware,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout_s: float | None = None,
    ) -> None:
        self._register(
            self._tool_execution,
            middleware,
            name=name,
            priority=priority,
            timeout_s=(
                TOOL_EXECUTION_MIDDLEWARE_DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
            ),
            capabilities=frozenset(),
        )

    def register_llm_request(
        self,
        middleware: LlmRequestMiddleware,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout_s: float | None = None,
        allow_cache_invalidation: bool = False,
    ) -> None:
        self._register(
            self._llm_request,
            middleware,
            name=name,
            priority=priority,
            timeout_s=(REQUEST_MIDDLEWARE_DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s),
            capabilities=(
                frozenset({"llm_cache_invalidation"}) if allow_cache_invalidation else frozenset()
            ),
        )

    def register_llm_execution(
        self,
        middleware: LlmExecutionMiddleware,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout_s: float | None = None,
    ) -> None:
        self._register(
            self._llm_execution,
            middleware,
            name=name,
            priority=priority,
            timeout_s=(
                LLM_EXECUTION_MIDDLEWARE_DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
            ),
            capabilities=frozenset(),
        )

    def _register(
        self,
        registrations: list[_Registration],
        middleware: Any,
        *,
        name: str | None,
        priority: int,
        timeout_s: float,
        capabilities: frozenset[str],
    ) -> None:
        middleware_name = name or str(getattr(middleware, "name", type(middleware).__name__))
        entry = _Registration(
            middleware=middleware,
            name=middleware_name,
            priority=priority,
            timeout_s=max(0.0, timeout_s),
            capabilities=capabilities,
        )
        with self._lock:
            if any(item.name == middleware_name for item in registrations):
                raise DuplicateMiddlewareError(
                    f"Middleware {middleware_name!r} is already registered at this join point"
                )
            registrations.append(entry)
            registrations.sort(key=lambda item: item.priority)

    async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
        current = _clone_tool_request(request)
        for registration in self._snapshot(self._tool_request):
            before = _request_hash(current)
            before_correlation = copy.deepcopy(dict(current.correlation))
            before_context = _physical_context_state(current.context)
            started = time.monotonic()
            try:
                result = await self._invoke(
                    registration,
                    "tool_request",
                    current,
                )
                if not isinstance(result, ToolCallRequest):
                    raise InvalidMiddlewareResultError(
                        f"{registration.name} returned {type(result).__name__}; "
                        "expected ToolCallRequest"
                    )
                if (
                    _request_hash(current) != before
                    or dict(current.correlation) != before_correlation
                    or _physical_context_state(current.context) != before_context
                ):
                    raise InvalidMiddlewareResultError(
                        f"{registration.name} mutated its immutable ToolCallRequest input "
                        "or physical correlation"
                    )
                current = replace(
                    result,
                    context=copy.copy(request.context),
                    correlation=copy.deepcopy(dict(request.correlation)),
                )
            except BaseException as exc:
                await self._record(
                    surface="tool_request",
                    registration=registration,
                    outcome="error",
                    reason=type(exc).__name__,
                    duration_ms=(time.monotonic() - started) * 1_000,
                    original_hash=before,
                    effective_hash=before,
                    correlation=request.correlation,
                )
                raise
            await self._record(
                surface="tool_request",
                registration=registration,
                outcome="ok",
                reason="",
                duration_ms=(time.monotonic() - started) * 1_000,
                original_hash=before,
                effective_hash=_request_hash(current),
                correlation=request.correlation,
            )
        return replace(
            current,
            context=request.context,
            correlation=copy.deepcopy(dict(request.correlation)),
        )

    async def llm_request(self, request: LlmCallRequest) -> LlmCallRequest:
        current = _clone_llm_request(request)
        for registration in self._snapshot(self._llm_request):
            before = _request_hash(current)
            before_correlation = copy.deepcopy(dict(current.correlation))
            started = time.monotonic()
            try:
                result = await self._invoke(
                    registration,
                    "llm_request",
                    current,
                )
                if not isinstance(result, LlmCallRequest):
                    raise InvalidMiddlewareResultError(
                        f"{registration.name} returned {type(result).__name__}; "
                        "expected LlmCallRequest"
                    )
                if (
                    _request_hash(current) != before
                    or dict(current.correlation) != before_correlation
                ):
                    raise InvalidMiddlewareResultError(
                        f"{registration.name} mutated its immutable LlmCallRequest input "
                        "or physical correlation"
                    )
                self._validate_llm_request_transform(
                    registration,
                    before_request=current,
                    after_request=result,
                )
                current = replace(
                    result,
                    correlation=copy.deepcopy(dict(request.correlation)),
                )
            except BaseException as exc:
                await self._record(
                    surface="llm_request",
                    registration=registration,
                    outcome="error",
                    reason=type(exc).__name__,
                    duration_ms=(time.monotonic() - started) * 1_000,
                    original_hash=before,
                    effective_hash=before,
                    correlation=request.correlation,
                )
                raise
            await self._record(
                surface="llm_request",
                registration=registration,
                outcome="ok",
                reason="",
                duration_ms=(time.monotonic() - started) * 1_000,
                original_hash=before,
                effective_hash=_request_hash(current),
                correlation=request.correlation,
            )
        return replace(current, correlation=copy.deepcopy(dict(request.correlation)))

    @staticmethod
    def _validate_llm_request_transform(
        registration: _Registration,
        *,
        before_request: LlmCallRequest,
        after_request: LlmCallRequest,
    ) -> None:
        before = before_request.request
        after = after_request.request
        cache_sensitive_changed = (
            before.system_prompt != after.system_prompt
            or before.messages != after.messages
            or before.tools != after.tools
        )
        if not cache_sensitive_changed:
            return
        if "llm_cache_invalidation" not in registration.capabilities:
            raise InvalidMiddlewareResultError(
                f"{registration.name} changed the cache-sensitive LLM prefix "
                "without allow_cache_invalidation=True"
            )
        reason = after.metadata.get("cache_invalidation_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidMiddlewareResultError(
                f"{registration.name} must set metadata.cache_invalidation_reason "
                "when changing the cache-sensitive LLM prefix"
            )

    async def tool_execution(
        self,
        request: ToolCallRequest,
        next_call: ToolNextCall,
    ) -> dict[str, Any]:
        registrations = self._snapshot(self._tool_execution)

        async def terminal(current: ToolCallRequest) -> dict[str, Any]:
            result = await next_call(current)
            if not isinstance(result, dict):
                raise InvalidMiddlewareResultError(
                    f"Tool terminal returned {type(result).__name__}; expected dict"
                )
            return result

        call = terminal
        for registration in reversed(registrations):
            downstream = call

            async def wrapped(
                current: ToolCallRequest,
                *,
                _registration: _Registration = registration,
                _downstream: ToolNextCall = downstream,
            ) -> dict[str, Any]:
                return await self._invoke_tool_execution(
                    _registration,
                    current,
                    _downstream,
                )

            call = wrapped
        return await call(request)

    async def llm_execution(
        self,
        request: LlmCallRequest,
        next_call: LlmNextCall,
    ) -> AdapterCallResult:
        registrations = self._snapshot(self._llm_execution)

        async def terminal(current: LlmCallRequest) -> AdapterCallResult:
            return await next_call(current)

        call = terminal
        for registration in reversed(registrations):
            downstream = call

            async def wrapped(
                current: LlmCallRequest,
                *,
                _registration: _Registration = registration,
                _downstream: LlmNextCall = downstream,
            ) -> AdapterCallResult:
                return await self._invoke_llm_execution(
                    _registration,
                    current,
                    _downstream,
                )

            call = wrapped
        return await call(request)

    async def call_llm(
        self,
        adapter: LLMAdapter,
        request: AdapterCallRequest,
        *,
        correlation: Mapping[str, Any] | None = None,
    ) -> AdapterCallResult:
        """Run both LLM join points around one ``adapter.acomplete`` call."""
        transformed = await self.llm_request(
            LlmCallRequest(
                adapter=adapter,
                request=request,
                correlation=dict(correlation or {}),
            )
        )

        async def execute(current: LlmCallRequest) -> AdapterCallResult:
            return await current.adapter.acomplete(current.request)

        return await self.llm_execution(transformed, execute)

    async def _invoke_tool_execution(
        self,
        registration: _Registration,
        request: ToolCallRequest,
        downstream: ToolNextCall,
    ) -> dict[str, Any]:
        used = False
        downstream_result: dict[str, Any] | None = None
        before = _request_hash(request)
        before_correlation = copy.deepcopy(dict(request.correlation))
        before_context = _physical_context_state(request.context)

        async def next_once(current: ToolCallRequest) -> dict[str, Any]:
            nonlocal downstream_result, used
            if used:
                raise NextCallAlreadyUsedError(
                    f"{registration.name} called tool next_call more than once"
                )
            used = True
            if not isinstance(current, ToolCallRequest):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} passed {type(current).__name__} to next_call; "
                    "expected ToolCallRequest"
                )
            if (
                current.context is not request.context
                or dict(current.correlation) != before_correlation
                or _physical_context_state(current.context) != before_context
                or _request_hash(current) != before
            ):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} changed the request at tool_execution; "
                    "use tool_request for transforms"
                )
            downstream_result = await downstream(current)
            return downstream_result

        started = time.monotonic()
        try:
            result = await self._invoke(
                registration,
                "tool_execution",
                request,
                next_once,
            )
            if not isinstance(result, dict):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} returned {type(result).__name__}; expected dict"
                )
            if (
                _request_hash(request) != before
                or dict(request.correlation) != before_correlation
                or _physical_context_state(request.context) != before_context
            ):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} mutated the request at tool_execution; "
                    "use tool_request for transforms"
                )
        except BaseException as exc:
            _restore_physical_context(request.context, before_context)
            _restore_correlation(request.correlation, before_correlation)
            await self._record(
                surface="tool_execution",
                registration=registration,
                outcome="error",
                reason=type(exc).__name__,
                duration_ms=(time.monotonic() - started) * 1_000,
                original_hash=before,
                effective_hash=before,
                correlation=before_correlation,
            )
            if (
                used
                and downstream_result is not None
                and not isinstance(exc, NextCallAlreadyUsedError)
            ):
                log.warning(
                    "Tool execution middleware %s failed after next_call; "
                    "preserving the completed downstream result to prevent replay",
                    registration.name,
                    exc_info=True,
                )
                return downstream_result
            raise
        await self._record(
            surface="tool_execution",
            registration=registration,
            outcome="called_next" if used else "short_circuit",
            reason="",
            duration_ms=(time.monotonic() - started) * 1_000,
            original_hash=before,
            effective_hash=before,
            correlation=before_correlation,
        )
        return result

    async def _invoke_llm_execution(
        self,
        registration: _Registration,
        request: LlmCallRequest,
        downstream: LlmNextCall,
    ) -> AdapterCallResult:
        used = False
        downstream_result: AdapterCallResult | None = None
        before = _request_hash(request)
        before_correlation = copy.deepcopy(dict(request.correlation))

        async def next_once(current: LlmCallRequest) -> AdapterCallResult:
            nonlocal downstream_result, used
            if used:
                raise NextCallAlreadyUsedError(
                    f"{registration.name} called LLM next_call more than once"
                )
            used = True
            if not isinstance(current, LlmCallRequest):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} passed {type(current).__name__} to next_call; "
                    "expected LlmCallRequest"
                )
            if (
                current.adapter is not request.adapter
                or dict(current.correlation) != before_correlation
                or _request_hash(current) != before
            ):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} changed the request at llm_execution; "
                    "use llm_request for transforms"
                )
            downstream_result = await downstream(current)
            return downstream_result

        started = time.monotonic()
        try:
            result = await self._invoke(
                registration,
                "llm_execution",
                request,
                next_once,
            )
            if not isinstance(result, AdapterCallResult):
                raise InvalidMiddlewareResultError(
                    f"{registration.name} returned {type(result).__name__}; "
                    "expected AdapterCallResult"
                )
            if _request_hash(request) != before or dict(request.correlation) != before_correlation:
                raise InvalidMiddlewareResultError(
                    f"{registration.name} mutated the request at llm_execution; "
                    "use llm_request for transforms"
                )
        except BaseException as exc:
            _restore_correlation(request.correlation, before_correlation)
            await self._record(
                surface="llm_execution",
                registration=registration,
                outcome="error",
                reason=type(exc).__name__,
                duration_ms=(time.monotonic() - started) * 1_000,
                original_hash=before,
                effective_hash=before,
                correlation=before_correlation,
            )
            if (
                used
                and downstream_result is not None
                and not isinstance(exc, NextCallAlreadyUsedError)
            ):
                log.warning(
                    "LLM execution middleware %s failed after next_call; "
                    "preserving the completed provider result to prevent rebilling",
                    registration.name,
                    exc_info=True,
                )
                return downstream_result
            raise
        await self._record(
            surface="llm_execution",
            registration=registration,
            outcome="called_next" if used else "short_circuit",
            reason="",
            duration_ms=(time.monotonic() - started) * 1_000,
            original_hash=before,
            effective_hash=before,
            correlation=before_correlation,
        )
        return result

    @staticmethod
    async def _invoke(
        registration: _Registration,
        method_name: str,
        *args: Any,
    ) -> Any:
        method = getattr(registration.middleware, method_name, None)
        if not callable(method):
            raise TypeError(f"{registration.name} does not implement {method_name}()")

        async def run() -> Any:
            value = method(*args)
            if inspect.isawaitable(value):
                return await value
            return value

        if registration.timeout_s <= 0:
            return await run()
        return await asyncio.wait_for(run(), timeout=registration.timeout_s)

    def _snapshot(self, registrations: list[_Registration]) -> tuple[_Registration, ...]:
        with self._lock:
            return tuple(registrations)

    async def _record(
        self,
        *,
        surface: str,
        registration: _Registration,
        outcome: str,
        reason: str,
        duration_ms: float,
        original_hash: str,
        effective_hash: str,
        correlation: Mapping[str, Any],
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.emit_async(
                RuntimeEvent.EXTENSION_INVOKED,
                {
                    "surface": surface,
                    "name": registration.name,
                    "extension": registration.name,
                    "status": outcome,
                    "reason": redact_secrets(reason)[:512],
                    "duration_ms": round(duration_ms, 3),
                    "original_hash": original_hash,
                    "effective_hash": effective_hash,
                    "session_id": str(correlation.get("session_id", "")),
                    "turn_id": str(correlation.get("turn_id", "")),
                    "step_id": str(correlation.get("step_id", "")),
                    "run_id": str(correlation.get("run_id", "")),
                    "session_generation": int(correlation.get("session_generation", 0) or 0),
                    "verify_attempt": int(correlation.get("verify_attempt", 0) or 0),
                    "tool_call_id": str(correlation.get("tool_call_id", "")),
                    "llm_call_id": str(correlation.get("llm_call_id", "")),
                    "llm_attempt_id": str(correlation.get("llm_attempt_id", "")),
                },
            )
        except Exception:
            log.warning(
                "Middleware invocation telemetry failed for %s/%s",
                surface,
                registration.name,
                exc_info=True,
            )


def _request_hash(request: ToolCallRequest | LlmCallRequest) -> str:
    if isinstance(request, ToolCallRequest):
        value: Any = {
            "tool_name": request.tool_name,
            "arguments": request.arguments,
        }
    else:
        value = {
            "adapter": {
                "name": getattr(request.adapter, "name", ""),
                "provider": getattr(request.adapter, "provider", ""),
                "source": getattr(request.adapter, "source", ""),
            },
            "request": dataclasses.asdict(request.request),
        }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clone_tool_request(request: ToolCallRequest) -> ToolCallRequest:
    return replace(
        request,
        arguments=copy.deepcopy(dict(request.arguments)),
        context=copy.copy(request.context),
        correlation=copy.deepcopy(dict(request.correlation)),
    )


def _clone_llm_request(request: LlmCallRequest) -> LlmCallRequest:
    return replace(
        request,
        request=copy.deepcopy(request.request),
        correlation=copy.deepcopy(dict(request.correlation)),
    )


_PHYSICAL_CONTEXT_FIELDS = (
    "session_id",
    "turn_id",
    "step_id",
    "session_generation",
    "verify_attempt",
    "tool_call_id",
    "provider",
    "source",
    "model",
    "adapter_name",
    "tool_plan_hash",
    "tool_plan_generation",
    "bound_tool_plan",
)


def _physical_context_state(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(context, name, None) for name in _PHYSICAL_CONTEXT_FIELDS)


def _restore_physical_context(context: Any, state: tuple[Any, ...]) -> None:
    for name, value in zip(_PHYSICAL_CONTEXT_FIELDS, state, strict=True):
        with suppress(AttributeError, TypeError):
            setattr(context, name, value)


def _restore_correlation(
    correlation: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    if isinstance(correlation, MutableMapping):
        correlation.clear()
        correlation.update(copy.deepcopy(dict(state)))


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return {"_type": type(value).__name__}


__all__ = [
    "DuplicateMiddlewareError",
    "InvalidMiddlewareResultError",
    "LlmCallRequest",
    "LlmExecutionMiddleware",
    "LlmRequestMiddleware",
    "MiddlewareRegistry",
    "NextCallAlreadyUsedError",
    "ToolCallRequest",
    "ToolExecutionMiddleware",
    "ToolRequestMiddleware",
]
