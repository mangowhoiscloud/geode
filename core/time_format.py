"""Human-readable duration formatting — one home for two scattered idioms.

Four sites carried two near-identical formatters (PR-DEDUP-2):

- ``format_age`` — relative age (``"5m ago"`` / ``"2h ago"`` / ``"2d ago"``),
  was ``_format_age`` in ``core/memory/context.py`` + ``project_journal.py``.
- ``format_elapsed`` — short ``"Ns"`` / ``"Nm Ns"`` duration, was ``_fmt_elapsed``
  in ``core/ui/event_renderer.py`` + ``_format_seconds`` in ``agentic_ui/_state.py``.

Pure stdlib leaf so any layer (memory, ui) can import it without a cycle.
"""

from __future__ import annotations


def format_age(seconds: float) -> str:
    """Format elapsed seconds as a relative age (``"now"`` under one minute).

    Negative inputs (clock skew / future timestamps) collapse to ``"now"``.
    """
    if seconds < 60:
        return "now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    return f"{int(days)}d ago"


def format_elapsed(seconds: float) -> str:
    """Format a duration as ``"Ns"`` (under a minute) or ``"Nm Ns"``."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    return f"{m}m {sec}s"
