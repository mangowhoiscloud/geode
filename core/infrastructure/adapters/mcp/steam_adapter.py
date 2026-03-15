"""Steam MCP Signal Adapter — fetch game metrics via Steam MCP server.

Supports two connection modes:
  1. MCPClientBase (legacy) — direct client connection
  2. MCPServerManager — stdio-based server management (production)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.infrastructure.adapters.mcp.base import MCPClientBase
    from core.infrastructure.adapters.mcp.manager import MCPServerManager


class SteamMCPSignalAdapter:
    """Fetch Steam game signals via MCP server.

    Implements SignalEnrichmentPort. Falls back gracefully if MCP unavailable.

    Accepts either:
      - MCPClientBase (legacy): direct ``mcp_client`` parameter
      - MCPServerManager (production): ``manager`` + ``server_name`` parameters
    """

    def __init__(
        self,
        mcp_client: MCPClientBase | None = None,
        *,
        manager: MCPServerManager | None = None,
        server_name: str = "steam",
    ) -> None:
        self._client = mcp_client
        self._manager = manager
        self._server_name = server_name

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        if not self.is_available():
            return {}
        try:
            if self._manager is not None:
                result = self._manager.call_tool(
                    self._server_name, "get_game_info", {"query": ip_name}
                )
            elif self._client is not None:
                result = self._client.call_tool("get_game_info", {"query": ip_name})
            else:
                return {}

            if "error" in result:
                log.warning("Steam MCP returned error for %s: %s", ip_name, result["error"])
                return {}

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
        if self._manager is not None:
            health = self._manager.check_health()
            return health.get(self._server_name, False)
        if self._client is not None:
            return self._client.is_connected()
        return False
