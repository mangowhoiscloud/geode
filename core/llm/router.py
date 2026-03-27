"""LLM Router — provider-aware dispatching for all LLM calls.

Replaces the monolithic client.py. Routes to the correct provider SDK
based on model name. Owns ContextVar DI definitions and LangSmith tracing.

Data types (ToolCallRecord, ToolUseResult) and re-exports from
token_tracker are kept here for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import os as _os
import re
import time
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

import anthropic
from pydantic import BaseModel

from core.config import (
    ANTHROPIC_FALLBACK_CHAIN,
    GLM_FALLBACK_CHAIN,
    OPENAI_FALLBACK_CHAIN,
    _resolve_provider,
    is_model_allowed,
    settings,
)
from core.llm.errors import (
    LLMAPIStatusError as LLMAPIStatusError,
)
from core.llm.errors import (
    LLMAuthenticationError as LLMAuthenticationError,
)
from core.llm.errors import (
    LLMBadRequestError as LLMBadRequestError,
)
from core.llm.errors import (
    LLMConnectionError as LLMConnectionError,
)
from core.llm.errors import (
    LLMInternalServerError as LLMInternalServerError,
)
from core.llm.errors import (
    LLMRateLimitError as LLMRateLimitError,
)
from core.llm.errors import (
    LLMTimeoutError as LLMTimeoutError,
)
from core.llm.fallback import MAX_RETRIES as MAX_RETRIES
from core.llm.fallback import RETRY_BASE_DELAY as RETRY_BASE_DELAY
from core.llm.fallback import RETRY_MAX_DELAY as RETRY_MAX_DELAY
from core.llm.fallback import CircuitBreaker as CircuitBreaker
from core.llm.fallback import retry_with_backoff_generic as retry_with_backoff_generic
from core.llm.providers.anthropic import (
    FALLBACK_MODELS as FALLBACK_MODELS,
)
from core.llm.providers.anthropic import (
    NON_RETRYABLE_ERRORS as _NON_RETRYABLE_ERRORS,
)
from core.llm.providers.anthropic import (
    RETRYABLE_ERRORS as _RETRYABLE_ERRORS,
)
from core.llm.providers.anthropic import (
    _build_httpx_limits as _build_httpx_limits,
)
from core.llm.providers.anthropic import (
    _build_httpx_timeout as _build_httpx_timeout,
)
from core.llm.providers.anthropic import (
    get_anthropic_client as get_anthropic_client,
)
from core.llm.providers.anthropic import (
    get_async_anthropic_client as get_async_anthropic_client,
)
from core.llm.providers.anthropic import (
    reset_clients as reset_clients,
)
from core.llm.providers.anthropic import (
    retry_with_backoff as _retry_with_backoff,
)
from core.llm.providers.anthropic import (
    system_with_cache as _system_with_cache,
)
from core.llm.token_tracker import MODEL_PRICING as MODEL_PRICING
from core.llm.token_tracker import LLMUsage as LLMUsage
from core.llm.token_tracker import LLMUsageAccumulator as LLMUsageAccumulator
from core.llm.token_tracker import calculate_cost as calculate_cost
from core.llm.token_tracker import get_tracker
from core.llm.token_tracker import get_usage_accumulator as get_usage_accumulator
from core.llm.token_tracker import reset_usage_accumulator as reset_usage_accumulator
from core.llm.token_tracker import track_token_usage as track_token_usage

log = logging.getLogger(__name__)

# Suppress langsmith/langchain rate-limit log spam (429 errors when quota exceeded)
logging.getLogger("langsmith").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# LangSmith tracing (Phase 5-A): LangChain standard env vars
# ---------------------------------------------------------------------------


def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is active (both gate + key required).

    Reads env vars at call time for testability.
    """
    tracing = _os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = _os.environ.get("LANGCHAIN_API_KEY") or _os.environ.get("LANGSMITH_API_KEY")
    return tracing and api_key is not None


def maybe_traceable(
    *,
    run_type: str = "llm",
    name: str | None = None,
) -> Any:
    """Return @traceable decorator if LangSmith is configured, else passthrough.

    Public API — used by domain/verification layers for LangSmith integration.
    """
    if is_langsmith_enabled():
        try:
            from langsmith import traceable

            return traceable(run_type=run_type, name=name)  # type: ignore[call-overload]
        except ImportError:
            pass

    def _identity(fn: Any) -> Any:
        return fn

    return _identity


# Backward compatibility alias (deprecated — use maybe_traceable)
_maybe_traceable = maybe_traceable


# ---------------------------------------------------------------------------
# Token usage recording helpers
# ---------------------------------------------------------------------------


def _record_response_usage(
    response: Any,
    model: str,
    *,
    label: str = "",
) -> LLMUsage | None:
    """Record token usage from an Anthropic response. Returns usage or None."""
    if not (hasattr(response, "usage") and response.usage):
        return None
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    usage = get_tracker().record(
        model,
        in_tok,
        out_tok,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
    )
    suffix = f" ({label})" if label else ""
    log.info(
        "LLM call%s: model=%s in=%d out=%d cost=$%.4f",
        suffix,
        model,
        in_tok,
        out_tok,
        usage.cost_usd,
    )
    if cache_create or cache_read:
        log.debug("Cache: create=%d read=%d", cache_create, cache_read)
    return usage


def _record_openai_usage(
    response: Any,
    model: str,
    *,
    label: str = "",
) -> LLMUsage | None:
    """Record token usage from an OpenAI-format response. Returns usage or None."""
    if not (hasattr(response, "usage") and response.usage):
        return None
    in_tok = response.usage.prompt_tokens or 0
    out_tok = response.usage.completion_tokens or 0
    usage = get_tracker().record(model, in_tok, out_tok)
    suffix = f" ({label})" if label else ""
    log.info(
        "LLM call%s: model=%s in=%d out=%d cost=$%.4f",
        suffix,
        model,
        in_tok,
        out_tok,
        usage.cost_usd,
    )
    return usage


# ---------------------------------------------------------------------------
# call_with_failover — async model failover for AgenticLoop
# ---------------------------------------------------------------------------


async def call_with_failover(
    models: list[str],
    call_fn: Any,
    *,
    max_retries: int | None = None,
    retry_base_delay: float | None = None,
    retry_max_delay: float | None = None,
) -> tuple[Any | None, str | None]:
    """Execute an async LLM call with model failover chain.

    Iterates through the ``models`` list. For each model, retries on
    retryable errors (rate-limit, timeout, connection, server errors)
    with exponential backoff. If all retries for a model are exhausted,
    moves to the next model in the chain.

    Non-retryable errors (e.g. AuthenticationError) cause immediate failure
    without trying further models.

    Args:
        models: Ordered list of model names to try.
        call_fn: Async callable ``(model: str) -> response``.
        max_retries: Per-model retry count (default: settings.llm_max_retries).
        retry_base_delay: Base delay in seconds (default: settings.llm_retry_base_delay).
        retry_max_delay: Max delay cap in seconds (default: settings.llm_retry_max_delay).

    Returns:
        A tuple of ``(response, model_used)``. On complete failure,
        returns ``(None, None)``.
    """
    import asyncio as _asyncio

    _max_retries = max_retries if max_retries is not None else MAX_RETRIES
    _base_delay = retry_base_delay if retry_base_delay is not None else RETRY_BASE_DELAY
    _max_delay = retry_max_delay if retry_max_delay is not None else RETRY_MAX_DELAY

    # Filter models by policy (GAP 2: model-policy.toml governance)
    allowed_models = [m for m in models if is_model_allowed(m)]
    if not allowed_models:
        log.error("Failover: all models blocked by policy: %s", models)
        return None, None

    last_error: Exception | None = None

    for model_idx, current_model in enumerate(allowed_models):
        for attempt in range(_max_retries):
            try:
                result = await call_fn(current_model)
                return result, current_model
            except _NON_RETRYABLE_ERRORS as exc:
                # Non-retryable: fail immediately, do not try other models
                log.warning(
                    "Non-retryable error on model=%s: %s — aborting failover",
                    current_model,
                    type(exc).__name__,
                )
                return None, None
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                wait = min(_base_delay * (2**attempt), _max_delay)
                log.debug(
                    "Failover: model=%s attempt=%d/%d error=%s, retrying in %.1fs",
                    current_model,
                    attempt + 1,
                    _max_retries,
                    type(exc).__name__,
                    wait,
                )
                if attempt < _max_retries - 1:
                    await _asyncio.sleep(wait)
            except Exception as exc:
                # Unexpected error: log and move on to next model
                last_error = exc
                log.debug(
                    "Failover: unexpected error on model=%s: %s",
                    current_model,
                    exc,
                )
                break  # break retry loop, try next model

        # All retries exhausted for this model
        if model_idx < len(allowed_models) - 1:
            next_model = allowed_models[model_idx + 1]
            log.info(
                "Failover: model=%s exhausted, falling back to %s",
                current_model,
                next_model,
            )

    log.error(
        "Failover: all models exhausted. Last error: %s",
        last_error,
    )
    return None, None


# ---------------------------------------------------------------------------
# Provider-aware helpers — route to correct SDK based on model provider
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Provider dispatch — single source of truth for per-provider configurations.
# Replaces 6 individual _get_provider_*() functions (Kent Beck DRY).
# ---------------------------------------------------------------------------

# Per-provider circuit breakers (must be module-level singletons)
_openai_cb = CircuitBreaker()
_glm_cb = CircuitBreaker()


def _openai_retryable() -> tuple[type[Exception], ...]:
    import openai

    return (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)


def _openai_bad_request() -> type[Exception]:
    import openai

    return openai.BadRequestError


# Lazy dispatch table — callables to avoid import-time side effects
_PROVIDER_DISPATCH: dict[str, dict[str, Any]] = {
    "anthropic": {
        "get_client": lambda: get_anthropic_client(),
        "fallback_chain": lambda: list(ANTHROPIC_FALLBACK_CHAIN),
        "retryable_errors": lambda: _RETRYABLE_ERRORS,
        "bad_request_error": lambda: anthropic.BadRequestError,
        "circuit_breaker": lambda: __import__(
            "core.llm.providers.anthropic", fromlist=["get_circuit_breaker"]
        ).get_circuit_breaker(),
    },
    "openai": {
        "get_client": lambda: __import__(
            "core.llm.providers.openai", fromlist=["_get_openai_client"]
        )._get_openai_client(),
        "fallback_chain": lambda: list(OPENAI_FALLBACK_CHAIN),
        "retryable_errors": _openai_retryable,
        "bad_request_error": _openai_bad_request,
        "circuit_breaker": lambda: _openai_cb,
    },
    "glm": {
        "get_client": lambda: __import__(
            "core.llm.providers.glm", fromlist=["_get_glm_client"]
        )._get_glm_client(),
        "fallback_chain": lambda: list(GLM_FALLBACK_CHAIN),
        "retryable_errors": _openai_retryable,  # GLM uses openai SDK
        "bad_request_error": _openai_bad_request,
        "circuit_breaker": lambda: _glm_cb,
    },
}


def _get_provider_config(provider: str, key: str) -> Any:
    """Lookup a provider-specific configuration by key.

    Valid keys: get_client, fallback_chain, retryable_errors,
    bad_request_error, circuit_breaker.
    """
    dispatch = _PROVIDER_DISPATCH.get(provider)
    if dispatch is None:
        raise ValueError(f"Unsupported provider: {provider}")
    factory = dispatch.get(key)
    if factory is None:
        raise KeyError(f"Unknown config key '{key}' for provider '{provider}'")
    return factory()


# Convenience wrappers (preserve existing call sites)
def _get_provider_client(provider: str) -> Any:
    return _get_provider_config(provider, "get_client")


def _get_fallback_chain(provider: str) -> list[str]:
    result: list[str] = _get_provider_config(provider, "fallback_chain")
    return result


def _get_provider_retryable_errors(provider: str) -> tuple[type[Exception], ...]:
    result: tuple[type[Exception], ...] = _get_provider_config(provider, "retryable_errors")
    return result


def _get_provider_bad_request_error(provider: str) -> type[Exception] | None:
    result: type[Exception] | None = _get_provider_config(provider, "bad_request_error")
    return result


def _get_provider_circuit_breaker(provider: str) -> CircuitBreaker:
    result: CircuitBreaker = _get_provider_config(provider, "circuit_breaker")
    return result


def _retry_provider_aware(
    fn: Any,
    *,
    model: str,
    provider: str,
) -> Any:
    """Execute fn with retry + backoff + fallback, provider-aware."""
    fallback = _get_fallback_chain(provider)
    candidates = [model] + [m for m in fallback if m != model]
    models_to_try = [m for m in candidates if is_model_allowed(m)]
    if not models_to_try:
        raise RuntimeError(f"All models blocked by policy: {candidates}")

    return retry_with_backoff_generic(
        fn,
        model=models_to_try[0],
        fallback_models=models_to_try[1:],
        circuit_breaker=_get_provider_circuit_breaker(provider),
        retryable_errors=_get_provider_retryable_errors(provider),
        bad_request_error=_get_provider_bad_request_error(provider),
        billing_message=f"{provider} API billing/credit error.",
        provider_label=provider.upper(),
    )


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main API functions — provider-aware routing
# ---------------------------------------------------------------------------

T = TypeVar("T", bound=BaseModel)


@maybe_traceable(run_type="llm", name="call_llm")  # type: ignore[untyped-decorator]
def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> str:
    """Synchronous LLM call with provider-aware routing and failover.

    Routes to Anthropic, OpenAI, or GLM SDK based on the model name.
    Returns text content.
    """
    target_model = model or settings.model
    provider = _resolve_provider(target_model)

    if seed is not None:
        log.info("Reproducibility seed=%d requested (logged for auditing)", seed)

    # Non-Anthropic providers: use OpenAI-compatible SDK
    if provider != "anthropic":
        oa_client = _get_provider_client(provider)

        def _do_call_openai(*, model: str) -> str:
            response = oa_client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=120.0,
            )
            _record_openai_usage(response, model)
            choice = response.choices[0]
            return choice.message.content or ""

        result: str = _retry_provider_aware(_do_call_openai, model=target_model, provider=provider)
        return result

    # Anthropic path (original)
    client = get_anthropic_client()
    system_cached = _system_with_cache(system)

    def _do_call(*, model: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
        )
        _record_response_usage(response, model)

        block = response.content[0]
        if not hasattr(block, "text"):
            raise TypeError(f"Expected TextBlock, got {type(block)}")
        return block.text

    result = _retry_with_backoff(_do_call, model=target_model)
    return result


@maybe_traceable(run_type="llm", name="call_llm_parsed")  # type: ignore[untyped-decorator]
def call_llm_parsed(  # noqa: UP047 — PEP695 syntax requires Python 3.12+
    system: str,
    user: str,
    *,
    output_model: type[T],
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> T:
    """LLM call with provider-aware structured output routing."""
    target_model = model or settings.model
    provider = _resolve_provider(target_model)

    # Non-Anthropic providers: use OpenAI-compatible beta.chat.completions.parse()
    if provider != "anthropic":
        oa_client = _get_provider_client(provider)

        def _do_call_openai(*, model: str) -> T:
            response = oa_client.beta.chat.completions.parse(
                model=model,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=output_model,
                timeout=120.0,
            )
            _record_openai_usage(response, model, label="parsed")

            choice = response.choices[0]
            if choice.message.parsed is None:
                raise ValueError(
                    "LLM returned no structured output. "
                    "Verify the prompt constrains the response format "
                    "and the Pydantic model matches the schema."
                )
            return choice.message.parsed  # type: ignore[no-any-return]

        result: T = _retry_provider_aware(_do_call_openai, model=target_model, provider=provider)
        return result

    # Anthropic path (original)
    client = get_anthropic_client()
    system_cached = _system_with_cache(system)

    def _do_call(*, model: str) -> T:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_cached,
            messages=[{"role": "user", "content": user}],
            output_format=output_model,
        )
        _record_response_usage(response, model, label="parsed")

        if response.parsed_output is None:
            raise ValueError(
                "LLM returned no structured output. "
                "Verify the prompt constrains the response format "
                "and the Pydantic model matches the schema."
            )
        return response.parsed_output

    result = _retry_with_backoff(_do_call, model=target_model)
    return result


@maybe_traceable(run_type="llm", name="call_llm_json")  # type: ignore[untyped-decorator]
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


@maybe_traceable(run_type="chain", name="call_llm_with_tools")  # type: ignore[untyped-decorator]
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
    """LLM call with tool-use loop and provider-aware routing."""
    target_model = model or settings.model
    provider = _resolve_provider(target_model)

    # Non-Anthropic providers: delegate to OpenAIAdapter.generate_with_tools
    if provider != "anthropic":
        from core.llm.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter(default_model=target_model)
        # Override client for GLM provider
        if provider == "glm":
            from core.llm.providers import openai as _openai_provider

            orig_get = _openai_provider._get_openai_client

            def _glm_client_override() -> Any:
                return _get_provider_client("glm")

            _openai_provider._get_openai_client = _glm_client_override
            try:
                oai_result: ToolUseResult = adapter.generate_with_tools(
                    system,
                    user,
                    tools=tools,
                    tool_executor=tool_executor,
                    model=target_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    max_tool_rounds=max_tool_rounds,
                )
                return oai_result
            finally:
                _openai_provider._get_openai_client = orig_get
        else:
            oai_result2: ToolUseResult = adapter.generate_with_tools(
                system,
                user,
                tools=tools,
                tool_executor=tool_executor,
                model=target_model,
                max_tokens=max_tokens,
                temperature=temperature,
                max_tool_rounds=max_tool_rounds,
            )
            return oai_result2

    # Anthropic path (original)
    client = get_anthropic_client()
    system_cached = _system_with_cache(system)

    all_tool_calls: list[ToolCallRecord] = []
    all_usage: list[LLMUsage] = []
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    # Apply cache_control to tool definitions for Anthropic prompt caching
    cached_tools: list[dict[str, Any]] = []
    for i, tool in enumerate(tools):
        tool_copy = dict(tool)
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
            )

        response = _retry_with_backoff(_do_call, model=target_model)

        # Track usage
        usage = _record_response_usage(response, target_model, label="tools")
        if usage is not None:
            all_usage.append(usage)

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
                tool_output: dict[str, Any] = tool_executor(tool_name, **tool_input)
            except Exception as exc:
                log.warning("Tool '%s' execution failed: %s", tool_name, exc)
                tool_output = {"error": str(exc)}
            elapsed_ms = (time.time() - t0) * 1000

            all_tool_calls.append(
                ToolCallRecord(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_result=tool_output,
                    duration_ms=elapsed_ms,
                )
            )
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(tool_output),
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


@maybe_traceable(run_type="llm", name="call_llm_streaming")  # type: ignore[untyped-decorator]
def call_llm_streaming(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> Iterator[str]:
    """Streaming Claude call with failover. Yields text deltas."""
    from core.llm.providers.anthropic import get_circuit_breaker

    client = get_anthropic_client()
    target_model = model or settings.model
    circuit_breaker = get_circuit_breaker()

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

            # Record success AFTER stream completes
            circuit_breaker.record_success()

            # Capture token usage from the stream's final response
            final = stream.get_final_message()
            if final:
                _record_response_usage(final, model, label="stream")

    # Circuit breaker check
    if not circuit_breaker.can_execute():
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
    circuit_breaker.record_failure()
    raise last_error


# ---------------------------------------------------------------------------
# LLMClientPort — Protocol interface for LLM provider adapters
# ---------------------------------------------------------------------------

T2 = TypeVar("T2", bound=BaseModel)


@runtime_checkable
class LLMClientPort(Protocol):
    """Protocol for LLM client adapters.

    Implementations: ClaudeAdapter (router functions), OpenAIAdapter, MockAdapter.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        ...

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str: ...

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T2],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T2: ...

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]: ...

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
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Lightweight callable protocols for node-level DI
# ---------------------------------------------------------------------------


class LLMJsonCallable(Protocol):
    """Callable that returns parsed JSON from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> dict[str, Any]: ...


class LLMTextCallable(Protocol):
    """Callable that returns raw text from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> str: ...


class LLMParsedCallable(Protocol):
    """Callable that returns a Pydantic model instance from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T2],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> T2: ...


class LLMToolCallable(Protocol):
    """Callable that runs a tool-use loop with an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        max_tool_rounds: int = ...,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Thread-safe injection via contextvars
# ---------------------------------------------------------------------------

_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar("llm_json", default=None)
_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar("llm_parsed", default=None)
_llm_tool_ctx: ContextVar[LLMToolCallable | None] = ContextVar("llm_tool", default=None)

# Secondary LLM contextvars for ensemble/cross-LLM mode
_secondary_llm_json_ctx: ContextVar[LLMJsonCallable | None] = ContextVar(
    "secondary_llm_json", default=None
)
_secondary_llm_parsed_ctx: ContextVar[LLMParsedCallable | None] = ContextVar(
    "secondary_llm_parsed", default=None
)


def set_llm_callable(
    json_fn: LLMJsonCallable,
    text_fn: LLMTextCallable,
    parsed_fn: LLMParsedCallable | None = None,
    tool_fn: LLMToolCallable | None = None,
    secondary_json_fn: LLMJsonCallable | None = None,
    secondary_parsed_fn: LLMParsedCallable | None = None,
) -> None:
    """Inject LLM callables (typically called by GeodeRuntime.create())."""
    _llm_json_ctx.set(json_fn)
    if parsed_fn is not None:
        _llm_parsed_ctx.set(parsed_fn)
    if tool_fn is not None:
        _llm_tool_ctx.set(tool_fn)
    # Always update secondary contextvars (set to None to clear if not provided)
    _secondary_llm_json_ctx.set(secondary_json_fn)
    _secondary_llm_parsed_ctx.set(secondary_parsed_fn)


def get_llm_json() -> LLMJsonCallable:
    """Return the injected JSON callable. Raises if not injected."""
    fn = _llm_json_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM JSON callable not injected. "
            "Call set_llm_callable() first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_parsed() -> LLMParsedCallable:
    """Return the injected parsed callable. Raises if not injected."""
    fn = _llm_parsed_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM parsed callable not injected. "
            "Call set_llm_callable(parsed_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_llm_tool() -> LLMToolCallable:
    """Return the injected tool-use callable. Raises if not injected."""
    fn = _llm_tool_ctx.get()
    if fn is None:
        raise RuntimeError(
            "LLM tool callable not injected. "
            "Call set_llm_callable(tool_fn=...) first (done by GeodeRuntime.create())."
        )
    return fn


def get_secondary_llm_json() -> LLMJsonCallable | None:
    """Return the secondary JSON callable, or None if not configured."""
    return _secondary_llm_json_ctx.get()


def get_secondary_llm_parsed() -> LLMParsedCallable | None:
    """Return the secondary parsed callable, or None if not configured."""
    return _secondary_llm_parsed_ctx.get()


# ---------------------------------------------------------------------------
# AgenticLLMPort — Protocol interface for agentic loop LLM adapters
# ---------------------------------------------------------------------------

from core.cli.agentic_response import AgenticResponse  # noqa: E402


@runtime_checkable
class AgenticLLMPort(Protocol):
    """Protocol for agentic loop LLM calls.

    Implementations: ClaudeAgenticAdapter, OpenAIAgenticAdapter, GlmAgenticAdapter.
    """

    @property
    def provider_name(self) -> str: ...

    @property
    def fallback_chain(self) -> list[str]: ...

    async def agentic_call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, str] | str,
        max_tokens: int,
        temperature: float,
    ) -> AgenticResponse | None: ...

    def reset_client(self) -> None: ...


# ---------------------------------------------------------------------------
# resolve_agentic_adapter — factory + cross-provider fallback map
# ---------------------------------------------------------------------------

import importlib  # noqa: E402

from core.config import ANTHROPIC_PRIMARY, OPENAI_PRIMARY  # noqa: E402

# Provider -> "module_path:ClassName"
_ADAPTER_MAP: dict[str, str] = {
    "anthropic": "core.llm.providers.anthropic:ClaudeAgenticAdapter",
    "openai": "core.llm.providers.openai:OpenAIAgenticAdapter",
    "glm": "core.llm.providers.glm:GlmAgenticAdapter",
}

# Cross-provider fallback: when a provider's chain is exhausted, try these.
# GLM -> OpenAI -> Anthropic (Bug #6 fix: add Anthropic path for GLM)
CROSS_PROVIDER_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "anthropic": [("openai", OPENAI_PRIMARY)],
    "openai": [("anthropic", ANTHROPIC_PRIMARY)],
    "glm": [("openai", OPENAI_PRIMARY), ("anthropic", ANTHROPIC_PRIMARY)],
}

_router_log = logging.getLogger(__name__)


def resolve_agentic_adapter(provider: str) -> AgenticLLMPort:
    """Create an agentic adapter for the given provider.

    Uses dynamic import to avoid loading unused providers.
    """
    entry = _ADAPTER_MAP.get(provider)
    if entry is None:
        # Unknown provider -> default to OpenAI-compatible
        _router_log.warning("Unknown provider '%s', defaulting to openai adapter", provider)
        entry = _ADAPTER_MAP["openai"]

    module_path, class_name = entry.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    adapter: AgenticLLMPort = cls()
    return adapter


# ---------------------------------------------------------------------------
# ClaudeAdapter — thin wrapper that delegates to router functions
# ---------------------------------------------------------------------------


class ClaudeAdapter:
    """Anthropic Claude adapter implementing LLMClientPort.

    Wraps the router functions into the port interface.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        return settings.model

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        result: str = call_llm(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
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
        result: dict[str, Any] = call_llm_json(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
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
        return call_llm_parsed(  # type: ignore[no-any-return]
            system,
            user,
            output_model=output_model,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]:
        return call_llm_streaming(  # type: ignore[no-any-return]
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )

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
    ) -> Any:
        result: ToolUseResult = call_llm_with_tools(
            system,
            user,
            tools=tools,
            tool_executor=tool_executor,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
        )
        return result
