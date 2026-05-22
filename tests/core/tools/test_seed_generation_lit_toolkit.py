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
    """Grep-level pin — the generator and critic prompts must mention the
    literature tool names so the LLM knows they exist. Without the
    mention, the model would have access but not awareness.

    CSP-9 — prompts now live under ``plugins/seed_generation/agents/``
    (operator-override copies in ``.claude/agents/`` still win at
    discovery time, but the canonical source is the plugin folder).
    """

    _PLUGIN_AGENTS_DIR = Path("plugins/seed_generation/agents")

    def test_generator_prompt_mentions_lit_tools(self) -> None:
        text = (self._PLUGIN_AGENTS_DIR / "generator.md").read_text(encoding="utf-8")
        assert "geode_seed_pool_search" in text
        assert "arxiv_search" in text
        assert "references:" in text  # frontmatter contract advertised

    def test_critic_prompt_mentions_paper_fetch(self) -> None:
        text = (self._PLUGIN_AGENTS_DIR / "critic.md").read_text(encoding="utf-8")
        assert "paper_fetch_arxiv" in text
        assert "references:" in text  # spot-check contract

    def test_evolver_preserves_references_field(self) -> None:
        """CSP-3 contract — Evolver must preserve the Generator's
        ``references:`` provenance across rewrites."""
        text = (self._PLUGIN_AGENTS_DIR / "evolver.md").read_text(encoding="utf-8")
        assert "references:" in text
        assert "unchanged" in text.lower()  # phrased as a preservation rule


class TestPromptsColocationCSP9:
    """CSP-9 — pin that the 8 seed-generation prompts live in the plugin
    folder and that ``SubagentLoader`` discovers them under default config.

    Without this pin, a future refactor could move the .md files back to
    ``.claude/agents/`` (cwd-relative, not shipped with the package) and
    fresh clones would silently regress to "no registered agent" at
    runtime.
    """

    _ROLES = (
        "critic",
        "evolver",
        "generator",
        "meta_reviewer",
        "pilot",
        "proximity",
        "ranker",
        "supervisor",
    )

    def test_all_8_prompts_in_plugin_folder(self) -> None:
        agents_dir = Path("plugins/seed_generation/agents")
        for role in self._ROLES:
            prompt = agents_dir / f"{role}.md"
            assert prompt.is_file(), f"missing prompt: {prompt}"

    def test_subagent_loader_discovers_all_8_prompts(self) -> None:
        from core.skills.agents import SubagentLoader

        loader = SubagentLoader()
        loaded_names = {loader.load_file(p).name for p in loader.discover()}
        for role in self._ROLES:
            expected = f"seed_{role}"
            assert expected in loaded_names, (
                f"SubagentLoader did not discover {expected}; "
                f"check plugins/seed_generation/agents/{role}.md"
            )
