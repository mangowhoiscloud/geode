"""Tests for OAuth login flow + auth.toml SOT (v0.50.2 onwards).

The legacy ``~/.geode/auth.json`` was retired in v0.50.2; these tests
exercise the new auth.toml-backed save/load path through the public
``_save_auth_store`` / ``_load_auth_store`` helpers (kept as
backwards-compatible shims for ``get_auth_status`` etc).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.auth.oauth_login import (
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

        with patch("core.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None):
            statuses = get_auth_status()

        assert len(statuses) >= 1
        # The first status row corresponds to our openai entry
        openai_rows = [s for s in statuses if s["provider"] == "openai"]
        assert openai_rows
        assert openai_rows[0]["email"] == "test@example.com"
        assert openai_rows[0]["status"] == "active"

    def test_status_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("core.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "empty.json")

        with patch("core.auth.codex_cli_oauth.read_codex_cli_credentials", return_value=None):
            statuses = get_auth_status()

        assert statuses == []


class TestCmdLogin:
    def test_login_no_args(self):
        from core.cli.commands import cmd_login

        # Should not raise, just print help
        cmd_login("")

    def test_login_status(self, tmp_path: Path, monkeypatch):
        from core.cli.commands import cmd_login

        monkeypatch.setattr("core.auth.oauth_login.AUTH_STORE_PATH", tmp_path / "a.json")
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

    Signature is bogus — ``_decode_jwt_claims`` does no verification.
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
    """`_decode_jwt_claims` + `_plan_type_from_token` — regression for the
    v0.95.x plan tier reconciliation path."""

    def test_decode_valid_jwt(self):
        from core.auth.oauth_login import _decode_jwt_claims

        token = _build_fake_jwt(
            {
                "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
                "https://api.openai.com/profile": {"email": "u@example.com"},
                "exp": 9999999999,
            }
        )
        claims = _decode_jwt_claims(token)
        assert claims["exp"] == 9999999999
        assert claims["https://api.openai.com/auth"]["chatgpt_plan_type"] == "pro"

    def test_decode_malformed_returns_empty(self):
        from core.auth.oauth_login import _decode_jwt_claims

        # Fewer than 2 dot-separated parts → early return.
        assert _decode_jwt_claims("not-a-jwt") == {}
        assert _decode_jwt_claims("") == {}
        # 2+ parts but the payload section is not valid base64+JSON.
        assert _decode_jwt_claims("garbage.payload.sig") == {}
        assert _decode_jwt_claims("only.one") == {}

    def test_plan_type_extraction(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt(
            {"https://api.openai.com/auth": {"chatgpt_plan_type": "max"}}
        )
        assert _plan_type_from_token(token) == "max"

    def test_plan_type_missing_claim(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt({"some_other_claim": "x"})
        assert _plan_type_from_token(token) == ""


class TestPlanTierReconcile:
    """`reconcile_plan_tier_from_stored_jwt` — drift detection + update."""

    def test_no_drift_returns_none(self, tmp_path: Path, monkeypatch):
        from core.auth.oauth_login import reconcile_plan_tier_from_stored_jwt
        from core.auth.plan_registry import get_plan_registry, reset_plan_registry
        from core.auth.plans import Plan, PlanKind
        from core.auth.profiles import AuthProfile, CredentialType
        from core.wiring import container as container_mod

        _isolate(tmp_path, monkeypatch)
        reset_plan_registry()

        registry = get_plan_registry()
        registry.add(
            Plan(
                id="openai-codex-geode",
                provider="openai-codex",
                kind=PlanKind.OAUTH_BORROWED,
                display_name="OpenAI Codex (GEODE OAuth)",
                base_url="https://chatgpt.com/backend-api/codex",
                subscription_tier="prolite",
            )
        )

        from core.auth.profiles import ProfileStore

        store = ProfileStore()
        token = _build_fake_jwt(
            {"https://api.openai.com/auth": {"chatgpt_plan_type": "prolite"}}
        )
        store.add(
            AuthProfile(
                name="openai-codex-geode:user",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key=token,
                plan_id="openai-codex-geode",
            )
        )
        monkeypatch.setattr(container_mod, "ensure_profile_store", lambda: store)

        assert reconcile_plan_tier_from_stored_jwt() is None

    def test_drift_reconciles_and_returns_pair(self, tmp_path: Path, monkeypatch):
        from core.auth.oauth_login import reconcile_plan_tier_from_stored_jwt
        from core.auth.plan_registry import get_plan_registry, reset_plan_registry
        from core.auth.plans import Plan, PlanKind
        from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
        from core.wiring import container as container_mod

        _isolate(tmp_path, monkeypatch)
        reset_plan_registry()

        registry = get_plan_registry()
        registry.add(
            Plan(
                id="openai-codex-geode",
                provider="openai-codex",
                kind=PlanKind.OAUTH_BORROWED,
                display_name="OpenAI Codex (GEODE OAuth)",
                base_url="https://chatgpt.com/backend-api/codex",
                subscription_tier="plus",  # stale
            )
        )

        store = ProfileStore()
        token = _build_fake_jwt(
            {"https://api.openai.com/auth": {"chatgpt_plan_type": "max"}}
        )
        store.add(
            AuthProfile(
                name="openai-codex-geode:user",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key=token,
                plan_id="openai-codex-geode",
                metadata={"plan_type": "plus"},
            )
        )
        monkeypatch.setattr(container_mod, "ensure_profile_store", lambda: store)

        result = reconcile_plan_tier_from_stored_jwt()
        assert result == ("plus", "max")
        plan = get_plan_registry().get("openai-codex-geode")
        assert plan is not None
        assert plan.subscription_tier == "max"
        # Profile metadata also updated
        profile = store.get("openai-codex-geode:user")
        assert profile is not None
        assert profile.metadata["plan_type"] == "max"

    def test_no_profile_returns_none(self, tmp_path: Path, monkeypatch):
        from core.auth.oauth_login import reconcile_plan_tier_from_stored_jwt
        from core.auth.plan_registry import reset_plan_registry
        from core.auth.profiles import ProfileStore
        from core.wiring import container as container_mod

        _isolate(tmp_path, monkeypatch)
        reset_plan_registry()

        monkeypatch.setattr(container_mod, "ensure_profile_store", lambda: ProfileStore())

        assert reconcile_plan_tier_from_stored_jwt() is None
