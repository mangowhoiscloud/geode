"""GlmAgenticAdapter — ZhipuAI GLM adapter for agentic loop.

Inherits from OpenAIAgenticAdapter. Only overrides _resolve_config()
and fallback_chain for GLM-specific base_url and API key.
"""

from __future__ import annotations

from core.config import GLM_BASE_URL, GLM_FALLBACK_CHAIN, settings
from core.infrastructure.adapters.llm.openai_agentic_adapter import OpenAIAgenticAdapter


class GlmAgenticAdapter(OpenAIAgenticAdapter):
    """ZhipuAI GLM adapter (glm-5, glm-5-turbo, glm-4.7-flash)."""

    @property
    def provider_name(self) -> str:
        return "glm"

    @property
    def fallback_chain(self) -> list[str]:
        return list(GLM_FALLBACK_CHAIN)

    def _resolve_config(self, model: str) -> tuple[str, str | None]:
        return settings.zai_api_key, GLM_BASE_URL
