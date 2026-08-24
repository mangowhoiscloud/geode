"""Unit tests for evals.petri.credential_source (P1-D)."""

from __future__ import annotations

import pytest
from evals.petri import credential_source as cs
from evals.petri.adapters import is_adapter_available
from evals.petri.manifest import clear_manifest_cache


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
    short-circuit on whatever GEODE's real ``settings.<provider>_credential_source``
    happens to be configured to. Tests that exercise the settings path opt in
    by re-patching _settings_source explicitly."""
    monkeypatch.setattr(cs, "_settings_source", lambda provider: None)


@pytest.fixture(autouse=True)
def _stub_oauth_adapters(monkeypatch):
    """Keep host OpenAI OAuth state out of resolver tests."""
    from evals.petri.adapters import openai_codex_oauth

    monkeypatch.setattr(openai_codex_oauth, "is_available", lambda: False)


# ── list_credential_sources ────────────────────────────────────────────────


def test_list_credential_sources_anthropic_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    out = cs.list_credential_sources("anthropic")
    sources = [entry["source"] for entry in out]
    assert sources == ["api_key", "auto"]
    api_key_entry = next(e for e in out if e["source"] == "api_key")
    assert api_key_entry["available"] is True
    assert api_key_entry["adapter"] == "evals.petri.adapters.http_anthropic"
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


def test_resolve_retired_claude_cli_override_raises() -> None:
    with pytest.raises(RuntimeError, match="integration is retired"):
        cs.resolve_credential_source("anthropic", override="claude-cli")


# ── resolve_credential_source — auto expansion ─────────────────────────────


def test_resolve_auto_returns_first_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_auto_skips_suppressed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cs.suppress_credential_source("anthropic", "api_key")
    # api_key suppressed → no resolution.
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic")


def test_resolve_auto_no_available_source_raises():
    # No API key → no Anthropic source is available.
    with pytest.raises(cs.CredentialResolutionError):
        cs.resolve_credential_source("anthropic")


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
        lambda provider: "api_key" if provider == "anthropic" else None,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_settings_auto_falls_to_expansion(monkeypatch):
    """settings returns None / 'auto' → manifest default → auto expansion."""
    monkeypatch.setattr(cs, "_settings_source", lambda provider: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"


def test_resolve_settings_invalid_raises(monkeypatch):
    monkeypatch.setattr(cs, "_settings_source", lambda provider: "imposter")
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


def test_error_carries_provider_and_allowed():
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("anthropic")
    err = excinfo.value
    assert err.provider == "anthropic"
    assert "api_key" in err.allowed


# ── PR-β1: subscription-only mode (fallback_to_payg=False) ─────────────────


def test_strict_mode_keeps_anthropic_sole_api_key_route(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert cs.resolve_credential_source("anthropic") == "api_key"
    assert cs.resolve_credential_source("anthropic", fallback_to_payg=False) == "api_key"


def test_subscription_only_error_message_actionable(monkeypatch):
    monkeypatch.setattr(cs, "is_adapter_available", lambda provider, source: False)
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("openai", fallback_to_payg=False)
    msg = str(excinfo.value)
    assert "fallback_to_payg=false" in msg
    assert "subscription credential source" in msg


def test_subscription_only_error_carries_flag(monkeypatch):
    """``subscription_only`` attribute exposed for FE banner consumption."""
    monkeypatch.setattr(cs, "is_adapter_available", lambda provider, source: False)
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("openai", fallback_to_payg=False)
    assert excinfo.value.subscription_only is True
    # Backwards-compat: default invocation has subscription_only=False.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


def test_strict_mode_keeps_zhipuai_sole_api_key_route(monkeypatch):
    monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-test")
    assert cs.resolve_credential_source("zhipuai") == "api_key"
    assert cs.resolve_credential_source("zhipuai", fallback_to_payg=False) == "api_key"


def test_explicit_settings_api_key_bypasses_openai_fallback_gate(monkeypatch):
    monkeypatch.setattr(cs, "_settings_source", lambda provider: "api_key")
    monkeypatch.setattr(
        cs,
        "is_adapter_available",
        lambda provider, source: provider == "openai" and source == "api_key",
    )
    assert cs.resolve_credential_source("openai", fallback_to_payg=False) == "api_key"


@pytest.mark.parametrize("source_origin", ["override", "settings"])
def test_openai_auto_or_suppressed_subscription_cannot_bypass_fallback_gate(
    monkeypatch,
    source_origin,
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    monkeypatch.setattr(
        cs,
        "is_adapter_available",
        lambda provider, source: provider == "openai" and source == "api_key",
    )
    kwargs = {"override": "auto"} if source_origin == "override" else {}
    if source_origin == "settings":
        monkeypatch.setattr(cs, "_settings_source", lambda provider: "openai-codex")
        cs.suppress_credential_source("openai", "openai-codex")
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source("openai", fallback_to_payg=False, **kwargs)
    assert excinfo.value.subscription_only is True


def test_auto_override_outranks_api_key_setting_without_authorizing_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    monkeypatch.setattr(cs, "_settings_source", lambda provider: "api_key")
    monkeypatch.setattr(
        cs,
        "is_adapter_available",
        lambda provider, source: provider == "openai" and source == "api_key",
    )
    with pytest.raises(cs.CredentialResolutionError) as excinfo:
        cs.resolve_credential_source(
            "openai",
            override="auto",
            fallback_to_payg=False,
        )
    assert excinfo.value.subscription_only is True


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_returns_true_when_unconfigured(monkeypatch):
    """self_improving_loop_fallback_policy() defaults True when [self_improving_loop] absent.

    Tested by monkeypatching load_self_improving_loop_config to return the default
    SelfImprovingLoopConfig (which has fallback_to_payg=False per the strict
    default settled in PR-α1 — but the helper itself just reads the field).
    """
    from evals.config import SelfImprovingLoopConfig

    # Unconfigured → default SelfImprovingLoopConfig().fallback_to_payg is False.
    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: SelfImprovingLoopConfig(),
    )
    assert cs.self_improving_loop_fallback_policy() is False


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_reads_user_config(monkeypatch):
    """When config sets fallback_to_payg=True, helper returns True."""
    from evals.config import SelfImprovingLoopConfig

    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: SelfImprovingLoopConfig(fallback_to_payg=True),
    )
    assert cs.self_improving_loop_fallback_policy() is True


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_safe_on_import_error(monkeypatch):
    """If evals.config is unavailable, helper returns True
    (back-compat preservation)."""
    import builtins

    real_import = builtins.__import__

    def _raising(name, *args, **kwargs):
        if name == "evals.config":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising)
    assert cs.self_improving_loop_fallback_policy() is True


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_safe_on_load_failure(monkeypatch):
    """If load_self_improving_loop_config raises (corrupt TOML, etc.), helper
    returns True and logs a warning rather than breaking the run."""

    def _raise():
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        _raise,
    )
    assert cs.self_improving_loop_fallback_policy() is True


def test_smoke_adapter_module_round_trip(monkeypatch):
    """Resolved source must be loadable by the adapter registry."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    source = cs.resolve_credential_source("anthropic")
    # The chosen source is a real adapter that the registry can probe.
    assert is_adapter_available("anthropic", source) is True


# ── P0c — subscription_only error trips the quota banner ────────────────


def test_anthropic_strict_error_does_not_claim_subscription_quota_abort():
    """Anthropic has no built-in subscription route, so no quota abort is claimed."""
    from core.cli.quota_banner import (
        SubscriptionQuotaBanner,
        install_banner,
        uninstall_banner,
    )

    banner = SubscriptionQuotaBanner()
    install_banner(banner)
    try:
        with pytest.raises(cs.CredentialResolutionError):
            raise cs.CredentialResolutionError("anthropic", ["api_key"], subscription_only=True)
        state = banner.state
        assert state.aborted is False
    finally:
        uninstall_banner()


def test_non_subscription_credential_error_does_not_trip_banner():
    """Generic CredentialResolutionError (no source available, not a
    subscription exhaustion) must NOT trip the banner — only subscription
    aborts get the red state."""
    from core.cli.quota_banner import (
        SubscriptionQuotaBanner,
        install_banner,
        uninstall_banner,
    )

    banner = SubscriptionQuotaBanner()
    install_banner(banner)
    try:
        with pytest.raises(cs.CredentialResolutionError):
            raise cs.CredentialResolutionError("anthropic", ["api_key"])
        assert banner.state.aborted is False
    finally:
        uninstall_banner()


def test_subscription_only_banner_trip_safe_when_no_banner_installed():
    """When no banner is installed (non-REPL invocation) the error must
    still raise cleanly — the wiring is optional, not load-bearing."""
    from core.cli.quota_banner import uninstall_banner

    uninstall_banner()
    with pytest.raises(cs.CredentialResolutionError):
        raise cs.CredentialResolutionError("anthropic", ["api_key"], subscription_only=True)


# ── P1b — credential resolver journal emit ──────────────────────────────


def _emit_test_journal(tmp_path):
    """Build a RunTimeline under tmp_path. Caller activates with run_timeline_scope."""
    from evals.run_timeline import RunTimeline

    sip_home = tmp_path / "self-improving-loop"

    class _ScopedPaths:
        pass

    journal = RunTimeline(
        session_id="s-p1b",
        gen_tag="gen-p1b",
        component="autoresearch",
        path=sip_home / "s-p1b" / "events.jsonl",
    )
    return journal, sip_home


def test_anthropic_strict_error_does_not_emit_subscription_abort(tmp_path, monkeypatch):
    from evals.run_timeline import run_timeline_scope

    journal, _ = _emit_test_journal(tmp_path)
    with run_timeline_scope(journal), pytest.raises(cs.CredentialResolutionError):
        raise cs.CredentialResolutionError("anthropic", ["api_key"], subscription_only=True)
    assert not journal.path.exists()


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_emits_journal_on_config_success(tmp_path, monkeypatch):
    """Successful config read emits fallback_policy_resolved with
    source='config' so the operator sees which path the resolver took."""
    import json

    from evals.run_timeline import run_timeline_scope

    journal, _ = _emit_test_journal(tmp_path)

    # Force a known fallback_to_payg value by stubbing the loader.
    from types import SimpleNamespace

    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        lambda: SimpleNamespace(fallback_to_payg=False),
    )
    with run_timeline_scope(journal):
        assert cs.self_improving_loop_fallback_policy() is False
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    events = [r for r in rows if r["event"] == "fallback_policy_resolved"]
    assert len(events) == 1
    assert events[0]["payload"] == {"value": False, "source": "config"}


@pytest.mark.policy_real
def test_self_improving_loop_fallback_policy_emits_journal_on_load_error(tmp_path, monkeypatch):
    """When the loader raises, the helper still returns the lenient
    default but the journal records source='load_error_default' so the
    silent fallback is auditable."""
    import json

    from evals.run_timeline import run_timeline_scope

    journal, _ = _emit_test_journal(tmp_path)

    def _raise():
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(
        "evals.config.load_self_improving_loop_config",
        _raise,
    )
    with run_timeline_scope(journal):
        assert cs.self_improving_loop_fallback_policy() is True
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    events = [r for r in rows if r["event"] == "fallback_policy_resolved"]
    assert len(events) == 1
    assert events[0]["level"] == "warn"
    assert events[0]["payload"] == {"value": True, "source": "load_error_default"}


def test_credential_journal_emit_noop_outside_scope(monkeypatch):
    """Outside a RunTimeline scope (single-shot CLI) the emit must
    no-op cleanly so the resolver's contract is unchanged."""
    # No run_timeline_scope active.
    with pytest.raises(cs.CredentialResolutionError):
        raise cs.CredentialResolutionError("anthropic", ["api_key"], subscription_only=True)
