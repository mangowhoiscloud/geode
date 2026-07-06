"""Tool call tracker — per-tool spinner with in-place ✓ updates.

Renders parallel tool calls with individual spinner animations.
When a tool completes, its line is updated in-place using ANSI
cursor movement (cursor-up + clear-line + rewrite).

Usage (by thin client IPC handler)::

    tracker = ToolCallTracker()
    tracker.on_tool_start({"name": "web_search", "args_preview": "query=..."})
    # spinner runs automatically
    tracker.on_tool_end({"name": "web_search", "summary": "5 results"})
    # line updated to ✓
    tracker.stop()
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
import time
import unicodedata

from core.ui import spinner_glyph

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _truncate_display(text: str, max_width: int) -> str:
    """Truncate text by display width, accounting for CJK wide characters."""
    width = 0
    for i, ch in enumerate(text):
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + w > max_width - 3:  # room for "..."
            return text[:i] + "..."
        width += w
    return text


_MAX_VISIBLE_TOOL_LINES = 8
_VISIBLE_TOOL_HEAD = 3
_VISIBLE_TOOL_TAIL = 4


class ToolCallTracker:
    """Renders tool call lines with spinners, updating in-place on completion.

    Output is suppressed when stdout is not a TTY (e.g., pytest, CI, pipes).
    """

    def __init__(self, *, live_updates: bool = True) -> None:
        self._tools: list[dict[str, str | bool | float]] = []
        self._lock = threading.Lock()
        self._spinner_thread: threading.Thread | None = None
        self._running = False
        self._line_count = 0  # how many lines we've printed
        self._visual_row_count = 0
        self._rendered_lines: list[str] = []
        self._tty = sys.stdout.isatty() and live_updates

    def on_tool_start(self, event: dict[str, object]) -> None:
        """Handle a tool_start event from serve."""
        with self._lock:
            # Clear completed entries from previous batch to prevent
            # stale lines re-rendering (e.g. sequential sequentialthinking calls)
            if not self._running and self._tools and all(t["done"] for t in self._tools):
                self._tools.clear()
                self._line_count = 0
                self._visual_row_count = 0
                self._rendered_lines = []
            self._tools.append(
                {
                    "name": str(event.get("name", "?")),
                    "args": str(event.get("args_preview", "")),
                    "done": False,
                    "error": "",
                    "summary": "",
                    "start_time": time.monotonic(),
                    "duration": 0.0,
                }
            )
            self._redraw()
        if not self._running:
            self._running = True
            self._spinner_thread = threading.Thread(target=self._animate, daemon=True)
            self._spinner_thread.start()

    def on_tool_end(self, event: dict[str, object]) -> None:
        """Handle a tool_end event from serve."""
        name = str(event.get("name", ""))
        all_done = False
        with self._lock:
            for t in self._tools:
                if t["name"] == name and not t["done"]:
                    t["done"] = True
                    t["summary"] = str(event.get("summary", "ok"))
                    t["error"] = str(event.get("error", ""))
                    # Prefer server-measured duration (excludes IPC latency)
                    server_dur = event.get("duration_s")
                    if server_dur is not None and float(str(server_dur)) > 0:
                        t["duration"] = float(str(server_dur))
                    else:
                        t["duration"] = time.monotonic() - float(t["start_time"])
                    break
            all_done = all(t["done"] for t in self._tools)
            if all_done:
                self._running = False
            self._redraw()

        # Join spinner thread outside lock to prevent stale frame after final redraw
        if all_done and self._spinner_thread:
            self._spinner_thread.join(timeout=0.5)
            with self._lock:
                self._redraw()  # final clean redraw without spinner

    def stop(self) -> None:
        """Stop the spinner and do a final redraw."""
        self._running = False
        if self._spinner_thread:
            self._spinner_thread.join(timeout=0.3)
        with self._lock:
            self._redraw()

    def suspend(self) -> None:
        """Stop animation and erase rendered lines. Resets cursor position.

        Tools remain tracked. When ``on_tool_end`` is called later,
        the completion line prints at the current cursor position
        (no cursor-up) to avoid overwriting interleaved output.

        Idempotent: second call is a no-op.
        """
        self._running = False
        if self._spinner_thread:
            self._spinner_thread.join(timeout=0.3)
            self._spinner_thread = None
        with self._lock:
            if self._visual_row_count > 0 and self._tty:
                out = sys.stdout
                for _ in range(self._visual_row_count):
                    out.write("\033[A\033[2K")
                out.write("\r")
                out.flush()
            self._line_count = 0
            self._visual_row_count = 0
            self._rendered_lines = []

    def _animate(self) -> None:
        while self._running:
            with self._lock:
                self._redraw()
            time.sleep(0.08)

    def _redraw(self) -> None:
        """Clear all tool lines and reprint them (ANSI cursor-up).

        Internal state (_line_count) is always updated so tests can verify
        tracker behaviour.  ANSI stdout writes are suppressed in non-TTY.
        """
        lines = self._render_tool_lines(time.monotonic())

        previous_lines = list(self._rendered_lines)
        width = self._terminal_width()
        previous_rows = max(
            self._visual_row_count,
            self._visual_rows(previous_lines, width),
        )
        current_rows = self._visual_rows(lines, width)
        self._line_count = len(lines)
        self._visual_row_count = current_rows
        self._rendered_lines = list(lines)

        # Only write ANSI output to real terminals
        if not self._tty:
            return
        out = sys.stdout
        if previous_rows > 0:
            out.write(f"\033[{previous_rows}A")

        output = "\n".join(lines)
        if lines:
            output += "\n"
        out.write(output)

        # If this redraw rendered fewer rows than the previous frame
        # (for example after a large batch collapses), wipe the stale tail.
        for _ in range(max(0, previous_rows - current_rows)):
            out.write("\r\033[2K\n")

        out.flush()

    def _render_tool_lines(self, now: float) -> list[str]:
        """Return the bounded terminal rows for the currently tracked tools."""
        lines = [self._render_tool_line(t, now) for t in self._tools]
        if len(lines) <= _MAX_VISIBLE_TOOL_LINES:
            return lines

        omitted = len(lines) - _VISIBLE_TOOL_HEAD - _VISIBLE_TOOL_TAIL
        if omitted <= 0:
            return lines

        return [
            *lines[:_VISIBLE_TOOL_HEAD],
            f"\r\033[2K  \033[2m… +{omitted} tool calls collapsed\033[0m",
            *lines[-_VISIBLE_TOOL_TAIL:],
        ]

    def _render_tool_line(self, tool: dict[str, str | bool | float], now: float) -> str:
        """Render one tool call row. Every row starts from column 0.

        A running row carries the signature shimmer (``core.ui.spinner_glyph``,
        the single spinner source) over ``◆ name``; completed rows keep static ✓/✗.
        """
        name = tool["name"]
        if tool["done"]:
            dur = f" ({float(tool['duration']):.1f}s)"
            if tool["error"]:
                err = _truncate_display(str(tool["error"]), 60)
                return f"\r\033[2K  \033[31m\u2717 {name}\033[0m — {err}{dur}"
            summary = _truncate_display(str(tool["summary"]), 60)
            return f"\r\033[2K  \033[32m\u2713 {name}\033[0m → {summary}{dur}"

        args = str(tool["args"]).replace("\n", " ")
        args = _truncate_display(args, 50)
        body = spinner_glyph.shimmer(f"{spinner_glyph.GLYPH} {name}", now)
        return f"\r\033[2K  {body}\033[2m({args})\033[0m"

    def _terminal_width(self) -> int:
        return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)

    def _visual_rows(self, lines: list[str], width: int | None = None) -> int:
        width = width or self._terminal_width()
        rows = 0
        for line in lines:
            plain = _ANSI_ESCAPE.sub("", line).lstrip("\r").rstrip("\n")
            display_width = sum(
                2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in plain
            )
            rows += max(1, (display_width + width - 1) // width)
        return rows
