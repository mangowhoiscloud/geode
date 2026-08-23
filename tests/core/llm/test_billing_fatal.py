"""Bug class B4 — billing-fatal errors must not be retried.

The v0.52.1 incident: GLM 429 with code 1113 ("Insufficient balance") was
classified as retryable RateLimitError, causing the fallback loop to
hammer all 4 GLM models × 5 retries × exp-backoff = ~40s per LLM call.
Same shape applies to OpenAI ``insufficient_quota`` and Anthropic
``permission_error``.

This invariant pins:
  1. ``is_billing_fatal()`` correctly identifies the 3 SDK shapes.
  2. ``extract_billing_message()`` recovers the user-facing string.
  3. The fallback retry loop calls ``is_billing_fatal`` and short-circuits
     with ``BillingError`` BEFORE entering the retry sleep.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.llm.errors import (
    BillingError,
    extract_billing_message,
    is_billing_fatal,
)

# ---------------------------------------------------------------------------
# Contract 1 — is_billing_fatal recognises the 3 SDK shapes
# ---------------------------------------------------------------------------


def _make_exc_with_body(body: dict) -> Exception:
    exc = Exception("rate limited")
    exc.body = body  # type: ignore[attr-defined]
    return exc


def test_glm_1113_is_billing_fatal() -> None:
    """GLM 429 body — `{'error': {'code': '1113', 'message': '...'}}`"""
    exc = _make_exc_with_body({"error": {"code": "1113", "message": "Insufficient balance"}})
    assert is_billing_fatal(exc) is True
    assert "Insufficient balance" in extract_billing_message(exc)


def test_glm_1114_is_billing_fatal() -> None:
    exc = _make_exc_with_body({"error": {"code": "1114", "message": "quota exhausted"}})
    assert is_billing_fatal(exc) is True


def test_glm_1301_is_billing_fatal() -> None:
    exc = _make_exc_with_body({"error": {"code": "1301", "message": "suspended"}})
    assert is_billing_fatal(exc) is True


def test_openai_insufficient_quota_is_billing_fatal() -> None:
    exc = _make_exc_with_body(
        {"error": {"code": "insufficient_quota", "message": "You exceeded your quota"}}
    )
    assert is_billing_fatal(exc) is True


def test_openai_billing_hard_limit_is_billing_fatal() -> None:
    exc = _make_exc_with_body({"error": {"code": "billing_hard_limit_reached"}})
    assert is_billing_fatal(exc) is True


def test_anthropic_permission_error_is_billing_fatal() -> None:
    exc = _make_exc_with_body({"type": "permission_error", "message": "billing denied"})
    assert is_billing_fatal(exc) is True


def test_transient_429_is_not_billing_fatal() -> None:
    """Plain rate limit (no fatal code) must remain retryable."""
    exc = _make_exc_with_body({"error": {"code": "rate_limit_exceeded"}})
    assert is_billing_fatal(exc) is False


def test_unparseable_exc_is_not_billing_fatal() -> None:
    """Unknown shape must default to retryable (avoid false-positive denial)."""
    exc = Exception("network blip")
    assert is_billing_fatal(exc) is False


def test_response_attr_fallback() -> None:
    """SDK that exposes .response.json() rather than .body must also work."""
    exc = Exception("rl")
    response = MagicMock()
    response.json.return_value = {"error": {"code": "1113", "message": "balance"}}
    exc.response = response  # type: ignore[attr-defined]
    assert is_billing_fatal(exc) is True


# ---------------------------------------------------------------------------
# Contract 2 — fallback.py retry loop short-circuits via BillingError
# ---------------------------------------------------------------------------


def test_shared_retry_runner_short_circuits_billing_before_retry() -> None:
    """Billing classification must precede callbacks, sleep, and fallback."""
    import asyncio

    from core.llm.fallback import auxiliary_retry_policy, run_with_retry_policy

    calls = 0
    retry_callback = MagicMock()

    async def fn(_model: str) -> None:
        nonlocal calls
        calls += 1
        raise _make_exc_with_body({"error": {"code": "1113", "message": "balance"}})

    with (
        patch("core.llm.fallback.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(BillingError),
    ):
        asyncio.run(
            run_with_retry_policy(
                ["glm-5.1", "glm-5"],
                fn,
                policy=auxiliary_retry_policy(
                    max_attempts=5,
                    base_delay_s=0.0,
                    max_delay_s=0.0,
                ),
                on_retry=retry_callback,
            )
        )

    assert calls == 1
    retry_callback.assert_not_called()
    sleep.assert_not_awaited()


def test_fallback_loop_raises_billing_error_on_glm_1113() -> None:
    """End-to-end: a fake fn() that raises a 429-with-code-1113 must propagate
    as BillingError out of run_with_retries, no retries observed."""
    import asyncio

    from core.llm.fallback import retry_with_backoff_generic_async

    call_count = 0

    class FakeRateLimitError(Exception):
        pass

    async def fn(*, model: str) -> None:
        nonlocal call_count
        call_count += 1
        exc = FakeRateLimitError("429")
        exc.body = {"error": {"code": "1113", "message": "Insufficient balance"}}  # type: ignore[attr-defined]
        raise exc

    with pytest.raises(BillingError) as exc_info:
        asyncio.run(
            retry_with_backoff_generic_async(
                fn,
                model="glm-5.1",
                fallback_models=["glm-5", "glm-5-turbo"],
                retryable_errors=(FakeRateLimitError,),
                bad_request_error=None,
                billing_message="GLM billing exhausted",
                max_retries=5,
                provider_label="GLM",
            )
        )
    assert "Insufficient balance" in str(exc_info.value)
    assert call_count == 1, (
        f"Billing-fatal must short-circuit after FIRST call, got {call_count} attempts. "
        "v0.52.1 incident: 5×4=20 attempts wasted ~40s on the same 1113."
    )
