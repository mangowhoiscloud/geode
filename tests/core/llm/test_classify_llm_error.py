"""Tests for :func:`core.llm.errors.classify_llm_error`."""

from __future__ import annotations

import anthropic
import httpx
from core.llm.errors import classify_llm_error


def _fake_anthropic_response(status_code: int) -> httpx.Response:
    """Anthropic SDK error classes require an ``httpx.Response`` to construct."""
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


class TestClassifyAnthropicSdkErrorsUnchanged:
    """Regression guard for Anthropic SDK exception types."""

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
    """Regression guard for GLM / OpenAI SDK exception types."""

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

    def test_codex_sse_generic_overload_error(self) -> None:
        import openai

        exc = openai.APIError(
            "Our servers are currently overloaded. Please try again later.",
            request=httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses"),
            body=None,
        )
        error_type, _severity, _hint = classify_llm_error(exc)
        assert error_type == "server"
