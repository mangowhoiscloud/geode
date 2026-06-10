"""Tests for ``core.llm.oauth_usage`` — Phase 3 of the LaneQueue plan.

Coverage map:

* :class:`TestReadOAuthToken` — JSON-on-disk parser (token / config-dir
  resolution / malformed-file tolerance).
* :class:`TestNormaliseUtilization` — 0-1 vs 0-100 shape handling.
* :class:`TestFetchOAuthUsage` — HTTP path with mocked ``urlopen``
  (success, HTTP error, network error, malformed JSON).
* :class:`TestOAuthUsage` — ``is_throttled`` precedence + null handling.
* :class:`TestOAuthUsagePoller` — TTL cache + force-refresh + stale-on-fail.
* :class:`TestShouldBlockLaneAcquisition` — env-knob branches +
  fail-open default.

No live network calls. Every HTTP call is mocked through
``unittest.mock`` so the suite stays cheap and deterministic.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest
from core.llm import oauth_usage
from core.llm.oauth_usage import (
    DEFAULT_BLOCK_THRESHOLD,
    OAUTH_POLL_DISABLED_ENV,
    OAUTH_POLL_REQUIRED_ENV,
    OAuthUsage,
    OAuthUsagePoller,
    OAuthUsageWindow,
    _normalise_utilization,
    _reset_default_poller_for_tests,
    fetch_oauth_usage,
    read_anthropic_oauth_token,
    should_block_lane_acquisition,
)


@pytest.fixture(autouse=True)
def _reset_poller(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the singleton + clear polling env knobs before each test."""
    monkeypatch.delenv(OAUTH_POLL_DISABLED_ENV, raising=False)
    monkeypatch.delenv(OAUTH_POLL_REQUIRED_ENV, raising=False)
    _reset_default_poller_for_tests()


class TestReadOAuthToken:
    def test_reads_dot_credentials_first(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "primary-token"}})
        )
        (tmp_path / "credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "fallback-token"}})
        )
        assert read_anthropic_oauth_token() == "primary-token"

    def test_falls_back_to_credentials_json(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / "credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "fallback-token"}})
        )
        assert read_anthropic_oauth_token() == "fallback-token"

    def test_returns_none_when_no_files(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert read_anthropic_oauth_token() is None

    def test_tolerates_malformed_json(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / ".credentials.json").write_text("{not valid json")
        assert read_anthropic_oauth_token() is None

    def test_tolerates_missing_oauth_section(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / ".credentials.json").write_text(json.dumps({"other": {}}))
        assert read_anthropic_oauth_token() is None

    def test_empty_token_treated_as_missing(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        (tmp_path / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": ""}})
        )
        assert read_anthropic_oauth_token() is None


class TestNormaliseUtilization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, None),
            (0.0, 0.0),
            (0.5, 0.5),
            (1.0, 1.0),
            # 0-100 percentage shape (paperclip ``toPercent`` parity).
            (50, 0.5),
            (100, 1.0),
            (150, 1.0),  # clamp to 1.0
            (-0.1, 0.0),  # clamp at 0
            ("not-a-number", None),
        ],
    )
    def test_normalises_to_zero_one_range(self, raw: object, expected: float | None) -> None:
        assert _normalise_utilization(raw) == expected  # type: ignore[arg-type]


class _StubResponse:
    """Mimic the bits of ``http.client.HTTPResponse`` we touch in code."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _StubResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestFetchOAuthUsage:
    _PAYLOAD = {
        "five_hour": {"utilization": 0.42, "resets_at": "2026-05-22T15:00:00-07:00"},
        "seven_day": {"utilization": 12, "resets_at": "2026-05-29T00:00:00Z"},
        "seven_day_sonnet": {"utilization": 5.0, "resets_at": None},
        "seven_day_opus": {"utilization": None, "resets_at": None},
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 10000,
            "used_credits": 1234,
            "currency": "USD",
        },
    }

    def test_parses_complete_payload(self) -> None:
        body = json.dumps(self._PAYLOAD).encode("utf-8")
        with patch.object(
            oauth_usage.urllib.request, "urlopen", return_value=_StubResponse(200, body)
        ):
            usage = fetch_oauth_usage("token")
        assert usage is not None
        assert usage.five_hour is not None
        assert usage.five_hour.utilization == pytest.approx(0.42)
        assert usage.five_hour.resets_at == "2026-05-22T15:00:00-07:00"
        # 12 → 0.12 (percentage normalisation).
        assert usage.seven_day is not None
        assert usage.seven_day.utilization == pytest.approx(0.12)
        # 5.0 ≤ 1.0 check — already 0-1 shape (legacy) so stays 5.0?
        # Wait — 5.0 is > 1.0 so it gets divided to 0.05.
        assert usage.seven_day_sonnet is not None
        assert usage.seven_day_sonnet.utilization == pytest.approx(0.05)
        # Missing utilisation → None.
        assert usage.seven_day_opus is not None
        assert usage.seven_day_opus.utilization is None
        # Extra usage carried as raw dict.
        assert usage.extra_usage["monthly_limit"] == 10000

    def test_returns_none_on_non_200(self) -> None:
        with patch.object(
            oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(500, b'{"err": "x"}'),
        ):
            assert fetch_oauth_usage("token") is None

    def test_returns_none_on_http_error(self) -> None:
        exc = urllib.error.HTTPError(
            url=oauth_usage.OAUTH_USAGE_URL,
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        with patch.object(oauth_usage.urllib.request, "urlopen", side_effect=exc):
            assert fetch_oauth_usage("token") is None

    def test_returns_none_on_url_error(self) -> None:
        with patch.object(
            oauth_usage.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("network down"),
        ):
            assert fetch_oauth_usage("token") is None

    def test_returns_none_on_timeout(self) -> None:
        with patch.object(
            oauth_usage.urllib.request,
            "urlopen",
            side_effect=TimeoutError("slow"),
        ):
            assert fetch_oauth_usage("token") is None

    def test_returns_none_on_malformed_json(self) -> None:
        with patch.object(
            oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(200, b"not json"),
        ):
            assert fetch_oauth_usage("token") is None

    def test_tolerates_empty_payload(self) -> None:
        with patch.object(
            oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(200, b"{}"),
        ):
            usage = fetch_oauth_usage("token")
        assert usage is not None
        assert usage.five_hour is None
        assert usage.extra_usage == {}


class TestOAuthUsageIsThrottled:
    def test_throttled_above_threshold(self) -> None:
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.85))
        assert usage.is_throttled(threshold=0.8) is True

    def test_not_throttled_below_threshold(self) -> None:
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.5))
        assert usage.is_throttled(threshold=0.8) is False

    def test_at_threshold_is_throttled(self) -> None:
        """``>=`` semantics — at the boundary we surrender."""
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.8))
        assert usage.is_throttled(threshold=0.8) is True

    def test_no_five_hour_data_is_not_throttled(self) -> None:
        usage = OAuthUsage(five_hour=None)
        assert usage.is_throttled() is False

    def test_null_utilization_is_not_throttled(self) -> None:
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", None))
        assert usage.is_throttled() is False


class TestOAuthUsagePoller:
    def _usage_at(self, util: float) -> OAuthUsage:
        return OAuthUsage(five_hour=OAuthUsageWindow("Current session", util))

    def test_first_call_fetches(self) -> None:
        usage_obj = self._usage_at(0.5)
        fetched: list[str] = []

        def _fetch(token: str) -> OAuthUsage:
            fetched.append(token)
            return usage_obj

        poller = OAuthUsagePoller(
            ttl_s=30.0,
            fetch_fn=_fetch,
            token_fn=lambda: "stub-token",
        )
        assert poller.current() is usage_obj
        assert fetched == ["stub-token"]

    def test_within_ttl_returns_cached(self) -> None:
        fetched: list[str] = []
        usage_obj = self._usage_at(0.3)

        def _fetch(token: str) -> OAuthUsage:
            fetched.append(token)
            return usage_obj

        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=_fetch, token_fn=lambda: "tok")
        poller.current()
        poller.current()
        poller.current()
        assert len(fetched) == 1

    def test_force_refresh_bypasses_cache(self) -> None:
        fetched: list[str] = []
        usage_obj = self._usage_at(0.4)

        def _fetch(token: str) -> OAuthUsage:
            fetched.append(token)
            return usage_obj

        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=_fetch, token_fn=lambda: "tok")
        poller.current()
        poller.current(force=True)
        assert len(fetched) == 2

    def test_returns_stale_when_refresh_fails(self) -> None:
        """A network blip should NOT erase the last good reading."""
        fetched: list[OAuthUsage | None] = [self._usage_at(0.2), None]

        def _fetch(token: str) -> OAuthUsage | None:
            return fetched.pop(0)

        poller = OAuthUsagePoller(
            ttl_s=0.0,  # always stale → always tries to refresh
            fetch_fn=_fetch,
            token_fn=lambda: "tok",
        )
        first = poller.current()
        assert first is not None and first.five_hour is not None
        # Cache is immediately stale; next call refreshes → fetch returns None.
        # Poller should return the previous good value.
        second = poller.current()
        assert second is first

    def test_returns_none_when_no_token(self) -> None:
        def _fetch(token: str) -> OAuthUsage:
            raise AssertionError("must not be called without a token")

        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=_fetch, token_fn=lambda: None)
        assert poller.current() is None


class TestShouldBlockLaneAcquisition:
    def test_disabled_env_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When polling is disabled, the helper always returns False."""
        monkeypatch.setenv(OAUTH_POLL_DISABLED_ENV, "1")
        # Fail-loud poller — if the helper consulted it, we'd see this.
        poller = OAuthUsagePoller(
            ttl_s=60.0,
            fetch_fn=lambda _t: pytest.fail("poller invoked despite disabled env"),
            token_fn=lambda: "tok",
        )
        assert should_block_lane_acquisition(poller=poller) is False

    def test_blocks_when_utilisation_exceeds_threshold(self) -> None:
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.9))
        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: usage, token_fn=lambda: "tok")
        assert should_block_lane_acquisition(poller=poller, threshold=0.8) is True

    def test_does_not_block_below_threshold(self) -> None:
        usage = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.4))
        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: usage, token_fn=lambda: "tok")
        assert should_block_lane_acquisition(poller=poller, threshold=0.8) is False

    def test_default_threshold_is_80_percent(self) -> None:
        usage_high = OAuthUsage(five_hour=OAuthUsageWindow("Current session", 0.85))
        poller_high = OAuthUsagePoller(
            ttl_s=60.0, fetch_fn=lambda _t: usage_high, token_fn=lambda: "tok"
        )
        assert should_block_lane_acquisition(poller=poller_high) is True
        assert DEFAULT_BLOCK_THRESHOLD == 0.8

    def test_fails_open_when_poll_returns_none(self) -> None:
        """Default behaviour — polling errors don't block."""
        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: None, token_fn=lambda: "tok")
        assert should_block_lane_acquisition(poller=poller) is False

    def test_fails_closed_in_strict_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(OAUTH_POLL_REQUIRED_ENV, "1")
        poller = OAuthUsagePoller(ttl_s=60.0, fetch_fn=lambda _t: None, token_fn=lambda: "tok")
        assert should_block_lane_acquisition(poller=poller) is True
