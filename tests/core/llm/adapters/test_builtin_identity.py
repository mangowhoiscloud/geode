"""Identity invariants for each built-in adapter.

These tests pin the (name, provider, source, billing_type) tuple for each
shipped adapter. They DO NOT exercise the actual SDK call path —
that requires live credentials and is out of scope for the unit suite. The
acomplete path is covered by integration tests in the adapter migration
follow-up PRs.

The invariants here guard against accidental renames that would silently break
operator overrides and the UI's adapter list.

v0.99.44 — Follow-up F adds the two GLM adapters (PAYG + Coding Plan).
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator
from core.config import GLM_PRIMARY
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.base import (
    AdapterBillingType,
    CredentialDetectionCapable,
    EnvironmentDiagnosticCapable,
    ModelListingCapable,
    QuotaInspectionCapable,
    StreamingCapable,
)
from core.llm.adapters.codex_oauth import CodexOAuthAdapter
from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter, _resolve_coding_plan_endpoint
from core.llm.adapters.glm_payg import GlmPaygAdapter
from core.llm.adapters.openai_payg import OpenAIPaygAdapter
from core.llm.strategies.plan_registry import PlanRegistry
from core.llm.strategies.plans import GLM_CODING_TIERS, PlanKind


@pytest.mark.parametrize(
    ("cls", "expected_name", "expected_provider", "expected_source", "expected_billing"),
    [
        (AnthropicPaygAdapter, "anthropic-payg", "anthropic", "payg", AdapterBillingType.API),
        (OpenAIPaygAdapter, "openai-payg", "openai", "payg", AdapterBillingType.API),
        (
            CodexOAuthAdapter,
            "codex-oauth",
            "openai",
            "subscription",
            AdapterBillingType.SUBSCRIPTION,
        ),
        (GlmPaygAdapter, "glm-payg", "glm", "payg", AdapterBillingType.API),
        (
            GlmCodingPlanAdapter,
            "glm-coding-plan",
            "glm",
            "subscription",
            AdapterBillingType.SUBSCRIPTION,
        ),
    ],
)
def test_adapter_identity(
    cls: type,
    expected_name: str,
    expected_provider: str,
    expected_source: str,
    expected_billing: AdapterBillingType,
) -> None:
    instance = cls()
    assert instance.name == expected_name
    assert instance.provider == expected_provider
    assert instance.source == expected_source
    assert instance.billing_type is expected_billing
    assert isinstance(instance, StreamingCapable)
    assert isinstance(instance, EnvironmentDiagnosticCapable)
    assert isinstance(instance, ModelListingCapable)
    assert not isinstance(instance, QuotaInspectionCapable)
    assert isinstance(instance, CredentialDetectionCapable)


def test_test_environment_returns_report() -> None:
    """Every adapter's test_environment returns an EnvironmentReport (no raise).

    Adapters may report ok=False when credentials are missing — that's a valid
    outcome. We just confirm the surface doesn't raise on a fresh process.
    """
    for cls in (
        AnthropicPaygAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        GlmPaygAdapter,
        GlmCodingPlanAdapter,
    ):
        report = cls().test_environment()
        # Either ok=True with credentials available, or ok=False with hints.
        if not report.ok:
            assert report.hints, f"{cls.__name__}: ok=False but no hints"


def test_list_models_returns_specs() -> None:
    from core.llm.model_catalog import context_window_for

    for cls in (
        AnthropicPaygAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        GlmPaygAdapter,
        GlmCodingPlanAdapter,
    ):
        models = cls().list_models()
        if cls is GlmCodingPlanAdapter:
            assert models == []  # The persisted route is not eligible for GEODE.
            continue
        assert models, f"{cls.__name__}: list_models returned empty list"
        for m in models:
            assert m.id
            assert m.context_tokens > 0
            assert m.context_tokens == context_window_for(m.id), (
                f"{cls.__name__}.{m.id} must derive context_tokens from model_catalog"
            )


@pytest.mark.parametrize(
    ("plan_provider", "plan_kind", "profile_provider", "accepted"),
    [
        ("glm-coding", PlanKind.SUBSCRIPTION, "glm-coding", True),
        ("glm", PlanKind.PAYG, "glm", False),
        ("glm-coding", PlanKind.PAYG, "glm-coding", False),
        ("glm", PlanKind.SUBSCRIPTION, "glm", False),
        ("openai-codex", PlanKind.SUBSCRIPTION, "openai-codex", False),
        ("unknown", PlanKind.SUBSCRIPTION, "unknown", False),
        ("glm-coding", PlanKind.SUBSCRIPTION, "glm", False),
    ],
)
def test_coding_plan_route_preserves_subscription_identity(
    monkeypatch: pytest.MonkeyPatch,
    plan_provider: str,
    plan_kind: PlanKind,
    profile_provider: str,
    accepted: bool,
) -> None:
    from core.llm.adapters import glm_coding_plan
    from core.llm.errors import ModelSourceUnavailableError
    from core.llm.strategies import plan_registry, provider_routing_policy
    from core.wiring import container

    plan = replace(GLM_CODING_TIERS["pro"], provider=plan_provider, kind=plan_kind)
    endpoint = "https://example.invalid/operator-configured-endpoint"
    profile = AuthProfile(
        name="synthetic-profile",
        provider=profile_provider,
        credential_type=CredentialType.API_KEY,
        key="synthetic-key",
        plan_id=plan.id,
        base_url_override=endpoint,
    )
    store = ProfileStore()
    store.add(profile)
    registry = PlanRegistry()
    registry.add(plan)
    registry.set_routing(GLM_PRIMARY, [plan.id])
    monkeypatch.setattr(container, "get_profile_store", lambda: store)
    monkeypatch.setattr(container, "get_profile_rotator", lambda: ProfileRotator(store))
    monkeypatch.setattr(plan_registry, "get_plan_registry", lambda: registry)
    monkeypatch.setattr(provider_routing_policy, "_load_provider_routing_override", lambda **kw: {})
    build_client = Mock(return_value=object())
    monkeypatch.setattr(glm_coding_plan, "build_async_openai_client", build_client)

    adapter = GlmCodingPlanAdapter()
    assert _resolve_coding_plan_endpoint() == ((profile.key, endpoint) if accepted else ("", ""))
    assert adapter.detect_credential() is None
    assert not adapter.test_environment().ok
    with pytest.raises(ModelSourceUnavailableError, match="GEODE"):
        adapter._get_client()
    build_client.assert_not_called()
