"""Slash-command dispatcher for the GEODE thin CLI.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split). Hosts
``_handle_command`` — the multi-action dispatch tree shared between the
thin client local-handled commands and the daemon-side IPC handler.
"""

from __future__ import annotations

from typing import Any

from core.cli.commands import (
    cmd_apply,
    cmd_context,
    cmd_key,
    cmd_login,
    cmd_mcp,
    cmd_model,
    cmd_petri,
    cmd_schedule,
    cmd_skills,
    cmd_trigger,
    resolve_action,
    show_help,
)
from core.cli.onboarding import render_readiness
from core.cli.session_state import (
    _get_readiness,
    _scheduler_service_ctx,
)
from core.ui.console import console
from core.wiring.startup import check_readiness


def _handle_command(
    cmd: str,
    args: str,
    verbose: bool,
    *,
    skill_registry: Any = None,
    mcp_manager: Any = None,
) -> tuple[bool, bool, Any]:
    """Handle a slash command. Returns (should_break, new_verbose, resume_state)."""
    action = resolve_action(cmd)

    if action == "quit":
        from core.ui.agentic_ui import render_session_cost_summary

        render_session_cost_summary()
        console.print("  [muted]Goodbye.[/muted]\n")
        return True, verbose, None

    if action == "help":
        show_help()
    elif action == "cost":
        from core.cli.commands import cmd_cost

        cmd_cost(args)
    elif action == "verbose":
        verbose = not verbose
        state = "[success]ON[/success]" if verbose else "[muted]OFF[/muted]"
        console.print(f"  Verbose: {state}")
        console.print()
    elif action == "key":
        changed = cmd_key(args)
        if changed:
            new_readiness = check_readiness()
            from core.cli.session_state import _set_readiness

            _set_readiness(new_readiness)
            render_readiness(new_readiness)
    elif action == "model":
        cmd_model(args)
    elif action == "login":
        cmd_login(args)
    elif action == "petri":
        cmd_petri(args)
    elif action == "schedule":
        cmd_schedule(args, scheduler_service=_scheduler_service_ctx.get(None))
    elif action == "trigger":
        cmd_trigger(args)
    elif action == "status":
        from core.config import settings

        console.print()
        console.print("  [header]GEODE System Status[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        readiness = _get_readiness()
        if readiness:
            mode = "Full LLM" if not readiness.force_dry_run else "Dry-Run Only"
            console.print(f"  Mode: [bold]{mode}[/bold]")
        # MCP status section
        _mcp_st = mcp_manager.get_status() if mcp_manager is not None else {"active": []}
        console.print()
        console.print("  [header]MCP Servers[/header]")
        for srv in _mcp_st["active"]:
            _desc = f" -- {srv['description']}" if srv["description"] else ""
            console.print(f"    [green]OK[/green] {srv['name']} [dim]{_desc}[/dim]")
        if not _mcp_st["active"]:
            console.print("    [muted]No active servers[/muted]")
        console.print()

        # v0.63.0 — daemon + disk usage block (lifecycle parity with Hermes
        # ``cmd_status``). Skipped silently if json_output requested.
        if "--json" in args.split():
            from core.cli.cmd_lifecycle import show_status

            show_status(json_output=True)
        else:
            from core.cli.cmd_lifecycle import show_status

            show_status()
    elif action == "mcp":
        cmd_mcp(args, mcp_manager=mcp_manager)
    elif action == "skills":
        if skill_registry is not None:
            cmd_skills(skill_registry, args)
        else:
            console.print("  [muted]Skills not loaded.[/muted]")
            console.print()
    elif action == "skill_invoke":
        # /skill <name> [args] — invoke a skill with optional arguments
        if skill_registry is not None:
            from core.cli.commands import cmd_skill_invoke

            cmd_skill_invoke(skill_registry, args)
        else:
            console.print("  [muted]Skills not loaded.[/muted]")
            console.print()
    elif action == "resume":
        from core.cli.commands import cmd_resume

        resume_state = cmd_resume(args)
        return False, verbose, resume_state
    elif action == "context":
        cmd_context(args)
    elif action == "apply":
        cmd_apply(args)
    elif action == "compact":
        from core.cli.commands import cmd_compact

        cmd_compact(args)
    elif action == "clear":
        from core.cli.commands import cmd_clear

        cmd_clear(args)
    elif action in ("tasks", "task"):
        from core.cli.commands import cmd_tasks

        cmd_tasks(args)
    elif action == "audit":
        from plugins.petri_audit.cli_audit import cmd_audit_slash

        cmd_audit_slash(args)
    elif action == "self-improving":
        from core.cli.commands.self_improving import cmd_self_improving

        cmd_self_improving(args)
    elif action == "recall":
        from core.cli.commands.recall import cmd_recall

        cmd_recall(args)
    elif action == "stop":
        # v0.63.0 — Hermes-style daemon shutdown (`hermes stop`).
        # Args: ``/stop --force`` for SIGKILL, optional ``--timeout=N``.
        from core.cli.cmd_lifecycle import stop_serve

        force = "--force" in args.split()
        stop_serve(force=force)
    elif action == "clean":
        # v0.63.0 — selective cache cleanup. Args: ``--scope=all|project|global|build``
        # ``--all-data`` ``--force`` ``--dry-run``.
        from core.cli.cmd_lifecycle import do_clean

        opts = args.split()
        scope = next(
            (o.split("=", 1)[1] for o in opts if o.startswith("--scope=")),
            "all",
        )
        do_clean(
            scope=scope,
            all_data=("--all-data" in opts),
            force=("--force" in opts),
            dry_run=("--dry-run" in opts),
        )
    elif action == "uninstall":
        # v0.63.0 — full system removal (Hermes ``cmd_uninstall`` parity).
        # Args: ``--force`` to skip confirmation, ``--dry-run`` to preview,
        # ``--keep-config`` ``--keep-data`` for partial uninstall.
        from core.cli.cmd_lifecycle import do_uninstall

        opts = args.split()
        do_uninstall(
            force=("--force" in opts),
            dry_run=("--dry-run" in opts),
            keep_config=("--keep-config" in opts),
            keep_data=("--keep-data" in opts),
        )
    else:
        console.print(f"  [warning]Unknown command: {cmd}[/warning]")
        console.print("  [muted]Type /help for available commands.[/muted]")
        console.print()

    return False, verbose, None
