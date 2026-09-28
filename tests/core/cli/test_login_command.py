"""Phase 3 — /login unified command UX tests.

Smoke-tests for the subcommand router and the side effects on
ProfileStore + PlanRegistry. UI rendering is covered by snapshot tests
of the dashboard string output.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.auth.auth_toml import save_auth_toml
from core.cli.commands import cmd_login
from core.llm.strategies.plan_registry import (
    get_plan_registry,
    reset_plan_registry,
)
from core.llm.strategies.plans import GLM_CODING_TIERS, default_plan_for_payg


@pytest.mark.parametrize("accepted", [True, False])
def test_source_choice_requires_session_ack_before_saving_defaults(
    accepted: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.config.session import SessionModelConfig

    _reset_state()
    calls: list[tuple[str, object]] = []
    config = SessionModelConfig(
        model="gpt-6-sol",
        effort="low",
        source="subscription",
        reflection_model="gpt-6-luna",
        reflection_source="subscription",
        judge_model="claude-fable-5-1",
        judge_source="payg",
    )

    class Client:
        model_config = config.model_dump()

        def apply_model_config(self, changes):
            calls.append(("apply", changes))
            return {"status": "applied" if accepted else "error", "message": "rejected"}

    monkeypatch.setattr(
        "core.cli.commands.login._persist_credential_source",
        lambda *args: calls.append(("persist", args)),
    )
    with patch("core.cli.commands.console"):
        assert cmd_login("source openai api_key", client=Client()) is accepted
    assert calls[0] == ("apply", {"source": "payg", "reflection_source": "payg"})
    assert [kind for kind, _ in calls] == (["apply", "persist"] if accepted else ["apply"])
    assert config.effort == "low" and config.judge_source == "payg"


def test_source_candidate_does_not_mutate_current_record_or_global_defaults() -> None:
    from core.cli.commands.login import session_source_changes
    from core.config import settings
    from core.config.session import SessionModelConfig

    _reset_state()
    before = settings.openai_credential_source
    config = SessionModelConfig(model="gpt-6-sol", effort="low", source="subscription")
    assert session_source_changes(config, "openai", "api_key") == {"source": "payg"}
    assert config.source == "subscription" and settings.openai_credential_source == before
    with pytest.raises(RuntimeError, match="disabled"):
        session_source_changes(config, "openai", "none")


@pytest.fixture(autouse=True)
def _scrub_real_provider_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate the machine's real credentials from the auth/profile store.

    ``build_auth`` seeds runtime ``<provider>:default`` profiles from
    ``settings.{openai,anthropic,zai}_api_key`` in ``core.wiring.container``. ``Settings``
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

    def test_openai_login_reports_malformed_reply_as_login_failure(self) -> None:
        import json

        _reset_state()
        malformed = json.JSONDecodeError("Expecting value", "<html>", 0)
        with (
            patch("core.auth.oauth_login.login_openai", side_effect=malformed),
            patch("core.cli.commands.console") as mock_console,
        ):
            assert cmd_login("openai") is False
        text = " ".join(str(c.args[0]) for c in mock_console.print.call_args_list if c.args)
        assert "Login failed: Expecting value" in text

    def test_anthropic_login_prompts_for_api_key(self) -> None:
        _reset_state()
        with patch("core.cli.commands.login._login_anthropic_api_key") as login_api_key:
            cmd_login("anthropic")
        login_api_key.assert_called_once_with()

    def test_anthropic_login_persists_the_live_adapter_key(self, tmp_path: Path) -> None:
        _reset_state()
        key = "sk-ant-api03-test-key-1234567890"
        with (
            patch("getpass.getpass", return_value=key),
            patch("core.cli.commands.console"),
            patch("core.cli.commands._upsert_env") as upsert_env,
        ):
            cmd_login("anthropic")

        from core.config import settings

        assert settings.anthropic_api_key == ""
        upsert_env.assert_not_called()

        from core.auth.auth_toml import load_auth_toml
        from core.auth.profiles import ProfileStore
        from core.auth.rotation import ProfileRotator
        from core.llm.strategies.plan_registry import PlanRegistry

        registry, store = PlanRegistry(), ProfileStore()
        assert load_auth_toml(registry=registry, store=store, path=tmp_path / "auth.toml")
        profile = ProfileRotator(store).resolve("anthropic")
        assert profile is not None and profile.key == key
        assert profile.managed_by == ""

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
            patch("core.auth.auth_toml.save_api_key") as seed,
        ):
            assert cmd_key(key) is True

        assert settings.openrouter_api_key == ""
        upsert.assert_not_called()
        seed.assert_called_once_with(key, provider="openrouter")

    def test_set_key_updates_existing_plan(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = default_plan_for_payg("openai", "")
        registry.add(plan)
        save_auth_toml()  # Credential changes apply to plans stored in auth.toml.
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
        save_auth_toml()
        cmd_login(f"use {plan.id}")
        for model in ("glm-5.3", "glm-5.2", "glm-5.1"):
            assert registry.get_routing(model)[0] == plan.id

    def test_use_blocked_subscription_keeps_routing_unchanged(self) -> None:
        _reset_state()
        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)
        registry.set_routing("glm-5.1", ["existing-plan"])
        from core.auth.auth_toml import auth_toml_path

        assert cmd_login(f"use {plan.id}") is False
        assert registry.get_routing("glm-5.1") == ["existing-plan"]
        assert registry.get_routing("glm-5.3") == []
        assert not auth_toml_path().exists()


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
        save_auth_toml()
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


@pytest.mark.parametrize(
    ("args", "provider", "field"),
    [
        ("openai synthetic-new", "openai", "openai_api_key"),
        ("openrouter synthetic-new", "openrouter", "openrouter_api_key"),
        ("glm synthetic-new", "glm", "zai_api_key"),
        ("sk-ant-synthetic-new", "anthropic", "anthropic_api_key"),
        ("sk-or-v1-synthetic-new", "openrouter", "openrouter_api_key"),
        ("sk-proj-synthetic-new", "openai", "openai_api_key"),
        ("test1234.key56789", "glm", "zai_api_key"),
    ],
)
def test_key_write_failure_preserves_credentials(
    args: str, provider: str, field: str, tmp_path: Path
) -> None:
    from core.auth.rotation import ProfileRotator
    from core.cli.commands.key import cmd_key
    from core.config import settings
    from core.wiring.container import ensure_profile_store

    _reset_state()
    seed = "sk-ant-synthetic-old" if provider == "anthropic" else f"{provider} synthetic-old"
    with patch("core.cli.commands._upsert_env"), patch("core.cli.commands.console"):
        assert cmd_key(seed)
    prior_value = getattr(settings, field)
    store = ensure_profile_store()
    borrowed = ProfileRotator(store).resolve(provider)
    path = tmp_path / "auth.toml"
    before = path.read_bytes()

    with (
        patch("core.memory.atomic_write.os.replace", side_effect=OSError("synthetic failure")),
        patch("core.cli.commands._upsert_env") as mirror,
        patch("core.cli.commands.key.clear_dry_run_opt_in") as clear,
        patch("core.cli.commands.console") as console,
    ):
        assert cmd_key(args) is False
    assert getattr(settings, field) == prior_value
    assert path.read_bytes() == before
    assert ProfileRotator(store).resolve(provider) is borrowed
    mirror.assert_not_called()
    clear.assert_not_called()
    output = "\n".join(str(call.args[0]) for call in console.print.call_args_list if call.args)
    assert "Credential update failed" in output
    assert "[success]" not in output


@pytest.mark.parametrize("entry", ["interactive", "daemon", "thin"])
def test_key_entry_commits_auth_without_mutating_environment(entry: str, tmp_path: Path) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock

    from core.auth.auth_toml import load_auth_toml
    from core.auth.profiles import ProfileStore
    from core.cli.commands.key import cmd_key
    from core.cli.ipc_client import IPCClient
    from core.cli.routing import run_thin_command
    from core.config import settings
    from core.llm.strategies.plan_registry import PlanRegistry
    from core.server.ipc_server.poller import CLIPoller
    from core.wiring.container import ensure_profile_store

    _reset_state()
    key = "synthetic-selected"
    client = Mock(spec=IPCClient)
    client.send_command.return_value = {"status": "ok", "output": ""}
    with (
        patch("core.cli.commands._upsert_env", side_effect=AssertionError("no secret mirror")),
        patch("core.cli.commands.console") as console,
    ):
        if entry == "interactive":
            assert cmd_key(f"openai {key}") is True
        elif entry == "daemon":
            from core.cli.dispatcher import _handle_command

            poller = object.__new__(CLIPoller)
            poller._command_handler = _handle_command
            poller._scheduler_service = None
            poller._services = SimpleNamespace(
                command_registry=None, skill_registry=None, mcp_manager=None
            )
            result = asyncio.run(
                poller._handle_command_on_server({"cmd": "/key", "args": f"openai {key}"}, None)
            )
            assert result["status"] == "ok"
        else:
            with patch("core.ui.console.console", console):
                run_thin_command(client, "/key", f"openai {key}")
            client.send_command.assert_called_once_with("/login", "refresh")
    assert settings.openai_api_key == ""
    assert ensure_profile_store().get_pinned_active("openai").key == key
    registry, fresh = PlanRegistry(), ProfileStore()
    assert load_auth_toml(registry=registry, store=fresh, path=tmp_path / "auth.toml")
    assert fresh.get_pinned_active("openai").key == key


@pytest.mark.parametrize("args", ["openai", "pasted-unknown-secret", "openai key\nINJECT=value"])
def test_key_rejects_invalid_input_without_echo_or_persistence(args: str) -> None:
    from core.cli.commands.key import run_key

    with (
        patch("core.auth.auth_toml.save_api_key") as persist,
        pytest.raises(ValueError) as error,
    ):
        run_key(args)
    persist.assert_not_called()
    assert "pasted-unknown-secret" not in str(error.value)
    assert "INJECT" not in str(error.value)


@pytest.mark.parametrize("with_client", [False, True])
def test_source_conflict_does_not_save_defaults_or_mutate_unrelated_session(
    monkeypatch: pytest.MonkeyPatch,
    with_client: bool,
) -> None:
    from core.config import settings
    from core.config.session import SessionModelConfig

    _reset_state()
    monkeypatch.setattr(settings, "forced_login_method", {"openai": "subscription"})
    monkeypatch.setattr(settings, "openai_credential_source", "auto")
    config = SessionModelConfig(model="claude-fable-5-1", effort="low", source="payg")

    class Client:
        model_config = config.model_dump()

        def apply_model_config(self, changes):
            pytest.fail("conflicting future default must not mutate a session")

    with (
        patch("core.cli.commands.console"),
        patch("core.cli.commands.login._persist_credential_source") as persist,
    ):
        assert cmd_login("source openai api_key", client=Client() if with_client else None) is False
    persist.assert_not_called()
    assert settings.openai_credential_source == "auto"


def test_status_judges_each_profile_against_its_own_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from core.auth.profiles import AuthProfile, CredentialType
    from core.wiring.container import ensure_profile_store

    _reset_state()
    store = ensure_profile_store()
    for name, provider in (("openai:work", "openai"), ("anthropic:work", "anthropic")):
        store.add(AuthProfile(name, provider, CredentialType.API_KEY, key="synthetic-key-123456"))

    assert cmd_login("") is True

    out = capsys.readouterr().out
    assert "provider_mismatch" not in out
    assert "openai:work" in out and "anthropic:work" in out


@pytest.mark.parametrize("entry", ["add", "anthropic", "set-key"])
def test_hidden_key_entry_uses_single_auth_owner(entry: str, tmp_path: Path) -> None:
    from core.auth.auth_toml import save_api_key
    from core.config import settings
    from core.wiring.container import ensure_profile_store

    _reset_state()
    if entry == "set-key":
        save_api_key("old-synthetic", provider="anthropic")
    key = "sk-ant-synthetic-hidden"
    args = "set-key anthropic-payg" if entry == "set-key" else entry
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("core.cli.commands.login.TerminalMenu") as menu,
        patch("getpass.getpass", return_value=key) as hidden,
        patch("core.cli.commands.console") as console,
        patch("core.cli.commands._upsert_env", side_effect=AssertionError("no env writes")),
    ):
        menu.return_value.show.side_effect = [1, 0]
        assert cmd_login(args)
    hidden.assert_called_once()
    console.input.assert_not_called()
    assert settings.anthropic_api_key == ""
    assert ensure_profile_store().get_pinned_active("anthropic").key == key
    assert key in (tmp_path / "auth.toml").read_text()
    assert (tmp_path / "auth.toml").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("key", ["", "two words", "key\nINJECT=value"])
def test_api_key_owner_rejects_invalid_secret_before_file_creation(
    key: str, tmp_path: Path
) -> None:
    from core.auth.auth_toml import save_api_key

    _reset_state()
    with pytest.raises(ValueError, match=r"nonempty.*whitespace"):
        save_api_key(key, provider="openai")
    assert not (tmp_path / "auth.toml").exists()


@pytest.mark.parametrize("provider", ["unknown", "openai-codex", "glm-coding"])
def test_api_key_owner_rejects_unsupported_payg_route(provider: str, tmp_path: Path) -> None:
    from core.auth.auth_toml import save_api_key
    from core.wiring.container import ensure_profile_store

    _reset_state()
    store = ensure_profile_store()
    profiles_before = store.list_all()
    plans_before = get_plan_registry().list_all()
    with pytest.raises(ValueError, match="supported PAYG"):
        save_api_key("synthetic-new", provider=provider)
    assert not (tmp_path / "auth.toml").exists()
    assert store.list_all() == profiles_before
    assert get_plan_registry().list_all() == plans_before


@pytest.mark.parametrize("managed_by", ["external", ""])
def test_api_key_owner_preserves_live_credentials_owned_elsewhere(
    managed_by: str, tmp_path: Path
) -> None:
    from core.auth.auth_toml import save_api_key
    from core.auth.profiles import AuthProfile, CredentialType
    from core.wiring.container import ensure_profile_store

    _reset_state()
    store = ensure_profile_store()
    borrowed = AuthProfile(
        name="openai-payg:user",
        provider="openai",
        credential_type=CredentialType.API_KEY,
        key="synthetic-old",
        plan_id="openai-payg",
        managed_by=managed_by,
    )
    store.add(borrowed, activate=True)
    preferences_before = store.auth_preferences()
    plans_before = get_plan_registry().list_all()
    with pytest.raises(ValueError, match="another owner"):
        save_api_key("synthetic-new", provider="openai")
    assert not (tmp_path / "auth.toml").exists()
    assert store.get(borrowed.name) is borrowed
    assert store.get_pinned_active("openai") is borrowed
    assert borrowed.key == "synthetic-old"
    assert store.auth_preferences() == preferences_before
    assert get_plan_registry().list_all() == plans_before


@pytest.mark.parametrize("provider,kind", [("glm", "payg"), ("openai", "subscription")])
def test_api_key_owner_preserves_conflicting_saved_plan(
    provider: str, kind: str, tmp_path: Path
) -> None:
    from core.auth.auth_toml import save_api_key
    from core.auth.profiles import AuthProfile, CredentialType
    from core.llm.strategies.plans import Plan, PlanKind
    from core.wiring.container import ensure_profile_store

    _reset_state()
    registry, store = get_plan_registry(), ensure_profile_store()
    plan = Plan(
        id="openai-payg",
        provider=provider,
        kind=PlanKind(kind),
        display_name="Existing plan",
        base_url="https://example.invalid",
    )
    registry.add(plan)
    borrowed = AuthProfile(
        name="openai-payg:user",
        provider=provider,
        credential_type=CredentialType.API_KEY,
        key="synthetic-old",
        plan_id=plan.id,
    )
    store.add(borrowed, activate=True)
    path = save_auth_toml(registry=registry, store=store)
    contents_before = path.read_bytes()
    preferences_before = store.auth_preferences()
    with pytest.raises(ValueError, match="conflicts with the requested provider"):
        save_api_key("synthetic-new", provider="openai")
    assert path == tmp_path / "auth.toml"
    assert path.read_bytes() == contents_before
    assert registry.get(plan.id) is plan
    assert store.get(borrowed.name) is borrowed
    assert borrowed.key == "synthetic-old"
    assert store.auth_preferences() == preferences_before


def test_login_rejects_pasted_key_without_echoing_it() -> None:
    from core.ui.console import capture_output
    from rich.text import Text

    secret = "sk-" + "synthetic1234567890" * 2
    with capture_output() as output:
        assert cmd_login(f"remove {secret}") is False
    assert secret not in output.getvalue()
    assert "[REDACTED]" in Text.from_ansi(output.getvalue()).plain
    assert "Plan not found" in output.getvalue()


def test_login_persistence_failure_redacts_credential_in_error() -> None:
    from core.ui.console import capture_output
    from rich.text import Text

    secret = "sk-" + "synthetic1234567890" * 2
    with (
        patch("core.cli.commands.login.run_login", side_effect=PermissionError(f"denied {secret}")),
        capture_output() as output,
    ):
        assert cmd_login("remove example") is False
    assert secret not in output.getvalue()
    assert "[REDACTED]" in Text.from_ansi(output.getvalue()).plain
    assert "Credential change failed" in output.getvalue()


@pytest.mark.parametrize(
    "args",
    ["source", "source unknown auto", "source openai unknown", "source anthropic oauth"],
)
def test_source_invalid_input_propagates_without_persisting(args: str) -> None:
    from core.cli.commands.login import run_login

    with (
        patch("core.cli.commands.login._persist_credential_source") as persist,
        patch("core.cli.commands.console"),
    ):
        with pytest.raises(ValueError):
            run_login(args)
        assert cmd_login(args) is False
    persist.assert_not_called()


@pytest.mark.parametrize("with_client", [False, True])
def test_source_persistence_failure_is_not_reported_as_success(with_client: bool) -> None:
    from core.config import settings
    from core.config.session import SessionModelConfig
    from core.ui.console import capture_output

    _reset_state()
    config = SessionModelConfig(model="gpt-6-sol", effort="low", source="subscription")
    applied: list[dict[str, str]] = []

    class Client:
        model_config = config.model_dump()

        def apply_model_config(self, changes):
            applied.append(changes)
            return {"status": "applied"}

    before = settings.openai_credential_source
    with (
        patch("core.config.env_io.upsert_config_toml", side_effect=PermissionError("denied")),
        capture_output() as output,
    ):
        assert cmd_login("source openai api_key", client=Client() if with_client else None) is False
    assert settings.openai_credential_source == before
    assert applied == ([{"source": "payg"}] if with_client else [])
    assert "Credential change failed" in output.getvalue()
    assert "Defaults saved" not in output.getvalue()
    assert ("Session source applied" in output.getvalue()) is with_client


@pytest.mark.parametrize("entry", ["add", "anthropic", "set-key"])
@pytest.mark.parametrize("input_result", ["", EOFError, KeyboardInterrupt])
def test_hidden_key_empty_or_cancel_preserves_saved_credential(
    entry: str, input_result: object, tmp_path: Path
) -> None:
    from core.auth.auth_toml import save_api_key
    from core.wiring.container import ensure_profile_store

    _reset_state()
    save_api_key("synthetic-old", provider="anthropic")
    path = tmp_path / "auth.toml"
    before = path.read_bytes()
    profile = ensure_profile_store().get_pinned_active("anthropic")
    args = "set-key anthropic-payg" if entry == "set-key" else entry
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("core.cli.commands.login.TerminalMenu") as menu,
        patch("getpass.getpass") as hidden,
        patch("core.cli.commands.console"),
    ):
        menu.return_value.show.side_effect = [1, 0]
        if input_result == "":
            hidden.return_value = ""
        else:
            hidden.side_effect = input_result
        assert cmd_login(args) is False
    assert path.read_bytes() == before
    assert ensure_profile_store().get_pinned_active("anthropic") is profile
    assert profile.key == "synthetic-old"


@pytest.mark.parametrize("menu_choices", [[None], [1, None]])
def test_add_menu_cancel_does_not_request_or_save_credential(
    menu_choices: list[int | None],
) -> None:
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("core.cli.commands.login.TerminalMenu") as menu,
        patch("getpass.getpass") as hidden,
        patch("core.auth.auth_toml.save_api_key") as save,
        patch("core.cli.commands.console"),
    ):
        menu.return_value.show.side_effect = menu_choices
        assert cmd_login("add") is False
    hidden.assert_not_called()
    save.assert_not_called()
