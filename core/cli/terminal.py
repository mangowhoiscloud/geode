"""Terminal utilities — extracted from cli/__init__.py for SRP.

Functions for terminal state management: restore cooked mode, suppress warnings,
drain leftover stdin bytes, SIGINT handling.
"""

from __future__ import annotations

import logging
import sys
import termios
from typing import Any

log = logging.getLogger(__name__)


def restore_terminal() -> None:
    """Restore terminal to sane cooked mode.

    Rich Status/Live can leave the terminal in raw mode (echo off, no
    line-editing) if interrupted or if an exception escapes their context
    manager.  This ensures the terminal is usable before reading input.
    """
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        # Ensure ECHO and ICANON (cooked mode) are enabled
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (ValueError, OSError, termios.error):
        # Non-TTY or stdin not available — nothing to restore
        pass


def make_sigint_handler() -> Any:
    """Create a SIGINT handler that restores terminal before raising."""

    def _sigint_handler(signum: int, frame: Any) -> None:
        restore_terminal()
        raise KeyboardInterrupt

    return _sigint_handler


def suppress_noisy_warnings() -> None:
    """Suppress known noisy warnings from dependencies."""
    import warnings

    # Pydantic V1 deprecation from langchain_core on Python 3.14+
    warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
    # LangGraph msgpack deserialization warning (warnings.warn path)
    warnings.filterwarnings("ignore", message="Deserializing unregistered type")

    # LangGraph checkpoint deserialization also logs via logging.warning —
    # suppress those at the logging level.
    for noisy_logger in (
        "langgraph.checkpoint.serde.jsonplus",
        "langgraph.checkpoint.serde.base",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.ERROR)


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
