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

import sys
import threading
import time

# Braille spinner frames (same as TextSpinner)
_FRAMES = [
    "\u280b",
    "\u2819",
    "\u2839",
    "\u2838",
    "\u283c",
    "\u2834",
    "\u2826",
    "\u2827",
    "\u2807",
    "\u280f",
]


class ToolCallTracker:
    """Renders tool call lines with spinners, updating in-place on completion."""

    def __init__(self) -> None:
        self._tools: list[dict[str, str | bool | float]] = []
        self._lock = threading.Lock()
        self._spinner_thread: threading.Thread | None = None
        self._running = False
        self._line_count = 0  # how many lines we've printed

    def on_tool_start(self, event: dict[str, object]) -> None:
        """Handle a tool_start event from serve."""
        with self._lock:
            # Clear completed entries from previous batch to prevent
            # stale lines re-rendering (e.g. sequential sequentialthinking calls)
            if not self._running and self._tools and all(t["done"] for t in self._tools):
                self._tools.clear()
                self._line_count = 0
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
            if self._line_count > 0:
                out = sys.stdout
                for _ in range(self._line_count):
                    out.write("\033[A\033[2K")
                out.write("\r")
                out.flush()
            self._line_count = 0

    def _animate(self) -> None:
        while self._running:
            with self._lock:
                self._redraw()
            time.sleep(0.08)

    def _redraw(self) -> None:
        """Clear all tool lines and reprint them (ANSI cursor-up)."""
        out = sys.stdout
        # Move cursor up to overwrite previous render
        if self._line_count > 0:
            out.write(f"\033[{self._line_count}A")

        frame = _FRAMES[int(time.monotonic() * 12) % len(_FRAMES)]
        lines: list[str] = []
        for t in self._tools:
            name = t["name"]
            if t["done"]:
                dur = f" ({float(t['duration']):.1f}s)"
                if t["error"]:
                    lines.append(f"\033[2K  \033[31m\u2717 {name}\033[0m — {t['error']}{dur}")
                else:
                    summary = t["summary"]
                    lines.append(f"\033[2K  \033[32m\u2713 {name}\033[0m → {summary}{dur}")
            else:
                args = str(t["args"]).replace("\n", " ")
                if len(args) > 60:
                    args = args[:57] + "..."
                lines.append(f"\033[2K  \033[35m\u25b8 {name}\033[0m({args}) {frame}")

        output = "\n".join(lines)
        if lines:
            output += "\n"
        out.write(output)
        out.flush()
        self._line_count = len(lines)
