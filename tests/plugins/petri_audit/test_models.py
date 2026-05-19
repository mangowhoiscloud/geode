"""Model-id mapping tests for petri_audit (no [audit] extra needed)."""

from __future__ import annotations

import pytest
from plugins.petri_audit.models import (
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
    # auto-detect path is covered in tests/plugins/petri_audit/
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
    # PR B — claude-* now resolves to ``claude-code/`` when the Claude
    # subscription keychain entry is present, or ``anthropic/`` when
    # not. Accept either form (same precedent as the gpt-5 OAuth path).
    assert any(
        i.startswith("anthropic/claude-") or i.startswith("claude-code/claude-")
        for i in inspect_ids
    )
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


def test_claude_oauth_explicit_use_oauth_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``use_oauth=True`` forces ``claude-code/`` regardless of settings.
    The CLI flag must still beat the persisted picker choice — matches
    the codex side's precedence rule."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "api_key", raising=False)
    assert to_inspect_model("claude-opus-4-7", use_oauth=True) == "claude-code/claude-opus-4-7"


def test_claude_oauth_explicit_off_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """``use_oauth=False`` forces ``anthropic/`` regardless of settings."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "oauth", raising=False)
    assert to_inspect_model("claude-opus-4-7", use_oauth=False) == "anthropic/claude-opus-4-7"


def test_claude_source_oauth_routes_to_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """``settings.anthropic_credential_source = 'oauth'`` routes
    ``claude-*`` ids through ``claude-code/`` (subscription quota)."""
    from core.config import settings

    monkeypatch.setattr(settings, "anthropic_credential_source", "oauth", raising=False)
    assert to_inspect_model("claude-sonnet-4-6") == "claude-code/claude-sonnet-4-6"


def test_claude_source_api_key_routes_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """``settings.anthropic_credential_source = 'api_key'`` keeps the
    stock ``anthropic/`` prefix even when a keychain entry exists."""
    from core.config import settings
    from plugins.petri_audit.adapters import claude_cli_backend

    monkeypatch.setattr(settings, "anthropic_credential_source", "api_key", raising=False)
    # Pretend keychain says yes — explicit api_key must still win.
    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert to_inspect_model("claude-opus-4-7") == "anthropic/claude-opus-4-7"


def test_claude_source_auto_prefers_oauth_when_keychain_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In ``auto`` mode the keychain detection takes over — keychain
    present → ``claude-code/``, absent → ``anthropic/``."""
    from core.config import settings
    from plugins.petri_audit.adapters import claude_cli_backend

    monkeypatch.setattr(settings, "anthropic_credential_source", "auto", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: True)
    assert to_inspect_model("claude-opus-4-7") == "claude-code/claude-opus-4-7"

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: False)
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


def test_gpt_source_api_key_routes_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """``api_key`` keeps the PAYG path even with a Codex token present."""
    from core.config import settings
    from plugins.petri_audit.adapters import openai_codex_oauth

    monkeypatch.setattr(settings, "openai_credential_source", "api_key", raising=False)
    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    assert to_inspect_model("gpt-5.5") == "openai/gpt-5.5"
