"""Phase 4 — auth.toml persistence + .env migration tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.gateway.auth.auth_toml import (
    auth_toml_path,
    load_auth_toml,
    migrate_env_to_toml,
    save_auth_toml,
)
from core.gateway.auth.plan_registry import (
    get_plan_registry,
    reset_plan_registry,
)
from core.gateway.auth.plans import GLM_CODING_TIERS
from core.gateway.auth.profiles import AuthProfile, CredentialType


def _fresh_path() -> Path:
    fd, name = tempfile.mkstemp(suffix=".toml")
    os.close(fd)
    p = Path(name)
    p.unlink()  # save_auth_toml will recreate
    return p


def _reset_state() -> None:
    from core.runtime_wiring import infra as _infra

    _infra._profile_store = None
    _infra._profile_rotator = None
    reset_plan_registry()


class TestRoundtrip:
    def test_save_then_load_preserves_plan(self) -> None:
        _reset_state()
        from core.runtime_wiring.infra import ensure_profile_store

        store = ensure_profile_store()
        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)
        store.add(
            AuthProfile(
                name="glm-coding-lite:user",
                provider="glm-coding",
                credential_type=CredentialType.API_KEY,
                key="zai-test-key",
                plan_id=plan.id,
            )
        )
        registry.set_routing("glm-5.1", [plan.id])

        path = _fresh_path()
        save_auth_toml(path=path)
        assert path.exists()
        text = path.read_text()
        assert "glm-coding-lite" in text
        assert "zai-test-key" in text
        assert "[plans.quota]" in text
        assert "max_calls = 80" in text

        # Reload into a fresh state
        _reset_state()
        load_auth_toml(path=path)
        registry2 = get_plan_registry()
        assert registry2.get("glm-coding-lite") is not None
        assert registry2.get_routing("glm-5.1") == ["glm-coding-lite"]
        store2 = ensure_profile_store()
        prof = next(
            (p for p in store2.list_all() if p.name == "glm-coding-lite:user"), None
        )
        assert prof is not None
        assert prof.key == "zai-test-key"
        path.unlink()

    def test_managed_profiles_are_not_persisted(self) -> None:
        _reset_state()
        from core.runtime_wiring.infra import ensure_profile_store

        store = ensure_profile_store()
        store.add(
            AuthProfile(
                name="openai-codex:codex-cli",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key="oauth-token-borrowed",
                managed_by="codex-cli",
            )
        )
        path = _fresh_path()
        save_auth_toml(path=path)
        text = path.read_text()
        assert "oauth-token-borrowed" not in text
        path.unlink()


class TestMigrateEnvToToml:
    def test_migration_seeds_payg_plans_for_env_keys(self) -> None:
        _reset_state()
        from unittest.mock import patch

        path = _fresh_path()
        with patch("core.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_settings.openai_api_key = "sk-proj-test"
            mock_settings.zai_api_key = ""

            seeded = migrate_env_to_toml(path=path)
            assert seeded == 2
            assert path.exists()

            registry = get_plan_registry()
            ids = {p.id for p in registry.list_all()}
            assert "anthropic-payg" in ids
            assert "openai-payg" in ids
            assert "glm-payg" not in ids
        path.unlink()

    def test_migration_is_idempotent(self) -> None:
        _reset_state()
        from unittest.mock import patch

        path = _fresh_path()
        with patch("core.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-test"
            mock_settings.openai_api_key = ""
            mock_settings.zai_api_key = ""

            migrate_env_to_toml(path=path)

            # Second call sees the file exists → just loads, doesn't double-seed
            _reset_state()
            seeded = migrate_env_to_toml(path=path)
            assert seeded == 0

            registry = get_plan_registry()
            assert sum(1 for p in registry.list_all() if p.id == "anthropic-payg") == 1
        path.unlink()


class TestEnvOverride:
    def test_geode_auth_toml_env_var_redirects_path(self) -> None:
        custom = _fresh_path()
        old = os.environ.get("GEODE_AUTH_TOML")
        try:
            os.environ["GEODE_AUTH_TOML"] = str(custom)
            assert auth_toml_path() == custom
        finally:
            if old is None:
                os.environ.pop("GEODE_AUTH_TOML", None)
            else:
                os.environ["GEODE_AUTH_TOML"] = old
