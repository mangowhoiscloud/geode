"""OpenAI Adapter — GPT implementation of LLMClientPort.

Mirrors ClaudeAdapter pattern for GPT-5.4 and other OpenAI models.
Uses the openai SDK (>=2.0.0) with retry + failover.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pydantic import BaseModel

from core.config import settings
from core.llm.client import (
    CircuitBreaker,
    LLMUsage,
    ToolCallRecord,
    ToolUseResult,
    get_usage_accumulator,
    track_token_usage,
)

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

# OpenAI retryable errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

# Default OpenAI model
DEFAULT_OPENAI_MODEL = "gpt-5.4"

# OpenAI fallback chain
OPENAI_FALLBACK_MODELS = ["gpt-5.4", "gpt-5.3", "gpt-4o"]

# Model pricing (USD per token) — local copy to avoid coupling to Anthropic client internals
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50 / 1_000_000, "output": 15.0 / 1_000_000},
    "gpt-5.3": {"input": 10.0 / 1_000_000, "output": 30.0 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
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
    global _openai_client
    if _openai_client is None:
        with _openai_lock:
            if _openai_client is None:
                import openai

                _openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_retryable_errors() -> tuple[type[Exception], ...]:
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
                track_token_usage(model, in_tok, out_tok)
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

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T:
        """Generate structured output using OpenAI's chat.completions.parse().

        Uses native Pydantic integration for guaranteed valid JSON.
        """
        client = _get_openai_client()
        target = model or self._default_model

        def _do_call(*, model: str) -> T:
            response = client.beta.chat.completions.parse(
                model=model,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=output_model,
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
                track_token_usage(model, in_tok, out_tok)

            choice = response.choices[0]
            if choice.message.parsed is None:
                raise ValueError("OpenAI returned null parsed output")
            return choice.message.parsed  # type: ignore[no-any-return]

        result: T = self._retry_with_backoff(_do_call, model=target)
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
                    track_token_usage(model, in_tok, out_tok)
                    log.debug(
                        "OpenAI streaming usage: model=%s in=%d out=%d cost=$%.4f",
                        model,
                        in_tok,
                        out_tok,
                        cost,
                    )

        result: Iterator[str] = self._retry_with_backoff(_do_stream, model=target_model)
        return result

    def generate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> ToolUseResult:
        """OpenAI tool-use loop. Mirrors ClaudeAdapter pattern."""
        client = _get_openai_client()
        target = model or self._default_model

        all_tool_calls: list[ToolCallRecord] = []
        all_usage: list[LLMUsage] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for round_idx in range(max_tool_rounds):
            is_last_round = round_idx == max_tool_rounds - 1
            tool_choice = "none" if is_last_round else "auto"

            def _do_call(*, model: str, _tc: str = tool_choice) -> Any:
                return client.chat.completions.create(
                    model=model,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                    tools=tools,
                    tool_choice=_tc,
                    timeout=90.0,
                )

            response = self._retry_with_backoff(_do_call, model=target)

            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                cost = _calculate_cost(target, in_tok, out_tok)
                usage = LLMUsage(
                    model=target, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost
                )
                all_usage.append(usage)
                get_usage_accumulator().record(usage)
                track_token_usage(target, in_tok, out_tok)

            choice = response.choices[0]

            # No tool calls → return text
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                return ToolUseResult(
                    text=choice.message.content or "",
                    tool_calls=all_tool_calls,
                    usage=all_usage,
                    rounds=round_idx + 1,
                )

            # Process tool calls
            messages.append(choice.message)  # assistant message with tool_calls
            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                t0 = time.time()
                try:
                    result = tool_executor(func_name, **func_args)
                except Exception as exc:
                    log.warning("Tool '%s' execution failed: %s", func_name, exc)
                    result = {"error": str(exc)}
                elapsed_ms = (time.time() - t0) * 1000

                all_tool_calls.append(
                    ToolCallRecord(
                        tool_name=func_name,
                        tool_input=func_args,
                        tool_result=result,
                        duration_ms=elapsed_ms,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )

        return ToolUseResult(
            text="",
            tool_calls=all_tool_calls,
            usage=all_usage,
            rounds=max_tool_rounds,
        )

    def _retry_with_backoff(self, fn: Any, *, model: str) -> Any:
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
