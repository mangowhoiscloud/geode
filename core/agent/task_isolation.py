"""Per-task isolated working directory ContextVar.

Set by the sub-agent worker at startup so the claude-cli adapter can
spawn the ``claude`` subprocess with a per-task cwd. claude-cli's
session cache (``~/.claude/projects/<cwd-hash>/sessions/``) is keyed
on cwd; by giving each ``task_id`` its own directory the cache pools
are non-overlapping, eliminating cross-sub-agent leak via cwd-cache
auto-pickup. Within-task session persistence still works because
turn N+1 of the same ``task_id`` sees the same cwd, so the
``--resume <id>`` from PR-V finds the session turn N saved.

PR-RESUME-NO-PERSIST-FIX (2026-05-25) — replaces the blunt
``--no-session-persistence`` flag from PR-PERMS-FLAG-FIX B. That
flag disabled ALL persistence, which broke PR-V's intra-task
``--resume`` path because turn N had no saved session for turn N+1
to resume from. The smoke 10 generator gen-gen1-000 and evolver
evolve-gen1-001 both failed with ``No conversation found with
session ID <uuid>`` because of that conflict.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

__all__ = ["get_task_isolated_cwd", "set_task_isolated_cwd"]

# Default ``None`` — when no sub-agent worker context is set (direct
# adapter calls from inspect_ai audit lane, one-shot diagnostic
# scripts, etc.), the adapter inherits the caller's cwd just as it
# did pre-PR-RESUME-NO-PERSIST-FIX.
_task_isolated_cwd: ContextVar[str | None] = ContextVar("geode_task_isolated_cwd", default=None)


def set_task_isolated_cwd(cwd: str | Path | None) -> None:
    """Bind a per-task working directory for the current execution
    context.

    The sub-agent worker calls this at startup with
    ``<run_dir>/sub_agents/<task_id>/cwd/``. The directory must
    already exist on disk — this function does NOT create it (the
    worker mkdirs before binding so the read-write parity check is
    explicit at the call site).

    Passing ``None`` clears the binding (used by test teardown).
    """
    _task_isolated_cwd.set(str(cwd) if cwd is not None else None)


def get_task_isolated_cwd() -> str | None:
    """Return the per-task isolated cwd, or ``None`` if not bound.

    The claude-cli adapter reads this and forwards to
    ``asyncio.create_subprocess_exec(..., cwd=<value>)``. When ``None``,
    the subprocess inherits the caller's cwd — same behavior as
    pre-PR-RESUME-NO-PERSIST-FIX direct-call paths.
    """
    return _task_isolated_cwd.get()
