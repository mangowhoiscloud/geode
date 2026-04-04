"""Rich Console — GEODE brand theme with thread-safe session isolation.

Each IPC handler thread gets its own Rich Console instance via
``set_thread_console()``.  The module-level ``console`` is a lightweight
proxy that delegates attribute access to the thread-local Console (or
falls back to the process-wide default).  This prevents cross-session
output contamination when multiple thin-CLI clients connect to
``geode serve`` concurrently.

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
import threading
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


# ───────────────────────────────────────────────────────────────────────────
# Thread-safe Console proxy
# ───────────────────────────────────────────────────────────────────────────

_default_console = Console(theme=GEODE_THEME, width=_get_terminal_width())


class _ConsoleProxy:
    """Thread-safe proxy delegating to per-thread Console instances.

    IPC handler threads call ``set_thread_console()`` to install a
    session-scoped Console whose ``file`` writes to the client's socket.
    All other threads transparently fall back to ``_default_console``.

    Both ``__getattr__`` and ``__setattr__`` are forwarded, so existing
    code like ``console._file = buf`` in ``capture_output()`` safely
    mutates the *thread-local* Console — never the shared default.
    """

    _local = threading.local()

    def __init__(self, default: Console) -> None:
        # Bypass our __setattr__ to store the default on the instance.
        object.__setattr__(self, "_default", default)

    def _current(self) -> Console:
        """Return thread-local Console, or fall back to default."""
        local: Console | None = getattr(self._local, "console", None)
        if local is not None:
            return local
        default: Console = object.__getattribute__(self, "_default")
        return default

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._current(), name, value)


console: Any = _ConsoleProxy(_default_console)


def set_thread_console(c: Console) -> None:
    """Install a thread-local Console for the current thread.

    Called by CLIPoller at the start of each IPC handler thread so that
    all ``console.print(...)`` calls within that thread route to the
    session's ``_StreamingWriter`` instead of the shared stdout.
    """
    _ConsoleProxy._local.console = c


def reset_thread_console() -> None:
    """Remove thread-local Console, reverting to the default."""
    _ConsoleProxy._local.__dict__.pop("console", None)


def make_session_console(file: Any) -> Console:
    """Create a session-scoped Console writing to *file*.

    Returns a fully configured Console with the GEODE theme, forced
    ANSI output, and truecolor — suitable for IPC streaming writers.
    """
    from rich.color import ColorSystem

    c = Console(theme=GEODE_THEME, file=file, force_terminal=True, width=120)
    c._color_system = ColorSystem.TRUECOLOR
    return c


@contextmanager
def capture_output() -> Generator[StringIO, None, None]:
    """Capture console output with ANSI styling preserved.

    Temporarily redirects the current thread's console to a StringIO
    buffer with ``force_terminal=True`` and a valid color system so
    that Rich markup is rendered as ANSI escape codes — even when the
    process's stdout is not a TTY (e.g. ``geode serve`` with DEVNULL).

    Thread-safe: operates on the thread-local Console (via the proxy),
    so concurrent IPC sessions don't interfere with each other.

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

    Thread-safe: operates on the thread-local Console (via the proxy).
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
