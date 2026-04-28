"""Shared fixture utilities.

Supports both hand-crafted IP fixtures (root) and ported Steam game
fixtures (steam/ subdirectory).  All ``*.json`` files are auto-discovered
at import time so new fixtures only need to be dropped into the directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent

# --- Auto-discover all fixture JSON files ---
FIXTURE_MAP: dict[str, str] = {}

for _p in FIXTURES_DIR.rglob("*.json"):
    if _p.name.startswith("_"):  # skip meta files like _fixture_map.json
        continue
    _key = _p.stem.replace("_", " ")
    _rel = str(_p.relative_to(FIXTURES_DIR))
    FIXTURE_MAP[_key] = _rel


def load_fixture(ip_name: str) -> dict[str, Any]:
    """Load a fixture JSON file by IP name."""
    key = ip_name.lower().strip()
    filename = FIXTURE_MAP.get(key)
    if not filename:
        raise ValueError(f"No fixture found for '{ip_name}'. Available: {list(FIXTURE_MAP.keys())}")
    path = FIXTURES_DIR / filename
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def list_fixtures(source: str | None = None) -> list[str]:
    """List available fixture names, optionally filtered by source.

    Args:
        source: "ip" for hand-crafted IP fixtures, "steam" for ported
                Steam games, or None for all.
    """
    if source == "steam":
        return sorted(k for k, v in FIXTURE_MAP.items() if v.startswith("steam/"))
    if source == "ip":
        return sorted(k for k, v in FIXTURE_MAP.items() if not v.startswith("steam/"))
    return sorted(FIXTURE_MAP.keys())
