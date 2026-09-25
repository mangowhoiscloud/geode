"""Phase 3 — /login unified command UX tests.

Smoke-tests for the subcommand router and the side effects on
ProfileStore + PlanRegistry. UI rendering is covered by snapshot tests
of the dashboard string output.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.commands import cmd_login
from core.llm.strategies.plan_registry import (
    get_plan_registry,
    reset_plan_registry,
)
from core.llm.strategies.plans import GLM_CODING_TIERS, default_plan_for_payg


@pytest.fixture(autouse=True)
def _scrub_real_provider_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate the machine's real credentials from the auth/profile store.

    ``build_auth`` seeds ``<provider>-payg:env`` profiles from
    ``settings.{openai,anthropic,zai}_api_key`` (``migrate_env_to_toml`` +
    the legacy-provider loop in ``core.wiring.container``). ``Settings``
    resolves those from the process env AND an ``env_file`` fallback
    (``.env`` + ``~/.geode/.env``), so on a developer box with real keys
    present the store gains a real-key profile the test never created —
    ``test_set_key_updates_existing_plan`` then reads that leaked key
    instead of the one it bound. CI passes only because a clean HOME has
    no keys.

    Empty-string values (not ``delenv``) are required: pydantic prefers
    the env var over the ``env_file``, so an empty var shadows the file,
    whereas ``delenv`` lets pydantic fall back to ``~/.geode/.env``.
    Resetting the cached ``Settings`` singleton forces a re-read with the
    scrubbed values before ``build_auth`` runs.
    """
    import core.config as cfg

    for _var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ZAI_API_KEY"):
        monkeypatch.setenv(_var, "")
    monkeypatch.setenv("GEODE_AUTH_TOML", str(tmp_path / "auth.toml"))
    monkeypatch.setattr(cfg, "_settings_instance", None, raising=False)
    settings = cfg.settings
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "zai_api_key", "", raising=False)


def _reset_state() -> None:
    from core.wiring import container as infra

    infra._profile_store = None
    infra._profile_rotator = None
    reset_plan_registry()


class TestSubcommandRouter:
    def test_bare_login_renders_dashboard(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("")
            assert mock_console.print.called

    def test_help_subcommand(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("help")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "/login add" in text
            assert "/login openai" in text
            removed_oauth_shape = "/login " + "oauth"
            assert removed_oauth_shape not in text

    def test_provider_parameter_dispatches_oauth(self) -> None:
        _reset_state()
        with patch("core.cli.commands.login._login_oauth") as mock_oauth:
            cmd_login("openai")
            mock_oauth.assert_called_once_with("openai")

    def test_anthropic_login_prompts_for_api_key(self) -> None:
        _reset_state()
        with patch("core.cli.commands.login._login_anthropic_api_key") as login_api_key:
            cmd_login("anthropic")
        login_api_key.assert_called_once_with()

    def test_anthropic_login_persists_the_live_adapter_key(self) -> None:
        _reset_state()
        key = "sk-ant-api03-test-key-1234567890"
        with (
            patch("getpass.getpass", return_value=key),
            patch("core.cli.commands.console"),
            patch("core.cli.commands._upsert_env") as upsert_env,
            patch("core.cli.commands.login._persist_credential_source") as persist_source,
            patch("core.llm.adapters.registry.invalidate_provider_clients") as invalidate,
        ):
            cmd_login("anthropic")

        from core.config import settings

        assert settings.anthropic_api_key == key
        upsert_env.assert_called_once_with("ANTHROPIC_API_KEY", key)
        persist_source.assert_called_once_with("anthropic", "api_key")
        invalidate.assert_called_once_with("anthropic")

    def test_unknown_subcommand_warns(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("nonsense")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown" in text


class TestSetKeyAndUse:
    def test_legacy_key_detects_openrouter_before_generic_openai_prefix(self) -> None:
        from core.cli.commands import cmd_key
        from core.config import settings

        key = "sk-or-v1-abcdefghij1234567890"
        with (
            patch("core.cli.commands.console"),
            patch("core.cli.commands._upsert_env") as upsert,
            patch("core.cli.commands._seed_payg_plan_from_key") as seed,
        ):
            assert cmd_key(key) is True

        assert settings.openrouter_api_key == key
        upsert.assert_called_once_with("OPENROUTER_API_KEY", key)
        seed.assert_called_once_with("openrouter", key)

    def test_set_key_updates_existing_plan(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = default_plan_for_payg("openai", "")
        registry.add(plan)
        with patch("core.cli.commands.login.clear_dry_run_opt_in") as clear_opt_in:
            cmd_login(f"set-key {plan.id} sk-fresh-key-1234567890")
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        bound = [p for p in store.list_all() if p.plan_id == plan.id]
        assert bound and bound[0].key == "sk-fresh-key-1234567890"
        clear_opt_in.assert_called_once_with()
        borrowed = bound[0]
        cmd_login(f"set-key {plan.id} synthetic-replacement")
        assert borrowed.key == "sk-fresh-key-1234567890"
        assert store.get(borrowed.name).key == "synthetic-replacement"

    def test_set_key_unknown_plan_warns(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("set-key ghost sk-key")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown plan" in text

    def test_use_pins_payg_plan_for_provider(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = default_plan_for_payg("glm", "")
        registry.add(plan)
        cmd_login(f"use {plan.id}")
        for model in ("glm-5.3", "glm-5.2", "glm-5.1"):
            assert registry.get_routing(model)[0] == plan.id

    def test_use_blocked_subscription_keeps_routing_unchanged(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)
        registry.set_routing("glm-5.1", ["existing-plan"])
        with patch("core.cli.commands._persist_auth_state") as persist:
            cmd_login(f"use {plan.id}")
        assert registry.get_routing("glm-5.1") == ["existing-plan"]
        assert registry.get_routing("glm-5.3") == []
        persist.assert_not_called()


class TestRouteAndQuota:
    def test_route_requires_known_plan(self) -> None:
        _reset_state()
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("route glm-5.1 ghost-plan")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert "Unknown plan" in text

    def test_route_records_chain(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        a = default_plan_for_payg("glm", "")
        a.id = "glm-a"
        registry.add(a)
        b = GLM_CODING_TIERS["lite"]
        registry.add(b)
        cmd_login(f"route glm-5.1 {b.id} {a.id}")
        assert registry.get_routing("glm-5.1") == [b.id, a.id]

    def test_quota_shows_explicit_operator_call_window(self) -> None:
        from dataclasses import replace

        from core.llm.strategies.plans import Quota

        _reset_state()
        registry = get_plan_registry()
        plan = replace(GLM_CODING_TIERS["lite"], quota=Quota(window_s=18000, max_calls=42))
        registry.add(plan)
        with patch("core.cli.commands.console") as mock_console:
            cmd_login("quota")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            assert plan.id in text
            assert "42" in text

    def test_builtin_credit_plans_do_not_invent_call_quota(self) -> None:
        assert all(plan.quota is None for plan in GLM_CODING_TIERS.values())


class TestLegacyKeyAlias:
    def test_bare_key_redirects_to_login(self) -> None:
        _reset_state()
        from core.cli.commands import cmd_key

        with patch("core.cli.commands.console") as mock_console:
            cmd_key("")
            text = " ".join(
                str(call.args[0]) for call in mock_console.print.call_args_list if call.args
            )
            # Either the deprecation hint or the dashboard "Plans" header must show
            assert "Plans" in text or "redirects" in text

    def test_key_write_clears_dry_run_opt_in(self) -> None:
        _reset_state()
        from core.cli.commands import cmd_key

        with (
            patch("core.cli.commands.console"),
            patch("core.cli.commands._upsert_env"),
            patch("core.cli.commands.key.clear_dry_run_opt_in") as clear_opt_in,
        ):
            assert cmd_key("openai sk-fresh-key-1234567890") is True
        clear_opt_in.assert_called_once_with()


@pytest.mark.parametrize("provider", ["openai", "glm"])
def test_explicit_key_persists_fresh_profile_and_preserves_borrowed_key(
    provider: str, tmp_path: Path
) -> None:
    from core.auth.auth_toml import load_auth_toml
    from core.auth.profiles import ProfileStore
    from core.auth.rotation import ProfileRotator
    from core.cli.commands import cmd_key
    from core.llm.strategies.plan_registry import PlanRegistry
    from core.wiring.container import ensure_profile_store

    _reset_state()
    with patch("core.cli.commands._upsert_env"), patch("core.cli.commands.console"):
        assert cmd_key(f"{provider} synthetic-original")
        live = ensure_profile_store()
        borrowed = ProfileRotator(live).resolve(provider)
        assert borrowed is not None
        assert cmd_key(f"{provider} synthetic-replacement")
    fresh_registry, fresh = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=fresh_registry, store=fresh, path=tmp_path / "auth.toml")
    selected = ProfileRotator(fresh).resolve(provider)
    assert selected is not None and selected.key == "synthetic-replacement"
    assert borrowed.key == "synthetic-original"
