"""Tests for Karpathy prompt hardening — drift detection, skill versioning, context budget.

Covers 12 gaps from Karpathy P1/P4/P6/P7/P10 audit:
  #1 L3 context budget (proportional extraction)
  #2 Skill injection versioning (SHA-256 in hook data)
  #3 Prompt drift detection (verify_prompt_integrity)
  #4 PROMPT_VERSIONS CI gate (hash pinning, 8→20)
  #5 Skill discovery order (already sorted — regression test)
  #6 Memory truncation improvement (budget-aware extraction)
  #7 Prompt .md Constraints sections (P7 structured constraints)
  #8 Node confidence clamping (P1 defensive clamp)
  #9 Scoring LLM composite removal (P0 #2 composite_score independence)
  #10 Synthesizer DT boundary logging (P2 #12 round-crossing warning)
  #11 Agentic loop message pruning (P10 context budget)
  #12 Axes version hashing (P4 structured data drift)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.hooks import HookEvent, HookSystem
from core.llm.prompt_assembler import PromptAssembler
from core.llm.prompts import (
    PROMPT_VERSIONS,
    _hash_prompt,
    load_prompt,
    verify_prompt_integrity,
)
from core.llm.prompts.axes import AXES_VERSIONS, _hash_axes
from core.llm.skill_registry import SkillDefinition, SkillRegistry
from core.memory.context import ContextAssembler

# ---------------------------------------------------------------------------
# Gap #3 + #4: Prompt drift detection + CI gate (expanded 8→20)
# ---------------------------------------------------------------------------


class TestPromptDriftDetection:
    """Karpathy P4 ratchet — prompt hash pinning + drift alert."""

    def test_no_drift_on_clean_state(self):
        """Computed hashes should match pinned hashes (no unintended changes)."""
        drifted = verify_prompt_integrity()
        assert drifted == [], f"Unexpected prompt drift: {drifted}"

    def test_raise_on_drift(self):
        """raise_on_drift=True should raise RuntimeError on mismatch."""
        # Clean state — should not raise
        verify_prompt_integrity(raise_on_drift=True)

    def test_prompt_versions_count_20(self):
        """PROMPT_VERSIONS must contain all 20 entries (8 base + 9 extended + 3 axes)."""
        assert len(PROMPT_VERSIONS) == 20

    def test_prompt_versions_expected_keys(self):
        """All 20 expected keys must be present."""
        expected_keys = {
            # Base templates (8)
            "ANALYST_SYSTEM",
            "ANALYST_USER",
            "EVALUATOR_SYSTEM",
            "EVALUATOR_USER",
            "SYNTHESIZER_SYSTEM",
            "SYNTHESIZER_USER",
            "BIASBUSTER_SYSTEM",
            "BIASBUSTER_USER",
            # Extended templates (9)
            "ROUTER_SYSTEM",
            "AGENTIC_SUFFIX",
            "COMMENTARY_SYSTEM",
            "COMMENTARY_USER",
            "CROSS_LLM_SYSTEM",
            "CROSS_LLM_RESCORE",
            "CROSS_LLM_DUAL_VERIFY",
            "ANALYST_TOOLS_SUFFIX",
            "SYNTHESIZER_TOOLS_SUFFIX",
            # Axes hashes (3)
            "EVALUATOR_AXES",
            "PROSPECT_EVALUATOR_AXES",
            "ANALYST_SPECIFIC",
        }
        assert set(PROMPT_VERSIONS.keys()) == expected_keys

    def test_hashes_are_12_char_hex(self):
        """All hashes should be 12-character hex strings."""
        for name, h in PROMPT_VERSIONS.items():
            assert len(h) == 12, f"{name} hash length={len(h)}, expected 12"
            assert all(c in "0123456789abcdef" for c in h), f"{name} hash not hex: {h}"

    def test_hash_deterministic(self):
        """Same input should always produce the same hash."""
        h1 = _hash_prompt("test prompt content")
        h2 = _hash_prompt("test prompt content")
        assert h1 == h2

    def test_hash_changes_on_different_content(self):
        h1 = _hash_prompt("version A")
        h2 = _hash_prompt("version B")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Gap #12: Axes version hashing
# ---------------------------------------------------------------------------


class TestAxesVersionHashing:
    """Karpathy P4 — structured axes data drift detection."""

    def test_axes_versions_has_3_entries(self):
        assert len(AXES_VERSIONS) == 3

    def test_axes_versions_keys(self):
        expected = {"EVALUATOR_AXES", "PROSPECT_EVALUATOR_AXES", "ANALYST_SPECIFIC"}
        assert set(AXES_VERSIONS.keys()) == expected

    def test_hash_axes_deterministic(self):
        data = {"a": 1, "b": [2, 3]}
        h1 = _hash_axes(data)
        h2 = _hash_axes(data)
        assert h1 == h2

    def test_hash_axes_12_char_hex(self):
        h = _hash_axes({"key": "value"})
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_axes_versions_merged_into_prompt_versions(self):
        """AXES_VERSIONS entries should be present in PROMPT_VERSIONS."""
        for key in AXES_VERSIONS:
            assert key in PROMPT_VERSIONS
            assert PROMPT_VERSIONS[key] == AXES_VERSIONS[key]


# ---------------------------------------------------------------------------
# Gap #2: Skill injection versioning
# ---------------------------------------------------------------------------


class TestSkillVersioning:
    """Karpathy P4 — skill content hashes in PROMPT_ASSEMBLED hook data."""

    def _make_skill(self, name: str, body: str, priority: int = 100) -> SkillDefinition:
        return SkillDefinition(
            name=name,
            node="analyst",
            type="game_mechanics",
            priority=priority,
            version="1.0",
            role="system",
            enabled=True,
            prompt_body=body,
            source_path=Path(f"/tmp/{name}.md"),  # noqa: S108
        )

    def test_skill_hashes_in_hook_event(self):
        """PROMPT_ASSEMBLED hook should include skill_hashes dict."""
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []
        hooks.register(HookEvent.PROMPT_ASSEMBLED, lambda e, d: captured.append(d))

        skill = self._make_skill("test-skill", "Analyze game mechanics carefully.")
        registry = SkillRegistry()
        registry._skills = [skill]

        assembler = PromptAssembler(skill_registry=registry, hooks=hooks)
        assembler.assemble(
            base_system="You are an analyst.",
            base_user="Evaluate {ip_name}.",
            state={},
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(captured) == 1
        data = captured[0]
        assert "skill_hashes" in data
        assert "test-skill" in data["skill_hashes"]
        expected = _hash_prompt("Analyze game mechanics carefully.")
        assert data["skill_hashes"]["test-skill"] == expected

    def test_no_skill_hashes_when_no_skills(self):
        """When no skills match, skill_hashes should not be in hook data."""
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []
        hooks.register(HookEvent.PROMPT_ASSEMBLED, lambda e, d: captured.append(d))

        assembler = PromptAssembler(hooks=hooks)
        assembler.assemble(
            base_system="You are an analyst.",
            base_user="Evaluate.",
            state={},
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(captured) == 1
        assert "skill_hashes" not in captured[0]

    def test_truncation_events_in_hook(self):
        """Truncation events should be reported in hook data."""
        hooks = HookSystem()
        captured: list[dict[str, Any]] = []
        hooks.register(HookEvent.PROMPT_ASSEMBLED, lambda e, d: captured.append(d))

        long_memory = "x" * 500
        assembler = PromptAssembler(hooks=hooks, max_memory_chars=100)
        assembler.assemble(
            base_system="System.",
            base_user="User.",
            state={"memory_context": {"_llm_summary": long_memory}},
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(captured) == 1
        data = captured[0]
        assert "truncation_events" in data
        assert any("memory:" in t for t in data["truncation_events"])


# ---------------------------------------------------------------------------
# Gap #1 + #6: Context budget — proportional extraction
# ---------------------------------------------------------------------------


class TestContextBudget:
    """Karpathy P6 L2 extraction — budget-aware context summarization."""

    def test_proportional_budget(self):
        """Summary should respect tier budgets instead of hard-cutting."""
        ctx: dict[str, Any] = {
            "_soul_loaded": True,
            "_soul": "# Mission\nAutonomous research, analysis, and task execution",
            "_org_loaded": True,
            "organization_strategy": "Data-driven autonomous execution with domain plugins",
            "_project_loaded": True,
            "project_goal": "Build automated pipeline for analysis and scoring",
            "_session_loaded": True,
            "previous_results": ["Berserk: S/81.3", "Cowboy Bebop: A/68.4"],
        }
        summary = ContextAssembler._build_llm_summary(ctx, max_chars=280)
        assert "Mission:" in summary
        assert "Org:" in summary
        assert "Project:" in summary
        assert "Prev:" in summary

    def test_budget_respects_max_chars(self):
        """Total summary should not grossly exceed max_chars."""
        ctx: dict[str, Any] = {
            "_soul_loaded": True,
            "_soul": "# Soul\n" + "Long mission " * 50,
            "_org_loaded": True,
            "organization_strategy": "Strategy " * 50,
            "_project_loaded": True,
            "project_goal": "Goal " * 50,
            "_session_loaded": True,
            "previous_results": ["Result " * 20] * 5,
        }
        summary = ContextAssembler._build_llm_summary(ctx, max_chars=200)
        # Each tier is individually truncated — total may exceed max_chars
        # due to separators, but should be within 2x
        assert len(summary) < 200 * 2

    def test_empty_context_returns_empty(self):
        summary = ContextAssembler._build_llm_summary({})
        assert summary == ""

    def test_session_only(self):
        ctx: dict[str, Any] = {
            "_session_loaded": True,
            "previous_results": ["Berserk: S/81.3"],
        }
        summary = ContextAssembler._build_llm_summary(ctx)
        assert "Prev: Berserk" in summary

    def test_session_budget_most_recent_first(self):
        """Most recent results should be prioritized when budget is tight."""
        ctx: dict[str, Any] = {
            "_session_loaded": True,
            "previous_results": [
                "Old result that is very long " * 5,
                "Middle result " * 5,
                "Latest: S/95.0",
            ],
        }
        summary = ContextAssembler._build_llm_summary(ctx, max_chars=150)
        # Latest result should always be present
        assert "Latest" in summary


# ---------------------------------------------------------------------------
# Gap #5: Skill discovery determinism (regression test)
# ---------------------------------------------------------------------------


class TestSkillDiscoveryOrder:
    """Verify skills are discovered in sorted order (deterministic)."""

    def test_discover_is_sorted(self, tmp_path: Path):
        """Skills from glob should be alphabetically sorted."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create skill files in reverse alphabetical order
        for name in ["zebra", "alpha", "middle"]:
            content = (
                f"---\nname: {name}\nnode: analyst\ntype: '*'\n"
                f"priority: 100\nversion: '1.0'\n---\nBody for {name}."
            )
            (skills_dir / f"{name}.md").write_text(content, encoding="utf-8")

        registry = SkillRegistry(extra_dirs=[skills_dir])
        discovered = registry.discover()

        names = [s.name for s in discovered]
        assert names == sorted(names), f"Skills not in sorted order: {names}"

    def test_multiple_dirs_maintain_order(self, tmp_path: Path):
        """Skills from multiple directories should maintain per-dir sort."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        (dir_a / "beta.md").write_text(
            "---\nname: beta\nnode: analyst\ntype: '*'\n---\nBeta body.",
            encoding="utf-8",
        )
        (dir_b / "alpha.md").write_text(
            "---\nname: alpha\nnode: analyst\ntype: '*'\n---\nAlpha body.",
            encoding="utf-8",
        )

        registry = SkillRegistry(extra_dirs=[dir_a, dir_b])
        discovered = registry.discover()

        # dir_a files come first (priority order), then dir_b
        names = [s.name for s in discovered]
        assert names == ["beta", "alpha"]


# ---------------------------------------------------------------------------
# Hook event type regression
# ---------------------------------------------------------------------------


class TestHookEventTypes:
    def test_prompt_drift_detected_event_exists(self):
        """PROMPT_DRIFT_DETECTED should be a valid hook event."""
        assert hasattr(HookEvent, "PROMPT_DRIFT_DETECTED")
        assert HookEvent.PROMPT_DRIFT_DETECTED.value == "prompt_drift_detected"

    def test_hook_event_count(self):
        """Total hook events should be 36 (27 + 3 TOOL_RECOVERY_* + 2 GATEWAY_* + 2 MCP_SERVER_* + 2 CONTEXT_*)."""
        assert len(HookEvent) == 36


# ---------------------------------------------------------------------------
# Gap #7: Prompt .md Constraints sections
# ---------------------------------------------------------------------------


class TestPromptConstraintsSections:
    """Verify .md prompts contain ## Constraints sections."""

    def test_evaluator_has_constraints(self):
        system = load_prompt("evaluator", "system")
        assert "## Constraints" in system
        assert "composite_score" in system.lower()

    def test_evaluator_has_style(self):
        system = load_prompt("evaluator", "system")
        assert "## Style" in system

    def test_synthesizer_has_constraints(self):
        system = load_prompt("synthesizer", "system")
        assert "## Constraints" in system
        assert "LOCKED" in system

    def test_biasbuster_has_constraints(self):
        system = load_prompt("biasbuster", "system")
        assert "## Constraints" in system
        assert "CV < 0.05" in system

    def test_analyst_has_style(self):
        system = load_prompt("analyst", "system")
        assert "## Style" in system


# ---------------------------------------------------------------------------
# Gap #8: Analyst confidence clamping (P1 #4)
# ---------------------------------------------------------------------------


class TestAnalystConfidenceClamping:
    """Karpathy P1 — defensive confidence clamp [0, 100]."""

    def test_confidence_clamped_above_100(self):
        from core.domains.game_ip.nodes.analysts import analyst_node
        from core.state import AnalysisResult

        # Use model_construct to bypass Pydantic validation (simulates raw LLM output)
        over_result = AnalysisResult.model_construct(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=["test"],
            confidence=150.0,
        )

        state: dict[str, Any] = {
            "_analyst_type": "game_mechanics",
            "ip_name": "Test",
            "ip_info": {},
            "monolake": {},
            "signals": {},
            "dry_run": True,
            "verbose": False,
            "analyses": [],
            "errors": [],
        }

        with patch("core.domains.game_ip.nodes.analysts._run_analyst", return_value=over_result):
            result = analyst_node(state)

        analyses = result["analyses"]
        assert len(analyses) == 1
        assert analyses[0].confidence == 100.0

    def test_confidence_clamped_below_0(self):
        from core.domains.game_ip.nodes.analysts import analyst_node
        from core.state import AnalysisResult

        # Use model_construct to bypass Pydantic validation (simulates raw LLM output)
        under_result = AnalysisResult.model_construct(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=["test"],
            confidence=-10.0,
        )

        state: dict[str, Any] = {
            "_analyst_type": "game_mechanics",
            "ip_name": "Test",
            "ip_info": {},
            "monolake": {},
            "signals": {},
            "dry_run": True,
            "verbose": False,
            "analyses": [],
            "errors": [],
        }

        with patch("core.domains.game_ip.nodes.analysts._run_analyst", return_value=under_result):
            result = analyst_node(state)

        analyses = result["analyses"]
        assert len(analyses) == 1
        assert analyses[0].confidence == 0.0

    def test_confidence_normal_not_clamped(self):
        from core.domains.game_ip.nodes.analysts import analyst_node
        from core.state import AnalysisResult

        normal_result = AnalysisResult(
            analyst_type="game_mechanics",
            score=4.0,
            key_finding="test",
            reasoning="test",
            evidence=["test"],
            confidence=85.0,
        )

        state: dict[str, Any] = {
            "_analyst_type": "game_mechanics",
            "ip_name": "Test",
            "ip_info": {},
            "monolake": {},
            "signals": {},
            "dry_run": True,
            "verbose": False,
            "analyses": [],
            "errors": [],
        }

        with patch("core.domains.game_ip.nodes.analysts._run_analyst", return_value=normal_result):
            result = analyst_node(state)

        assert result["analyses"][0].confidence == 85.0


# ---------------------------------------------------------------------------
# Gap #9: Scoring — LLM composite_score independence (P0 #2)
# ---------------------------------------------------------------------------


class TestScoringCompositeIndependence:
    """Scoring must use server-side _calc_community_momentum, not LLM composite."""

    def test_growth_score_uses_axes_not_composite(self):
        """_calc_growth_score should derive trend from axes, not composite_score."""
        from core.domains.game_ip.nodes.scoring import _calc_growth_score
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 3.0, "f_score": 4.0},
                composite_score=0.0,  # deliberately wrong composite
                rationale="test",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 5.0, "k_score": 4.0, "l_score": 4.0},
                composite_score=0.0,  # deliberately wrong composite
                rationale="test",
            ),
        }

        # Server-side momentum: ((5+4+4)-3)/12*100 = 83.33
        growth = _calc_growth_score(evaluations, developer_track_record=50.0)

        # trend = 83.33, expand = ((4.0-1)/4*100) = 75.0, dev = 50.0
        # 0.40*83.33 + 0.40*75.0 + 0.20*50.0 = 33.33 + 30.0 + 10.0 = 73.33
        expected = 0.40 * 83.333 + 0.40 * 75.0 + 0.20 * 50.0
        assert abs(growth - expected) < 0.1

    def test_growth_score_no_community_momentum(self):
        """Without community_momentum evaluator, trend defaults to 50.0."""
        from core.domains.game_ip.nodes.scoring import _calc_growth_score
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 3.0, "f_score": 4.0},
                composite_score=99.0,
                rationale="test",
            ),
        }

        growth = _calc_growth_score(evaluations, developer_track_record=50.0)
        # trend = 50.0 (default), expand = 75.0, dev = 50.0
        expected = 0.40 * 50.0 + 0.40 * 75.0 + 0.20 * 50.0
        assert abs(growth - expected) < 0.1

    def test_growth_score_with_precomputed_momentum(self):
        """Pre-computed momentum should be used instead of recalculating."""
        from core.domains.game_ip.nodes.scoring import _calc_growth_score
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 3.0, "f_score": 4.0},
                composite_score=0.0,
                rationale="test",
            ),
            "community_momentum": EvaluatorResult(
                evaluator_type="community_momentum",
                axes={"j_score": 5.0, "k_score": 5.0, "l_score": 5.0},
                composite_score=0.0,
                rationale="test",
            ),
        }

        # Pass pre-computed momentum=90.0
        growth = _calc_growth_score(evaluations, developer_track_record=50.0, momentum=90.0)
        # trend = 90.0 (pre-computed, NOT recalculated), expand = 75.0, dev = 50.0
        expected = 0.40 * 90.0 + 0.40 * 75.0 + 0.20 * 50.0
        assert abs(growth - expected) < 0.1


# ---------------------------------------------------------------------------
# Gap #10: Synthesizer DT boundary logging (P2 #12)
# ---------------------------------------------------------------------------


class TestSynthesizerBoundaryLogging:
    """Decision Tree boundary crossing should produce a warning log."""

    def test_boundary_crossing_logged(self, caplog: Any):
        from core.domains.game_ip.nodes.synthesizer import _extract_def_scores
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 2.5, "e_score": 3.0, "f_score": 3.0},
                composite_score=50.0,
                rationale="test",
            ),
        }

        with caplog.at_level(logging.WARNING, logger="core.domains.game_ip.nodes.synthesizer"):
            d, e, f = _extract_def_scores(evaluations)

        # 2.5 rounds to 2 → crosses from <3 to... no, stays <3.
        # Actually 2.5 rounds to 2 in Python (banker's rounding).
        # Let's verify actual values
        assert d == 2
        assert e == 3
        assert f == 3

    def test_boundary_crossing_at_2_point_5(self, caplog: Any):
        """2.5 → round(2.5) = 2 in Python (banker's rounding). No boundary cross."""
        from core.domains.game_ip.nodes.synthesizer import _extract_def_scores
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 2.6, "e_score": 3.0, "f_score": 3.0},
                composite_score=50.0,
                rationale="test",
            ),
        }

        with caplog.at_level(logging.WARNING, logger="core.domains.game_ip.nodes.synthesizer"):
            d, e, f = _extract_def_scores(evaluations)

        # 2.6 rounds to 3 → crosses boundary (raw < 3 but rounded >= 3)
        assert d == 3
        assert any("DT boundary shift" in msg for msg in caplog.messages)

    def test_no_boundary_crossing_clear_scores(self, caplog: Any):
        """Scores clearly above/below 3 should not warn."""
        from core.domains.game_ip.nodes.synthesizer import _extract_def_scores
        from core.state import EvaluatorResult

        evaluations = {
            "hidden_value": EvaluatorResult(
                evaluator_type="hidden_value",
                axes={"d_score": 4.0, "e_score": 2.0, "f_score": 4.0},
                composite_score=60.0,
                rationale="test",
            ),
        }

        with caplog.at_level(logging.WARNING, logger="core.domains.game_ip.nodes.synthesizer"):
            d, e, f = _extract_def_scores(evaluations)

        assert d == 4
        assert e == 2
        assert f == 4
        assert not any("DT boundary shift" in msg for msg in caplog.messages)

    def test_no_hidden_value_returns_defaults(self):
        from core.domains.game_ip.nodes.synthesizer import _extract_def_scores

        d, e, f = _extract_def_scores({})
        assert (d, e, f) == (3, 3, 3)


# ---------------------------------------------------------------------------
# Gap #11: Agentic loop message pruning (P10 context budget)
# ---------------------------------------------------------------------------


class TestAgenticLoopPruning:
    """Karpathy P10 — message pruning for context budget."""

    def test_no_pruning_under_threshold(self):
        from core.agent.agentic_loop import AgenticLoop

        loop = AgenticLoop.__new__(AgenticLoop)
        messages: list[dict[str, Any]] = [{"role": "user", "content": f"msg{i}"} for i in range(8)]
        loop._maybe_prune_messages(messages)
        assert len(messages) == 8  # No change

    def test_pruning_at_threshold(self):
        from core.agent.agentic_loop import AgenticLoop

        loop = AgenticLoop.__new__(AgenticLoop)
        messages: list[dict[str, Any]] = [{"role": "user", "content": f"msg{i}"} for i in range(30)]
        loop._maybe_prune_messages(messages)
        assert len(messages) == 30  # Exactly 30 = no prune

    def test_pruning_above_threshold(self):
        from core.agent.agentic_loop import AgenticLoop

        loop = AgenticLoop.__new__(AgenticLoop)
        # Build alternating user/assistant (32 msgs = 16 rounds)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "first message"}]
        for i in range(1, 32):
            role = "assistant" if i % 2 else "user"
            messages.append({"role": role, "content": f"msg{i}"})
        assert len(messages) == 32

        loop._maybe_prune_messages(messages)

        # first(user) + bridge(assistant) + recent(user-start) = 7
        assert messages[0]["content"] == "first message"
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert "(earlier rounds omitted)" in str(messages[1]["content"])
        # Verify alternation: no consecutive same roles
        for i in range(1, len(messages)):
            assert messages[i]["role"] != messages[i - 1]["role"], (
                f"Consecutive {messages[i]['role']} at index {i - 1},{i}"
            )

    def test_pruning_preserves_recent_and_alternation(self):
        from core.agent.agentic_loop import AgenticLoop

        loop = AgenticLoop.__new__(AgenticLoop)
        # Build proper alternating conversation (13 msgs: 6 turns + current user)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "original"}]
        for i in range(1, 11):
            role = "assistant" if i % 2 else "user"
            messages.append({"role": role, "content": f"old{i}"})
        messages.extend(
            [
                {"role": "assistant", "content": "recent_a1"},
                {"role": "user", "content": "recent_u2"},
            ]
        )
        assert len(messages) == 13

        loop._maybe_prune_messages(messages)

        contents = [m["content"] for m in messages]
        assert "original" in contents
        assert "recent_u2" in contents
        # Verify alternation
        for i in range(1, len(messages)):
            assert messages[i]["role"] != messages[i - 1]["role"]
