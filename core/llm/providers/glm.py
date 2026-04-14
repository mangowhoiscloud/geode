"""ZhipuAI GLM provider — OpenAI-compatible API with custom base_url.

Separate provider for GLM models (glm-5, glm-5-turbo, glm-4.7-flash).
Uses OpenAI SDK but managed as an independent provider with its own
client lifecycle, circuit breaker, and failover chain.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import GLM_BASE_URL, GLM_FALLBACK_CHAIN, GLM_PRIMARY, settings
from core.llm.fallback import CircuitBreaker

log = logging.getLogger(__name__)

# Default GLM model — from config.py single source of truth
DEFAULT_GLM_MODEL = GLM_PRIMARY

# GLM fallback chain — from config.py single source of truth
GLM_FALLBACK_MODELS = GLM_FALLBACK_CHAIN

_glm_client: Any = None  # openai.OpenAI | None — GLM via OpenAI-compatible API
_glm_lock = threading.Lock()

# Circuit breaker for GLM API calls
_glm_circuit_breaker = CircuitBreaker()


def _get_glm_client() -> Any:
    """Lazy import and return cached GLM client (OpenAI-compatible, thread-safe).

    Uses double-checked locking pattern consistent with _get_openai_client().
    """
    global _glm_client
    if _glm_client is None:
        with _glm_lock:
            if _glm_client is None:
                import openai

                _glm_client = openai.OpenAI(
                    api_key=settings.zai_api_key,
                    base_url=GLM_BASE_URL,
                )
    return _glm_client


def reset_glm_client() -> None:
    """Reset cached GLM client (e.g. after /key glm changes)."""
    global _glm_client
    with _glm_lock:
        _glm_client = None


def get_circuit_breaker() -> CircuitBreaker:
    """Return the module-level GLM circuit breaker."""
    return _glm_circuit_breaker


# ---------------------------------------------------------------------------
# GlmAgenticAdapter — ZhipuAI GLM adapter for agentic loop
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

from core.llm.errors import UserCancelledError  # noqa: E402
from core.llm.providers.openai import (  # noqa: E402
    OpenAIAgenticAdapter,
    _convert_messages_to_openai,
    _tools_to_chat_completions,
)
from core.llm.router import call_with_failover  # noqa: E402

# GLM-5 native web_search configuration.
# Injected alongside function tools for free built-in web search.
_GLM_NATIVE_WEB_SEARCH: dict[str, Any] = {
    "type": "web_search",
    "web_search": {
        "enable": True,
    },
}


class GlmAgenticAdapter(OpenAIAgenticAdapter):
    """ZhipuAI GLM adapter (glm-5, glm-5-turbo, glm-4.7-flash).

    Injects GLM native web_search tool alongside function tools.
    """

    @property
    def provider_name(self) -> str:
        return "glm"

    @property
    def fallback_chain(self) -> list[str]:
        return list(GLM_FALLBACK_CHAIN)

    def _resolve_config(self, model: str) -> tuple[str, str | None]:
        return settings.zai_api_key, GLM_BASE_URL

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
        thinking_budget: int = 0,
    ) -> Any | None:
        """GLM agentic call with native web_search injection."""
        client = self._ensure_client(model)
        if client is None:
            self.last_error = ValueError(f"{self.provider_name} API key not configured")
            log.warning("No API key for %s agentic loop", self.provider_name)
            return None

        if not self._circuit_breaker.can_execute():
            self.last_error = RuntimeError(f"{self.provider_name} circuit breaker is OPEN")
            log.warning("%s circuit breaker is OPEN, skipping call", self.provider_name)
            return None

        tc_val = tool_choice.get("type", "auto") if isinstance(tool_choice, dict) else tool_choice

        oai_tools = _tools_to_chat_completions(tools)
        oai_tools.append(_GLM_NATIVE_WEB_SEARCH)

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
        except Exception as exc:
            self.last_error = exc
            log.warning("%s agentic LLM call failed", self.provider_name, exc_info=True)
            self._circuit_breaker.record_failure()
            return None

        if response is None:
            self._circuit_breaker.record_failure()
            return None

        self._circuit_breaker.record_success()

        # Track token usage/cost (was missing — GLM calls were $0.00)
        if hasattr(response, "usage") and response.usage:
            from core.llm.token_tracker import get_tracker

            actual_model = used_model or model
            in_tok = response.usage.prompt_tokens or 0
            out_tok = response.usage.completion_tokens or 0
            get_tracker().record(actual_model, in_tok, out_tok)

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        from core.llm.agentic_response import normalize_openai

        return normalize_openai(response)
