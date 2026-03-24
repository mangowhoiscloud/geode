"""Brave Search MCP Adapter — web search via Brave Search MCP server.

Provides both search-level and signal-level interfaces:
  - BraveSearchAdapter: raw web search (WebSearchPort)
  - BraveSignalAdapter: signal enrichment via search (SignalEnrichmentPort)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.mcp.base import MCPClientBase
    from core.mcp.manager import MCPServerManager


class BraveSearchAdapter:
    """Web search via Brave Search MCP server.

    Accepts either MCPClientBase (legacy) or MCPServerManager (production).
    """

    def __init__(
        self,
        mcp_client: MCPClientBase | None = None,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "brave-search",
    ) -> None:
        self._client = mcp_client
        self._manager = manager
        self._server_name = server_name

    def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        if not self.is_available():
            return []
        try:
            if self._manager is not None:
                result = self._manager.call_tool(
                    self._server_name,
                    "brave_web_search",
                    {"query": query, "count": count},
                )
            elif self._client is not None:
                result = self._client.call_tool(
                    "brave_web_search",
                    {"query": query, "count": count},
                )
            else:
                return []

            if "error" in result:
                log.warning("Brave search returned error for '%s': %s", query, result["error"])
                return []

            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception as exc:
            log.warning("Brave search failed for '%s': %s", query, exc)
            return []

    def is_available(self) -> bool:
        if self._manager is not None:
            health = self._manager.check_health()
            return health.get(self._server_name, False)
        if self._client is not None:
            return self._client.is_connected()
        return False


class BraveSignalAdapter:
    """Signal enrichment via Brave web search.

    Implements SignalEnrichmentPort by searching for IP-related community
    and market data, then extracting structured signals from results.
    """

    def __init__(self, brave_search: BraveSearchAdapter) -> None:
        self._search = brave_search

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        if not self._search.is_available():
            return {}
        try:
            results = self._search.search(
                f"{ip_name} game franchise community statistics popularity",
                count=5,
            )
            if not results:
                return {}

            snippets = [r.get("description", "") for r in results if r.get("description")]
            urls = [r.get("url", "") for r in results if r.get("url")]

            return {
                "brave_search_snippets": snippets[:5],
                "brave_search_urls": urls[:5],
                "brave_result_count": len(results),
                "_enrichment_source": "brave_mcp",
            }
        except Exception as exc:
            log.warning("Brave signal fetch failed for %s: %s", ip_name, exc)
            return {}

    def is_available(self) -> bool:
        return self._search.is_available()
