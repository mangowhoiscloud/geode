"""OpenAI provider — client lifecycle + retry wrapper.

Merged from core.infrastructure.adapters.llm.openai_adapter.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from core.config import OPENAI_FALLBACK_CHAIN, OPENAI_PRIMARY
from core.llm.fallback import (
    retry_with_backoff_generic,
    retry_with_backoff_generic_async,
)
from core.llm.token_tracker import LLMUsage, get_tracker

if TYPE_CHECKING:
    # Pydantic is a heavy import (~100 ms cumulative). The ``BaseModel``
    # bound is only consumed by mypy so a forward-reference string keeps
    # runtime free of the pydantic tree.
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")

log = logging.getLogger(__name__)

# Retry policy values (max_retries / retry_base_delay / retry_max_delay) are
# resolved lazily from ``core.config.settings.llm_*`` inside
# ``retry_with_backoff_generic`` (fallback.py).  Keeping a single source of
# truth ensures runtime ``settings.llm_max_retries`` tuning reaches every
# provider — previously OpenAI/GLM passed module-local constants that pinned
# them to ``3`` regardless of configuration.

# Default OpenAI model — from config.py single source of truth
DEFAULT_OPENAI_MODEL = OPENAI_PRIMARY

# OpenAI fallback chain — from config.py single source of truth
OPENAI_FALLBACK_MODELS = OPENAI_FALLBACK_CHAIN


_openai_client: Any = None  # openai.OpenAI | None — lazy import
_openai_lock = threading.Lock()
_async_openai_client: Any = None  # openai.AsyncOpenAI | None — lazy import
_async_openai_lock = threading.Lock()


def _resolve_openai_key() -> str:
    """Resolve OpenAI API key from ProfileRotator (OAuth preferred) or settings."""
    from core.config import settings
    from core.llm.credentials import resolve_provider_key

    return resolve_provider_key("openai", settings.openai_api_key)


def _get_openai_client() -> Any:
    """Lazy import and return cached OpenAI client (thread-safe).

    PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28, Codex MCP MED) —
    ``max_retries=0`` matches the adapter-side invariant
    (``_openai_common.build_async_openai_client``) so legacy callers that
    still hit this singleton (paperclip ``OpenAIAdapter``,
    ``llm_extract_learning``, ``models.py``) don't compound SDK + app
    retry loops on stalled streams.
    """
    global _openai_client
    if _openai_client is None:
        with _openai_lock:
            if _openai_client is None:
                import openai

                _openai_client = openai.OpenAI(api_key=_resolve_openai_key(), max_retries=0)
    return _openai_client


def _get_async_openai_client() -> Any:
    """Lazy import and return cached async OpenAI client (thread-safe).

    See :func:`_get_openai_client` for the ``max_retries=0`` rationale.
    """
    global _async_openai_client
    if _async_openai_client is None:
        with _async_openai_lock:
            if _async_openai_client is None:
                import openai

                _async_openai_client = openai.AsyncOpenAI(
                    api_key=_resolve_openai_key(), max_retries=0
                )
    return _async_openai_client


def reset_openai_client() -> None:
    """Reset cached OpenAI client (e.g. after /key openai changes)."""
    global _async_openai_client, _openai_client
    with _openai_lock:
        _openai_client = None
    with _async_openai_lock:
        _async_openai_client = None


def _get_retryable_errors() -> tuple[type[Exception], ...]:
    """Get retryable error types from openai SDK."""
    import openai

    return (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


async def _run_tool_executor_async(
    tool_executor: Callable[..., Any],
    tool_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Run sync or async tool executors without blocking the event loop."""
    if inspect.iscoroutinefunction(tool_executor):
        raw = await tool_executor(tool_name, **tool_input)
    else:
        raw = await asyncio.to_thread(tool_executor, tool_name, **tool_input)

    if inspect.isawaitable(raw):
        raw = await raw
    return raw if isinstance(raw, dict) else {"result": raw}


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
                timeout=120.0,
            )
            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                get_tracker().record(model, in_tok, out_tok)

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
                timeout=120.0,
            )
            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                get_tracker().record(model, in_tok, out_tok)

            choice = response.choices[0]
            if choice.message.parsed is None:
                raise ValueError("OpenAI returned null parsed output")
            return cast(T, choice.message.parsed)

        result: T = self._retry_with_backoff(_do_call, model=target)
        return result

    async def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        client = _get_async_openai_client()
        target_model = model or self._default_model

        async def _do_stream(*, model: str) -> Any:
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
                timeout=120.0,
            )
            if inspect.isawaitable(response):
                return await response
            return response

        stream = await self._aretry_with_backoff(_do_stream, model=target_model)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if hasattr(chunk, "usage") and chunk.usage is not None:
                in_tok = chunk.usage.prompt_tokens or 0
                out_tok = chunk.usage.completion_tokens or 0
                get_tracker().record(target_model, in_tok, out_tok)

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        """OpenAI-compatible async tool-use loop."""
        from core.llm.router import ToolCallRecord, ToolUseResult

        client = _get_async_openai_client()
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

            async def _do_call(*, model: str, _tc: str = tool_choice) -> Any:
                response = client.chat.completions.create(
                    model=model,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                    tools=tools,
                    tool_choice=_tc,
                    timeout=120.0,
                )
                if inspect.isawaitable(response):
                    return await response
                return response

            response = await self._aretry_with_backoff(_do_call, model=target)

            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                usage = get_tracker().record(target, in_tok, out_tok)
                all_usage.append(usage)

            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                return ToolUseResult(
                    text=choice.message.content or "",
                    tool_calls=all_tool_calls,
                    usage=all_usage,
                    rounds=round_idx + 1,
                )

            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                t0 = time.time()
                try:
                    result = await _run_tool_executor_async(tool_executor, func_name, func_args)
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
        """Retry with exponential backoff + model fallback.

        Delegates to the shared ``retry_with_backoff_generic`` from fallback.py.
        """
        import openai

        return retry_with_backoff_generic(
            fn,
            model=model,
            fallback_models=list(OPENAI_FALLBACK_MODELS),
            retryable_errors=_get_retryable_errors(),
            bad_request_error=openai.BadRequestError,
            billing_message=(
                "OpenAI API billing/credit error. Check your OpenAI account billing settings."
            ),
            provider_label="OpenAI",
        )

    async def _aretry_with_backoff(self, fn: Any, *, model: str) -> Any:
        """Async retry with exponential backoff + model fallback."""
        import openai

        return await retry_with_backoff_generic_async(
            fn,
            model=model,
            fallback_models=list(OPENAI_FALLBACK_MODELS),
            retryable_errors=_get_retryable_errors(),
            bad_request_error=openai.BadRequestError,
            billing_message=(
                "OpenAI API billing/credit error. Check your OpenAI account billing settings."
            ),
            provider_label="OpenAI",
        )
