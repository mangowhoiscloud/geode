"""Module-level Lane for Anthropic API call concurrency (oauth + payg).

PR-OAUTH-API-LANES (2026-05-26) — covers ``anthropic-oauth`` (Claude Max
OAuth subscription) and ``anthropic-payg`` (Anthropic API key). Both
billing paths share the same per-account rate-limit bucket on
Anthropic's server side, so a single shared lane prevents a burst of
concurrent ``messages.create`` calls from racing the per-account
floor.

Distinct from ``claude_cli_lane`` because:

- ``claude-cli`` lane gates **subprocess fork** (`claude --print` cold-
  start cost, sandbox isolation, host-session OAuth keychain sharing).
- ``anthropic_api_lane`` gates **direct API call** (no subprocess, just
  ``anthropic.AsyncClient.messages.create``); the burst pattern + 429
  surface differ.

Why ``max_concurrent=4``
========================

Mid-range default selected from three reference points:

1. **Anthropic API documented tier 1** allows ~50 RPM = ~0.83 RPS. A
   single match's voter latency is ~70s (per smoke-24 evidence) →
   throughput-limit is roughly 1 inflight at a time before the bucket
   starts gating. 4 leaves headroom for cluster-level concurrency
   without crossing the 50 RPM ceiling on the typical seed-gen Loop
   (59 matches × 1 anthropic voter = 59 RPM if fully parallel, well
   under 50 RPM when amortised across the ~5-min wallclock).
2. **claude_cli_lane=2** + ``audit_lane=1`` already consume 3 slots
   of the per-account budget when active; the API lane sits on top,
   so 4 keeps total per-account inflight ≤ 7 (still under the soft
   throttle threshold per [[project_lanequeue_handoff_2026_05_22]]).
3. **PR-RANKER-PARALLEL** (the immediate consumer) needs the lane to
   smooth a 59-match burst, not to add ceiling — 4 is enough for
   60% wallclock reduction without 429 spikes (vs unbounded → ~30%
   chance of 429 per smoke run pre-PR).

Operator override via :data:`ANTHROPIC_API_LANE_MAX_ENV` for tiers
with higher RPM (custom enterprise quotas) or lower (degraded shared
account).

Why module-level (not LaneQueue-registered)
===========================================

Same rationale as ``audit_lane`` + ``claude_cli_lane``: contexts where
the global ``LaneQueue`` singleton is not built (standalone CLI,
pytest harness, autoresearch subprocess) still need the gate. A
module-level singleton works in both contexts and stays cheap.
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
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 4 to 8.

Anthropic tier 1 documents 50 RPM aggregate per account. Voter calls
land in 60-70s wallclock each → steady-state ~0.86 inflight per cap
slot, so cap 8 = ~7 RPM steady state, well under the 50 RPM
ceiling. The ranker.py panel uses claude-cli (subprocess, gated by
``claude_cli_lane``) for the anthropic voter, NOT direct API, so the
8-slot cap here exists to cover hybrid panels and the autoresearch
mutator's direct API path; it is the natural pair to
``claude_cli_lane`` raised to 4 in the same PR.

Operator override via :data:`ANTHROPIC_API_LANE_MAX_ENV` for
enterprise tiers with higher per-account RPM budgets."""

ANTHROPIC_API_LANE_TIMEOUT_S = 7200.0
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 300s (5min) to
7200s (2h). Same rationale as the sibling lanes."""


_ANTHROPIC_API_LANE: Lane | None = None
_ANTHROPIC_API_LANE_INIT_LOCK = threading.Lock()
"""Double-checked locking around lazy init (mirrors ``audit_lane``
+ ``claude_cli_lane`` pattern). Two concurrent first-callers could
otherwise observe ``_ANTHROPIC_API_LANE is None`` and construct
distinct ``Lane`` instances, defeating the per-account cap."""


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
