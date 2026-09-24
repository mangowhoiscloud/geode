"""Source lifecycle admission must not mutate a saved model or billing source."""

from __future__ import annotations

import re
import sys
from unittest.mock import Mock

import pytest
from core.cli.commands import _state, model
from core.config import settings


@pytest.fixture(autouse=True)
def _isolate_anthropic_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def _wire_openai_credentials(monkeypatch: pytest.MonkeyPatch, *, oauth: bool, payg: bool) -> None:
    from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
    from core.auth.rotation import ProfileRotator
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import Plan, PlanKind
    from core.wiring import container

    store = ProfileStore()
    registry = get_plan_registry()
    for enabled, provider, kind, credential_type in (
        (oauth, "openai-codex", PlanKind.OAUTH_BORROWED, CredentialType.OAUTH),
        (payg, "openai", PlanKind.PAYG, CredentialType.API_KEY),
    ):
        if enabled:
            registry.add(Plan(provider, provider, kind, provider, "https://offline.example.test"))
            store.add(
                AuthProfile(
                    name=f"{provider}-offline",
                    provider=provider,
                    plan_id=provider,
                    credential_type=credential_type,
                    key="offline-key",
                )
            )
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr(container, "_profile_rotator", ProfileRotator(store))
    monkeypatch.setattr(settings, "openai_api_key", "offline-key" if payg else "")
    monkeypatch.setattr(settings, "openai_credential_source", "oauth")
    monkeypatch.setattr(settings, "forced_login_method", {})
    monkeypatch.setattr(
        "core.auth.codex_cli_oauth.read_codex_cli_credentials", lambda **kwargs: None
    )


@pytest.mark.parametrize("oauth,payg", [(True, False), (False, True), (True, True)])
def test_explicit_source_checks_its_real_adapter_credentials(
    monkeypatch: pytest.MonkeyPatch, oauth: bool, payg: bool
) -> None:
    from core.llm.strategies.plan_registry import resolve_routing

    _wire_openai_credentials(monkeypatch, oauth=oauth, payg=payg)
    target = resolve_routing("gpt-5.5")
    assert target is not None
    assert target.plan.provider == ("openai-codex" if oauth else "openai")
    assert _state.model_available("gpt-5.5") is True  # default behavior unchanged
    assert _state.model_available("gpt-5.4", source="payg") is payg
    assert _state.model_available("gpt-5.5", source="subscription") is oauth


@pytest.mark.parametrize("retired", ["gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.3-codex"])
def test_subscription_picker_excludes_retired_offerings_but_keeps_disabled_current_row(
    monkeypatch: pytest.MonkeyPatch, retired: str
) -> None:
    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "subscription")
    rows = _state.get_model_profiles()
    assert retired not in {row.id for row in rows}
    assert "gpt-5.5" in {row.id for row in rows}  # October 14 is still future

    configured = _state.get_model_profiles(configured_model_ids=(retired, retired))
    matches = [row for row in configured if row.id == retired]
    assert len(matches) == 1
    assert "Unavailable on subscription" in matches[0].label
    assert _state.model_available(retired) is False


def test_picker_reloads_source_without_hiding_platform_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "subscription")
    assert "gpt-5.4" not in {row.id for row in _state.get_model_profiles()}
    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "payg")
    assert {"gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"} <= {
        row.id for row in _state.get_model_profiles()
    }
    assert _state.model_unavailable_reason("gpt-5.4") is None


def test_retired_anthropic_configuration_is_disabled_and_not_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg

    monkeypatch.setattr(cfg, "ANTHROPIC_SECONDARY", "claude-sonnet-4")
    rows = _state.get_model_profiles(configured_model_ids=("claude-opus-4-1",))
    for model_id in ("claude-sonnet-4", "claude-opus-4-1"):
        row = next(row for row in rows if row.id == model_id)
        assert "Unavailable on Anthropic API" in row.label
        assert _state.model_available(model_id) is False
        assert "retired" in (_state.model_unavailable_reason(model_id) or "")
    assert cfg.ANTHROPIC_SECONDARY == "claude-sonnet-4"


def test_custom_anthropic_host_does_not_inherit_official_api_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    monkeypatch.setattr(cfg, "ANTHROPIC_SECONDARY", "claude-sonnet-4")
    monkeypatch.setattr(settings, "anthropic_api_key", "offline-key")
    rows = _state.get_model_profiles(configured_model_ids=("claude-opus-4-1",))
    for model_id in ("claude-sonnet-4", "claude-opus-4-1"):
        row = next(row for row in rows if row.id == model_id)
        assert "Unavailable" not in row.label
        assert _state.model_available(model_id, source="payg") is True
        assert _state.model_unavailable_reason(model_id) is None


def test_retired_current_selection_enter_does_not_pick_another_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.cli import effort_picker

    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "subscription")
    rows = _state.get_model_profiles(configured_model_ids=("gpt-5.4",))
    profiles = [
        (row.id, row.provider, row.label, row.cost, row.id != "gpt-5.4", None) for row in rows
    ]
    monkeypatch.setattr(effort_picker, "_read_key", lambda: effort_picker._KEY_ENTER)
    monkeypatch.setattr(effort_picker, "_render", lambda *args, **kwargs: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda lines: None)
    result = effort_picker.pick_model_and_effort(profiles, "gpt-5.4", "high")
    assert result.cancelled is True
    assert result.model_id == "gpt-5.4"


def test_payg_mutator_keeps_platform_choice_while_subscription_primary_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.cli import effort_picker

    _wire_openai_credentials(monkeypatch, oauth=True, payg=True)
    monkeypatch.setattr(
        model, "_read_toml_value", lambda section, key: "api_key" if key == "source" else "gpt-5.4"
    )
    initial_models = {role.name: "gpt-5.4" for role in _state.AGENT_ROLES}
    rows = model._picker_profiles(initial_models)
    availability = model._role_model_availability(rows)
    assert availability["primary"]["gpt-5.4"] is False
    assert availability["mutator"]["gpt-5.4"] is True

    keys = iter([effort_picker._KEY_TAB, effort_picker._KEY_TAB, effort_picker._KEY_ENTER])
    monkeypatch.setattr(effort_picker, "_read_key", lambda: next(keys))
    monkeypatch.setattr(effort_picker, "_render", lambda *args, **kwargs: 0)
    monkeypatch.setattr(effort_picker, "_clear_lines", lambda lines: None)
    profiles = [(row.id, row.provider, row.label, row.cost, False, None) for row in rows]
    result = effort_picker.pick_model_and_effort(
        profiles,
        "gpt-5.4",
        "high",
        roles=[(role.name, role.label, role.description) for role in _state.AGENT_ROLES],
        role_initial_models=initial_models,
        role_model_availability=availability,
    )
    assert result.cancelled is False
    assert result.role == "mutator" and result.model_id == "gpt-5.4"

    applied = Mock()
    monkeypatch.setattr(model, "_apply_model", applied)
    model.cmd_model("mutator gpt-5.4")
    assert applied.call_args.args[0].id == "gpt-5.4"
    assert applied.call_args.kwargs["role"] == "mutator"


@pytest.mark.parametrize("role", ["primary", "mutator"])
def test_non_tty_displayed_index_selects_the_same_role_specific_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, role: str
) -> None:
    from core.cli import commands

    _wire_openai_credentials(monkeypatch, oauth=True, payg=True)
    monkeypatch.setattr(
        model,
        "_read_toml_value",
        lambda section, key: "api_key" if key == "source" else "gpt-6-astra",
    )
    monkeypatch.setattr(model, "_current_model_for_role", lambda role: "gpt-6-astra")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    printer = Mock()
    monkeypatch.setattr(commands.console, "print", printer)
    model.cmd_model(role)
    displayed = [str(call.args[0]) for call in printer.call_args_list if call.args]
    gpt54_rows = [row for row in displayed if re.search(r"\bGPT-5\.4\s+openai\b", row)]
    if role == "primary":
        assert gpt54_rows == []
        return
    assert len(gpt54_rows) == 1
    assert "unavailable" not in gpt54_rows[0] and "login required" not in gpt54_rows[0]
    match = re.match(r"\s*(\d+)\.", gpt54_rows[0])
    assert match is not None
    applied = Mock()
    monkeypatch.setattr(model, "_apply_model", applied)
    caplog.clear()
    model.cmd_model(f"{role} {match[1]}")
    assert applied.call_args.args[0].id == "gpt-5.4"
    assert applied.call_args.kwargs["role"] == role
    assert "No built-in adapter family matches model" not in caplog.text


@pytest.mark.parametrize("role", ["primary", "reflection", "mutator"])
def test_explicit_retired_selection_reports_reason_before_credentials_or_writes(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    from core.cli import commands
    from core.config import env_io

    monkeypatch.setattr(_state, "_selected_openai_source", lambda: "subscription")
    monkeypatch.setattr(settings, "model", "gpt-5.6-sol")
    monkeypatch.setattr(settings, "openai_credential_source", "oauth")
    printer, credential_check, persist = Mock(), Mock(), Mock()
    monkeypatch.setattr(commands.console, "print", printer)
    monkeypatch.setattr(commands, "_check_provider_key", credential_check)
    monkeypatch.setattr(env_io, "upsert_config_toml", persist)

    model.cmd_model(f"{role} gpt-5.4")
    model._apply_model(_state.ModelProfile("gpt-5.4", "openai", "GPT-5.4", "$$"), role=role)

    assert settings.model == "gpt-5.6-sol"
    assert settings.openai_credential_source == "oauth"
    assert "retired on 2026-08-31" in str(printer.call_args_list)
    assert "gpt-6-sol explicitly" in str(printer.call_args_list)
    credential_check.assert_not_called()
    persist.assert_not_called()
