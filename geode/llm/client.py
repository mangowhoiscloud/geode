"""LLM client wrapper for Anthropic and OpenAI.

Failover strategy (OpenClaw-inspired 4-stage):
1. Retry with exponential backoff (max 3 attempts)
2. Model fallback chain (primary → fallback models)
3. Context overflow detection (token limit → truncation hint)
4. Graceful degradation (log + raise after all retries exhausted)
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import anthropic

from geode.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------

# Model pricing (USD per token) — updated 2026-02
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-sonnet-4-5-20250929": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    "gpt-5.3": {"input": 10.0 / 1_000_000, "output": 30.0 / 1_000_000},
}


@dataclass
class LLMUsage:
    """Token usage and cost tracking for a single LLM call."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass
class LLMUsageAccumulator:
    """Accumulates token usage across multiple LLM calls."""

    calls: list[LLMUsage] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.calls)

    def record(self, usage: LLMUsage) -> None:
        self.calls.append(usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "call_count": len(self.calls),
        }


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token counts."""
    prices = MODEL_PRICING.get(model, {})
    return input_tokens * prices.get("input", 0) + output_tokens * prices.get("output", 0)


# Thread-safe usage accumulator via contextvars
# Note: No default= argument — avoids sharing a single mutable instance across contexts.
_usage_ctx: contextvars.ContextVar[LLMUsageAccumulator] = contextvars.ContextVar("llm_usage")


def get_usage_accumulator() -> LLMUsageAccumulator:
    """Get the context-local usage accumulator (thread-safe).

    Creates a fresh accumulator on first access per context to avoid
    the shared-mutable-default pitfall.
    """
    try:
        return _usage_ctx.get()
    except LookupError:
        acc = LLMUsageAccumulator()
        _usage_ctx.set(acc)
        return acc


def reset_usage_accumulator() -> None:
    """Reset the context-local usage accumulator."""
    _usage_ctx.set(LLMUsageAccumulator())


# Failover configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 30.0
FALLBACK_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-5-20250929",
]


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Simple circuit breaker for LLM API calls."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._failures = 0
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._last_failure: float = 0.0
        self._state: str = "closed"  # closed, open, half-open

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._state = "open"

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def can_execute(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.time() - self._last_failure > self._recovery_timeout:
                self._state = "half-open"
                return True
            return False
        return True  # half-open: allow one attempt


_circuit_breaker = CircuitBreaker()

# Retryable error types
_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


def get_anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _retry_with_backoff(
    fn,
    *,
    model: str,
    max_retries: int = MAX_RETRIES,
) -> Any:
    """Execute fn with retry + exponential backoff + model fallback.

    Stage 1: Retry same model with exponential backoff.
    Stage 2: On persistent failure, try fallback models.
    Stage 3: Circuit breaker prevents calls when API is down.
    """
    if not _circuit_breaker.can_execute():
        raise RuntimeError(
            "Circuit breaker is open — LLM API calls are temporarily blocked. "
            "Too many consecutive failures detected."
        )

    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error: Exception | None = None

    for model_idx, current_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            try:
                result = fn(model=current_model)
                _circuit_breaker.record_success()
                return result
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
                log.warning(
                    "LLM call failed (model=%s, attempt=%d/%d): %s. Retrying in %.1fs",
                    current_model,
                    attempt + 1,
                    max_retries,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
            except anthropic.BadRequestError as exc:
                error_msg = str(exc)
                # Credit balance / billing error — no retry, clear message
                if "credit balance" in error_msg.lower() or "billing" in error_msg.lower():
                    log.error("Billing error: %s", error_msg)
                    raise RuntimeError(
                        "Anthropic API credit balance too low. "
                        "Visit https://console.anthropic.com/settings/billing to add credits, "
                        "or use --dry-run mode."
                    ) from exc
                # Context overflow or invalid request — no retry
                if "token" in error_msg.lower() or "context" in error_msg.lower():
                    log.error("Context overflow detected (model=%s): %s", current_model, error_msg)
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
    _circuit_breaker.record_failure()
    log.error("All models and retries exhausted. Last error: %s", last_error)
    raise last_error


def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> str:
    """Synchronous Claude call with failover. Returns text content.

    Args:
        seed: Optional seed for reproducibility tracking. Logged for auditing
            but not passed to the Anthropic API (not supported by SDK).
    """
    client = get_anthropic_client()
    target_model = model or settings.model

    if seed is not None:
        log.info("Reproducibility seed=%d requested (logged for auditing)", seed)

    def _do_call(*, model: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=90.0,
        )
        # Capture token usage
        if hasattr(response, "usage") and response.usage:
            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            cost = calculate_cost(model, in_tok, out_tok)
            usage = LLMUsage(
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
            )
            get_usage_accumulator().record(usage)
            log.debug(
                "LLM usage: model=%s in=%d out=%d cost=$%.4f",
                model,
                in_tok,
                out_tok,
                cost,
            )

        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block)}")
        return block.text  # type: ignore[return-value]

    result: str = _retry_with_backoff(_do_call, model=target_model)
    return result


def call_llm_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> dict[str, Any]:
    """Claude call that parses JSON from the response. Includes failover."""
    raw = call_llm(
        system, user, model=model, max_tokens=max_tokens, temperature=temperature, seed=seed
    )
    # Strip markdown code fences if present (handles ```json, ``` with trailing spaces, etc.)
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    try:
        result: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse LLM JSON response. Raw text: %s", text[:500])
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
    return result


def call_llm_streaming(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Iterator[str]:
    """Streaming Claude call with failover. Yields text deltas.

    Token usage is captured from the stream's final message and recorded
    to the context-local accumulator after the stream completes.
    """
    client = get_anthropic_client()
    target_model = model or settings.model

    def _do_stream(*, model: str) -> Iterator[str]:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            yield from stream.text_stream

            # Capture token usage from the stream's final response
            final = stream.get_final_message()
            if final and hasattr(final, "usage") and final.usage:
                in_tok = final.usage.input_tokens
                out_tok = final.usage.output_tokens
                cost = calculate_cost(model, in_tok, out_tok)
                usage = LLMUsage(
                    model=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                )
                get_usage_accumulator().record(usage)
                log.debug(
                    "Streaming usage: model=%s in=%d out=%d cost=$%.4f",
                    model,
                    in_tok,
                    out_tok,
                    cost,
                )

    # Circuit breaker check — mirrors call_llm() behavior
    if not _circuit_breaker.can_execute():
        raise RuntimeError(
            "Circuit breaker is open — LLM API calls are temporarily blocked. "
            "Too many consecutive failures detected."
        )

    # For streaming, retry at connection level only
    models_to_try = [target_model] + [m for m in FALLBACK_MODELS if m != target_model]
    last_error: Exception | None = None

    for current_model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                result = _do_stream(model=current_model)
                _circuit_breaker.record_success()
                return result
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                delay = min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)
                log.warning(
                    "Streaming call failed (model=%s, attempt=%d/%d): %s",
                    current_model,
                    attempt + 1,
                    MAX_RETRIES,
                    type(exc).__name__,
                )
                time.sleep(delay)

    if last_error is None:
        raise RuntimeError("All retries exhausted with no error recorded")
    _circuit_breaker.record_failure()
    raise last_error
