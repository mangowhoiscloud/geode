"""Brave Search MCP Adapter — web search via Brave Search MCP server."""

from __future__ import annotations

import logging
from typing import Any

from geode.infrastructure.adapters.mcp.base import MCPClientBase

log = logging.getLogger(__name__)


class BraveSearchAdapter:
    """Web search via Brave Search MCP server."""

    def __init__(self, mcp_client: MCPClientBase) -> None:
        self._client = mcp_client

    def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        if not self._client.is_connected():
            return []
        try:
            result = self._client.call_tool("brave_web_search", {
                "query": query,
                "count": count,
            })
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception as exc:
            log.warning("Brave search failed for '%s': %s", query, exc)
            return []

    def is_available(self) -> bool:
        return self._client.is_connected()
