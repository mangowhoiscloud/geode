"""``run_dir`` — single SoT for the "active per-cycle output directory"
the seed-generation / petri-audit orchestrators run inside.

Pre-PR-Q every observability writer (RunTranscript / SessionTranscript /
WorkerResult / IsolatedRunner stderr) had its own hardcoded global
``~/.geode/<bucket>/`` destination. One seed-generation cycle's artifacts
landed across 5 prefixes with 3 different identifiers (run_id /
task-id / session-hash) — joining a cycle's data required 5 greps and
manual identifier reconciliation (see GAP audit in the PR-Q body).

This module exposes ONE ContextVar so every writer asks the same
question — "is there an active run_dir for this thread?" — and routes
its output inside it when set. When the var is empty the writer falls
back to its legacy global path so callers outside the seed-generation
orchestrator (gateway, REPL, ad-hoc CLI, tests) are unaffected.

Cross-process propagation (parent → worker subprocess) is handled by
:data:`RUN_DIR_ENV`: the orchestrator's ContextVar value is forwarded
via the worker's environment, and the worker's :func:`main` re-binds it
on entry so writers inside the child process see the same active dir.

Resolver:

* :func:`get_active_run_dir` — current binding, or ``None``.
* :func:`resolve_sub_agent_path` — ``<run_dir>/sub_agents/<task_id>/<filename>``
  when active, else ``None``. Most writers use this.
* :func:`run_dir_scope` — context manager that sets + restores the
  binding (orchestrator entry).
* :data:`RUN_DIR_ENV` — env var name (``GEODE_RUN_DIR``) used to bridge
  the binding across the parent → child subprocess boundary.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = [
    "RUN_DIR_ENV",
    "get_active_run_dir",
    "resolve_sub_agent_path",
    "run_dir_scope",
    "set_active_run_dir",
]


RUN_DIR_ENV = "GEODE_RUN_DIR"
"""Env var name used to cross the parent → worker subprocess boundary.

The parent's :class:`IsolatedRunner._aexecute_subprocess` reads the
active ContextVar binding and forwards it via this env var; the worker's
:func:`core.agent.worker.main` re-binds the ContextVar from this env
on entry so writers inside the child see the same run_dir."""


_active_run_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "geode_active_run_dir", default=None
)


def set_active_run_dir(run_dir: Path | str | None) -> contextvars.Token[Path | None]:
    """Bind ``run_dir`` as the active per-cycle output directory for
    the current ContextVar scope. Returns the reset token so callers
    can restore the prior binding (mirrors
    :func:`set_current_run_transcript` shape).
    """
    resolved: Path | None = Path(run_dir) if run_dir else None
    return _active_run_dir.set(resolved)


def get_active_run_dir() -> Path | None:
    """Return the active run directory, or ``None`` when no orchestrator
    has bound one. Writers use this to decide whether to redirect their
    output into the per-cycle directory vs the legacy global pool."""
    return _active_run_dir.get()


@contextmanager
def run_dir_scope(run_dir: Path | str) -> Iterator[Path]:
    """Context manager that binds ``run_dir`` for the duration of the
    ``with`` block and restores the prior binding on exit (even if an
    exception propagates). The orchestrator opens this scope right
    before delegating work so every writer downstream sees the binding.
    """
    resolved = Path(run_dir)
    resolved.mkdir(parents=True, exist_ok=True)
    token = set_active_run_dir(resolved)
    try:
        yield resolved
    finally:
        _active_run_dir.reset(token)


def resolve_sub_agent_path(task_id: str, filename: str) -> Path | None:
    """Compute the canonical per-sub-agent output path
    ``<active_run_dir>/sub_agents/<task_id>/<filename>``.

    Returns ``None`` when no run_dir is bound — caller falls back to
    its legacy ``~/.geode/<bucket>/`` global. ``parent.mkdir`` is
    side-effected here so writers don't each duplicate that boilerplate.

    Examples (each writer's call site):

    * WorkerResult backup:        ``resolve_sub_agent_path(task_id, "result.json")``
    * IsolatedRunner stderr dump: ``resolve_sub_agent_path(session_id, "stderr.log")``
    * Per-sub-agent dialogue:     ``resolve_sub_agent_path(session_id, "dialogue.jsonl")``
    """
    run_dir = get_active_run_dir()
    if run_dir is None:
        return None
    sub_agent_dir = run_dir / "sub_agents" / task_id
    sub_agent_dir.mkdir(parents=True, exist_ok=True)
    return sub_agent_dir / filename
