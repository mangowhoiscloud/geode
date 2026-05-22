"""Verify CSP-3 wiring — seed_generation / seed_critique toolkits now
include the literature-research tools, while pilot / ranker / evolver /
meta_review / proximity remain unchanged.

The intent is "LLM-autonomous literature grounding": Generator and
Critic can call arXiv / seed_pool search themselves, but the rest of
the pipeline keeps its narrower allowlist (Pilot stays pinned to
``petri_audit`` etc.).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.tools.toolkit_registry import load_default_registry

_LIT_TOOLS = frozenset({"arxiv_search", "paper_fetch_arxiv", "geode_seed_pool_search"})


class TestSeedGenerationToolkitLitWired:
    def test_generator_can_call_lit_tools(self) -> None:
        reg = load_default_registry(force_reload=True)
        tools = reg.resolve("seed_generation")
        assert tools >= _LIT_TOOLS, (
            f"seed_generation toolkit missing CSP-3 lit tools: {_LIT_TOOLS - tools}"
        )
        # Pre-CSP-3 read/write surface preserved.
        assert {"read_document", "write_file", "grep_files"} <= tools

    def test_critic_can_call_lit_tools(self) -> None:
        reg = load_default_registry(force_reload=True)
        tools = reg.resolve("seed_critique")
        assert tools >= _LIT_TOOLS, (
            f"seed_critique toolkit missing CSP-3 lit tools: {_LIT_TOOLS - tools}"
        )
        # Critique stays read-only — write surface NOT pulled in.
        assert "write_file" not in tools
        assert "edit_file" not in tools


class TestUnchangedToolkits:
    """The other 5 seed toolkits must not silently inherit lit tools."""

    @pytest.mark.parametrize(
        "kit_name",
        ["seed_proximity", "seed_pilot", "seed_ranker", "seed_evolver", "seed_meta_review"],
    )
    def test_kit_does_not_have_lit_tools(self, kit_name: str) -> None:
        reg = load_default_registry(force_reload=True)
        tools = reg.resolve(kit_name)
        leaked = _LIT_TOOLS & tools
        assert not leaked, (
            f"toolkit {kit_name!r} unexpectedly resolves lit tools: {leaked}. "
            "CSP-3 scope is generator/critic only — if you intentionally "
            "migrated this kit, update the test."
        )


class TestAgentPromptContract:
    """Grep-level pin — seed_generator.md and seed_critic.md must mention
    the literature tool names so the LLM knows they exist. Without the
    mention, the model would have access but not awareness."""

    def test_generator_prompt_mentions_lit_tools(self) -> None:
        text = Path(".claude/agents/seed_generator.md").read_text(encoding="utf-8")
        assert "geode_seed_pool_search" in text
        assert "arxiv_search" in text
        assert "references:" in text  # frontmatter contract advertised

    def test_critic_prompt_mentions_paper_fetch(self) -> None:
        text = Path(".claude/agents/seed_critic.md").read_text(encoding="utf-8")
        assert "paper_fetch_arxiv" in text
        assert "references:" in text  # spot-check contract

    def test_evolver_preserves_references_field(self) -> None:
        """CSP-3 contract — Evolver must preserve the Generator's
        ``references:`` provenance across rewrites."""
        text = Path(".claude/agents/seed_evolver.md").read_text(encoding="utf-8")
        assert "references:" in text
        assert "unchanged" in text.lower()  # phrased as a preservation rule
