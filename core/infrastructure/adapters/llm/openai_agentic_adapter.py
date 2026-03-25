"""OpenAIAgenticAdapter — OpenAI-compatible LLM adapter for agentic loop.

Base adapter for all OpenAI-compatible providers (OpenAI, GLM, etc.).
Handles Anthropic→OpenAI message/tool conversion, httpx pool, circuit breaker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import httpx

from core.cli.agentic_response import AgenticResponse, normalize_openai
from core.config import OPENAI_FALLBACK_CHAIN, settings
from core.infrastructure.ports.agentic_llm_port import UserCancelledError
from core.llm.client import (
    CircuitBreaker,
    _build_httpx_limits,
    _build_httpx_timeout,
    call_with_failover,
)

log = logging.getLogger(__name__)


class OpenAIAgenticAdapter:
    """OpenAI agentic adapter (P1 Gateway pattern).

    Subclass for GLM, Qwen, etc. Override ``_resolve_config()`` and
    ``fallback_chain`` for provider-specific settings.

    Features:
    - Anthropic→OpenAI message format conversion
    - Anthropic→OpenAI tool schema conversion
    - httpx connection pool (parity with Anthropic adapter)
    - CircuitBreaker
    - KeyboardInterrupt → UserCancelledError
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
        api_key, base_url = self._resolve_config(model)
        if not api_key:
            return None

        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    import openai

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
                    self._client = openai.OpenAI(**kwargs)
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
    ) -> AgenticResponse | None:
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
# Format converters (Anthropic → OpenAI)
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
    """Convert Anthropic assistant message to OpenAI format.

    tool_use blocks → tool_calls with arguments as JSON string.
    """
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
    """Convert Anthropic user message to OpenAI format.

    tool_result blocks → separate role:"tool" messages with tool_call_id.
    """
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
