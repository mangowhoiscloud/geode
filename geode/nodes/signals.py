"""Layer 2: Signals — External signal collection (fixture-based)."""

from __future__ import annotations

import logging
from typing import Any

from geode.fixtures import load_fixture
from geode.state import GeodeState

log = logging.getLogger(__name__)


def signals_node(state: GeodeState) -> dict[str, Any]:
    """Load external signals from fixtures."""
    try:
        ip_name = state["ip_name"]
        fixture = load_fixture(ip_name)
        signals: dict[str, Any] = fixture["signals"]
        return {"signals": signals}
    except Exception as exc:
        log.error("Node signals failed: %s", exc)
        return {"errors": [f"signals: {exc}"]}
