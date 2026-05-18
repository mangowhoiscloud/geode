"""Responses API prompt-cache token extraction."""

from __future__ import annotations

from types import SimpleNamespace

from core.llm.agentic_response import normalize_openai, normalize_openai_responses


def test_responses_api_input_tokens_details_cached_tokens() -> None:
    """Codex/OpenAI Responses usage reports cache hits on input token details."""
    response = SimpleNamespace(
        output=[],
        usage=SimpleNamespace(
            input_tokens=128,
            output_tokens=8,
            input_tokens_details=SimpleNamespace(cached_tokens=96),
            output_tokens_details=SimpleNamespace(reasoning_tokens=3),
        ),
    )

    result = normalize_openai_responses(response)

    assert result.usage.input_tokens == 128
    assert result.usage.output_tokens == 8
    assert result.usage.thinking_tokens == 3
    assert result.usage.cache_read_tokens == 96


def test_responses_api_prompt_tokens_details_cached_tokens_fallback() -> None:
    """Compatibility fallback for Responses-shaped mocks with old usage details."""
    response = SimpleNamespace(
        output=[],
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=2,
            prompt_tokens_details=SimpleNamespace(cached_tokens=21),
        ),
    )

    result = normalize_openai_responses(response)

    assert result.usage.cache_read_tokens == 21


def test_chat_completions_cache_token_path_still_works() -> None:
    """Chat Completions keeps using prompt_tokens_details.cached_tokens."""
    message = SimpleNamespace(content="hello", tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason="stop")
    response = SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=80,
            completion_tokens=5,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        ),
    )

    result = normalize_openai(response)

    assert result.usage.input_tokens == 80
    assert result.usage.cache_read_tokens == 40
