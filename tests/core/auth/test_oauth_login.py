"""Tests for OAuth login flow + auth.toml SOT (v0.50.2 onwards).

The legacy ``~/.geode/auth.json`` was retired in v0.50.2; these tests
exercise the new auth.toml-backed save/load path through the
``_save_auth_store`` / ``_load_auth_store`` helpers.
"""

from __future__ import annotations

from pathlib import Path

from core.auth.oauth_login import (
    _load_auth_store,
    _save_auth_store,
    read_geode_openai_credentials,
)


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    """Point GEODE_AUTH_TOML at a temp file + isolate the legacy path."""
    toml_path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))
    monkeypatch.setattr(
        "core.auth.oauth_login.LEGACY_AUTH_STORE_PATH",
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


class TestCmdLogin:
    def test_login_no_args(self):
        from core.cli.commands import cmd_login

        # Should not raise, just print help
        cmd_login("")

    def test_login_status(self, tmp_path: Path, monkeypatch):
        from core.cli.commands import cmd_login

        _isolate(tmp_path, monkeypatch)
        cmd_login("status")  # Should not raise

    def test_login_unknown_provider(self):
        from core.cli.commands import cmd_login

        cmd_login("unknown_provider")  # Should print error, not raise

    def test_login_in_command_map(self):
        from core.cli.commands import COMMAND_MAP

        assert "/login" in COMMAND_MAP
        assert COMMAND_MAP["/login"] == "login"


def _build_fake_jwt(claims: dict) -> str:
    """Construct a JWT-shaped string with ``claims`` as the payload.

    Signature is bogus — ``decode_jwt_claims`` does no verification.
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = (
        base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{body}.signature"


class TestJWTDecode:
    """`decode_jwt_claims` + `_plan_type_from_token` — regression for the
    v0.95.x plan tier reconciliation path."""

    def test_decode_valid_jwt(self):
        from core.auth.jwt_claims import decode_jwt_claims

        token = _build_fake_jwt(
            {
                "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
                "https://api.openai.com/profile": {"email": "u@example.com"},
                "exp": 9999999999,
            }
        )
        claims = decode_jwt_claims(token)
        assert claims["exp"] == 9999999999
        assert claims["https://api.openai.com/auth"]["chatgpt_plan_type"] == "pro"

    def test_decode_malformed_returns_empty(self):
        from core.auth.jwt_claims import decode_jwt_claims

        # Fewer than 2 dot-separated parts → early return.
        assert decode_jwt_claims("not-a-jwt") == {}
        assert decode_jwt_claims("") == {}
        # 2+ parts but the payload section is not valid base64+JSON.
        assert decode_jwt_claims("garbage.payload.sig") == {}
        assert decode_jwt_claims("only.one") == {}

    def test_plan_type_extraction(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "max"}})
        assert _plan_type_from_token(token) == "max"

    def test_plan_type_missing_claim(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt({"some_other_claim": "x"})
        assert _plan_type_from_token(token) == ""


def test_persisting_new_tokens_records_their_plan_tier(tmp_path: Path, monkeypatch) -> None:
    from core.auth.oauth_login import _GEODE_OPENAI_PLAN_ID, _persist_oauth_to_authtoml
    from core.llm.strategies.plan_registry import get_plan_registry, reset_plan_registry

    _isolate(tmp_path, monkeypatch)
    _persist_oauth_to_authtoml({"access_token": "first-token", "plan_type": "plus"})
    _persist_oauth_to_authtoml({"access_token": "second-token", "plan_type": "pro"})
    assert get_plan_registry().get(_GEODE_OPENAI_PLAN_ID).subscription_tier == "pro"

    reset_plan_registry()
    from core.auth.auth_toml import load_auth_toml

    assert load_auth_toml()
    assert get_plan_registry().get(_GEODE_OPENAI_PLAN_ID).subscription_tier == "pro"
