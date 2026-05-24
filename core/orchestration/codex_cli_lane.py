"""Module-level Lane for ``codex exec`` sub-agent subprocess
serialisation — Codex parity for the Phase 2 + Phase 3 stack.

Built alongside :mod:`core.orchestration.claude_cli_lane` so Codex
spawns share the same shape: a single bucket-wide cap + OAuth-quota
admission control + dashboard mirror in ``build_default_lanes``.

Why a separate lane (not just ``global`` or the Claude lane)
============================================================

Codex CLI's ``codex exec`` reaches the operator's ChatGPT subscription OAuth
bucket (different from Anthropic's). Combining it with the
``claude-cli-subagent`` lane would cap the two providers against a
single semaphore, blocking Codex spawns when Claude is busy and
vice versa — defeating the cross-provider diversity that the seed-
generation judge panel relies on.

The cap matches the Claude side for now
(``DEFAULT_CODEX_CLI_LANE_MAX=2``) because:

1. Codex CLI's per-account burst limiter isn't publicly documented;
   the conservative public-doc-grounded cap leaves headroom for a
   host ``codex`` session.
2. ChatGPT subscription + Codex CLI behaviour under fan-out lacks the
   paperclip-style empirical study Claude has. Until measurements
   land, "small + tunable" beats "high + untested".

Operators tune via :data:`CODEX_CLI_LANE_MAX_ENV` (positive int;
empty / non-int / non-positive falls back to the default).

Module surface mirrors :mod:`claude_cli_lane`
=============================================

* :data:`CODEX_CLI_LANE_NAME` / :data:`CODEX_CLI_LANE_TIMEOUT_S` /
  :data:`DEFAULT_CODEX_CLI_LANE_MAX` / :data:`CODEX_CLI_LANE_MAX_ENV`
  constants — same shape, prefixed for the Codex side.
* :func:`get_codex_cli_lane` — singleton accessor (lazy + thread-safe).
* :func:`acquire_codex_cli_lane` / :func:`acquire_codex_cli_lane_async`
  — sync + async context managers sharing the SAME semaphore.
* :data:`CODEX_CLI_LANE_THROTTLED_MSG` — error message hint when
  Phase 3 admission blocks the acquire; phrased to flow through the
  Phase 4 ``classify_transient`` "quota" branch so the existing
  retry path picks up the block transparently.
"""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from core.orchestration.lane_queue import Lane

__all__ = [
    "CODEX_CLI_LANE_MAX_ENV",
    "CODEX_CLI_LANE_NAME",
    "CODEX_CLI_LANE_THROTTLED_MSG",
    "CODEX_CLI_LANE_TIMEOUT_S",
    "DEFAULT_CODEX_CLI_LANE_MAX",
    "acquire_codex_cli_lane",
    "acquire_codex_cli_lane_async",
    "get_codex_cli_lane",
    "resolve_codex_cli_lane_max",
]


CODEX_CLI_LANE_NAME = "codex-cli-subagent"
"""Lane name surfaced in logs + ``LaneQueue.status()`` dashboards.
Symmetric with ``claude-cli-subagent``."""

CODEX_CLI_LANE_MAX_ENV = "GEODE_CODEX_CLI_LANE_MAX"
"""Operator override for :data:`DEFAULT_CODEX_CLI_LANE_MAX`."""

DEFAULT_CODEX_CLI_LANE_MAX = 2
"""Conservative cap until ChatGPT subscription / Codex CLI burst-limit
behaviour is measured. Same value as the Claude side; the per-
provider knob lets operators tune independently as data accumulates."""

CODEX_CLI_LANE_TIMEOUT_S = 300.0
"""5 minutes — same shape as the Claude lane. A legitimate
``codex exec`` call finishes in seconds; the wait window outlasts a
queued slow call but doesn't bury genuinely-stuck subprocesses."""

CODEX_CLI_LANE_THROTTLED_MSG = (
    "codex-cli-subagent lane blocked — Codex 5-hour OAuth bucket >= "
    "throttle threshold (see GEODE_CODEX_OAUTH_POLL_DISABLED to bypass)."
)
"""Phase 3 throttle surface. The ``5-hour`` substring keeps the Phase
4 classifier on the quota branch (paperclip-derived backoff schedule
applies) without additional wiring."""


_CODEX_CLI_LANE: Lane | None = None
_CODEX_CLI_LANE_INIT_LOCK = threading.Lock()


def resolve_codex_cli_lane_max() -> int:
    """Return the effective cap, honouring :data:`CODEX_CLI_LANE_MAX_ENV`.

    Falls back to :data:`DEFAULT_CODEX_CLI_LANE_MAX` for empty,
    non-integer, or non-positive overrides — same fallback semantics
    as :func:`core.orchestration.claude_cli_lane.resolve_claude_cli_lane_max`
    so a typo never hardens the lane into "no slots".
    """
    raw = os.environ.get(CODEX_CLI_LANE_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_CODEX_CLI_LANE_MAX
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_CODEX_CLI_LANE_MAX
    if parsed <= 0:
        return DEFAULT_CODEX_CLI_LANE_MAX
    return parsed


def get_codex_cli_lane() -> Lane:
    """Return the singleton ``codex-cli-subagent`` lane, lazily initialised.

    Thread-safe via double-checked locking. Exposed for tests +
    operators that want to inspect ``lane.stats`` / ``lane.get_active()``.
    """
    global _CODEX_CLI_LANE
    if _CODEX_CLI_LANE is None:
        with _CODEX_CLI_LANE_INIT_LOCK:
            if _CODEX_CLI_LANE is None:  # re-check inside lock
                _CODEX_CLI_LANE = Lane(
                    name=CODEX_CLI_LANE_NAME,
                    max_concurrent=resolve_codex_cli_lane_max(),
                    timeout_s=CODEX_CLI_LANE_TIMEOUT_S,
                )
    return _CODEX_CLI_LANE


@contextmanager
def acquire_codex_cli_lane(key: str) -> Iterator[None]:
    """Block until a ``codex exec`` slot is free, then yield.

    Phase 3 — before reserving a slot, consults
    :func:`core.llm.codex_oauth_usage.should_block_codex_lane_acquisition`.
    When the Codex 5-hour OAuth bucket has crossed the threshold the
    acquire raises :class:`TimeoutError` with a ``5-hour limit
    reached``-shaped message so Phase 4's classifier routes to the
    quota backoff schedule.
    """
    from core.llm.codex_oauth_usage import should_block_codex_lane_acquisition

    if should_block_codex_lane_acquisition():
        raise TimeoutError(CODEX_CLI_LANE_THROTTLED_MSG)
    lane = get_codex_cli_lane()
    with lane.acquire(key):
        yield


@asynccontextmanager
async def acquire_codex_cli_lane_async(key: str) -> AsyncIterator[None]:
    """Async sibling for inspect_ai's ``CodexCliAPI.generate``.

    Shares the SAME underlying semaphore as
    :func:`acquire_codex_cli_lane`. Blocking acquire runs in a worker
    thread; the OAuth-quota probe (currently a no-op placeholder
    pending endpoint verification) is also off-loaded via
    ``asyncio.to_thread`` so the event loop is not pinned.
    """
    import asyncio

    from core.llm.codex_oauth_usage import should_block_codex_lane_acquisition

    if await asyncio.to_thread(should_block_codex_lane_acquisition):
        raise TimeoutError(CODEX_CLI_LANE_THROTTLED_MSG)
    lane = get_codex_cli_lane()
    async with lane.acquire_async(key):
        yield


def _reset_codex_cli_lane_for_tests() -> None:
    """Drop the singleton so tests can flip env knobs + re-resolve."""
    global _CODEX_CLI_LANE
    with _CODEX_CLI_LANE_INIT_LOCK:
        _CODEX_CLI_LANE = None
