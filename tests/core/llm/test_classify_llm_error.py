"""Tests for :func:`core.llm.errors.classify_llm_error`.

PR-DEFECT-AB (2026-05-24) regression pin: the seed-generation smoke
revealed that ``classify_llm_error`` returned the generic ``unknown``
classification for ``ClaudeCliTransientUpstreamError`` raised by the
PR-T subprocess transient classifier, which routed claude-cli 429s
through the loop's "Unexpected error. Auto-retrying." fallback UI
instead of the rate-limit retry branch. The cases below pin the new
mapping so the regression cannot return silently.

paperclip parity reference: ``src/transport/execute.ts:809`` tags the
same upstream signatures with ``errorCode = "claude_transient_upstream"``
and dispatches them via the rate-limit retry path.
"""

from __future__ import annotations

import anthropic
import httpx
import pytest
from core.llm.errors import classify_llm_error
from plugins.petri_audit.claude_cli_provider import ClaudeCliTransientUpstreamError


def _fake_anthropic_response(status_code: int) -> httpx.Response:
    """Anthropic SDK error classes require an ``httpx.Response`` to construct."""
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


class TestClassifyClaudeCliTransientUpstream:
    """PR-DEFECT-AB primary regression pin."""

    def test_transient_upstream_maps_to_rate_limit(self) -> None:
        exc = ClaudeCliTransientUpstreamError("Error: 429 Too Many Requests")
        error_type, severity, hint = classify_llm_error(exc)
        assert error_type == "rate_limit"
        assert severity == "warning"
        assert "rate limit" in hint.lower() or "switch model" in hint.lower()

    def test_overload_signature_maps_to_rate_limit(self) -> None:
        exc = ClaudeCliTransientUpstreamError("overloaded_error: server overloaded")
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "rate_limit"

    def test_quota_signature_maps_to_rate_limit(self) -> None:
        exc = ClaudeCliTransientUpstreamError("5-hour limit reached, resets at 3:00pm (Pacific)")
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "rate_limit"

    def test_subclass_still_maps_to_rate_limit(self) -> None:
        """Ensure isinstance gate accepts subclasses if they appear later."""

        class _ChildTransientError(ClaudeCliTransientUpstreamError):
            pass

        exc = _ChildTransientError("burst")
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "rate_limit"


class TestClassifyAnthropicSdkErrorsUnchanged:
    """Regression guard: the new lazy-import branch must not change
    classifications of any existing Anthropic SDK exception type."""

    def test_rate_limit_error(self) -> None:
        exc = anthropic.RateLimitError(
            message="rate limited",
            response=_fake_anthropic_response(429),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "rate_limit"

    def test_timeout_error(self) -> None:
        exc = anthropic.APITimeoutError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "timeout"

    def test_connection_error(self) -> None:
        exc = anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "connection"

    def test_authentication_error(self) -> None:
        exc = anthropic.AuthenticationError(
            message="invalid api key",
            response=_fake_anthropic_response(401),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "auth"

    def test_internal_server_error(self) -> None:
        exc = anthropic.InternalServerError(
            message="boom",
            response=_fake_anthropic_response(500),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "server"

    def test_bad_request_generic(self) -> None:
        exc = anthropic.BadRequestError(
            message="invalid tool schema",
            response=_fake_anthropic_response(400),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "bad_request"

    def test_bad_request_context_overflow_via_message(self) -> None:
        """The classifier inspects the message for 'token' / 'context' /
        'prompt exceeds' / 'max length' substrings to upgrade a generic
        400 to ``context_overflow`` so the loop's recovery path fires."""
        exc = anthropic.BadRequestError(
            message="prompt exceeds the model's context window of 200000 tokens",
            response=_fake_anthropic_response(400),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "context_overflow"

    def test_unknown_error(self) -> None:
        error_type, _severity, _hint = classify_llm_error(RuntimeError("???"))
        assert error_type == "unknown"


class TestClassifyOpenAiSdkErrorsUnchanged:
    """Regression guard: GLM / OpenAI providers route through
    ``_classify_openai_error`` — confirm the lazy-import PR-T branch
    does not short-circuit that path."""

    def _fake_openai_response(self, status_code: int) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )

    def test_openai_rate_limit_error(self) -> None:
        import openai

        exc = openai.RateLimitError(
            message="rate limited",
            response=self._fake_openai_response(429),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "rate_limit"

    def test_openai_authentication_error(self) -> None:
        import openai

        exc = openai.AuthenticationError(
            message="invalid api key",
            response=self._fake_openai_response(401),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "auth"

    def test_openai_bad_request_context_overflow(self) -> None:
        import openai

        exc = openai.BadRequestError(
            message="This model's maximum context length is 128000 tokens",
            response=self._fake_openai_response(400),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "context_overflow"


@pytest.mark.parametrize(
    "message",
    [
        "Error: 429 Too Many Requests",
        "rate_limit_error: token bucket empty",
        "overloaded_error: server overloaded",
        "weekly limit reached. resets at 9am (UTC)",
    ],
)
def test_transient_upstream_precedes_unknown_fallback(message: str) -> None:
    """Parametric smoke: every PR-T transient signature must NOT fall through to ``unknown``."""
    exc = ClaudeCliTransientUpstreamError(message)
    error_type, _severity, _hint = classify_llm_error(exc)
    assert error_type != "unknown", (
        f"transient upstream message {message!r} fell through to unknown — Defect A would re-emerge"
    )
