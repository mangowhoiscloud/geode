"""Model-id mapping tests for petri_audit (no [audit] extra needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from evals.petri.models import (
    AuditModelMappingError,
    list_audit_models,
    to_inspect_model,
    to_inspect_target,
)

# ---------------------------------------------------------------------------
# to_inspect_model — auditor / judge alias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geode_id, expected",
    [
        ("claude-opus-4-7", "anthropic/claude-opus-4-7"),
        ("claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
        ("claude-haiku-4-5-20251001", "anthropic/claude-haiku-4-5-20251001"),
        ("gpt-5.5", "openai/gpt-5.5"),
        ("gpt-5.4-mini", "openai/gpt-5.4-mini"),
        ("o3", "openai/o3"),
        ("o4-mini", "openai/o4-mini"),
        ("glm-5", "geode/glm-5"),
        ("glm-4.7-flash", "geode/glm-4.7-flash"),
    ],
)
def test_to_inspect_model_known_providers(geode_id: str, expected: str) -> None:
    # PR #6 (2026-05-14) — pin ``use_oauth=False`` so the legacy
    # ``openai/<model>`` mapping is exercised regardless of whether the
    # test runner has a Codex OAuth token in the environment. The
    # auto-detect path is covered in tests/evals/petri/
    # test_oauth_judge.py.
    assert to_inspect_model(geode_id, use_oauth=False) == expected


def test_to_inspect_model_raw_passthrough() -> None:
    raw = "openai-api/glm/glm-5.1"
    assert to_inspect_model(raw) == raw
    assert to_inspect_model("anthropic/claude-haiku-4-5-20251001") == (
        "anthropic/claude-haiku-4-5-20251001"
    )


def test_to_inspect_model_unknown_raises() -> None:
    with pytest.raises(AuditModelMappingError, match="Unknown model id"):
        to_inspect_model("mystery-model")


def test_to_inspect_model_empty_raises() -> None:
    with pytest.raises(AuditModelMappingError, match="Empty model id"):
        to_inspect_model("")


# ---------------------------------------------------------------------------
# to_inspect_target — always geode/<base>
# ---------------------------------------------------------------------------


def test_to_inspect_target_auto_prefixes() -> None:
    assert to_inspect_target("claude-opus-4-7") == "geode/claude-opus-4-7"
    assert to_inspect_target("gpt-5.5") == "geode/gpt-5.5"
    assert to_inspect_target("glm-5") == "geode/glm-5"


def test_to_inspect_target_raw_passthrough() -> None:
    assert to_inspect_target("geode/claude-opus-4-7") == "geode/claude-opus-4-7"
    assert to_inspect_target("anthropic/claude-opus-4-7") == "anthropic/claude-opus-4-7"


@pytest.mark.parametrize("prefix", ["claude-cli", "claude-code"])
def test_to_inspect_target_rejects_retired_claude_cli_prefix(prefix: str) -> None:
    with pytest.raises(AuditModelMappingError, match="integration is retired"):
        to_inspect_target(f"{prefix}/claude-opus-4-7")


def test_to_inspect_target_none_returns_default_sentinel() -> None:
    """N6-followup: None / empty → ``geode/default`` sentinel."""
    assert to_inspect_target(None) == "geode/default"
    assert to_inspect_target("") == "geode/default"


# ---------------------------------------------------------------------------
# list_audit_models — catalog enumeration
# ---------------------------------------------------------------------------


def test_list_audit_models_includes_each_provider() -> None:
    pairs = list_audit_models()
    inspect_ids = {inspect for _, inspect in pairs}
    assert any(i.startswith("anthropic/claude-") for i in inspect_ids)
    # PR #6 — gpt-* now resolves to ``openai-codex/`` when a token is
    # available, or ``openai/`` when not. Accept either form so the
    # test passes in both environments.
    assert any(
        i.startswith("openai/gpt-") or i.startswith("openai-codex/gpt-") for i in inspect_ids
    )
    assert any(i.startswith("geode/glm-") for i in inspect_ids)


def test_list_audit_models_pairs_with_pricing_keys() -> None:
    """Every pair's geode_id is a MODEL_PRICING key (catalog SOT)."""
    from core.llm.token_tracker import MODEL_PRICING

    for geode_id, _ in list_audit_models():
        assert geode_id in MODEL_PRICING


# ---------------------------------------------------------------------------
# Credential-source routing — anthropic side (claude-* ids)
# ---------------------------------------------------------------------------


def test_claude_use_oauth_true_stays_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "api_key", raising=False)
    assert to_inspect_model("claude-opus-4-7", use_oauth=True) == "anthropic/claude-opus-4-7"


def test_claude_oauth_explicit_off_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``use_oauth=False`` forces ``anthropic/`` regardless of settings."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "oauth", raising=False)
    assert to_inspect_model("claude-opus-4-7", use_oauth=False) == "anthropic/claude-opus-4-7"


def test_claude_source_oauth_is_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "oauth", raising=False)
    with pytest.raises(RuntimeError, match="integration is retired"):
        to_inspect_model("claude-sonnet-4-6")


def test_claude_source_api_key_routes_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """``settings.anthropic_credential_source = 'api_key'`` keeps the
    stock ``anthropic/`` prefix."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "api_key", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert to_inspect_model("claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_claude_source_auto_uses_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic auto has one built-in destination: API key."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "auto", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert to_inspect_model("claude-opus-4-7") == "anthropic/claude-opus-4-7"


# ---------------------------------------------------------------------------
# Credential-source routing — openai side (gpt-5.* ids)
# ---------------------------------------------------------------------------


def test_gpt_source_oauth_routes_to_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    """``settings.openai_credential_source = 'oauth'`` routes ``gpt-5.*``
    through ``openai-codex/`` (ChatGPT subscription quota)."""
    from core.config import settings

    monkeypatch.setattr(settings, "openai_credential_source", "oauth", raising=False)
    assert to_inspect_model("gpt-5.5") == "openai-codex/gpt-5.5"


def test_legacy_codex_cli_identifier_normalizes() -> None:
    with pytest.warns(DeprecationWarning, match="legacy alias"):
        assert to_inspect_model("codex-cli/gpt-5.5") == "openai-codex/gpt-5.5"


def test_legacy_claude_code_identifier_is_retired() -> None:
    with pytest.raises(AuditModelMappingError, match="integration is retired"):
        to_inspect_model("claude-code/claude-opus-4-7")


def test_gpt_source_api_key_routes_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key`` keeps the PAYG path even with a Codex token present."""
    from core.config import settings
    from evals.petri.adapters import openai_codex_oauth

    monkeypatch.setattr(settings, "openai_credential_source", "api_key", raising=False)
    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    assert to_inspect_model("gpt-5.5") == "openai/gpt-5.5"


@pytest.fixture
def strict_mapping_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from core.config import settings
    from evals.petri import credential_source as cs

    config = tmp_path / "config.toml"
    config.write_text("[self_improving_loop]\nfallback_to_payg = false\n", encoding="utf-8")
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(config))
    monkeypatch.setattr(settings, "openai_credential_source", "auto")
    monkeypatch.setattr(cs, "is_suppressed", lambda provider, source: False)
    monkeypatch.setattr(cs, "is_adapter_available", lambda provider, source: True)
    return config


@pytest.mark.policy_real
@pytest.mark.usefixtures("strict_mapping_policy")
class TestStrictMappingPolicy:
    @pytest.mark.parametrize("model", ["gpt-6-astra", "o3", "o4-mini"])
    def test_forced_oauth_does_not_become_payg(self, model: str) -> None:
        with pytest.raises(AuditModelMappingError, match=r"audit.*mapping"):
            to_inspect_model(model, use_oauth=True)

    @pytest.mark.parametrize("model", ["gpt-6-astra", "o3", "o4-mini"])
    def test_auto_oauth_unmapped_id_does_not_become_payg(self, model: str) -> None:
        with pytest.raises(AuditModelMappingError, match=r"audit.*mapping"):
            to_inspect_model(model)

    def test_no_oauth_does_not_authorize_payg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evals.petri import credential_source as cs

        monkeypatch.setattr(
            cs, "is_adapter_available", lambda provider, source: source == "api_key"
        )
        with pytest.raises(cs.CredentialResolutionError) as excinfo:
            to_inspect_model("gpt-6-astra")
        assert excinfo.value.subscription_only is True

    @pytest.mark.parametrize("authorization", ["source", "use_oauth", "settings"])
    def test_explicit_payg_remains_allowed(
        self, monkeypatch: pytest.MonkeyPatch, authorization: str
    ) -> None:
        from core.config import settings

        if authorization == "source":
            actual = to_inspect_model("gpt-6-astra", source="api_key", use_oauth=True)
        elif authorization == "use_oauth":
            actual = to_inspect_model("gpt-6-astra", use_oauth=False)
        else:
            monkeypatch.setattr(settings, "openai_credential_source", "api_key")
            actual = to_inspect_model("gpt-6-astra")
        assert actual == "openai/gpt-6-astra"

    @pytest.mark.parametrize("authorization", ["source", "settings", "legacy_settings"])
    @pytest.mark.parametrize("fallback", [False, True])
    def test_concrete_oauth_pin_bypasses_only_the_name_heuristic(
        self,
        strict_mapping_policy: Path,
        monkeypatch: pytest.MonkeyPatch,
        authorization: str,
        fallback: bool,
    ) -> None:
        from core.config import settings

        strict_mapping_policy.write_text(
            f"[self_improving_loop]\nfallback_to_payg = {str(fallback).lower()}\n",
            encoding="utf-8",
        )
        if authorization == "source":
            actual = to_inspect_model("gpt-6-astra", source="openai-codex")
        else:
            monkeypatch.setattr(
                settings,
                "openai_credential_source",
                "oauth" if authorization == "legacy_settings" else "openai-codex",
            )
            actual = to_inspect_model("gpt-6-astra")
        assert actual == "openai-codex/gpt-6-astra"

    def test_concrete_oauth_pin_still_obeys_source_suppression(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evals.petri import credential_source as cs

        monkeypatch.setattr(cs, "is_suppressed", lambda provider, source: source == "openai-codex")
        with pytest.raises(cs.CredentialResolutionError) as excinfo:
            to_inspect_model("gpt-6-astra", source="openai-codex")
        assert excinfo.value.subscription_only is True

    @pytest.mark.parametrize("source", ["unregistered", "api_key"])
    def test_non_subscription_resolution_errors_are_not_payg_authority(
        self, monkeypatch: pytest.MonkeyPatch, source: str
    ) -> None:
        from evals.petri import credential_source as cs

        monkeypatch.setattr(cs, "is_suppressed", lambda provider, source: True)
        with pytest.raises(cs.CredentialResolutionError) as excinfo:
            to_inspect_model("gpt-6-astra", source=source)
        assert excinfo.value.subscription_only is False

    @pytest.mark.parametrize("model", ["gpt-6-astra", "o3", "o4-mini"])
    def test_explicit_fallback_policy_preserves_legacy_auto_mapping(
        self, strict_mapping_policy: Path, model: str
    ) -> None:
        strict_mapping_policy.write_text(
            "[self_improving_loop]\nfallback_to_payg = true\n", encoding="utf-8"
        )
        assert to_inspect_model(model) == f"openai/{model}"

    @pytest.mark.parametrize("model", ["gpt-5.5", "gpt-6-astra"])
    def test_payg_fallback_does_not_revive_suppressed_sources(
        self,
        strict_mapping_policy: Path,
        monkeypatch: pytest.MonkeyPatch,
        model: str,
    ) -> None:
        from evals.petri import credential_source as cs

        strict_mapping_policy.write_text(
            "[self_improving_loop]\nfallback_to_payg = true\n", encoding="utf-8"
        )
        monkeypatch.setattr(cs, "is_suppressed", lambda provider, source: True)
        with pytest.raises(cs.CredentialResolutionError) as excinfo:
            to_inspect_model(model)
        assert excinfo.value.subscription_only is False

    def test_explicit_api_key_mapping_does_not_require_key_availability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evals.petri import credential_source as cs

        monkeypatch.setattr(cs, "is_adapter_available", lambda provider, source: False)
        assert to_inspect_model("gpt-5.5", source="api_key") == "openai/gpt-5.5"

    def test_enabled_payg_fallback_still_requires_an_available_source(
        self, strict_mapping_policy: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evals.petri import credential_source as cs

        strict_mapping_policy.write_text(
            "[self_improving_loop]\nfallback_to_payg = true\n", encoding="utf-8"
        )
        monkeypatch.setattr(cs, "is_adapter_available", lambda provider, source: False)
        with pytest.raises(cs.CredentialResolutionError):
            to_inspect_model("gpt-5.5")

    def test_missing_subscription_adapter_does_not_select_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evals.petri import manifest as manifest_module

        manifest = manifest_module.load_manifest()
        unavailable = Mock(wraps=manifest)
        unavailable.get_adapter.side_effect = [
            KeyError("missing subscription adapter"),
            manifest.get_adapter("openai", "api_key"),
        ]
        monkeypatch.setattr(manifest_module, "load_manifest", lambda: unavailable)
        with pytest.raises(KeyError, match="missing subscription adapter"):
            to_inspect_model("gpt-5.5", source="openai-codex")
        unavailable.get_adapter.assert_called_once_with("openai", "openai-codex")

    def test_raw_oauth_identifier_remains_an_explicit_escape_hatch(self) -> None:
        assert to_inspect_model("openai-codex/gpt-6-astra") == "openai-codex/gpt-6-astra"

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("gpt-5.5", "openai-codex/gpt-5.5"),
            ("claude-opus-4-7", "anthropic/claude-opus-4-7"),
            ("glm-5", "geode/glm-5"),
        ],
    )
    def test_existing_mappings_remain_available(
        self, monkeypatch: pytest.MonkeyPatch, model: str, expected: str
    ) -> None:
        from core.config import settings

        monkeypatch.setattr(settings, "anthropic_credential_source", "auto")
        assert to_inspect_model(model) == expected

    def test_payg_fallback_does_not_override_a_forced_oauth_request(
        self, strict_mapping_policy: Path
    ) -> None:
        strict_mapping_policy.write_text(
            "[self_improving_loop]\nfallback_to_payg = true\n", encoding="utf-8"
        )
        with pytest.raises(AuditModelMappingError, match=r"audit.*mapping"):
            to_inspect_model("gpt-6-astra", use_oauth=True)

    def test_catalog_display_does_not_resolve_billing_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evals.petri import credential_source as cs
        from evals.petri import models

        model_ids = ("gpt-6-astra", "o3", "o4-mini")
        monkeypatch.setattr(models, "MODEL_PRICING", dict.fromkeys(model_ids))
        policy = Mock(side_effect=ValueError("invalid policy"))
        resolver = Mock(side_effect=AssertionError("display must not resolve credentials"))
        monkeypatch.setattr(cs, "self_improving_loop_fallback_policy", policy)
        monkeypatch.setattr(cs, "resolve_credential_source", resolver)
        assert list_audit_models() == [(model, f"openai/{model}") for model in model_ids]
        policy.assert_not_called()
        resolver.assert_not_called()
