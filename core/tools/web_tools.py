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
            return {"error": "httpx not installed"}

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
            return {"error": f"HTTP {exc.response.status_code}: {url}"}
        except Exception as exc:
            return {"error": f"Failed to fetch {url}: {exc}"}

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Extract text from HTML, stripping tags."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style elements
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except ImportError:
            # Fallback: simple regex strip
            import re

            text = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", text).strip()


class GeneralWebSearchTool:
    """Search the web for current information via Anthropic native web search."""

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

        try:
            from core.config import ANTHROPIC_PRIMARY, settings
            from core.llm.router import get_anthropic_client

            if not settings.anthropic_api_key:
                return {"error": "No API key configured for web search"}

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
                # Extract cited URLs from web_search_tool_result blocks
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
            return {"error": f"Web search failed: {exc}"}
