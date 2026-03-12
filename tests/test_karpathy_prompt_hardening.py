"""Tests for Karpathy prompt hardening — drift detection, skill versioning, context budget.

Covers 6 gaps from Karpathy P4/P6 audit:
  #1 L3 context budget (proportional extraction)
  #2 Skill injection versioning (SHA-256 in hook data)
  #3 Prompt drift detection (verify_prompt_integrity)
  #4 PROMPT_VERSIONS CI gate (hash pinning)
  #5 Skill discovery order (already sorted — regression test)
  #6 Memory truncation improvement (budget-aware extraction)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.llm.prompt_assembler import PromptAssembler
from core.llm.prompts import (
    PROMPT_VERSIONS,
    _hash_prompt,
    verify_prompt_integrity,
)
from core.llm.skill_registry import SkillDefinition, SkillRegistry
from core.memory.context import ContextAssembler
from core.orchestration.hooks import HookEvent, HookSystem

# ---------------------------------------------------------------------------
# Gap #3 + #4: Prompt drift detection + CI gate
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

    def test_prompt_versions_not_empty(self):
        """PROMPT_VERSIONS must contain all 8 base templates."""
        assert len(PROMPT_VERSIONS) == 8
        expected_keys = {
            "ANALYST_SYSTEM",
            "ANALYST_USER",
            "EVALUATOR_SYSTEM",
            "EVALUATOR_USER",
            "SYNTHESIZER_SYSTEM",
            "SYNTHESIZER_USER",
            "BIASBUSTER_SYSTEM",
            "BIASBUSTER_USER",
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
            "_soul": "# Mission\nDiscover undervalued IPs through data-driven analysis",
            "_org_loaded": True,
            "organization_strategy": "Data-driven IP acquisition for game publishing portfolio",
            "_project_loaded": True,
            "project_goal": "Build automated pipeline for IP evaluation and scoring",
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
        """Total hook events should be 27 (26 + PROMPT_DRIFT_DETECTED)."""
        assert len(HookEvent) == 27
