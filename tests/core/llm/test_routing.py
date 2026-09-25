"""One route decision for admission and source-constrained account selection."""

from __future__ import annotations

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator
from core.config import settings
from core.llm.routing import infer_source, resolve_routing
from core.llm.strategies import plan_registry
from core.llm.strategies.plans import Plan, PlanKind, default_plan_for_payg
from core.wiring import container


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch) -> tuple[ProfileStore, plan_registry.PlanRegistry]:
    store, registry = ProfileStore(), plan_registry.PlanRegistry()
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr(container, "_profile_rotator", ProfileRotator(store))
    monkeypatch.setattr(plan_registry, "_plan_registry", registry)
    monkeypatch.setattr(settings, "forced_login_method", {})
    monkeypatch.setattr(settings, "openai_credential_source", "auto")
    monkeypatch.setattr(settings, "anthropic_credential_source", "auto")
    return store, registry


def _add(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
    provider: str,
    *,
    subscription: bool = False,
) -> Plan:
    store, registry = accounts
    plan = (
        Plan(
            id=provider,
            provider=provider,
            kind=PlanKind.SUBSCRIPTION,
            display_name=provider,
            base_url="https://chatgpt.com/backend-api/codex"
            if provider == "openai-codex"
            else "https://api.z.ai/api/coding/paas/v4",
        )
        if subscription
        else default_plan_for_payg(provider, "synthetic")
    )
    registry.add(plan)
    store.add(
        AuthProfile(
            name=provider,
            provider=provider,
            credential_type=CredentialType.OAUTH
            if provider == "openai-codex"
            else CredentialType.API_KEY,
            key="synthetic",
            plan_id=plan.id,
        )
    )
    return plan


def test_forced_api_matches_runtime_and_plan(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry], monkeypatch: pytest.MonkeyPatch
) -> None:
    payg = _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    monkeypatch.setattr(settings, "forced_login_method", {"openai": "apikey"})
    assert infer_source("openai", model="gpt-6-sol") == "payg"
    target = resolve_routing("gpt-6-sol")
    assert target is not None and target.plan is payg


def test_glm_coding_selection_does_not_silently_become_payg(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
) -> None:
    coding = _add(accounts, "glm-coding", subscription=True)
    assert infer_source("glm", model="glm-5.3") == "subscription"
    target = resolve_routing("glm-5.3")
    assert target is not None and target.plan is coding


def test_unavailable_subscription_never_falls_through_to_payg(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
) -> None:
    _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    profile = accounts[0].get("openai-codex")
    assert profile is not None
    profile.disabled = True
    assert infer_source("openai", model="gpt-6-sol") == "subscription"
    assert resolve_routing("gpt-6-sol") is None


def test_concrete_route_ignores_changed_global_source(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry], monkeypatch: pytest.MonkeyPatch
) -> None:
    payg = _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    monkeypatch.setattr(settings, "openai_credential_source", "openai-codex")
    target = resolve_routing("gpt-6-sol", source="payg")
    assert target is not None and target.plan is payg


def test_model_chain_chooses_source_once_not_first_available_billing_bucket(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
) -> None:
    payg = _add(accounts, "openai")
    sub = _add(accounts, "openai-codex", subscription=True)
    accounts[1].set_routing("gpt-6-sol", [sub.id, payg.id])
    profile = accounts[0].get("openai-codex")
    assert profile is not None
    profile.disabled = True
    assert infer_source("openai", model="gpt-6-sol") == "subscription"
    with pytest.raises(RuntimeError, match="no available account"):
        resolve_routing("gpt-6-sol")


def test_unknown_model_plan_rejects_instead_of_defaulting(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
) -> None:
    _add(accounts, "openai")
    accounts[1].set_routing("gpt-6-sol", ["deleted-plan"])
    with pytest.raises(RuntimeError, match="unknown plan"):
        infer_source("openai", model="gpt-6-sol")


def test_missing_credentials_remain_unavailable_on_declared_default(
    accounts: tuple[ProfileStore, plan_registry.PlanRegistry],
) -> None:
    assert infer_source("openai", model="gpt-6-sol") == "payg"
    assert resolve_routing("gpt-6-sol") is None
    with pytest.raises(RuntimeError, match="no registered credential route"):
        infer_source("unregistered")


def test_capture_uses_supplied_settings_without_global_policy_broadcast(
    accounts, monkeypatch
) -> None:
    from core.config.session import capture_session_model_config

    _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    monkeypatch.setattr(settings, "forced_login_method", {"openai": "subscription"})
    candidate = settings.model_copy(
        update={
            "cognitive_reflection_model": "gpt-6-luna",
            "judge_model": "gpt-6-sol",
            "openai_credential_source": "auto",
            "forced_login_method": {"openai": "apikey"},
        }
    )
    record = capture_session_model_config(
        candidate,
        model="claude-fable-5-1",
        effort="low",
        source="payg",
    )
    assert record.reflection_source == record.judge_source == "payg"
    assert settings.forced_login_method == {"openai": "subscription"}


def test_billing_metadata_preserves_the_failed_concrete_route(accounts, monkeypatch) -> None:
    from core.llm.fallback import _resolve_plan_for_billing_error

    payg = _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    monkeypatch.setattr(settings, "openai_credential_source", "oauth")
    meta = _resolve_plan_for_billing_error("gpt-6-sol", provider="openai", source="payg")
    assert meta["plan_id"] == payg.id
    assert infer_source("openai", model="gpt-6-sol") == "subscription"


@pytest.mark.parametrize("explicit", [False, True])
def test_capture_and_standalone_dispatch_share_composed_model_policy(
    accounts,
    monkeypatch,
    tmp_path,
    explicit: bool,
) -> None:
    import json

    from core.config.policy_source import PolicySourcePaths
    from core.config.session import capture_session_model_config
    from core.llm.adapters.dispatch import _resolve_dispatch_route
    from core.llm.adapters.registry import registry_snapshot

    payg = _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({"gpt-6-sol": [payg.id]}))
    sources = PolicySourcePaths(
        "TEST_OVERRIDE", explicit_override=path, explicit_override_strict=True
    )
    for adapter in registry_snapshot().list_adapters():
        if adapter.provider == "openai":
            monkeypatch.setattr(adapter, "routing_sources", sources)
    monkeypatch.setattr(settings, "cognitive_reflection_model", "gpt-6-sol")
    monkeypatch.setattr(settings, "judge_model", "gpt-6-sol")
    record = capture_session_model_config(
        settings,
        model="claude-fable-5-1",
        effort="low",
        source="payg",
        sources=sources if explicit else None,
    )
    assert record.reflection_source == record.judge_source == "payg"
    assert _resolve_dispatch_route(prefer_provider=None, prefer_source=None, model="gpt-6-sol") == (
        "openai",
        "payg",
    )
    target = resolve_routing(
        record.reflection_model, source=record.reflection_source, sources=sources
    )
    assert target is not None and target.plan is payg


def test_picker_model_sources_follow_each_model_plan(accounts) -> None:
    from core.cli.commands._state import get_model_profiles

    payg = _add(accounts, "openai")
    _add(accounts, "openai-codex", subscription=True)
    accounts[1].set_routing("gpt-5.4", [payg.id])
    rows = get_model_profiles()
    assert "gpt-5.4" in {row.id for row in rows}
    assert "gpt-5.4-mini" not in {row.id for row in rows}
