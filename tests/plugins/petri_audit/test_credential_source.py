"""Unit tests for plugins.petri_audit.credential_source (P1-D)."""

from __future__ import annotations

import pytest
from plugins.petri_audit.adapters import is_adapter_available
from plugins.petri_audit.manifest import clear_manifest_cache

from plugins.petri_audit import credential_source as cs


@pytest.fixture(autouse=True)
def _clear_state():
    clear_manifest_cache()
    cs.clear_suppressions()
    yield
    cs.clear_suppressions()
    clear_manifest_cache()


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ZHIPUAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    """Pin _settings_source to None across the suite so the resolver does not
    short-circuit on whatever GEODE's real ``settings.<family>_credential_source``
    happens to be configured to. Tests that exercise the settings path opt in
    by re-patching _settings_source explicitly."""
    monkeypatch.setattr(cs, "_settings_source", lambda family: None)


@pytest.fixture(autouse=True)
def _stub_oauth_adapters(monkeypatch):
    """Force OAuth adapter is_available probes to False across the suite.

    Both ``claude_cli_backend`` and ``openai_codex_oauth`` query the
    developer machine's keychain / file-based OAuth state — running tests
    on a host with a live ``Claude Code-credentials`` keychain entry (or
    a valid Codex OAuth token) would otherwise leak into the resolver.

    Tests that need an OAuth source to register as available opt in by
    monkeypatching the adapter's ``is_available`` back to a True
    callable. See ``test_resolve_auto_oauth_priority`` for the pattern.

    NOTE — this fixture papers over a design gap (the resolver consults
    three hidden sources: settings / keychain / env). The long-term fix
    is constructor-injected DI à la ``core/auth/rotation.py::ProfileRotator``;
    tracked as a backlog task. See P1-D PR body for the rationale.
    """
    from plugins.petri_audit.adapters import claude_cli_backend, openai_codex_oauth

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: False)
    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: False)


# ── list_credential_sources ────────────────────────────────────────────────


def test_list_credential_sources_anthropic_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    out = cs.list_credential_sources("anthropic")
    sources = [entry["source"] for entry in out]
    # Default manifest order — OAuth first (P1-D rebalance).
    assert sources == ["claude-cli", "api_key", "auto"]
    api_key_entry = next(e for e in out if e["source"] == "api_key")
    assert api_key_entry["available"] is True
    assert api_key_entry["adapter"] == "plugins.petri_audit.adapters.http_anthropic"
    assert api_key_entry["inspect_prefix"] == "anthropic"
    assert api_key_entry["auth_env_vars"] == ["ANTHROPIC_API_KEY"]
    auto_entry = next(e for e in out if e["source"] == "auto")
    assert auto_entry["available"] is True
    assert auto_entry["adapter"] is None
    assert auto_entry["is_default"] is True


def test_list_credential_sources_marks_suppressed():
    cs.suppress_credential_source("anthropic", "api_key")
    out = cs.list_credential_sources("anthropic")
    api_key_entry = next(e for e in out if e["source"] == "api_key")
    assert api_key_entry["is_suppressed"] is True
    # Even if env var is set, suppressed → unavailable.
    assert api_key_entry["available"] is False


def test_list_credential_sources_zhipuai_single_source():
    out = cs.list_credential_sources("zhipuai")
    assert [e["source"] for e in out] == ["api_key"]
    assert out[0]["is_default"] is True


# ── resolve_credential_source — explicit paths ─────────────────────────────


def test_resolve_with_explicit_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic", override="api_key") == "api_key"


def test_resolve_override_invalid_raises():
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic", override="nonexistent")


def test_resolve_override_auto_falls_through_to_expansion(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # 'auto' override is allowed and triggers expansion — api_key is available.
    assert cs.resolve_credential_source("anthropic", override="auto") == "api_key"


def test_resolve_override_suppressed_falls_through(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cs.suppress_credential_source("anthropic", "claude-cli")
    # claude-cli explicitly requested but suppressed → auto expansion picks
    # the next available source.
    assert cs.resolve_credential_source("anthropic", override="claude-cli") == "api_key"


# ── resolve_credential_source — auto expansion ─────────────────────────────


def test_resolve_auto_returns_first_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # claude-cli unavailable (no keychain), api_key available → api_key.
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_auto_skips_suppressed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cs.suppress_credential_source("anthropic", "api_key")
    # api_key suppressed, claude-cli unavailable → no resolution.
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic")


def test_resolve_auto_no_available_source_raises():
    # No env vars, no keychain → both anthropic sources unavailable.
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic")


def test_resolve_auto_oauth_priority(monkeypatch):
    """When both claude-cli (OAuth) and api_key are available, manifest order
    wins — claude-cli is listed first so it should be preferred."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # Force claude-cli adapter to report available.
    from plugins.petri_audit.adapters import claude_cli_backend

    monkeypatch.setattr(claude_cli_backend, "is_available", lambda: True)
    assert cs.resolve_credential_source("anthropic") == "claude-cli"


def test_resolve_zhipuai_with_env(monkeypatch):
    monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-test")
    assert cs.resolve_credential_source("zhipuai") == "api_key"


def test_resolve_zhipuai_returns_default_regardless_of_env():
    """zhipuai's manifest default = 'api_key' (not 'auto'). The resolver
    returns it unconditionally — availability is a separate concern checked
    at call time by the adapter, not by the resolver."""
    assert cs.resolve_credential_source("zhipuai") == "api_key"
    # The chosen source is unavailable (no env var) — that surfaces when
    # inspect_ai actually attempts the call, not from resolve_credential_source.
    assert is_adapter_available("zhipuai", "api_key") is False


# ── settings integration ───────────────────────────────────────────────────


def test_resolve_reads_settings_explicit(monkeypatch):
    """settings.anthropic_credential_source = 'api_key' → returned directly."""
    monkeypatch.setattr(
        cs,
        "_settings_source",
        lambda family: "api_key" if family == "anthropic" else None,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_settings_auto_falls_to_expansion(monkeypatch):
    """settings returns None / 'auto' → manifest default → auto expansion."""
    monkeypatch.setattr(cs, "_settings_source", lambda family: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_settings_invalid_raises(monkeypatch):
    monkeypatch.setattr(cs, "_settings_source", lambda family: "imposter")
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic")


# ── suppress / clear ───────────────────────────────────────────────────────


def test_suppress_and_is_suppressed():
    assert cs.is_suppressed("anthropic", "api_key") is False
    cs.suppress_credential_source("anthropic", "api_key")
    assert cs.is_suppressed("anthropic", "api_key") is True


def test_clear_suppressions_resets_all():
    cs.suppress_credential_source("anthropic", "api_key")
    cs.suppress_credential_source("openai", "openai-codex")
    cs.clear_suppressions()
    assert cs.is_suppressed("anthropic", "api_key") is False
    assert cs.is_suppressed("openai", "openai-codex") is False


def test_suppress_is_idempotent():
    cs.suppress_credential_source("anthropic", "api_key")
    cs.suppress_credential_source("anthropic", "api_key")  # no raise
    assert cs.is_suppressed("anthropic", "api_key") is True


# ── CredentialResolutionError shape ────────────────────────────────────────


def test_error_carries_family_and_allowed():
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("anthropic")
    err = excinfo.value
    assert err.family == "anthropic"
    assert "claude-cli" in err.allowed
    assert "api_key" in err.allowed


# ── PR-β1: subscription-only mode (fallback_to_payg=False) ─────────────────


def test_fallback_disabled_filters_api_key_from_auto_expansion(monkeypatch):
    """With fallback_to_payg=False, auto expansion must skip api_key
    even when ANTHROPIC_API_KEY is set."""
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # Without fallback: api_key chosen.
    assert cs.resolve_credential_source("anthropic") == "api_key"
    # With fallback disabled: api_key filtered → no OAuth available → raise.
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("anthropic", fallback_to_payg=False)
    assert excinfo.value.subscription_only is True


def test_fallback_disabled_returns_oauth_when_available(monkeypatch):
    """With fallback_to_payg=False and OAuth available, returns OAuth."""
    monkeypatch.setattr(
        cs,
        "is_adapter_available",
        lambda fam, src: src == "claude-cli",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # would-be fallback
    assert cs.resolve_credential_source("anthropic", fallback_to_payg=False) == "claude-cli"


def test_subscription_only_error_message_actionable(monkeypatch):
    """Stripe-style actionable message must mention the config remedy."""
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("anthropic", fallback_to_payg=False)
    msg = str(excinfo.value)
    assert "fallback_to_payg = true" in msg
    assert "[outer_loop]" in msg
    assert "subscription" in msg.lower()


def test_subscription_only_error_carries_flag(monkeypatch):
    """``subscription_only`` attribute exposed for FE banner consumption."""
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("anthropic", fallback_to_payg=False)
    assert excinfo.value.subscription_only is True
    # Backwards-compat: default invocation has subscription_only=False.
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(cs.CredentialResolutionError) as excinfo2:
        cs.resolve_credential_source("anthropic")
    assert excinfo2.value.subscription_only is False


def test_fallback_default_true_preserves_backcompat(monkeypatch):
    """Default behaviour (no kwarg) matches pre-2026-05-19 resolver."""
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_override_bypasses_subscription_only_filter(monkeypatch):
    """Explicit override of ``api_key`` wins even with fallback_to_payg=False.

    Rationale: explicit override = caller takes responsibility; the
    subscription-only filter is only for the auto-expansion path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert (
        cs.resolve_credential_source("anthropic", override="api_key", fallback_to_payg=False)
        == "api_key"
    )


def test_payg_source_constant_matches_manifest():
    """PAYG_SOURCE constant is the literal `api_key` string."""
    assert cs.PAYG_SOURCE == "api_key"


def test_strict_mode_blocks_payg_default_for_zhipuai(monkeypatch):
    """zhipuai manifest default is `api_key` (no OAuth alternative).

    Strict mode (fallback_to_payg=False) must block the concrete-default
    path too, not only the auto-expansion loop. Explicit override stays
    a valid escape hatch.
    """
    monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-test")
    # Default kwarg returns api_key as before.
    assert cs.resolve_credential_source("zhipuai") == "api_key"
    # Strict mode + no override → raise.
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("zhipuai", fallback_to_payg=False)
    assert excinfo.value.subscription_only is True
    # Explicit override bypasses the filter (caller responsibility).
    assert (
        cs.resolve_credential_source("zhipuai", override="api_key", fallback_to_payg=False)
        == "api_key"
    )


@pytest.mark.policy_real
def test_outer_loop_fallback_policy_returns_true_when_unconfigured(monkeypatch):
    """outer_loop_fallback_policy() defaults True when [outer_loop] absent.

    Tested by monkeypatching load_outer_loop_config to return the default
    OuterLoopConfig (which has fallback_to_payg=False per the strict
    default settled in PR-α1 — but the helper itself just reads the field).
    """
    from core.config.outer_loop import OuterLoopConfig

    # Unconfigured → default OuterLoopConfig().fallback_to_payg is False.
    monkeypatch.setattr(
        "core.config.outer_loop.load_outer_loop_config",
        lambda: OuterLoopConfig(),
    )
    assert cs.outer_loop_fallback_policy() is False


@pytest.mark.policy_real
def test_outer_loop_fallback_policy_reads_user_config(monkeypatch):
    """When config sets fallback_to_payg=True, helper returns True."""
    from core.config.outer_loop import OuterLoopConfig

    monkeypatch.setattr(
        "core.config.outer_loop.load_outer_loop_config",
        lambda: OuterLoopConfig(fallback_to_payg=True),
    )
    assert cs.outer_loop_fallback_policy() is True


@pytest.mark.policy_real
def test_outer_loop_fallback_policy_safe_on_import_error(monkeypatch):
    """If core.config.outer_loop is unavailable, helper returns True
    (back-compat preservation)."""
    import builtins

    real_import = builtins.__import__

    def _raising(name, *args, **kwargs):
        if name == "core.config.outer_loop":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising)
    assert cs.outer_loop_fallback_policy() is True


@pytest.mark.policy_real
def test_outer_loop_fallback_policy_safe_on_load_failure(monkeypatch):
    """If load_outer_loop_config raises (corrupt TOML, etc.), helper
    returns True and logs a warning rather than breaking the run."""

    def _raise():
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(
        "core.config.outer_loop.load_outer_loop_config",
        _raise,
    )
    assert cs.outer_loop_fallback_policy() is True


def test_smoke_adapter_module_round_trip(monkeypatch):
    """Resolved source must be loadable by the adapter registry."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    source = cs.resolve_credential_source("anthropic")
    # The chosen source is a real adapter that the registry can probe.
    assert is_adapter_available("anthropic", source) is True
