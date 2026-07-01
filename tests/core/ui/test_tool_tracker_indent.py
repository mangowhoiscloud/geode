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

import io
import sys

from core.ui.tool_tracker import ToolCallTracker


def _tool(name: str, *, done: bool = True) -> dict[str, str | bool | float]:
    return {
        "name": name,
        "args": "",
        "done": done,
        "error": "",
        "summary": "ok",
        "start_time": 0.0,
        "duration": 0.1,
    }


def test_rendered_tool_lines_are_carriage_return_prefixed() -> None:
    tracker = ToolCallTracker()
    tracker._tools = [
        _tool("memory_search"),
        _tool("glob_files", done=False),
        {**_tool("grep_files"), "error": "failed"},
    ]

    lines = tracker._render_tool_lines("⠋")

    assert len(lines) == 3
    for line in lines:
        assert line.startswith("\r\033[2K"), f"line not column-0-safe: {line!r}"


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


def test_large_tool_batches_collapse_to_bounded_view() -> None:
    tracker = ToolCallTracker()
    tracker._tools = [_tool(f"tool_{i}") for i in range(10)]

    lines = tracker._render_tool_lines("⠋")

    assert len(lines) == 8
    assert "tool_0" in lines[0]
    assert "tool_1" in lines[1]
    assert "tool_2" in lines[2]
    assert "+3 tool calls collapsed" in lines[3]
    assert "tool_6" in lines[4]
    assert "tool_9" in lines[-1]
    assert all(line.startswith("\r\033[2K") for line in lines)


def test_redraw_clears_previous_taller_frame(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    tracker = ToolCallTracker()
    tracker._tty = True
    tracker._line_count = 8
    tracker._visual_row_count = 8
    tracker._tools = [_tool("memory_search"), _tool("glob_files")]

    tracker._redraw()

    out = buf.getvalue()
    assert out.startswith("\033[8A")
    assert out.count("\r\033[2K\n") >= 6


def test_redraw_overclears_when_terminal_width_shrinks(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(
        "core.ui.tool_tracker.shutil.get_terminal_size",
        lambda fallback=(80, 24): __import__("os").terminal_size((20, 24)),
    )
    tracker = ToolCallTracker()
    tracker._tty = True
    tracker._line_count = 1
    tracker._visual_row_count = 1
    tracker._rendered_lines = ["\r\033[2K  ✓ very_long_tool_name_that_wrapped_at_narrow_width"]
    tracker._tools = [_tool("ok")]

    tracker._redraw()

    out = buf.getvalue()
    assert out.startswith("\033[3A")
