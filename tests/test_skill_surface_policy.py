from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_SKILLS = ROOT / ".agents/skills"
CLAUDE_SKILLS = ROOT / ".claude/skills"
RUNTIME_SKILLS = ROOT / ".geode/skills"


def _shared_skill_dirs() -> list[Path]:
    return sorted(path.parent for path in AGENT_SKILLS.glob("*/SKILL.md"))


def test_cross_host_skills_have_relative_claude_aliases() -> None:
    for canonical in _shared_skill_dirs():
        alias = CLAUDE_SKILLS / canonical.name
        assert alias.is_symlink(), f"missing Claude Code alias for {canonical.name}"
        assert not Path(os.readlink(alias)).is_absolute()
        assert alias.resolve() == canonical.resolve()


def test_runtime_overlaps_are_thin_scaffolds_not_competing_contracts() -> None:
    for scaffold_dir in _shared_skill_dirs():
        runtime_contract = RUNTIME_SKILLS / scaffold_dir.name / "SKILL.md"
        if not runtime_contract.is_file():
            continue
        scaffold = (scaffold_dir / "SKILL.md").read_text(encoding="utf-8")
        runtime_reference = f".geode/skills/{scaffold_dir.name}/SKILL.md"
        assert runtime_reference in scaffold
        assert not runtime_contract.parent.is_symlink()


def test_runtime_architecture_skills_name_current_package_roots() -> None:
    context = (RUNTIME_SKILLS / "geode-context/SKILL.md").read_text(encoding="utf-8")
    slop_audit = (RUNTIME_SKILLS / "slop-audit/SKILL.md").read_text(encoding="utf-8")

    for root in ("`core/`", "`evals/`", "`evolve/`"):
        assert root in context
        assert root in slop_audit
    assert "`geode_product/` — first-party composition" not in context
    assert "scan of `core/` / `geode_product/`" not in slop_audit
