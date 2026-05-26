"""Module-level Lane for ``claude --print`` sub-agent subprocess
serialisation.

PR-LQ-Phase2 (2026-05-22) — second leg of the LaneQueue 5-phase plan
([[project_lanequeue_handoff_2026_05_22]]).

Why a separate lane (not just ``global``)
=========================================

Both the self-improving-loop mutator runner
(:func:`core.self_improving_loop.cli_subprocess.invoke_claude_cli`) and
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

Why ``max_concurrent=4`` (PR-LANE-CAP-AGGRESSIVE, 2026-05-27)
============================================================

Raised from 2 (PR-RANKER-PARALLEL conservative default) to 4 per
operator decision "공격적으로 늘려" + the measured PR-RANKER-PARALLEL
burst evidence (Loop 1: 59 matches × 1 anthropic voter = 59
``claude --print`` forks queued behind the prior cap-2 ceiling, tail
latency past 5min).

**Burst-limiter reality**: Claude Code's documented sub-agent burst
floor is 3-4 *exclusive of* the operator's host session — the host's
own OAuth claim does NOT consume a sub-agent slot. So cap 4 = 4
``claude --print`` sub-agents running concurrently against the
shared 5h pool, with the host's interactive session as a separate
budget line item. The two share the same 5h pool *token total* but
their inflight counts are independent.

**Aggressive headroom trade-off**: Cap 4 sits at the upper edge of
the documented floor. Two stacked watch-outs:

1. **Pool exhaustion still possible** — the 5h pool's *token*
   budget is a separate ceiling. Smoke 25 (2026-05-26) hit
   ``model_action_required`` after ~2h of sustained sub-agent
   traffic. Cap-raise alone doesn't prevent that; the pool must
   refresh before resume.
2. **Host session contention**: if the operator's interactive
   session is mid-multi-turn while a smoke runs at cap 4, the
   shared 5h pool drains faster. Operators on Max20x tier with
   larger pools may raise via :data:`CLAUDE_CLI_LANE_MAX_ENV`;
   operators on lower tiers may lower to 2-3.

**Pre-flight measurement gap**: [[project_lanequeue_handoff_2026_05_22]]
called for a one-time measurement of the actual burst threshold.
The PR-LANE-CAP-AGGRESSIVE raise rests on smoke-24-25 empirical
data (cap 2 demonstrably idle ~95% of the 5h pool RPM budget)
rather than the original public-doc grounding.

Why module-level (not LaneQueue-registered)
===========================================

Same rationale as
:mod:`core.llm.audit_lane`:

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

DEFAULT_CLAUDE_CLI_LANE_MAX = 50
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 2 to 4.

Documented Claude Code burst-limiter floor is 3-4 slots per 5h pool.
Operator's host Claude Code session occupies 1 slot; the remaining 3
go to ranker / mutator / audit-spawned sub-agents. Pre-raise the
ranker's ``asyncio.gather`` burst (`ranker.py:256`) queued all
voter-side claude-cli calls behind 2-slot cap → 89 × 70s = ~104min
worst-case lane queue wait, well past the (also raised) 7200s
timeout. The new cap matches the documented public floor exactly,
with the host slot accounted for, so a long-running smoke (Loop 1
ranker with 59 matches × 1 anthropic voter = 59 claude-cli forks) no
longer creates a queue depth deeper than the 5h pool can sustain.

Operator override via :data:`CLAUDE_CLI_LANE_MAX_ENV` for Max20x tier
operators with larger 5h pools (5-6) or single-account audit hosts
that need to push to the documented 4-slot ceiling without host-
session contention."""

CLAUDE_CLI_LANE_TIMEOUT_S = 7200.0
"""PR-LANE-CAP-AGGRESSIVE (2026-05-27) — raised from 300s (5min) to
7200s (2h). Pre-raise the ranker's parallel match-burst could send
the last-queued voter to a 60-100min wait, well past 5min — the lane
would fall through to "timeout" and surface a `TimeoutError` even
though the subprocess itself was perfectly healthy. The 2h timeout
covers the worst-case Loop 1 ranker (59 matches × ~70s/voter / cap 4
= ~17min steady state, with retries up to ~1h). A genuinely-stuck
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
``core/llm/audit_lane.py``). Two concurrent first-callers could
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
