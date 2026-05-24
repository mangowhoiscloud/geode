"""Provider-label invariants — the bug class that motivated v0.50.0.

Before v0.50.0 the provider string was spelled four different ways across
runtime/UI/dispatch (`"openai"` for both API keys and Codex OAuth, `"glm"`
in the dispatch but `"zhipuai"` in the UI store). The Codex OAuth token
therefore matched `ProfileRotator.resolve("openai")` and poisoned every
plain GPT call. These tests pin the labels so a future rename can't
silently re-open the cross-provider leak.

PR-MAINPATH-67 (2026-05-24) — the legacy ``_ADAPTER_MAP`` was deleted
alongside ``resolve_agentic_adapter``; the adapter alignment test now
walks the Path-B registry (``list_adapters``) instead.
"""

from __future__ import annotations

from core.cli.commands import MODEL_PROFILES
from core.config import _resolve_provider

from core.llm import adapters as _adapters_mod

# Path-B registry collapses ``openai-codex`` onto ``openai`` (the source
# axis encodes the Codex distinction) and ``zhipuai`` onto ``glm``.
_LEGACY_TO_REGISTRY = {"openai-codex": "openai", "zhipuai": "glm"}


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


class TestAdapterRegistryAlignment:
    def test_every_resolver_target_has_a_registered_adapter(self) -> None:
        """Every provider returned by :func:`_resolve_provider` must be
        registered in the Path-B adapter registry (after the
        ``openai-codex`` / ``zhipuai`` normalisation that
        ``AgenticLoop.__init__`` applies)."""
        from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins, list_adapters

        _reset_for_test()
        bootstrap_builtins()
        registered = {entry.provider for entry in list_adapters()}

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
            registry_key = _LEGACY_TO_REGISTRY.get(provider, provider)
            assert registry_key in registered, (provider, registry_key, registered)


class TestCrossProviderFallbackSafety:
    def test_cross_provider_fallback_shim_removed(self) -> None:
        """v0.99.19 — the empty-dict ``CROSS_PROVIDER_FALLBACK`` shim is
        deleted. Re-introducing it would invite a code path that silently
        diverts to a different provider on quota / billing failure."""
        assert not hasattr(_adapters_mod, "CROSS_PROVIDER_FALLBACK"), (
            "CROSS_PROVIDER_FALLBACK resurfaced — silent provider swap is "
            "globally forbidden. On quota exhaustion the agentic loop fires "
            "``quota_exhausted`` and the user picks a new model via /model."
        )


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
        # v0.53.0 — provider label MUST equal the canonical provider ID
        # (lowercase ``glm``), matching /login dashboard + auth.toml +
        # rotator dispatch key. Pre-fix used capitalised "GLM" which
        # diverged from the dispatch key. v0.50 originally moved away
        # from "ZhipuAI" → "GLM"; v0.53.0 finishes by lowercasing.
        for profile in MODEL_PROFILES:
            if profile.id.startswith("glm-"):
                assert profile.provider == "glm", profile.id
