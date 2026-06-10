"""PR-VOTER-EFFORT-OVERRIDE-HATCH (Sprint G/H follow-up, 2026-05-26)
— per-voter ``reasoning.effort`` override propagation.

Pin the operator escape-hatch: ``[[seed_generation.judge_panel.voters]]
effort = "low"`` in ``~/.geode/config.toml`` flips one voter's effort
without redeploy. Empty (the manifest default) preserves the Sprint G
``"none"`` floor that ranker already pins.

Tests:
  1. ``VoterSpec`` accepts optional ``effort`` (default "").
  2. ``VoterBinding`` carries ``effort`` through the picker.
  3. ``picker.pick_bindings`` propagates ``VoterSpec.effort`` into
     ``VoterBinding.effort``.
  4. Ranker ``_build_voter_tasks`` uses ``voter.effort`` when set,
     falls back to ``"none"`` when empty.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from plugins.seed_generation.manifest import (
    JudgePanelSpec,
    SeedGenerationManifest,
    SeedRoleSpec,
    VoterSpec,
)
from plugins.seed_generation.picker import VoterBinding, pick_bindings
from plugins.seed_generation.tournament import MatchPlan


def test_voter_spec_accepts_optional_effort() -> None:
    """``VoterSpec`` exposes ``effort`` with empty-string default
    (back-compat — pre-fix TOML rows without ``effort`` still load)."""
    v = VoterSpec(model="gpt-5.5", provider="openai", source="openai-codex")
    assert v.effort == ""

    v2 = VoterSpec(model="gpt-5.5", provider="openai", source="openai-codex", effort="low")
    assert v2.effort == "low"


def test_voter_binding_carries_effort_field() -> None:
    """``VoterBinding`` dataclass exposes ``effort`` so the picker can
    propagate the manifest value to the ranker."""
    b = VoterBinding(model="m", provider="p", source="s", effort="medium")
    assert b.effort == "medium"
    # Default empty for back-compat call sites.
    b2 = VoterBinding(model="m", provider="p", source="s")
    assert b2.effort == ""


def _minimal_manifest(voter_effort: str = "") -> SeedGenerationManifest:
    """Manifest with 2 voters where the first carries the override
    effort and the second uses default empty."""
    voter_first = VoterSpec(
        model="gpt-5.5", provider="openai", source="openai-codex", effort=voter_effort
    )
    voter_second = VoterSpec(model="claude-opus-4-7", provider="anthropic", source="claude-cli")
    return SeedGenerationManifest(
        enabled_roles=["generator"],
        roles={
            "generator": SeedRoleSpec(
                default_model="claude-opus-4-7",
                allowed_models=["claude-opus-4-7"],
            ),
        },
        judge_panel=JudgePanelSpec(
            voters=[voter_first, voter_second],
            required_diversity_providers=2,
        ),
    )


def test_picker_propagates_voter_effort_into_binding() -> None:
    """``pick_bindings`` must forward ``VoterSpec.effort`` into the
    matching ``VoterBinding`` — operator override path."""
    manifest = _minimal_manifest(voter_effort="high")
    result = pick_bindings(manifest=manifest, overrides={}, auto_probe=False)
    assert len(result.voters) == 2
    # First voter inherits the operator override.
    assert result.voters[0].effort == "high"
    # Second voter has no override, stays empty.
    assert result.voters[1].effort == ""


def test_ranker_voter_subtask_uses_voter_effort_when_set() -> None:
    """When ``VoterBinding.effort`` is non-empty, the ranker's
    SubTask carries that effort; when empty, falls back to Sprint G
    default ``"none"``."""
    from plugins.seed_generation.agents.ranker import Ranker

    voters = [
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex", effort="low"),
        VoterBinding(model="claude-opus-4-7", provider="anthropic", source="claude-cli"),
    ]
    ranker = Ranker(manager=MagicMock(), voters=voters)
    match = MatchPlan(match_id="m000", a="c_a", b="c_b")
    tasks = ranker._build_voter_tasks(
        match,
        pilot_means={},
        candidate_bodies={"c_a": "body-a", "c_b": "body-b"},
    )
    # 2 voters × 1 match = 2 tasks
    assert len(tasks) == 2
    # First voter override → effort="low"
    assert tasks[0].effort == "low", (
        f"voter.effort='low' override must flow to SubTask.effort; got {tasks[0].effort!r}"
    )
    # Second voter empty → Sprint G default "none"
    assert tasks[1].effort == "none", (
        f"empty voter.effort must fall back to 'none'; got {tasks[1].effort!r}"
    )


def test_voter_spec_invalid_source_still_rejected_after_effort_addition() -> None:
    """Regression guard — adding ``effort`` must not weaken the
    existing ``source="auto"`` rejection."""
    with pytest.raises(ValueError, match="auto"):
        VoterSpec(model="m", provider="anthropic", source="auto", effort="low")


def test_voter_spec_rejects_invalid_effort_value() -> None:
    """Codex MCP catch — operator typo (e.g. ``"loww"``) must fail at
    manifest load, not silently flow to the server."""
    with pytest.raises(ValueError, match="reasoning_effort"):
        VoterSpec(model="gpt-5.5", provider="openai", source="openai-codex", effort="loww")


def test_voter_spec_accepts_all_documented_effort_values() -> None:
    """Every value in the OpenAI Responses API documented enum + empty
    sentinel must pass the validator."""
    for effort in ("", "none", "minimal", "low", "medium", "high", "xhigh"):
        v = VoterSpec(model="gpt-5.5", provider="openai", source="openai-codex", effort=effort)
        assert v.effort == effort


def test_config_toml_voter_overrides_full_panel_replacement(tmp_path) -> None:
    """Codex MCP HIGH catch — config.toml
    ``[[seed_generation.judge_panel.voters]]`` must actually replace
    the bundled manifest's voter list. Pre-fold the picker ignored
    this section so the advertised operator override didn't work."""
    from plugins.seed_generation.picker import _load_config_toml_voter_overrides

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[[seed_generation.judge_panel.voters]]\n"
        'model = "gpt-5.5"\n'
        'provider = "openai"\n'
        'source = "openai-codex"\n'
        'effort = "low"\n'
        "\n"
        "[[seed_generation.judge_panel.voters]]\n"
        'model = "claude-opus-4-7"\n'
        'provider = "anthropic"\n'
        'source = "claude-cli"\n'
        'effort = "high"\n',
        encoding="utf-8",
    )
    overrides = _load_config_toml_voter_overrides(cfg)
    assert overrides is not None
    assert len(overrides) == 2
    assert overrides[0].model == "gpt-5.5"
    assert overrides[0].effort == "low"
    assert overrides[1].model == "claude-opus-4-7"
    assert overrides[1].effort == "high"


def test_config_toml_voter_overrides_missing_returns_none(tmp_path) -> None:
    """When config.toml has no ``[[seed_generation.judge_panel.voters]]``
    section the loader returns ``None`` so pick_bindings falls back to
    the bundled manifest."""
    from plugins.seed_generation.picker import _load_config_toml_voter_overrides

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[seed_generation.role.generator]\nmodel = "claude-opus-4-7"\n',
        encoding="utf-8",
    )
    overrides = _load_config_toml_voter_overrides(cfg)
    assert overrides is None


def test_config_toml_voter_overrides_missing_file_returns_none(tmp_path) -> None:
    """Missing config.toml entirely → None."""
    from plugins.seed_generation.picker import _load_config_toml_voter_overrides

    overrides = _load_config_toml_voter_overrides(tmp_path / "nope.toml")
    assert overrides is None


def test_config_toml_voter_overrides_invalid_entry_skipped(tmp_path) -> None:
    """A voter entry with bad effort is dropped (with a WARN) rather
    than killing the whole load — operator can still bring up the
    panel if one entry typo'd."""
    from plugins.seed_generation.picker import _load_config_toml_voter_overrides

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[[seed_generation.judge_panel.voters]]\n"
        'model = "gpt-5.5"\n'
        'provider = "openai"\n'
        'source = "openai-codex"\n'
        'effort = "BOGUS_EFFORT"\n'
        "\n"
        "[[seed_generation.judge_panel.voters]]\n"
        'model = "claude-opus-4-7"\n'
        'provider = "anthropic"\n'
        'source = "claude-cli"\n',
        encoding="utf-8",
    )
    overrides = _load_config_toml_voter_overrides(cfg)
    assert overrides is not None
    # Only the valid entry survives.
    assert len(overrides) == 1
    assert overrides[0].model == "claude-opus-4-7"
