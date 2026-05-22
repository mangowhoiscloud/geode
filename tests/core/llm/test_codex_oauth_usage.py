"""Tests for ``core.llm.codex_oauth_usage`` — Codex parity for Phase 3.

The endpoint contract for Codex / ChatGPT-Plus OAuth quota is NOT
publicly verified, so :func:`fetch_codex_usage` is a placeholder
returning ``None``. These tests pin the SCAFFOLD:

* token reading from ``$CODEX_HOME/auth.json``
* poller behaviour (TTL, force, stale-on-fail) via injected stub
* decision helper (default fail-open, strict mode flip)
* shape parity with the Anthropic module so a future verified
  endpoint plugs into the lane without churn.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from core.llm.codex_oauth_usage import (
    CODEX_OAUTH_POLL_DISABLED_ENV,
    CODEX_OAUTH_POLL_REQUIRED_ENV,
    DEFAULT_CODEX_BLOCK_THRESHOLD,
    CodexUsage,
    CodexUsagePoller,
    CodexUsageWindow,
    _reset_default_codex_poller_for_tests,
    fetch_codex_usage,
    read_codex_oauth_token,
    should_block_codex_lane_acquisition,
)


@pytest.fixture(autouse=True)
def _reset_codex_poller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CODEX_OAUTH_POLL_DISABLED_ENV, raising=False)
    monkeypatch.delenv(CODEX_OAUTH_POLL_REQUIRED_ENV, raising=False)
    _reset_default_codex_poller_for_tests()


class TestReadCodexOAuthToken:
    def test_reads_codex_home_auth_json(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": "codex-token"}}))
        assert read_codex_oauth_token() == "codex-token"

    def test_returns_none_when_no_file(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        assert read_codex_oauth_token() is None

    def test_tolerates_malformed_json(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text("{nope")
        assert read_codex_oauth_token() is None

    def test_empty_token_treated_as_missing(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": ""}}))
        assert read_codex_oauth_token() is None


class TestFetchCodexUsagePlaceholder:
    def test_returns_none_until_endpoint_verified(self) -> None:
        """Default fetch is a no-op — pinned so a contributor who
        flips it without updating tests notices immediately."""
        assert fetch_codex_usage("any-token") is None


class TestCodexUsageIsThrottled:
    def test_throttled_at_threshold(self) -> None:
        usage = CodexUsage(five_hour=CodexUsageWindow("Current session", 0.8))
        assert usage.is_throttled(threshold=0.8) is True

    def test_below_threshold_not_throttled(self) -> None:
        usage = CodexUsage(five_hour=CodexUsageWindow("Current session", 0.6))
        assert usage.is_throttled(threshold=0.8) is False

    def test_null_window_not_throttled(self) -> None:
        assert CodexUsage(five_hour=None).is_throttled() is False


class TestCodexUsagePoller:
    def _usage(self, util: float) -> CodexUsage:
        return CodexUsage(five_hour=CodexUsageWindow("Current session", util))

    def test_caches_within_ttl(self) -> None:
        calls: list[str] = []

        def _fetch(token: str) -> CodexUsage:
            calls.append(token)
            return self._usage(0.4)

        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=_fetch, token_fn=lambda: "t")
        poller.current()
        poller.current()
        assert len(calls) == 1

    def test_force_refreshes(self) -> None:
        calls: list[str] = []

        def _fetch(token: str) -> CodexUsage:
            calls.append(token)
            return self._usage(0.5)

        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=_fetch, token_fn=lambda: "t")
        poller.current()
        poller.current(force=True)
        assert len(calls) == 2

    def test_returns_stale_on_failure(self) -> None:
        fetched: list[CodexUsage | None] = [self._usage(0.3), None]

        def _fetch(token: str) -> CodexUsage | None:
            return fetched.pop(0)

        poller = CodexUsagePoller(ttl_s=0.0, fetch_fn=_fetch, token_fn=lambda: "t")
        first = poller.current()
        second = poller.current()
        assert first is second


class TestShouldBlockCodexLaneAcquisition:
    def test_disabled_env_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CODEX_OAUTH_POLL_DISABLED_ENV, "1")
        poller = CodexUsagePoller(
            ttl_s=60.0,
            fetch_fn=lambda _t: pytest.fail("poller ran despite disabled env"),
            token_fn=lambda: "t",
        )
        assert should_block_codex_lane_acquisition(poller=poller) is False

    def test_blocks_above_threshold(self) -> None:
        usage = CodexUsage(five_hour=CodexUsageWindow("Current session", 0.9))
        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: usage, token_fn=lambda: "t")
        assert should_block_codex_lane_acquisition(poller=poller, threshold=0.8) is True

    def test_does_not_block_below_threshold(self) -> None:
        usage = CodexUsage(five_hour=CodexUsageWindow("Current session", 0.5))
        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: usage, token_fn=lambda: "t")
        assert should_block_codex_lane_acquisition(poller=poller, threshold=0.8) is False

    def test_fails_open_by_default(self) -> None:
        """With the default (placeholder) fetch returning None, the
        helper must fall open — operators upgrading from the Claude-
        only Phase 3 must not see Codex spawns suddenly blocked."""
        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: None, token_fn=lambda: "t")
        assert should_block_codex_lane_acquisition(poller=poller) is False

    def test_fails_closed_in_strict_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CODEX_OAUTH_POLL_REQUIRED_ENV, "1")
        poller = CodexUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: None, token_fn=lambda: "t")
        assert should_block_codex_lane_acquisition(poller=poller) is True

    def test_default_threshold(self) -> None:
        assert DEFAULT_CODEX_BLOCK_THRESHOLD == 0.8
