"""Geodi pixel art — the hand-authored native sprite (no image protocol).

Character canon: a round rose axolotl with EXACTLY six gill stalks (three per
side, deeper rose, visibly separated), simple symmetric 2x2 dark eyes with a
1px white catchlight in the top-right corner of each, a tiny 2px mouth, a
lighter belly patch, and a subtle deep-rose cheek blush beside the eyes.

The canonical sprite is authored as a 22x20 pixel grid
(``GEODI_SOURCE_PIXELS``). The welcome screen renders a face-only 22x12 pixel
derivative (``GEODI_PIXELS``) that preserves the original silhouette while
matching the adjacent three-line brand block. Pixels render as truecolor
half-blocks — ``▀`` with fg = upper pixel, bg = lower pixel, two pixels per
terminal cell — so the mascot draws as 22 cols x 6 rows — the head down to the mouth, cropped
to a round face (belly/feet removed) so it sits level with the 3-line welcome — in ANY
truecolor terminal. Transparent pixels reset to the terminal's default
background.

Hand-edit ``GEODI_SOURCE_PIXELS`` first; keep ``GEODI_PIXELS`` as a compact
derivative of that shape. Every compact row must stay exactly 22 chars.
Live preview: ``python -m core.ui.geodi_art``.
"""

from __future__ import annotations

_RESET = "\x1b[0m"

# char -> hex color; "." = transparent (terminal default background).
GEODI_PALETTE: dict[str, str | None] = {
    ".": None,
    "p": "#F49BC4",  # body — signature Axolotl Rose
    "r": "#E0699F",  # deep rose — gill stalks, cheek blush
    "l": "#FCD9E8",  # light rose — belly patch
    "e": "#2B2233",  # near-black — eyes, smile
    "w": "#FFFFFF",  # white — eye catchlight
}

# 22 wide x 20 tall. Full-detail source retained to prevent the compact welcome
# mascot from drifting into a different character.
GEODI_SOURCE_PIXELS: list[str] = [
    "........pppppp........",
    "......pppppppppp......",
    ".rr..pppppppppppp..rr.",
    "..rrpppppppppppppprr..",
    "....pppppppppppppp....",
    ".rrrpppppppppppppprrr.",
    "....pppppppppppppp....",
    "..rrpppppppppppppprr..",
    "....pppewppppewppp....",
    "....pppeeppppeeppp....",
    "....prrpppppppprrp....",
    "....ppppppeepppppp....",
    "....ppppllllllpppp....",
    "....pppllllllllppp....",
    "....pppllllllllppp....",
    ".....pppllllllppp.....",
    "......pppppppppp......",
    ".......pppppppp.......",
    "......ppp....ppp......",
    "......ppp....ppp......",
]

# 16 wide x 14 tall. Rows pair top/bottom into half-block cells (7 rows out).
# Gills: THREE stalks per side — upper diagonal (r2-r3), middle (r5), lower
# (r7) — with fully transparent side rows (r4, r6) between them so each
# counts visually. Face (kawaii): symmetric 2x2 dark eyes (r8-r9) with the
# 1px catchlight in the TOP-RIGHT corner of each, nothing above them but
# body; cheek blush one row below the eyes (r10); ONE tiny 2px mouth row
# (r11, cols 8-9). No other dark pixels on the face.
GEODI_PIXELS: list[str] = [
    "........pppppp........",
    ".rr..pppppppppppp..rr.",
    "....pppppppppppppp....",
    ".rrrpppppppppppppprrr.",
    "....pppppppppppppp....",
    "..rrpppppppppppppprr..",
    "....pppewppppewppp....",
    "....pppeeppppeeppp....",
    "....prrpppppppprrp....",
    "....ppppppeepppppp....",
    ".....pppppppppppp.....",
    "......pppppppppp......",
]


def _sgr_rgb(hex_color: str) -> str:
    """``#RRGGBB`` -> ``r;g;b`` for a truecolor SGR parameter."""
    return ";".join(str(int(hex_color[i : i + 2], 16)) for i in (1, 3, 5))


def geodi_pixel_lines() -> list[str]:
    """Render ``GEODI_PIXELS`` as ANSI half-block lines (two pixels per cell).

    Each cell: both pixels colored -> ``▀`` with fg=upper/bg=lower; upper only
    -> reset + fg ``▀`` (default bg below); lower only -> reset + fg ``▄``;
    both transparent -> reset + space, so rows keep a constant compact width
    and text can align beside the sprite.
    """
    lines: list[str] = []
    for top_row, bottom_row in zip(GEODI_PIXELS[0::2], GEODI_PIXELS[1::2], strict=True):
        cells: list[str] = []
        for top_ch, bottom_ch in zip(top_row, bottom_row, strict=True):
            top = GEODI_PALETTE[top_ch]
            bottom = GEODI_PALETTE[bottom_ch]
            if top is None and bottom is None:
                cells.append(f"{_RESET} ")
            elif top is not None and bottom is not None:
                cells.append(f"\x1b[38;2;{_sgr_rgb(top)};48;2;{_sgr_rgb(bottom)}m▀")
            elif top is not None:
                cells.append(f"{_RESET}\x1b[38;2;{_sgr_rgb(top)}m▀")
            else:
                cells.append(f"{_RESET}\x1b[38;2;{_sgr_rgb(bottom or '')}m▄")
        cells.append(_RESET)
        lines.append("".join(cells))
    return lines


if __name__ == "__main__":
    # Live preview: python -m core.ui.geodi_art
    for _line in geodi_pixel_lines():
        print(f"  {_line}")
