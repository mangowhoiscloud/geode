"""Signal & Search & Memory Ports — abstract interfaces for external data.

Defines contracts for:
- SignalEnrichmentPort: live signals (YouTube, Reddit, etc)
- WebSearchPort: web search queries
- KGMemoryPort: knowledge graph memory operations
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SignalEnrichmentPort(Protocol):
    """Port for external signal enrichment."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        """Fetch enrichment signals for an IP.

        Returns dict with standard signal keys:
            youtube_views, reddit_subscribers, fan_art_yoy_pct,
            twitch_hours_monthly, google_trends_index, twitter_mentions
        """
        ...

    def is_available(self) -> bool:
        """Check if the enrichment service is reachable."""
        ...


@runtime_checkable
class WebSearchPort(Protocol):
    """Port for web search operations."""

    def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        """Search the web and return results."""
        ...

    def is_available(self) -> bool:
        """Check if the search service is reachable."""
        ...


@runtime_checkable
class KGMemoryPort(Protocol):
    """Port for knowledge graph memory operations."""

    def create_entities(self, entities: list[dict[str, Any]]) -> bool:
        """Create entities in the knowledge graph."""
        ...

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search the knowledge graph."""
        ...

    def add_observations(self, observations: list[dict[str, Any]]) -> bool:
        """Add observations to existing entities."""
        ...

    def is_available(self) -> bool:
        """Check if the memory service is reachable."""
        ...
