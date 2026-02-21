"""Shared fixture utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent

FIXTURE_MAP: dict[str, str] = {
    "cowboy bebop": "cowboy_bebop.json",
    "ghost in the shell": "ghost_in_shell.json",
    "berserk": "berserk.json",
}


def load_fixture(ip_name: str) -> dict[str, Any]:
    """Load a fixture JSON file by IP name."""
    key = ip_name.lower().strip()
    filename = FIXTURE_MAP.get(key)
    if not filename:
        raise ValueError(
            f"No fixture found for '{ip_name}'. Available: {list(FIXTURE_MAP.keys())}"
        )
    path = FIXTURES_DIR / filename
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result
