"""Phase 2 — Plan + ProviderSpec + PlanRegistry data model tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from core.auth.profiles import AuthProfile, CredentialType
from core.llm.registry import (
    PROVIDER_VARIANTS,
    CredentialRoute,
    ProviderProfile,
    TransportSpec,
    get_provider_spec,
)
from core.llm.strategies.plan_registry import (
    PlanRegistry,
    get_plan_registry,
    reset_plan_registry,
    resolve_payg_profile,
    resolve_routing,
)
from core.llm.strategies.plans import (
    GLM_CODING_TIERS,
    Plan,
    PlanKind,
    PlanUsage,
    Quota,
    default_plan_for_payg,
)


@pytest.fixture
def payg_selection(monkeypatch: pytest.MonkeyPatch):
    from core.auth.profiles import ProfileStore
    from core.llm.strategies import plan_registry
    from core.wiring import container

    registry, store = PlanRegistry(), ProfileStore()
    monkeypatch.setattr(plan_registry, "_plan_registry", registry)
    monkeypatch.setattr(container, "_profile_store", store)
    plan = default_plan_for_payg("openai", "fixture")
    profile = AuthProfile(
        "openai:work", "openai", CredentialType.API_KEY, key="fixture", plan_id=plan.id
    )
    registry.add(plan)
    store.add(profile)
    return registry, store, plan, profile


@pytest.mark.parametrize(
    "change",
    ["oauth", "subscription", "provider", "unbound", "managed", "disabled", "empty", "endpoint"],
)
def test_payg_selection_never_borrows_an_ineligible_or_other_route_profile(
    payg_selection, change: str
) -> None:
    registry, store, plan, profile = payg_selection
    base_url = plan.base_url
    if change == "oauth":
        profile.credential_type = CredentialType.OAUTH
    elif change == "subscription":
        registry.add(replace(plan, kind=PlanKind.SUBSCRIPTION))
    elif change == "provider":
        registry.add(replace(plan, provider="openai-codex"))
    elif change == "unbound":
        profile.plan_id = "missing"
    elif change == "managed":
        profile.managed_by = "external-cli"
    elif change == "disabled":
        profile.disabled = True
    elif change == "empty":
        profile.key = ""
    elif change == "endpoint":
        profile.base_url_override = "https://other.invalid/v1"
    store.set_active(profile.name)
    assert resolve_payg_profile("openai", base_url=base_url) is None


def test_payg_selection_respects_pin_order_availability_and_effective_endpoint(
    payg_selection,
) -> None:
    _registry, store, plan, first = payg_selection
    second = replace(first, name="openai:second", key="second", last_used=100)
    store.add(second)
    assert resolve_payg_profile("openai", base_url=plan.base_url) is first
    store.set_active(second.name)
    assert resolve_payg_profile("openai", base_url=plan.base_url) is second
    store.set_auth_order("openai", [first.name, second.name])
    assert resolve_payg_profile("openai", base_url=plan.base_url) is first
    first.disabled = True
    assert resolve_payg_profile("openai", base_url=plan.base_url) is second
    second.base_url_override = "https://relay.invalid/v1/"
    assert resolve_payg_profile("openai", base_url=plan.base_url) is None
    assert resolve_payg_profile("openai", base_url="https://relay.invalid/v1") is second


class TestProviderRegistry:
    def test_required_variants_registered(self) -> None:
        for v in ("anthropic", "openai", "openai-codex", "glm", "glm-coding"):
            assert v in PROVIDER_VARIANTS, v

    def test_codex_variant_targets_chatgpt_backend(self) -> None:
        spec = get_provider_spec("openai-codex")
        assert spec is not None
        assert "chatgpt.com/backend-api" in spec.default_base_url
        assert spec.auth_type == "oauth_external"

    def test_glm_coding_variant_uses_coding_endpoint(self) -> None:
        spec = get_provider_spec("glm-coding")
        assert spec is not None
        assert "coding/paas/v4" in spec.default_base_url

    def test_glm_payg_variant_uses_paas_endpoint(self) -> None:
        spec = get_provider_spec("glm")
        assert spec is not None
        assert "/paas/v4" in spec.default_base_url
        assert "/coding/" not in spec.default_base_url

    def test_variants_compose_separate_immutable_records(self) -> None:
        codex = PROVIDER_VARIANTS["openai-codex"]
        assert isinstance(codex.profile, ProviderProfile)
        assert isinstance(codex.credential, CredentialRoute)
        assert isinstance(codex.transport, TransportSpec)
        assert codex.profile.provider == "openai"
        assert codex.profile.default_model() == "gpt-6-sol"
        assert codex.credential.account_provider == "openai-codex"
        assert codex.credential.selector == "codex-oauth"
        assert codex.transport.api == "openai-responses"
        assert codex.transport.retry_policy == "agentic-loop"
        assert codex.credential.quota_policy == "codex-usage"


class TestGlmCodingTiers:
    def test_lite_pro_max_present(self) -> None:
        for tier in ("lite", "pro", "max"):
            assert tier in GLM_CODING_TIERS

    def test_credit_quota_is_not_invented_as_a_local_call_limit(self) -> None:
        for plan in GLM_CODING_TIERS.values():
            assert plan.quota is None
            usage = PlanUsage(plan_id=plan.id, weighted_calls=80.0)
            assert not usage.is_quota_exhausted(plan)
            assert usage.remaining_in_window(plan) == -1

    def test_subscription_kind(self) -> None:
        for plan in GLM_CODING_TIERS.values():
            assert plan.kind == PlanKind.SUBSCRIPTION
            assert plan.upgrade_url


class TestPlanRegistry:
    def test_add_get_remove(self) -> None:
        reg = PlanRegistry()
        plan = Plan(
            id="t1",
            provider="openai",
            kind=PlanKind.PAYG,
            display_name="Test PAYG",
            base_url="https://example.test/v1",
        )
        reg.add(plan)
        assert reg.get("t1") is plan
        assert reg.remove("t1") is True
        assert reg.get("t1") is None

    def test_routing_chain(self) -> None:
        reg = PlanRegistry()
        reg.set_routing("glm-5.1", ["glm-coding-lite", "glm-payg"])
        assert reg.get_routing("glm-5.1") == ["glm-coding-lite", "glm-payg"]

    def test_remove_clears_routing_for_plan(self) -> None:
        reg = PlanRegistry()
        plan = GLM_CODING_TIERS["lite"]
        reg.add(plan)
        reg.set_routing("glm-5.1", [plan.id])
        reg.remove(plan.id)
        assert reg.get_routing("glm-5.1") == []


class TestPlanUsage:
    def test_quota_unset_means_no_known_local_limit(self) -> None:
        plan = default_plan_for_payg("openai", "sk-...")
        usage = PlanUsage(plan_id=plan.id)
        assert usage.is_quota_exhausted(plan) is False
        assert usage.remaining_in_window(plan) == -1

    def test_quota_exhausted_after_max_calls(self) -> None:
        plan = replace(GLM_CODING_TIERS["lite"], quota=Quota(window_s=18_000, max_calls=80))
        usage = PlanUsage(plan_id=plan.id, weighted_calls=80.0)
        assert usage.is_quota_exhausted(plan) is True
        assert usage.remaining_in_window(plan) == 0


class TestResolveRouting:
    def test_falls_back_to_payg_when_no_plan_registered(self) -> None:
        # Reset state for a clean test
        from core.wiring.container import build_auth

        reset_plan_registry()
        store, _, _ = build_auth()

        # Ensure at least an anthropic profile exists for the fallback path
        store.add(
            AuthProfile(
                name="anthropic:test-routing",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key="sk-ant-test-routing",
            )
        )

        target = resolve_routing("claude-opus-4-7")
        assert target is not None
        assert target.plan.provider == "anthropic"
        assert target.plan.kind == PlanKind.PAYG

    def test_explicit_plan_routing_takes_precedence(self) -> None:
        from core.wiring.container import build_auth

        reset_plan_registry()
        store, _, _ = build_auth()

        registry = get_plan_registry()
        plan = GLM_CODING_TIERS["lite"]
        registry.add(plan)

        store.add(
            AuthProfile(
                name="glm-coding:test",
                provider="glm-coding",
                credential_type=CredentialType.API_KEY,
                key="zai-coding-test",
                plan_id=plan.id,
            )
        )
        registry.set_routing("glm-5.1", [plan.id])

        target = resolve_routing("glm-5.1")
        assert target is not None
        assert target.plan.id == "glm-coding-lite"
        assert "coding/paas/v4" in target.base_url

    def test_quota_models_are_aware_of_weights(self) -> None:
        # Explicit operator metadata remains readable for existing records.
        plan = replace(
            GLM_CODING_TIERS["lite"],
            quota=Quota(window_s=18_000, max_calls=80, model_weights={"glm-5.1": 3.0}),
        )
        assert plan.quota is not None
        assert plan.quota.model_weights["glm-5.1"] >= 3.0
