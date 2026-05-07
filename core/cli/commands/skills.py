"""``/skills`` and ``/skill`` slash commands.

Hosts ``cmd_skills`` (list/inspect/reload), ``cmd_skill_invoke`` (invoke a
skill — supports ``context:fork`` subagent execution), and ``_skills_add``.
Extracted from the monolithic ``core/cli/commands.py`` (Tier 3 #9) —
every function body is preserved byte-identical from the legacy module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any as _Any

log = logging.getLogger(__name__)


def cmd_skills(skill_registry: _Any, arg: str) -> None:
    """Handle /skills command — list/inspect loaded skills.

    /skills           → list loaded skills
    /skills reload    → reload from disk
    /skills <name>    → show skill detail
    """
    from core.cli import commands as _pkg
    from core.skills.skills import SkillLoader, SkillRegistry

    reg: SkillRegistry = skill_registry
    sub = arg.strip() if arg else ""

    if not sub:
        names = reg.list_skills()
        if not names:
            _pkg.console.print("  [muted]No skills loaded.[/muted]")
            _pkg.console.print("  [muted]Add skills to .geode/skills/<name>/SKILL.md[/muted]")
            _pkg.console.print()
            return

        _pkg.console.print()
        _pkg.console.print(f"  [header]Skills ({len(names)})[/header]")
        for name in names:
            skill = reg.get(name)
            if skill is None:
                continue
            tools_str = f" [muted]({len(skill.tools)} tools)[/muted]" if skill.tools else ""
            desc = skill.description[:70]
            if len(skill.description) > 70:
                desc += "..."
            _pkg.console.print(f"  [label]{name:25s}[/label]{tools_str}  {desc}")
        _pkg.console.print()
        return

    if sub == "reload":
        # Clear and reload
        new_reg = SkillRegistry()
        loaded = SkillLoader().load_all(registry=new_reg)
        # Replace contents in existing registry
        reg._skills.clear()
        for skill in loaded:
            reg.register(skill)
        _pkg.console.print(f"  [success]Reloaded {len(loaded)} skills[/success]")
        _pkg.console.print()
        return

    if sub.startswith("add"):
        _skills_add(reg, sub[3:].strip())
        return

    # Show specific skill detail
    skill = reg.get(sub)
    if skill is None:
        _pkg.console.print(f"  [warning]Skill not found: {sub}[/warning]")
        _pkg.console.print(f"  [muted]Available: {', '.join(reg.list_skills())}[/muted]")
        _pkg.console.print()
        return

    _pkg.console.print()
    _pkg.console.print(f"  [header]{skill.name}[/header]")
    _pkg.console.print(f"  [label]Description:[/label] {skill.description}")
    if skill.triggers:
        _pkg.console.print(f"  [label]Triggers:[/label]    {', '.join(skill.triggers)}")
    if skill.tools:
        _pkg.console.print(f"  [label]Tools:[/label]       {', '.join(skill.tools)}")
    _pkg.console.print(f"  [label]Risk:[/label]        {skill.risk}")
    _pkg.console.print(f"  [label]Body:[/label]        {len(skill.body)} chars")
    _pkg.console.print()


def cmd_skill_invoke(skill_registry: _Any, arg: str, *, agentic_ref: _Any = None) -> None:
    """Handle /skill <name> [args] — invoke a skill with arguments.

    Supports context:fork (subagent execution) and $ARGUMENTS substitution.
    """
    from core.cli import commands as _pkg
    from core.skills.skills import SkillRegistry

    reg: SkillRegistry = skill_registry
    parts = arg.strip().split(None, 1)
    if not parts:
        _pkg.console.print("  [warning]Usage: /skill <name> [arguments][/warning]")
        _pkg.console.print()
        return

    name = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""

    skill = reg.get(name)
    if skill is None:
        _pkg.console.print(f"  [warning]Skill not found: {name}[/warning]")
        _pkg.console.print(f"  [muted]Available: {', '.join(reg.list_skills())}[/muted]")
        _pkg.console.print()
        return

    # Render skill body with dynamic context and arguments
    rendered = skill.render(arguments=arguments)
    if not rendered:
        _pkg.console.print(f"  [warning]Skill '{name}' has no body content[/warning]")
        _pkg.console.print()
        return

    if skill.context_fork:
        # Fork execution: run in isolated subagent
        _pkg.console.print(f"  [dim]Skill '{name}' → forked subagent[/dim]")
        from core.cli.bootstrap import _build_agentic_stack_minimal

        try:
            result = _build_agentic_stack_minimal(rendered, quiet=True)
            status = "ok" if result and not getattr(result, "error", False) else "err"
            summary = getattr(result, "text", "")[:200] if result else "(no output)"
            _pkg.console.print(f"  [dim]skill:{name} → {status}[/dim]")
            if summary:
                _pkg.console.print(f"\n{summary}\n")
        except Exception as exc:
            _pkg.console.print(f"  [error]Skill fork failed: {exc}[/error]")
    else:
        # Inline execution: inject rendered body as user message into main loop
        from core.cli.session_state import get_current_loop

        _loop = get_current_loop()
        if _loop is not None:
            prompt = f"[skill:{name}] {rendered}"
            result = _loop.run(prompt)
            from core.ui.agentic_ui import render_status_line

            render_status_line()
        else:
            _pkg.console.print("  [warning]AgenticLoop not available for skill execution[/warning]")
    _pkg.console.print()


def _skills_add(reg: _Any, raw: str) -> None:
    """Handle /skills add <path> — register an external SKILL.md file.

    Copies the SKILL.md into .geode/skills/<name>/ and registers it.
    Example: /skills add /path/to/my-skill/SKILL.md
    """
    import shutil

    from core.cli import commands as _pkg
    from core.skills.skills import SkillLoader

    path_str = raw.strip()
    if not path_str:
        _pkg.console.print("  [warning]Usage: /skills add <path-to-SKILL.md>[/warning]")
        _pkg.console.print("  [muted]Example: /skills add ./my-skill/SKILL.md[/muted]")
        _pkg.console.print()
        return

    src = Path(path_str).expanduser().resolve()
    if not src.exists():
        _pkg.console.print(f"  [warning]File not found: {src}[/warning]")
        _pkg.console.print()
        return

    if not src.name.upper().startswith("SKILL"):
        _pkg.console.print(f"  [warning]Expected a SKILL.md file, got: {src.name}[/warning]")
        _pkg.console.print()
        return

    # Determine skill name from parent directory or filename
    skill_name = src.parent.name
    if skill_name in (".", ""):
        skill_name = src.stem.lower().replace(" ", "-")

    # Copy to .geode/skills/<name>/SKILL.md
    loader = SkillLoader()
    dest_dir = loader.skills_dir / skill_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    shutil.copy2(src, dest)

    # Load and register
    skill = loader.load_file(dest)
    reg.register(skill)

    _pkg.console.print(f"  [success]Added skill: {skill.name}[/success]")
    _pkg.console.print(f"  [muted]Copied to {dest}[/muted]")
    if skill.triggers:
        _pkg.console.print(f"  [muted]Triggers: {', '.join(skill.triggers)}[/muted]")
    _pkg.console.print()
