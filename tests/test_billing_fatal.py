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

import inspect
from unittest.mock import MagicMock

import core.llm.fallback as _fallback
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


def test_fallback_loop_calls_is_billing_fatal_before_retry() -> None:
    """Source-level invariant: the retryable_errors except block must call
    is_billing_fatal and raise BillingError BEFORE the retry sleep / fallback
    iteration. If a future refactor moves the check after sleep, the 40s
    waste regression returns.
    """
    src = inspect.getsource(_fallback)
    assert "is_billing_fatal" in src, (
        "fallback.py must import and call is_billing_fatal from core.llm.errors"
    )
    # Locate the except retryable_errors block and assert is_billing_fatal
    # appears before the time.sleep / on_retry callback in the same block.
    block_start = src.find("except retryable_errors as exc:")
    assert block_start >= 0
    next_except = src.find("except Exception as exc:", block_start)
    block = src[block_start : next_except if next_except > 0 else len(src)]
    fatal_pos = block.find("is_billing_fatal(exc)")
    sleep_pos = block.find("time.sleep(delay)")
    assert fatal_pos >= 0, "is_billing_fatal call missing inside retryable block"
    assert sleep_pos >= 0, "time.sleep removed?"
    assert fatal_pos < sleep_pos, (
        "is_billing_fatal must be checked BEFORE time.sleep — otherwise we "
        "waste an entire backoff cycle on a billing-fatal error"
    )


def test_fallback_loop_raises_billing_error_on_glm_1113() -> None:
    """End-to-end: a fake fn() that raises a 429-with-code-1113 must propagate
    as BillingError out of run_with_retries, no retries observed."""
    from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

    call_count = 0

    class FakeRateLimitError(Exception):
        pass

    def fn(*, model: str) -> None:
        nonlocal call_count
        call_count += 1
        exc = FakeRateLimitError("429")
        exc.body = {"error": {"code": "1113", "message": "Insufficient balance"}}  # type: ignore[attr-defined]
        raise exc

    cb = CircuitBreaker()
    with pytest.raises(BillingError) as exc_info:
        retry_with_backoff_generic(
            fn,
            model="glm-5.1",
            fallback_models=["glm-5", "glm-5-turbo"],
            circuit_breaker=cb,
            retryable_errors=(FakeRateLimitError,),
            bad_request_error=None,
            billing_message="GLM billing exhausted",
            max_retries=5,
            provider_label="GLM",
        )
    assert "Insufficient balance" in str(exc_info.value)
    assert call_count == 1, (
        f"Billing-fatal must short-circuit after FIRST call, got {call_count} attempts. "
        "v0.52.1 incident: 5×4=20 attempts wasted ~40s on the same 1113."
    )
