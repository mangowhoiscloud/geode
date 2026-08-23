"""R5.4 explicit retry-policy and shared-runner contracts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import anthropic
import pytest
from core.llm.errors import BillingError
from core.llm.fallback import (
    RetryAction,
    RetryPolicy,
    auxiliary_retry_policy,
    classify_retry_error,
    interactive_retry_policy,
    provider_retry_policy,
    run_with_retry_policy,
)
from core.llm.router import call_with_failover


class _RateLimitError(Exception):
    status_code = 429


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


def test_interactive_policy_preserves_terminal_quota_and_delay() -> None:
    policy = interactive_retry_policy(max_attempts=5)

    assert policy.action_for("rate_limit") is RetryAction.TERMINAL
    assert policy.action_for("connection") is RetryAction.RETRY
    assert policy.delay_for(1) == 2.0
    assert policy.delay_for(2) == 4.0
    assert policy.delay_for(5) == 30.0


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


def test_final_failure_sleep_difference_is_explicit() -> None:
    async def call(_model: str) -> None:
        raise _RateLimitError("busy")

    with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep:
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
    assert outcome.succeeded is False
    sleep.assert_not_awaited()

    with patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep:
        outcome = asyncio.run(
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
    assert outcome.succeeded is False
    sleep.assert_awaited_once_with(0.0)
