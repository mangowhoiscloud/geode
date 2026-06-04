"""PR-SG-SELECTION-ALIGN (2026-05-25) — seed-gen ↔ selection-layer alignment.

Tests for G1 (anchor 3 surface) + G2 (scenario_realism) + G3 (tier .md
drift) + G4 (target_dims_attribution + pick_regression_target_dims).

(G5 Pareto front evolver embed was removed with the group/swarm
machinery in PR-GROUP-REMOVAL, 2026-05-29.)

Plan: docs/plans/2026-05-25-seed-gen-selection-layer-alignment.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _extract_handoff(description: str) -> dict:
    marker = "```json\n"
    start = description.index(marker) + len(marker)
    end = description.rindex("```")
    return json.loads(description[start:end].strip())


# ─────────────────────── G1 — anchor 3 surface ───────────────────────────────


class TestAnchorMeansSurface:
    def test_extract_anchor_means_returns_three_dims(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_anchor_means

        result = extract_anchor_means(
            {
                "admirable": 1.2,
                "disappointing": 0.4,
                "needs_attention": 0.7,
                "broken_tool_use": 1.5,  # not anchor → dropped
            }
        )
        assert result == {"admirable": 1.2, "disappointing": 0.4, "needs_attention": 0.7}

    def test_extract_anchor_means_empty_when_no_anchor_dims(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_anchor_means

        result = extract_anchor_means({"broken_tool_use": 1.5})
        assert result == {}

    def test_extract_anchor_means_skips_non_numeric(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_anchor_means

        result = extract_anchor_means(
            {"admirable": "high", "disappointing": None, "needs_attention": 0.5}
        )
        assert result == {"needs_attention": 0.5}

    def test_anchor_means_matches_anchor_confidence_module(self) -> None:
        """Drift guard: extract_anchor_means keys ↔ anchor_confidence module."""
        from core.self_improving.loop.anchor_confidence import (
            ANCHOR_DIMS_NEGATIVE,
            ANCHOR_DIMS_POSITIVE,
        )
        from plugins.seed_generation.handoff_schemas import extract_anchor_means

        all_anchor = set(ANCHOR_DIMS_POSITIVE) | set(ANCHOR_DIMS_NEGATIVE)
        # Build a dim_means with every anchor key — extract should preserve all.
        dim_means = dict.fromkeys(all_anchor, 1.0)
        result = extract_anchor_means(dim_means)
        assert set(result.keys()) == all_anchor


# ─────────────────────── G2 — scenario_realism routing ───────────────────────


class TestScenarioRealism:
    def test_extract_returns_float(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_scenario_realism

        assert extract_scenario_realism({"scenario_realism": 2.3}) == 2.3

    def test_extract_returns_none_when_absent(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_scenario_realism

        assert extract_scenario_realism({"broken_tool_use": 1.0}) is None

    def test_extract_returns_none_when_non_numeric(self) -> None:
        from plugins.seed_generation.handoff_schemas import extract_scenario_realism

        assert extract_scenario_realism({"scenario_realism": "high"}) is None


# ─────────────────────── G3 — tier .md drift ─────────────────────────────────


PROMPT_DIR = Path(__file__).parents[3] / "plugins" / "seed_generation" / "agents"


class TestTierDocParity:
    """Pin the .md tier blocks to ``core.self_improving.train.AXIS_TIERS``.

    catalog is frozen, but the .md strings hard-code the same dim
    names — drift would surface here as a fail forcing a same-PR sync.
    """

    @pytest.mark.parametrize("md_name", ["critic.md", "evolver.md"])
    def test_md_lists_every_critical_dim(self, md_name: str) -> None:
        from core.self_improving.train import AXIS_TIERS

        body = (PROMPT_DIR / md_name).read_text(encoding="utf-8")
        critical_dims = [d for d, tier in AXIS_TIERS.items() if tier == "critical"]
        assert critical_dims, "AXIS_TIERS must define critical dims"
        for dim in critical_dims:
            assert f"`{dim}`" in body, f"{md_name} missing critical dim {dim}"

    @pytest.mark.parametrize("md_name", ["critic.md", "evolver.md"])
    def test_md_lists_every_auxiliary_dim(self, md_name: str) -> None:
        from core.self_improving.train import AXIS_TIERS

        body = (PROMPT_DIR / md_name).read_text(encoding="utf-8")
        auxiliary_dims = [d for d, tier in AXIS_TIERS.items() if tier == "auxiliary"]
        assert auxiliary_dims
        for dim in auxiliary_dims:
            assert f"`{dim}`" in body, f"{md_name} missing auxiliary dim {dim}"

    @pytest.mark.parametrize("md_name", ["critic.md", "evolver.md"])
    def test_md_lists_every_info_dim(self, md_name: str) -> None:
        from core.self_improving.train import AXIS_TIERS

        body = (PROMPT_DIR / md_name).read_text(encoding="utf-8")
        info_dims = [d for d, tier in AXIS_TIERS.items() if tier == "info"]
        assert info_dims
        for dim in info_dims:
            assert f"`{dim}`" in body, f"{md_name} missing info dim {dim}"

    @pytest.mark.parametrize("md_name", ["critic.md", "evolver.md"])
    def test_md_tier_mapping_matches_axis_tiers(self, md_name: str) -> None:
        """Parse the tier table in each .md and assert dim -> tier
        bidirectional equality with ``core.self_improving.train.AXIS_TIERS``.

        PR-SG-SELECTION-ALIGN-FIX (2026-05-25, V3) — pre-fix
        `test_md_lists_every_<tier>_dim` only asserted "every
        AXIS_TIERS dim appears somewhere in the file"; a dim listed
        under the WRONG tier or a typo in the .md would still pass.
        This test parses the markdown row for each tier and checks
        the dim's actual classification.

        Row format (matched by regex on bold tier label + backticked
        dim names):

            | **<tier> (N)** | `dim_a`, `dim_b`, ... |
        """
        import re

        from core.self_improving.train import AXIS_TIERS

        body = (PROMPT_DIR / md_name).read_text(encoding="utf-8")
        for tier in ("critical", "auxiliary", "info"):
            pattern = re.compile(
                rf"\|\s*\*\*{tier}\s*\(\d+\)\*\*\s*\|\s*(.*?)\s*\|",
                re.DOTALL,
            )
            match = pattern.search(body)
            assert match, f"{md_name}: missing tier row for {tier!r}"
            row_dims = set(re.findall(r"`([a-z_]+)`", match.group(1)))
            expected = {d for d, t in AXIS_TIERS.items() if t == tier}
            assert row_dims == expected, (
                f"{md_name} tier {tier!r} mismatch:\n"
                f"  in .md row: {sorted(row_dims)}\n"
                f"  in AXIS_TIERS: {sorted(expected)}\n"
                f"  unexpected (in md but not catalog): {sorted(row_dims - expected)}\n"
                f"  missing (in catalog but not md): {sorted(expected - row_dims)}"
            )

    @pytest.mark.parametrize("md_name", ["critic.md", "evolver.md"])
    def test_md_has_anchor_section(self, md_name: str) -> None:
        body = (PROMPT_DIR / md_name).read_text(encoding="utf-8")
        assert "## Anchor 3 dims" in body
        for dim in ("admirable", "disappointing", "needs_attention"):
            assert f"`{dim}`" in body


# ─────────────────────── G4 — pick_regression_target_dims ────────────────────


class TestPickRegressionTargetDims:
    def _snapshot(self, dim_means: dict[str, float]):
        from plugins.seed_generation.baseline_reader import BaselineSnapshot

        return BaselineSnapshot(dim_means=dim_means, dim_stderr={})

    def test_top_k_worst_means(self) -> None:
        from plugins.seed_generation.baseline_reader import pick_regression_target_dims

        # 4 operational dims; we expect top-3 by mean.
        snap = self._snapshot(
            {
                "broken_tool_use": 1.5,
                "input_hallucination": 2.3,
                "stuck_in_loops": 0.8,
                "context_attribution": 2.0,
            }
        )
        result = pick_regression_target_dims(snap, k=3, prefer_critical=False)
        assert result == ["input_hallucination", "context_attribution", "broken_tool_use"]

    def test_empty_snapshot_returns_empty_list(self) -> None:
        from plugins.seed_generation.baseline_reader import pick_regression_target_dims

        assert pick_regression_target_dims(self._snapshot({}), k=3) == []

    def test_k_zero_returns_empty_list(self) -> None:
        from plugins.seed_generation.baseline_reader import pick_regression_target_dims

        snap = self._snapshot({"broken_tool_use": 1.0})
        assert pick_regression_target_dims(snap, k=0) == []

    def test_prefer_critical_orders_critical_first(self) -> None:
        from plugins.seed_generation.baseline_reader import pick_regression_target_dims

        # Critical 'broken_tool_use' has LOWER mean than auxiliary
        # 'input_hallucination' but critical-first ordering still puts
        # it ahead.
        snap = self._snapshot(
            {
                "broken_tool_use": 1.0,  # critical
                "input_hallucination": 2.5,  # auxiliary
                "context_attribution": 1.8,  # auxiliary
            }
        )
        result = pick_regression_target_dims(snap, k=3, prefer_critical=True)
        assert result[0] == "broken_tool_use"
        # Remaining 2 in worst-mean order across auxiliary.
        assert result[1:] == ["input_hallucination", "context_attribution"]

    def test_tie_break_alphabetical(self) -> None:
        from plugins.seed_generation.baseline_reader import pick_regression_target_dims

        snap = self._snapshot({"input_hallucination": 1.0, "context_attribution": 1.0})
        result = pick_regression_target_dims(snap, k=2, prefer_critical=False)
        assert result == ["context_attribution", "input_hallucination"]


# ─────────────────────── G4 — PipelineState field ────────────────────────────


class TestPipelineStateTargetDimsAttribution:
    def test_field_default_empty_list(self) -> None:
        from plugins.seed_generation.orchestrator import PipelineState

        state = PipelineState(run_id="r", target_dim="d", gen_tag="g")
        assert state.target_dims_attribution == []

    def test_field_accepts_list(self) -> None:
        from plugins.seed_generation.orchestrator import PipelineState

        state = PipelineState(
            run_id="r",
            target_dim="d",
            gen_tag="g",
            target_dims_attribution=["broken_tool_use", "input_hallucination"],
        )
        assert state.target_dims_attribution == ["broken_tool_use", "input_hallucination"]


# ─────────────────────── G1+G2+G4 — agent handoff embed ──────────────────────


class TestAgentHandoffEmbedding:
    def _state_with_baseline(self) -> object:
        from plugins.seed_generation.baseline_reader import BaselineSnapshot
        from plugins.seed_generation.orchestrator import PipelineState

        snap = BaselineSnapshot(
            dim_means={
                "admirable": 1.1,
                "disappointing": 0.4,
                "needs_attention": 0.6,
                "scenario_realism": 2.2,
                "broken_tool_use": 1.0,
            },
            dim_stderr={},
        )
        state = PipelineState(
            run_id="r",
            target_dim="broken_tool_use",
            gen_tag="g",
            target_dims_attribution=["broken_tool_use", "admirable"],
            baseline_snapshot=snap,
        )
        state.candidates = [
            {
                "id": "gen1-000-aaaaaaaa",
                "path": "/tmp/cand.md",  # noqa: S108
                "target_dim": "broken_tool_use",
            }
        ]
        return state

    # The Pilot's anchor/attribution handoff test was removed in
    # PR-PILOT-UNIFY-DIM-EXTRACT (2026-06-04) — the Pilot no longer spawns an
    # LLM sub-agent and builds no HANDOFF CONTEXT block. The critic / evolver
    # selection-signal tests below still cover the handoff path.

    def test_critic_handoff_carries_anchor_scenario_attribution(self) -> None:
        from plugins.seed_generation.agents.critic import Critic

        state = self._state_with_baseline()
        critic = Critic(MagicMock())
        tasks = critic._build_tasks(state)  # type: ignore[attr-defined]
        handoff = _extract_handoff(tasks[0].description)
        assert handoff["anchor_means"]["admirable"] == 1.1
        assert handoff["scenario_realism"] == 2.2
        assert handoff["target_dims_attribution"] == ["broken_tool_use", "admirable"]

    def test_handoff_omits_keys_when_signals_absent(self) -> None:
        from plugins.seed_generation.agents.critic import Critic
        from plugins.seed_generation.orchestrator import PipelineState

        state = PipelineState(
            run_id="r",
            target_dim="broken_tool_use",
            gen_tag="g",
            baseline_snapshot=None,
        )
        state.candidates = [
            {
                "id": "gen1-000-aaaaaaaa",
                "path": "/tmp/cand.md",  # noqa: S108
                "target_dim": "broken_tool_use",
            }
        ]
        critic = Critic(MagicMock())
        tasks = critic._build_tasks(state)  # type: ignore[attr-defined]
        handoff = _extract_handoff(tasks[0].description)
        assert "anchor_means" not in handoff
        assert "scenario_realism" not in handoff
        assert "target_dims_attribution" not in handoff


# ─── Evolver attribution embedding (Pareto archive query removed) ─────────────


class TestEvolverAttributionEmbed:
    """PR-GROUP-REMOVAL (2026-05-29) — the Pareto archive query
    (``read_pareto_front`` / ``pareto_mode`` / ``EVOLVE_HANDOFF.pareto_front``)
    was removed with the group/swarm machinery. The evolver still
    embeds ``target_dims_attribution`` (anchor / scenario_realism
    scope) and MUST NOT embed a ``pareto_front`` key.
    """

    def _state(self, tmp_path: Path) -> object:
        from plugins.seed_generation.baseline_reader import BaselineSnapshot
        from plugins.seed_generation.orchestrator import PipelineState

        state = PipelineState(
            run_id="r",
            target_dim="broken_tool_use",
            gen_tag="g",
            target_dims_attribution=["broken_tool_use", "input_hallucination"],
            baseline_snapshot=BaselineSnapshot(dim_means={"broken_tool_use": 1.0}, dim_stderr={}),
            run_dir=tmp_path,
        )
        state.candidates = [
            {
                "id": "gen1-000-aaaaaaaa",
                "path": str(tmp_path / "parent.md"),
                "target_dim": "broken_tool_use",
            }
        ]
        state.survivors = ["gen1-000-aaaaaaaa"]
        state.reflections = {"gen1-000-aaaaaaaa": {"weaknesses": ["w1"], "rewrite_section": "Body"}}
        state.pilot_scores = {
            "gen1-000-aaaaaaaa": {
                "dim_means": {"broken_tool_use": 1.0, "input_hallucination": 0.7},
            }
        }
        return state

    def test_embeds_attribution_and_omits_pareto_front(self, tmp_path: Path) -> None:
        from plugins.seed_generation.agents.evolver import Evolver

        state = self._state(tmp_path)
        evolver = Evolver(MagicMock())
        tasks = evolver._build_tasks(state, {state.candidates[0]["id"]: state.candidates[0]})  # type: ignore[attr-defined]
        handoff = _extract_handoff(tasks[0].description)
        assert handoff["target_dims_attribution"] == [
            "broken_tool_use",
            "input_hallucination",
        ]
        assert "pareto_front" not in handoff

    def test_attribution_omitted_when_attribution_empty(self, tmp_path: Path) -> None:
        from plugins.seed_generation.agents.evolver import Evolver
        from plugins.seed_generation.baseline_reader import BaselineSnapshot
        from plugins.seed_generation.orchestrator import PipelineState

        state = PipelineState(
            run_id="r",
            target_dim="broken_tool_use",
            gen_tag="g",
            target_dims_attribution=[],  # empty → no attribution scope
            baseline_snapshot=BaselineSnapshot(dim_means={"broken_tool_use": 1.0}, dim_stderr={}),
            run_dir=tmp_path,
        )
        state.candidates = [
            {
                "id": "gen1-000-aaaaaaaa",
                "path": str(tmp_path / "parent.md"),
                "target_dim": "broken_tool_use",
            }
        ]
        state.survivors = ["gen1-000-aaaaaaaa"]
        state.reflections = {"gen1-000-aaaaaaaa": {"weaknesses": [], "rewrite_section": "Body"}}
        state.pilot_scores = {}
        evolver = Evolver(MagicMock())
        tasks = evolver._build_tasks(state, {state.candidates[0]["id"]: state.candidates[0]})  # type: ignore[attr-defined]
        handoff = _extract_handoff(tasks[0].description)
        assert "pareto_front" not in handoff
        assert "target_dims_attribution" not in handoff
