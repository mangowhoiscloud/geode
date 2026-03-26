"""OpenAI provider — client lifecycle + retry wrapper.

Merged from core.infrastructure.adapters.llm.openai_adapter.
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

from core.config import OPENAI_FALLBACK_CHAIN, OPENAI_PRIMARY, settings
from core.llm.fallback import (
    CircuitBreaker,
    retry_with_backoff_generic,
)
from core.llm.token_tracker import LLMUsage, get_tracker

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

# OpenAI retryable errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

# Default OpenAI model — from config.py single source of truth
DEFAULT_OPENAI_MODEL = OPENAI_PRIMARY

# OpenAI fallback chain — from config.py single source of truth
OPENAI_FALLBACK_MODELS = OPENAI_FALLBACK_CHAIN


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


def reset_openai_client() -> None:
    """Reset cached OpenAI client (e.g. after /key openai changes)."""
    global _openai_client
    with _openai_lock:
        _openai_client = None


def _get_retryable_errors() -> tuple[type[Exception], ...]:
    """Get retryable error types from openai SDK."""
    import openai

    return (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


def get_circuit_breaker() -> CircuitBreaker:
    """Return the module-level OpenAI circuit breaker."""
    return _openai_circuit_breaker


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
                timeout=120.0,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                # Final chunk carries usage when stream_options includes usage
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    in_tok = chunk.usage.prompt_tokens or 0
                    out_tok = chunk.usage.completion_tokens or 0
                    get_tracker().record(model, in_tok, out_tok)

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
    ) -> Any:
        """OpenAI tool-use loop. Mirrors ClaudeAdapter pattern."""
        from core.llm.router import ToolCallRecord, ToolUseResult

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
                    timeout=120.0,
                )

            response = self._retry_with_backoff(_do_call, model=target)

            # Track usage
            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                usage = get_tracker().record(target, in_tok, out_tok)
                all_usage.append(usage)

            choice = response.choices[0]

            # No tool calls -> return text
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
        """Retry with exponential backoff + model fallback + circuit breaker.

        Delegates to the shared ``retry_with_backoff_generic`` from fallback.py.
        """
        import openai

        return retry_with_backoff_generic(
            fn,
            model=model,
            fallback_models=list(OPENAI_FALLBACK_MODELS),
            circuit_breaker=_openai_circuit_breaker,
            retryable_errors=_get_retryable_errors(),
            bad_request_error=openai.BadRequestError,
            billing_message=(
                "OpenAI API billing/credit error. Check your OpenAI account billing settings."
            ),
            max_retries=_MAX_RETRIES,
            retry_base_delay=_RETRY_BASE_DELAY,
            retry_max_delay=_RETRY_MAX_DELAY,
            provider_label="OpenAI",
        )


# ---------------------------------------------------------------------------
# OpenAIAgenticAdapter — OpenAI-compatible LLM adapter for agentic loop
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

import httpx  # noqa: E402


class OpenAIAgenticAdapter:
    """OpenAI agentic adapter (P1 Gateway pattern).

    TODO(v0.30+): Migrate to OpenAI Responses API for native web_search_preview,
    code_interpreter, file_search, and other hosted tools.

    Subclass for GLM, Qwen, etc. Override ``_resolve_config()`` and
    ``fallback_chain`` for provider-specific settings.

    Features:
    - Anthropic->OpenAI message format conversion
    - Anthropic->OpenAI tool schema conversion
    - httpx connection pool (parity with Anthropic adapter)
    - CircuitBreaker
    - KeyboardInterrupt -> UserCancelledError
    """

    def __init__(self) -> None:
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        self._circuit_breaker = CircuitBreaker()

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def fallback_chain(self) -> list[str]:
        return list(OPENAI_FALLBACK_CHAIN)

    def _resolve_config(self, model: str) -> tuple[str, str | None]:
        """Return (api_key, base_url) for this provider. Override in subclasses."""
        return settings.openai_api_key, None

    def _ensure_client(self, model: str) -> Any:
        """Lazy-create or re-create client if base_url changed."""
        from core.llm.providers.anthropic import _build_httpx_limits, _build_httpx_timeout

        api_key, base_url = self._resolve_config(model)
        if not api_key:
            return None

        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    import openai as _openai

                    http_client = httpx.Client(
                        limits=_build_httpx_limits(),
                        timeout=_build_httpx_timeout(),
                    )
                    kwargs: dict[str, Any] = {
                        "api_key": api_key,
                        "max_retries": 0,
                        "http_client": http_client,
                    }
                    if base_url:
                        kwargs["base_url"] = base_url
                    self._client = _openai.OpenAI(**kwargs)
        return self._client

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
    ) -> Any | None:
        from core.llm.errors import UserCancelledError
        from core.llm.router import call_with_failover

        client = self._ensure_client(model)
        if client is None:
            log.warning("No API key for %s agentic loop", self.provider_name)
            return None

        if not self._circuit_breaker.can_execute():
            log.warning("%s circuit breaker is OPEN, skipping call", self.provider_name)
            return None

        # OpenAI tool_choice is a string
        tc_val = tool_choice.get("type", "auto") if isinstance(tool_choice, dict) else tool_choice

        oai_tools = _tools_to_openai(tools)
        oai_messages = _convert_messages_to_openai(system, messages)
        failover_models = [model] + [m for m in self.fallback_chain if m != model]

        async def _do_call(m: str) -> Any:
            return await asyncio.to_thread(
                client.chat.completions.create,
                model=m,
                messages=oai_messages,
                tools=oai_tools if oai_tools else None,
                tool_choice=tc_val if oai_tools else None,
                max_completion_tokens=max_tokens,
                temperature=temperature,
                timeout=120.0,
            )

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except Exception:
            log.warning("%s agentic LLM call failed", self.provider_name, exc_info=True)
            self._circuit_breaker.record_failure()
            return None

        if response is None:
            self._circuit_breaker.record_failure()
            return None

        self._circuit_breaker.record_success()

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        from core.cli.agentic_response import normalize_openai

        return normalize_openai(response)

    def reset_client(self) -> None:
        with self._client_lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    log.debug("Error closing %s httpx client", self.provider_name, exc_info=True)
            self._client = None


# ---------------------------------------------------------------------------
# Format converters (Anthropic -> OpenAI)
# ---------------------------------------------------------------------------


def _tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic tool definitions to OpenAI function-calling format."""
    result: list[dict[str, Any]] = []
    for t in tools:
        name = t.get("name", "")
        if not name:
            continue
        fn: dict[str, Any] = {
            "name": name,
            "description": t.get("description", ""),
        }
        schema = t.get("input_schema")
        if schema:
            fn["parameters"] = schema
        result.append({"type": "function", "function": fn})
    return result


def _convert_messages_to_openai(
    system: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to OpenAI chat format."""
    result: list[dict[str, Any]] = []

    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if role == "assistant":
            result.append(_convert_assistant_msg(content))
        elif role == "user":
            result.extend(_convert_user_msg(content))
        else:
            result.append({"role": role, "content": str(content) if content else ""})

    return result


def _convert_assistant_msg(content: Any) -> dict[str, Any]:
    """Convert Anthropic assistant message to OpenAI format."""
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    if not isinstance(content, list):
        return {"role": "assistant", "content": str(content) if content else ""}

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    }
                )

    msg: dict[str, Any] = {"role": "assistant"}
    msg["content"] = "\n".join(text_parts) if text_parts else None
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _convert_user_msg(content: Any) -> list[dict[str, Any]]:
    """Convert Anthropic user message to OpenAI format."""
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        return [{"role": "user", "content": str(content) if content else ""}]

    result: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "tool_result":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    }
                )
            elif block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            else:
                text_parts.append(str(block))
        else:
            text_parts.append(str(block))

    if text_parts:
        result.append({"role": "user", "content": "\n".join(text_parts)})

    return result if result else [{"role": "user", "content": ""}]
