"""Serve renders command output with ANSI styles; the thin CLI relays it."""

from __future__ import annotations

import io

import pytest
from core.cli import _write_daemon_output

STYLED = "\x1b[1mGEODE System Status\x1b[0m\n"


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    ("stream", "expected"),
    [(_Terminal(), STYLED), (io.StringIO(), "GEODE System Status\n")],
)
def test_styles_reach_a_terminal_and_a_pipe_gets_plain_text(
    monkeypatch: pytest.MonkeyPatch, stream: io.StringIO, expected: str
) -> None:
    monkeypatch.setattr("sys.stdout", stream)
    _write_daemon_output(STYLED)
    assert stream.getvalue() == expected
