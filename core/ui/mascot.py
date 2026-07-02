"""GEODE mascot — Geodi, the rose axolotl, in the startup brand block.

The sprite is the hand-authored pixel grid in ``core/ui/geodi_art.py``,
rendered as truecolor half-blocks: ONE code path for every terminal — no
Kitty/iTerm2 image protocol, no baked PNG, no animation env knob. The brand
text sits to the sprite's right, vertically centred:

    line 1  ``◆ GEODE v{version}``   (rose mark, bold name)
    line 2  dim ``{model} · {cwd}``  ($HOME collapsed to ~)
    line 3  dim ``/help for commands · type naturally``
    line 4  dim plan/quota summary   (only when a plan is registered)
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.text import Text

from core.ui import spinner_glyph
from core.ui.console import console
from core.ui.geodi_art import geodi_pixel_lines

_GAP = 3  # blank columns between sprite and text
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_RST = "\x1b[0m"


def _collapse_home(path: str) -> str:
    """Collapse the home prefix (``$HOME/dev`` -> ``~/dev``) — short, machine-neutral cwd."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _spec_lines(version: str, model: str, cwd: str) -> list[str]:
    """Brand text beside the sprite: mark + version, context, quickstart hint."""
    lines = [
        f"{spinner_glyph.ROSE}{spinner_glyph.GLYPH}{_RST} {_BOLD}GEODE{_RST} v{version}",
        f"{_DIM}{model} · {_collapse_home(cwd)}{_RST}",
        f"{_DIM}/help for commands · type naturally{_RST}",
    ]
    plan = _resolve_active_plan_summary(model)
    if plan:
        lines.append(f"{_DIM}{plan}{_RST}")
    return lines


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


def render_mascot(version: str, model: str, cwd: str) -> None:
    """Draw the pixel-art Geodi with the brand block to its right."""
    art = geodi_pixel_lines()
    spec = _spec_lines(version, model, cwd)
    top = max(0, (len(art) - len(spec)) // 2)
    pad = " " * _GAP
    console.print()
    for i, row in enumerate(art):
        j = i - top
        side = f"{pad}{spec[j]}" if 0 <= j < len(spec) else ""
        console.print(Text.from_ansi(f"  {row}{side}", no_wrap=True))
    console.print()
