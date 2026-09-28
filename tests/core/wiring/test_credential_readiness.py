"""Credential displays inspect the same local routes as request admission."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from core.auth.auth_toml import load_auth_toml, save_api_key
from core.auth.profiles import ProfileStore
from core.config import settings
from core.llm.routing import model_available
from core.llm.strategies import plan_registry
from core.wiring import container, startup


@pytest.fixture
def accounts(monkeypatch):
    store = ProfileStore()
    registry = plan_registry.PlanRegistry()
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr(plan_registry, "_plan_registry", registry)
    monkeypatch.setattr(settings, "model", "claude-fable-5-1")
    monkeypatch.setattr(settings, "forced_login_method", {})
    monkeypatch.setattr(settings, "anthropic_credential_source", "auto")
    monkeypatch.setattr(settings, "openai_credential_source", "auto")
    return store, registry


@pytest.mark.parametrize(
    "provider,model,field",
    [
        ("anthropic", "claude-fable-5-1", "anthropic_api_key"),
        ("openai", "gpt-6-sol", "openai_api_key"),
        ("openrouter", "openrouter/openrouter/free", "openrouter_api_key"),
        ("glm", "glm-5.3", "zai_api_key"),
    ],
)
def test_auth_file_only_survives_reload_and_unblocks_readiness(
    accounts, monkeypatch, tmp_path, provider, model, field
):
    save_api_key("synthetic-account-key", provider=provider)
    assert getattr(settings, field) == ""
    # Simulate a new process's account hydration from the sole interactive store.
    store, registry = ProfileStore(), plan_registry.PlanRegistry()
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr(plan_registry, "_plan_registry", registry)
    assert load_auth_toml(store=store, registry=registry)
    assert model_available(model)
    assert startup.has_available_llm_credential(provider)
    assert startup._has_any_llm_key()
    assert startup.check_readiness(tmp_path).blocked is False


@pytest.mark.parametrize(
    "state", ["disabled", "cooldown", "source-disabled", "forced-subscription"]
)
def test_unavailable_accounts_and_source_policy_do_not_unblock(
    accounts, monkeypatch, tmp_path, state
):
    save_api_key("synthetic-account-key", provider="anthropic")
    profile = accounts[0].list_all()[0]
    if state == "disabled":
        profile.disabled = True
    elif state == "cooldown":
        profile.cooldown_until = time.time() + 3600
    elif state == "source-disabled":
        monkeypatch.setattr(settings, "anthropic_credential_source", "none")
    else:
        monkeypatch.setattr(settings, "forced_login_method", {"anthropic": "subscription"})
    assert not model_available(settings.model)
    assert not startup._has_any_llm_key()
    assert startup.check_readiness(tmp_path).blocked is True
    from core.cli.doctor_bootstrap import _check_profile_store

    assert not _check_profile_store().ok


@pytest.mark.parametrize(
    "field,model,placeholder",
    [
        ("anthropic_api_key", "claude-fable-5-1", "sk-ant-..."),
        ("openai_api_key", "gpt-6-sol", "sk-..."),
        ("openrouter_api_key", "openrouter/openrouter/free", "sk-or-v1-..."),
        ("zai_api_key", "glm-5.3", "..."),
    ],
)
def test_external_settings_fallback_and_placeholder(
    accounts, monkeypatch, field, model, placeholder
):
    monkeypatch.setattr(settings, field, "synthetic-environment-key")
    assert model_available(model)
    assert startup._has_any_llm_key()
    monkeypatch.setattr(settings, field, placeholder)
    assert not model_available(model)
    assert not startup._has_any_llm_key()


def test_explicit_unavailable_plan_does_not_use_environment_fallback(accounts, monkeypatch):
    save_api_key("synthetic-account-key", provider="anthropic")
    plan = accounts[1].list_all()[0]
    accounts[1].set_routing(settings.model, [plan.id])
    accounts[0].list_all()[0].disabled = True
    monkeypatch.setattr(settings, "anthropic_api_key", "synthetic-environment-key")
    assert not model_available(settings.model)


def test_status_mcp_doctor_and_key_warning_see_auth_only_account(accounts, monkeypatch):
    save_api_key("synthetic-account-key", provider="anthropic")
    from core.cli import commands, session_state
    from core.cli.commands.key import _check_provider_key
    from core.cli.doctor_bootstrap import _check_profile_store
    from core.cli.tool_handlers.system import _build_system_handlers

    monkeypatch.setattr(session_state, "_get_readiness", lambda: None)
    status = dict(_build_system_handlers(None))["check_status"]()
    assert status["anthropic_configured"] is True
    assert status["openai_configured"] is False
    assert status["model_available"] is True
    assert status["mode"] == "full_llm"
    assert _check_profile_store().ok
    console = Mock()
    monkeypatch.setattr(commands, "console", console)
    _check_provider_key(commands.ModelProfile(settings.model, "anthropic", "test", "$"))
    console.print.assert_not_called()

    from core.mcp_server import create_mcp_server

    # MCP may be the first caller in a process; its model bit must hydrate too.
    monkeypatch.setattr(container, "_profile_store", None)
    monkeypatch.setattr(plan_registry, "_plan_registry", None)
    response = asyncio.run(create_mcp_server().call_tool("get_health", {}))
    payload = response[1] if isinstance(response, tuple) else response
    if "result" in payload:
        payload = payload["result"]
    assert payload["anthropic_configured"] is True
    assert payload["model_available"] is True


def test_status_uses_session_source_after_default_changes(accounts, monkeypatch):
    save_api_key("synthetic-account-key", provider="openai")
    from core.cli import session_state
    from core.cli.tool_handlers.system import _build_system_handlers
    from core.config.session import SessionModelConfig

    monkeypatch.setattr(session_state, "_get_readiness", lambda: None)
    monkeypatch.setattr(settings, "openai_credential_source", "none")
    config = SessionModelConfig(model="gpt-6-sol", effort="low", source="payg")
    owner = SimpleNamespace(model=config.model, _model_settings=config)
    status = dict(_build_system_handlers(None))["check_status"](
        _tool_context=SimpleNamespace(agent_loop=owner)
    )
    assert status["scope"] == "session"
    assert status["model_available"] is True
    assert status["mode"] == "full_llm"
    assert status["openai_configured"] is False  # future-session default is disabled


@pytest.mark.parametrize(
    "provider,model",
    [
        ("anthropic", "claude-fable-5-1"),
        ("openai", "gpt-6-sol"),
        ("openrouter", "openrouter/openrouter/free"),
        ("glm", "glm-5.3"),
    ],
)
def test_availability_uses_the_request_endpoint_and_model_plan(accounts, provider, model):
    from core.llm.adapters.registry import resolve_for

    plan = save_api_key("synthetic-endpoint-key", provider=provider)
    endpoint = "https://selected.invalid/v1"
    accounts[0].list_all()[0].base_url_override = endpoint
    adapter = resolve_for(provider, "payg")
    # An unselected profile for a different endpoint cannot supply this request.
    assert not model_available(model, source="payg")
    with pytest.raises(RuntimeError, match="not set"):
        adapter._get_client(model)
    # An explicit model plan selects that endpoint; detection must use this model.
    accounts[1].set_routing(model, [plan.id])
    assert model_available(model, source="payg")
    assert adapter._credential(model)[:2] == ("synthetic-endpoint-key", endpoint)


@pytest.mark.parametrize(
    "provider,model,variable",
    [
        ("anthropic", "claude-fable-5-1", "ANTHROPIC_BASE_URL"),
        ("openai", "gpt-6-sol", "OPENAI_BASE_URL"),
    ],
)
def test_endpoint_environment_override_does_not_report_default_profile_available(
    accounts, monkeypatch, provider, model, variable
):
    from core.llm.adapters.registry import resolve_for

    save_api_key("synthetic-default-endpoint-key", provider=provider)
    monkeypatch.setenv(variable, "https://other.invalid/v1")
    assert not model_available(model, source="payg")
    with pytest.raises(RuntimeError, match="not set"):
        resolve_for(provider, "payg")._get_client(model)


def test_codex_availability_checks_subscription_endpoint_and_managed_owner(accounts, monkeypatch):
    from core.auth.profiles import AuthProfile, CredentialType
    from core.config import CODEX_BASE_URL
    from core.llm.strategies.plans import Plan, PlanKind

    store, registry = accounts
    plan = Plan("subscription", "openai-codex", PlanKind.SUBSCRIPTION, "test", CODEX_BASE_URL)
    registry.add(plan)
    profile = AuthProfile(
        "subscription:test",
        "openai-codex",
        CredentialType.OAUTH,
        key="synthetic-oauth-token",
        plan_id=plan.id,
    )
    store.add(profile)
    monkeypatch.setattr("core.auth.codex_cli_oauth.read_codex_cli_credentials", lambda **_: None)
    assert model_available("gpt-6-sol", source="subscription")
    profile.base_url_override = "https://invalid.example/codex"
    assert not model_available("gpt-6-sol", source="subscription")
    profile.base_url_override = None
    # An imported credential disappears when its authoritative owner has logged out.
    profile.managed_by = "codex-cli"
    assert not model_available("gpt-6-sol", source="subscription")
    assert store.get(profile.name) is None
