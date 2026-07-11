"""Fail-fast evaluator calls retain one side-effect-safe transport retry."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from core.agent.loop.agent_loop import _acomplete_with_fail_fast_pre_execution_retry
from core.llm.adapters.base import EmptyModelOutputError


class _Adapter:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[object] = []

    async def acomplete(self, request: object) -> object:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    async def immediate(_delay: float) -> None:
        return None

    monkeypatch.setattr("core.agent.loop.agent_loop.asyncio.sleep", immediate)


def test_fail_fast_retries_one_read_timeout_with_the_identical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    _no_delay(monkeypatch)
    request = object()
    expected = object()
    adapter = _Adapter([httpx.ReadTimeout("stream stalled"), expected])
    retried: list[Exception] = []

    async def record_retry(exc: Exception) -> None:
        retried.append(exc)

    result = asyncio.run(
        _acomplete_with_fail_fast_pre_execution_retry(
            adapter,
            request,
            on_retry=record_retry,
        )
    )

    assert result is expected
    assert adapter.requests == [request, request]
    assert [type(exc).__name__ for exc in retried] == ["ReadTimeout"]


def test_fail_fast_retries_one_empty_model_output_with_the_identical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    _no_delay(monkeypatch)
    request = object()
    expected = object()
    recovered: list[bool] = []
    adapter = _Adapter(
        [
            EmptyModelOutputError(
                "reasoning-only response",
                mark_recovered=lambda: recovered.append(True),
            ),
            expected,
        ]
    )

    result = asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, request))

    assert result is expected
    assert adapter.requests == [request, request]
    assert recovered == [True]


def test_fail_fast_connection_retry_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "true")
    _no_delay(monkeypatch)
    adapter = _Adapter(
        [
            httpx.ReadTimeout("first stall"),
            httpx.ReadTimeout("second stall"),
        ]
    )

    with pytest.raises(httpx.ReadTimeout, match="second stall"):
        asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, object()))

    assert len(adapter.requests) == 2


def test_fail_fast_empty_output_retry_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "true")
    _no_delay(monkeypatch)
    recovered: list[bool] = []
    adapter = _Adapter(
        [
            EmptyModelOutputError(
                "first empty response",
                mark_recovered=lambda: recovered.append(True),
            ),
            EmptyModelOutputError("second empty response"),
        ]
    )

    with pytest.raises(EmptyModelOutputError, match="second empty response"):
        asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, object()))

    assert len(adapter.requests) == 2
    assert recovered == []


def test_fail_fast_empty_output_recovery_attestation_failure_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "true")
    _no_delay(monkeypatch)

    def fail_attestation() -> None:
        raise RuntimeError("marker write failed")

    adapter = _Adapter(
        [
            EmptyModelOutputError(
                "first empty response",
                mark_recovered=fail_attestation,
            ),
            object(),
        ]
    )

    with pytest.raises(RuntimeError, match="marker write failed"):
        asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, object()))

    assert len(adapter.requests) == 2


@pytest.mark.parametrize(
    ("fail_fast", "error"),
    [
        ("1", ValueError("schema mismatch")),
        ("", httpx.ReadTimeout("outer loop owns ordinary retries")),
        ("", EmptyModelOutputError("ordinary route owns empty output")),
    ],
)
def test_retry_requires_both_fail_fast_and_a_connection_error(
    monkeypatch: pytest.MonkeyPatch,
    fail_fast: str,
    error: Exception,
) -> None:
    if fail_fast:
        monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", fail_fast)
    else:
        monkeypatch.delenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", raising=False)
    adapter = _Adapter([error])

    with pytest.raises(type(error)):
        asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, object()))

    assert len(adapter.requests) == 1
