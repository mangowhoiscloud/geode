"""Fail-fast evaluator calls retain bounded side-effect-safe retries."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from core.agent.loop.agent_loop import (
    AgenticLoop,
    _acomplete_with_fail_fast_pre_execution_retry,
)
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


def test_agent_loop_exposes_current_run_retry_identity_as_an_immutable_view() -> None:
    loop = object.__new__(AgenticLoop)
    loop._pre_execution_retry_errors = ["ReadTimeout"]

    observed = loop.pre_execution_retry_errors
    loop._pre_execution_retry_errors.append("EmptyModelOutputError")

    assert observed == ("ReadTimeout",)
    assert loop.pre_execution_retry_errors == ("ReadTimeout", "EmptyModelOutputError")


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
    retried: list[tuple[Exception, int, int]] = []

    async def record_retry(exc: Exception, attempt: int, max_attempts: int) -> None:
        retried.append((exc, attempt, max_attempts))

    result = asyncio.run(
        _acomplete_with_fail_fast_pre_execution_retry(
            adapter,
            request,
            on_retry=record_retry,
        )
    )

    assert result is expected
    assert adapter.requests == [request, request]
    assert [(type(exc).__name__, attempt, maximum) for exc, attempt, maximum in retried] == [
        ("ReadTimeout", 2, 2)
    ]


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


def test_fail_fast_empty_output_recovers_after_two_identical_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    _no_delay(monkeypatch)
    request = object()
    expected = object()
    recovered: list[str] = []
    retries: list[tuple[int, int]] = []
    adapter = _Adapter(
        [
            EmptyModelOutputError(
                "first empty response",
                mark_recovered=lambda: recovered.append("first"),
            ),
            EmptyModelOutputError(
                "second empty response",
                mark_recovered=lambda: recovered.append("second"),
            ),
            expected,
        ]
    )

    async def record_retry(_exc: Exception, attempt: int, max_attempts: int) -> None:
        retries.append((attempt, max_attempts))

    result = asyncio.run(
        _acomplete_with_fail_fast_pre_execution_retry(
            adapter,
            request,
            on_retry=record_retry,
        )
    )

    assert result is expected
    assert adapter.requests == [request, request, request]
    assert recovered == ["first", "second"]
    assert retries == [(2, 3), (3, 3)]


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
    actionable: list[str] = []
    adapter = _Adapter(
        [
            EmptyModelOutputError(
                "first empty response",
                mark_recovered=lambda: recovered.append(True),
                mark_actionable=lambda: actionable.append("first"),
            ),
            EmptyModelOutputError(
                "second empty response",
                mark_actionable=lambda: actionable.append("second"),
            ),
            EmptyModelOutputError(
                "third empty response",
                mark_actionable=lambda: actionable.append("third"),
            ),
        ]
    )

    with pytest.raises(EmptyModelOutputError, match="third empty response") as error:
        asyncio.run(_acomplete_with_fail_fast_pre_execution_retry(adapter, object()))

    assert len(adapter.requests) == 3
    assert recovered == []
    error.value.mark_actionable()
    assert actionable == ["first", "second", "third"]


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


def test_empty_output_cannot_be_actionable_without_attestation() -> None:
    error = EmptyModelOutputError("unattested empty")

    with pytest.raises(RuntimeError, match="without a marker"):
        error.mark_actionable()


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
