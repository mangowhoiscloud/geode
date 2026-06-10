"""Module-level Lane for ``claude --print`` sub-agent subprocess
serialisation.

PR-LQ-Phase2 (2026-05-22) — second leg of the LaneQueue 5-phase plan
([[project_lanequeue_handoff_2026_05_22]]).

Why a separate lane (not just ``global``)
=========================================

Both the self-improving-loop mutator runner
(:func:`core.self_improving.loop.mutate.cli_subprocess.invoke_claude_cli`) and
the Petri inspect_ai bridge
(:class:`plugins.petri_audit.claude_cli_provider.ClaudeCliAPI`) spawn
``claude --print`` subprocesses for their inference path. Those
subprocesses go out through the host's Claude Code OAuth bucket — the
SAME bucket the operator's interactive Claude Code session is using
right now. Anthropic rate-limits per-account-bucket, not per-process,
and the public surface confirms a burst limiter at **3-4 concurrent
in-flight** before 429s (anthropics/claude-code#53922; paperclip
empirical findings — see [[project_lanequeue_handoff_2026_05_22]]).

The ``global`` lane (max=8) is too permissive for this path: 8
concurrent ``claude --print`` spawns saturate the OAuth bucket and
collide with the operator's host session. Conversely the ``global``
lane is too restrictive for non-Claude-CLI traffic (API-billed
Anthropic / OpenAI completions). The two flows need separate caps,
which is why this lane sits alongside ``global`` rather than under it.

Why ``max_concurrent=3`` (PR-LANE-CAP-TIGHTER, v0.99.76, 2026-05-27)
====================================================================

v0.99.75 dropped this from 50 to 5 after the freeze, but cap 5 still
required ~3 GB of free host RAM per burst (5 × ~487 MB per match).
The operator's M3 16 GB host typically has **150-750 MB unused** at
steady state (with normal desktop apps + Claude Code + Slack /
Chrome / Notion running), so cap 5 still demands an explicit
cleanup pass before each smoke — which defeats the "safe default"
goal. Cap 3 brings the burst to ~1.5 GB and survives without the
cleanup ritual.

**Measured local cost** (M3 16 GB, 2026-05-27):

* `claude --print` subprocess RSS: ~425 MB per voter (Node V8 + bundled
  deps; fresh process each spawn — see
  `paperclip/packages/adapter-utils/src/server-utils.ts:1943` for the
  canonical `child_process.spawn` pattern this lane shadow-fires).
* Cap 3 burst: 3 matches × ~487 MB ≈ **1.5 GB peak anonymous RSS**.
  Fits in the operator's typical "no-cleanup" headroom + compressor
  give-back.

**Trade-off**: Ranker phase wall-clock grows from ~1 min (cap 50)
to ~20-40 min for a 50-match Loop 1. Acceptable for nightly /
autonomous smokes; operators with larger boxes (32 GB+) or who
*have* done a heavy-app cleanup should override via
:data:`CLAUDE_CLI_LANE_MAX_ENV` (e.g. ``=6`` for 32 GB, ``=20+``
for 64 GB Mac Studio).

**Upstream rate-limit headroom**: At cap 3 the steady-state
throughput against Anthropic's 5h pool sits orders of magnitude
below the documented per-account ceiling, so neither floor (RPM nor
token pool) is the binding constraint — the local RSS one is.

Why module-level (not LaneQueue-registered)
===========================================

Same rationale as
:mod:`core.orchestration.audit_lane`:

* The self-improving-loop mutator runs from contexts where the global
  ``LaneQueue`` singleton (built in
  ``core/wiring/container.py::build_default_lanes``) may not exist
  (standalone ``python -m`` invocations, pytest fixtures that skip
  the container).
* The inspect_ai bridge is loaded as a Petri plugin and instantiates
  its ``ModelAPI`` subclass through inspect_ai's router, well outside
  the path that constructs the container.

A module-level :class:`~core.orchestration.lane_queue.Lane` works in
all three contexts (daemon, CLI, plugin-mounted inspect_ai) without
plumbing a queue reference through the call chain.

The lane name (:data:`CLAUDE_CLI_LANE_NAME`) is also registered on the
default :class:`~core.orchestration.lane_queue.LaneQueue` (see
``core.wiring.container.build_default_lanes``) so dashboards / status
endpoints surface it alongside ``gateway`` / ``global`` /
``seed-generation``. The two registrations stay in lockstep via the
constants defined in this module.

Future Phase 3+ integration
===========================

Phase 3 (paperclip P1 port) will surface OAuth-usage telemetry via
``core/llm/oauth_usage.py`` (planned). The lane's
:meth:`~core.orchestration.lane_queue.Lane.acquire` call site is the
natural integration point: poll utilisation immediately before
``_raw_acquire``, and back off when ``five_hour.utilization >= 0.8``.
That work is scoped to Phase 3 and explicitly out of this PR.
"""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from core.orchestration.lane_queue import Lane

__all__ = [
    "CLAUDE_CLI_LANE_MAX_ENV",
    "CLAUDE_CLI_LANE_NAME",
    "CLAUDE_CLI_LANE_TIMEOUT_S",
    "DEFAULT_CLAUDE_CLI_LANE_MAX",
    "acquire_claude_cli_lane",
    "acquire_claude_cli_lane_async",
    "get_claude_cli_lane",
    "resolve_claude_cli_lane_max",
]


CLAUDE_CLI_LANE_NAME = "claude-cli-subagent"
"""Lane name surfaced in logs + ``LaneQueue.status()`` dashboards."""

CLAUDE_CLI_LANE_MAX_ENV = "GEODE_CLAUDE_CLI_LANE_MAX"
"""Operator override for :data:`DEFAULT_CLAUDE_CLI_LANE_MAX`.

Set to a positive integer to raise / lower the cap (e.g. operators on
Max20x tier with larger 5h pools may raise to 3). Invalid values
silently fall back to the default — the lane should never harden into
"no slots" mid-run because of a typo.
"""

DEFAULT_CLAUDE_CLI_LANE_MAX = 3
"""PR-LANE-CAP-TIGHTER (v0.99.76, 2026-05-27) — lowered from 5.

v0.99.75 dropped this from 50 to 5 after the gen1-broken_tool_use
freeze (Node V8 spawn cost ~425 MB × 50 ≈ 21 GB peak on a 16 GB
box). Empirically, even cap 5 needs ~3 GB of host headroom (5 ×
~487 MB per match) that the operator's M3 16 GB rarely has free
without explicit desktop-app cleanup — the *steady state* PhysMem
unused on this host hovers around 150-750 MB during normal work.
Cap 3 keeps the burst to ~1.5 GB which survives without requiring
the operator to close Slack / Chrome / Notion first.

Operator override via :data:`CLAUDE_CLI_LANE_MAX_ENV`:
* 16 GB box (this default): leave at 3.
* 32 GB box: raise to ~6.
* 64 GB+ Mac Studio / Linux server: raise to 20-50.
* The Anthropic RPM ceiling kicks in well above any local-RSS-safe
  cap on consumer hardware, so this knob is for memory, not quota."""

CLAUDE_CLI_LANE_TIMEOUT_S = 7200.0
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 300s (5min) to
7200s (2h). Pre-raise the ranker's parallel match-burst could send
the last-queued voter to a 60-100min wait, well past 5min — the lane
would fall through to "timeout" and surface a `TimeoutError` even
though the subprocess itself was perfectly healthy. The 2h timeout
covers the worst-case Loop 1 ranker (59 matches × ~70s/voter / cap 3
= ~23min steady state, with retries up to ~1h). A genuinely-stuck
subprocess still surfaces — just on a 2h boundary instead of 5min.

Pre-raise rationale (retained for context): A legitimate
``claude --print`` for mutator-sized prompts finishes in
seconds-to-tens-of-seconds; an inspect_ai eval call may take a minute
or two. The lane wait should outlast a queued slow call but not so
long that a genuinely-stuck subprocess hides the
problem from operators."""


_CLAUDE_CLI_LANE: Lane | None = None
_CLAUDE_CLI_LANE_INIT_LOCK = threading.Lock()
"""Double-checked locking around lazy init (same pattern as
``core/orchestration/audit_lane.py``). Two concurrent first-callers could
otherwise observe ``_CLAUDE_CLI_LANE is None`` and construct distinct
:class:`Lane` instances, defeating the per-bucket cap this module
exists to enforce."""


def resolve_claude_cli_lane_max() -> int:
    """Return the effective cap, honouring :data:`CLAUDE_CLI_LANE_MAX_ENV`.

    Falls back to :data:`DEFAULT_CLAUDE_CLI_LANE_MAX` for empty,
    non-integer, or non-positive overrides. Surfaced as a function
    rather than a constant so tests can monkeypatch ``os.environ`` and
    re-resolve without touching the module-level singleton.
    """
    raw = os.environ.get(CLAUDE_CLI_LANE_MAX_ENV, "").strip()
    if not raw:
        return DEFAULT_CLAUDE_CLI_LANE_MAX
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_CLAUDE_CLI_LANE_MAX
    if parsed <= 0:
        return DEFAULT_CLAUDE_CLI_LANE_MAX
    return parsed


def get_claude_cli_lane() -> Lane:
    """Return the singleton ``claude-cli-subagent`` lane, lazily initialised.

    Thread-safe via double-checked locking (see
    :data:`_CLAUDE_CLI_LANE_INIT_LOCK`). Exposed for tests that need
    to inspect ``lane.stats`` / ``lane.get_active()`` after a series of
    acquires.
    """
    global _CLAUDE_CLI_LANE
    if _CLAUDE_CLI_LANE is None:
        with _CLAUDE_CLI_LANE_INIT_LOCK:
            if _CLAUDE_CLI_LANE is None:  # re-check inside lock
                _CLAUDE_CLI_LANE = Lane(
                    name=CLAUDE_CLI_LANE_NAME,
                    max_concurrent=resolve_claude_cli_lane_max(),
                    timeout_s=CLAUDE_CLI_LANE_TIMEOUT_S,
                )
    return _CLAUDE_CLI_LANE


CLAUDE_CLI_LANE_THROTTLED_MSG = (
    "claude-cli-subagent lane blocked — 5-hour OAuth bucket >= "
    "throttle threshold (see GEODE_CLAUDE_OAUTH_POLL_DISABLED to bypass)."
)
"""Surface text for the PR-LQ-Phase3 OAuth-quota block.

Phase 4's classifier sees this as a quota-class transient because the
message mentions ``5-hour`` — so the existing retry/backoff path
(``next_retry_at`` → quota schedule) picks it up without any
additional wiring. Tests pin the substring against the
``_QUOTA_RE`` pattern."""


@contextmanager
def acquire_claude_cli_lane(key: str) -> Iterator[None]:
    """Block until a ``claude --print`` slot is free, then yield.

    Used as a sync context manager around the mutator runner's
    ``subprocess.run(["claude", "--print", ...])`` call::

        with acquire_claude_cli_lane(key=session_id):
            stdout = invoke_claude_cli(system_prompt=..., user_prompt=...)

    Raises :class:`TimeoutError` (propagated from
    :meth:`Lane.acquire`) when the slot doesn't free within
    :data:`CLAUDE_CLI_LANE_TIMEOUT_S`.

    PR-LQ-Phase3 (2026-05-22) — before reserving a slot, consult
    :func:`core.llm.oauth_usage.should_block_lane_acquisition`. When
    the 5-hour OAuth bucket has crossed the throttle threshold the
    helper returns True and this acquire raises ``TimeoutError`` with
    a ``5-hour limit reached``-shaped message so Phase 4's
    classifier routes the caller to the quota backoff schedule.
    """
    from core.llm.oauth_usage import should_block_lane_acquisition

    if should_block_lane_acquisition():
        raise TimeoutError(CLAUDE_CLI_LANE_THROTTLED_MSG)
    lane = get_claude_cli_lane()
    with lane.acquire(key):
        yield


@asynccontextmanager
async def acquire_claude_cli_lane_async(key: str) -> AsyncIterator[None]:
    """Async sibling for inspect_ai's :class:`ClaudeCliAPI.generate`.

    Shares the SAME underlying semaphore as
    :func:`acquire_claude_cli_lane`, so the cap is global across the
    sync and async spawn paths. The blocking acquire runs in a worker
    thread (``asyncio.to_thread``) so the event loop is not pinned
    while waiting for a slot.

    PR-LQ-Phase3 — the OAuth-quota probe runs via
    :func:`asyncio.to_thread` (the underlying poller uses
    :mod:`urllib`, which would block the loop if called directly).
    """
    import asyncio

    from core.llm.oauth_usage import should_block_lane_acquisition

    if await asyncio.to_thread(should_block_lane_acquisition):
        raise TimeoutError(CLAUDE_CLI_LANE_THROTTLED_MSG)
    lane = get_claude_cli_lane()
    async with lane.acquire_async(key):
        yield


def _reset_claude_cli_lane_for_tests() -> None:
    """Drop the module-level singleton so the next ``get_claude_cli_lane``
    call rebuilds it.

    Tests that mutate :data:`CLAUDE_CLI_LANE_MAX_ENV` via
    ``monkeypatch.setenv`` need this to re-resolve the cap; without
    it the first call captures the cap forever (per double-checked
    locking).
    """
    global _CLAUDE_CLI_LANE
    with _CLAUDE_CLI_LANE_INIT_LOCK:
        _CLAUDE_CLI_LANE = None
