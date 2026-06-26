"""Unit tests for core.config.routing_manifest (P2-A schema + loader)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.config.routing_manifest import (
    DEFAULT_MANIFEST_PATH,
    ModelDefaults,
    ModelFallbacks,
    RoutingManifest,
    RoutingRules,
    _merge_routing_dicts,
    _parse_manifest,
    clear_routing_manifest_cache,
    load_routing_manifest,
    resolve_provider,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    clear_routing_manifest_cache()
    yield
    clear_routing_manifest_cache()


def _valid_dict() -> dict[str, Any]:
    """Minimal valid manifest dict — fixture for negative tests."""
    return {
        "model": {
            "defaults": {
                "anthropic": "claude-opus-4-7",
                "openai": "gpt-5.5",
                "codex": "gpt-5.5",
                "glm": "glm-5.1",
            },
            "fallbacks": {
                "anthropic": ["claude-opus-4-7", "claude-sonnet-4-6"],
                "openai": ["gpt-5.5", "gpt-5.4"],
                "codex": ["gpt-5.5", "gpt-5.3-codex"],
                "glm": ["glm-5.1", "glm-5"],
            },
        },
        "routing": {
            "prefixes": {"claude-": "anthropic", "gpt-": "openai"},
            "codex_only_models": ["gpt-5.5"],
            "codex_suffixes": ["-codex"],
            "fallback_provider": "openai",
        },
        "credentials": {
            "patterns": {"^sk-ant-": "anthropic"},
            "keychain": {"anthropic": "Claude Code-credentials"},
        },
    }


# ── Default manifest happy path ────────────────────────────────────────────


def test_default_manifest_loads() -> None:
    manifest = load_routing_manifest()
    assert isinstance(manifest, RoutingManifest)
    assert manifest.defaults.anthropic == "claude-opus-4-8"
    assert manifest.defaults.openai == "gpt-5.5"
    assert manifest.defaults.glm == "glm-5.2"


def test_default_manifest_path_exists() -> None:
    assert DEFAULT_MANIFEST_PATH.name == "routing.toml"
    assert DEFAULT_MANIFEST_PATH.exists()


def test_default_manifest_fallback_chains_empty() -> None:
    """v0.99.19 — shipped default is an opt-in knob: empty list = no
    silent same-provider fallback. User populates ``~/.geode/routing.toml``
    ``[model.fallbacks]`` to opt in."""
    manifest = load_routing_manifest()
    assert manifest.fallbacks.anthropic == []
    assert manifest.fallbacks.openai == []
    assert manifest.fallbacks.codex == []
    assert manifest.fallbacks.glm == []


def test_default_manifest_routing_rules() -> None:
    manifest = load_routing_manifest()
    assert manifest.routing.prefixes.get("claude-") == "anthropic"
    assert "gpt-5.5" in manifest.routing.codex_only_models
    assert manifest.routing.fallback_provider == "openai"


def test_default_manifest_credentials_keychain() -> None:
    manifest = load_routing_manifest()
    assert manifest.credential_keychain.services.get("anthropic") == "Claude Code-credentials"


def test_default_manifest_credentials_patterns() -> None:
    manifest = load_routing_manifest()
    # P2-C: regexes carry length quantifiers — verify by prefix match.
    keys = list(manifest.credential_patterns.patterns)
    anthropic_key = next(k for k in keys if k.startswith("^sk-ant-"))
    assert manifest.credential_patterns.patterns[anthropic_key] == "anthropic"


def test_default_manifest_credentials_env_vars() -> None:
    """P2-C — provider → env var mapping is loaded from the manifest."""
    manifest = load_routing_manifest()
    assert manifest.credential_env_vars.env_vars.get("anthropic") == "ANTHROPIC_API_KEY"
    assert manifest.credential_env_vars.env_vars.get("openai") == "OPENAI_API_KEY"
    assert manifest.credential_env_vars.env_vars.get("glm") == "ZAI_API_KEY"


# ── resolve_provider — executable providers only ──────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-opus-4-7", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
        ("glm-5.1", "glm"),
        ("gpt-5.5", "openai-codex"),  # codex_only_models hits first
        ("gpt-5.5-pro", "openai-codex"),
        ("gpt-5.4", "openai"),  # gpt- prefix
        ("gpt-5.3-codex", "openai-codex"),  # codex suffix
        ("o3-mini", "openai"),
        ("o4-mini", "openai"),
        ("gemini-1.5-pro", "openai"),  # no built-in google adapter
        ("deepseek-r1", "openai"),  # no built-in deepseek adapter
        ("llama-3.3", "openai"),  # no built-in meta adapter
        ("qwen-72b", "openai"),  # no built-in alibaba adapter
        ("qwen3-72b", "openai"),  # no built-in alibaba adapter
        ("mystery-model", "openai"),  # fallback
    ],
)
def test_resolve_provider_routes_only_executable_providers(model: str, expected: str) -> None:
    """resolve_provider returns only executable built-in providers.

    Families without adapters fall through to fallback_provider instead of
    routing to inert provider names.
    """
    assert resolve_provider(model) == expected


# ── Negative validation ────────────────────────────────────────────────────


def test_fallback_default_drift_raises() -> None:
    bad = _valid_dict()
    bad["model"]["fallbacks"]["anthropic"] = ["claude-sonnet-4-6", "claude-opus-4-7"]
    with pytest.raises(ValueError, match="drift between"):
        _parse_manifest(bad)


def test_empty_fallback_is_accepted() -> None:
    """v0.99.19 — empty fallback chain = opt-out (no silent fallback).
    Pre-fix this raised; the new invariant accepts the empty case so the
    shipped default can encode "no auto-retry to alternates"."""
    good = _valid_dict()
    good["model"]["fallbacks"]["openai"] = []
    manifest = _parse_manifest(good)
    assert manifest.fallbacks.openai == []


def test_prefix_target_empty_raises() -> None:
    bad = _valid_dict()
    bad["routing"]["prefixes"]["weird-"] = ""
    with pytest.raises(ValueError, match="empty provider"):
        _parse_manifest(bad)


def test_prefix_target_without_builtin_adapter_raises() -> None:
    bad = _valid_dict()
    bad["routing"]["prefixes"]["gemini-"] = "google"
    with pytest.raises(ValueError, match="unsupported provider"):
        _parse_manifest(bad)


def test_fallback_provider_without_builtin_adapter_raises() -> None:
    bad = _valid_dict()
    bad["routing"]["fallback_provider"] = "google"
    with pytest.raises(ValueError, match="fallback_provider"):
        _parse_manifest(bad)


def test_missing_required_default_field_raises() -> None:
    bad = _valid_dict()
    del bad["model"]["defaults"]["openai"]
    with pytest.raises(Exception):  # pydantic ValidationError
        _parse_manifest(bad)


# ── Schema dataclass roundtrip ─────────────────────────────────────────────


def test_model_defaults_accessor() -> None:
    d = ModelDefaults(
        anthropic="x",
        openai="y",
        codex="z",
        glm="g",
    )
    assert d.get("anthropic") == "x"
    assert d.get("nonexistent") is None


def test_model_fallbacks_accessor() -> None:
    f = ModelFallbacks(
        anthropic=["x"],
        openai=["y"],
        codex=["z"],
        glm=["g"],
    )
    assert f.get("anthropic") == ["x"]
    assert f.get("nonexistent") is None


def test_routing_rules_defaults() -> None:
    r = RoutingRules()
    assert r.fallback_provider == "openai"
    assert r.codex_only_models == []


# ── User override merge ────────────────────────────────────────────────────


def test_user_override_merges_single_key(tmp_path: Path) -> None:
    """A user TOML that only sets ``[credentials.keychain]`` overrides exactly
    that section, leaving every other default intact."""
    override = tmp_path / "routing.toml"
    override.write_text(
        '[credentials.keychain]\nopenai = "Codex-credentials"\n',
        encoding="utf-8",
    )
    manifest = load_routing_manifest(user_path=override)
    assert manifest.credential_keychain.services.get("openai") == "Codex-credentials"
    # Shipped keychain entries preserved
    assert manifest.credential_keychain.services.get("anthropic") == "Claude Code-credentials"
    # Other sections untouched
    assert manifest.defaults.anthropic == "claude-opus-4-8"
    assert manifest.defaults.openai == "gpt-5.5"


def test_user_override_paired_default_and_fallback(tmp_path: Path) -> None:
    """When the user overrides both default and fallback for a provider
    consistently, the manifest accepts the change."""
    override = tmp_path / "routing.toml"
    override.write_text(
        """
[model.defaults]
anthropic = "claude-sonnet-4-6"

[model.fallbacks]
anthropic = ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
""",
        encoding="utf-8",
    )
    manifest = load_routing_manifest(user_path=override)
    assert manifest.defaults.anthropic == "claude-sonnet-4-6"
    assert manifest.fallbacks.anthropic[0] == "claude-sonnet-4-6"
    # Other providers untouched
    assert manifest.defaults.openai == "gpt-5.5"


def test_user_override_merges_nested_section(tmp_path: Path) -> None:
    """Executable user prefix overrides merge instead of replace."""
    override = tmp_path / "routing.toml"
    override.write_text(
        '[routing.prefixes]\n"custom-openai-" = "openai"\n',
        encoding="utf-8",
    )
    manifest = load_routing_manifest(user_path=override)
    assert manifest.routing.prefixes.get("custom-openai-") == "openai"
    # Shipped prefixes preserved
    assert manifest.routing.prefixes.get("claude-") == "anthropic"


def test_user_override_drift_invariant_still_enforced(tmp_path: Path) -> None:
    """User can't break the default/fallback consistency by overriding only
    one side — the validator runs on the merged manifest."""
    override = tmp_path / "routing.toml"
    override.write_text(
        '[model.fallbacks]\nanthropic = ["claude-sonnet-4-6", "claude-opus-4-7"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="drift between"):
        load_routing_manifest(user_path=override)


def test_use_user_override_false_ignores_override(tmp_path: Path) -> None:
    override = tmp_path / "routing.toml"
    override.write_text(
        '[model.defaults]\nanthropic = "claude-sonnet-4-6"\n',
        encoding="utf-8",
    )
    manifest = load_routing_manifest(user_path=override, use_user_override=False)
    assert manifest.defaults.anthropic == "claude-opus-4-8"


def test_user_override_missing_file_no_op(tmp_path: Path) -> None:
    """A missing user TOML degrades to shipped default — no error."""
    missing = tmp_path / "does_not_exist.toml"
    manifest = load_routing_manifest(user_path=missing)
    assert manifest.defaults.anthropic == "claude-opus-4-8"


def test_user_override_malformed_toml_no_op(tmp_path: Path) -> None:
    """A malformed user TOML degrades to shipped default — defensive."""
    bad = tmp_path / "routing.toml"
    bad.write_text("this is not toml [[[", encoding="utf-8")
    manifest = load_routing_manifest(user_path=bad)
    assert manifest.defaults.anthropic == "claude-opus-4-8"


# ── Merge helper ───────────────────────────────────────────────────────────


def test_merge_routing_dicts_deep_merge_one_level() -> None:
    base = {"model": {"defaults": {"a": "1", "b": "2"}}}
    override = {"model": {"defaults": {"a": "X"}}}
    merged = _merge_routing_dicts(base, override)
    assert merged["model"]["defaults"] == {"a": "X", "b": "2"}


def test_merge_routing_dicts_disjoint_sections() -> None:
    base = {"model": {"defaults": {"a": "1"}}}
    override = {"routing": {"fallback_provider": "X"}}
    merged = _merge_routing_dicts(base, override)
    assert merged["model"]["defaults"] == {"a": "1"}
    assert merged["routing"]["fallback_provider"] == "X"


# ── Cache behaviour ────────────────────────────────────────────────────────


def test_load_manifest_caches_per_path(tmp_path: Path) -> None:
    a = load_routing_manifest()
    b = load_routing_manifest()
    assert a is b


def test_clear_cache_forces_reload() -> None:
    a = load_routing_manifest()
    clear_routing_manifest_cache()
    b = load_routing_manifest()
    assert a is not b
