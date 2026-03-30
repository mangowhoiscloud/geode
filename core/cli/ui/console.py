"""Rich Console singleton — GEODE brand theme.

Brand colors (from axolotl mascot, toned-down for readability):
  Rose (#d4a0a0)     — axolotl body → brand identity (muted coral)
  Amber (#e0b040)    — headlamp → energy, highlights (warm gold)
  Cadet (#5f9ea0)    — crystals, tech → interactive elements (calm cyan)
  Iris (#9775c4)     — gills → accent, tool names (soft purple)
  Lavender (#a88fd4) — geode crystal purple (muted crystal)
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from io import StringIO
from typing import Any

from rich.console import Console
from rich.theme import Theme

# -- Brand palette (terminal-safe, toned-down) --
_CORAL = "#d4a0a0"  # axolotl body (muted rose)
_GOLD = "#e0b040"  # headlamp (warm amber)
_CYAN = "#5f9ea0"  # crystals / tech (calm cadet)
_MAGENTA = "#9775c4"  # gills / accent (soft iris)
_CRYSTAL = "#a88fd4"  # geode crystal (muted lavender)

GEODE_THEME = Theme(
    {
        # -- Brand --
        "brand": f"bold {_CORAL}",
        "brand.accent": f"bold {_MAGENTA}",
        "brand.gold": f"bold {_GOLD}",
        "brand.crystal": _CRYSTAL,
        # -- Semantic --
        "header": f"bold {_CYAN}",
        "step": "bold green",
        "score": f"bold {_GOLD}",
        "tier_s": "bold white on red",
        "tier_a": "bold white on blue",
        "tier_b": "bold white on green",
        "tier_c": "dim white on grey37",
        "label": "bold",
        "value": _CYAN,
        "warning": f"bold {_GOLD}",
        "error": "bold red",
        "success": "bold green",
        "muted": "dim",
        "status.spinner": _CYAN,
        # -- Agentic UI (Claude Code-style) --
        "tool_name": f"bold {_MAGENTA}",
        "tool_args": f"dim {_CYAN}",
        "token_info": "dim",
        "plan_step": _CYAN,
        "subagent": "bold blue",
        # -- Mascot --
        "mascot.gills": _MAGENTA,
        "mascot.lamp": f"bold {_GOLD}",
        "mascot.body": "white",
        "mascot.outline": "dim",
    }
)


def _get_terminal_width() -> int | None:
    """Return dynamic terminal width (min=80, max=160), or None for non-TTY."""
    if not sys.stdout.isatty():
        return 120  # fallback for pipes, CI
    cols = shutil.get_terminal_size().columns
    return max(80, min(cols, 160))


console = Console(theme=GEODE_THEME, width=_get_terminal_width())


@contextmanager
def capture_output() -> Generator[StringIO, None, None]:
    """Capture console output with ANSI styling preserved.

    Temporarily redirects the global console to a StringIO buffer with
    ``force_terminal=True`` and a valid color system so that Rich markup
    is rendered as ANSI escape codes — even when the process's stdout is
    not a TTY (e.g. ``geode serve`` started with ``stdout=DEVNULL``).

    Usage::

        with capture_output() as buf:
            console.print("[bold]hello[/bold]")
        text = buf.getvalue()   # contains ANSI-styled text
    """
    from rich.color import ColorSystem

    buf = StringIO()
    old_file = console._file
    old_force = console._force_terminal
    old_color = console._color_system
    console._file = buf
    console._force_terminal = True
    if old_color is None:
        console._color_system = ColorSystem.TRUECOLOR
    try:
        yield buf
    finally:
        console._file = old_file
        console._force_terminal = old_force
        console._color_system = old_color


@contextmanager
def redirect_console(target: Any) -> Generator[None, None, None]:
    """Redirect console output to *target* with ANSI styling preserved.

    Like ``capture_output`` but writes to an arbitrary file-like object
    (e.g. ``_StreamingWriter``) instead of a ``StringIO`` buffer.
    Ensures ``_color_system`` is set so styles render even when the
    process stdout is DEVNULL.
    """
    from rich.color import ColorSystem

    old_file = console._file
    old_force = console._force_terminal
    old_color = console._color_system
    console._file = target
    console._force_terminal = True
    if old_color is None:
        console._color_system = ColorSystem.TRUECOLOR
    try:
        yield
    finally:
        console._file = old_file
        console._force_terminal = old_force
        console._color_system = old_color
