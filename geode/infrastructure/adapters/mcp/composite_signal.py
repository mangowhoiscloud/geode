"""Composite Signal Adapter — chains multiple signal sources with fallback."""

from __future__ import annotations

import logging
from typing import Any

from geode.infrastructure.ports.signal_port import SignalEnrichmentPort

log = logging.getLogger(__name__)


class CompositeSignalAdapter:
    """Chain multiple signal adapters with merge + fallback.

    Tries each adapter in order, merging results. If all fail,
    returns empty dict (caller falls back to fixture).
    Implements SignalEnrichmentPort.
    """

    def __init__(self, adapters: list[SignalEnrichmentPort]) -> None:
        self._adapters = adapters

    def fetch_signals(self, ip_name: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        sources: list[str] = []
        for adapter in self._adapters:
            if not adapter.is_available():
                continue
            try:
                signals = adapter.fetch_signals(ip_name)
                if signals:
                    # Warn on key collisions (excluding metadata keys)
                    for key in signals:
                        if key in merged and not key.startswith("_"):
                            log.debug(
                                "Signal key '%s' overwritten by %s",
                                key,
                                type(adapter).__name__,
                            )
                    merged.update(signals)
                    src = signals.get("_enrichment_source", type(adapter).__name__)
                    sources.append(src)
            except Exception as exc:
                log.warning("Signal adapter %s failed: %s", type(adapter).__name__, exc)
        if sources:
            merged["_enrichment_sources"] = sources
        return merged

    def is_available(self) -> bool:
        return any(a.is_available() for a in self._adapters)
