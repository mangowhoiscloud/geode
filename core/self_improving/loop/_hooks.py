"""Self-improving-loop hook bridge — emit MUTATION_*/BASELINE_PROMOTED events.

PR-MUTATION-EMIT-WIRE (2026-05-27) — PR-HOOKEVENT-RESERVE (2026-05-26)
reserved the five mutator lifecycle event names in
``core.hooks.system.HookEvent`` but left the emit sites un-wired
("writers will emit these once the SoT-revert paths land in
``core/self_improving/train.py:2407-2455`` + ``runner.py:1882-1888``"). This
module is the writer-side wiring: the runner + train.py promote/revert
paths call :func:`_fire_hook` with the payload schema documented on
the enum.

Mirrors the ``core.llm.router._hooks`` pattern — a module-level
``_hooks_ctx`` slot, a ``set_self_improving_loop_hooks`` setter
invoked from ``core.wiring.bootstrap`` after ``HookSystem`` is built,
and a ``_fire_hook`` helper that no-ops gracefully when the setter
hasn't fired yet (the lazy-wire path keeps unit tests + cold-start
imports independent of the runtime container).
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.dispatch import fire_hook
from core.hooks.system import HookEvent

log = logging.getLogger(__name__)

_hooks_ctx: Any = None  # HookSystem | None — set via set_self_improving_loop_hooks()


def set_self_improving_loop_hooks(hooks: Any) -> None:
    """Wire HookSystem into the self-improving-loop emit sites.

    Called from ``core.wiring.bootstrap`` after the ``HookSystem``
    singleton is constructed. Until this is called, every
    :func:`_fire_hook` call is a silent no-op (matches the
    ``core.llm.router._hooks`` lazy-wire contract).
    """
    global _hooks_ctx
    _hooks_ctx = hooks


def clear_self_improving_loop_hooks(expected: Any) -> bool:
    """Clear the binding only when it still points at ``expected``."""
    global _hooks_ctx
    if _hooks_ctx is not expected:
        return False
    _hooks_ctx = None
    return True


def _fire_hook(event: HookEvent, data: dict[str, Any]) -> None:
    """Fire a mutation lifecycle event when the HookSystem is wired.

    No-op when the setter hasn't been called (cold-start imports,
    isolated unit tests). Failure to fire is non-blocking — the
    mutator's SoT writes are the correctness boundary, observability
    is best-effort.

    PR-HOOK-TAXONOMY D4 removed the sibling ``_fire_hook_with_result``:
    its only caller was the ``PROGRAM_MD_UNREADABLE`` override contract,
    which never had a registered handler anywhere — a structurally dead
    feedback path. The runner now fires this plain notify and fails loud.
    """
    fire_hook(_hooks_ctx, event, data)
