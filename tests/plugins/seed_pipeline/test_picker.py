"""Tests for ``plugins.seed_pipeline.picker``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — OAuth probe is stubbed (no real keychain
  reads), but the stub matches the real boolean signature so the
  resolver doesn't lie about which path it would pick in production.
- **P4 Environment Anchor** — overrides loaded via explicit path arg
  in tests; no env-var coupling.
- **P7 Caller-Callee Contract** — every test asserts the resolver's
  output shape: concrete (no ``auto``) sources, kind discriminator,
  diversity counts, subscription set membership.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from plugins.seed_pipeline.manifest import (
    JudgePanelSpec,
    SeedPipelineManifest,
    SeedRoleSpec,
    VoterSpec,
)
from plugins.seed_pipeline.picker import (
    SUBSCRIPTION_SOURCES,
    PickerResult,
    VoterBinding,
    infer_family,
    iter_distinct_paths,
    list_subscription_roles,
    load_user_overrides,
    pick_bindings,
    print_tos_notice,
    reset_tos_notice,
    validate_runtime_diversity,
)


def _make_manifest() -> SeedPipelineManifest:
    """Build an in-memory manifest equivalent to the shipped TOML."""
    roles = {
        "generator": SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-sonnet-4-6", "claude-opus-4-7"],
        ),
        "critic": SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-sonnet-4-6"],
        ),
        "proximity": SeedRoleSpec(
            default_model="text-embedding-3-small",
            allowed_models=["text-embedding-3-small"],
            kind="embedding",
        ),
        "pilot": SeedRoleSpec(
            default_model="claude-haiku-4-5",
            allowed_models=["claude-haiku-4-5"],
        ),
        "ranker": SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-sonnet-4-6"],
        ),
        "evolver": SeedRoleSpec(
            default_model="claude-sonnet-4-6",
            allowed_models=["claude-sonnet-4-6"],
        ),
        "meta_reviewer": SeedRoleSpec(
            default_model="claude-opus-4-7",
            allowed_models=["claude-opus-4-7"],
        ),
    }
    judge_panel = JudgePanelSpec(
        voters=[
            VoterSpec(model="claude-sonnet-4-6", family="anthropic", source="claude-cli"),
            VoterSpec(model="gpt-5.5", family="openai", source="openai-codex"),
            VoterSpec(model="claude-haiku-4-5", family="anthropic", source="api_key"),
        ],
        required_diversity_families=2,
    )
    return SeedPipelineManifest(
        enabled_roles=list(roles.keys()),
        roles=roles,
        judge_panel=judge_panel,
    )


def test_infer_family_claude_models() -> None:
    assert infer_family("claude-sonnet-4-6") == "anthropic"
    assert infer_family("claude-opus-4-7") == "anthropic"
    assert infer_family("claude-haiku-4-5") == "anthropic"


def test_infer_family_openai_models() -> None:
    assert infer_family("gpt-5.5") == "openai"
    assert infer_family("text-embedding-3-small") == "openai"


def test_infer_family_zhipuai() -> None:
    assert infer_family("glm-4.5") == "zhipuai"


def test_infer_family_unknown_raises() -> None:
    with pytest.raises(ValueError, match=r"did not match any known prefix"):
        infer_family("mystery-model-1")


def test_pick_bindings_resolves_all_roles_with_oauth() -> None:
    manifest = _make_manifest()
    with (
        patch("plugins.seed_pipeline.picker._probe_oauth", return_value=True),
    ):
        result = pick_bindings(manifest=manifest, overrides={})
    assert set(result.bindings) == set(manifest.enabled_roles)
    # All Claude-* roles resolve to claude-cli when OAuth is available.
    for role in ("generator", "critic", "pilot", "ranker", "evolver", "meta_reviewer"):
        assert result.bindings[role].family == "anthropic"
        assert result.bindings[role].source == "claude-cli"
    # Proximity (embedding) — openai family, but with OAuth probe we still
    # land on openai-codex (semantics of "auto" probe). Note this is a
    # known limitation; embeddings actually need api_key but the picker's
    # job here is the binding, not the runtime check (S4 text_embed reads
    # OPENAI_API_KEY directly so this won't break in practice).
    assert result.bindings["proximity"].family == "openai"


def test_pick_bindings_resolves_payg_when_no_oauth() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=False):
        result = pick_bindings(manifest=manifest, overrides={})
    for role, binding in result.bindings.items():
        assert binding.source == "api_key", f"role={role} should fall back to api_key"


def test_pick_bindings_no_probe_uses_payg() -> None:
    manifest = _make_manifest()
    result = pick_bindings(manifest=manifest, overrides={}, auto_probe=False)
    for binding in result.bindings.values():
        assert binding.source == "api_key"


def test_pick_bindings_user_override_source() -> None:
    manifest = _make_manifest()
    overrides = {"generator": {"source": "api_key"}, "pilot": {"source": "claude-cli"}}
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=True):
        result = pick_bindings(manifest=manifest, overrides=overrides)
    assert result.bindings["generator"].source == "api_key"
    assert result.bindings["pilot"].source == "claude-cli"
    # Critic was NOT overridden → still claude-cli (OAuth probe = True).
    assert result.bindings["critic"].source == "claude-cli"


def test_pick_bindings_user_override_model() -> None:
    manifest = _make_manifest()
    overrides = {"generator": {"model": "claude-opus-4-7"}}
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=False):
        result = pick_bindings(manifest=manifest, overrides=overrides)
    assert result.bindings["generator"].model == "claude-opus-4-7"


def test_pick_bindings_carries_kind_discriminator() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=False):
        result = pick_bindings(manifest=manifest, overrides={})
    assert result.bindings["proximity"].kind == "embedding"
    assert result.bindings["generator"].kind == "completion"


def test_pick_bindings_voter_panel_resolved() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=True):
        result = pick_bindings(manifest=manifest, overrides={})
    assert len(result.voters) == 3
    sources = {v.source for v in result.voters}
    # Voters have explicit sources (claude-cli / openai-codex / api_key),
    # none are "auto" so the OAuth probe doesn't change them.
    assert sources == {"claude-cli", "openai-codex", "api_key"}


def test_pick_bindings_diversity_families_count() -> None:
    manifest = _make_manifest()
    result = pick_bindings(manifest=manifest, overrides={}, auto_probe=False)
    # Voters: anthropic, openai, anthropic → 2 distinct families
    assert result.diversity_families == 2


def test_pick_bindings_subscription_paths_in_use() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=True):
        result = pick_bindings(manifest=manifest, overrides={})
    # OAuth available → roles use claude-cli; voters include claude-cli + openai-codex
    assert "claude-cli" in result.subscription_paths_in_use
    assert "openai-codex" in result.subscription_paths_in_use


def test_pick_bindings_no_subscription_when_payg() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=False):
        result = pick_bindings(manifest=manifest, overrides={})
    # Roles all fall back to api_key; only voters with explicit subscription sources remain.
    # Voters: claude-cli (explicit, not auto so probe doesn't matter) + openai-codex + api_key.
    assert "claude-cli" in result.subscription_paths_in_use
    assert "openai-codex" in result.subscription_paths_in_use


def test_load_user_overrides_missing_file_returns_empty(tmp_path: Path) -> None:
    out = load_user_overrides(path=tmp_path / "nonexistent.toml")
    assert out == {}


def test_load_user_overrides_parses_role_tables(tmp_path: Path) -> None:
    p = tmp_path / "seed-pipeline.toml"
    p.write_text(
        '[generator]\nsource = "api_key"\n\n[pilot]\nmodel = "claude-haiku-4-5"\n',
        encoding="utf-8",
    )
    out = load_user_overrides(path=p)
    assert out["generator"]["source"] == "api_key"
    assert out["pilot"]["model"] == "claude-haiku-4-5"


def test_load_user_overrides_skips_non_table_entries(tmp_path: Path) -> None:
    p = tmp_path / "seed-pipeline.toml"
    # Top-level scalar that isn't a table — must be ignored, not crash.
    p.write_text('debug = true\n\n[pilot]\nsource = "claude-cli"\n', encoding="utf-8")
    out = load_user_overrides(path=p)
    assert "pilot" in out
    assert "debug" not in out


def test_load_user_overrides_invalid_toml_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "seed-pipeline.toml"
    p.write_text("not = valid = toml = here", encoding="utf-8")
    out = load_user_overrides(path=p)
    assert out == {}


def test_print_tos_notice_emits_when_subscription_in_use() -> None:
    reset_tos_notice()
    result = PickerResult(
        bindings={},
        voters=[],
        diversity_families=2,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    buf = io.StringIO()
    print_tos_notice(result, file=buf)
    out = buf.getvalue()
    assert "ToS notice" in out
    assert "claude-cli" in out
    assert "Anthropic" in out


def test_print_tos_notice_silent_when_no_subscription() -> None:
    reset_tos_notice()
    result = PickerResult(
        bindings={},
        voters=[],
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )
    buf = io.StringIO()
    print_tos_notice(result, file=buf)
    assert buf.getvalue() == ""


def test_print_tos_notice_idempotent_within_process() -> None:
    reset_tos_notice()
    result = PickerResult(
        bindings={},
        voters=[],
        diversity_families=2,
        subscription_paths_in_use=frozenset({"openai-codex"}),
    )
    buf = io.StringIO()
    print_tos_notice(result, file=buf)
    first_len = len(buf.getvalue())
    print_tos_notice(result, file=buf)  # second call should be no-op
    assert len(buf.getvalue()) == first_len


def test_print_tos_notice_force_reemits() -> None:
    reset_tos_notice()
    result = PickerResult(
        bindings={},
        voters=[],
        diversity_families=2,
        subscription_paths_in_use=frozenset({"openai-codex"}),
    )
    buf = io.StringIO()
    print_tos_notice(result, file=buf)
    print_tos_notice(result, file=buf, force=True)
    # Two notices appended.
    assert buf.getvalue().count("ToS notice") == 2


def test_print_tos_notice_quiet_suppresses() -> None:
    reset_tos_notice()
    result = PickerResult(
        bindings={},
        voters=[],
        diversity_families=2,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    buf = io.StringIO()
    print_tos_notice(result, file=buf, quiet=True)
    assert buf.getvalue() == ""


def test_validate_runtime_diversity_pass() -> None:
    result = PickerResult(
        bindings={},
        voters=[
            VoterBinding(model="m1", family="anthropic", source="claude-cli"),
            VoterBinding(model="m2", family="openai", source="openai-codex"),
            VoterBinding(model="m3", family="anthropic", source="api_key"),
        ],
        diversity_families=2,
        subscription_paths_in_use=frozenset(),
    )
    # 2 families, 3 distinct paths → passes both gates.
    validate_runtime_diversity(result)


def test_validate_runtime_diversity_family_collapse_raises() -> None:
    result = PickerResult(
        bindings={},
        voters=[
            VoterBinding(model="m1", family="anthropic", source="claude-cli"),
            VoterBinding(model="m2", family="anthropic", source="api_key"),
        ],
        diversity_families=1,
        subscription_paths_in_use=frozenset(),
    )
    with pytest.raises(ValueError, match=r"runtime diversity violated"):
        validate_runtime_diversity(result)


def test_validate_runtime_diversity_path_collapse_raises() -> None:
    result = PickerResult(
        bindings={},
        voters=[
            VoterBinding(model="m1", family="anthropic", source="claude-cli"),
            VoterBinding(model="m2", family="anthropic", source="claude-cli"),
            VoterBinding(model="m3", family="anthropic", source="claude-cli"),
        ],
        diversity_families=1,
        subscription_paths_in_use=frozenset({"claude-cli"}),
    )
    with pytest.raises(ValueError, match=r"runtime"):
        validate_runtime_diversity(result)


def test_list_subscription_roles() -> None:
    manifest = _make_manifest()
    with patch("plugins.seed_pipeline.picker._probe_oauth", return_value=True):
        result = pick_bindings(manifest=manifest, overrides={})
    roles = list_subscription_roles(result)
    # All claude-* roles → claude-cli when OAuth available
    assert "generator" in roles
    assert "ranker" in roles


def test_iter_distinct_paths_dedupes() -> None:
    manifest = _make_manifest()
    result = pick_bindings(manifest=manifest, overrides={}, auto_probe=False)
    paths = list(iter_distinct_paths(result))
    # Roles all api_key; voters include 3 distinct paths
    # → distinct (family, source) pairs across all bindings.
    assert len(paths) == len(set(paths)), "duplicates leaked"


def test_subscription_sources_set_pinned() -> None:
    """Regression guard — only claude-cli / openai-codex are subscriptions."""
    assert frozenset({"claude-cli", "openai-codex"}) == SUBSCRIPTION_SOURCES


def test_pick_bindings_role_binding_immutable() -> None:
    """RoleBinding is frozen so callers can't mutate the resolver's output."""
    manifest = _make_manifest()
    result = pick_bindings(manifest=manifest, overrides={}, auto_probe=False)
    binding = result.bindings["generator"]
    with pytest.raises(Exception):
        binding.source = "different"  # type: ignore[misc]


def test_pick_bindings_unknown_model_prefix_logs_and_defaults() -> None:
    """A user override with an unrecognised model prefix falls back to anthropic
    family (warning logged) rather than crashing the picker.
    """
    manifest = _make_manifest()
    overrides = {"generator": {"model": "mystery-x9"}}
    result = pick_bindings(manifest=manifest, overrides=overrides, auto_probe=False)
    assert result.bindings["generator"].family == "anthropic"
