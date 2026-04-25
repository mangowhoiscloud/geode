"""Phase 2 — Plan + ProviderSpec + PlanRegistry data model tests."""

from __future__ import annotations

from core.gateway.auth.plan_registry import (
    PlanRegistry,
    get_plan_registry,
    reset_plan_registry,
    resolve_routing,
)
from core.gateway.auth.plans import (
    GLM_CODING_TIERS,
    Plan,
    PlanKind,
    PlanUsage,
    default_plan_for_payg,
)
from core.gateway.auth.profiles import AuthProfile, CredentialType
from core.llm.registry import PROVIDER_VARIANTS, get_provider_spec


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


class TestGlmCodingTiers:
    def test_lite_pro_max_present(self) -> None:
        for tier in ("lite", "pro", "max"):
            assert tier in GLM_CODING_TIERS

    def test_lite_quota_matches_published_limits(self) -> None:
        # 5h window, 80 calls (post-2026-02-12 reduction)
        plan = GLM_CODING_TIERS["lite"]
        assert plan.quota is not None
        assert plan.quota.window_s == 18_000
        assert plan.quota.max_calls == 80
        assert plan.quota.model_weights["glm-5.1"] == 3.0

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
    def test_quota_unset_means_unlimited(self) -> None:
        plan = default_plan_for_payg("openai", "sk-...")
        usage = PlanUsage(plan_id=plan.id)
        assert usage.is_quota_exhausted(plan) is False
        assert usage.remaining_in_window(plan) == -1

    def test_quota_exhausted_after_max_calls(self) -> None:
        plan = GLM_CODING_TIERS["lite"]
        usage = PlanUsage(plan_id=plan.id, weighted_calls=80.0)
        assert usage.is_quota_exhausted(plan) is True
        assert usage.remaining_in_window(plan) == 0


class TestResolveRouting:
    def test_falls_back_to_payg_when_no_plan_registered(self) -> None:
        # Reset state for a clean test
        from core.runtime_wiring.infra import build_auth

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
        from core.runtime_wiring.infra import build_auth

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
        plan = GLM_CODING_TIERS["lite"]
        assert plan.quota is not None
        assert plan.quota.model_weights["glm-5.1"] >= 3.0
