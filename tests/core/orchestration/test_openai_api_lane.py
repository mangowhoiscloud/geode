"""PR-OAUTH-API-LANES (2026-05-26) — openai-api lane invariants.

Mirrors test_anthropic_api_lane.py — the two lanes follow identical
shape (singleton + env override + sync/async acquire + burst cap)
because both gate per-account 429 floors with the same primitive
(:class:`core.orchestration.lane_queue.Lane`).
"""

from __future__ import annotations

import asyncio

import pytest
from core.orchestration.openai_api_lane import (
    DEFAULT_OPENAI_API_LANE_MAX,
    OPENAI_API_LANE_MAX_ENV,
    OPENAI_API_LANE_NAME,
    acquire_openai_api_lane,
    acquire_openai_api_lane_async,
    get_openai_api_lane,
    reset_openai_api_lane_for_tests,
    resolve_openai_api_lane_max,
)


@pytest.fixture(autouse=True)
def _reset_lane() -> None:
    reset_openai_api_lane_for_tests()
    yield
    reset_openai_api_lane_for_tests()


def test_default_max_concurrent_is_ten() -> None:
    """Default capacity 10 — PR-LANE-CAP-CONSERVATIVE (v0.99.75,
    2026-05-27) lowered from 50 to 10 after the cap-50 ranker burst
    froze a 16 GB M3 host. Paired with ``claude_cli_lane=5`` for the
    standard 1-claude + 2-codex voter panel: 5 matches × 2 codex
    voters = exactly 10 in-flight, no queue. RPM headroom against
    the 500 RPM ChatGPT subscription ceiling stays at ~440 RPM."""
    assert DEFAULT_OPENAI_API_LANE_MAX == 10
    assert resolve_openai_api_lane_max() == 10


def test_env_override_positive_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "10")
    assert resolve_openai_api_lane_max() == 10


def test_env_override_empty_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "")
    assert resolve_openai_api_lane_max() == DEFAULT_OPENAI_API_LANE_MAX


def test_env_override_non_integer_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "not-a-number")
    assert resolve_openai_api_lane_max() == DEFAULT_OPENAI_API_LANE_MAX


def test_env_override_non_positive_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "0")
    assert resolve_openai_api_lane_max() == DEFAULT_OPENAI_API_LANE_MAX
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "-1")
    assert resolve_openai_api_lane_max() == DEFAULT_OPENAI_API_LANE_MAX


def test_singleton_identity() -> None:
    a = get_openai_api_lane()
    b = get_openai_api_lane()
    assert a is b
    assert a.name == OPENAI_API_LANE_NAME


def test_reset_drops_singleton() -> None:
    a = get_openai_api_lane()
    reset_openai_api_lane_for_tests()
    b = get_openai_api_lane()
    assert a is not b


def test_sync_acquire_smoke() -> None:
    with acquire_openai_api_lane("test-sync-key"):
        lane = get_openai_api_lane()
        assert "test-sync-key" in lane.get_active()


def test_async_acquire_smoke() -> None:
    async def _runner() -> None:
        async with acquire_openai_api_lane_async("test-async-key"):
            lane = get_openai_api_lane()
            assert "test-async-key" in lane.get_active()

    asyncio.run(_runner())


def test_async_concurrent_burst_respects_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same PR-RANKER-PARALLEL invariant as the Anthropic lane —
    burst → throttle to cap. Codex voter side specifically: a 59-match
    × 2-codex-voter burst = 118 spawn-time concurrent acquires; the
    cap (default 4) must hold them to 4 in-flight."""
    monkeypatch.setenv(OPENAI_API_LANE_MAX_ENV, "3")
    reset_openai_api_lane_for_tests()
    observed_max = 0
    inside = 0
    lock = asyncio.Lock()

    async def _hold(idx: int) -> None:
        nonlocal observed_max, inside
        async with acquire_openai_api_lane_async(f"burst-{idx}"):
            async with lock:
                inside += 1
                observed_max = max(observed_max, inside)
            await asyncio.sleep(0.02)
            async with lock:
                inside -= 1

    async def _runner() -> None:
        await asyncio.gather(*[_hold(i) for i in range(10)])

    asyncio.run(_runner())
    assert observed_max <= 3, (
        f"observed {observed_max} concurrent acquirers; lane cap=3 should have throttled the burst"
    )
