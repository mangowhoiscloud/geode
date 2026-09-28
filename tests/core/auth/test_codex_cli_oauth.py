"""Tests for Codex CLI OAuth token reader."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from core.auth.codex_cli_oauth import (
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
    def test_codex_home_override_survives_an_isolated_home(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        codex_home = tmp_path / "codex"
        codex_home.mkdir()
        codex_home.joinpath("auth.json").write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "override-token",
                        "refresh_token": "override-refresh",
                    }
                }
            ),
            encoding="utf-8",
        )
        isolated_home = tmp_path / "isolated"
        isolated_home.mkdir()
        monkeypatch.setenv("HOME", str(isolated_home))
        monkeypatch.setenv("CODEX_HOME", str(codex_home))

        result = read_codex_cli_credentials(force_refresh=True)

        assert result is not None
        assert result["access_token"] == "override-token"

    def test_file_read_success(self, tmp_path, monkeypatch):
        import core.auth.codex_cli_oauth as module

        auth = tmp_path / "auth.json"
        auth.write_text("{}")
        monkeypatch.setattr(module, "_cache", module.CredentialCache(auth))
        fake_data = {
            "tokens": {
                "access_token": "file-token",
                "refresh_token": "file-refresh",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        with patch(
            "core.auth.codex_cli_oauth._read_from_file",
            return_value=fake_data,
        ):
            result = read_codex_cli_credentials(force_refresh=True)

        assert result is not None
        assert result["access_token"] == "file-token"

    def test_no_file(self):
        with patch(
            "core.auth.codex_cli_oauth._read_from_file",
            return_value=None,
        ):
            result = read_codex_cli_credentials(force_refresh=True)
        assert result is None

    def test_cache_hit(self, tmp_path, monkeypatch):
        import core.auth.codex_cli_oauth as module

        auth = tmp_path / "auth.json"
        auth.write_text("{}")
        monkeypatch.setattr(module, "codex_auth_path", lambda: auth)
        monkeypatch.setattr(module, "_cache", module.CredentialCache(lambda: auth))
        fake_data = {
            "tokens": {
                "access_token": "cached",
                "refresh_token": "rt",
            },
            "last_refresh": "2026-04-01T12:00:00Z",
        }
        with patch(
            "core.auth.codex_cli_oauth._read_from_file",
            return_value=fake_data,
        ):
            r1 = read_codex_cli_credentials(force_refresh=True)

        with patch(
            "core.auth.codex_cli_oauth._read_from_file",
        ) as mock_read:
            r2 = read_codex_cli_credentials()

        assert r1 == r2
        mock_read.assert_not_called()


class TestRefreshCodexToken:
    def test_refresh_updates(self):
        from core.auth.profiles import AuthProfile, CredentialType

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
            "core.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=new_creds,
        ):
            updated = refresh_codex_cli_token(profile)

        assert updated is True
        assert profile.key == "new-token"

    def test_refresh_no_change(self):
        from core.auth.profiles import AuthProfile, CredentialType

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
            "core.auth.codex_cli_oauth.read_codex_cli_credentials",
            return_value=creds,
        ):
            assert refresh_codex_cli_token(profile) is False


def test_deleted_external_file_invalidates_cache(tmp_path, monkeypatch) -> None:
    import core.auth.codex_cli_oauth as module

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "old", "refresh_token": "r"}}))
    monkeypatch.setattr(module, "_cache", module.CredentialCache(lambda: auth))
    monkeypatch.setattr(module, "codex_auth_path", lambda: auth)
    assert module.read_codex_cli_credentials()["access_token"] == "old"
    auth.unlink()
    assert module.read_codex_cli_credentials() is None


def test_concurrent_reads_publish_in_order_and_invalidation_waits(tmp_path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from core.auth.credential_cache import CredentialCache

    auth = tmp_path / "auth.json"
    auth.write_text("old")
    cache = CredentialCache(auth)
    read_started, finish_read, second_started = Event(), Event(), Event()

    def slow_read():
        value = auth.read_text()
        read_started.set()
        assert finish_read.wait(5)
        return value

    def fresh_read():
        second_started.set()
        return cache.read(auth.read_text, force_refresh=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(cache.read, slow_read)
        assert read_started.wait(5)
        auth.write_text("new")
        new = pool.submit(fresh_read)
        assert second_started.wait(5)
        finish_read.set()
        assert old.result(5) == "new"
        assert new.result(5) == "new"
    assert cache.read(lambda: pytest.fail("fresh snapshot should be cached")) == "new"

    read_started.clear()
    finish_read.clear()
    second_started.clear()

    def invalidate():
        second_started.set()
        cache.invalidate()

    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(cache.read, slow_read, force_refresh=True)
        assert read_started.wait(5)
        invalidation = pool.submit(invalidate)
        assert second_started.wait(5)
        finish_read.set()
        old.result(5)
        invalidation.result(5)
    assert cache.read(lambda: "reread") == "reread"


def test_stale_refresh_does_not_overwrite_changed_profile() -> None:
    from core.auth.credential_cache import refresh_managed_token
    from core.auth.profiles import AuthProfile, CredentialType

    profile = AuthProfile("external", "openai-codex", CredentialType.OAUTH, key="old")

    def read(**kwargs):
        profile.key = "newer"
        return {"access_token": "stale", "refresh_token": "old-refresh"}

    assert refresh_managed_token("Codex CLI", read, profile) is False
    assert profile.key == "newer"


@pytest.mark.parametrize("change", ["delete", "replace-twice"])
def test_unstable_file_never_returns_old_credentials(tmp_path, change):
    from core.auth.credential_cache import CredentialCache

    auth = tmp_path / "auth.json"
    auth.write_text("old")
    cache = CredentialCache(auth)
    calls = 0

    def read():
        nonlocal calls
        value = auth.read_text()
        calls += 1
        if change == "delete":
            auth.unlink()
        else:
            auth.write_text("new" * (calls + 1))
        return value

    assert cache.read(read) is None
    assert calls <= 2


def test_unchanged_external_snapshot_preserves_profile_and_health(monkeypatch):
    from core.auth.codex_cli_oauth import sync_codex_cli_profile
    from core.auth.profiles import ProfileStore

    store = ProfileStore()
    creds = {"access_token": "same", "refresh_token": "r", "expires_at": 9999999999}
    monkeypatch.setattr("core.auth.codex_cli_oauth.read_codex_cli_credentials", lambda **_: creds)
    sync_codex_cli_profile(store, force_refresh=True)
    profile = store.get("openai-codex:codex-cli")
    profile.error_count = 2
    profile.cooldown_until = time.time() + 60
    sync_codex_cli_profile(store, force_refresh=True)
    assert store.get(profile.name) is profile
    assert profile.error_count == 2
    assert profile.is_cooling_down
