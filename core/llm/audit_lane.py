"""Module-level Lane for autoresearch audit subprocess serialization.

OL-AUDIT-BURST-FIX (2026-05-22) FIX-3.

Why a module-level Lane (not the global LaneQueue container)
============================================================

The autoresearch audit (`core/self_improving/train.py::_run_autoresearch_subprocess`)
is sometimes invoked from contexts where the global ``LaneQueue``
singleton (built in ``core/wiring/container.py::build_lane_queue``)
does NOT exist:

* standalone CLI: ``uv run python -m core.self_improving.train`` outside the
  daemon — container isn't wired.
* test harness: pytest doesn't build the container by default.

A module-level Lane works in both contexts and stays cheap (just a
``threading.Semaphore`` + dict of active holders) per
:class:`core.orchestration.lane_queue.Lane`.

Why ``max_concurrent=1``
========================

Two stacked rationales:

1. **Inter-process serialisation**: when a daemon-driven cron audit
   collides with a manual ``geode audit`` (operator-initiated), both
   would otherwise spawn ``inspect eval`` simultaneously. Even after
   FIX-1/2 caps inspect_ai's *per-process* burst to 1, two processes
   running together = 2 inflight = potential 2x of Max OAuth's soft
   limit on the host. Lane=1 keeps the host emitting at most one
   audit's worth of API requests at a time.
2. **Self-conflict with host Claude Code session**: the operator's
   active Claude Code session (this conversation, REPL session, etc.)
   shares the same Max OAuth token via the system keychain. Anthropic
   rate-limits per-account-bucket, not per-process. By serialising the
   audit's own subprocess, we leave headroom for whatever the operator
   is actively doing in their host session.

Multi-account future
====================

When operator provisions a dedicated Anthropic account for audit
(future AccountPool work), the audit subprocess routes through that
account's API key — completely separate rate bucket from the host
session. At that point ``max_concurrent`` can be raised (controlled by
account-tier metadata) and this module's Lane becomes a hint rather
than a hard bottleneck. The Lane shape is preserved; only its capacity
moves.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from core.orchestration.lane_queue import Lane

log = logging.getLogger(__name__)

__all__ = [
    "AUDIT_LANE_MAX_CONCURRENT_ENV",
    "AUDIT_LANE_NAME",
    "AUDIT_LANE_TIMEOUT_S",
    "acquire_audit_lane",
    "get_audit_lane",
    "resolve_audit_max_concurrent",
]


AUDIT_LANE_NAME = "autoresearch-audit"
"""Lane name surfaced in logs + LaneQueue stats."""

AUDIT_LANE_TIMEOUT_S = 900.0
"""15 minutes — a legitimate audit (with FIX-1/2's serialised inspect_ai)
takes ~5-10 min on Max OAuth. The lane should wait long enough for one
to finish before timing out the queued caller, but not so long that a
truly-stuck audit hides the problem from operators."""


AUDIT_LANE_MAX_CONCURRENT_ENV = "GEODE_AUDIT_MAX_CONCURRENT"
"""Operator knob for the audit lane capacity (PR-ASYNC-FIRST, 2026-06-03).

Default (unset) → ``1`` (subscription-safe serialisation: the host Claude Code
session shares the Anthropic OAuth rate bucket, so two concurrent audits on the
OAuth lane self-conflict — the ``max_concurrent=1`` rationale this module was
built around). When the audit roles route through a SEPARATE rate bucket — PAYG
``api_key`` for both the opus-4-8 auditor/judge and the gpt-5.5 target, i.e.
``[self_improving_loop] openai_source = "api_key"`` — the bucket-contention reason
is gone, so the async-first campaign harness sets this knob to fan audits out
concurrently. This is exactly the "Multi-account future ... ``max_concurrent`` can
be raised ... the Lane becomes a hint" path the module docstring anticipates.

Value semantics: a positive int sets the capacity; ``0`` → effectively unbounded
(``no CAP``, operator's standing PAYG directive). Read once at lazy lane init, so
set it in the process environment before the first audit."""

_UNBOUNDED_AUDIT_CONCURRENCY = 100_000
"""Semaphore size standing in for "unbounded" — far above any realistic audit
fan-out, so the lane never blocks while staying a real (resettable) Semaphore."""

_AUDIT_LANE: Lane | None = None
_AUDIT_LANE_INIT_LOCK = threading.Lock()
"""Codex MCP catch (PR-OL-AUDIT-BURST-FIX fix-up): double-checked
locking around lazy init. Two concurrent first-callers could both
observe ``_AUDIT_LANE is None`` and create distinct ``Lane``
instances — defeating the very serialisation this module exists for."""


def resolve_audit_max_concurrent() -> int:
    """Resolve the audit lane capacity from :data:`AUDIT_LANE_MAX_CONCURRENT_ENV`.

    Defaults to ``1`` (subscription-safe). A non-numeric or negative value falls
    back to ``1`` with a warning rather than crashing the audit (graceful boundary
    — the env is operator-supplied). ``0`` maps to the unbounded sentinel.
    """
    raw = os.environ.get(AUDIT_LANE_MAX_CONCURRENT_ENV, "").strip()
    if not raw:
        return 1
    try:
        value = int(raw)
    except ValueError:
        log.warning(
            "%s=%r is not an integer; falling back to max_concurrent=1",
            AUDIT_LANE_MAX_CONCURRENT_ENV,
            raw,
        )
        return 1
    if value < 0:
        log.warning(
            "%s=%d is negative; falling back to max_concurrent=1",
            AUDIT_LANE_MAX_CONCURRENT_ENV,
            value,
        )
        return 1
    return _UNBOUNDED_AUDIT_CONCURRENCY if value == 0 else value


def get_audit_lane() -> Lane:
    """Return the singleton audit lane, lazily initialised.

    Capacity comes from :func:`resolve_audit_max_concurrent` (default 1). Thread-safe
    via double-checked locking (see :data:`_AUDIT_LANE_INIT_LOCK`). Exposed for tests
    that need to inspect ``lane.stats`` or ``lane.get_active()`` after a series of
    acquires.
    """
    global _AUDIT_LANE
    if _AUDIT_LANE is None:
        with _AUDIT_LANE_INIT_LOCK:
            if _AUDIT_LANE is None:  # re-check inside lock
                _AUDIT_LANE = Lane(
                    name=AUDIT_LANE_NAME,
                    max_concurrent=resolve_audit_max_concurrent(),
                    timeout_s=AUDIT_LANE_TIMEOUT_S,
                )
    return _AUDIT_LANE


@contextmanager
def acquire_audit_lane(key: str) -> Iterator[None]:
    """Block until the audit lane slot is free, then yield.

    Use as a context manager around ``subprocess.run`` for the
    audit subprocess::

        with acquire_audit_lane(key=session_id):
            proc = subprocess.run(argv, ...)

    Raises :class:`TimeoutError` (from underlying ``Lane.acquire``)
    when the slot doesn't free within :data:`AUDIT_LANE_TIMEOUT_S`.
    Caller's choice whether to surface as RuntimeError or retry.
    """
    lane = get_audit_lane()
    with lane.acquire(key):
        yield
