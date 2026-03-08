"""Integration tests for ADR-007 bootstrap wire.

Tests the full chain: BootstrapManager -> state -> PromptAssembler -> final prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from geode.llm.prompt_assembler import PromptAssembler
from geode.llm.skill_registry import SkillRegistry
from geode.orchestration.hooks import HookEvent, HookSystem

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hooks() -> HookSystem:
    return HookSystem()


@pytest.fixture()
def assembler(hooks: HookSystem) -> PromptAssembler:
    return PromptAssembler(
        skill_registry=SkillRegistry(),
        hooks=hooks,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests: extra_instructions reach the final assembled prompt
# ---------------------------------------------------------------------------


class TestExtraInstructionsWire:
    def test_extra_instructions_appended_to_system(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {
            "_extra_instructions": ["Focus on RPG mechanics", "Weight combat depth highly"],
        }
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="Analyze this IP.",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert "Focus on RPG mechanics" in result.system
        assert "Weight combat depth highly" in result.system
        assert "## Additional Instructions" in result.system
        assert "bootstrap-extra:2" in result.fragments_used

    def test_no_extra_instructions_no_fragment(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {}
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="Analyze this IP.",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert "## Additional Instructions" not in result.system
        assert result.fragment_count == 0

    def test_extra_instructions_truncated_at_limit(self) -> None:
        assembler = PromptAssembler(
            max_extra_instructions=2,
            max_extra_instruction_chars=10,
        )
        state: dict[str, Any] = {
            "_extra_instructions": ["AAAA", "BBBB", "CCCC should be dropped"],
        }
        result = assembler.assemble(
            base_system="base",
            base_user="user",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert "AAAA" in result.system
        assert "BBBB" in result.system
        assert "CCCC" not in result.system
        assert "bootstrap-extra:2" in result.fragments_used


# ---------------------------------------------------------------------------
# Tests: memory_context._llm_summary reaches the final assembled prompt
# ---------------------------------------------------------------------------


class TestMemoryContextWire:
    def test_llm_summary_injected(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {
            "memory_context": {
                "_llm_summary": "Organization: Focus on action RPGs | Project: Q1 evaluation",
            },
        }
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="Analyze this IP.",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert "Focus on action RPGs" in result.system
        assert "Q1 evaluation" in result.system
        assert "## Context from Memory" in result.system
        assert "memory-context" in result.fragments_used

    def test_no_memory_context_no_fragment(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {}
        result = assembler.assemble(
            base_system="base",
            base_user="user",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert "## Context from Memory" not in result.system
        assert "memory-context" not in result.fragments_used

    def test_fallback_when_no_llm_summary(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {
            "memory_context": {
                "_org_loaded": True,
                "organization_strategy": "Expand into action genre",
                "_project_loaded": True,
                "project_goal": "Evaluate top 10 IPs",
            },
        }
        result = assembler.assemble(
            base_system="base",
            base_user="user",
            state=state,
            node="evaluator",
            role_type="quality_judge",
        )
        assert "Expand into action genre" in result.system
        assert "Evaluate top 10 IPs" in result.system
        assert "memory-context" in result.fragments_used


# ---------------------------------------------------------------------------
# Tests: _prompt_overrides append-only mode
# ---------------------------------------------------------------------------


class TestPromptOverridesWire:
    def test_override_appended_in_default_mode(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {
            "_prompt_overrides": {
                "analyst_system": "Extra override content appended.",
            },
        }
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="user prompt",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        # In append mode, the base is preserved and override is appended
        assert result.system.startswith("You are an analyst.")
        assert "Extra override content appended." in result.system
        assert "override-append:analyst_system" in result.fragments_used

    def test_full_override_when_allowed(self) -> None:
        assembler = PromptAssembler(allow_full_override=True)
        state: dict[str, Any] = {
            "_prompt_overrides": {
                "analyst_system": "Completely replaced system prompt.",
            },
        }
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="user prompt",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert result.system.startswith("Completely replaced system prompt.")
        assert "override:analyst_system" in result.fragments_used

    def test_non_matching_override_key_ignored(self, assembler: PromptAssembler) -> None:
        state: dict[str, Any] = {
            "_prompt_overrides": {
                "evaluator_system": "This should be ignored for analyst node.",
            },
        }
        result = assembler.assemble(
            base_system="You are an analyst.",
            base_user="user prompt",
            state=state,
            node="analyst",
            role_type="game_mechanics",
        )
        assert result.system == "You are an analyst."
        assert result.fragment_count == 0


# ---------------------------------------------------------------------------
# Tests: make_analyst_sends propagates ADR-007 keys
# ---------------------------------------------------------------------------


class TestAnalystSendsPropagation:
    def test_sends_contain_adr007_keys(self) -> None:
        from geode.nodes.analysts import make_analyst_sends

        state: dict[str, Any] = {
            "ip_name": "Berserk",
            "ip_info": {"ip_name": "Berserk"},
            "monolake": {},
            "signals": {},
            "_prompt_overrides": {"analyst_system": "override"},
            "_extra_instructions": ["Focus on dark fantasy"],
            "memory_context": {"_llm_summary": "org context"},
        }
        sends = make_analyst_sends(state)
        assert len(sends) == 4
        for send in sends:
            send_state = send.arg
            assert send_state["_prompt_overrides"] == {"analyst_system": "override"}
            assert send_state["_extra_instructions"] == ["Focus on dark fantasy"]
            assert send_state["memory_context"] == {"_llm_summary": "org context"}


# ---------------------------------------------------------------------------
# Tests: make_evaluator_sends propagates ADR-007 keys
# ---------------------------------------------------------------------------


class TestEvaluatorSendsPropagation:
    def test_sends_contain_adr007_keys(self) -> None:
        from geode.nodes.evaluators import make_evaluator_sends

        state: dict[str, Any] = {
            "ip_name": "Berserk",
            "ip_info": {"ip_name": "Berserk"},
            "monolake": {},
            "signals": {},
            "analyses": [],
            "_prompt_overrides": {"evaluator_system": "eval override"},
            "_extra_instructions": ["Check bias carefully"],
            "memory_context": {"_llm_summary": "session context"},
        }
        sends = make_evaluator_sends(state)
        assert len(sends) == 3
        for send in sends:
            send_state = send.arg
            assert send_state["_prompt_overrides"] == {"evaluator_system": "eval override"}
            assert send_state["_extra_instructions"] == ["Check bias carefully"]
            assert send_state["memory_context"] == {"_llm_summary": "session context"}


# ---------------------------------------------------------------------------
# Tests: _make_hooked_node injects _prompt_assembler into state
# ---------------------------------------------------------------------------


class TestHookedNodeAssemblerInjection:
    def test_assembler_injected_into_state(self, hooks: HookSystem) -> None:
        from geode.graph import _make_hooked_node

        assembler = PromptAssembler()
        captured_state: list[dict[str, Any]] = []

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            captured_state.append(dict(state))
            return {}

        wrapped = _make_hooked_node(
            fake_node,
            "analyst",
            hooks,  # type: ignore[arg-type]
            bootstrap_mgr=None,
            prompt_assembler=assembler,
        )
        wrapped({"ip_name": "Berserk"})  # type: ignore[typeddict-item]

        assert len(captured_state) == 1
        assert captured_state[0].get("_prompt_assembler") is assembler

    def test_no_assembler_when_none(self, hooks: HookSystem) -> None:
        from geode.graph import _make_hooked_node

        captured_state: list[dict[str, Any]] = []

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            captured_state.append(dict(state))
            return {}

        wrapped = _make_hooked_node(
            fake_node,
            "analyst",
            hooks,  # type: ignore[arg-type]
            bootstrap_mgr=None,
            prompt_assembler=None,
        )
        wrapped({"ip_name": "Berserk"})  # type: ignore[typeddict-item]

        assert len(captured_state) == 1
        assert "_prompt_assembler" not in captured_state[0]


# ---------------------------------------------------------------------------
# Tests: PROMPT_ASSEMBLED hook event fires
# ---------------------------------------------------------------------------


class TestPromptAssembledHookEvent:
    def test_hook_event_fires_on_assemble(self, hooks: HookSystem) -> None:
        captured: list[dict[str, Any]] = []

        def _on_assembled(event: HookEvent, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.PROMPT_ASSEMBLED, _on_assembled, name="test_hook")

        assembler = PromptAssembler(hooks=hooks)  # type: ignore[arg-type]
        assembler.assemble(
            base_system="system",
            base_user="user",
            state={"_extra_instructions": ["test instruction"]},
            node="analyst",
            role_type="game_mechanics",
        )

        assert len(captured) == 1
        assert captured[0]["node"] == "analyst"
        assert captured[0]["role_type"] == "game_mechanics"
        assert "assembled_hash" in captured[0]
        assert captured[0]["fragment_count"] == 1  # bootstrap-extra:1

    def test_prompt_assembled_event_exists(self) -> None:
        assert hasattr(HookEvent, "PROMPT_ASSEMBLED")
        assert HookEvent.PROMPT_ASSEMBLED.value == "prompt_assembled"


# ---------------------------------------------------------------------------
# Tests: ContextAssembler._build_llm_summary
# ---------------------------------------------------------------------------


class TestContextAssemblerLlmSummary:
    def test_builds_summary_from_all_tiers(self) -> None:
        from geode.memory.context import ContextAssembler

        ctx: dict[str, Any] = {
            "_org_loaded": True,
            "organization_strategy": "Focus on action RPGs",
            "_project_loaded": True,
            "project_goal": "Q1 2026 evaluation",
            "_session_loaded": True,
            "previous_results": ["Berserk: S tier", "Bebop: A tier", "GitS: B tier"],
        }
        summary = ContextAssembler._build_llm_summary(ctx)
        assert "Organization: Focus on action RPGs" in summary
        assert "Project: Q1 2026 evaluation" in summary
        assert "Previous: Berserk: S tier" in summary
        assert " | " in summary

    def test_empty_context_returns_empty_string(self) -> None:
        from geode.memory.context import ContextAssembler

        assert ContextAssembler._build_llm_summary({}) == ""

    def test_partial_context(self) -> None:
        from geode.memory.context import ContextAssembler

        ctx: dict[str, Any] = {
            "_org_loaded": True,
            "organization_strategy": "Expand globally",
        }
        summary = ContextAssembler._build_llm_summary(ctx)
        assert summary == "Organization: Expand globally"
        assert " | " not in summary


# ---------------------------------------------------------------------------
# Tests: ANALYST_SPECIFIC migration (ADR-007 Phase 2 step 16)
# ---------------------------------------------------------------------------


class TestAnalystSpecificMigration:
    """ADR-007 Phase 2 step 16: skill .md takes priority over ANALYST_SPECIFIC."""

    def test_analyst_specific_suppressed_when_skill_exists(self) -> None:
        """When skill .md exists, ANALYST_SPECIFIC value should not appear in user prompt."""
        from geode.llm.skill_registry import SkillDefinition

        skill = SkillDefinition(
            name="analyst-game-mechanics",
            node="analyst",
            type="game_mechanics",
            priority=50,
            version="1.0",
            role="system",
            enabled=True,
            prompt_body="Custom skill guidance for game mechanics.",
            source_path=Path("/fake/analyst-game-mechanics.md"),
        )
        registry = SkillRegistry()
        registry._skills = [skill]

        assembler = PromptAssembler(skill_registry=registry)

        # Build a minimal state that _build_analyst_prompt() expects
        from geode.llm.prompts import ANALYST_SPECIFIC
        from geode.nodes.analysts import _build_analyst_prompt

        state: dict[str, Any] = {
            "ip_info": {
                "ip_name": "Test IP",
                "media_type": "anime",
                "release_year": 2020,
                "studio": "TestStudio",
                "genre": ["action"],
                "synopsis": "Test synopsis.",
            },
            "monolake": {
                "dau_current": 1000,
                "revenue_ltm": 50000,
                "active_game_count": 2,
                "last_game_year": 2019,
            },
            "signals": {
                "youtube_views": 1000000,
                "reddit_subscribers": 50000,
                "fan_art_yoy_pct": 15.0,
                "google_trends_index": 60,
                "twitter_mentions_monthly": 5000,
            },
            "_prompt_assembler": assembler,
        }

        system, user = _build_analyst_prompt("game_mechanics", state)

        # ANALYST_SPECIFIC value should NOT appear in user prompt
        # because skill .md exists for this analyst type
        assert ANALYST_SPECIFIC["game_mechanics"] not in user
        # But the skill guidance should be in system prompt
        assert "Custom skill guidance for game mechanics." in system

    def test_analyst_specific_used_when_no_skill(self) -> None:
        """When no skill .md exists, ANALYST_SPECIFIC should appear in user prompt."""
        from geode.llm.prompts import ANALYST_SPECIFIC
        from geode.nodes.analysts import _build_analyst_prompt

        assembler = PromptAssembler(skill_registry=SkillRegistry())

        state: dict[str, Any] = {
            "ip_info": {
                "ip_name": "Test IP",
                "media_type": "anime",
                "release_year": 2020,
                "studio": "TestStudio",
                "genre": ["action"],
                "synopsis": "Test synopsis.",
            },
            "monolake": {
                "dau_current": 1000,
                "revenue_ltm": 50000,
                "active_game_count": 2,
                "last_game_year": 2019,
            },
            "signals": {
                "youtube_views": 1000000,
                "reddit_subscribers": 50000,
                "fan_art_yoy_pct": 15.0,
                "google_trends_index": 60,
                "twitter_mentions_monthly": 5000,
            },
            "_prompt_assembler": assembler,
        }

        system, user = _build_analyst_prompt("game_mechanics", state)

        # ANALYST_SPECIFIC value SHOULD appear because no skill .md
        assert ANALYST_SPECIFIC["game_mechanics"] in user
