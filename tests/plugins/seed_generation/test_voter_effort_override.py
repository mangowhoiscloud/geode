"""PR-VOTER-EFFORT-OVERRIDE-HATCH (Sprint G/H follow-up, 2026-05-26)
— per-voter ``reasoning.effort`` override propagation.

Pin the operator escape-hatch: ``[[seed_generation.judge_panel.voters]]
effort = "low"`` in ``~/.geode/config.toml`` flips one voter's effort
without redeploy. Empty (the manifest default) preserves the Sprint G
``"none"`` floor that ranker / mutation_eval already pin.

Tests:
  1. ``VoterSpec`` accepts optional ``effort`` (default "").
  2. ``VoterBinding`` carries ``effort`` through the picker.
  3. ``picker.pick_bindings`` propagates ``VoterSpec.effort`` into
     ``VoterBinding.effort``.
  4. Ranker ``_build_voter_tasks`` uses ``voter.effort`` when set,
     falls back to ``"none"`` when empty.
  5. mutation_eval voter dispatch same.
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


def test_mutation_eval_voter_uses_voter_effort_when_set() -> None:
    """Mirror invariant on ``evaluate_mutation_pairwise`` voter dispatch."""
    import asyncio

    from plugins.seed_generation.mutation_eval import evaluate_mutation_pairwise

    voters = [
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex", effort="medium"),
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="claude-opus-4-7", provider="anthropic", source="claude-cli"),
    ]
    dispatched: list = []

    class StubManager:
        async def adelegate(self, tasks, *, announce: bool = True):
            dispatched.extend(tasks)
            from core.agent.sub_agent import SubResult

            return [
                SubResult(
                    task_id=t.task_id,
                    description="stub",
                    success=False,
                    output={},
                    error="stub",
                    duration_ms=0.0,
                )
                for t in tasks
            ]

    asyncio.run(
        evaluate_mutation_pairwise(
            before_response="before",
            after_response="after",
            scenario_seed="seed",
            voters=voters,
            manager=StubManager(),  # type: ignore[arg-type]
            match_id="m-override-pin",
        )
    )

    assert len(dispatched) == 3
    # voters[0] has effort="medium" override
    assert dispatched[0].effort == "medium"
    # voters[1] empty → "none"
    assert dispatched[1].effort == "none"
    # voters[2] empty → "none"
    assert dispatched[2].effort == "none"


def test_voter_spec_invalid_source_still_rejected_after_effort_addition() -> None:
    """Regression guard — adding ``effort`` must not weaken the
    existing ``source="auto"`` rejection."""
    with pytest.raises(ValueError, match="auto"):
        VoterSpec(model="m", provider="anthropic", source="auto", effort="low")
