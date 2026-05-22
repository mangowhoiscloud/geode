"""Tests for ``core.orchestration.claude_cli_lane``.

PR-LQ-Phase2 (2026-05-22) — pin the module-level singleton's contract:

* Singleton identity across ``get_claude_cli_lane`` calls.
* Operator-override env honoured (positive int) and silently rejected
  (empty / non-int / non-positive) — the lane should never harden into
  "no slots" mid-run because of a typo.
* Sync + async acquire share the SAME underlying semaphore so the cap
  composes across the two spawn paths.
* Dashboard mirror in ``build_default_lanes`` exposes the lane with
  the resolved cap.
"""

from __future__ import annotations

import asyncio

import pytest
from core.orchestration.claude_cli_lane import (
    CLAUDE_CLI_LANE_MAX_ENV,
    CLAUDE_CLI_LANE_NAME,
    DEFAULT_CLAUDE_CLI_LANE_MAX,
    _reset_claude_cli_lane_for_tests,
    acquire_claude_cli_lane,
    acquire_claude_cli_lane_async,
    get_claude_cli_lane,
    resolve_claude_cli_lane_max,
)


@pytest.fixture(autouse=True)
def _reset_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the singleton + clear the env override before each test.

    Without this the first test's cap leaks into every subsequent test
    via double-checked locking (the module guards against multi-init
    by design).
    """
    monkeypatch.delenv(CLAUDE_CLI_LANE_MAX_ENV, raising=False)
    _reset_claude_cli_lane_for_tests()


class TestResolveClaudeCliLaneMax:
    def test_default_when_env_unset(self) -> None:
        assert resolve_claude_cli_lane_max() == DEFAULT_CLAUDE_CLI_LANE_MAX

    def test_env_override_positive_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, "5")
        assert resolve_claude_cli_lane_max() == 5

    def test_env_override_empty_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, "")
        assert resolve_claude_cli_lane_max() == DEFAULT_CLAUDE_CLI_LANE_MAX

    def test_env_override_non_integer_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, "not-a-number")
        assert resolve_claude_cli_lane_max() == DEFAULT_CLAUDE_CLI_LANE_MAX

    def test_env_override_zero_or_negative_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for value in ("0", "-1"):
            monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, value)
            assert resolve_claude_cli_lane_max() == DEFAULT_CLAUDE_CLI_LANE_MAX


class TestSingleton:
    def test_get_claude_cli_lane_returns_singleton(self) -> None:
        first = get_claude_cli_lane()
        second = get_claude_cli_lane()
        assert first is second

    def test_lane_name_and_default_cap(self) -> None:
        lane = get_claude_cli_lane()
        assert lane.name == CLAUDE_CLI_LANE_NAME
        assert lane.max_concurrent == DEFAULT_CLAUDE_CLI_LANE_MAX

    def test_env_override_applied_after_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, "3")
        _reset_claude_cli_lane_for_tests()
        lane = get_claude_cli_lane()
        assert lane.max_concurrent == 3


class TestAcquireSync:
    def test_sync_acquire_increments_and_releases_active_count(self) -> None:
        lane = get_claude_cli_lane()
        assert lane.active_count == 0
        with acquire_claude_cli_lane(key="job-1"):
            assert lane.active_count == 1
        assert lane.active_count == 0


class TestAcquireAsync:
    def test_async_acquire_shares_semaphore_with_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sync acquire holds the slot; concurrent async acquire must
        WAIT — proving they share the same underlying semaphore."""
        monkeypatch.setenv(CLAUDE_CLI_LANE_MAX_ENV, "1")
        _reset_claude_cli_lane_for_tests()
        lane = get_claude_cli_lane()
        assert lane.max_concurrent == 1

        async def scenario() -> None:
            # Hold the only slot synchronously, then try an async acquire
            # with a very short timeout to prove the cap is shared.
            from core.orchestration.claude_cli_lane import get_claude_cli_lane as _g

            held = _g()
            # Raw-acquire instead of context-manager so we can release
            # explicitly inside the async branch.
            assert held._raw_acquire("sync-holder")  # type: ignore[attr-defined]
            try:
                # 0.05s timeout — semaphore is held by sync side, async
                # must time out.
                lane_inner = _g()
                lane_inner.timeout_s = 0.05
                with pytest.raises(TimeoutError, match="claude-cli-subagent"):
                    async with acquire_claude_cli_lane_async(key="async-blocked"):
                        pass
            finally:
                held._raw_release("sync-holder")  # type: ignore[attr-defined]

        asyncio.run(scenario())


class TestDefaultLanesDashboardMirror:
    def test_build_default_lanes_registers_claude_cli_lane(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The container's dashboard mirror exposes the lane with the
        same cap as the module-level singleton resolver."""
        from core.wiring.container import build_default_lanes

        from core import config as _config

        class _StubSettings:
            gateway_max_concurrent = 0

        monkeypatch.setattr(_config, "settings", _StubSettings(), raising=False)

        queue = build_default_lanes()
        lane = queue.get_lane(CLAUDE_CLI_LANE_NAME)
        assert lane is not None
        assert lane.max_concurrent == resolve_claude_cli_lane_max()
