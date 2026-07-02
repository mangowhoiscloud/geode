"""Claude Code-style status spinner for AgenticLoop LLM calls.

Shows a rose-crystal (GEODE signature) spinner with a rotating activity word
and live elapsed timer during API calls, then replaces it with a permanent
summary line including action, token counts, cost and elapsed time.

Usage::

    with GeodeStatus("Classifying intent...", model=ANTHROPIC_PRIMARY) as status:
        intent = router.classify(text)
        status.update(f"Tool: {intent.action}")
    # prints: ✓ summarize · repo  ↑200 ↓50  $0.004  1.2s
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from core.llm.router import LLMUsageAccumulator, get_usage_accumulator
from core.ui import spinner_glyph
from core.ui.console import console

# Generic messages that hand the spinner line over to a whimsical gerund \u2014
# ONE word per spinner lifetime, seeded by its start time (Claude Code parity).
# The crystal glyph + activity words live in core.ui.spinner_glyph \u2014 one source.
_GENERIC = {"", "processing...", "thinking...", "working..."}


class TextSpinner:
    """Non-invasive rose-crystal status spinner. No raw mode, no cursor hiding.

    Renders a Claude Code-style live status line: an animated GEODE crystal, a
    per-turn activity word (or the caller's message), and a live elapsed timer,
    rewritten in place with a carriage return + line clear. The output target is
    resolved at write-time so it follows ``redirect_console()`` (IPC streaming).
    """

    def __init__(self, message: str, *, model: str = "", quiet: bool = False) -> None:
        self._message = message
        self._model = model
        self._rotate = message.strip().lower() in _GENERIC
        self._running = False
        self._thread: threading.Thread | None = None
        self._quiet = quiet  # suppress output (sub-agent, headless)
        self._start = 0.0

    @staticmethod
    def _out() -> Any:
        """Resolve the output target — follows console redirect if active."""
        target = console.file
        if target is not None and target is not sys.__stdout__:
            return target
        return sys.stdout

    def start(self) -> None:
        if self._quiet:
            return
        # IPC mode: thin CLI has its own ToolCallTracker.
        # Serve-side spinner would send raw ANSI over IPC → cursor race.
        from core.ui.agentic_ui import _ipc_writer_local

        if getattr(_ipc_writer_local, "writer", None) is not None:
            return
        self._running = True
        self._start = time.monotonic()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        """Update the spinner message while running."""
        self._message = message
        self._rotate = message.strip().lower() in _GENERIC

    def _animate(self) -> None:
        word_of_turn = spinner_glyph.gerund(self._start)  # stable for this spinner's lifetime
        while self._running:
            el = time.monotonic() - self._start
            word = f"{word_of_turn}…" if self._rotate else self._message
            body = spinner_glyph.shimmer(f"{spinner_glyph.GLYPH} {word}", el)
            meta = spinner_glyph.elapsed(el)
            meta += f" · {self._model}" if self._model else ""
            out = self._out()
            out.write(f"\r\x1b[2K  {body} {spinner_glyph.DIM}({meta}){spinner_glyph.RST}")
            out.flush()
            time.sleep(0.05)

    def stop(self, final_message: str = "") -> None:
        self._running = False
        if self._quiet:
            return
        if self._thread:
            self._thread.join(timeout=0.2)
        out = self._out()
        out.write("\r\x1b[2K")
        if final_message:
            out.write(f"  {final_message}\n")
        out.flush()


@dataclass(frozen=True)
class _UsageSnapshot:
    """Immutable snapshot of accumulator totals at a point in time."""

    input_tokens: int
    output_tokens: int
    cost_usd: float


def _snapshot(acc: LLMUsageAccumulator) -> _UsageSnapshot:
    return _UsageSnapshot(
        input_tokens=acc.total_input_tokens,
        output_tokens=acc.total_output_tokens,
        cost_usd=acc.total_cost_usd,
    )


def _fmt(n: int) -> str:
    """Format token count: 1200 → 1.2k."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


class GeodeStatus:
    """Context manager that shows a TextSpinner during LLM calls.

    On ``__enter__``, captures a token-usage snapshot and starts the spinner.
    ``update(msg)`` changes the spinner text mid-flight.
    ``stop(summary)`` (or ``__exit__``) ends the spinner and prints a
    permanent summary line with token delta and elapsed time.
    """

    def __init__(self, message: str = "Processing...", *, model: str = "") -> None:
        self._initial_message = message
        self._model = model
        self._start_time: float = 0.0
        self._snap_before: _UsageSnapshot | None = None
        self._spinner: TextSpinner | None = None
        self._stopped = False

    def __enter__(self) -> GeodeStatus:
        self._start_time = time.monotonic()
        self._snap_before = _snapshot(get_usage_accumulator())
        self._spinner = TextSpinner(self._initial_message, model=self._model)
        self._spinner.start()
        return self

    def update(self, message: str) -> None:
        """Change the spinner message while running."""
        if self._spinner is not None and not self._stopped:
            self._spinner.update(message)

    def stop(self, summary: str) -> None:
        """End spinner and print a permanent summary line."""
        if self._stopped:
            return
        self._stopped = True

        # Stop the spinner
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None

        elapsed = time.monotonic() - self._start_time
        delta = self._get_token_delta()

        parts = [f"  [bold green]✓[/bold green] {summary}"]
        if delta.input_tokens > 0 or delta.output_tokens > 0:
            parts.append(f"[dim]↓{_fmt(delta.input_tokens)} ↑{_fmt(delta.output_tokens)}[/dim]")
        if delta.cost_usd > 0:
            parts.append(f"[dim]${delta.cost_usd:.4f}[/dim]")
        parts.append(f"[dim]{elapsed:.1f}s[/dim]")

        console.print(" · ".join(parts))

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if not self._stopped:
            # Auto-stop with a generic summary if stop() was not called explicitly
            elapsed = time.monotonic() - self._start_time
            self._stopped = True
            if self._spinner is not None:
                self._spinner.stop()
                self._spinner = None
            delta = self._get_token_delta()
            parts = ["  [bold green]✓[/bold green] done"]
            if delta.input_tokens > 0 or delta.output_tokens > 0:
                parts.append(f"[dim]↓{_fmt(delta.input_tokens)} ↑{_fmt(delta.output_tokens)}[/dim]")
            if delta.cost_usd > 0:
                parts.append(f"[dim]${delta.cost_usd:.4f}[/dim]")
            parts.append(f"[dim]{elapsed:.1f}s[/dim]")
            console.print(" · ".join(parts))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token_delta(self) -> _UsageSnapshot:
        """Compute the token/cost delta since ``__enter__``."""
        if self._snap_before is None:
            return _UsageSnapshot(0, 0, 0.0)
        after = _snapshot(get_usage_accumulator())
        return _UsageSnapshot(
            input_tokens=after.input_tokens - self._snap_before.input_tokens,
            output_tokens=after.output_tokens - self._snap_before.output_tokens,
            cost_usd=after.cost_usd - self._snap_before.cost_usd,
        )
