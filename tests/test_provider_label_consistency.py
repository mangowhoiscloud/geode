"""Provider-label invariants — the bug class that motivated v0.50.0.

Before v0.50.0 the provider string was spelled four different ways across
runtime/UI/dispatch (`"openai"` for both API keys and Codex OAuth, `"glm"`
in the dispatch but `"zhipuai"` in the UI store). The Codex OAuth token
therefore matched `ProfileRotator.resolve("openai")` and poisoned every
plain GPT call. These tests pin the labels so a future rename can't
silently re-open the cross-provider leak.
"""

from __future__ import annotations

from core.cli.commands import MODEL_PROFILES
from core.config import _resolve_provider
from core.llm.adapters import _ADAPTER_MAP, CROSS_PROVIDER_FALLBACK


class TestProviderRouting:
    def test_codex_models_route_to_openai_codex(self) -> None:
        for model in ("gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex-mini"):
            assert _resolve_provider(model) == "openai-codex", model

    def test_general_openai_models_do_not_route_to_codex(self) -> None:
        for model in ("gpt-5.4", "gpt-5.4-mini", "gpt-4.1", "o3-mini"):
            assert _resolve_provider(model) == "openai", model

    def test_glm_models_route_to_glm(self) -> None:
        for model in ("glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7-flash"):
            assert _resolve_provider(model) == "glm", model

    def test_anthropic_models_route_to_anthropic(self) -> None:
        for model in ("claude-opus-4-7", "claude-sonnet-4-6"):
            assert _resolve_provider(model) == "anthropic", model


class TestAdapterMapAlignment:
    def test_every_resolver_target_has_an_adapter(self) -> None:
        targets = {
            _resolve_provider(m)
            for m in (
                "claude-opus-4-7",
                "gpt-5.4",
                "gpt-5.3-codex",
                "glm-5.1",
            )
        }
        for provider in targets:
            assert provider in _ADAPTER_MAP, provider


class TestCrossProviderFallbackSafety:
    def test_glm_does_not_auto_fall_back(self) -> None:
        # GLM Coding Plan auth errors must not silently divert to a metered
        # OpenAI key. Cross-plan jumps are an explicit user choice in v0.50+.
        assert CROSS_PROVIDER_FALLBACK.get("glm") == []

    def test_openai_codex_does_not_auto_fall_back(self) -> None:
        # Codex OAuth scope is unique to chatgpt.com/backend-api; silently
        # retrying on a PAYG provider would surprise the user with billing.
        assert CROSS_PROVIDER_FALLBACK.get("openai-codex") == []


class TestModelProfileLabels:
    def test_gpt_5_4_mini_is_not_labelled_codex(self) -> None:
        # Pre-0.50 the UI showed "Codex (Plus)" for gpt-5.4-mini even though
        # it routes to plain "openai". Users were billed PAYG while believing
        # they were on the Plus subscription.
        for profile in MODEL_PROFILES:
            if profile.id == "gpt-5.4-mini":
                assert "Codex" not in profile.provider, (
                    "gpt-5.4-mini routes to PAYG OpenAI, must not advertise Codex"
                )
                return
        raise AssertionError("gpt-5.4-mini missing from MODEL_PROFILES")

    def test_glm_models_use_glm_provider_label(self) -> None:
        # The UI label must match the dispatch provider (`glm`); pre-0.50
        # the UI said "ZhipuAI" while dispatch keyed off "glm" so the
        # /auth interactive add path stored credentials the rotator never
        # found.
        for profile in MODEL_PROFILES:
            if profile.id.startswith("glm-"):
                assert profile.provider == "GLM", profile.id
