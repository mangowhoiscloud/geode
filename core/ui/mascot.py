"""GEODE mascot — Geodi, the rose axolotl, in the startup brand block.

Terminals that speak an inline-image protocol draw the real transparent PNG:
  * Kitty (Ghostty/kitty) — the CLI cycles a short bob loop on startup, then
    settles on the resting frame (Ghostty draws static images only, so the
    animation is client-driven: re-transmit each frame with a small delay).
  * iTerm2 / WezTerm — the static resting image.
Everywhere else it falls back to a solid half-block ANSI sprite. Either way the
brand text (version / model / cwd / optional plan) follows.

Set ``GEODE_MASCOT_ANIM=0`` to skip the intro animation (static image instead).
Assets are baked by ``scripts/visualizations/geodi_ansi.py``.
"""

from __future__ import annotations

import os
import sys
import time

from rich.text import Text

from core.ui.console import console
from core.ui.geodi_art import GEODI_ART

_IMG_ROWS = 6  # cell height of the inline image / block sprite
_FRAME_DELAY = 0.09  # seconds per bob frame
_LOOPS = 2  # bob cycles before settling


def _brand_text(version: str, model: str, cwd: str, pad: str = "") -> Text:
    """Version / model / cwd / optional plan, each line prefixed with ``pad``."""
    t = Text()
    t.append(pad)
    t.append("GEODE", "header")
    t.append(f" v{version}\n")
    t.append(f"{pad}{model} · autonomous execution agent", "dim")
    t.append(f"\n{pad}{cwd}", "dim")
    plan_summary = _resolve_active_plan_summary(model)
    if plan_summary:
        t.append(f"\n{pad}{plan_summary}", "dim")
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


def _kitty(b64: str, rows: int, img_id: int = 1) -> str:
    """Kitty graphics: transmit+display a PNG at r=rows, keeping the cursor put."""
    e = "\x1b"
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    out = []
    for j, ch in enumerate(chunks):
        more = 0 if j == len(chunks) - 1 else 1
        keys = f"a=T,f=100,t=d,i={img_id},r={rows},C=1,m={more}" if j == 0 else f"m={more}"
        out.append(f"{e}_G{keys};{ch}{e}\\")
    return "".join(out)


def _play_kitty_intro(frames: list[str], resting: str, rows: int) -> None:
    """Cycle the bob frames in place, then leave the resting frame and step below."""
    e = "\x1b"
    delete = f"{e}_Ga=d,d=i,i=1{e}\\"  # drop image 1 before redrawing (avoids stacking)
    for _ in range(_LOOPS):
        for fr in frames:
            sys.stdout.write(delete + _kitty(fr, rows))
            sys.stdout.flush()
            time.sleep(_FRAME_DELAY)
    sys.stdout.write(delete + _kitty(resting, rows) + "\n" * rows)
    sys.stdout.flush()


def _draw_image(rows: int) -> bool:
    """Draw Geodi via an image protocol if the terminal supports one. False = no."""
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "").lower()
    prog = os.environ.get("TERM_PROGRAM", "").lower()
    animate = os.environ.get("GEODE_MASCOT_ANIM", "1") != "0"
    if (
        "kitty" in term
        or "ghostty" in term
        or prog == "ghostty"
        or os.environ.get("KITTY_WINDOW_ID")
    ):
        from core.ui.geodi_img import GEODI_FRAMES, GEODI_PNG_B64

        if animate and GEODI_FRAMES:
            _play_kitty_intro(GEODI_FRAMES, GEODI_PNG_B64, rows)
        else:
            sys.stdout.write(_kitty(GEODI_PNG_B64, rows) + "\n" * rows)
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
            f"{e}]1337;File=inline=1;height={rows};preserveAspectRatio=1;size={GEODI_PNG_SIZE}:{GEODI_PNG_B64}\a"
        )
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
    console.print()
    try:
        if _draw_image(_IMG_ROWS):
            console.print(_brand_text(version, model, cwd, pad="  "))
            console.print()
            return
    except Exception:  # noqa: S110 — never let branding break startup
        pass

    from rich.table import Table

    grid = Table.grid(padding=(0, 3))
    grid.add_column()
    grid.add_column(vertical="middle")
    grid.add_row(_art_block(), _brand_text(version, model, cwd))
    console.print(grid)
    console.print()
