"""GEODE mascot — Geodi, the rose axolotl head, in the startup brand block.

Image-capable terminals draw the real transparent PNG with the brand text
(version / model / cwd / optional plan) to its RIGHT:
  * Kitty (Ghostty/kitty) — the text block is printed first (padded left to
    reserve the image column, so it scrolls naturally), then the image is
    overlaid on the left with relative cursor moves and animated in place:
    a bob loop with an eye-blink. Ghostty draws static images only, so the
    animation is client-driven (re-transmit each frame). q=2 suppresses the
    ACK the terminal would otherwise echo onto stdin.
  * iTerm2 / WezTerm — the static resting image with the brand text below.
Everywhere else it falls back to a solid half-block ANSI sprite beside the text.

Set ``GEODE_MASCOT_ANIM=0`` to skip the animation (static image instead).
Assets are baked by ``scripts/visualizations/geodi_ansi.py``.
"""

from __future__ import annotations

import os
import sys
import time

from rich.text import Text

from core.ui.console import console
from core.ui.geodi_art import GEODI_ART

_IMG_ROWS = 6  # image / block-sprite height in cells
_IMG_COLS = 14  # image width in cells (full-body sprite is ~1.20 wide at 6 rows)
_GAP = 3  # blank columns between image and text
_FRAME_DELAY = 0.09  # seconds per animation frame
_LOOPS = 2  # animation loops before settling

_CADET = "\x1b[1;38;2;95;158;160m"  # bold #5f9ea0 — matches the "header" theme
_DIM = "\x1b[2m"
_RST = "\x1b[0m"


def _brand_lines(version: str, model: str, cwd: str) -> list[str]:
    """Raw-ANSI brand lines for the cursor-positioned (image) layouts."""
    lines = [
        f"{_CADET}GEODE{_RST} v{version}",
        f"{_DIM}{model} · autonomous execution agent{_RST}",
        f"{_DIM}{cwd}{_RST}",
    ]
    plan = _resolve_active_plan_summary(model)
    if plan:
        lines.append(f"{_DIM}{plan}{_RST}")
    return lines


def _brand_text(version: str, model: str, cwd: str, pad: str = "") -> Text:
    """Rich brand block for the block-art fallback path."""
    t = Text()
    t.append(pad)
    t.append("GEODE", "header")
    t.append(f" v{version}\n")
    t.append(f"{pad}{model} · autonomous execution agent", "dim")
    t.append(f"\n{pad}{cwd}", "dim")
    plan = _resolve_active_plan_summary(model)
    if plan:
        t.append(f"\n{pad}{plan}", "dim")
    return t


def _resolve_active_plan_summary(model: str) -> str:
    """Render a one-line plan/quota label for the mascot block.

    Returns "" when no plan is registered or routing isn't initialised.
    """
    try:
        from core.llm.strategies.plan_registry import resolve_routing

        target = resolve_routing(model)
        if target is None:
            return ""
        plan = target.plan
        label = f"Plan: {plan.display_name}"
        if plan.quota is None:
            return label
        from core.llm.strategies.plan_registry import get_plan_registry

        usage = get_plan_registry().usage_for(plan.id)
        remaining = usage.remaining_in_window(plan)
        used = int(usage.weighted_calls)
        if usage.next_reset_at > 0:
            mins = max(0, usage.seconds_until_reset() // 60)
            reset_label = f"resets {mins}m"
        else:
            reset_label = f"window {plan.quota.window_s // 3600}h"
        return f"{label} (used {used}/{plan.quota.max_calls} · {remaining} left · {reset_label})"
    except Exception:
        return ""


# -- inline image (real PNG) ---------------------------------------------------


def _kitty(b64: str, rows: int, cols: int) -> str:
    """Kitty graphics: transmit+display a PNG in a cols×rows cell box, cursor put."""
    e = "\x1b"
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    out = []
    for j, ch in enumerate(chunks):
        more = 0 if j == len(chunks) - 1 else 1
        # q=2 suppresses the OK/error ACK the terminal would echo onto stdin.
        head = f"a=T,f=100,t=d,i=1,c={cols},r={rows},C=1,q=2,m={more}"
        out.append(f"{e}_G{head if j == 0 else f'q=2,m={more}'};{ch}{e}\\")
    return "".join(out)


def _kitty_beside(frames: list[str], resting: str, lines: list[str], rows: int, cols: int) -> None:
    """Text on the right (printed first, scrolls naturally), image overlaid left.

    Robust vs. the DECSC/DECRC approach: the text block is committed with plain
    newlines, then the cursor steps up ``rows`` (never scrolls), draws the image
    in the reserved left column, and steps back down. Each frame repeats that so
    the head bobs / blinks in place while the text stays put.
    """
    e = "\x1b"
    delete = f"{e}_Ga=d,d=i,i=1,q=2{e}\\"
    pad = " " * (cols + _GAP)
    top = max(0, (rows - len(lines)) // 2)  # vertical-centre the text against the image
    for r in range(rows):
        text = lines[r - top] if top <= r < top + len(lines) else ""
        sys.stdout.write(f"{pad}{text}\n")  # block scrolls in; cursor ends below it

    def draw(src: str) -> str:  # up to the block top, redraw image, back below
        return f"{e}[{rows}A\r{delete}{_kitty(src, rows, cols)}{e}[{rows}B\r"

    for _ in range(_LOOPS if len(frames) > 1 else 0):
        for fr in frames:
            sys.stdout.write(draw(fr))
            sys.stdout.flush()
            time.sleep(_FRAME_DELAY)
    sys.stdout.write(draw(resting))
    sys.stdout.flush()


def _draw_image(version: str, model: str, cwd: str) -> bool:
    """Draw Geodi + brand via an image protocol. True if drawn, False = use ANSI."""
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "").lower()
    prog = os.environ.get("TERM_PROGRAM", "").lower()
    animate = os.environ.get("GEODE_MASCOT_ANIM", "1") != "0"
    lines = _brand_lines(version, model, cwd)
    if (
        "kitty" in term
        or "ghostty" in term
        or prog == "ghostty"
        or os.environ.get("KITTY_WINDOW_ID")
    ):
        from core.ui.geodi_img import GEODI_FRAMES, GEODI_PNG_B64

        frames = GEODI_FRAMES if (animate and GEODI_FRAMES) else [GEODI_PNG_B64]
        sys.stdout.write("\n")
        _kitty_beside(frames, GEODI_PNG_B64, lines, _IMG_ROWS, _IMG_COLS)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True
    if (
        prog in ("iterm.app", "wezterm")
        or os.environ.get("ITERM_SESSION_ID")
        or os.environ.get("WEZTERM_PANE")
    ):
        from core.ui.geodi_img import GEODI_PNG_B64, GEODI_PNG_SIZE

        e = "\x1b"
        sys.stdout.write(
            f"\n{e}]1337;File=inline=1;height={_IMG_ROWS};preserveAspectRatio=1;"
            f"size={GEODI_PNG_SIZE}:{GEODI_PNG_B64}\a\n"
        )
        for ln in lines:
            sys.stdout.write(f"  {ln}\n")
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True
    return False


# -- ANSI fallback -------------------------------------------------------------


def _art_block() -> Text:
    """Solid half-block Geodi (baked), for terminals without image support."""
    t = Text(no_wrap=True)
    for i, row in enumerate(GEODI_ART):
        if i:
            t.append("\n")
        t.append_text(Text.from_ansi(row))
    return t


def render_mascot(version: str, model: str, cwd: str) -> None:
    """Draw Geodi (real image where supported, half-block otherwise) + brand text."""
    try:
        if _draw_image(version, model, cwd):
            return
    except Exception:  # noqa: S110 — never let branding break startup
        pass

    console.print()
    from rich.table import Table

    grid = Table.grid(padding=(0, 3))
    grid.add_column()
    grid.add_column(vertical="middle")
    grid.add_row(_art_block(), _brand_text(version, model, cwd))
    console.print(grid)
    console.print()
