"""Layer 2: Signals — External signal collection with graceful degradation.

Execution path:
  1. SignalEnrichmentPort adapter (live API if available)
  2. Fixture fallback (known IPs)
  3. Web search fallback (unknown IPs — external data mode)
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from core.fixtures import load_fixture
from core.infrastructure.ports.signal_port import SignalEnrichmentPort
from core.state import GeodeState

log = logging.getLogger(__name__)

_signal_adapter_ctx: ContextVar[SignalEnrichmentPort | None] = ContextVar(
    "signal_adapter", default=None
)


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


def signals_node(state: GeodeState) -> dict[str, Any]:
    """Load external signals — adapter → fixture → web search fallback."""
    try:
        ip_name = state["ip_name"]

        # 1. Try injected adapter first (may be live API)
        adapter = _signal_adapter_ctx.get()
        if adapter is not None and adapter.is_available():
            try:
                signals = adapter.fetch_signals(ip_name)
                if signals:
                    return {"signals": signals}
            except Exception as exc:
                log.warning("Signal adapter failed for %s: %s", ip_name, exc)

        # 2. Fixture fallback (known IPs)
        try:
            fixture = load_fixture(ip_name)
            return {"signals": fixture["signals"]}
        except ValueError:
            pass

        # 3. Web search fallback (unknown IPs)
        log.info("No fixture for '%s' — fetching signals via web search", ip_name)
        web_signals = _fetch_web_signals(ip_name)
        if web_signals:
            return {"signals": web_signals}

        # 4. All sources exhausted — empty signals (analysts will handle)
        log.warning("No signal data available for '%s'", ip_name)
        return {"signals": {}}
    except Exception as exc:
        log.error("Node signals failed: %s", exc)
        return {"errors": [f"signals: {exc}"]}
