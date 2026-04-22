"""CLI subcommand: geode skill — manage skills (list/create/install).

3-tier skill storage:
  tier 1: core/skills/        — builtin (repo)
  tier 2: .geode/skills/      — project (team)
  tier 3: ~/.geode/skills/    — personal (local only)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from core.skills._frontmatter import parse_yaml_frontmatter

app = typer.Typer(name="skill", help="Manage GEODE skills (list/create/install).")

_PROJECT_SKILLS = Path(".geode/skills")
_PERSONAL_SKILLS = Path.home() / ".geode" / "skills"


def _discover_skills() -> list[dict[str, str]]:
    """Discover all skills across 3 tiers."""
    results: list[dict[str, str]] = []

    for tier, base in [("project", _PROJECT_SKILLS), ("personal", _PERSONAL_SKILLS)]:
        if not base.exists():
            continue
        for skill_dir in sorted(base.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            text = skill_md.read_text(encoding="utf-8")
            meta, _body = parse_yaml_frontmatter(text)
            if not meta:
                continue
            results.append(
                {
                    "name": meta.get("name", skill_dir.name),
                    "description": meta.get("description", "")[:60],
                    "visibility": meta.get("visibility", "public"),
                    "tier": tier,
                    "path": str(skill_dir),
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
    for base in [_PROJECT_SKILLS, _PERSONAL_SKILLS]:
        skill_dir = base / name
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            text = skill_md.read_text(encoding="utf-8")
            meta, body = parse_yaml_frontmatter(text)
            typer.echo(f"Name:        {meta.get('name', name)}")
            typer.echo(f"Visibility:  {meta.get('visibility', 'public')}")
            typer.echo(f"Path:        {skill_dir}")
            typer.echo(f"Description: {meta.get('description', '')[:100]}")
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
