from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENT_SKILLS = ROOT / ".agents/skills"
CLAUDE_SKILLS = ROOT / ".claude/skills"
RUNTIME_SKILLS = ROOT / ".geode/skills"
STANDARD_FRONTMATTER_FIELDS = {
    "allowed-tools",
    "compatibility",
    "description",
    "license",
    "metadata",
    "name",
}


def _shared_skill_dirs() -> list[Path]:
    return sorted(path.parent for path in AGENT_SKILLS.glob("*/SKILL.md"))


def test_cross_host_skills_have_relative_claude_aliases() -> None:
    assert {entry.name for entry in CLAUDE_SKILLS.iterdir()} == {
        canonical.name for canonical in _shared_skill_dirs()
    }
    for canonical in _shared_skill_dirs():
        alias = CLAUDE_SKILLS / canonical.name
        assert alias.is_symlink(), f"missing Claude Code alias for {canonical.name}"
        assert not Path(os.readlink(alias)).is_absolute()
        assert alias.resolve() == canonical.resolve()


def test_cross_host_skills_use_standard_frontmatter() -> None:
    for canonical in _shared_skill_dirs():
        text = (canonical / "SKILL.md").read_text(encoding="utf-8")
        _, frontmatter, _ = text.split("---", maxsplit=2)
        metadata = yaml.safe_load(frontmatter)

        assert metadata["name"] == canonical.name
        assert set(metadata) <= STANDARD_FRONTMATTER_FIELDS


def test_runtime_overlaps_are_thin_scaffolds_not_competing_contracts() -> None:
    for scaffold_dir in _shared_skill_dirs():
        runtime_contract = RUNTIME_SKILLS / scaffold_dir.name / "SKILL.md"
        if not runtime_contract.is_file():
            continue
        scaffold = (scaffold_dir / "SKILL.md").read_text(encoding="utf-8")
        runtime_reference = f".geode/skills/{scaffold_dir.name}/SKILL.md"
        assert runtime_reference in scaffold
        assert not runtime_contract.parent.is_symlink()


def test_public_inventory_covers_development_and_runtime_skills() -> None:
    inventory = (ROOT / "docs/scaffold-skills.md").read_text(encoding="utf-8")
    development, runtime = inventory.split("## Runtime Skills", maxsplit=1)

    for skill_dir in _shared_skill_dirs():
        assert f"| `{skill_dir.name}` |" in development
    for skill_file in sorted(RUNTIME_SKILLS.glob("*/SKILL.md")):
        assert f"| `{skill_file.parent.name}` |" in runtime


def test_reviewed_skills_define_non_echoing_security_boundaries() -> None:
    benchmark = (AGENT_SKILLS / "agent-world-benchmark/SKILL.md").read_text(encoding="utf-8")
    anti_deception = (AGENT_SKILLS / "anti-deception-checklist/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "does not provide cryptographic services" in benchmark
    assert "Hashing a secret is not redaction" in benchmark
    assert "Never publish" in benchmark
    assert "grep -rn" not in anti_deception
    assert "git grep -IlE" in anti_deception
    assert "never the matching line" in anti_deception
    assert "revoke or rotate it first" in anti_deception


def test_runtime_architecture_skills_name_current_package_roots() -> None:
    context = (RUNTIME_SKILLS / "geode-context/SKILL.md").read_text(encoding="utf-8")
    slop_audit = (RUNTIME_SKILLS / "slop-audit/SKILL.md").read_text(encoding="utf-8")

    for root in ("`core/`", "`evals/`", "`evolve/`"):
        assert root in context
        assert root in slop_audit
    assert "`geode_product/` — first-party composition" not in context
    assert "scan of `core/` / `geode_product/`" not in slop_audit
