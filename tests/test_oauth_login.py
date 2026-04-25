"""Tests for OAuth login flow + auth.toml SOT (v0.50.2 onwards).

The legacy ``~/.geode/auth.json`` was retired in v0.50.2; these tests
exercise the new auth.toml-backed save/load path through the public
``_save_auth_store`` / ``_load_auth_store`` helpers (kept as
backwards-compatible shims for ``get_auth_status`` etc).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.gateway.auth.oauth_login import (
    _load_auth_store,
    _save_auth_store,
    get_auth_status,
    read_geode_openai_credentials,
)


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    """Point GEODE_AUTH_TOML at a temp file + isolate the legacy path."""
    toml_path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))
    monkeypatch.setattr(
        "core.gateway.auth.oauth_login.LEGACY_AUTH_STORE_PATH",
        tmp_path / "auth.json",
    )
    return toml_path


class TestAuthStore:
    def test_load_empty(self, tmp_path: Path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        store = _load_auth_store()
        assert store["version"] == 1
        assert store["providers"] == {}

    def test_save_and_load_round_trip(self, tmp_path: Path, monkeypatch):
        _isolate(tmp_path, monkeypatch)

        _save_auth_store({"version": 1, "providers": {"openai": {"access_token": "test-rt"}}})
        loaded = _load_auth_store()
        assert loaded["providers"]["openai"]["access_token"] == "test-rt"

    def test_save_routes_through_authtoml(self, tmp_path: Path, monkeypatch):
        toml_path = _isolate(tmp_path, monkeypatch)
        _save_auth_store({"version": 1, "providers": {"openai": {"access_token": "abc-perm"}}})
        # auth.toml is the new SOT — written with 0600 perms (auth_toml.save_auth_toml).
        assert toml_path.exists()
        assert oct(toml_path.stat().st_mode)[-3:] == "600"


class TestReadCredentials:
    def test_read_valid(self, tmp_path: Path, monkeypatch):
        import time

        _isolate(tmp_path, monkeypatch)
        _save_auth_store(
            {
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
        )

        creds = read_geode_openai_credentials()
        assert creds is not None
        assert creds["access_token"] == "test-token"

    def test_read_expired(self, tmp_path: Path, monkeypatch):
        import time

        _isolate(tmp_path, monkeypatch)
        _save_auth_store(
            {
                "version": 1,
                "providers": {
                    "openai": {
                        "access_token": "expired-token",
                        "expires_at": time.time() - 100,
                    }
                },
            }
        )
        assert read_geode_openai_credentials() is None

    def test_read_missing(self, tmp_path: Path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        assert read_geode_openai_credentials() is None


class TestAuthStatus:
    def test_status_with_credentials(self, tmp_path: Path, monkeypatch):
        import time

        _isolate(tmp_path, monkeypatch)
        _save_auth_store(
            {
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
        )

        with patch(
            "core.gateway.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None
        ):
            statuses = get_auth_status()

        assert len(statuses) >= 1
        # The first status row corresponds to our openai entry
        openai_rows = [s for s in statuses if s["provider"] == "openai"]
        assert openai_rows
        assert openai_rows[0]["email"] == "test@example.com"
        assert openai_rows[0]["status"] == "active"

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
