"""Tests for /login command and OAuth login flow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from core.gateway.auth.oauth_login import (
    _load_auth_store,
    _save_auth_store,
    get_auth_status,
    read_geode_openai_credentials,
)


class TestAuthStore:
    def test_load_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "auth.json")
        store = _load_auth_store()
        assert store["version"] == 1
        assert store["providers"] == {}

    def test_save_and_load(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "auth.json"
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", path)

        data = {"version": 1, "providers": {"openai": {"access_token": "test"}}}
        _save_auth_store(data)

        assert path.exists()
        loaded = _load_auth_store()
        assert loaded["providers"]["openai"]["access_token"] == "test"

    def test_save_permissions(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "auth.json"
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", path)
        _save_auth_store({"version": 1, "providers": {}})
        assert oct(path.stat().st_mode)[-3:] == "600"


class TestReadCredentials:
    def test_read_valid(self, tmp_path: Path, monkeypatch):
        import time

        path = tmp_path / "auth.json"
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", path)

        data = {
            "version": 1,
            "providers": {
                "openai": {
                    "access_token": "test-token",
                    "refresh_token": "rt-test",
                    "expires_at": time.time() + 3600,
                    "account_id": "acc-123",
                }
            },
        }
        path.write_text(json.dumps(data))

        creds = read_geode_openai_credentials()
        assert creds is not None
        assert creds["access_token"] == "test-token"

    def test_read_expired(self, tmp_path: Path, monkeypatch):
        import time

        path = tmp_path / "auth.json"
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", path)

        data = {
            "version": 1,
            "providers": {
                "openai": {
                    "access_token": "expired-token",
                    "expires_at": time.time() - 100,
                }
            },
        }
        path.write_text(json.dumps(data))

        creds = read_geode_openai_credentials()
        assert creds is None

    def test_read_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "nope.json")
        assert read_geode_openai_credentials() is None


class TestAuthStatus:
    def test_status_with_credentials(self, tmp_path: Path, monkeypatch):
        import time

        path = tmp_path / "auth.json"
        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", path)

        data = {
            "version": 1,
            "providers": {
                "openai": {
                    "access_token": "tok",
                    "email": "test@example.com",
                    "plan_type": "plus",
                    "source": "geode-device-code",
                    "expires_at": time.time() + 7200,
                }
            },
        }
        path.write_text(json.dumps(data))

        with patch(
            "core.gateway.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None
        ):
            statuses = get_auth_status()

        assert len(statuses) >= 1
        assert statuses[0]["provider"] == "openai"
        assert statuses[0]["email"] == "test@example.com"
        assert statuses[0]["status"] == "active"

    def test_status_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "core.gateway.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "empty.json"
        )

        with patch(
            "core.gateway.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None
        ):
            statuses = get_auth_status()

        assert statuses == []


class TestCmdLogin:
    def test_login_no_args(self):
        from core.cli.commands import cmd_login

        # Should not raise, just print help
        cmd_login("")

    def test_login_status(self, tmp_path: Path, monkeypatch):
        from core.cli.commands import cmd_login

        monkeypatch.setattr("core.gateway.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "a.json")
        cmd_login("status")  # Should not raise

    def test_login_unknown_provider(self):
        from core.cli.commands import cmd_login

        cmd_login("unknown_provider")  # Should print error, not raise

    def test_login_in_command_map(self):
        from core.cli.commands import COMMAND_MAP

        assert "/login" in COMMAND_MAP
        assert COMMAND_MAP["/login"] == "login"
