"""Module-level concurrency lane for Anthropic PAYG API calls.

The module-level singleton protects standalone and subprocess callers that do
not construct the global :class:`LaneQueue`. Operators can override the default
for their account tier with :data:`ANTHROPIC_API_LANE_MAX_ENV`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from core.orchestration.lane_queue import Lane

log = logging.getLogger(__name__)

__all__ = [
    "ANTHROPIC_API_LANE_MAX_ENV",
    "ANTHROPIC_API_LANE_NAME",
    "ANTHROPIC_API_LANE_TIMEOUT_S",
    "DEFAULT_ANTHROPIC_API_LANE_MAX",
    "acquire_anthropic_api_lane",
    "acquire_anthropic_api_lane_async",
    "get_anthropic_api_lane",
    "reset_anthropic_api_lane_for_tests",
    "resolve_anthropic_api_lane_max",
]


ANTHROPIC_API_LANE_NAME = "anthropic-api"
"""Lane name surfaced in logs + ``LaneQueue.status()`` dashboards."""

ANTHROPIC_API_LANE_MAX_ENV = "GEODE_ANTHROPIC_API_LANE_MAX"
"""Operator override for :data:`DEFAULT_ANTHROPIC_API_LANE_MAX`."""

DEFAULT_ANTHROPIC_API_LANE_MAX = 50
"""Default concurrent Anthropic API calls; configurable for account quotas."""

ANTHROPIC_API_LANE_TIMEOUT_S = 7200.0
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 300s (5min) to
7200s (2h). Same rationale as the sibling lanes."""


_ANTHROPIC_API_LANE: Lane | None = None
_ANTHROPIC_API_LANE_INIT_LOCK = threading.Lock()
"""Protect lazy singleton creation from concurrent first callers."""


def resolve_anthropic_api_lane_max() -> int:
    """Return the effective cap, honouring :data:`ANTHROPIC_API_LANE_MAX_ENV`.

    Falls back to :data:`DEFAULT_ANTHROPIC_API_LANE_MAX` for empty,
    non-integer, or non-positive overrides. The lane should never
    harden into "no slots" mid-run because of a typo.
    """
    raw = os.environ.get(ANTHROPIC_API_LANE_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_ANTHROPIC_API_LANE_MAX
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_ANTHROPIC_API_LANE_MAX
    if parsed <= 0:
        return DEFAULT_ANTHROPIC_API_LANE_MAX
    return parsed


def get_anthropic_api_lane() -> Lane:
    """Return the singleton ``anthropic-api`` lane, lazily initialised."""
    global _ANTHROPIC_API_LANE
    if _ANTHROPIC_API_LANE is None:
        with _ANTHROPIC_API_LANE_INIT_LOCK:
            if _ANTHROPIC_API_LANE is None:
                _ANTHROPIC_API_LANE = Lane(
                    name=ANTHROPIC_API_LANE_NAME,
                    max_concurrent=resolve_anthropic_api_lane_max(),
                    timeout_s=ANTHROPIC_API_LANE_TIMEOUT_S,
                )
    return _ANTHROPIC_API_LANE


@contextmanager
def acquire_anthropic_api_lane(key: str) -> Generator[None, None, None]:
    """Synchronous lane acquisition (test / CLI helper).

    Production callers from the async adapter chain should use
    :func:`acquire_anthropic_api_lane_async` instead — the sync form
    blocks the event loop.
    """
    lane = get_anthropic_api_lane()
    with lane.acquire(key):
        yield


@asynccontextmanager
async def acquire_anthropic_api_lane_async(key: str) -> AsyncGenerator[None, None]:
    """Async lane acquisition for adapter ``acomplete`` call sites.

    ``key`` is surfaced in ``LaneQueue.get_active()`` so operators can
    distinguish concurrent voters / agents inside the lane. Convention:
    ``"<adapter_type>:<model>:<task_id_short>"``.
    """
    lane = get_anthropic_api_lane()
    async with lane.acquire_async(key):
        yield


def reset_anthropic_api_lane_for_tests() -> None:
    """Drop the singleton so the next ``get_anthropic_api_lane`` re-reads
    the env override. Tests that monkeypatch ``os.environ`` must call
    this between subtests; production code never invokes it."""
    global _ANTHROPIC_API_LANE
    with _ANTHROPIC_API_LANE_INIT_LOCK:
        _ANTHROPIC_API_LANE = None
