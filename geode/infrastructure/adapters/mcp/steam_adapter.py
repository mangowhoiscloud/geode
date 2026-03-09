"""Steam MCP Signal Adapter — fetch game metrics via Steam MCP server."""

from __future__ import annotations

import logging
from typing import Any

from geode.infrastructure.adapters.mcp.base import MCPClientBase

log = logging.getLogger(__name__)


class SteamMCPSignalAdapter:
    """Fetch Steam game signals via MCP server.

    Implements SignalEnrichmentPort. Falls back gracefully if MCP unavailable.
    """

    def __init__(self, mcp_client: MCPClientBase) -> None:
        self._client = mcp_client

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        if not self._client.is_connected():
            return {}
        try:
            result = self._client.call_tool("get_game_info", {"query": ip_name})
            return {
                "steam_players_current": result.get("player_count", 0),
                "steam_review_score": result.get("review_score", 0),
                "steam_review_count": result.get("review_count", 0),
                "_enrichment_source": "steam_mcp",
            }
        except Exception as exc:
            log.warning("Steam MCP fetch failed for %s: %s", ip_name, exc)
            return {}

    def is_available(self) -> bool:
        return self._client.is_connected()
