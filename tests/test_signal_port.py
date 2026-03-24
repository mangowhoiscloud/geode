"""Tests for Signal Enrichment Port + Adapters."""

from __future__ import annotations

from typing import Any

from core.domains.game_ip.nodes.signals import set_signal_adapter, signals_node
from core.infrastructure.adapters.signal_adapter import (
    FixtureSignalAdapter,
    LiveSignalAdapter,
    create_signal_adapter,
)
from core.mcp.signal_port import SignalEnrichmentPort
from core.state import GeodeState


class TestSignalEnrichmentPort:
    def test_port_has_required_methods(self):
        assert hasattr(SignalEnrichmentPort, "fetch_signals")
        assert hasattr(SignalEnrichmentPort, "is_available")

    def test_fixture_adapter_satisfies_port(self):
        adapter = FixtureSignalAdapter()
        assert isinstance(adapter, SignalEnrichmentPort)

    def test_live_adapter_satisfies_port(self):
        adapter = LiveSignalAdapter()
        assert isinstance(adapter, SignalEnrichmentPort)


class TestFixtureSignalAdapter:
    def test_fetch_known_ip(self):
        adapter = FixtureSignalAdapter()
        signals = adapter.fetch_signals("Berserk")
        assert "youtube_views" in signals

    def test_fetch_unknown_ip(self):
        adapter = FixtureSignalAdapter()
        signals = adapter.fetch_signals("Nonexistent IP")
        assert signals == {}

    def test_is_available(self):
        assert FixtureSignalAdapter().is_available() is True


class TestLiveSignalAdapter:
    def test_falls_back_to_fixture(self):
        adapter = LiveSignalAdapter()
        signals = adapter.fetch_signals("Berserk")
        assert "youtube_views" in signals
        assert signals["_enrichment_source"] == "fixture_fallback"

    def test_is_available(self):
        assert LiveSignalAdapter().is_available() is True


class TestCreateSignalAdapter:
    def test_returns_adapter(self):
        adapter = create_signal_adapter()
        assert isinstance(adapter, SignalEnrichmentPort)


class TestSignalsNodeWithAdapter:
    def test_uses_injected_adapter(self):
        class MockAdapter:
            def fetch_signals(self, ip_name: str) -> dict[str, Any]:
                return {"youtube_views": 999, "_source": "mock"}

            def is_available(self) -> bool:
                return True

        set_signal_adapter(MockAdapter())
        try:
            state: GeodeState = {"ip_name": "Berserk", "pipeline_mode": "full"}  # type: ignore[typeddict-item]
            result = signals_node(state)
            assert result["signals"]["_source"] == "mock"
        finally:
            set_signal_adapter(None)

    def test_falls_back_on_adapter_failure(self):
        class FailingAdapter:
            def fetch_signals(self, ip_name: str) -> dict[str, Any]:
                raise ConnectionError("API down")

            def is_available(self) -> bool:
                return True

        set_signal_adapter(FailingAdapter())
        try:
            state: GeodeState = {"ip_name": "Berserk", "pipeline_mode": "full"}  # type: ignore[typeddict-item]
            result = signals_node(state)
            # Should fall back to fixture
            assert "youtube_views" in result["signals"]
        finally:
            set_signal_adapter(None)

    def test_skips_unavailable_adapter(self):
        class UnavailableAdapter:
            def fetch_signals(self, ip_name: str) -> dict[str, Any]:
                return {"should_not": "appear"}

            def is_available(self) -> bool:
                return False

        set_signal_adapter(UnavailableAdapter())
        try:
            state: GeodeState = {"ip_name": "Berserk", "pipeline_mode": "full"}  # type: ignore[typeddict-item]
            result = signals_node(state)
            assert "should_not" not in result["signals"]
            assert "youtube_views" in result["signals"]
        finally:
            set_signal_adapter(None)
