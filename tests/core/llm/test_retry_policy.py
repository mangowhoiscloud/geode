"""R5.4 explicit retry-policy and shared-runner contracts."""

from __future__ import annotations

import asyncio
import email.utils
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import anthropic
import httpx
import openai
import pytest
from core.llm.errors import BillingError
from core.llm.fallback import (
    RetryAction,
    RetryPolicy,
    auxiliary_retry_policy,
    classify_retry_error,
    interactive_retry_policy,
    provider_retry_policy,
    retry_delay_for,
    run_with_retry_policy,
)
from core.llm.router import call_with_failover


class _RateLimitError(Exception):
    status_code = 429

    def __init__(self, message: str = "busy", *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.response = SimpleNamespace(headers=headers or {})


def test_policy_rejects_overlapping_category_actions() -> None:
    with pytest.raises(ValueError, match="conflicting categories"):
        RetryPolicy(
            name="invalid",
            max_attempts=1,
            base_delay_s=0.0,
            max_delay_s=0.0,
            jitter=False,
            retry_categories=frozenset({"rate_limit"}),
            terminal_categories=frozenset({"rate_limit"}),
        )


def test_interactive_policy_retries_transient_quota_with_jitter() -> None:
    policy = interactive_retry_policy(max_attempts=5)

    assert policy.action_for("rate_limit") is RetryAction.RETRY
    assert policy.action_for("connection") is RetryAction.RETRY
    with patch("core.llm.fallback.random.uniform", return_value=1.25):
        assert policy.delay_for(1) == 1.25


def test_interactive_policy_reads_shared_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.config.settings.llm_max_retries", 4)
    monkeypatch.setattr("core.config.settings.llm_retry_base_delay", 1.5)
    monkeypatch.setattr("core.config.settings.llm_retry_max_delay", 9.0)

    policy = interactive_retry_policy()

    assert (policy.max_attempts, policy.base_delay_s, policy.max_delay_s) == (4, 1.5, 9.0)


def test_backoff_caps_without_overflow() -> None:
    policy = interactive_retry_policy(
        max_attempts=1,
        base_delay_s=2.0,
        max_delay_s=30.0,
    )

    with patch("core.llm.fallback.random.uniform", side_effect=lambda _low, high: high):
        assert policy.delay_for(100_000) == 30.0


@pytest.mark.parametrize(("status", "expected"), [(408, "timeout"), (409, "server")])
def test_http_retry_statuses_follow_stainless_contract(status: int, expected: str) -> None:
    error = _RateLimitError()
    error.status_code = status

    assert classify_retry_error(error) == expected


@pytest.mark.parametrize("status", [403, 404, 422])
def test_wrapped_permanent_rejection_cannot_enable_retry(status: int) -> None:
    cause = httpx.HTTPStatusError(
        "Request 401-example rejected",
        request=httpx.Request("POST", "https://example.invalid"),
        response=httpx.Response(status, headers={"x-should-retry": "true"}),
    )
    wrapped = RuntimeError("adapter failed")
    wrapped.__cause__ = cause

    assert classify_retry_error(wrapped) == "bad_request"


@pytest.mark.parametrize("sdk_name", ["anthropic", "openai"])
@pytest.mark.parametrize("status", [403, 404, 422])
@pytest.mark.parametrize("policy_name", ["interactive", "provider", "auxiliary"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_permanent_sdk_http_rejection_stops_without_retry_or_refresh(
    sdk_name: str, status: int, policy_name: str, wrapped: bool
) -> None:
    async def exercise() -> None:
        calls: list[str] = []

        def reject(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(
                status,
                json={
                    "error": {
                        "type": "permission_error" if status == 403 else "invalid_request_error",
                        "message": "Resource access rejected",
                    }
                },
                headers={"x-should-retry": "true"},
            )

        policy = {
            "interactive": interactive_retry_policy,
            "provider": provider_retry_policy,
            "auxiliary": auxiliary_retry_policy,
        }[policy_name](max_attempts=3)
        sdk = anthropic if sdk_name == "anthropic" else openai
        client_type = anthropic.AsyncAnthropic if sdk_name == "anthropic" else openai.AsyncOpenAI
        on_retry = AsyncMock()
        # Refresh is a synchronous owner operation; accepting it would prove an unwanted replay.
        refresh_owner = Mock(return_value=True)
        async with client_type(
            api_key="synthetic-test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject)),
        ) as client:

            async def call(model: str):
                try:
                    if isinstance(client, anthropic.AsyncAnthropic):
                        return await client.messages.create(
                            model=model,
                            max_tokens=8,
                            messages=[{"role": "user", "content": "test"}],
                        )
                    return await client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": "test"}]
                    )
                except sdk.APIStatusError as exc:
                    if wrapped:
                        raise sdk.APIConnectionError(request=exc.request) from exc
                    raise

            with (
                patch("core.config.is_model_allowed", return_value=True),
                patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep,
                pytest.raises(sdk.APIConnectionError if wrapped else sdk.APIStatusError) as caught,
            ):
                await run_with_retry_policy(
                    ["model-a", "model-b"],
                    call,
                    policy=policy,
                    refresh_auth=refresh_owner,
                    on_retry=on_retry,
                )

        http_error = caught.value.__cause__ if wrapped else caught.value
        assert http_error.status_code == status
        assert len(calls) == 1
        refresh_owner.assert_not_called()
        on_retry.assert_not_called()
        sleep.assert_not_called()

    asyncio.run(exercise())


@pytest.mark.parametrize("sdk_name", ["anthropic", "openai"])
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, "bad_request"),
        (401, "auth"),
        (403, "bad_request"),
        (408, "timeout"),
        (409, "server"),
        (429, "rate_limit"),
    ],
)
def test_response_status_overrides_sdk_transport_wrapper(
    sdk_name: str, status: int, expected: str
) -> None:
    sdk = anthropic if sdk_name == "anthropic" else openai
    request = httpx.Request("POST", "https://example.invalid")
    wrapped = sdk.APIConnectionError(request=request)
    wrapped.__cause__ = httpx.HTTPStatusError(
        "Request rejected", request=request, response=httpx.Response(status, request=request)
    )

    assert classify_retry_error(wrapped) == expected


def test_http_status_preserves_overflow_and_local_replay_rejection() -> None:
    from core.llm.errors import StreamInterruptedError

    request = httpx.Request("POST", "https://example.invalid")
    overflow = openai.BadRequestError(
        "Request too large",
        response=httpx.Response(400, request=request),
        body={"code": "context_length_exceeded"},
    )
    interruption = StreamInterruptedError("visible output")
    interruption.__cause__ = httpx.HTTPStatusError(
        "Retryable response", request=request, response=httpx.Response(429, request=request)
    )
    wrapped = openai.APIConnectionError(request=request)
    wrapped.__cause__ = interruption

    assert classify_retry_error(overflow) == "context_overflow"
    assert classify_retry_error(interruption) == "stream_interrupted"
    assert classify_retry_error(wrapped) == "stream_interrupted"


def test_retry_delay_honors_server_lower_bound_and_cap() -> None:
    policy = RetryPolicy(
        name="test",
        max_attempts=2,
        base_delay_s=1.0,
        max_delay_s=1.0,
        jitter=False,
        retry_categories=frozenset({"rate_limit"}),
        terminal_categories=frozenset(),
    )

    assert (
        retry_delay_for(
            policy,
            1,
            _RateLimitError(headers={"retry-after-ms": "2500"}),
        )
        == 2.5
    )
    assert retry_delay_for(policy, 1, _RateLimitError(headers={"retry-after": "61"})) is None
    assert (
        retry_delay_for(
            policy,
            1,
            _RateLimitError(headers={"X-Should-Retry": "false"}),
        )
        is None
    )


def test_retry_delay_accepts_http_date() -> None:
    policy = RetryPolicy(
        name="test",
        max_attempts=2,
        base_delay_s=1.0,
        max_delay_s=1.0,
        jitter=False,
        retry_categories=frozenset({"rate_limit"}),
        terminal_categories=frozenset(),
    )
    now = 1_700_000_000.0
    error = _RateLimitError(headers={"retry-after": email.utils.formatdate(now + 10, usegmt=True)})

    with patch("core.llm.fallback.time.time", return_value=now):
        assert retry_delay_for(policy, 1, error) == 10.0


def test_server_retry_veto_stops_without_sleeping() -> None:
    attempted = 0

    async def call(_model: str) -> None:
        nonlocal attempted
        attempted += 1
        raise _RateLimitError(headers={"x-should-retry": "false"})

    with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep:
        outcome = asyncio.run(
            run_with_retry_policy(
                ["model"],
                call,
                policy=auxiliary_retry_policy(
                    max_attempts=3,
                    base_delay_s=0.0,
                    max_delay_s=0.0,
                ),
            )
        )

    assert outcome.succeeded is False
    assert attempted == 1
    sleep.assert_not_awaited()


def test_auxiliary_unknown_error_advances_to_next_model() -> None:
    attempted: list[str] = []

    async def call(model: str) -> str:
        attempted.append(model)
        if model == "primary":
            raise ValueError("unexpected response shape")
        return "ok"

    outcome = asyncio.run(
        run_with_retry_policy(
            ["primary", "secondary"],
            call,
            policy=auxiliary_retry_policy(
                max_attempts=3,
                base_delay_s=0.0,
                max_delay_s=0.0,
            ),
        )
    )

    assert outcome.succeeded is True
    assert (outcome.value, outcome.model) == ("ok", "secondary")
    assert attempted == ["primary", "secondary"]


def test_provider_unknown_error_remains_terminal() -> None:
    attempted: list[str] = []

    async def call(model: str) -> str:
        attempted.append(model)
        raise ValueError("unexpected response shape")

    with pytest.raises(ValueError, match="unexpected response shape"):
        asyncio.run(
            run_with_retry_policy(
                ["primary", "secondary"],
                call,
                policy=provider_retry_policy(
                    max_attempts=3,
                    base_delay_s=0.0,
                    max_delay_s=0.0,
                ),
            )
        )

    assert attempted == ["primary"]


def test_only_auxiliary_policy_filters_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.config.is_model_allowed", lambda _model: False)
    attempted: list[str] = []

    async def call(model: str) -> str:
        attempted.append(model)
        return "ok"

    auxiliary = asyncio.run(
        run_with_retry_policy(
            ["blocked"],
            call,
            policy=auxiliary_retry_policy(
                max_attempts=1,
                base_delay_s=0.0,
                max_delay_s=0.0,
            ),
        )
    )
    provider = asyncio.run(
        run_with_retry_policy(
            ["blocked"],
            call,
            policy=provider_retry_policy(
                max_attempts=1,
                base_delay_s=0.0,
                max_delay_s=0.0,
            ),
        )
    )

    assert auxiliary.succeeded is False
    assert provider.succeeded is True
    assert attempted == ["blocked"]


def test_failover_rejects_policy_that_disables_model_filtering() -> None:
    async def call(_model: str) -> str:
        return "unreachable"

    with pytest.raises(ValueError, match="requires model filtering"):
        asyncio.run(
            call_with_failover(
                ["blocked"],
                call,
                policy=provider_retry_policy(
                    max_attempts=1,
                    base_delay_s=0.0,
                    max_delay_s=0.0,
                ),
            )
        )


def test_wrapped_billing_cause_remains_terminal() -> None:
    class APIConnectionError(Exception):
        pass

    wrapped = APIConnectionError("transport wrapper")
    wrapped.__cause__ = BillingError("quota exhausted", provider="anthropic")

    assert classify_retry_error(wrapped) == "billing"


def test_wrapped_auth_and_request_errors_remain_terminal() -> None:
    class AuthenticationError(Exception):
        pass

    class BadRequestError(Exception):
        status_code = 400

    wrapped_auth = RuntimeError("adapter wrapper")
    wrapped_auth.__cause__ = AuthenticationError("invalid credential")
    wrapped_request = RuntimeError("adapter wrapper")
    wrapped_request.__cause__ = BadRequestError("Unsupported parameter: max_output_tokens")

    assert classify_retry_error(wrapped_auth) == "auth"
    assert classify_retry_error(wrapped_request) == "bad_request"


def test_wrapped_response_status_is_classified() -> None:
    class ResponseError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("provider response")
            self.response = SimpleNamespace(status_code=429, headers={})

    cause = ResponseError()
    wrapped = RuntimeError("adapter wrapper")
    wrapped.__cause__ = cause

    assert classify_retry_error(wrapped) == "rate_limit"


def test_anthropic_credit_bad_request_remains_billing() -> None:
    error = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
    error.args = ("Your credit balance is too low to access the Anthropic API",)
    error.status_code = 400

    assert (
        classify_retry_error(
            error,
            compatibility_bad_request_error=anthropic.BadRequestError,
        )
        == "billing"
    )


def test_sdk_timeout_retains_timeout_classification() -> None:
    error = anthropic.APITimeoutError.__new__(anthropic.APITimeoutError)
    error.args = ("request timed out",)

    assert classify_retry_error(error) == "timeout"


def test_structured_billing_error_is_reraised_unchanged() -> None:
    billing = BillingError(
        "quota exhausted",
        provider="openai",
        plan_id="plus",
        plan_display_name="ChatGPT Plus",
        upgrade_url="https://example.test/upgrade",
        resets_in_seconds=1234,
    )

    async def call(_model: str) -> None:
        raise billing

    with pytest.raises(BillingError) as exc_info:
        asyncio.run(
            run_with_retry_policy(
                ["model"],
                call,
                policy=provider_retry_policy(
                    max_attempts=1,
                    base_delay_s=0.0,
                    max_delay_s=0.0,
                ),
            )
        )

    assert exc_info.value is billing


def test_successful_none_is_not_confused_with_exhaustion() -> None:
    async def call(_model: str) -> None:
        return None

    outcome = asyncio.run(
        run_with_retry_policy(
            ["model"],
            call,
            policy=auxiliary_retry_policy(
                max_attempts=1,
                base_delay_s=0.0,
                max_delay_s=0.0,
            ),
        )
    )

    assert outcome.succeeded is True
    assert outcome.model == "model"
    assert outcome.value is None
    assert outcome.last_error is None


def test_final_failure_does_not_emit_retry_or_sleep() -> None:
    async def call(_model: str) -> None:
        raise _RateLimitError("busy")

    for policy in (
        auxiliary_retry_policy(max_attempts=1, base_delay_s=0.0, max_delay_s=0.0),
        provider_retry_policy(max_attempts=1, base_delay_s=0.0, max_delay_s=0.0),
    ):
        events: list[object] = []
        with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep:
            outcome = asyncio.run(
                run_with_retry_policy(["model"], call, policy=policy, on_retry=events.append)
            )
        assert outcome.succeeded is False
        assert events == []
        sleep.assert_not_awaited()
