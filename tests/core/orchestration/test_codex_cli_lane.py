"""Tests for ``core.orchestration.codex_cli_lane`` — Codex parity.

Mirrors ``test_claude_cli_lane.py`` 1:1 so the two sides stay in
lock-step: singleton, env override fallback, sync acquire, dashboard
mirror in ``build_default_lanes``.
"""

from __future__ import annotations

import pytest
from core.orchestration.codex_cli_lane import (
    CODEX_CLI_LANE_MAX_ENV,
    CODEX_CLI_LANE_NAME,
    DEFAULT_CODEX_CLI_LANE_MAX,
    _reset_codex_cli_lane_for_tests,
    acquire_codex_cli_lane,
    get_codex_cli_lane,
    resolve_codex_cli_lane_max,
)


@pytest.fixture(autouse=True)
def _reset_codex_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CODEX_CLI_LANE_MAX_ENV, raising=False)
    _reset_codex_cli_lane_for_tests()


class TestResolveCodexCliLaneMax:
    def test_default_when_env_unset(self) -> None:
        assert resolve_codex_cli_lane_max() == DEFAULT_CODEX_CLI_LANE_MAX

    def test_env_override_positive_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CODEX_CLI_LANE_MAX_ENV, "5")
        assert resolve_codex_cli_lane_max() == 5

    @pytest.mark.parametrize("value", ["", "not-int", "0", "-1"])
    def test_fallback_for_invalid(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CODEX_CLI_LANE_MAX_ENV, value)
        assert resolve_codex_cli_lane_max() == DEFAULT_CODEX_CLI_LANE_MAX


class TestSingleton:
    def test_get_returns_singleton(self) -> None:
        first = get_codex_cli_lane()
        second = get_codex_cli_lane()
        assert first is second

    def test_lane_name_and_default_cap(self) -> None:
        lane = get_codex_cli_lane()
        assert lane.name == CODEX_CLI_LANE_NAME
        assert lane.max_concurrent == DEFAULT_CODEX_CLI_LANE_MAX

    def test_env_override_applied_after_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CODEX_CLI_LANE_MAX_ENV, "3")
        _reset_codex_cli_lane_for_tests()
        lane = get_codex_cli_lane()
        assert lane.max_concurrent == 3


class TestAcquireSync:
    def test_sync_acquire_increments_and_releases(self) -> None:
        lane = get_codex_cli_lane()
        assert lane.active_count == 0
        with acquire_codex_cli_lane(key="job-1"):
            assert lane.active_count == 1
        assert lane.active_count == 0


class TestDefaultLanesDashboardMirror:
    def test_build_default_lanes_registers_codex_lane(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import config as _config
        from core.wiring.container import build_default_lanes

        class _StubSettings:
            gateway_max_concurrent = 0

        monkeypatch.setattr(_config, "settings", _StubSettings(), raising=False)

        queue = build_default_lanes()
        lane = queue.get_lane(CODEX_CLI_LANE_NAME)
        assert lane is not None
        assert lane.max_concurrent == resolve_codex_cli_lane_max()


class TestPhase3IntegrationCodexThrottle:
    """Confirm the Codex lane consults
    :func:`should_block_codex_lane_acquisition` before grabbing a slot."""

    def test_acquire_raises_when_codex_quota_throttled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.llm import codex_oauth_usage

        # Monkeypatch the decision helper so the lane sees "throttled"
        # without us needing a real Codex usage payload.
        def _always_block() -> bool:
            return True

        monkeypatch.setattr(
            codex_oauth_usage,
            "should_block_codex_lane_acquisition",
            _always_block,
            raising=True,
        )
        # The acquire site imports the helper inside the function; we
        # need to patch the module attribute the function actually
        # resolves at call time.
        with (
            pytest.raises(TimeoutError, match="5-hour"),
            acquire_codex_cli_lane(key="blocked"),
        ):
            pass
