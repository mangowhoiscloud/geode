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

Why ``max_concurrent=10`` (PR-LANE-CAP-CONSERVATIVE, v0.99.75)
=============================================================

Lowered from 50 (PR-LANE-CAP-50, v0.99.74) to **10** alongside the
same-PR claude-cli lane drop. Local-RSS reasoning is identical to
``claude_cli_lane.py``: a ranker burst at cap 50 panel-fires ~150
voter tasks (50 × 3) and the host froze.

Codex API calls are *not* subprocess-based — they fire from the
parent Python process via ``openai.AsyncOpenAI.responses.create``,
so the per-task cost is ~31 MB (measured on the freeze host, codex
subprocess RSS — the API path stays in-process Python and is even
cheaper). The cap-10 ceiling is **paired with** the new
claude_cli_lane cap of 5: for the 1-claude + 2-codex panel,
``ranker_max_inflight=5`` saturates 5 claude slots and 10 codex
slots simultaneously without bursting.

**Upstream RPM headroom retained**: ChatGPT subscription bucket
documents ~500 RPM aggregate; cap 10 with ~10s voter wallclock =
~60 RPM — still 8× below the ceiling, so this is *not* a quota
governor any more, just a panel-balance one.

Operator override via :data:`OPENAI_API_LANE_MAX_ENV`. Operators
with bigger boxes raising ``claude_cli_lane`` should raise this
in proportion (2× the new claude cap is the panel rule).

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

DEFAULT_OPENAI_API_LANE_MAX = 10
"""PR-LANE-CAP-CONSERVATIVE (v0.99.75, 2026-05-27) — lowered from 50.

Paired with ``claude_cli_lane=5`` for the standard 1-claude + 2-codex
voter panel: ``ranker_max_inflight=5`` × 2 codex voters = 10 in-flight
codex calls, exactly saturating this cap. The 50→10 drop is a sibling
correction of the same-day claude-cli cap drop (see
``claude_cli_lane.py`` for the freeze incident that motivated the
sprint).

Throughput-wise this still leaves ~440 RPM of the documented 500 RPM
ChatGPT subscription headroom unused — the binding constraint is
panel balance, not OpenAI quota.

Operator override via :data:`OPENAI_API_LANE_MAX_ENV`. Rule of thumb:
keep this at ``2 × claude_cli_lane`` for cross-provider panels;
operators running codex-only panels (no claude voter) can raise
freely up to the 500 RPM tier ceiling."""

OPENAI_API_LANE_TIMEOUT_S = 7200.0
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 300s (5min) to
7200s (2h). Same rationale as ``claude_cli_lane`` — the parallel
ranker burst can push the last-queued voter well past 5min even
under the new 16-cap if a single 429 cascades. 2h matches the
ranker phase's hard time budget; a genuinely-stuck call still
surfaces at the 2h boundary."""


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
