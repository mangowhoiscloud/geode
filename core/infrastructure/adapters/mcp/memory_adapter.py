"""Knowledge Graph Memory MCP Adapter."""

from __future__ import annotations

import logging
from typing import Any

from core.infrastructure.adapters.mcp.base import MCPClientBase

log = logging.getLogger(__name__)


class KGMemoryAdapter:
    """Knowledge Graph Memory via MCP server.

    Provides entity-relation-observation storage for persistent
    cross-session analysis memory.
    """

    def __init__(self, mcp_client: MCPClientBase) -> None:
        self._client = mcp_client

    def create_entities(self, entities: list[dict[str, Any]]) -> bool:
        if not self._client.is_connected():
            return False
        try:
            self._client.call_tool("create_entities", {"entities": entities})
            return True
        except Exception as exc:
            log.warning("KG memory create_entities failed: %s", exc)
            return False

    def search(self, query: str) -> list[dict[str, Any]]:
        if not self._client.is_connected():
            return []
        try:
            result = self._client.call_tool("search_nodes", {"query": query})
            nodes: list[dict[str, Any]] = result.get("nodes", [])
            return nodes
        except Exception as exc:
            log.warning("KG memory search failed: %s", exc)
            return []

    def add_observations(self, observations: list[dict[str, Any]]) -> bool:
        if not self._client.is_connected():
            return False
        try:
            self._client.call_tool("add_observations", {"observations": observations})
            return True
        except Exception as exc:
            log.warning("KG memory add_observations failed: %s", exc)
            return False

    def is_available(self) -> bool:
        return self._client.is_connected()
