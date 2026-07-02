from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_evidence_first_workflow_has_required_scaffold_sections() -> None:
    workflow = _read("docs/workflow.md")

    required_sections = [
        "# GEODE Evidence-First Development Workflow",
        "## Core Loop",
        "## Progressive Disclosure Map",
        "## Worktree And GitFlow",
        "## Minimum Verification",
        ".claude/skills/geode-workflow/SKILL.md",
    ]

    for section in required_sections:
        assert section in workflow


def test_geode_workflow_skill_uses_progressive_disclosure() -> None:
    skill = _read(".claude/skills/geode-workflow/SKILL.md")

    required_references = [
        "references/phase-checklist.md",
        "references/provider-grounding.md",
        "references/observability-contract.md",
        "references/verification-gates.md",
        "references/gitflow.md",
    ]

    assert "name: geode-workflow" in skill
    assert "description:" in skill
    assert "## Reference Routing" in skill
    for reference in required_references:
        assert reference in skill
        assert (ROOT / ".claude/skills/geode-workflow" / reference).exists()


def test_agent_entrypoints_reference_canonical_workflow() -> None:
    for path in ("CLAUDE.md", "AGENTS.md"):
        text = _read(path)

        assert "docs/workflow.md" in text
        assert ".claude/skills/geode-workflow/" in text
        assert "evidence-first" in text.lower()
