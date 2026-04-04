"""Tests for Codex CLI OAuth token reader."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from core.gateway.auth.codex_cli_oauth import (
    CodexCliCredentials,
    _decode_jwt_expiry,
    _parse_codex_credentials,
    invalidate_cache,
    read_codex_cli_credentials,
    refresh_codex_cli_token,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_cache()
    yield
    invalidate_cache()


class TestDecodeJwtExpiry:
    def test_valid_jwt(self):
        # Minimal JWT: header.payload.signature
        import base64

        payload = json.dumps({"exp": 9999999999}).encode()
        b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        token = f"eyJhbGciOiJSUzI1NiJ9.{b64}.sig"
        result = _decode_jwt_expiry(token)
        assert result == 9999999999.0

    def test_no_exp(self):
        import base64

        payload = json.dumps({"sub": "user"}).encode()
        b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        token = f"header.{b64}.sig"
        assert _decode_jwt_expiry(token) is None

    def test_not_jwt(self):
        assert _decode_jwt_expiry("not-a-jwt") is None


class TestParseCodexCredentials:
    def test_valid_full(self):
        data = {
            "tokens": {
                "access_token": "eyJhbGciOiJSUzI1NiJ9.test.sig",
                "refresh_token": "rt-test",
                "account_id": "acc-123",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        result = _parse_codex_credentials(data)
        assert result is not None
        assert result["access_token"] == "eyJhbGciOiJSUzI1NiJ9.test.sig"
        assert result["refresh_token"] == "rt-test"
        assert result["account_id"] == "acc-123"
        assert result["expires_at"] > 0

    def test_missing_tokens(self):
        assert _parse_codex_credentials({}) is None

    def test_missing_access_token(self):
        data = {"tokens": {"refresh_token": "rt"}}
        assert _parse_codex_credentials(data) is None

    def test_missing_refresh_token(self):
        data = {"tokens": {"access_token": "at"}}
        assert _parse_codex_credentials(data) is None

    def test_fallback_expiry_from_last_refresh(self):
        data = {
            "tokens": {
                "access_token": "not-a-jwt-token",
                "refresh_token": "rt",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        result = _parse_codex_credentials(data)
        assert result is not None
        # Should be ~1h after last_refresh
        assert result["expires_at"] > 1743508800  # 2026-04-01T12:00:00Z epoch


class TestReadCodexCredentials:
    def test_file_read_success(self):
        fake_data = {
            "tokens": {
                "access_token": "file-token",
                "refresh_token": "file-refresh",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        with patch(
            "core.gateway.auth.codex_cli_oauth._read_from_file",
            return_value=fake_data,
        ):
            result = read_codex_cli_credentials(force_refresh=True)

        assert result is not None
        assert result["access_token"] == "file-token"

    def test_no_file(self):
        with patch(
            "core.gateway.auth.codex_cli_oauth._read_from_file",
            return_value=None,
        ):
            result = read_codex_cli_credentials(force_refresh=True)
        assert result is None

    def test_cache_hit(self):
        fake_data = {
            "tokens": {
                "access_token": "cached",
                "refresh_token": "rt",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        with patch(
            "core.gateway.auth.codex_cli_oauth._read_from_file",
            return_value=fake_data,
        ):
            r1 = read_codex_cli_credentials(force_refresh=True)

        with patch(
            "core.gateway.auth.codex_cli_oauth._read_from_file",
        ) as mock_read:
            r2 = read_codex_cli_credentials()

        assert r1 == r2
        mock_read.assert_not_called()


class TestRefreshCodexToken:
    def test_refresh_updates(self):
        from core.gateway.auth.profiles import AuthProfile, CredentialType

        profile = AuthProfile(
            name="openai:codex-cli",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="old-token",
            managed_by="codex-cli",
        )
        new_creds: CodexCliCredentials = {
            "access_token": "new-token",
            "refresh_token": "rt",
            "expires_at": time.time() + 3600,
        }
        with patch(
            "core.gateway.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=new_creds,
        ):
            updated = refresh_codex_cli_token(profile)

        assert updated is True
        assert profile.key == "new-token"

    def test_refresh_no_change(self):
        from core.gateway.auth.profiles import AuthProfile, CredentialType

        profile = AuthProfile(
            name="openai:codex-cli",
            provider="openai",
            credential_type=CredentialType.OAUTH,
            key="same-token",
            managed_by="codex-cli",
        )
        creds: CodexCliCredentials = {
            "access_token": "same-token",
            "refresh_token": "rt",
            "expires_at": time.time() + 3600,
        }
        with patch(
            "core.gateway.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=creds,
        ):
            assert refresh_codex_cli_token(profile) is False
