"""Tests for ``core.llm.codex_oauth_usage`` — Codex WHAM HTTP path.

paperclip ``fetchCodexQuota`` 1:1 Python port. All HTTP calls are
mocked through ``unittest.mock`` so the suite stays cheap and
deterministic — no live network in CI.

Coverage map:

* :class:`TestReadCodexCredentials` — modern + legacy auth.json,
  partial fields, malformed JSON.
* :class:`TestFetchCodexUsage` — WHAM endpoint success / error /
  timeout / malformed JSON, header attachment, reset_at number/string
  normalisation.
* :class:`TestParseWhamPayload` — null-tolerant field parsing.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest
from core.llm import codex_oauth_usage
from core.llm.codex_oauth_usage import (
    CodexAuthCredentials,
    CodexUsage,
    _parse_wham_payload,
    fetch_codex_usage,
    read_codex_oauth_credentials,
    read_codex_oauth_token,
)


class TestReadCodexCredentials:
    def test_reads_modern_tokens_block_with_account_id(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "tok-modern",
                        "account_id": "acc-1",
                        "id_token": "jwt.xyz.sig",
                    }
                }
            )
        )
        creds = read_codex_oauth_credentials()
        assert creds is not None
        assert creds.token == "tok-modern"
        assert creds.account_id == "acc-1"

    def test_modern_block_without_account_id(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": "tok-only"}}))
        creds = read_codex_oauth_credentials()
        assert creds is not None
        assert creds.token == "tok-only"
        assert creds.account_id is None

    def test_reads_legacy_top_level_schema(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps({"accessToken": "tok-legacy", "accountId": "acc-2"})
        )
        creds = read_codex_oauth_credentials()
        assert creds is not None
        assert creds.token == "tok-legacy"
        assert creds.account_id == "acc-2"

    def test_modern_layout_wins_over_legacy(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If both schemas are present (transitional auth.json), modern
        ``tokens.access_token`` must win."""
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps(
                {
                    "tokens": {"access_token": "tok-modern"},
                    "accessToken": "tok-legacy",
                }
            )
        )
        creds = read_codex_oauth_credentials()
        assert creds is not None
        assert creds.token == "tok-modern"

    def test_returns_none_when_no_file(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        assert read_codex_oauth_credentials() is None
        assert read_codex_oauth_token() is None

    def test_tolerates_malformed_json(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text("{nope")
        assert read_codex_oauth_credentials() is None

    def test_empty_token_treated_as_missing(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(json.dumps({"tokens": {"access_token": ""}}))
        assert read_codex_oauth_credentials() is None

    def test_compat_shim_returns_just_token(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "tok", "account_id": "acc"}})
        )
        assert read_codex_oauth_token() == "tok"


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


class TestFetchCodexUsage:
    _PAYLOAD = {
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {
                "used_percent": 42.5,
                "limit_window_seconds": 18000,
                "reset_at": "2026-05-22T22:00:00Z",
            },
            "secondary_window": {
                "used_percent": 12,
                "limit_window_seconds": 604800,
                "reset_at": 1716998400,  # unix seconds — must normalise
            },
        },
        "credits": {"balance": 1234, "unlimited": False},
    }

    def test_attaches_authorization_and_account_id_headers(self) -> None:
        captured: dict[str, str] = {}

        def _capture(req: Any, timeout: float = 0) -> _StubResponse:
            captured.update(dict(req.header_items()))
            return _StubResponse(200, json.dumps(self._PAYLOAD).encode("utf-8"))

        creds = CodexAuthCredentials(token="tok-x", account_id="acc-y")
        with patch.object(codex_oauth_usage.urllib.request, "urlopen", _capture):
            usage = fetch_codex_usage(creds)

        assert usage is not None
        headers = {k.lower(): v for k, v in captured.items()}
        assert headers["authorization"] == "Bearer tok-x"
        assert headers["chatgpt-account-id"] == "acc-y"

    def test_omits_account_id_header_when_credentials_have_none(self) -> None:
        captured: dict[str, str] = {}

        def _capture(req: Any, timeout: float = 0) -> _StubResponse:
            captured.update(dict(req.header_items()))
            return _StubResponse(200, b"{}")

        creds = CodexAuthCredentials(token="tok-only", account_id=None)
        with patch.object(codex_oauth_usage.urllib.request, "urlopen", _capture):
            fetch_codex_usage(creds)

        headers = {k.lower(): v for k, v in captured.items()}
        assert "chatgpt-account-id" not in headers
        assert headers["authorization"] == "Bearer tok-only"

    def test_parses_complete_payload(self) -> None:
        body = json.dumps(self._PAYLOAD).encode("utf-8")
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(200, body),
        ):
            usage = fetch_codex_usage(CodexAuthCredentials(token="t"))

        assert usage is not None
        assert usage.plan_type == "plus"

        assert usage.five_hour is not None
        assert usage.five_hour.utilization == pytest.approx(0.425)
        assert usage.five_hour.resets_at == "2026-05-22T22:00:00Z"

        # secondary_window's reset_at was unix seconds — must be ISO now.
        assert usage.weekly is not None
        assert usage.weekly.utilization == pytest.approx(0.12)
        assert usage.weekly.resets_at is not None
        assert "T" in usage.weekly.resets_at  # ISO-shaped

        assert usage.credits["balance"] == 1234
        assert usage.credits["unlimited"] is False

    def test_returns_none_on_non_200(self) -> None:
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(503, b'{"err":"x"}'),
        ):
            assert fetch_codex_usage(CodexAuthCredentials(token="t")) is None

    def test_returns_none_on_http_error(self) -> None:
        exc = urllib.error.HTTPError(
            url=codex_oauth_usage.CODEX_WHAM_USAGE_URL,
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b""),
        )
        with patch.object(codex_oauth_usage.urllib.request, "urlopen", side_effect=exc):
            assert fetch_codex_usage(CodexAuthCredentials(token="t")) is None

    def test_returns_none_on_url_error(self) -> None:
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("network down"),
        ):
            assert fetch_codex_usage(CodexAuthCredentials(token="t")) is None

    def test_returns_none_on_timeout(self) -> None:
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            side_effect=TimeoutError("slow"),
        ):
            assert fetch_codex_usage(CodexAuthCredentials(token="t")) is None

    def test_returns_none_on_malformed_json(self) -> None:
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(200, b"not json"),
        ):
            assert fetch_codex_usage(CodexAuthCredentials(token="t")) is None

    def test_tolerates_empty_payload(self) -> None:
        with patch.object(
            codex_oauth_usage.urllib.request,
            "urlopen",
            return_value=_StubResponse(200, b"{}"),
        ):
            usage = fetch_codex_usage(CodexAuthCredentials(token="t"))
        assert usage is not None
        assert usage.five_hour is None
        assert usage.weekly is None
        assert usage.credits == {}
        assert usage.plan_type is None


class TestParseWhamPayload:
    def test_drops_non_dict_payload(self) -> None:
        assert _parse_wham_payload(None) == CodexUsage()
        assert _parse_wham_payload("not a dict") == CodexUsage()

    def test_handles_missing_rate_limit_block(self) -> None:
        usage = _parse_wham_payload({"plan_type": "free", "credits": {"balance": 0}})
        assert usage.plan_type == "free"
        assert usage.five_hour is None
        assert usage.weekly is None
        assert usage.credits == {"balance": 0}

    def test_partial_window_only_primary(self) -> None:
        usage = _parse_wham_payload({"rate_limit": {"primary_window": {"used_percent": 60}}})
        assert usage.five_hour is not None
        assert usage.five_hour.utilization == pytest.approx(0.6)
        assert usage.weekly is None
