"""Module-level Lane for OpenAI API call concurrency (codex-oauth + payg).

PR-OAUTH-API-LANES (2026-05-26) — covers ``openai-codex`` (ChatGPT
subscription via Codex Responses API) and ``openai-payg`` (OpenAI
API key). Both share the same per-account rate-limit bucket on
OpenAI's server side; a single shared lane prevents a burst of
concurrent ``responses.create`` calls from racing the per-account
floor.

Distinct from ``codex_cli_lane`` because:

- ``codex-cli`` lane gates **subprocess fork** (codex-cli binary
  cold-start, sandbox isolation, ``~/.codex/auth.json`` shared file
  handle).
- ``openai_api_lane`` gates **direct API call** (no subprocess, just
  ``openai.AsyncOpenAI.responses.create``); 429 surface differs.

Why ``max_concurrent=4``
========================

Mid-range default selected from three reference points:

1. **OpenAI Codex Responses API**: ChatGPT subscription bucket
   is documented to support ~500 RPM aggregate across all models
   (per the public Codex CLI roll-out post-2025-Q4). gpt-5.x voter
   calls average ~10s wallclock; 4 inflight × 10s = 0.4s/call
   serialised throughput ≈ 150 RPM — well under 500.
2. **codex_cli_lane=2** + ``audit_lane=1`` consume 3 slots of the
   per-account budget when CLI flows are also active; the API lane
   sits on top, so 4 keeps total per-account inflight ≤ 7.
3. **PR-RANKER-PARALLEL** (the immediate consumer): for the typical
   2-codex + 1-claude-cli voter panel, 4 codex slots = 2 matches'
   worth of concurrent codex voters — paired with claude_cli_lane=2
   the two match-side bottlenecks balance.

Operator override via :data:`OPENAI_API_LANE_MAX_ENV` for tiers with
higher quotas.

Why module-level (not LaneQueue-registered)
===========================================

Same rationale as the other module-level lanes: contexts where the
global LaneQueue singleton is not built (standalone CLI, pytest,
autoresearch subprocess) still need the gate.
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

DEFAULT_OPENAI_API_LANE_MAX = 4
"""Default concurrent OpenAI API calls (codex-oauth + payg pooled).

See module docstring for the three-point rationale (OpenAI Codex
Responses API 500 RPM bucket, codex_cli_lane co-existence,
PR-RANKER-PARALLEL match-burst headroom)."""

OPENAI_API_LANE_TIMEOUT_S = 300.0
"""5 minutes — same rationale as the Anthropic API lane."""


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
