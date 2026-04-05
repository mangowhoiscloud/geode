"""Web Tools — URL fetch and web search as LLM-callable tools.

Provides:
- WebFetchTool: Fetch and extract text from a URL
- GeneralWebSearchTool: Search the web for current information
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


class WebFetchTool:
    """Fetch and extract text content from a URL."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch and extract text content from a URL."

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        url: str = kwargs["url"]
        max_chars: int = min(kwargs.get("max_chars", 8000), 10000)

        try:
            import httpx
        except ImportError:
            from core.tools.base import tool_error

            return tool_error(
                "httpx not installed",
                error_type="dependency",
                recoverable=False,
                hint="Install httpx: pip install httpx",
            )

        try:
            try:
                resp = httpx.get(url, timeout=10.0, follow_redirects=True)
            except httpx.ConnectError:
                # SSL cert fallback (Python 3.14 + macOS certifi issue)
                resp = httpx.get(url, timeout=10.0, follow_redirects=True, verify=False)  # noqa: S501  # nosec B501
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            text = self._html_to_text(resp.text) if "text/html" in content_type else resp.text

            return {
                "result": {
                    "url": url,
                    "source": url,  # explicit source tag for grounding
                    "content": text[:max_chars],
                    "truncated": len(text) > max_chars,
                    "content_type": content_type,
                    "status_code": resp.status_code,
                }
            }
        except httpx.HTTPStatusError as exc:
            from core.tools.base import tool_error

            status = exc.response.status_code
            return tool_error(
                f"HTTP {status}: {url}",
                error_type="connection",
                recoverable=status in (429, 500, 502, 503, 504),
                hint="Retry later." if status == 429 else "Check URL or try a different source.",
                context={"url": url, "status_code": status},
            )
        except Exception as exc:
            from core.tools.base import tool_error

            return tool_error(
                f"Failed to fetch {url}: {exc}",
                error_type="connection",
                hint="Check URL validity or network connectivity.",
                context={"url": url},
            )

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to Markdown, preserving structure.

        Uses markdownify for structure-preserving conversion (links,
        headings, code blocks). Falls back to BeautifulSoup text
        extraction if markdownify unavailable.
        Claude Code pattern: Turndown HTML→MD before context injection.
        """
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            cleaned = str(soup)
        except ImportError:
            cleaned = html

        try:
            from markdownify import markdownify as md

            return md(cleaned, heading_style="ATX", strip=["img"])
        except ImportError:
            # Fallback: plain text extraction
            try:
                return soup.get_text(separator="\n", strip=True)
            except NameError:
                import re

                text = re.sub(r"<[^>]+>", " ", html)
                return re.sub(r"\s+", " ", text).strip()


class GeneralWebSearchTool:
    """Search the web via 3-provider native web search fallback chain.

    Priority: Anthropic (Opus) → OpenAI (gpt-5.4) → GLM (glm-5).
    Each provider uses its native web search tool — no external API keys needed.
    """

    @property
    def name(self) -> str:
        return "general_web_search"

    @property
    def description(self) -> str:
        today = date.today()
        return (
            f"Search the web for current information on any topic. "
            f"Today is {today.isoformat()} (year {today.year})."
        )

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)

        # 1. Anthropic (primary)
        result = self._anthropic_search(query, max_results)
        if result:
            return result

        # 2. OpenAI Responses API (fallback 1)
        result = self._openai_search(query, max_results)
        if result:
            return result

        # 3. GLM native web_search (fallback 2)
        result = self._glm_search(query, max_results)
        if result:
            return result

        from core.tools.base import tool_error

        return tool_error(
            "All web search providers failed",
            error_type="connection",
            recoverable=True,
            hint="Retry or rephrase the query.",
            context={"query": query},
        )

    def _anthropic_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        """Anthropic native web search via Messages API."""
        try:
            from core.config import ANTHROPIC_PRIMARY, settings
            from core.llm.router import get_anthropic_client

            if not settings.anthropic_api_key:
                return None

            today = date.today()
            client = get_anthropic_client()
            response = client.messages.create(
                model=ANTHROPIC_PRIMARY,
                max_tokens=1024,
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Today is {today.isoformat()}. "
                            f"Search the web for: {query}. "
                            f"Return up to {max_results} relevant results "
                            "with titles, URLs, and brief summaries."
                        ),
                    }
                ],
                timeout=30.0,
            )
            text_parts: list[str] = []
            source_urls: list[str] = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                if getattr(block, "type", "") == "web_search_tool_result":
                    for entry in getattr(block, "content", []):
                        url = getattr(entry, "url", None)
                        if url:
                            source_urls.append(url)
            return {
                "result": {
                    "query": query,
                    "search_results": "\n".join(text_parts),
                    "source": "anthropic_web_search",
                    "source_urls": source_urls,
                }
            }
        except Exception as exc:
            log.debug("Anthropic web search failed: %s", exc)
            return None

    def _openai_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        """OpenAI native web search via Responses API."""
        try:
            from core.config import OPENAI_PRIMARY, settings
            from core.llm.providers.openai import _get_openai_client

            if not settings.openai_api_key:
                return None

            today = date.today()
            client = _get_openai_client()
            response = client.responses.create(
                model=OPENAI_PRIMARY,
                tools=[{"type": "web_search"}],
                input=(
                    f"Today is {today.isoformat()}. "
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
        except Exception as exc:
            log.debug("OpenAI web search failed: %s", exc)
            return None

    def _glm_search(self, query: str, max_results: int) -> dict[str, Any] | None:
        """GLM native web search via Chat Completions API."""
        try:
            from core.config import GLM_BASE_URL, GLM_PRIMARY, settings

            if not settings.zai_api_key:
                return None

            import openai

            client = openai.OpenAI(api_key=settings.zai_api_key, base_url=GLM_BASE_URL)
            today = date.today()
            response = client.chat.completions.create(
                model=GLM_PRIMARY,
                tools=[{"type": "web_search", "web_search": {"enable": True}}],  # type: ignore[list-item]  # GLM native tool
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Today is {today.isoformat()}. "
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
        except Exception as exc:
            log.debug("GLM web search failed: %s", exc)
            return None
