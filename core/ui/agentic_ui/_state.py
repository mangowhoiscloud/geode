"""Session-level timing state and pipeline IP context.

Module-level thread-local globals live here and are re-exported from the
package ``__init__.py``:

- ``_ipc_writer_local`` — thread-local IPC writer for structured tool events.
- ``_pipeline_ip_local`` — thread-local pipeline IP name for forward-compatible
  event tagging.
- ``_meter_local`` — thread-local ``SessionMeter`` instance per session.

The package-level ``_turn_snapshot`` global lives in ``__init__.py`` so that
test patches like ``mod._turn_snapshot = None`` flow through; ``summary.py``
reads/writes it through the package namespace.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Thread-local IPC writer for structured tool events.
# When set (by CLIPoller._run_prompt_streaming), OperationLogger sends
# tool_start/tool_end events instead of console.print — enabling the
# thin client to render per-tool spinners with in-place ✓ updates.
_ipc_writer_local = threading.local()

# Thread-local pipeline IP name for forward-compatible event tagging.
# Set by _run_analysis() before pipeline execution; read by emit_pipeline_*
# functions to tag events with the originating IP (for future parallel UI).
_pipeline_ip_local = threading.local()


def set_pipeline_ip(ip_name: str) -> None:
    """Set the current pipeline's IP name (thread-safe)."""
    _pipeline_ip_local.ip_name = ip_name


def _get_pipeline_ip() -> str:
    """Get the current pipeline's IP name."""
    return getattr(_pipeline_ip_local, "ip_name", "")


# ───────────────────────────────────────────────────────────────────────────
# SessionMeter — session-level timing for status line
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class SessionMeter:
    """Tracks session-level and per-turn timing for status line display."""

    start_time: float = field(default_factory=time.monotonic)
    model: str = ""
    _turn_start: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._turn_start = self.start_time

    def mark_turn_start(self) -> None:
        """Reset the per-turn timer (call before each agentic.run())."""
        self._turn_start = time.monotonic()

    # -- Session-level (cumulative) ----------------------------------------

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def elapsed_display(self) -> str:
        return self._format_seconds(self.elapsed_s)

    # -- Turn-level (per-turn delta) ---------------------------------------

    @property
    def turn_elapsed_s(self) -> float:
        return time.monotonic() - self._turn_start

    @property
    def turn_elapsed_display(self) -> str:
        return self._format_seconds(self.turn_elapsed_s)

    # -- Helpers -----------------------------------------------------------

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s"


_meter_local = threading.local()


def init_session_meter(model: str = "") -> SessionMeter:
    """Initialize the session meter for the current thread.

    Thread-safe: each IPC handler thread (and the main thread) gets its
    own ``SessionMeter`` instance via ``threading.local``, preventing
    cross-session contamination of model names, elapsed times, and
    token counters.
    """
    if not model:
        from core.config import ANTHROPIC_PRIMARY

        model = ANTHROPIC_PRIMARY
    meter = SessionMeter(model=model)
    _meter_local.meter = meter
    return meter


def update_session_model(model: str) -> None:
    """Update the current thread's session meter model after /model switch."""
    meter = getattr(_meter_local, "meter", None)
    if meter is not None:
        meter.model = model


def get_session_meter() -> SessionMeter | None:
    """Return the current thread's session meter (None if not initialized)."""
    return getattr(_meter_local, "meter", None)
