"""Unit tests for the Petri audit manifest schema + loader (P1-A)."""

from __future__ import annotations

from pathlib import Path

import pytest
from plugins.petri_audit.manifest import (
    DEFAULT_MANIFEST_PATH,
    AdapterSpec,
    PetriManifest,
    RoleSpec,
    SourceSpec,
    _parse_manifest_dict,
    clear_manifest_cache,
    load_manifest,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_manifest_cache()
    yield
    clear_manifest_cache()


def _valid_dict() -> dict:
    """Minimal valid manifest dict — fixture for negative tests."""
    return {
        "petri": {
            "enabled_roles": ["auditor", "judge"],
            "role": {
                "auditor": {
                    "default_model": "claude-sonnet-4-6",
                    "allowed_models": ["claude-sonnet-4-6", "claude-opus-4-7"],
                    "role_contract": "roles/auditor.md",
                },
                "judge": {
                    "default_model": "claude-sonnet-4-6",
                    "allowed_models": ["claude-sonnet-4-6"],
                },
            },
            "source": {
                "anthropic": {
                    "default": "auto",
                    "allowed": ["api_key", "claude-cli", "auto"],
                }
            },
            "adapter": {
                "anthropic": {
                    "api_key": {
                        "module": "plugins.petri_audit.adapters.http_anthropic",
                        "inspect_prefix": "anthropic",
                        "auth_env_vars": ["ANTHROPIC_API_KEY"],
                        "endpoint": "https://api.anthropic.com",
                    },
                    "claude-cli": {
                        "module": "plugins.petri_audit.adapters.claude_cli_backend",
                        "inspect_prefix": "claude-code",
                        "auth_env_vars": ["ANTHROPIC_OAUTH_TOKEN"],
                        "binary": "claude",
                    },
                }
            },
        }
    }


# ── Default manifest happy path ────────────────────────────────────────────


def test_default_manifest_loads():
    manifest = load_manifest()
    assert isinstance(manifest, PetriManifest)
    assert set(manifest.enabled_roles) == {"auditor", "target", "judge"}
    assert "anthropic" in manifest.sources
    assert "openai" in manifest.sources
    assert "zhipuai" in manifest.sources


def test_default_manifest_role_defaults_in_allowed():
    manifest = load_manifest()
    for role_name in manifest.enabled_roles:
        spec = manifest.get_role(role_name)
        assert spec.default_model in spec.allowed_models


def test_default_manifest_adapter_coverage():
    """Every non-auto source in source.allowed has an adapter."""
    manifest = load_manifest()
    for family, source_spec in manifest.sources.items():
        for source in source_spec.allowed:
            if source == "auto":
                continue
            # raises if missing
            manifest.get_adapter(family, source)


def test_default_manifest_default_path_constant():
    assert DEFAULT_MANIFEST_PATH.name == "petri.plugin.toml"
    assert DEFAULT_MANIFEST_PATH.exists()


def test_default_manifest_inspect_prefixes():
    """Inspect prefixes match the existing to_inspect_model contract."""
    manifest = load_manifest()
    assert manifest.get_adapter("anthropic", "api_key").inspect_prefix == "anthropic"
    assert manifest.get_adapter("anthropic", "claude-cli").inspect_prefix == "claude-code"
    assert manifest.get_adapter("openai", "api_key").inspect_prefix == "openai"
    assert manifest.get_adapter("openai", "openai-codex").inspect_prefix == "openai-codex"
    assert manifest.get_adapter("zhipuai", "api_key").inspect_prefix == "geode"


# ── Negative validation paths ──────────────────────────────────────────────


def test_role_default_not_in_allowed_raises():
    bad = _valid_dict()
    bad["petri"]["role"]["auditor"]["default_model"] = "claude-haiku-4-5"
    with pytest.raises(ValueError, match="default_model"):
        _parse_manifest_dict(bad)


def test_source_default_not_in_allowed_raises():
    bad = _valid_dict()
    bad["petri"]["source"]["anthropic"]["default"] = "openai-codex"
    with pytest.raises(ValueError, match="source default"):
        _parse_manifest_dict(bad)


def test_missing_adapter_for_allowed_source_raises():
    bad = _valid_dict()
    bad["petri"]["source"]["anthropic"]["allowed"] = [
        "api_key",
        "claude-cli",
        "openai-codex",
        "auto",
    ]
    with pytest.raises(ValueError, match="no adapter"):
        _parse_manifest_dict(bad)


def test_enabled_role_without_spec_raises():
    bad = _valid_dict()
    bad["petri"]["enabled_roles"] = ["auditor", "judge", "target"]
    with pytest.raises(ValueError, match="role spec keys"):
        _parse_manifest_dict(bad)


def test_missing_petri_root_raises():
    with pytest.raises(ValueError, match="\\[petri\\] root"):
        _parse_manifest_dict({})


# ── Accessor behaviour ─────────────────────────────────────────────────────


def test_get_role_unknown_raises_keyerror():
    manifest = load_manifest()
    with pytest.raises(KeyError, match="Unknown petri role"):
        manifest.get_role("nonexistent")


def test_get_source_unknown_raises_keyerror():
    manifest = load_manifest()
    with pytest.raises(KeyError, match="Unknown petri family"):
        manifest.get_source("nonexistent")


def test_get_adapter_auto_raises_valueerror():
    manifest = load_manifest()
    with pytest.raises(ValueError, match="Cannot resolve adapter for 'auto'"):
        manifest.get_adapter("anthropic", "auto")


def test_get_adapter_unknown_source_raises():
    manifest = load_manifest()
    with pytest.raises(KeyError, match="No adapter for"):
        manifest.get_adapter("anthropic", "nonexistent")


# ── Cache behaviour ────────────────────────────────────────────────────────


def test_load_manifest_caches_by_path(tmp_path: Path):
    target = tmp_path / "petri.plugin.toml"
    target.write_text(
        """
[petri]
enabled_roles = ["judge"]
[petri.role.judge]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-sonnet-4-6"]
[petri.source.anthropic]
default = "api_key"
allowed = ["api_key"]
[petri.adapter.anthropic.api_key]
module = "plugins.petri_audit.adapters.http_anthropic"
inspect_prefix = "anthropic"
auth_env_vars = ["ANTHROPIC_API_KEY"]
""",
        encoding="utf-8",
    )
    m1 = load_manifest(target)
    m2 = load_manifest(target)
    assert m1 is m2


def test_clear_manifest_cache_forces_reload(tmp_path: Path):
    target = tmp_path / "petri.plugin.toml"
    body = """
[petri]
enabled_roles = ["judge"]
[petri.role.judge]
default_model = "claude-sonnet-4-6"
allowed_models = ["claude-sonnet-4-6"]
[petri.source.anthropic]
default = "api_key"
allowed = ["api_key"]
[petri.adapter.anthropic.api_key]
module = "plugins.petri_audit.adapters.http_anthropic"
inspect_prefix = "anthropic"
auth_env_vars = ["ANTHROPIC_API_KEY"]
"""
    target.write_text(body, encoding="utf-8")
    m1 = load_manifest(target)
    clear_manifest_cache()
    m2 = load_manifest(target)
    assert m1 is not m2


# ── Schema dataclass roundtrip ─────────────────────────────────────────────


def test_role_spec_round_trip():
    spec = RoleSpec(
        default_model="x",
        allowed_models=["x", "y"],
        role_contract="roles/x.md",
    )
    assert spec.default_model == "x"
    assert spec.role_contract == "roles/x.md"


def test_source_spec_round_trip():
    spec = SourceSpec(default="api_key", allowed=["api_key", "auto"])
    assert spec.default == "api_key"


def test_adapter_spec_optional_fields():
    spec = AdapterSpec(
        module="plugins.petri_audit.adapters.http_anthropic",
        inspect_prefix="anthropic",
    )
    assert spec.auth_env_vars == []
    assert spec.endpoint is None
    assert spec.binary is None
