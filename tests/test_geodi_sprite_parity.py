"""Geodi sprite dual-SoT drift guard.

The portfolio page renders the CLI welcome-screen mascot from a transcription
of ``core/ui/geodi_art.py`` (``site/src/components/geode/geodi-sprite.tsx``).
Grid or palette drift between the two would silently break the page's core
claim ("the same pixel data the CLI draws"), so both are pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.ui.geodi_art import GEODI_PALETTE, GEODI_PIXELS

SPRITE_TSX = (
    Path(__file__).resolve().parents[1]
    / "site"
    / "src"
    / "components"
    / "geode"
    / "geodi-sprite.tsx"
)


def _sprite_source() -> str:
    return SPRITE_TSX.read_text(encoding="utf-8")


def test_web_sprite_grid_matches_cli_canon() -> None:
    web_rows = re.findall(r'^\s*"([.prew]{22})",$', _sprite_source(), flags=re.MULTILINE)
    assert web_rows == GEODI_PIXELS, (
        "geodi-sprite.tsx GEODI_PIXELS drifted from core/ui/geodi_art.py — "
        "update both in the same commit"
    )


def test_web_sprite_palette_matches_cli_canon() -> None:
    web_palette = dict(re.findall(r'([prew]): "(#[0-9A-Fa-f]{6})"', _sprite_source()))
    cli_palette = {ch: hex_color for ch, hex_color in GEODI_PALETTE.items() if hex_color}
    assert web_palette == cli_palette, (
        "geodi-sprite.tsx palette drifted from core/ui/geodi_art.py GEODI_PALETTE"
    )
