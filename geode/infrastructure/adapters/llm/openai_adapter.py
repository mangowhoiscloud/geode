"""OpenAI Adapter — GPT implementation of LLMClientPort.

Mirrors ClaudeAdapter pattern for GPT-5.3 and other OpenAI models.
Uses the openai SDK (>=2.0.0) with retry + failover.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Iterator
from typing import Any

from geode.config import settings
from geode.llm.client import (
    CircuitBreaker,
    LLMUsage,
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
OPENAI_FALLBACK_MODELS = ["gpt-5.3", "gpt-4o"]

# Model pricing (USD per token) — local copy to avoid coupling to Anthropic client internals
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.3": {"input": 10.0 / 1_000_000, "output": 30.0 / 1_000_000},
}


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for OpenAI models."""
    prices = _MODEL_PRICING.get(model, {})
    return input_tokens * prices.get("input", 0) + output_tokens * prices.get("output", 0)


_openai_client: Any = None  # openai.OpenAI | None — lazy import
_openai_lock = threading.Lock()

# Circuit breaker for OpenAI API calls
_openai_circuit_breaker = CircuitBreaker()


def _get_openai_client() -> Any:
    """Lazy import and return cached OpenAI client (thread-safe)."""
    global _openai_client  # noqa: PLW0603
    if _openai_client is None:
        with _openai_lock:
            if _openai_client is None:
                import openai

                _openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _openai_client


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

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        return self._default_model

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
                timeout=90.0,
            )
            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                cost = _calculate_cost(model, in_tok, out_tok)
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
        try:
            result: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("Failed to parse OpenAI JSON response. Raw text: %s", text[:500])
            raise ValueError(f"OpenAI returned invalid JSON: {exc}") from exc
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
        target_model = model or self._default_model

        def _do_stream(*, model: str) -> Iterator[str]:
            response = client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                stream=True,
                stream_options={"include_usage": True},
                timeout=90.0,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                # Final chunk carries usage when stream_options includes usage
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    in_tok = chunk.usage.prompt_tokens or 0
                    out_tok = chunk.usage.completion_tokens or 0
                    cost = _calculate_cost(model, in_tok, out_tok)
                    usage = LLMUsage(
                        model=model,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cost_usd=cost,
                    )
                    get_usage_accumulator().record(usage)
                    log.debug(
                        "OpenAI streaming usage: model=%s in=%d out=%d cost=$%.4f",
                        model,
                        in_tok,
                        out_tok,
                        cost,
                    )

        return self._retry_with_backoff(_do_stream, model=target_model)

    def _retry_with_backoff(self, fn, *, model: str) -> Any:
        """Retry with exponential backoff + model fallback + circuit breaker."""
        import openai

        if not _openai_circuit_breaker.can_execute():
            raise RuntimeError(
                "Circuit breaker is open — OpenAI API calls are temporarily blocked. "
                "Too many consecutive failures detected."
            )

        retryable = _get_retryable_errors()
        models_to_try = [model] + [m for m in OPENAI_FALLBACK_MODELS if m != model]
        last_error: Exception | None = None

        for model_idx, current_model in enumerate(models_to_try):
            for attempt in range(_MAX_RETRIES):
                try:
                    result = fn(model=current_model)
                    _openai_circuit_breaker.record_success()
                    return result
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
                except openai.BadRequestError as exc:
                    error_msg = str(exc)
                    # Credit balance / billing error — no retry, clear message
                    if "billing" in error_msg.lower() or "credit" in error_msg.lower():
                        log.error("OpenAI billing error: %s", error_msg)
                        raise RuntimeError(
                            "OpenAI API billing/credit error. "
                            "Check your OpenAI account billing settings, "
                            "or use --dry-run mode."
                        ) from exc
                    # Context overflow or token limit — no retry, log details
                    if "token" in error_msg.lower() or "context" in error_msg.lower():
                        log.error(
                            "Context overflow (model=%s): %s",
                            current_model,
                            error_msg,
                        )
                    raise

            if model_idx < len(models_to_try) - 1:
                next_model = models_to_try[model_idx + 1]
                log.warning(
                    "All retries exhausted for model=%s. Falling back to %s",
                    current_model,
                    next_model,
                )

        if last_error is None:
            raise RuntimeError("All retries exhausted with no error recorded")
        _openai_circuit_breaker.record_failure()
        log.error("All OpenAI models and retries exhausted. Last error: %s", last_error)
        raise last_error
