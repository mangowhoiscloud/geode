"""Layer 2: Signals — External signal collection (fixture-based)."""

from __future__ import annotations

from typing import Any

from geode.fixtures import load_fixture
from geode.state import GeodeState


def signals_node(state: GeodeState) -> dict:
    """Load external signals from fixtures."""
    ip_name = state["ip_name"]
    fixture = load_fixture(ip_name)
    signals: dict[str, Any] = fixture["signals"]
    return {"signals": signals}
