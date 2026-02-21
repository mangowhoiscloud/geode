"""Layer 1: Cortex — MonoLake data retrieval (fixture-based)."""

from __future__ import annotations

from geode.fixtures import FIXTURE_MAP, load_fixture
from geode.state import GeodeState

# Re-export for CLI /list command
_FIXTURE_MAP = FIXTURE_MAP


def cortex_node(state: GeodeState) -> dict:
    """Load IP info and MonoLake data from fixtures."""
    ip_name = state["ip_name"]
    fixture = load_fixture(ip_name)
    return {
        "ip_info": fixture["ip_info"],
        "monolake": fixture["monolake"],
    }
