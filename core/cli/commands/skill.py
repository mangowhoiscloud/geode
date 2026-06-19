"""CLI subcommand: geode skill — manage skills (list/create/install).

Discovery (list/show) delegates to ``core.skills.skills.SkillLoader`` so this
CLI and the runtime ``/skills`` agree on the same scopes (PR-SKILL-UNIFY):
  builtin  : <package>/.geode/skills/   — shipped with GEODE
  personal : ~/.geode/skills/           — local only
  project  : <cwd>/.geode/skills/       — team (committed)
``create`` / ``remove`` write only to the user tiers (project / personal); the
builtin tier is read-only.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from core.paths import GLOBAL_SKILLS_DIR, PROJECT_SKILLS_DIR

app = typer.Typer(name="skill", help="Manage GEODE skills (list/create/install).")

_PROJECT_SKILLS = PROJECT_SKILLS_DIR
_PERSONAL_SKILLS = GLOBAL_SKILLS_DIR


def _discover_skills() -> list[dict[str, str]]:
    """Discover all skills across every tier via the canonical ``SkillLoader``.

    PR-SKILL-UNIFY — this used to hand-roll a 2-tier (`project` + `personal`)
    ``iterdir`` scan that **omitted the bundled tier**, so ``geode skill list``
    silently showed a different set than the runtime ``/skills``. Now it reuses
    ``SkillLoader.discover_tiered`` (builtin + personal + project, same override
    semantics) so the two surfaces agree.
    """
    from core.skills.skills import SkillLoader

    loader = SkillLoader()
    results: list[dict[str, str]] = []
    for path, tier in loader.discover_tiered():
        skill = loader.load_file(path)
        results.append(
            {
                "name": skill.name,
                "description": skill.description[:60],
                "visibility": skill.visibility,
                "tier": tier,
                "path": str(path.parent),
            }
        )
    return results


@app.command(name="list")
def skill_list(
    all_: Annotated[bool, typer.Option("--all", "-a", help="Include unlisted skills")] = False,
) -> None:
    """List available skills with visibility and tier."""
    skills = _discover_skills()
    if not all_:
        skills = [s for s in skills if s["visibility"] != "unlisted"]

    if not skills:
        typer.echo("No skills found.")
        raise typer.Exit()

    # Header
    typer.echo(f"{'NAME':<25} {'VISIBILITY':<12} {'TIER':<10} DESCRIPTION")
    typer.echo("-" * 80)
    for s in skills:
        typer.echo(f"{s['name']:<25} {s['visibility']:<12} {s['tier']:<10} {s['description']}")
    typer.echo(f"\n{len(skills)} skills found.")


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Skill name (e.g. 'my-tool')")],
    private: Annotated[
        bool, typer.Option("--private", "-p", help="Create in personal tier (~/.geode/skills/)")
    ] = False,
    description: Annotated[str, typer.Option("--desc", "-d", help="Skill description")] = "",
) -> None:
    """Create a new skill from template."""
    base = _PERSONAL_SKILLS if private else _PROJECT_SKILLS
    skill_dir = base / name
    if skill_dir.exists():
        typer.echo(f"Skill '{name}' already exists at {skill_dir}", err=True)
        raise typer.Exit(1)

    visibility = "private" if private else "public"
    desc = description or f"{name} skill"

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"""---
name: {name}
description: {desc}
visibility: {visibility}
---

# {name}

Add your skill instructions here.
""",
        encoding="utf-8",
    )

    tier = "personal" if private else "project"
    typer.echo(f"Created skill '{name}' ({visibility}) at {skill_dir}")

    # Auto-add to .gitignore if private and in project dir
    if private:
        typer.echo(f"  tier: {tier} (not committed to git)")
    else:
        typer.echo(f"  tier: {tier}")
        _ensure_gitignore_if_private(name, visibility)


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Skill name to remove")],
) -> None:
    """Remove a skill."""
    for base in [_PROJECT_SKILLS, _PERSONAL_SKILLS]:
        skill_dir = base / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
            typer.echo(f"Removed skill '{name}' from {base}")
            return
    typer.echo(f"Skill '{name}' not found.", err=True)
    raise typer.Exit(1)


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="Skill name to inspect")],
) -> None:
    """Show skill details and content."""
    from core.skills.skills import SkillLoader

    loader = SkillLoader()
    for path in loader.discover():
        skill = loader.load_file(path)
        # Match the frontmatter name OR the directory name — ``list`` displays
        # the frontmatter name, so ``show <that name>`` must resolve even when a
        # skill's dir differs from its declared name (e.g. seed-generation-cycle/
        # → name: seed-pipeline-cycle).
        if name not in (skill.name, path.parent.name):
            continue
        typer.echo(f"Name:        {skill.name}")
        typer.echo(f"Visibility:  {skill.visibility}")
        typer.echo(f"Path:        {path.parent}")
        typer.echo(f"Description: {skill.description[:100]}")
        body = skill.load_body()
        if body.strip():
            typer.echo(f"\n--- Content ---\n{body.strip()[:500]}")
        return
    typer.echo(f"Skill '{name}' not found.", err=True)
    raise typer.Exit(1)


def _ensure_gitignore_if_private(name: str, visibility: str) -> None:
    """Add private skill to .gitignore if needed."""
    if visibility != "private":
        return
    gitignore = Path(".gitignore")
    if not gitignore.exists():
        return
    pattern = f".geode/skills/{name}/"
    content = gitignore.read_text(encoding="utf-8")
    if pattern not in content:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write(f"\n{pattern}\n")
