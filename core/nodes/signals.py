"""Layer 2: Signals — External signal collection with graceful degradation.

Execution path:
  1. SignalEnrichmentPort adapter (live API if available)
  2. Fixture fallback (always available)
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


def signals_node(state: GeodeState) -> dict[str, Any]:
    """Load external signals — adapter-first with fixture fallback."""
    try:
        ip_name = state["ip_name"]

        # Try injected adapter first (may be live API)
        adapter = _signal_adapter_ctx.get()
        if adapter is not None and adapter.is_available():
            try:
                signals = adapter.fetch_signals(ip_name)
                if signals:
                    return {"signals": signals}
            except Exception as exc:
                log.warning("Signal adapter failed for %s: %s — using fixture", ip_name, exc)

        # Fixture fallback (always works)
        fixture = load_fixture(ip_name)
        fixture_signals: dict[str, Any] = fixture["signals"]
        return {"signals": fixture_signals}
    except Exception as exc:
        log.error("Node signals failed: %s", exc)
        return {"errors": [f"signals: {exc}"]}
