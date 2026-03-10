"""Tests for PromptAssembler (ADR-007 Phase 0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from core.llm.prompt_assembler import AssembledPrompt, PromptAssembler
from core.llm.prompts import _hash_prompt
from core.llm.skill_registry import SkillDefinition, SkillRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def base_system() -> str:
    return "You are a test analyst."


@pytest.fixture()
def base_user() -> str:
    return "Analyze this IP: TestIP"


@pytest.fixture()
def empty_state() -> dict[str, Any]:
    return {}


@pytest.fixture()
def mock_skill() -> SkillDefinition:
    return SkillDefinition(
        name="test-skill",
        node="analyst",
        type="game_mechanics",
        priority=50,
        version="1.0",
        role="system",
        enabled=True,
        prompt_body="Focus on core gameplay loop.",
        source_path=Path("/fake/test-skill.md"),
    )


@pytest.fixture()
def mock_registry(mock_skill: SkillDefinition) -> SkillRegistry:
    """SkillRegistry pre-loaded with a single skill."""
    registry = SkillRegistry()
    registry._skills = [mock_skill]
    return registry


class _HookCollector:
    """Minimal hook system that collects trigger calls for testing."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def trigger(self, event: Any, data: dict[str, Any]) -> None:
        self.calls.append((event, data))

    def register(self, event: Any, handler: Any, *, name: str = "", priority: int = 50) -> None:
        pass  # not needed for tests

    def unregister(self, event: Any, name: str) -> bool:
        return False


@pytest.fixture()
def hook_collector() -> _HookCollector:
    return _HookCollector()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBasicAssembly:
    def test_basic_assembly_no_fragments(
        self, base_system: str, base_user: str, empty_state: dict[str, Any]
    ) -> None:
        """Base-only assembly produces fragment_count=0 and correct hashes."""
        assembler = PromptAssembler()
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=empty_state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert isinstance(result, AssembledPrompt)
        assert result.system == base_system
        assert result.user == base_user
        assert result.fragment_count == 0
        assert result.fragments_used == []
        assert result.total_chars == len(base_system) + len(base_user)

    def test_no_assembler_fallback(self, empty_state: dict[str, Any]) -> None:
        """Verify state.get('_prompt_assembler') is None returns None (node-level fallback)."""
        # This tests the pattern used in nodes: assembler = state.get("_prompt_assembler")
        assert empty_state.get("_prompt_assembler") is None


class TestSkillInjection:
    def test_skill_fragment_injection(
        self,
        base_system: str,
        base_user: str,
        empty_state: dict[str, Any],
        mock_registry: SkillRegistry,
    ) -> None:
        """Skills from registry are injected into system prompt."""
        assembler = PromptAssembler(skill_registry=mock_registry)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=empty_state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert result.fragment_count == 1
        assert "test-skill:1.0" in result.fragments_used
        assert "## Skill: test-skill" in result.system
        assert "Focus on core gameplay loop." in result.system

    def test_token_budget_skill_truncation(
        self, base_system: str, base_user: str, empty_state: dict[str, Any]
    ) -> None:
        """Skill body exceeding max_skill_chars is truncated."""
        long_body = "A" * 600
        skill = SkillDefinition(
            name="long-skill",
            node="analyst",
            type="game_mechanics",
            priority=50,
            version="1.0",
            role="system",
            enabled=True,
            prompt_body=long_body,
            source_path=Path("/fake/long-skill.md"),
        )
        registry = SkillRegistry()
        registry._skills = [skill]

        assembler = PromptAssembler(skill_registry=registry, max_skill_chars=500)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=empty_state,
            node="analyst",
            role_type="game_mechanics",
        )

        # The skill body should be truncated to 500 chars + "..."
        assert "A" * 500 + "..." in result.system
        assert "A" * 501 not in result.system


class TestMemoryInjection:
    def test_memory_context_injection_llm_summary(self, base_system: str, base_user: str) -> None:
        """Memory context with _llm_summary is injected into system prompt."""
        state: dict[str, Any] = {
            "memory_context": {"_llm_summary": "Berserk was S tier in previous analysis."}
        }
        assembler = PromptAssembler()
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert "## Context from Memory" in result.system
        assert "Berserk was S tier" in result.system
        assert "memory-context" in result.fragments_used

    def test_memory_context_fallback(self, base_system: str, base_user: str) -> None:
        """Memory context without _llm_summary uses fallback keys."""
        state: dict[str, Any] = {
            "memory_context": {
                "_org_loaded": True,
                "organization_strategy": "Focus on anime IPs",
                "_project_loaded": True,
                "project_goal": "Find undervalued fighting IPs",
            }
        }
        assembler = PromptAssembler()
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert "Organization strategy: Focus on anime IPs" in result.system
        assert "Project goal: Find undervalued fighting IPs" in result.system
        assert "memory-context" in result.fragments_used

    def test_token_budget_memory_truncation(self, base_system: str, base_user: str) -> None:
        """Memory context exceeding max_memory_chars is truncated."""
        long_summary = "X" * 400
        state: dict[str, Any] = {"memory_context": {"_llm_summary": long_summary}}
        assembler = PromptAssembler(max_memory_chars=300)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        # The memory block is "## Context from Memory\n" + summary
        # Total block > 300 chars, so it gets truncated to 300 chars + "..."
        memory_block = "## Context from Memory\n" + long_summary
        expected_truncated = memory_block[:300] + "..."
        assert expected_truncated in result.system


class TestBootstrapInjection:
    def test_bootstrap_extra_instructions(self, base_system: str, base_user: str) -> None:
        """Extra instructions from bootstrap are injected."""
        state: dict[str, Any] = {
            "_extra_instructions": [
                "Weight combat depth heavily for fighting IPs",
                "Consider mobile market opportunity",
            ]
        }
        assembler = PromptAssembler()
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert "## Additional Instructions" in result.system
        assert "- Weight combat depth heavily for fighting IPs" in result.system
        assert "- Consider mobile market opportunity" in result.system
        assert "bootstrap-extra:2" in result.fragments_used

    def test_token_budget_extra_instructions_limit(self, base_system: str, base_user: str) -> None:
        """Only max_extra_instructions are included; each capped at max chars."""
        instructions = [f"Instruction {i}" for i in range(10)]
        state: dict[str, Any] = {"_extra_instructions": instructions}
        assembler = PromptAssembler(max_extra_instructions=5, max_extra_instruction_chars=100)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        # Only first 5 instructions
        assert "bootstrap-extra:5" in result.fragments_used
        assert "Instruction 4" in result.system
        assert "Instruction 5" not in result.system


class TestPromptOverride:
    def test_prompt_override_append_only(self, base_system: str, base_user: str) -> None:
        """With allow_full_override=False, override is appended."""
        state: dict[str, Any] = {"_prompt_overrides": {"analyst_system": "EXTRA CONTEXT HERE"}}
        assembler = PromptAssembler(allow_full_override=False)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert result.system.startswith(base_system)
        assert "EXTRA CONTEXT HERE" in result.system
        assert "override-append:analyst_system" in result.fragments_used

    def test_prompt_override_full_replace(self, base_system: str, base_user: str) -> None:
        """With allow_full_override=True, override replaces base system."""
        override_text = "COMPLETELY NEW SYSTEM PROMPT"
        state: dict[str, Any] = {"_prompt_overrides": {"analyst_system": override_text}}
        assembler = PromptAssembler(allow_full_override=True)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert result.system.startswith(override_text)
        assert base_system not in result.system
        assert "override:analyst_system" in result.fragments_used


class TestTokenBudget:
    def test_system_prompt_hard_limit(self, base_user: str) -> None:
        """System prompt exceeding hard limit is trimmed."""
        big_system = "S" * 7000
        assembler = PromptAssembler(prompt_hard_limit_chars=6000)
        result = assembler.assemble(
            base_system=big_system,
            base_user=base_user,
            state={},
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(result.system) == 6000


class TestHashing:
    def test_hash_computation(
        self, base_system: str, base_user: str, empty_state: dict[str, Any]
    ) -> None:
        """Assembled hash and base template hash are computed correctly."""
        assembler = PromptAssembler()
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=empty_state,
            node="analyst",
            role_type="game_mechanics",
        )

        expected_base_hash = _hash_prompt(base_system + base_user)
        expected_assembled_hash = _hash_prompt(result.system + result.user)

        assert result.base_template_hash == expected_base_hash
        assert result.assembled_hash == expected_assembled_hash
        # With no fragments, they should be identical
        assert result.assembled_hash == result.base_template_hash


class TestHookEmission:
    def test_hook_event_emitted(
        self,
        base_system: str,
        base_user: str,
        empty_state: dict[str, Any],
        hook_collector: _HookCollector,
    ) -> None:
        """PROMPT_ASSEMBLED hook event is triggered with correct metadata."""
        assembler = PromptAssembler(hooks=hook_collector)  # type: ignore[arg-type]
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=empty_state,
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(hook_collector.calls) == 1
        event, data = hook_collector.calls[0]
        assert data["node"] == "analyst"
        assert data["role_type"] == "game_mechanics"
        assert data["assembled_hash"] == result.assembled_hash
        assert data["base_template_hash"] == result.base_template_hash
        assert data["fragment_count"] == 0
        assert data["total_chars"] == result.total_chars


class TestCombinedAssembly:
    def test_combined_assembly_order(self, base_system: str, base_user: str) -> None:
        """Skills + memory + bootstrap all applied in correct order."""
        skill = SkillDefinition(
            name="combo-skill",
            node="analyst",
            type="game_mechanics",
            priority=50,
            version="2.0",
            role="system",
            enabled=True,
            prompt_body="Skill body here.",
            source_path=Path("/fake/combo.md"),
        )
        registry = SkillRegistry()
        registry._skills = [skill]

        state: dict[str, Any] = {
            "memory_context": {"_llm_summary": "Memory summary."},
            "_extra_instructions": ["Bootstrap instruction 1"],
        }

        assembler = PromptAssembler(skill_registry=registry)
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )

        # Verify order: base -> skill -> memory -> bootstrap
        system = result.system
        skill_pos = system.index("## Skill: combo-skill")
        memory_pos = system.index("## Context from Memory")
        bootstrap_pos = system.index("## Additional Instructions")

        assert skill_pos < memory_pos < bootstrap_pos

        # Verify fragments used
        assert result.fragment_count == 3
        assert "combo-skill:2.0" in result.fragments_used
        assert "memory-context" in result.fragments_used
        assert "bootstrap-extra:1" in result.fragments_used
