"""Session-level timing state and pipeline subject context.

Module-level context-local globals live here and are re-exported from the
package ``__init__.py``:

- ``_ipc_writer_local`` — task/thread-local IPC writer for structured tool events.
- ``_pipeline_subject_local`` — task/thread-local pipeline subject for event tagging.
- ``_meter_local`` — task/thread-local ``SessionMeter`` instance per session.

The package-level ``_turn_snapshot`` global lives in ``__init__.py`` so that
test patches like ``mod._turn_snapshot = None`` flow through; ``summary.py``
reads/writes it through the package namespace.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.time_format import format_elapsed
from core.ui.context_local import ContextLocal

# Task/thread-local IPC writer for structured tool events.
# When set (by CLIPoller._run_prompt_streaming), OperationLogger sends
# tool_start/tool_end events instead of console.print — enabling the
# thin client to render per-tool spinners with in-place ✓ updates.
_ipc_writer_local = ContextLocal("geode_ipc_writer_local")

# Task/thread-local pipeline subject for structured event tagging.
_pipeline_subject_local = ContextLocal("geode_pipeline_subject_local")


def set_pipeline_subject(subject_id: str) -> None:
    """Set the current pipeline subject."""
    _pipeline_subject_local.subject_id = subject_id


def _get_pipeline_subject() -> str:
    """Get the current pipeline subject."""
    return getattr(_pipeline_subject_local, "subject_id", "")


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
        return format_elapsed(self.elapsed_s)

    # -- Turn-level (per-turn delta) ---------------------------------------

    @property
    def turn_elapsed_s(self) -> float:
        return time.monotonic() - self._turn_start

    @property
    def turn_elapsed_display(self) -> str:
        return format_elapsed(self.turn_elapsed_s)


_meter_local = ContextLocal("geode_session_meter_local")


def init_session_meter(model: str = "") -> SessionMeter:
    """Initialize the session meter for the current thread.

    Thread-safe: each IPC handler thread (and the main thread) gets its
    own ``SessionMeter`` instance via ``threading.local``, preventing
    cross-session contamination of model names, elapsed times, and
    token counters.

    v0.83.0 — when ``model`` is omitted, fall back to the live
    ``settings.model`` (which `_apply_model` mutates on `/model`
    switches) instead of the hard-coded ``ANTHROPIC_PRIMARY``. The old
    shape always defaulted to anthropic, so callers like ``poller.py``
    that did ``init_session_meter()`` left the per-turn footer
    hard-stuck on ``claude-opus-4-7`` even after the user switched to
    ``gpt-5.5``. Pairs with v0.82.0 which fixed the *actual* call
    routing — this fixes the *displayed* model so the footer matches.
    """
    if not model:
        from core.config import ANTHROPIC_PRIMARY, settings

        model = settings.model or ANTHROPIC_PRIMARY
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
