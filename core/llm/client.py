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
import os as _os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import anthropic
from anthropic.types import TextBlockParam
from pydantic import BaseModel

from core.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LangSmith tracing (Phase 5-A): LangChain standard env vars
#   LANGCHAIN_TRACING_V2=true  — tracing on/off gate
#   LANGCHAIN_API_KEY=lsv2_... — LangSmith API key
#   LANGCHAIN_PROJECT=geode    — project name (optional, default: "default")
#   Legacy: LANGSMITH_API_KEY  — backward-compatible fallback
# ---------------------------------------------------------------------------


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is active (both gate + key required).

    Reads env vars at call time for testability.
    """
    tracing = _os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = _os.environ.get("LANGCHAIN_API_KEY") or _os.environ.get("LANGSMITH_API_KEY")
    return tracing and api_key is not None


def track_token_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record token usage + cost on the current LangSmith RunTree (no-op if disabled)."""
    if not is_langsmith_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree:
            cost = calculate_cost(model, input_tokens, output_tokens)
            run_tree.extra = run_tree.extra or {}
            run_tree.extra["metrics"] = {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": cost,
            }
    except Exception:
        log.debug("Failed to track token usage in LangSmith", exc_info=True)


def _maybe_traceable(
    *,
    run_type: str = "llm",
    name: str | None = None,
) -> Any:
    """Return @traceable decorator if LangSmith is configured, else passthrough."""
    if is_langsmith_enabled():
        try:
            from langsmith import traceable

            return traceable(run_type=run_type, name=name)  # type: ignore[call-overload]
        except ImportError:
            pass

    def _identity(fn: Any) -> Any:
        return fn

    return _identity


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------

# Model pricing (USD per token) — updated 2026-02
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-sonnet-4-5-20250929": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    "gpt-5.4": {"input": 2.50 / 1_000_000, "output": 15.0 / 1_000_000},
    "gpt-5.3": {"input": 10.0 / 1_000_000, "output": 30.0 / 1_000_000},
    "gpt-4.1-mini": {"input": 0.40 / 1_000_000, "output": 1.60 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
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


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Calculate cost in USD for a given model and token counts.

    For Anthropic models, cache tokens have different pricing:
    - cache_creation: input_price * 1.25
    - cache_read: input_price * 0.1
    """
    prices = MODEL_PRICING.get(model, {})
    input_price = prices.get("input", 0)
    output_price = prices.get("output", 0)
    base_cost = input_tokens * input_price + output_tokens * output_price

    # Anthropic cache token pricing
    if cache_creation_tokens or cache_read_tokens:
        cache_create_cost = cache_creation_tokens * input_price * 1.25
        cache_read_cost = cache_read_tokens * input_price * 0.1
        base_cost += cache_create_cost + cache_read_cost

    return base_cost


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
            log.warning(
                "Circuit breaker OPEN after %d failures (threshold=%d)",
                self._failures,
                self._threshold,
            )

    def record_success(self) -> None:
        prev_state = self._state
        self._failures = 0
        self._state = "closed"
        if prev_state == "half-open":
            log.info("Circuit breaker CLOSED (recovered from half-open)")

    def can_execute(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.time() - self._last_failure > self._recovery_timeout:
                self._state = "half-open"
                log.info("Circuit breaker HALF-OPEN (cooldown expired, testing)")
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


def _system_with_cache(system: str) -> list[TextBlockParam]:
    """Convert a system prompt string to content block format with cache_control.

    Enables Anthropic Prompt Caching so that repeated calls sharing the same
    system prompt (e.g., 4 analysts or 3 evaluators) get cache hits and
    reduced latency/cost.
    """
    return [
        TextBlockParam(
            type="text",
            text=system,
            cache_control={"type": "ephemeral"},
        )
    ]


def _retry_with_backoff(
    fn: Any,
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


@_maybe_traceable(run_type="llm", name="call_llm")  # type: ignore[untyped-decorator]
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

    system_cached = _system_with_cache(system)

    def _do_call(*, model: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
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
            track_token_usage(model, in_tok, out_tok)
            log.debug(
                "LLM usage: model=%s in=%d out=%d cost=$%.4f",
                model,
                in_tok,
                out_tok,
                cost,
            )
            # Log cache hit/miss if available
            cache_create = getattr(response.usage, "cache_creation_input_tokens", 0)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            if cache_create or cache_read:
                log.debug("Cache: create=%d read=%d", cache_create, cache_read)

        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block)}")
        return block.text

    result: str = _retry_with_backoff(_do_call, model=target_model)
    return result


T = TypeVar("T", bound=BaseModel)


@_maybe_traceable(run_type="llm", name="call_llm_parsed")  # type: ignore[untyped-decorator]
def call_llm_parsed(  # noqa: UP047 — PEP695 syntax requires Python 3.12+
    system: str,
    user: str,
    *,
    output_model: type[T],
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> T:
    """Claude call with Anthropic Structured Output (messages.parse).

    Uses the SDK's native Pydantic integration to guarantee valid JSON
    conforming to the output_model schema. No manual JSON parsing needed.
    """
    client = get_anthropic_client()
    target_model = model or settings.model
    system_cached = _system_with_cache(system)

    def _do_call(*, model: str) -> T:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
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
            track_token_usage(model, in_tok, out_tok)
            log.debug(
                "LLM parsed usage: model=%s in=%d out=%d cost=$%.4f",
                model,
                in_tok,
                out_tok,
                cost,
            )
            cache_create = getattr(response.usage, "cache_creation_input_tokens", 0)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0)
            if cache_create or cache_read:
                log.debug("Cache: create=%d read=%d", cache_create, cache_read)

        if response.parsed_output is None:
            raise ValueError("Structured output parsing returned None")
        return response.parsed_output

    result: T = _retry_with_backoff(_do_call, model=target_model)
    return result


@_maybe_traceable(run_type="llm", name="call_llm_json")  # type: ignore[untyped-decorator]
def call_llm_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> dict[str, Any]:
    """Claude call that parses JSON from the response. Includes failover.

    Legacy function — prefer call_llm_parsed() for guaranteed structured output.
    Kept for backward compatibility with code that expects dict[str, Any].
    """
    raw = call_llm(
        system, user, model=model, max_tokens=max_tokens, temperature=temperature, seed=seed
    )
    # Strip markdown code fences if present (handles ```json, ``` with trailing spaces, etc.)
    text = raw.strip()
    text = re.sub(r"^```\w*\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    text = text.strip()

    # Try direct JSON parse
    try:
        result: dict[str, Any] = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass

    # Fallback: extract JSON object from text (handles markdown-wrapped responses)
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            result = json.loads(candidate)
            log.info("Extracted JSON from position %d-%d in LLM response", first_brace, last_brace)
            return result
        except json.JSONDecodeError:
            pass

    log.error("Failed to parse LLM JSON response. Raw text: %s", text[:500])
    raise ValueError("LLM returned invalid JSON: could not extract JSON object from response")


@dataclass
class ToolCallRecord:
    """Record of a single tool call within a tool-use loop."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_result: dict[str, Any]
    duration_ms: float


@dataclass
class ToolUseResult:
    """Result from a multi-turn tool-use LLM call."""

    text: str
    tool_calls: list[ToolCallRecord]
    usage: list[LLMUsage]
    rounds: int


@_maybe_traceable(run_type="chain", name="call_llm_with_tools")  # type: ignore[untyped-decorator]
def call_llm_with_tools(
    system: str,
    user: str,
    *,
    tools: list[dict[str, Any]],
    tool_executor: Any,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    max_tool_rounds: int = 5,
) -> ToolUseResult:
    """Claude call with tool-use loop. Returns final text + tool call records.

    Runs a multi-turn loop: when the model requests tool_use, executes the
    tool via tool_executor and feeds the result back. On the last round,
    forces tool_choice=none to guarantee a text response.

    Args:
        tools: Anthropic-format tool definitions.
        tool_executor: Callable(name, **kwargs) -> dict[str, Any].
        max_tool_rounds: Max loop iterations (default 5). Prevents runaway.
    """
    client = get_anthropic_client()
    target_model = model or settings.model
    system_cached = _system_with_cache(system)

    all_tool_calls: list[ToolCallRecord] = []
    all_usage: list[LLMUsage] = []
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    # Apply cache_control to tool definitions for Anthropic prompt caching
    # ~4K tokens of tool definitions benefit significantly from caching
    cached_tools: list[dict[str, Any]] = []
    for i, tool in enumerate(tools):
        tool_copy = dict(tool)
        # Apply cache_control to the last tool (Anthropic caches up to the breakpoint)
        if i == len(tools) - 1:
            tool_copy["cache_control"] = {"type": "ephemeral"}
        cached_tools.append(tool_copy)
    tools = cached_tools

    for round_idx in range(max_tool_rounds):
        is_last_round = round_idx == max_tool_rounds - 1
        tool_choice: dict[str, str] | None = {"type": "none"} if is_last_round else {"type": "auto"}

        def _do_call(
            *,
            model: str,
            _tc: dict[str, str] | None = tool_choice,
        ) -> Any:
            return client.messages.create(  # type: ignore[call-overload]
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_cached,
                messages=messages,
                tools=tools,
                tool_choice=_tc,
                timeout=90.0,
            )

        response = _retry_with_backoff(_do_call, model=target_model)

        # Track usage
        if hasattr(response, "usage") and response.usage:
            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            cost = calculate_cost(target_model, in_tok, out_tok)
            usage = LLMUsage(
                model=target_model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
            )
            all_usage.append(usage)
            get_usage_accumulator().record(usage)
            track_token_usage(target_model, in_tok, out_tok)

        # Check if model wants to use tools
        if response.stop_reason != "tool_use":
            # Extract final text
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            return ToolUseResult(
                text=text,
                tool_calls=all_tool_calls,
                usage=all_usage,
                rounds=round_idx + 1,
            )

        # Process tool_use blocks
        assistant_content = response.content
        tool_result_blocks: list[dict[str, Any]] = []

        for block in assistant_content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input
            t0 = time.time()
            try:
                result = tool_executor(tool_name, **tool_input)
            except Exception as exc:
                log.warning("Tool '%s' execution failed: %s", tool_name, exc)
                result = {"error": str(exc)}
            elapsed_ms = (time.time() - t0) * 1000

            all_tool_calls.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_result=result,
                    duration_ms=elapsed_ms,
                )
            )
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )

        # Append assistant + tool_result messages for next round
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_result_blocks})

    # Should not reach here, but return last state
    return ToolUseResult(
        text="",
        tool_calls=all_tool_calls,
        usage=all_usage,
        rounds=max_tool_rounds,
    )


@_maybe_traceable(run_type="llm", name="call_llm_streaming")  # type: ignore[untyped-decorator]
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
        system_cached = _system_with_cache(system)
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            yield from stream.text_stream

            # Record success AFTER stream completes (not on generator creation)
            _circuit_breaker.record_success()

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
                track_token_usage(model, in_tok, out_tok)
                log.debug(
                    "Streaming usage: model=%s in=%d out=%d cost=$%.4f",
                    model,
                    in_tok,
                    out_tok,
                    cost,
                )

                # Log cache hit/miss if available
                cache_create = getattr(final.usage, "cache_creation_input_tokens", 0)
                cache_read = getattr(final.usage, "cache_read_input_tokens", 0)
                if cache_create or cache_read:
                    log.debug(
                        "Streaming cache: create=%d read=%d",
                        cache_create,
                        cache_read,
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
                # circuit_breaker.record_success() is called inside the generator
                # after stream completes, not here on generator creation
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
