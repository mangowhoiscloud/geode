"""Tests for Signal Liveification — MCP-first with fixture fallback.

Covers:
  - Live MCP signals via CompositeSignalAdapter
  - Fixture fallback when MCP unavailable
  - Mixed mode (partial live + fixture)
  - signal_source field tracking
"""

from __future__ import annotations

from typing import Any

from core.infrastructure.adapters.mcp.brave_adapter import BraveSignalAdapter
from core.infrastructure.adapters.mcp.composite_signal import CompositeSignalAdapter
from core.infrastructure.adapters.mcp.steam_adapter import SteamMCPSignalAdapter
from core.domains.game_ip.nodes.signals import set_signal_adapter, signals_node
from core.state import GeodeState

# ---------------------------------------------------------------------------
# Mock MCP adapters
# ---------------------------------------------------------------------------


class MockSteamAdapter:
    """Mock Steam MCP adapter returning live signals."""

    def __init__(self, *, available: bool = True, signals: dict[str, Any] | None = None) -> None:
        self._available = available
        self._signals = signals or {
            "steam_players_current": 12345,
            "steam_review_score": 92,
            "steam_review_count": 5000,
            "_enrichment_source": "steam_mcp",
        }

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        if not self._available:
            return {}
        return dict(self._signals)

    def is_available(self) -> bool:
        return self._available


class MockBraveAdapter:
    """Mock Brave signal adapter returning search-based signals."""

    def __init__(self, *, available: bool = True, signals: dict[str, Any] | None = None) -> None:
        self._available = available
        self._signals = signals or {
            "brave_search_snippets": ["snippet1", "snippet2"],
            "brave_search_urls": ["https://example.com"],
            "brave_result_count": 2,
            "_enrichment_source": "brave_mcp",
        }

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        if not self._available:
            return {}
        return dict(self._signals)

    def is_available(self) -> bool:
        return self._available


class MockFailingAdapter:
    """Adapter that raises on fetch but reports available."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        raise ConnectionError("MCP server unreachable")

    def is_available(self) -> bool:
        return True


class MockEmptyAdapter:
    """Adapter that is available but returns empty signals."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        return {}

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_state(ip_name: str = "Berserk") -> GeodeState:
    return {"ip_name": ip_name, "pipeline_mode": "full_pipeline"}  # type: ignore[typeddict-item]


# ---------------------------------------------------------------------------
# Test: Live MCP signals (all adapters available)
# ---------------------------------------------------------------------------


class TestLiveSignals:
    def test_live_signals_from_composite(self):
        """When MCP adapters have sufficient data, signal_source='live'."""
        composite = CompositeSignalAdapter([MockSteamAdapter(), MockBraveAdapter()])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state())
            assert result["signal_source"] == "live"
            assert "steam_players_current" in result["signals"]
            assert "brave_search_snippets" in result["signals"]
            assert "_enrichment_sources" in result["signals"]
        finally:
            set_signal_adapter(None)

    def test_live_signals_steam_only(self):
        """Single adapter with sufficient keys still qualifies as live."""
        composite = CompositeSignalAdapter([MockSteamAdapter()])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state())
            assert result["signal_source"] == "live"
            assert result["signals"]["steam_players_current"] == 12345
        finally:
            set_signal_adapter(None)


# ---------------------------------------------------------------------------
# Test: Fixture fallback (MCP unavailable)
# ---------------------------------------------------------------------------


class TestFixtureFallback:
    def test_fixture_when_no_adapter(self):
        """Without adapter, falls back to fixture."""
        set_signal_adapter(None)
        result = signals_node(_make_state("Berserk"))
        assert result["signal_source"] == "fixture"
        assert "youtube_views" in result["signals"]

    def test_fixture_when_adapter_unavailable(self):
        """When adapter reports unavailable, falls back to fixture."""
        composite = CompositeSignalAdapter(
            [MockSteamAdapter(available=False), MockBraveAdapter(available=False)]  # type: ignore[list-item]
        )
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "fixture"
            assert "youtube_views" in result["signals"]
        finally:
            set_signal_adapter(None)

    def test_fixture_when_adapter_fails(self):
        """When adapter throws, falls back to fixture."""
        set_signal_adapter(MockFailingAdapter())  # type: ignore[arg-type]
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "fixture"
            assert "youtube_views" in result["signals"]
        finally:
            set_signal_adapter(None)


# ---------------------------------------------------------------------------
# Test: Mixed mode (partial live + fixture)
# ---------------------------------------------------------------------------


class TestMixedSignals:
    def test_mixed_when_live_insufficient(self):
        """When live returns only 1 data key, merge with fixture."""
        sparse_adapter = MockSteamAdapter(
            signals={
                "steam_review_score": 85,
                "_enrichment_source": "steam_mcp",
            }
        )
        composite = CompositeSignalAdapter([sparse_adapter])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "mixed"
            # Live data merged
            assert result["signals"]["steam_review_score"] == 85
            # Fixture data present
            assert "youtube_views" in result["signals"]
        finally:
            set_signal_adapter(None)

    def test_mixed_live_overrides_fixture(self):
        """In mixed mode, live keys override fixture keys."""
        override_adapter = MockSteamAdapter(
            signals={
                "youtube_views": 999999,  # Override fixture value
                "_enrichment_source": "steam_mcp",
            }
        )
        composite = CompositeSignalAdapter([override_adapter])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "mixed"
            assert result["signals"]["youtube_views"] == 999999
        finally:
            set_signal_adapter(None)


# ---------------------------------------------------------------------------
# Test: signal_source tracking
# ---------------------------------------------------------------------------


class TestSignalSourceTracking:
    def test_signal_source_in_state_type(self):
        """GeodeState has signal_source field."""
        state: GeodeState = {  # type: ignore[typeddict-item]
            "ip_name": "test",
            "signal_source": "live",
        }
        assert state["signal_source"] == "live"

    def test_all_source_values(self):
        """Verify all four signal_source values can be produced."""
        # live
        composite = CompositeSignalAdapter([MockSteamAdapter(), MockBraveAdapter()])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state())
            assert result["signal_source"] == "live"
        finally:
            set_signal_adapter(None)

        # fixture
        set_signal_adapter(None)
        result = signals_node(_make_state("Berserk"))
        assert result["signal_source"] == "fixture"

        # mixed (sparse live data + known IP)
        sparse = MockSteamAdapter(signals={"one_key": 1, "_enrichment_source": "steam"})
        composite = CompositeSignalAdapter([sparse])  # type: ignore[list-item]
        set_signal_adapter(composite)
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "mixed"
        finally:
            set_signal_adapter(None)

    def test_empty_signals_returns_fixture_source(self):
        """When adapter returns empty and fixture exists, signal_source='fixture'."""
        set_signal_adapter(MockEmptyAdapter())  # type: ignore[arg-type]
        try:
            result = signals_node(_make_state("Berserk"))
            assert result["signal_source"] == "fixture"
        finally:
            set_signal_adapter(None)


# ---------------------------------------------------------------------------
# Test: CompositeSignalAdapter behavior
# ---------------------------------------------------------------------------


class TestCompositeSignalAdapter:
    def test_merges_multiple_sources(self):
        composite = CompositeSignalAdapter([MockSteamAdapter(), MockBraveAdapter()])  # type: ignore[list-item]
        signals = composite.fetch_signals("TestIP")
        assert "steam_players_current" in signals
        assert "brave_search_snippets" in signals
        assert "_enrichment_sources" in signals
        assert len(signals["_enrichment_sources"]) == 2

    def test_skips_unavailable(self):
        composite = CompositeSignalAdapter(
            [MockSteamAdapter(available=False), MockBraveAdapter()]  # type: ignore[list-item]
        )
        signals = composite.fetch_signals("TestIP")
        assert "steam_players_current" not in signals
        assert "brave_search_snippets" in signals
        assert len(signals["_enrichment_sources"]) == 1

    def test_is_available_any(self):
        """is_available() returns True if any adapter is available."""
        composite = CompositeSignalAdapter(
            [MockSteamAdapter(available=False), MockBraveAdapter(available=True)]  # type: ignore[list-item]
        )
        assert composite.is_available() is True

    def test_is_available_none(self):
        """is_available() returns False if no adapters are available."""
        composite = CompositeSignalAdapter(
            [MockSteamAdapter(available=False), MockBraveAdapter(available=False)]  # type: ignore[list-item]
        )
        assert composite.is_available() is False


# ---------------------------------------------------------------------------
# Test: SteamMCPSignalAdapter with manager
# ---------------------------------------------------------------------------


class TestSteamMCPSignalAdapterManager:
    def test_manager_mode_unavailable(self):
        """When manager reports server not healthy, returns empty."""

        class FakeManager:
            def check_health(self) -> dict[str, bool]:
                return {"steam": False}

            def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
                raise AssertionError("Should not be called")

        adapter = SteamMCPSignalAdapter(manager=FakeManager(), server_name="steam")  # type: ignore[arg-type]
        assert adapter.is_available() is False
        assert adapter.fetch_signals("Test") == {}

    def test_manager_mode_available(self):
        """When manager is healthy, calls tool and returns signals."""

        class FakeManager:
            def check_health(self) -> dict[str, bool]:
                return {"steam": True}

            def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
                return {"player_count": 100, "review_score": 90, "review_count": 50}

        adapter = SteamMCPSignalAdapter(manager=FakeManager(), server_name="steam")  # type: ignore[arg-type]
        assert adapter.is_available() is True
        signals = adapter.fetch_signals("Test")
        assert signals["steam_players_current"] == 100
        assert signals["_enrichment_source"] == "steam_mcp"

    def test_manager_mode_error_result(self):
        """When manager returns error dict, adapter returns empty."""

        class FakeManager:
            def check_health(self) -> dict[str, bool]:
                return {"steam": True}

            def call_tool(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
                return {"error": "Server not responding"}

        adapter = SteamMCPSignalAdapter(manager=FakeManager(), server_name="steam")  # type: ignore[arg-type]
        assert adapter.fetch_signals("Test") == {}


# ---------------------------------------------------------------------------
# Test: BraveSignalAdapter
# ---------------------------------------------------------------------------


class TestBraveSignalAdapter:
    def test_unavailable_search(self):
        """When search is unavailable, returns empty."""

        class FakeBraveSearch:
            def is_available(self) -> bool:
                return False

            def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
                raise AssertionError("Should not be called")

        adapter = BraveSignalAdapter(FakeBraveSearch())  # type: ignore[arg-type]
        assert adapter.is_available() is False
        assert adapter.fetch_signals("Test") == {}

    def test_successful_search(self):
        """When search returns results, extracts signal data."""

        class FakeBraveSearch:
            def is_available(self) -> bool:
                return True

            def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
                return [
                    {"description": "Game info", "url": "https://example.com/game"},
                    {"description": "Review", "url": "https://example.com/review"},
                ]

        adapter = BraveSignalAdapter(FakeBraveSearch())  # type: ignore[arg-type]
        signals = adapter.fetch_signals("Test")
        assert signals["_enrichment_source"] == "brave_mcp"
        assert signals["brave_result_count"] == 2
        assert len(signals["brave_search_snippets"]) == 2

    def test_empty_search_results(self):
        """When search returns empty, returns empty signals."""

        class FakeBraveSearch:
            def is_available(self) -> bool:
                return True

            def search(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
                return []

        adapter = BraveSignalAdapter(FakeBraveSearch())  # type: ignore[arg-type]
        assert adapter.fetch_signals("Test") == {}
