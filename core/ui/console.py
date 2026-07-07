"""Rich Console — GEODE brand theme with task/thread-safe session isolation.

Each IPC handler task/thread gets its own Rich Console instance via
``set_thread_console()``.  The module-level ``console`` is a lightweight
proxy that delegates attribute access to the task/thread-local Console (or
falls back to the process-wide default). This prevents cross-session output
contamination when multiple thin-CLI clients connect to ``geode serve``
concurrently.

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

from core.ui.context_local import ContextLocal

# -- Brand palette — hex SoT lives in core.ui.palette (drift-pinned) --
from core.ui.palette import CORAL as _CORAL
from core.ui.palette import CRYSTAL as _CRYSTAL
from core.ui.palette import CYAN as _CYAN
from core.ui.palette import GOLD as _GOLD
from core.ui.palette import MAGENTA as _MAGENTA

GEODE_THEME = Theme(
    {
        # -- Brand --
        "brand": f"bold {_CORAL}",
        "brand.accent": f"bold {_MAGENTA}",
        "brand.gold": f"bold {_GOLD}",
        "brand.crystal": _CRYSTAL,
        # -- Semantic --
        "header": f"bold {_CYAN}",
        "step": f"bold {_CYAN}",
        "score": f"bold {_GOLD}",
        "tier_s": "bold white on red",
        "tier_a": "bold white on blue",
        "tier_b": f"bold white on {_CYAN}",
        "tier_c": "dim white on grey37",
        "label": "bold",
        "value": _CYAN,
        "warning": f"bold {_GOLD}",
        "error": "bold red",
        "success": f"bold {_CYAN}",
        "muted": "dim",
        "status.spinner": _CYAN,
        # -- Agentic UI (Claude Code-style) --
        "tool_name": f"bold {_MAGENTA}",
        "tool_args": f"dim {_CYAN}",
        "token_info": "dim",
        "plan_step": _CYAN,
        "subagent": "bold blue",
    }
)


def _get_terminal_width() -> int | None:
    """Return dynamic terminal width (min=80, max=160), or None for non-TTY."""
    if not sys.stdout.isatty():
        return 120  # fallback for pipes, CI
    cols = shutil.get_terminal_size().columns
    return max(80, min(cols, 160))


def refresh_console_width() -> None:
    """Refresh the active Rich console width from the current terminal.

    The default Console is created once at import time. If the user resizes
    the terminal before the final Markdown render, Rich code-block backgrounds
    otherwise keep painting to the stale width and leave stair-step artifacts.
    Test/capture consoles and non-TTY output keep their fixed width.
    """
    if not sys.stdout.isatty():
        return
    current = console._current() if isinstance(console, _ConsoleProxy) else console
    current.width = _get_terminal_width() or current.width


# ───────────────────────────────────────────────────────────────────────────
# Thread-safe Console proxy
# ───────────────────────────────────────────────────────────────────────────

_default_console = Console(theme=GEODE_THEME, width=_get_terminal_width())


class _ConsoleProxy:
    """Task/thread-safe proxy delegating to session Console instances.

    IPC handlers call ``set_thread_console()`` to install a
    session-scoped Console whose ``file`` writes to the client's socket.
    All other tasks/threads transparently fall back to ``_default_console``.

    Both ``__getattr__`` and ``__setattr__`` are forwarded, so existing
    code like ``console._file = buf`` in ``capture_output()`` safely
    mutates the task/thread-local Console — never the shared default.
    """

    _local = ContextLocal("geode_console_local")

    def __init__(self, default: Console) -> None:
        # Bypass our __setattr__ to store the default on the instance.
        object.__setattr__(self, "_default", default)

    def _current(self) -> Console:
        """Return task/thread-local Console, or fall back to default."""
        local: Console | None = getattr(self._local, "console", None)
        if local is not None:
            return local
        default: Console = object.__getattribute__(self, "_default")
        return default

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._current(), name, value)

    # Dunder methods are looked up on the type, not the instance, so
    # __getattr__ doesn't intercept them. Rich's FileProxy calls
    # `with console:` which requires explicit __enter__/__exit__.
    def __enter__(self) -> Console:
        return self._current().__enter__()

    def __exit__(self, *args: Any) -> None:
        self._current().__exit__(*args)


console: Any = _ConsoleProxy(_default_console)


def set_thread_console(c: Console) -> None:
    """Install a task/thread-local Console for the current execution context.

    Called by CLIPoller at the start of each IPC prompt so that all
    ``console.print(...)`` calls in that task route to the session's
    ``_StreamingWriter`` instead of the shared stdout.
    """
    _ConsoleProxy._local.console = c


def reset_thread_console() -> None:
    """Remove task/thread-local Console, reverting to the default."""
    _ConsoleProxy._local.__dict__.pop("console", None)


def make_session_console(
    file: Any,
    *,
    force_terminal: bool = True,
    width: int = 120,
) -> Console:
    """Create a session-scoped Console writing to *file*.

    Returns a fully configured Console with the GEODE theme — suitable
    for IPC streaming writers.

    v0.84.0 — ``force_terminal`` and ``width`` are now propagated from
    the thin CLI via the ``client_capability`` IPC message. When the
    thin client's stdout is not a TTY (heredoc, pipe, CI), the daemon
    constructs the per-thread Console with ``force_terminal=False`` so
    Rich emits plain text instead of ANSI cursor-up / spinner braille
    frames. The truecolor color-system override is still applied when
    ANSI output is requested, mirroring the previous behavior.
    """
    from rich.color import ColorSystem

    c = Console(theme=GEODE_THEME, file=file, force_terminal=force_terminal, width=width)
    if force_terminal:
        c._color_system = ColorSystem.TRUECOLOR
    return c


@contextmanager
def capture_output() -> Generator[StringIO, None, None]:
    """Capture console output with ANSI styling preserved.

    Temporarily redirects the current thread's console to a StringIO
    buffer with ``force_terminal=True`` and a valid color system so
    that Rich markup is rendered as ANSI escape codes — even when the
    process's stdout is not a TTY (e.g. ``geode serve`` with DEVNULL).

    Task/thread-safe: operates on the local Console (via the proxy),
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

    Task/thread-safe: operates on the local Console (via the proxy).
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
