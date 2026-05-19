"""Unit tests for the Petri audit manifest schema + loader (P1-A)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from plugins.petri_audit.manifest import (
    DEFAULT_MANIFEST_PATH,
    AdapterSpec,
    PetriManifest,
    RoleContract,
    RoleSpec,
    SourceSpec,
    _parse_manifest_dict,
    clear_manifest_cache,
    load_manifest,
    parse_role_contract,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    clear_manifest_cache()
    yield
    clear_manifest_cache()


def _valid_dict() -> dict[str, Any]:
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


def test_default_manifest_loads() -> None:
    manifest = load_manifest()
    assert isinstance(manifest, PetriManifest)
    assert set(manifest.enabled_roles) == {"auditor", "target", "judge"}
    assert "anthropic" in manifest.sources
    assert "openai" in manifest.sources
    assert "zhipuai" in manifest.sources


def test_default_manifest_role_defaults_in_allowed() -> None:
    manifest = load_manifest()
    for role_name in manifest.enabled_roles:
        spec = manifest.get_role(role_name)
        assert spec.default_model in spec.allowed_models


def test_default_manifest_adapter_coverage() -> None:
    """Every non-auto source in source.allowed has an adapter."""
    manifest = load_manifest()
    for provider, source_spec in manifest.sources.items():
        for source in source_spec.allowed:
            if source == "auto":
                continue
            # raises if missing
            manifest.get_adapter(provider, source)


def test_default_manifest_default_path_constant() -> None:
    assert DEFAULT_MANIFEST_PATH.name == "petri.plugin.toml"
    assert DEFAULT_MANIFEST_PATH.exists()


def test_default_manifest_inspect_prefixes() -> None:
    """Inspect prefixes match the existing to_inspect_model contract."""
    manifest = load_manifest()
    assert manifest.get_adapter("anthropic", "api_key").inspect_prefix == "anthropic"
    assert manifest.get_adapter("anthropic", "claude-cli").inspect_prefix == "claude-code"
    assert manifest.get_adapter("openai", "api_key").inspect_prefix == "openai"
    assert manifest.get_adapter("openai", "openai-codex").inspect_prefix == "openai-codex"
    assert manifest.get_adapter("zhipuai", "api_key").inspect_prefix == "geode"


# ── Negative validation paths ──────────────────────────────────────────────


def test_role_default_not_in_allowed_raises() -> None:
    bad = _valid_dict()
    bad["petri"]["role"]["auditor"]["default_model"] = "claude-haiku-4-5"
    with pytest.raises(ValueError, match="default_model"):
        _parse_manifest_dict(bad)


def test_source_default_not_in_allowed_raises() -> None:
    bad = _valid_dict()
    bad["petri"]["source"]["anthropic"]["default"] = "openai-codex"
    with pytest.raises(ValueError, match="source default"):
        _parse_manifest_dict(bad)


def test_missing_adapter_for_allowed_source_raises() -> None:
    bad = _valid_dict()
    bad["petri"]["source"]["anthropic"]["allowed"] = [
        "api_key",
        "claude-cli",
        "openai-codex",
        "auto",
    ]
    with pytest.raises(ValueError, match="no adapter"):
        _parse_manifest_dict(bad)


def test_enabled_role_without_spec_raises() -> None:
    bad = _valid_dict()
    bad["petri"]["enabled_roles"] = ["auditor", "judge", "target"]
    with pytest.raises(ValueError, match="role spec keys"):
        _parse_manifest_dict(bad)


def test_missing_petri_root_raises() -> None:
    with pytest.raises(ValueError, match="\\[petri\\] root"):
        _parse_manifest_dict({})


# ── Accessor behaviour ─────────────────────────────────────────────────────


def test_get_role_unknown_raises_keyerror() -> None:
    manifest = load_manifest()
    with pytest.raises(KeyError, match="Unknown petri role"):
        manifest.get_role("nonexistent")


def test_get_source_unknown_raises_keyerror() -> None:
    manifest = load_manifest()
    with pytest.raises(KeyError, match="Unknown petri provider"):
        manifest.get_source("nonexistent")


def test_get_adapter_auto_raises_valueerror() -> None:
    manifest = load_manifest()
    with pytest.raises(ValueError, match="Cannot resolve adapter for 'auto'"):
        manifest.get_adapter("anthropic", "auto")


def test_get_adapter_unknown_source_raises() -> None:
    manifest = load_manifest()
    with pytest.raises(KeyError, match="No adapter for"):
        manifest.get_adapter("anthropic", "nonexistent")


# ── Cache behaviour ────────────────────────────────────────────────────────


def test_load_manifest_caches_by_path(tmp_path: Path) -> None:
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


def test_clear_manifest_cache_forces_reload(tmp_path: Path) -> None:
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


def test_role_spec_round_trip() -> None:
    spec = RoleSpec(
        default_model="x",
        allowed_models=["x", "y"],
        role_contract="roles/x.md",
    )
    assert spec.default_model == "x"
    assert spec.role_contract == "roles/x.md"


def test_source_spec_round_trip() -> None:
    spec = SourceSpec(default="api_key", allowed=["api_key", "auto"])
    assert spec.default == "api_key"


def test_adapter_spec_optional_fields() -> None:
    spec = AdapterSpec(
        module="plugins.petri_audit.adapters.http_anthropic",
        inspect_prefix="anthropic",
    )
    assert spec.auth_env_vars == []
    assert spec.endpoint is None
    assert spec.binary is None


# ── Role contract parsing ──────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["auditor", "target", "judge"])
def test_default_role_contracts_parse(role: str) -> None:
    """Every role enabled in the default manifest has a parsable contract MD
    whose frontmatter agrees with the manifest entry."""
    manifest = load_manifest()
    contract = manifest.get_role_contract(role)
    assert isinstance(contract, RoleContract)
    assert contract.role == role
    spec = manifest.get_role(role)
    assert contract.default_model == spec.default_model
    assert contract.default_model in spec.allowed_models


def test_role_contract_inline_skills_optional(tmp_path: Path) -> None:
    contract_path = tmp_path / "x.md"
    contract_path.write_text(
        """---
role: x
description: minimal
default_model: m
default_source: auto
---

body
""",
        encoding="utf-8",
    )
    contract = parse_role_contract(contract_path)
    assert contract.inline_skills == []


def test_parse_role_contract_missing_frontmatter(tmp_path: Path) -> None:
    bad = tmp_path / "no_frontmatter.md"
    bad.write_text("# Just a heading\n\nNo frontmatter here.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        parse_role_contract(bad)


def test_parse_role_contract_malformed_unclosed(tmp_path: Path) -> None:
    bad = tmp_path / "malformed.md"
    bad.write_text("---\nrole: x\ndescription: never closes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed frontmatter"):
        parse_role_contract(bad)


def test_parse_role_contract_frontmatter_not_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "list_frontmatter.md"
    bad.write_text("---\n- a\n- b\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a YAML mapping"):
        parse_role_contract(bad)


def test_get_role_contract_role_mismatch(tmp_path: Path) -> None:
    """Frontmatter role != manifest key → ValueError."""
    contract_path = tmp_path / "wrong_role.md"
    contract_path.write_text(
        """---
role: imposter
description: wrong role
default_model: claude-sonnet-4-6
default_source: auto
---
""",
        encoding="utf-8",
    )
    # Use the default manifest's auditor entry, but point its role_contract
    # at our tmp file with a mismatched role frontmatter.
    manifest = load_manifest()
    auditor_spec = manifest.get_role("auditor")
    # Build a transient PetriManifest pointing at the tmp file.
    bad_manifest = PetriManifest(
        enabled_roles=["auditor"],
        roles={
            "auditor": RoleSpec(
                default_model=auditor_spec.default_model,
                allowed_models=auditor_spec.allowed_models,
                role_contract=str(contract_path.name),
            )
        },
        sources=manifest.sources,
        adapters=manifest.adapters,
    )
    with pytest.raises(ValueError, match="frontmatter role="):
        bad_manifest.get_role_contract("auditor", base_dir=tmp_path)


def test_get_role_contract_default_model_mismatch(tmp_path: Path) -> None:
    """Frontmatter default_model != manifest default_model → ValueError."""
    contract_path = tmp_path / "auditor.md"
    contract_path.write_text(
        """---
role: auditor
description: drifted default_model
default_model: claude-opus-4-7
default_source: auto
---
""",
        encoding="utf-8",
    )
    manifest = load_manifest()
    auditor_spec = manifest.get_role("auditor")
    bad_manifest = PetriManifest(
        enabled_roles=["auditor"],
        roles={
            "auditor": RoleSpec(
                default_model=auditor_spec.default_model,  # claude-sonnet-4-6
                allowed_models=auditor_spec.allowed_models,
                role_contract="auditor.md",
            )
        },
        sources=manifest.sources,
        adapters=manifest.adapters,
    )
    with pytest.raises(ValueError, match="frontmatter default_model="):
        bad_manifest.get_role_contract("auditor", base_dir=tmp_path)


def test_get_role_contract_no_path_raises(tmp_path: Path) -> None:
    """role_contract = None in manifest → get_role_contract raises."""
    manifest = load_manifest()
    auditor_spec = manifest.get_role("auditor")
    bad_manifest = PetriManifest(
        enabled_roles=["auditor"],
        roles={
            "auditor": RoleSpec(
                default_model=auditor_spec.default_model,
                allowed_models=auditor_spec.allowed_models,
                role_contract=None,
            )
        },
        sources=manifest.sources,
        adapters=manifest.adapters,
    )
    with pytest.raises(ValueError, match="no role_contract path"):
        bad_manifest.get_role_contract("auditor", base_dir=tmp_path)
