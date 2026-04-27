"""v0.52.6 hotfix — Codex backend request shape + 400 fail-fast.

Production incident (2026-04-27): every Codex backend call to
``chatgpt.com/backend-api/codex/responses`` returned 400 Bad Request:
``{'detail': 'Unsupported parameter: max_output_tokens'}``. The Plus
subscription manages output limits server-side; sending a client cap
breaks every request. The retry loop then hammered the same 400 across
all fallback models for ~30s before the circuit breaker tripped — same
shape as the v0.52.3 billing-fatal storm but for request-shape errors.

Two invariants pinned here:

  1. ``CodexAgenticAdapter.agentic_call`` MUST NOT pass
     ``max_output_tokens`` to ``client.responses.stream`` — Codex
     backend rejects it. ``OpenAIAgenticAdapter`` (PAYG, talks to
     ``api.openai.com``) still passes it; the PAYG endpoint accepts it.

  2. ``is_request_fatal()`` recognises the 400 shape ("Unsupported
     parameter", "Invalid value", "Missing required parameter") and
     ``fallback.retry_with_backoff_generic`` re-raises immediately
     instead of retrying — saves the ~30s × 5 attempts × 3 fallback
     models cascade observed in production.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import core.llm.fallback as _fallback
import core.llm.providers.codex as _codex_mod
import pytest
from core.llm.errors import is_request_fatal

# ---------------------------------------------------------------------------
# Contract 1 — Codex adapter must not send max_output_tokens
# ---------------------------------------------------------------------------


def test_codex_agentic_call_does_not_send_max_output_tokens() -> None:
    """Source-level: the Codex Responses API call must not include
    ``max_output_tokens``. Codex backend rejects it with 400."""
    src = inspect.getsource(_codex_mod.CodexAgenticAdapter.agentic_call)
    # The literal kwarg must not appear inside the ``responses.stream(`` call.
    stream_block_start = src.find("responses.stream(")
    assert stream_block_start >= 0, "responses.stream call missing"
    stream_block_end = src.find(")", stream_block_start)
    stream_block = src[stream_block_start:stream_block_end]
    assert "max_output_tokens" not in stream_block, (
        "max_output_tokens must NOT be in the Codex Responses API call. "
        "Codex backend (chatgpt.com/backend-api/codex) rejects it with 400. "
        "Plus subscription manages output limits server-side."
    )


def test_codex_adapter_inherits_max_tokens_signature() -> None:
    """Signature compatibility — even though we don't pass max_tokens to
    the Codex call, the method signature must keep the kwarg so the
    abstract base class contract is honoured (siblings still need it)."""
    sig = inspect.signature(_codex_mod.CodexAgenticAdapter.agentic_call)
    assert "max_tokens" in sig.parameters, (
        "max_tokens kwarg removed from method signature — would break "
        "OpenAIAgenticAdapter parent class contract / call sites"
    )


# ---------------------------------------------------------------------------
# Contract 2 — is_request_fatal recognises 400 "Unsupported parameter"
# ---------------------------------------------------------------------------


def _make_400(detail: str, *, attr: str = "body") -> Exception:
    """Build an exception with status_code=400 and the given detail body."""
    exc = Exception(detail)
    if attr == "body":
        exc.body = {"detail": detail}  # type: ignore[attr-defined]
    elif attr == "response":
        response = MagicMock()
        response.json.return_value = {"detail": detail}
        response.status_code = 400
        exc.response = response  # type: ignore[attr-defined]
    exc.status_code = 400  # type: ignore[attr-defined]
    return exc


def test_unsupported_parameter_is_request_fatal() -> None:
    """The actual production trigger — Codex backend's exact response."""
    exc = _make_400("Unsupported parameter: max_output_tokens")
    assert is_request_fatal(exc) is True


def test_invalid_value_for_parameter_is_request_fatal() -> None:
    """Common OpenAI 400 — wrong enum value, wrong type, etc."""
    exc = _make_400("Invalid value for parameter 'tool_choice'")
    assert is_request_fatal(exc) is True


def test_missing_required_parameter_is_request_fatal() -> None:
    exc = _make_400("Missing required parameter: 'model'")
    assert is_request_fatal(exc) is True


def test_unknown_parameter_is_request_fatal() -> None:
    """Anthropic/GLM variant phrasing."""
    exc = _make_400("Unknown parameter 'thinking_budget'")
    assert is_request_fatal(exc) is True


def test_generic_400_without_marker_is_not_request_fatal() -> None:
    """A 400 that doesn't match any marker (e.g. context overflow) must
    NOT be classified as request-fatal — it has its own handling path."""
    exc = _make_400("This model's maximum context length is 200000 tokens")
    assert is_request_fatal(exc) is False


def test_429_is_not_request_fatal() -> None:
    """Rate limits go through is_billing_fatal / retry, not this path."""
    exc = Exception("rate limited")
    exc.status_code = 429  # type: ignore[attr-defined]
    exc.body = {"detail": "Unsupported parameter: foo"}  # type: ignore[attr-defined]
    assert is_request_fatal(exc) is False, (
        "429 must not be classified as request-fatal — only 4xx (non-429)"
    )


def test_500_is_not_request_fatal() -> None:
    """Server errors are retryable, never request-fatal."""
    exc = Exception("internal error")
    exc.status_code = 500  # type: ignore[attr-defined]
    exc.body = {"detail": "Unsupported parameter: foo"}  # type: ignore[attr-defined]
    assert is_request_fatal(exc) is False


def test_response_attr_fallback() -> None:
    """SDK that exposes .response.json() rather than .body."""
    exc = _make_400("Unsupported parameter: max_output_tokens", attr="response")
    assert is_request_fatal(exc) is True


def test_unparseable_exc_defaults_to_not_fatal() -> None:
    """Unknown shape ⇒ return False so legitimate retries aren't blocked."""
    exc = Exception("network blip")
    assert is_request_fatal(exc) is False


# ---------------------------------------------------------------------------
# Contract 3 — fallback.retry_with_backoff_generic short-circuits 400s
# ---------------------------------------------------------------------------


def test_fallback_loop_calls_is_request_fatal_in_bad_request_branch() -> None:
    """Source-level: the bad_request branch must call is_request_fatal
    BEFORE the billing/context-overflow checks so the production-trigger
    shape (400 + Unsupported parameter) re-raises immediately."""
    src = inspect.getsource(_fallback.retry_with_backoff_generic)
    fatal_pos = src.find("is_request_fatal(exc)")
    sleep_pos = src.find("time.sleep(delay)")
    assert fatal_pos >= 0, "fallback.py must import + call is_request_fatal"
    assert sleep_pos >= 0
    # Same constraint as v0.52.3 billing-fatal — fail before the next sleep.
    assert fatal_pos > sleep_pos or fatal_pos < src.find("except Exception as exc"), (
        "is_request_fatal call must live in the bad_request branch, not "
        "before the retryable_errors classification"
    )


def test_fallback_loop_reraises_on_unsupported_parameter() -> None:
    """End-to-end: a fake openai.BadRequestError-style exception with
    400 + ``Unsupported parameter`` body must NOT trigger any retries."""
    from core.llm.fallback import CircuitBreaker, retry_with_backoff_generic

    call_count = 0

    class FakeBadRequestError(Exception):
        pass

    def fn(*, model: str) -> None:
        nonlocal call_count
        call_count += 1
        exc = FakeBadRequestError("400")
        exc.status_code = 400  # type: ignore[attr-defined]
        exc.body = {"detail": "Unsupported parameter: max_output_tokens"}  # type: ignore[attr-defined]
        raise exc

    cb = CircuitBreaker()
    with pytest.raises(FakeBadRequestError):
        retry_with_backoff_generic(
            fn,
            model="gpt-5.5",
            fallback_models=["gpt-5.4-mini", "gpt-5.3-codex"],
            circuit_breaker=cb,
            retryable_errors=(),  # 400 not in this tuple — falls into bad_request branch
            bad_request_error=FakeBadRequestError,
            billing_message="OpenAI billing exhausted",
            max_retries=5,
            provider_label="OpenAI Codex",
        )
    assert call_count == 1, (
        f"Request-fatal 400 must not retry. Got {call_count} attempts. "
        "v0.52.5 incident: 5×3=15 attempts wasted ~30s on the same 400."
    )
