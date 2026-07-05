"""Geodi pixel art — the hand-authored native sprite (no image protocol).

Character canon: a round rose axolotl FACE with EXACTLY six gill stalks
(three per side, deeper rose, visibly separated), simple symmetric 2x2 dark
eyes with a 1px white catchlight in the top-right corner of each, a subtle
deep-rose cheek blush beside the eyes, and a tiny 2px mouth. The face-only
sprite IS the canon — no full-body (belly/feet) variant is kept.

The sprite is authored as a 22x12 pixel grid (``GEODI_PIXELS``). Pixels
render as truecolor half-blocks — ``▀`` with fg = upper pixel, bg = lower
pixel, two pixels per terminal cell — so the mascot draws as 22 cols x 6
rows, sitting level with the three-line welcome brand block in ANY
truecolor terminal. Transparent pixels reset to the terminal's default
background.

Hand-edit ``GEODI_PIXELS`` directly; every row must stay exactly 22 chars
and the row count must stay even (rows pair into half-block cells).
Live preview: ``python -m core.ui.geodi_art``.
"""

from __future__ import annotations

_RESET = "\x1b[0m"

# char -> hex color; "." = transparent (terminal default background).
GEODI_PALETTE: dict[str, str | None] = {
    ".": None,
    "p": "#F49BC4",  # body — signature Axolotl Rose
    "r": "#E0699F",  # deep rose — gill stalks, cheek blush
    "e": "#2B2233",  # near-black — eyes, mouth
    "w": "#FFFFFF",  # white — eye catchlight
}

# 22 wide x 12 tall. Rows pair top/bottom into half-block cells (6 rows out).
# Gills: THREE stalks per side — upper (r1), middle (r3), lower (r5) — each
# separated by a gill-free row so the three stalks stay visually distinct.
# Face (kawaii): symmetric 2x2 dark eyes (r6-r7) with the 1px catchlight in
# the TOP-RIGHT corner of each, cheek blush beside the eyes (r8), ONE tiny
# 2px mouth (r9, cols 10-11), rounded chin (r10-r11). No other dark pixels
# on the face.
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
