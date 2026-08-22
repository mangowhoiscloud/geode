"""Module-level concurrency lane shared by OpenAI PAYG and Codex OAuth.

The singleton protects standalone and subprocess callers that do not construct
the global :class:`LaneQueue`. Operators can override the default with
:data:`OPENAI_API_LANE_MAX_ENV`.
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
    "DEFAULT_OPENAI_API_LANE_MAX",
    "OPENAI_API_LANE_MAX_ENV",
    "OPENAI_API_LANE_NAME",
    "OPENAI_API_LANE_TIMEOUT_S",
    "acquire_openai_api_lane",
    "acquire_openai_api_lane_async",
    "get_openai_api_lane",
    "reset_openai_api_lane_for_tests",
    "resolve_openai_api_lane_max",
]


OPENAI_API_LANE_NAME = "openai-api"
"""Lane name surfaced in logs + ``LaneQueue.status()`` dashboards."""

OPENAI_API_LANE_MAX_ENV = "GEODE_OPENAI_API_LANE_MAX"
"""Operator override for :data:`DEFAULT_OPENAI_API_LANE_MAX`."""

DEFAULT_OPENAI_API_LANE_MAX = 6
"""Default concurrent OpenAI calls; configurable for account quotas."""

OPENAI_API_LANE_TIMEOUT_S = 7200.0
"""Two-hour ceiling for queued long-running evaluation calls."""


_OPENAI_API_LANE: Lane | None = None
_OPENAI_API_LANE_INIT_LOCK = threading.Lock()


def resolve_openai_api_lane_max() -> int:
    """Return the effective cap, honouring :data:`OPENAI_API_LANE_MAX_ENV`.

    Falls back to :data:`DEFAULT_OPENAI_API_LANE_MAX` for empty,
    non-integer, or non-positive overrides.
    """
    raw = os.environ.get(OPENAI_API_LANE_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_OPENAI_API_LANE_MAX
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_OPENAI_API_LANE_MAX
    if parsed <= 0:
        return DEFAULT_OPENAI_API_LANE_MAX
    return parsed


def get_openai_api_lane() -> Lane:
    """Return the singleton ``openai-api`` lane, lazily initialised."""
    global _OPENAI_API_LANE
    if _OPENAI_API_LANE is None:
        with _OPENAI_API_LANE_INIT_LOCK:
            if _OPENAI_API_LANE is None:
                _OPENAI_API_LANE = Lane(
                    name=OPENAI_API_LANE_NAME,
                    max_concurrent=resolve_openai_api_lane_max(),
                    timeout_s=OPENAI_API_LANE_TIMEOUT_S,
                )
    return _OPENAI_API_LANE


@contextmanager
def acquire_openai_api_lane(key: str) -> Generator[None, None, None]:
    """Synchronous lane acquisition (test / CLI helper)."""
    lane = get_openai_api_lane()
    with lane.acquire(key):
        yield


@asynccontextmanager
async def acquire_openai_api_lane_async(key: str) -> AsyncGenerator[None, None]:
    """Async lane acquisition for adapter ``acomplete`` call sites."""
    lane = get_openai_api_lane()
    async with lane.acquire_async(key):
        yield


def reset_openai_api_lane_for_tests() -> None:
    """Drop the singleton so the next ``get_openai_api_lane`` re-reads
    the env override."""
    global _OPENAI_API_LANE
    with _OPENAI_API_LANE_INIT_LOCK:
        _OPENAI_API_LANE = None
