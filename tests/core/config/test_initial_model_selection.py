"""Implicit defaults follow eligible registry routes; explicit policy never moves."""

from __future__ import annotations

import time

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.config import Settings
from core.config.session import resolve_initial_model
from core.llm.registry import get_provider_spec


@pytest.fixture
def implicit(monkeypatch, tmp_path):
    import core.config as cfg
    from core.config import explain
    from core.wiring import container

    for variable in (
        "GEODE_MODEL",
        "GEODE_OPENAI_CREDENTIAL_SOURCE",
        "GEODE_ANTHROPIC_CREDENTIAL_SOURCE",
        "GEODE_FORCED_LOGIN_METHOD",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(explain, "GLOBAL_ENV_FILE", tmp_path / "global.env")
    monkeypatch.setattr(explain, "PROJECT_ENV_FILE", tmp_path / "project.env")
    monkeypatch.setattr(explain, "PROJECT_CONFIG_PATH", tmp_path / "project.toml")
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(tmp_path / "global.toml"))
    candidate = Settings(
        _env_file=None,
        **{name: "" for name in Settings.model_fields if name.endswith("_api_key")},
    )
    monkeypatch.setattr(cfg, "settings", candidate)
    monkeypatch.setattr(cfg, "_get_settings", lambda: candidate)
    store = ProfileStore()
    store.add(
        AuthProfile(
            name="borrowed",
            provider="openai-codex",
            credential_type=CredentialType.OAUTH,
            key="synthetic-token",
            managed_by="codex-cli",
            expires_at=time.time() + 3600,
        )
    )
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr("core.auth.codex_cli_oauth.sync_codex_cli_profile", lambda *a, **kw: None)
    return candidate, store


def test_codex_only_selects_catalog_default_without_persisting(implicit, tmp_path):
    settings, _ = implicit
    before = settings.model_dump()
    spec = get_provider_spec("openai-codex")
    assert spec is not None
    assert resolve_initial_model(settings) == (spec.profile.default_model(), "subscription")
    assert settings.model_dump() == before
    assert not (tmp_path / "global.toml").exists()


def test_initial_client_payload_and_server_seed_agree(implicit, monkeypatch):
    from unittest.mock import MagicMock

    from core.cli.ipc_client import IPCClient
    from core.server.supervised.services import SessionMode, SharedServices

    settings, _ = implicit
    monkeypatch.setattr("core.config.reload_settings_from_disk", lambda: None)
    expected = resolve_initial_model(settings)
    sent = []
    client = IPCClient()
    monkeypatch.setattr(client, "_send", lambda payload: sent.append(payload) or "seed")
    client._send_client_capability(include_model_config=True)
    services = SharedServices(
        mcp_manager=MagicMock(), skill_registry=MagicMock(), hook_system=MagicMock()
    )
    _, loop = services.create_session(SessionMode.IPC)
    assert (sent[0]["model_config"]["model"], sent[0]["model_config"]["source"]) == expected
    assert (loop.model, loop._source) == expected


def test_plugin_policy_field_has_no_implicit_authority(implicit, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    settings, _ = implicit
    spec = get_provider_spec("openai-codex")
    assert spec is not None
    plugin = replace(spec, credential=replace(spec.credential, settings_field="plugin_preference"))
    snapshot = SimpleNamespace(registrations={"plugin": SimpleNamespace(provider_spec=plugin)})
    monkeypatch.setattr("core.llm.adapters.registry.active_registry_snapshot", lambda: snapshot)
    monkeypatch.setattr("core.llm.routing.infer_source", lambda *a, **kw: "payg")
    assert resolve_initial_model(settings) == (settings.model, "payg")


@pytest.mark.parametrize("layer", ["constructor", "env", "global", "project"])
def test_explicit_default_equal_value_stays_explicit(implicit, monkeypatch, tmp_path, layer):
    settings, _ = implicit
    if layer == "constructor":
        settings.model = settings.model
    elif layer == "env":
        monkeypatch.setenv("GEODE_MODEL", settings.model)
    else:
        (tmp_path / f"{layer}.toml").write_text(f'[llm]\nprimary_model="{settings.model}"\n')
    assert resolve_initial_model(settings) == (settings.model, "payg")


@pytest.mark.parametrize("pin", ["source", "forced", "plan"])
def test_source_and_plan_pins_never_choose_another_provider(implicit, pin):
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import Plan, PlanKind

    settings, _ = implicit
    if pin == "source":
        settings.openai_credential_source = "auto"
    elif pin == "forced":
        settings.forced_login_method = {"openai": "subscription"}
    else:
        registry = get_plan_registry()
        registry.add(
            Plan(
                id="anthropic-pinned",
                provider="anthropic",
                kind=PlanKind.PAYG,
                display_name="Pinned",
                base_url="https://api.anthropic.com",
            )
        )
        registry.set_routing(settings.model, ["anthropic-pinned"])
    assert resolve_initial_model(settings) == (settings.model, "payg")


def test_no_eligible_or_multiple_eligible_defaults_keep_selection(implicit):
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import Plan, PlanKind

    settings, store = implicit
    store.get("borrowed").disabled = True
    assert resolve_initial_model(settings) == (settings.model, "payg")
    store.get("borrowed").disabled = False
    get_plan_registry().add(
        Plan(
            id="other",
            provider="glm",
            kind=PlanKind.PAYG,
            display_name="other",
            base_url="https://api.z.ai/api/paas/v4",
        )
    )
    store.add(
        AuthProfile(
            name="other",
            provider="glm",
            plan_id="other",
            credential_type=CredentialType.API_KEY,
            key="synthetic-key",
        )
    )
    assert resolve_initial_model(settings) == (settings.model, "payg")
