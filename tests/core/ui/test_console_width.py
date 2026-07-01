from __future__ import annotations

import io
import os
import sys

from core.ui.console import (
    make_session_console,
    refresh_console_width,
    reset_thread_console,
    set_thread_console,
)


class _TtyStdout(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_refresh_console_width_updates_active_tty_console(monkeypatch) -> None:
    console = make_session_console(io.StringIO(), force_terminal=True, width=80)
    set_thread_console(console)
    monkeypatch.setattr(sys, "stdout", _TtyStdout())
    monkeypatch.setattr(
        "core.ui.console.shutil.get_terminal_size",
        lambda: os.terminal_size((100, 24)),
    )
    try:
        refresh_console_width()
        assert console._width == 100
    finally:
        reset_thread_console()


def test_refresh_console_width_preserves_non_tty_capture(monkeypatch) -> None:
    console = make_session_console(io.StringIO(), force_terminal=False, width=80)
    set_thread_console(console)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    try:
        refresh_console_width()
        assert console._width == 80
    finally:
        reset_thread_console()
