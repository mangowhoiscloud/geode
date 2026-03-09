"""Signal Enrichment Adapters — fixture fallback + live API stub.

FixtureSignalAdapter: Loads from geode/fixtures/*.json (always available).
LiveSignalAdapter: Placeholder for YouTube/Reddit/Google Trends APIs.
    Falls back to FixtureSignalAdapter when APIs are unreachable.

Usage:
    adapter = create_signal_adapter()  # auto-detects availability
    signals = adapter.fetch_signals("Berserk")
"""

from __future__ import annotations

import logging
from typing import Any

from geode.fixtures import load_fixture

log = logging.getLogger(__name__)


class FixtureSignalAdapter:
    """Signal adapter backed by JSON fixtures (always available)."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        try:
            fixture = load_fixture(ip_name)
            result: dict[str, Any] = fixture.get("signals", {})
            return result
        except Exception as e:
            log.warning("Fixture signal load failed for %s: %s", ip_name, e)
            return {}

    def is_available(self) -> bool:
        return True


class LiveSignalAdapter:
    """Signal adapter with external API integration (YouTube, Reddit, etc).

    Production upgrade path:
        1. Set YOUTUBE_API_KEY, REDDIT_CLIENT_ID env vars
        2. This adapter queries live APIs with rate limiting
        3. Falls back to FixtureSignalAdapter on API failure

    Currently stub — returns fixture data with enrichment metadata.
    """

    def __init__(self) -> None:
        self._fixture_fallback = FixtureSignalAdapter()
        self._api_available: bool | None = None

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        # TODO: Replace with actual API calls when keys are configured
        # youtube = self._fetch_youtube(ip_name)
        # reddit = self._fetch_reddit(ip_name)
        # trends = self._fetch_google_trends(ip_name)

        # Fallback to fixture data with enrichment metadata
        signals = self._fixture_fallback.fetch_signals(ip_name)
        signals["_enrichment_source"] = "fixture_fallback"
        signals["_live_api_available"] = False
        return signals

    def is_available(self) -> bool:
        # Will check API key availability when implemented
        return True


def create_signal_adapter() -> FixtureSignalAdapter | LiveSignalAdapter:
    """Factory: create the best available signal adapter."""
    # For now, always return fixture adapter.
    # When live API keys are configured, return LiveSignalAdapter.
    return FixtureSignalAdapter()
