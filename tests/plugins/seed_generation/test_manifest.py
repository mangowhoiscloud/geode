"""Tests for ``plugins.seed_generation.manifest``.

Coverage targets the P-checklist (cycle-skill SKILL.md):

- P4 Environment Anchor — DEFAULT_MANIFEST_PATH package-relative
- P7 Caller-Callee Contract — voter (provider, source) cross-validated
  against the Petri manifest's source table
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from plugins.seed_generation.manifest import (
    DEFAULT_MANIFEST_PATH,
    JudgePanelSpec,
    SeedGenerationManifest,
    SeedRoleSpec,
    VoterSpec,
    _parse_manifest_dict,
    clear_manifest_cache,
    load_manifest,
)

# ---------------------------------------------------------------------------
# Schema-level validators (in-memory dict input — no TOML round-trip)
# ---------------------------------------------------------------------------


def test_role_default_must_be_in_allowed() -> None:
    with pytest.raises(ValueError, match="default_model"):
        SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-opus-4-7"],
            role_contract=None,
        )


def test_voter_rejects_auto_source() -> None:
    with pytest.raises(ValueError, match="auto"):
        VoterSpec(model="claude-sonnet-4-6", provider="anthropic", source="auto")


def test_judge_panel_requires_minimum_voters() -> None:
    with pytest.raises(ValueError, match=">= 2 voters"):
        JudgePanelSpec(
            voters=[VoterSpec(model="x", provider="anthropic", source="api_key")],
            required_diversity_providers=1,
        )


def test_judge_panel_diversity_violation() -> None:
    with pytest.raises(ValueError, match="diversity violated"):
        JudgePanelSpec(
            voters=[
                VoterSpec(model="x1", provider="anthropic", source="api_key"),
                VoterSpec(model="x2", provider="anthropic", source="claude-cli"),
                VoterSpec(model="x3", provider="anthropic", source="claude-cli"),
            ],
            required_diversity_providers=2,
        )


def test_judge_panel_diversity_satisfied() -> None:
    panel = JudgePanelSpec(
        voters=[
            VoterSpec(model="x1", provider="anthropic", source="api_key"),
            VoterSpec(model="x2", provider="openai", source="api_key"),
        ],
        required_diversity_providers=2,
    )
    assert len(panel.voters) == 2


def test_manifest_role_keys_must_match_enabled_roles() -> None:
    with pytest.raises(ValueError, match="enabled_roles"):
        SeedGenerationManifest(
            enabled_roles=["generator", "critic"],
            roles={
                "generator": SeedRoleSpec(
                    default_model="claude-sonnet-4-6",
                    allowed_models=["claude-sonnet-4-6"],
                ),
                # Missing 'critic' role spec
            },
            judge_panel=JudgePanelSpec(
                voters=[
                    VoterSpec(model="x", provider="anthropic", source="api_key"),
                    VoterSpec(model="y", provider="openai", source="api_key"),
                ],
            ),
        )


# ---------------------------------------------------------------------------
# TOML load path — uses bundled seed_generation.plugin.toml
# ---------------------------------------------------------------------------


def test_default_manifest_path_is_package_relative() -> None:
    """P4 Environment Anchor — the default path must NOT be cwd-relative."""
    assert DEFAULT_MANIFEST_PATH.is_absolute()
    assert DEFAULT_MANIFEST_PATH.parent.name == "seed_generation"
    assert DEFAULT_MANIFEST_PATH.name == "seed_generation.plugin.toml"


def test_bundled_manifest_loads() -> None:
    clear_manifest_cache()
    manifest = load_manifest()
    assert set(manifest.enabled_roles) == {
        "generator",
        "critic",
        "proximity",
        "pilot",
        "ranker",
        "evolver",
        "meta_reviewer",
    }
    assert manifest.voter_diversity() >= 2


def test_bundled_manifest_voters_pass_cross_validation() -> None:
    """P7 Caller-Callee Contract — voters must reference real Petri sources."""
    clear_manifest_cache()
    manifest = load_manifest()
    voters = manifest.judge_panel.voters
    # The defaults pin (anthropic, claude-cli), (openai, openai-codex),
    # (anthropic, api_key) — all must be in Petri's allowed lists.
    for voter in voters:
        assert voter.provider in {"anthropic", "openai"}
        assert voter.source in {"claude-cli", "openai-codex", "api_key"}


def test_voter_unknown_provider_rejected(tmp_path: Path) -> None:
    """Cross-manifest validation — unknown provider in voter must fail."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text(
        textwrap.dedent(
            """\
            [seed_generation]
            enabled_roles = ["generator"]

            [seed_generation.role.generator]
            default_model = "x"
            allowed_models = ["x"]

            [seed_generation.judge_panel]
            required_diversity_providers = 2

            [[seed_generation.judge_panel.voters]]
            model = "x"
            provider = "imaginary-llm-provider"
            source = "api_key"

            [[seed_generation.judge_panel.voters]]
            model = "y"
            provider = "anthropic"
            source = "api_key"
            """
        )
    )
    clear_manifest_cache()
    with pytest.raises(ValueError, match=r"not in petri\.source table"):
        load_manifest(bad_toml)


def test_voter_unknown_source_rejected(tmp_path: Path) -> None:
    """Cross-manifest validation — typo'd source in voter must fail."""
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text(
        textwrap.dedent(
            """\
            [seed_generation]
            enabled_roles = ["generator"]

            [seed_generation.role.generator]
            default_model = "x"
            allowed_models = ["x"]

            [seed_generation.judge_panel]
            required_diversity_providers = 2

            [[seed_generation.judge_panel.voters]]
            model = "x"
            provider = "anthropic"
            source = "claude_cli"

            [[seed_generation.judge_panel.voters]]
            model = "y"
            provider = "openai"
            source = "api_key"
            """
        )
    )
    clear_manifest_cache()
    with pytest.raises(ValueError, match=r"not in petri\.source\.anthropic\.allowed"):
        load_manifest(bad_toml)


def test_manifest_get_role_unknown_raises() -> None:
    clear_manifest_cache()
    manifest = load_manifest()
    with pytest.raises(KeyError, match="Unknown seed_generation role"):
        manifest.get_role("nonexistent")


def test_manifest_get_role_known_returns_spec() -> None:
    clear_manifest_cache()
    manifest = load_manifest()
    spec = manifest.get_role("generator")
    assert spec.default_model in spec.allowed_models


def test_role_kind_completion_default() -> None:
    """Roles default to kind='completion' when not specified."""
    spec = SeedRoleSpec(
        default_model="claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6"],
    )
    assert spec.kind == "completion"


def test_role_kind_embedding_explicit() -> None:
    """An embedding role (e.g. proximity) must set kind='embedding'."""
    spec = SeedRoleSpec(
        default_model="text-embedding-3-small",
        allowed_models=["text-embedding-3-small"],
        kind="embedding",
    )
    assert spec.kind == "embedding"


def test_bundled_proximity_role_is_completion() -> None:
    """CSP-8 (2026-05-22): Proximity role flipped from ``kind="embedding"``
    to ``kind="completion"`` when it reverted to the paper's LLM-clustering
    pattern. The ``kind`` field stays in the schema for forward-compat —
    a future plugin may want a non-completion role kind — but no role
    in the bundled seed-generation manifest currently uses it."""
    clear_manifest_cache()
    manifest = load_manifest()
    proximity = manifest.get_role("proximity")
    assert proximity.kind == "completion"
    # Sibling check — every shipped role is now completion.
    assert manifest.get_role("generator").kind == "completion"
    assert manifest.get_role("critic").kind == "completion"


# ---------------------------------------------------------------------------
# Parse path (no I/O — dict literal)
# ---------------------------------------------------------------------------


def test_parse_manifest_dict_missing_root_raises() -> None:
    with pytest.raises(ValueError, match=r"missing \[seed_generation\] root"):
        _parse_manifest_dict({"unrelated": "section"})


def test_parse_manifest_dict_minimal_valid() -> None:
    data: dict = {
        "seed_generation": {
            "enabled_roles": ["generator"],
            "role": {
                "generator": {
                    "default_model": "claude-sonnet-4-6",
                    "allowed_models": ["claude-sonnet-4-6"],
                }
            },
            "judge_panel": {
                "required_diversity_providers": 2,
                "voters": [
                    {
                        "model": "claude-sonnet-4-6",
                        "provider": "anthropic",
                        "source": "api_key",
                    },
                    {
                        "model": "gpt-5.5",
                        "provider": "openai",
                        "source": "api_key",
                    },
                ],
            },
        }
    }
    manifest = _parse_manifest_dict(data)
    assert manifest.enabled_roles == ["generator"]
    assert manifest.voter_diversity() == 2
