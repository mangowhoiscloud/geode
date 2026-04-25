"""v0.50.2 — legacy auth.json → auth.toml one-shot migration tests."""

from __future__ import annotations

import json
from pathlib import Path


class TestLegacyMigration:
    def test_migration_consumes_legacy_file_and_writes_toml(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        legacy = tmp_path / "auth.json"
        legacy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "providers": {
                        "openai": {
                            "access_token": "eyJ-test-access-token",
                            "refresh_token": "eyJ-test-refresh",
                            "expires_at": 9_999_999_999,
                            "account_id": "acct-test",
                            "email": "user@test.example",
                            "plan_type": "plus",
                            "source": "geode-device-code",
                        }
                    },
                }
            )
        )
        toml_path = tmp_path / "auth.toml"
        monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))
        monkeypatch.setattr("core.gateway.auth.oauth_login.LEGACY_AUTH_STORE_PATH", legacy)

        from core.gateway.auth.oauth_login import _load_auth_store

        view = _load_auth_store()

        # 1. Returned view still presents the openai entry for legacy callers
        assert view["providers"]["openai"]["access_token"] == "eyJ-test-access-token"
        # 2. Legacy file is gone (renamed to *.migrated.bak)
        assert not legacy.exists()
        assert (tmp_path / "auth.json.migrated.bak").exists()
        # 3. New SOT TOML now contains the OAuth Plan + Profile
        assert toml_path.exists()
        text = toml_path.read_text()
        assert "openai-codex-geode" in text
        assert "eyJ-test-access-token" in text
        assert 'kind = "oauth_borrowed"' in text

    def test_no_legacy_file_returns_empty(self, tmp_path: Path, monkeypatch) -> None:
        legacy = tmp_path / "auth.json"  # never created
        toml_path = tmp_path / "auth.toml"
        monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))
        monkeypatch.setattr("core.gateway.auth.oauth_login.LEGACY_AUTH_STORE_PATH", legacy)

        from core.gateway.auth.oauth_login import _load_auth_store

        view = _load_auth_store()
        assert view["providers"] == {}

    def test_migration_is_idempotent_after_second_call(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        legacy = tmp_path / "auth.json"
        legacy.write_text(
            json.dumps(
                {
                    "providers": {
                        "openai": {
                            "access_token": "abc",
                            "refresh_token": "",
                            "expires_at": 9_999_999_999,
                        }
                    }
                }
            )
        )
        toml_path = tmp_path / "auth.toml"
        monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))
        monkeypatch.setattr("core.gateway.auth.oauth_login.LEGACY_AUTH_STORE_PATH", legacy)

        from core.gateway.auth.oauth_login import _load_auth_store

        _load_auth_store()
        # Second call: legacy file gone, view rebuilt from auth.toml
        view = _load_auth_store()
        assert view["providers"]["openai"]["access_token"] == "abc"


class TestSaveRoutesThroughAuthToml:
    def test_save_auth_store_persists_oauth_to_toml(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        toml_path = tmp_path / "auth.toml"
        monkeypatch.setenv("GEODE_AUTH_TOML", str(toml_path))

        from core.gateway.auth.oauth_login import _save_auth_store

        _save_auth_store(
            {
                "version": 1,
                "providers": {
                    "openai": {
                        "access_token": "new-access-789",
                        "refresh_token": "rt-456",
                        "expires_at": 9_999_999_999,
                        "account_id": "acct-x",
                        "email": "x@y.z",
                        "plan_type": "plus",
                    }
                },
            }
        )
        text = toml_path.read_text()
        assert "openai-codex-geode" in text
        assert "new-access-789" in text
