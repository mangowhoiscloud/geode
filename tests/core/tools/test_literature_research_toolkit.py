"""Smoke test — the bundled ``literature_research`` toolkit composes correctly."""

from __future__ import annotations

from core.tools.toolkit_registry import load_default_registry


def test_literature_research_resolves() -> None:
    """The kit expands to arxiv + seed_pool + common_read primitives."""
    reg = load_default_registry(force_reload=True)
    assert reg.has("literature_research")
    tools = reg.resolve("literature_research")
    # Three CSP-2 surface tools.
    assert {"arxiv_search", "paper_fetch_arxiv", "geode_seed_pool_search"} <= tools
    # ``common_read`` composition.
    assert {"read_document", "grep_files", "glob_files"} <= tools
    # No write tools — literature_research is read-only.
    assert "write_file" not in tools
    assert "edit_file" not in tools


def test_no_default_agent_uses_literature_research_yet() -> None:
    """CSP-2 ships the kit but does not migrate any default agent yet.

    Pinned so a future migration is an explicit decision (and the
    accompanying agent system_prompt update happens at the same time).
    """
    from core.skills.agents import AgentRegistry

    registry = AgentRegistry()
    registry.load_defaults()
    for name in ("research_assistant", "data_analyst", "web_researcher"):
        agent = registry.get(name)
        assert agent is not None
        assert agent.toolkit != "literature_research", (
            f"agent {name!r} unexpectedly migrated to literature_research; "
            "update this test if intentional + add a paper-grounding "
            "system_prompt change in the same PR."
        )
