"""Terminal utilities — extracted from cli/__init__.py for SRP.

Functions for terminal state management: restore cooked mode, suppress warnings,
drain leftover stdin bytes, SIGINT handling.
"""

from __future__ import annotations

import sys
from typing import Any

import core.ui.console as _console

restore_terminal = _console.restore_terminal


def make_sigint_handler() -> Any:
    """Create a SIGINT handler that restores terminal before raising."""

    def _sigint_handler(signum: int, frame: Any) -> None:
        restore_terminal()
        raise KeyboardInterrupt

    return _sigint_handler


def drain_stdin() -> None:
    """Drain leftover bytes from stdin after a paste.

    When bracketed paste is unavailable, pasted newlines trigger Enter
    and only the first line is submitted. The remaining text stays in
    stdin and gets auto-submitted on the next prompt() call.
    This drains any such leftover to prevent double-submit.
    """
    import select

    if not sys.stdin.isatty():
        return
    try:
        import os as _os

        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0.0)[0]:
            _os.read(fd, 4096)
    except (ValueError, OSError):
        pass
