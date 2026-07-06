"""PR-OAUTH-API-LANES (2026-05-26) — anthropic-api lane invariants.

Mirrors the test pattern of tests/test_claude_cli_lane.py — singleton
identity, default cap, env override, reset isolation between tests.
The lane gates direct Anthropic API calls (anthropic_oauth +
anthropic_payg adapters) so a PR-RANKER-PARALLEL burst stays under
the per-account 429 floor.
"""

from __future__ import annotations

import asyncio

import pytest
from core.orchestration.anthropic_api_lane import (
    ANTHROPIC_API_LANE_MAX_ENV,
    ANTHROPIC_API_LANE_NAME,
    DEFAULT_ANTHROPIC_API_LANE_MAX,
    acquire_anthropic_api_lane,
    acquire_anthropic_api_lane_async,
    get_anthropic_api_lane,
    reset_anthropic_api_lane_for_tests,
    resolve_anthropic_api_lane_max,
)


@pytest.fixture(autouse=True)
def _reset_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the lane singleton before + after each test so env override
    edits take effect and the next test starts with a clean lane."""
    monkeypatch.delenv(ANTHROPIC_API_LANE_MAX_ENV, raising=False)
    reset_anthropic_api_lane_for_tests()
    yield
    reset_anthropic_api_lane_for_tests()


def test_default_max_concurrent_is_fifty() -> None:
    """Default capacity 50 — PR-LANE-CAP-50 (2026-05-27) raised from
    8 to 50 per operator decision. Anthropic tier 1 documents 50 RPM
    aggregate per account; cap 50 saturates the documented ceiling
    (intentionally aggressive — operators on tier 1 may want to drop
    via ``GEODE_ANTHROPIC_API_LANE_MAX``; enterprise tiers with
    higher RPM keep the headroom)."""
    assert DEFAULT_ANTHROPIC_API_LANE_MAX == 50
    assert resolve_anthropic_api_lane_max() == 50


def test_env_override_positive_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "8")
    assert resolve_anthropic_api_lane_max() == 8


def test_env_override_empty_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "")
    assert resolve_anthropic_api_lane_max() == DEFAULT_ANTHROPIC_API_LANE_MAX


def test_env_override_non_integer_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo must NEVER harden the lane into "no slots" — fallback to
    the default keeps the lane usable instead of trapping the operator."""
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "abc")
    assert resolve_anthropic_api_lane_max() == DEFAULT_ANTHROPIC_API_LANE_MAX


def test_env_override_non_positive_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 / negative override → fall back. Zero would lock the lane;
    negatives are nonsensical for a semaphore."""
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "0")
    assert resolve_anthropic_api_lane_max() == DEFAULT_ANTHROPIC_API_LANE_MAX
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "-3")
    assert resolve_anthropic_api_lane_max() == DEFAULT_ANTHROPIC_API_LANE_MAX


def test_singleton_identity() -> None:
    """``get_anthropic_api_lane`` must return the same object across
    calls so the per-account cap is shared, not multiplied."""
    a = get_anthropic_api_lane()
    b = get_anthropic_api_lane()
    assert a is b
    assert a.name == ANTHROPIC_API_LANE_NAME


def test_reset_drops_singleton() -> None:
    a = get_anthropic_api_lane()
    reset_anthropic_api_lane_for_tests()
    b = get_anthropic_api_lane()
    assert a is not b


def test_singleton_picks_up_env_after_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The env override should win at construction time. Reset between
    test stanzas ensures the next ``get_*`` re-resolves the env."""
    lane_default = get_anthropic_api_lane()
    assert lane_default.max_concurrent == DEFAULT_ANTHROPIC_API_LANE_MAX
    reset_anthropic_api_lane_for_tests()
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "6")
    lane_overridden = get_anthropic_api_lane()
    assert lane_overridden.max_concurrent == 6


def test_sync_acquire_smoke() -> None:
    """Synchronous acquire path works (CLI / test helper invocations)."""
    with acquire_anthropic_api_lane("test-sync-key"):
        # Inside the lane the active map should hold the key.
        lane = get_anthropic_api_lane()
        assert "test-sync-key" in lane.get_active()


def test_async_acquire_smoke() -> None:
    """Async acquire path works (production adapter call sites)."""

    async def _runner() -> None:
        async with acquire_anthropic_api_lane_async("test-async-key"):
            lane = get_anthropic_api_lane()
            assert "test-async-key" in lane.get_active()

    asyncio.run(_runner())


def test_async_concurrent_burst_respects_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fire 6 concurrent acquirers against a cap of 2 — at most 2 may
    be inside the lane at once. This is the PR-RANKER-PARALLEL safety
    invariant the lane exists to enforce."""
    monkeypatch.setenv(ANTHROPIC_API_LANE_MAX_ENV, "2")
    reset_anthropic_api_lane_for_tests()
    observed_max = 0
    inside = 0
    lock = asyncio.Lock()

    async def _hold(idx: int) -> None:
        nonlocal observed_max, inside
        async with acquire_anthropic_api_lane_async(f"burst-{idx}"):
            async with lock:
                inside += 1
                observed_max = max(observed_max, inside)
            await asyncio.sleep(0.02)
            async with lock:
                inside -= 1

    async def _runner() -> None:
        await asyncio.gather(*[_hold(i) for i in range(6)])

    asyncio.run(_runner())
    assert observed_max <= 2, (
        f"observed {observed_max} concurrent acquirers; lane cap=2 should have throttled the burst"
    )
