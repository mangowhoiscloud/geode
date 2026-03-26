"""GlmAgenticAdapter — ZhipuAI GLM adapter for agentic loop.

Inherits from OpenAIAgenticAdapter. Overrides _resolve_config(),
fallback_chain, and agentic_call for GLM-specific base_url, API key,
and native web_search tool injection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.cli.agentic_response import AgenticResponse, normalize_openai
from core.config import GLM_BASE_URL, GLM_FALLBACK_CHAIN, settings
from core.infrastructure.adapters.llm.openai_agentic_adapter import (
    OpenAIAgenticAdapter,
    _convert_messages_to_openai,
    _tools_to_openai,
)
from core.infrastructure.ports.agentic_llm_port import UserCancelledError
from core.llm.client import call_with_failover

log = logging.getLogger(__name__)

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
    ) -> AgenticResponse | None:
        """GLM agentic call with native web_search injection.

        Converts function tools to OpenAI format, then appends the GLM
        native web_search tool for free built-in web search capability.
        """
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

        # Inject GLM native web_search alongside function tools
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
