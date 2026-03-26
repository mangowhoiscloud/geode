"""Claude Code-style status spinner for AgenticLoop LLM calls.

Shows a braille-dot spinner during API calls, then replaces with a
permanent summary line including action, token counts, cost and elapsed time.

Usage::

    with GeodeStatus("Classifying intent...", model=ANTHROPIC_PRIMARY) as status:
        intent = router.classify(text)
        status.update(f"Tool: {intent.action}")
    # prints: ✓ analyze · Berserk  ↑200 ↓50  $0.004  1.2s
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

from core.cli.ui.console import console
from core.llm.router import LLMUsageAccumulator, get_usage_accumulator


class TextSpinner:
    """Non-invasive text spinner. No raw mode, no cursor hiding."""

    FRAMES = [
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

    def __init__(self, message: str, *, quiet: bool = False) -> None:
        self._message = message
        self._running = False
        self._thread: threading.Thread | None = None
        self._quiet = quiet  # suppress output (sub-agent, headless)

    def start(self) -> None:
        if self._quiet:
            return
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        """Update the spinner message while running."""
        self._message = message

    def _animate(self) -> None:
        idx = 0
        while self._running:
            frame = self.FRAMES[idx % len(self.FRAMES)]
            sys.stdout.write(f"\r\x1b[2K  {frame} {self._message}")
            sys.stdout.flush()
            time.sleep(0.08)
            idx += 1

    def stop(self, final_message: str = "") -> None:
        self._running = False
        if self._quiet:
            return
        if self._thread:
            self._thread.join(timeout=0.2)
        sys.stdout.write("\r\x1b[2K")
        if final_message:
            sys.stdout.write(f"  {final_message}\n")
        sys.stdout.flush()


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
        self._spinner = TextSpinner(self._format_spinner(self._initial_message))
        self._spinner.start()
        return self

    def update(self, message: str) -> None:
        """Change the spinner message while running."""
        if self._spinner is not None and not self._stopped:
            self._spinner.update(self._format_spinner(message))

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

    def _format_spinner(self, message: str) -> str:
        """Build the spinner text with optional model name."""
        parts = [f"✢ {message}"]
        if self._model:
            parts.append(self._model)
        return " · ".join(parts)

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
