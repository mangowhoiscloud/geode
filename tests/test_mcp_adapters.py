"""Tests for MCP adapter infrastructure."""

from __future__ import annotations

from typing import Any

from geode.infrastructure.adapters.mcp.base import MCPClientBase, MCPTimeoutError
from geode.infrastructure.adapters.mcp.brave_adapter import BraveSearchAdapter
from geode.infrastructure.adapters.mcp.composite_signal import CompositeSignalAdapter
from geode.infrastructure.adapters.mcp.memory_adapter import KGMemoryAdapter
from geode.infrastructure.adapters.mcp.steam_adapter import SteamMCPSignalAdapter
from geode.infrastructure.ports.signal_port import KGMemoryPort, SignalEnrichmentPort, WebSearchPort

# ---------------------------------------------------------------------------
# MCPClientBase
# ---------------------------------------------------------------------------


class TestMCPClientBase:
    def test_default_not_connected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        assert client.is_connected() is False

    def test_connect_stub_returns_false(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        assert client.connect() is False
        assert client.is_connected() is False

    def test_list_tools_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        assert client.list_tools() == []

    def test_call_tool_raises_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        try:
            client.call_tool("some_tool", {})
            assert False, "Expected ConnectionError"  # noqa: B011
        except ConnectionError:
            pass

    def test_close_sets_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        client._connected = True
        assert client.is_connected() is True
        client.close()
        assert client.is_connected() is False

    def test_timeout_property(self) -> None:
        client = MCPClientBase("http://localhost:8080", timeout_s=10.0)
        assert client.timeout_s == 10.0

    def test_server_url_property(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        assert client.server_url == "http://localhost:8080"

    def test_mcp_timeout_error_is_timeout_error(self) -> None:
        assert issubclass(MCPTimeoutError, TimeoutError)


# ---------------------------------------------------------------------------
# SteamMCPSignalAdapter
# ---------------------------------------------------------------------------


class TestSteamMCPSignalAdapter:
    def test_returns_empty_when_not_connected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = SteamMCPSignalAdapter(client)
        assert adapter.fetch_signals("Berserk") == {}

    def test_is_available_false_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = SteamMCPSignalAdapter(client)
        assert adapter.is_available() is False

    def test_implements_signal_enrichment_port(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = SteamMCPSignalAdapter(client)
        assert isinstance(adapter, SignalEnrichmentPort)


# ---------------------------------------------------------------------------
# BraveSearchAdapter
# ---------------------------------------------------------------------------


class TestBraveSearchAdapter:
    def test_returns_empty_when_not_connected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = BraveSearchAdapter(client)
        assert adapter.search("test query") == []

    def test_is_available_false_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = BraveSearchAdapter(client)
        assert adapter.is_available() is False

    def test_implements_web_search_port(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = BraveSearchAdapter(client)
        assert isinstance(adapter, WebSearchPort)


# ---------------------------------------------------------------------------
# KGMemoryAdapter
# ---------------------------------------------------------------------------


class TestKGMemoryAdapter:
    def test_create_entities_returns_false_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = KGMemoryAdapter(client)
        assert adapter.create_entities([{"name": "test"}]) is False

    def test_search_returns_empty_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = KGMemoryAdapter(client)
        assert adapter.search("test") == []

    def test_add_observations_returns_false_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = KGMemoryAdapter(client)
        assert adapter.add_observations([{"entity": "test"}]) is False

    def test_is_available_false_when_disconnected(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = KGMemoryAdapter(client)
        assert adapter.is_available() is False

    def test_implements_kg_memory_port(self) -> None:
        client = MCPClientBase("http://localhost:8080")
        adapter = KGMemoryAdapter(client)
        assert isinstance(adapter, KGMemoryPort)


# ---------------------------------------------------------------------------
# CompositeSignalAdapter
# ---------------------------------------------------------------------------


class _MockAvailableAdapter:
    """Mock adapter that returns predefined signals."""

    def __init__(self, signals: dict[str, Any]) -> None:
        self._signals = signals

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        return self._signals

    def is_available(self) -> bool:
        return True


class _MockUnavailableAdapter:
    """Mock adapter that is not available."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        return {"should_not": "appear"}

    def is_available(self) -> bool:
        return False


class _MockFailingAdapter:
    """Mock adapter that raises on fetch."""

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        raise ConnectionError("API down")

    def is_available(self) -> bool:
        return True


class TestCompositeSignalAdapter:
    def test_chains_multiple_adapters(self) -> None:
        a1 = _MockAvailableAdapter({"steam_score": 95, "_enrichment_source": "steam"})
        a2 = _MockAvailableAdapter({"youtube_views": 1000, "_enrichment_source": "yt"})
        composite = CompositeSignalAdapter([a1, a2])
        result = composite.fetch_signals("Berserk")
        assert result["steam_score"] == 95
        assert result["youtube_views"] == 1000
        assert "_enrichment_sources" in result
        assert "steam" in result["_enrichment_sources"]
        assert "yt" in result["_enrichment_sources"]

    def test_skips_unavailable_adapters(self) -> None:
        a1 = _MockUnavailableAdapter()
        a2 = _MockAvailableAdapter({"score": 42, "_enrichment_source": "live"})
        composite = CompositeSignalAdapter([a1, a2])
        result = composite.fetch_signals("test")
        assert "should_not" not in result
        assert result["score"] == 42

    def test_handles_failing_adapters(self) -> None:
        a1 = _MockFailingAdapter()
        a2 = _MockAvailableAdapter({"ok": True, "_enrichment_source": "fallback"})
        composite = CompositeSignalAdapter([a1, a2])
        result = composite.fetch_signals("test")
        assert result["ok"] is True

    def test_returns_empty_when_all_unavailable(self) -> None:
        a1 = _MockUnavailableAdapter()
        composite = CompositeSignalAdapter([a1])
        assert composite.fetch_signals("test") == {}

    def test_is_available_true_when_any_available(self) -> None:
        a1 = _MockUnavailableAdapter()
        a2 = _MockAvailableAdapter({})
        composite = CompositeSignalAdapter([a1, a2])
        assert composite.is_available() is True

    def test_is_available_false_when_none_available(self) -> None:
        a1 = _MockUnavailableAdapter()
        composite = CompositeSignalAdapter([a1])
        assert composite.is_available() is False

    def test_implements_signal_enrichment_port(self) -> None:
        composite = CompositeSignalAdapter([])
        assert isinstance(composite, SignalEnrichmentPort)


# ---------------------------------------------------------------------------
# _system_with_cache (Prompt Caching)
# ---------------------------------------------------------------------------


class TestSystemWithCache:
    def test_returns_content_block_list(self) -> None:
        from geode.llm.client import _system_with_cache

        result = _system_with_cache("You are a helpful assistant.")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_block_has_cache_control(self) -> None:
        from geode.llm.client import _system_with_cache

        result = _system_with_cache("Test prompt")
        block = result[0]
        assert block["type"] == "text"
        assert block["text"] == "Test prompt"
        assert block["cache_control"] == {"type": "ephemeral"}

    def test_preserves_full_system_text(self) -> None:
        from geode.llm.client import _system_with_cache

        long_system = "A" * 10000
        result = _system_with_cache(long_system)
        assert result[0]["text"] == long_system
