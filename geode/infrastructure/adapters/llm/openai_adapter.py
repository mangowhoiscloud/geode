"""OpenAI Adapter — GPT implementation of LLMClientPort.

Mirrors ClaudeAdapter pattern for GPT-5.3 and other OpenAI models.
Uses the openai SDK (>=2.0.0) with retry + failover.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any

from geode.config import settings
from geode.llm.client import (
    LLMUsage,
    calculate_cost,
    get_usage_accumulator,
)

log = logging.getLogger(__name__)

# OpenAI retryable errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

# Default OpenAI model
DEFAULT_OPENAI_MODEL = "gpt-5.3"

# OpenAI fallback chain
OPENAI_FALLBACK_MODELS = ["gpt-5.3"]


def _get_openai_client():
    """Lazy import and create OpenAI client."""
    import openai

    return openai.OpenAI(api_key=settings.openai_api_key)


def _get_retryable_errors() -> tuple:
    """Get retryable error types from openai SDK."""
    import openai

    return (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


class OpenAIAdapter:
    """OpenAI GPT adapter implementing LLMClientPort.

    Provides the same interface as ClaudeAdapter but backed by OpenAI API.
    """

    def __init__(self, default_model: str = DEFAULT_OPENAI_MODEL) -> None:
        self._default_model = default_model

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        client = _get_openai_client()
        target = model or self._default_model

        def _do_call(*, model: str) -> str:
            response = client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                cost = calculate_cost(model, in_tok, out_tok)
                usage = LLMUsage(
                    model=model, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost
                )
                get_usage_accumulator().record(usage)
                log.debug(
                    "OpenAI usage: model=%s in=%d out=%d cost=$%.4f",
                    model,
                    in_tok,
                    out_tok,
                    cost,
                )

            choice = response.choices[0]
            return choice.message.content or ""

        result: str = self._retry_with_backoff(_do_call, model=target)
        return result

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        raw = self.generate(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
        text = raw.strip()
        text = re.sub(r"^```\w*\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        result: dict[str, Any] = json.loads(text)
        return result

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]:
        client = _get_openai_client()
        target = model or self._default_model

        stream = client.chat.completions.create(
            model=target,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _retry_with_backoff(self, fn, *, model: str) -> Any:
        """Retry with exponential backoff + model fallback."""
        retryable = _get_retryable_errors()
        models_to_try = [model] + [m for m in OPENAI_FALLBACK_MODELS if m != model]
        last_error: Exception | None = None

        for model_idx, current_model in enumerate(models_to_try):
            for attempt in range(_MAX_RETRIES):
                try:
                    return fn(model=current_model)
                except retryable as exc:
                    last_error = exc
                    delay = min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY)
                    log.warning(
                        "OpenAI call failed (model=%s, attempt=%d/%d): %s",
                        current_model,
                        attempt + 1,
                        _MAX_RETRIES,
                        type(exc).__name__,
                    )
                    time.sleep(delay)

            if model_idx < len(models_to_try) - 1:
                log.warning("Falling back to next OpenAI model")

        assert last_error is not None
        raise last_error
