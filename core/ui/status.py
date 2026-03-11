"""Claude Code-style status spinner for NLRouter LLM calls.

Shows a braille-dot spinner during API calls, then replaces with a
permanent summary line including action, token counts, cost and elapsed time.

Usage::

    with GeodeStatus("Classifying intent...", model=ANTHROPIC_PRIMARY) as status:
        intent = router.classify(text)
        status.update(f"Tool: {intent.action}")
    # prints: ✓ analyze · Berserk  ↑200 ↓50  $0.004  1.2s
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.llm.client import LLMUsageAccumulator, get_usage_accumulator
from core.ui.console import console


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


class GeodeStatus:
    """Context manager that shows a Rich spinner during LLM calls.

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
        self._status: Any | None = None  # Rich Status object
        self._stopped = False

    def __enter__(self) -> GeodeStatus:
        self._start_time = time.monotonic()
        self._snap_before = _snapshot(get_usage_accumulator())
        self._status = console.status(
            self._format_spinner(self._initial_message),
            spinner="dots",
            spinner_style="cyan",
        )
        self._status.__enter__()
        return self

    def update(self, message: str) -> None:
        """Change the spinner message while running."""
        if self._status is not None and not self._stopped:
            self._status.update(self._format_spinner(message))

    def stop(self, summary: str) -> None:
        """End spinner and print a permanent summary line."""
        if self._stopped:
            return
        self._stopped = True

        # Stop the spinner
        if self._status is not None:
            self._status.__exit__(None, None, None)
            self._status = None

        elapsed = time.monotonic() - self._start_time
        delta = self._get_token_delta()

        parts = [f"  [bold green]✓[/bold green] {summary}"]
        if delta.input_tokens > 0 or delta.output_tokens > 0:
            parts.append(f"[dim]↑{delta.input_tokens} ↓{delta.output_tokens}[/dim]")
        if delta.cost_usd > 0:
            parts.append(f"[dim]${delta.cost_usd:.3f}[/dim]")
        parts.append(f"[dim]{elapsed:.1f}s[/dim]")

        console.print("  ".join(parts))

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if not self._stopped:
            # Auto-stop with a generic summary if stop() was not called explicitly
            elapsed = time.monotonic() - self._start_time
            self._stopped = True
            if self._status is not None:
                self._status.__exit__(None, None, None)
                self._status = None
            delta = self._get_token_delta()
            parts = ["  [bold green]✓[/bold green] done"]
            if delta.input_tokens > 0 or delta.output_tokens > 0:
                parts.append(f"[dim]↑{delta.input_tokens} ↓{delta.output_tokens}[/dim]")
            if delta.cost_usd > 0:
                parts.append(f"[dim]${delta.cost_usd:.3f}[/dim]")
            parts.append(f"[dim]{elapsed:.1f}s[/dim]")
            console.print("  ".join(parts))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_spinner(self, message: str) -> str:
        """Build the spinner line with optional model name."""
        if self._model:
            return f"  {message}  [dim]{self._model}[/dim]"
        return f"  {message}"

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
