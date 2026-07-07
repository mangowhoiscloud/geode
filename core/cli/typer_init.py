"""Typer ``geode init`` command implementation.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split). Hosts
the ``init`` subcommand plus the ``_ensure_gitignore_entry`` helper it
relies on. The Typer ``app`` registers the function from the package
``__init__``; the function lives here without the ``@app.command()``
decorator to avoid a circular import.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from core.ui.console import console

log = logging.getLogger(__name__)


def _ensure_gitignore_entry(entry: str, comment: str = "") -> None:
    """Add entry to .gitignore if not already present."""
    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry in content:
            return
        if not content.endswith("\n"):
            content += "\n"
    else:
        content = ""
    if comment:
        content += f"\n{comment}\n"
    content += f"{entry}\n"
    gitignore.write_text(content, encoding="utf-8")


def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config.toml"),
) -> None:
    """Initialize .geode/ project structure with template config.

    Auto-detects project type (Node/Python/Rust/Go/Java) and generates
    config.toml with build/test/lint commands + Claude Code hook templates.
    Pattern: harness-for-real init.sh
    """
    import json

    from core.config.project_detect import (
        detect_project_type,
        generate_config_toml,
        generate_hooks,
        generate_settings_json_hooks,
    )
    from core.memory.project import ProjectMemory
    from core.memory.user_profile import FileBasedUserProfile

    project_mem = ProjectMemory(Path("."))
    user_profile = FileBasedUserProfile()

    # 0. Global ~/.geode/ directory + .env (API key storage)
    from core.paths import GEODE_HOME  # PR-CLEANUP-D2 anchor

    global_geode = GEODE_HOME
    global_geode.mkdir(parents=True, exist_ok=True)
    global_env = global_geode / ".env"
    if not global_env.exists():
        global_env.write_text(
            "# GEODE global API keys (shared across all projects)\n"
            "# Keys here are authoritative; project .env only fills missing keys.\n"
            "# Priority: env vars > ~/.geode/.env > CWD/.env\n\n"
            "# ANTHROPIC_API_KEY=sk-ant-...\n"
            "# OPENAI_API_KEY=sk-proj-...\n"
            "# BRAVE_API_KEY=...\n",
            encoding="utf-8",
        )
        global_env.chmod(0o600)
        console.print(f"  Created {global_env} (global API keys)")

    # 1. Detect project type (harness-for-real init.sh pattern)
    project_info = detect_project_type(Path("."))
    console.print(
        f"  Detected project type: [bold]{project_info.project_type}[/bold]"
        f" ({project_info.pkg_mgr})"
        if project_info.pkg_mgr
        else ""
    )

    # 2. .geode/memory/ + .geode/rules/ (ProjectMemory)
    created_mem = project_mem.ensure_structure()
    if created_mem:
        console.print("  Created .geode/memory/ + .geode/rules/ structure")

    # 3. .geode/ directories
    geode_dirs = [
        # Agent memory (git-tracked)
        Path(".geode/memory"),
        Path(".geode/rules"),
        # C1: Project config
        Path(".geode/project"),
        # C2: Journal (append-only execution history)
        Path(".geode/journal"),
        Path(".geode/journal/transcripts"),
        # V0: Vault (purpose-routed artifact storage)
        Path(".geode/vault/profile"),
        Path(".geode/vault/research"),
        Path(".geode/vault/applications"),
        Path(".geode/vault/general"),
        # C3: Session (checkpoints, resumable)
        Path(".geode/session"),
        # C4: Plan (goals, pending tasks)
        Path(".geode/plan"),
        # Cache + outputs
        Path(".geode/cache"),
        Path(".geode/reports"),
        Path(".geode/snapshots"),
        Path(".geode/models"),
        # Legacy compat
        Path(".geode/sessions"),
        Path(".geode/result_cache"),
    ]
    for d in geode_dirs:
        d.mkdir(parents=True, exist_ok=True)
    console.print("  Created .geode/ directories")

    # 4. config.toml with detected project info
    config_path = Path(".geode/config.toml")
    if not config_path.exists() or force:
        config_content = generate_config_toml(project_info)
        config_path.write_text(config_content, encoding="utf-8")
        console.print("  Created .geode/config.toml (with detected commands)")
    else:
        console.print("  .geode/config.toml already exists (use --force to overwrite)")

    # 4b. routing.toml template
    routing_path = Path(".geode/routing.toml")
    if not routing_path.exists():
        routing_path.write_text(
            "# Node-level LLM model routing\n"
            "# Uncomment to override default model per pipeline node.\n\n"
            "[nodes]\n"
            '# analyst = "claude-opus-4-8"\n'
            '# evaluator = "claude-sonnet-4-6"\n'
            '# scoring = "claude-haiku-4-5-20251001"\n'
            '# synthesizer = "claude-opus-4-8"\n\n'
            "[agentic]\n"
            '# default = "claude-opus-4-8"\n'
            '# sub_agent = "claude-sonnet-4-6"\n',
            encoding="utf-8",
        )
        console.print("  Created .geode/routing.toml (template)")

    # 4c. model-policy.toml template
    from core.paths import PROJECT_MODEL_POLICY  # PR-CLEANUP-D2 anchor

    policy_path = PROJECT_MODEL_POLICY
    if not policy_path.exists():
        policy_path.write_text(
            "# Model governance — allowlist/denylist\n"
            "# If allowlist is set, only listed models are allowed.\n"
            "# If only denylist is set, listed models are blocked.\n\n"
            "[policy]\n"
            "# allowlist = "
            '["claude-opus-4-8", "claude-sonnet-4-6", "gpt-5.4"]\n'
            "# denylist = "
            '["claude-haiku-4-5-20251001"]\n'
            '# default_model = "claude-sonnet-4-6"\n',
            encoding="utf-8",
        )
        console.print("  Created .geode/model-policy.toml (template)")

    # 5. Hook templates (harness-for-real pattern)
    hooks_dir = Path(".claude/hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks = generate_hooks(project_info)
    for filename, content in hooks.items():
        hook_path = hooks_dir / filename
        if not hook_path.exists() or force:
            hook_path.write_text(content, encoding="utf-8")
            hook_path.chmod(0o755)
    if hooks:
        console.print(f"  Created .claude/hooks/ ({len(hooks)} hooks)")

    # 6. Register hooks in .claude/settings.json (merge, not overwrite)
    settings_path = Path(".claude/settings.json")
    hook_config = generate_settings_json_hooks()
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        # Merge hooks (don't overwrite existing permissions/other keys)
        if "hooks" not in existing:
            existing.update(hook_config)
            settings_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            console.print("  Registered hooks in .claude/settings.json")
        else:
            console.print("  .claude/settings.json hooks already configured")
    else:
        settings_path.write_text(
            json.dumps(hook_config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        console.print("  Created .claude/settings.json with hooks")

    # 7. ~/.geode/user_profile
    created_profile = user_profile.ensure_structure()
    if created_profile:
        console.print("  Created ~/.geode/user_profile/")

    # 7a. Seed project profile from global if absent
    try:
        project_profile_dir = Path(".geode/user_profile")
        global_profile_dir = user_profile.global_dir
        if (
            not project_profile_dir.exists()
            and isinstance(global_profile_dir, Path)
            and (global_profile_dir / "profile.md").exists()
        ):
            import shutil

            shutil.copytree(str(global_profile_dir), str(project_profile_dir))
            console.print("  Seeded .geode/user_profile/ from global profile")
    except OSError as e:
        log.debug("Profile seeding skipped: %s", e)

    # 7b. ~/.geode/identity/career.toml template
    from core.paths import GLOBAL_IDENTITY_DIR  # PR-CLEANUP-D2 anchor

    identity_dir = GLOBAL_IDENTITY_DIR
    career_toml = identity_dir / "career.toml"
    if not career_toml.exists():
        identity_dir.mkdir(parents=True, exist_ok=True)
        career_toml.write_text(
            "# Career identity — injected into system prompt context\n"
            "# Edit this file to personalize GEODE for job search / career tasks.\n\n"
            "[identity]\n"
            'title = ""\n'
            'experience = ""\n'
            "skills = []\n\n"
            "[goals]\n"
            'seeking = ""\n'
            "target_companies = []\n"
            'preferred_location = ""\n',
            encoding="utf-8",
        )
        console.print("  Created ~/.geode/identity/career.toml (template)")

    # 8. .gitignore entry
    _ensure_gitignore_entry(".geode/", "# GEODE")
    console.print("[success]GEODE project initialized.[/success]")
