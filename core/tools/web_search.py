"""Generic web search tool — Anthropic / OpenAI / GLM 3-provider fallback.

Domain-agnostic: any plugin can register this tool. Extracted from the
former ``core/tools/signal_tools.py`` during the v0.66.2 step-5 split so
the signal-tools module could be retired and the IP-specific scrapers
moved to ``plugins/game_ip/tools/signal_tools.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.config import ANTHROPIC_PRIMARY

log = logging.getLogger(__name__)


_WEB_SEARCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query (e.g., 'Berserk game adaptation news 2026').",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5).",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class WebSearchTool:
    """Tool for real-time web search via 3-provider native fallback.

    Priority: Anthropic (Opus) → OpenAI (gpt-5.4) → GLM (glm-5).
    Falls back to stub data when all providers are unavailable.
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for real-time information about an IP. "
            "Useful for finding recent news, community discussions, "
            "sales data, and market signals that may not be in fixtures."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _WEB_SEARCH_PARAMETERS

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)

        result = self._anthropic_search(query, max_results)
        if result:
            return result

        result = self._openai_search(query, max_results)
        if result:
            return result

        result = self._glm_search(query, max_results)
        if result:
            return result

        return self._stub_result(query, "all_providers_failed")

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run provider web-search clients off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _anthropic_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        try:
            from core.config import settings
            from core.llm.router import get_anthropic_client

            if not settings.anthropic_api_key:
                return None
            client = get_anthropic_client()
            response = client.messages.create(
                model=ANTHROPIC_PRIMARY,
                max_tokens=1024,
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Search the web for: {query}. "
                            f"Return up to {max_results} relevant results "
                            "with titles, URLs, and brief summaries."
                        ),
                    }
                ],
                timeout=30.0,
            )
            text_parts: list[str] = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            return {
                "result": {
                    "query": query,
                    "search_results": "\n".join(text_parts),
                    "source": "anthropic_web_search",
                }
            }
        except Exception:
            log.debug("Anthropic web search failed for signal tool", exc_info=True)
            return None

    def _openai_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        try:
            from core.config import OPENAI_PRIMARY, settings
            from core.llm.providers.openai import _get_openai_client

            if not settings.openai_api_key:
                return None
            client = _get_openai_client()
            response = client.responses.create(
                model=OPENAI_PRIMARY,
                tools=[{"type": "web_search"}],
                input=(
                    f"Search the web for: {query}. "
                    f"Return up to {max_results} relevant results "
                    "with titles, URLs, and brief summaries."
                ),
            )
            text_parts: list[str] = []
            for item in response.output:
                if getattr(item, "type", "") == "message":
                    for sub in getattr(item, "content", []):
                        if getattr(sub, "type", "") == "output_text":
                            text = getattr(sub, "text", "")
                            if text:
                                text_parts.append(text)
            if not text_parts:
                return None
            return {
                "result": {
                    "query": query,
                    "search_results": "\n".join(text_parts),
                    "source": "openai_web_search",
                }
            }
        except Exception:
            log.debug("OpenAI web search failed for signal tool", exc_info=True)
            return None

    def _glm_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        try:
            from core.config import GLM_BASE_URL, GLM_PRIMARY, settings

            if not settings.zai_api_key:
                return None
            import openai

            client = openai.OpenAI(api_key=settings.zai_api_key, base_url=GLM_BASE_URL)
            response = client.chat.completions.create(
                model=GLM_PRIMARY,
                tools=[{"type": "web_search", "web_search": {"enable": True}}],  # type: ignore[list-item]  # GLM native tool
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Search the web for: {query}. "
                            f"Return up to {max_results} relevant results "
                            "with titles, URLs, and brief summaries."
                        ),
                    }
                ],
                timeout=30.0,
            )
            choice = response.choices[0] if response.choices else None
            if choice and choice.message.content:
                return {
                    "result": {
                        "query": query,
                        "search_results": choice.message.content,
                        "source": "glm_web_search",
                    }
                }
            return None
        except Exception:
            log.debug("GLM web search failed for signal tool", exc_info=True)
            return None

    @staticmethod
    def _stub_result(query: str, reason: str) -> dict[str, Any]:
        return {
            "result": {
                "query": query,
                "search_results": f"Web search unavailable ({reason}). "
                "Use fixture data or retry later.",
                "source": "web_search_stub",
            }
        }
