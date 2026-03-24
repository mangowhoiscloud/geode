"""Layer 2: Signals — External signal collection with graceful degradation.

Execution path (liveification):
  1. CompositeSignalAdapter via MCP (Steam + Brave live data)
  2. Fixture fallback (known IPs)
  3. Mixed mode: merge live + fixture when live is partial
  4. Web search fallback (unknown IPs — external data mode)

The ``signal_source`` state field tracks provenance:
  - "live"       — all signals from MCP adapters
  - "fixture"    — all signals from JSON fixtures
  - "mixed"      — live MCP data merged with fixture fallback
  - "web_search" — web search fallback for unknown IPs
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from core.domains.game_ip.fixtures import load_fixture
from core.infrastructure.ports.signal_port import SignalEnrichmentPort
from core.state import GeodeState

log = logging.getLogger(__name__)

_signal_adapter_ctx: ContextVar[SignalEnrichmentPort | None] = ContextVar(
    "signal_adapter", default=None
)

# Minimum number of signal keys (excluding metadata) to consider live data sufficient
_MIN_LIVE_SIGNAL_KEYS = 2


def set_signal_adapter(adapter: SignalEnrichmentPort | None) -> None:
    """Inject signal enrichment adapter (called by GeodeRuntime.create())."""
    _signal_adapter_ctx.set(adapter)


def _fetch_web_signals(ip_name: str) -> dict[str, Any]:
    """Last-resort: web search for signal data on unknown IPs.

    Uses Anthropic native web_search to collect public data, then returns
    raw results as signals. Analysts (LLM-based) can work with unstructured text.
    """
    from core.tools.web_tools import GeneralWebSearchTool

    search = GeneralWebSearchTool()
    queries = [
        f"{ip_name} game franchise popularity statistics",
        f"{ip_name} anime manga fan community size reddit youtube",
    ]

    web_results: list[str] = []
    for query in queries:
        try:
            result = search.execute(query=query, max_results=3)
            text = result.get("result", {}).get("search_results", "")
            if text:
                web_results.append(text)
        except Exception as exc:
            log.debug("Web search failed for '%s': %s", query, exc)

    if not web_results:
        return {}

    return {
        "web_search_data": "\n---\n".join(web_results),
        "youtube_views": 0,
        "reddit_subscribers": 0,
        "fan_art_yoy_pct": 0.0,
        "google_trends_index": 0,
        "twitter_mentions_monthly": 0,
        "cosplay_events_annual": 0,
        "mod_patch_activity": "unknown",
        "genre_fit_keywords": [],
        "game_sales_data": "No fixture data — see web_search_data for live results.",
        "_enrichment_source": "web_search",
    }


def _count_data_keys(signals: dict[str, Any]) -> int:
    """Count non-metadata signal keys (exclude keys starting with '_')."""
    return sum(1 for k in signals if not k.startswith("_"))


def signals_node(state: GeodeState) -> dict[str, Any]:
    """Load external signals — MCP live → fixture fallback → mixed → web search.

    Returns both ``signals`` and ``signal_source`` for provenance tracking.
    """
    try:
        ip_name = state["ip_name"]
        live_signals: dict[str, Any] = {}

        # 1. Try injected MCP adapter first (CompositeSignalAdapter in production)
        adapter = _signal_adapter_ctx.get()
        if adapter is not None and adapter.is_available():
            try:
                live_signals = adapter.fetch_signals(ip_name)
                if live_signals and _count_data_keys(live_signals) >= _MIN_LIVE_SIGNAL_KEYS:
                    log.info(
                        "Live signals collected for '%s': %d keys from %s",
                        ip_name,
                        _count_data_keys(live_signals),
                        live_signals.get("_enrichment_sources", ["unknown"]),
                    )
                    return {
                        "signals": live_signals,
                        "signal_source": "live",
                    }
            except Exception as exc:
                log.warning("Signal adapter failed for %s: %s", ip_name, exc)

        # 2. Fixture fallback (known IPs)
        fixture_signals: dict[str, Any] = {}
        try:
            fixture = load_fixture(ip_name)
            fixture_signals = fixture["signals"]
        except ValueError:
            pass

        # 3. Mixed mode: live data exists but insufficient → merge with fixture
        if live_signals and fixture_signals:
            merged = {**fixture_signals, **live_signals}
            merged["_enrichment_source"] = "mixed"
            log.info(
                "Mixed signals for '%s': live=%d keys + fixture=%d keys",
                ip_name,
                _count_data_keys(live_signals),
                _count_data_keys(fixture_signals),
            )
            return {
                "signals": merged,
                "signal_source": "mixed",
            }

        # 4. Pure fixture fallback
        if fixture_signals:
            return {
                "signals": fixture_signals,
                "signal_source": "fixture",
            }

        # 5. Web search fallback (unknown IPs)
        log.info("No fixture for '%s' — fetching signals via web search", ip_name)
        web_signals = _fetch_web_signals(ip_name)
        if web_signals:
            return {
                "signals": web_signals,
                "signal_source": "web_search",
            }

        # 6. All sources exhausted — empty signals (analysts will handle)
        log.warning("No signal data available for '%s'", ip_name)
        return {"signals": {}, "signal_source": "fixture"}
    except Exception as exc:
        log.error("Node signals failed: %s", exc)
        return {"errors": [f"signals: {exc}"]}
