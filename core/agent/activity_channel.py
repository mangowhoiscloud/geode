"""Child->parent live-activity side-channel for the fleet view (Stage 1.5).

Design SOT: ``docs/plans/2026-07-03-fleet-view.md``.

Sub-agents run as ``python -m core.agent.worker`` subprocesses with the child
:class:`~core.agent.loop.AgenticLoop` in ``quiet=True`` mode, so the child emits
no per-tool IPC back to the parent's renderer — the parent learns a task's state
only from the single final ``WorkerResult`` line at exit. Stage 1 left
``FleetAgent.current_activity`` as ``""`` for exactly this reason.

Stage 1.5 closes the gap with a **process-local activity sink**. The worker
subprocess installs a sink (:func:`set_activity_sink`) that serialises a
``{"type":"activity", ...}`` JSON line to its own stdout *before* the final
result line. The child's :class:`ToolExecutor` calls :func:`emit_tool_activity`
at the single per-tool dispatch boundary; when a sink is installed the current
tool name + best-effort cumulative token count are forwarded to it.

Fail-safe by construction:

- The sink is a plain module global, **only ever set inside the worker
  subprocess** (:mod:`core.agent.worker`). The parent process and every test
  never call :func:`set_activity_sink`, so :func:`emit_tool_activity` is a
  cheap no-op everywhere except a worker that opted in via
  ``WorkerRequest.emit_activity``.
- No sink installed → no emission → ``current_activity`` stays ``""`` (the
  Stage 1 honest default). Nothing is faked.
- Token count is read from the process token tracker (fresh per subprocess, so
  its cumulative total *is* this task's total). Subscription / CLI-routed calls
  expose no usage, so the count is honestly ``0`` for those — never fabricated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

# ``(tool_name, cumulative_tokens) -> None``. Installed only by the worker
# subprocess; ``None`` everywhere else (parent process, tests) → no-op emit.
ActivitySink = Callable[[str, int], None]

_activity_sink: ActivitySink | None = None


def set_activity_sink(sink: ActivitySink) -> None:
    """Install the process-local activity sink (worker subprocess only)."""
    global _activity_sink
    _activity_sink = sink


def clear_activity_sink() -> None:
    """Remove the installed sink (test hygiene; the worker process just exits)."""
    global _activity_sink
    _activity_sink = None


def get_activity_sink() -> ActivitySink | None:
    """Return the installed sink, or ``None`` when the feature is inactive."""
    return _activity_sink


def emit_tool_activity(tool: str) -> None:
    """Forward the child's *current* tool + cumulative tokens to the sink.

    A cheap no-op unless a sink was installed (i.e. unless this is a worker
    subprocess that opted in via ``WorkerRequest.emit_activity``). The token
    count is best-effort: read from the process token tracker, which is fresh
    per worker subprocess so its cumulative total is this task's total, and is
    ``0`` for subscription / CLI-routed calls that expose no usage.
    """
    sink = _activity_sink
    if sink is None:
        return
    tokens = 0
    try:
        from core.llm.token_tracker import get_tracker

        snap = get_tracker().snapshot()
        tokens = int(snap.total_input_tokens) + int(snap.total_output_tokens)
    except Exception:
        # Best-effort — a missing/unbound tracker must never break tool dispatch.
        tokens = 0
    try:
        sink(tool, tokens)
    except Exception:
        # A misbehaving sink (e.g. a broken stdout pipe) must never propagate
        # into the child's tool-execution path.
        log.debug("activity sink raised for tool=%s", tool, exc_info=True)
