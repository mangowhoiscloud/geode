"""Tests for Claude Code OAuth token reader."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from core.gateway.auth.claude_code_oauth import (
    ClaudeCodeCredentials,
    _parse_oauth,
    invalidate_cache,
    read_claude_code_credentials,
    refresh_claude_code_token,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear cache before each test."""
    invalidate_cache()
    yield
    invalidate_cache()


# -- _parse_oauth tests --


class TestParseOauth:
    def test_valid_full(self):
        raw = {
            "accessToken": "sk-ant-test-token",
            "refreshToken": "rt-test-refresh",
            "expiresAt": int((time.time() + 3600) * 1000),  # ms
            "subscriptionType": "max",
            "rateLimitTier": "default_claude_max_5x",
        }
        result = _parse_oauth(raw)
        assert result is not None
        assert result["access_token"] == "sk-ant-test-token"
        assert result["refresh_token"] == "rt-test-refresh"
        assert result["subscription_type"] == "max"
        assert result["rate_limit_tier"] == "default_claude_max_5x"
        # expiresAt should be converted from ms to seconds
        assert result["expires_at"] < 1e12

    def test_valid_no_refresh(self):
        raw = {
            "accessToken": "sk-ant-token-only",
            "expiresAt": int((time.time() + 3600) * 1000),
        }
        result = _parse_oauth(raw)
        assert result is not None
        assert result["access_token"] == "sk-ant-token-only"
        assert "refresh_token" not in result

    def test_missing_access_token(self):
        assert _parse_oauth({"expiresAt": 9999999999999}) is None

    def test_empty_access_token(self):
        assert _parse_oauth({"accessToken": "", "expiresAt": 9999999999999}) is None

    def test_missing_expires_at(self):
        assert _parse_oauth({"accessToken": "tok"}) is None

    def test_zero_expires_at(self):
        assert _parse_oauth({"accessToken": "tok", "expiresAt": 0}) is None

    def test_expires_at_in_seconds(self):
        """expiresAt already in seconds (< 1e12) should be kept as-is."""
        ts = time.time() + 3600
        raw = {"accessToken": "tok", "expiresAt": ts}
        result = _parse_oauth(raw)
        assert result is not None
        assert abs(result["expires_at"] - ts) < 1.0


# -- read_claude_code_credentials tests --


class TestReadCredentials:
    def test_keychain_success(self):
        fake_keychain = json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "keychain-token",
                    "refreshToken": "keychain-refresh",
                    "expiresAt": int((time.time() + 3600) * 1000),
                    "subscriptionType": "pro",
                }
            }
        )
        with patch(
            "core.gateway.auth.claude_code_oauth.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = fake_keychain
            with patch("core.gateway.auth.claude_code_oauth.sys") as mock_sys:
                mock_sys.platform = "darwin"
                result = read_claude_code_credentials(force_refresh=True)

        assert result is not None
        assert result["access_token"] == "keychain-token"
        assert result["subscription_type"] == "pro"

    def test_file_fallback(self, tmp_path: Path):
        cred_data = {
            "claudeAiOauth": {
                "accessToken": "file-token",
                "expiresAt": int((time.time() + 3600) * 1000),
            }
        }
        with (
            patch("core.gateway.auth.claude_code_oauth.sys") as mock_sys,
            patch(
                "core.gateway.auth.claude_code_oauth._read_from_keychain",
                return_value=None,
            ),
            patch(
                "core.gateway.auth.claude_code_oauth._read_from_file",
                return_value=cred_data["claudeAiOauth"],
            ),
        ):
            mock_sys.platform = "darwin"
            result = read_claude_code_credentials(force_refresh=True)

        assert result is not None
        assert result["access_token"] == "file-token"

    def test_no_credentials(self):
        with (
            patch("core.gateway.auth.claude_code_oauth.sys") as mock_sys,
            patch(
                "core.gateway.auth.claude_code_oauth._read_from_keychain",
                return_value=None,
            ),
            patch(
                "core.gateway.auth.claude_code_oauth._read_from_file",
                return_value=None,
            ),
        ):
            mock_sys.platform = "darwin"
            result = read_claude_code_credentials(force_refresh=True)
        assert result is None

    def test_cache_ttl(self):
        """Second call within TTL returns cached value without re-reading."""
        fake_oauth = {
            "accessToken": "cached-tok",
            "expiresAt": int((time.time() + 3600) * 1000),
        }
        with (
            patch("core.gateway.auth.claude_code_oauth.sys") as mock_sys,
            patch(
                "core.gateway.auth.claude_code_oauth._read_from_keychain",
                return_value=fake_oauth,
            ),
        ):
            mock_sys.platform = "darwin"
            r1 = read_claude_code_credentials(force_refresh=True)

        # Second call — keychain not called again
        with patch(
            "core.gateway.auth.claude_code_oauth._read_from_keychain"
        ) as mock_kc:
            r2 = read_claude_code_credentials()

        assert r1 == r2
        mock_kc.assert_not_called()


# -- refresh_claude_code_token tests --


class TestRefreshToken:
    def test_refresh_updates_profile(self):
        from core.gateway.auth.profiles import AuthProfile, CredentialType

        profile = AuthProfile(
            name="anthropic:claude-code",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="old-token",
            expires_at=time.time() - 100,
            managed_by="claude-code",
        )
        new_creds: ClaudeCodeCredentials = {
            "access_token": "new-token",
            "expires_at": time.time() + 3600,
        }
        with patch(
            "core.gateway.auth.claude_code_oauth.read_claude_code_credentials",
            return_value=new_creds,
        ):
            updated = refresh_claude_code_token(profile)

        assert updated is True
        assert profile.key == "new-token"

    def test_refresh_no_change(self):
        from core.gateway.auth.profiles import AuthProfile, CredentialType

        profile = AuthProfile(
            name="anthropic:claude-code",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="same-token",
            managed_by="claude-code",
        )
        creds: ClaudeCodeCredentials = {
            "access_token": "same-token",
            "expires_at": time.time() + 3600,
        }
        with patch(
            "core.gateway.auth.claude_code_oauth.read_claude_code_credentials",
            return_value=creds,
        ):
            updated = refresh_claude_code_token(profile)

        assert updated is False

    def test_refresh_no_credentials(self):
        from core.gateway.auth.profiles import AuthProfile, CredentialType

        profile = AuthProfile(
            name="anthropic:claude-code",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key="old-token",
            managed_by="claude-code",
        )
        with patch(
            "core.gateway.auth.claude_code_oauth.read_claude_code_credentials",
            return_value=None,
        ):
            updated = refresh_claude_code_token(profile)

        assert updated is False
        assert profile.key == "old-token"  # unchanged
