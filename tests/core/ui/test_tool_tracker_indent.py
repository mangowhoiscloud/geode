"""Guard: tool-tracker lines paint from column 0 (v0.99.177).

``_redraw`` moves the cursor UP with ``\\033[{n}A`` (preserves column) and
clears each line with ``\\033[2K`` (does not move the cursor). Without a
leading ``\\r`` the ``  ✓ name`` text printed at whatever column a prior
writer (activity spinner, thinking region, interleaved stream) left the
cursor at — producing ragged indentation (operator-reported, 2026-06-11:
some tool lines indented ~16 cols, others 2). Every rendered line must
start with ``\\r``.
"""

from __future__ import annotations

import inspect
import io
import sys

from core.ui.tool_tracker import ToolCallTracker


def test_redraw_lines_are_carriage_return_prefixed() -> None:
    src = inspect.getsource(ToolCallTracker._redraw)
    appends = [ln for ln in src.splitlines() if "lines.append" in ln]
    assert len(appends) == 3, f"expected 3 line builders, found {len(appends)}"
    for ln in appends:
        assert r'"\r\033[2K' in ln, f"line not column-0-safe: {ln.strip()}"


def test_redraw_output_resets_column_per_line(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    tracker = ToolCallTracker()
    tracker._tty = True  # force ANSI path (StringIO has no isatty)
    tracker._tools = [
        {
            "name": "memory_search",
            "args": "",
            "done": True,
            "error": "",
            "summary": "ok",
            "start_time": 0.0,
            "duration": 0.1,
        },
        {
            "name": "glob_files",
            "args": "",
            "done": True,
            "error": "",
            "summary": "ok",
            "start_time": 0.0,
            "duration": 0.0,
        },
    ]
    tracker._redraw()
    out = buf.getvalue()
    # both tool lines must carry the CR-prefixed clear sequence
    assert out.count("\r\033[2K") == 2
    # and no tool line content appears without a preceding CR
    assert "  \033[32m✓ memory_search" in out
    assert "  \033[32m✓ glob_files" in out
