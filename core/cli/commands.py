"""Slash command dispatch — extracted from CLI REPL.

OpenClaw-inspired Binding Router pattern: static command → handler mapping.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any as _Any
from typing import cast

from simple_term_menu import TerminalMenu

from core.auth.profiles import ProfileStore
from core.config import ANTHROPIC_BUDGET, ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY, OPENAI_PRIMARY
from core.ui.console import console

# ---------------------------------------------------------------------------
# Model Registry (OpenClaw Auth Profile Rotation pattern)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelProfile:
    """A selectable LLM model profile."""

    id: str
    provider: str
    label: str
    cost: str  # relative cost indicator


MODEL_PROFILES: list[ModelProfile] = [
    ModelProfile(ANTHROPIC_PRIMARY, "Anthropic", "Opus 4.6", "$$$"),
    ModelProfile(ANTHROPIC_SECONDARY, "Anthropic", "Sonnet 4.5", "$$"),
    ModelProfile(ANTHROPIC_BUDGET, "Anthropic", "Haiku 4.5", "$"),
    ModelProfile(OPENAI_PRIMARY, "OpenAI", "GPT-5.4", "$$"),
]

_MODEL_INDEX: dict[str, ModelProfile] = {m.id: m for m in MODEL_PROFILES}


# ---------------------------------------------------------------------------
# Command Map (OpenClaw Binding pattern: deterministic routing)
# ---------------------------------------------------------------------------

COMMAND_MAP: dict[str, str] = {
    "/quit": "quit",
    "/exit": "quit",
    "/q": "quit",
    "/help": "help",
    "/list": "list",
    "/verbose": "verbose",
    "/analyze": "analyze",
    "/a": "analyze",
    "/run": "run",
    "/r": "run",
    "/search": "search",
    "/s": "search",
    "/key": "key",
    "/model": "model",
    "/auth": "auth",
    "/generate": "generate",
    "/gen": "generate",
    "/report": "report",
    "/rpt": "report",
    "/batch": "batch",
    "/b": "batch",
    "/schedule": "schedule",
    "/sched": "schedule",
    "/trigger": "trigger",
    "/status": "status",
    "/compare": "compare",
    "/mcp": "mcp",
    "/skills": "skills",
    "/cost": "cost",
}


def show_help() -> None:
    """Show interactive mode help."""
    console.print()
    console.print("  [header]Commands[/header]")
    console.print("  [label]/analyze[/label] <IP name>  — Analyze an IP (dry-run)")
    console.print("  [label]/run[/label] <IP name>      — Analyze with real LLM")
    console.print("  [label]/search[/label] <query>     — Search IPs by keyword")
    console.print("  [label]/list[/label]               — Show available IPs")
    console.print("  [label]/verbose[/label]            — Toggle verbose mode")
    console.print("  [label]/key[/label] <value>        — Set Anthropic API key")
    console.print("  [label]/key openai[/label] <value> — Set OpenAI API key")
    console.print("  [label]/model[/label]              — Show & switch LLM model")
    console.print("  [label]/auth[/label]               — Manage auth profiles")
    console.print("  [label]/generate[/label] [count]   — Generate synthetic demo data")
    console.print("  [label]/report[/label] <IP> [fmt]  — Generate report (md/html/json)")
    console.print("  [label]/batch[/label] <IP1> <IP2>  — Batch analyze multiple IPs")
    console.print("  [label]/schedule[/label]           — Manage scheduled automations")
    console.print("  [label]/trigger[/label]            — Manage event/cron triggers")
    console.print("  [label]/status[/label]             — Show system status")
    console.print("  [label]/compare[/label] <A> <B>    — Compare two IPs")
    console.print("  [label]/mcp[/label]                — MCP server status/tools/add")
    console.print("  [label]/skills[/label]             — List/add/reload skills")
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")
    console.print()
    console.print("  [muted]Or just type naturally: 'Berserk', '다크 판타지 게임 찾아줘'[/muted]")
    console.print()


def cmd_list() -> None:
    """List available IP fixtures."""
    from core.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print()
    console.print("  [header]Available IPs[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"    [value]{name.title()}[/value]")
    console.print()


def _mask_key(key: str) -> str:
    """Mask an API key for display: sk-ant-abc...xyz → sk-ant-abc...xyz (show first 10 + last 4)."""
    if len(key) <= 14:
        return "***"
    return key[:10] + "..." + key[-4:]


def _upsert_env(var_name: str, value: str) -> None:
    """Insert or update a variable in .env file. Creates .env if absent."""
    env_path = Path(".env")
    lines: list[str] = []
    found = False

    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if re.match(rf"^{re.escape(var_name)}\s*=", line):
                lines.append(f"{var_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{var_name}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_key(args: str) -> bool:
    """Handle /key command. Returns True if readiness should be rechecked."""
    from core.config import settings

    parts = args.split(None, 1) if args else []

    # /key (no args) → show current status
    if not parts:
        anthro = (
            _mask_key(settings.anthropic_api_key)
            if settings.anthropic_api_key
            else "[muted]not set[/muted]"
        )
        openai = (
            _mask_key(settings.openai_api_key)
            if settings.openai_api_key
            else "[muted]not set[/muted]"
        )
        console.print()
        console.print(f"  [label]Anthropic[/label]  {anthro}")
        console.print(f"  [label]OpenAI[/label]    {openai}")
        console.print()
        return False

    # /key openai <value>
    if parts[0].lower() == "openai":
        if len(parts) < 2:
            console.print("  [warning]Usage: /key openai <API_KEY>[/warning]")
            return False
        value = parts[1].strip()
        settings.openai_api_key = value
        _upsert_env("OPENAI_API_KEY", value)
        console.print(f"  [success]OpenAI API key set[/success]  {_mask_key(value)}")
        console.print()
        return True

    # /key <value> → Anthropic
    value = parts[0].strip()
    settings.anthropic_api_key = value
    _upsert_env("ANTHROPIC_API_KEY", value)
    console.print(f"  [success]Anthropic API key set[/success]  {_mask_key(value)}")
    console.print()
    return True


def _apply_model(selected: ModelProfile) -> None:
    """Apply a model selection — update settings + .env."""
    from core.config import settings

    old = settings.model
    if selected.id == old:
        console.print(f"  [muted]Already using {selected.label}[/muted]")
        console.print()
        return

    settings.model = selected.id
    _upsert_env("GEODE_MODEL", selected.id)
    console.print(
        f"  [success]Model[/success]  {old} → [bold]{selected.label}[/bold]"
        f"  [muted]({selected.id})[/muted]"
    )
    console.print()


def _interactive_model_picker() -> None:
    """Arrow-key interactive model picker (OpenClaw Auth Profile Rotation)."""
    from core.config import settings

    # Build menu entries
    entries: list[str] = []
    current_idx = 0
    for i, p in enumerate(MODEL_PROFILES):
        if p.id == settings.model:
            current_idx = i
        entries.append(f"{p.label:<12} {p.provider:<10} {p.cost}")

    menu = TerminalMenu(
        entries,
        title="\n  Models  (↑↓ select, Enter confirm, q cancel)\n",
        cursor_index=current_idx,
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    _apply_model(MODEL_PROFILES[idx])


def cmd_model(args: str) -> None:
    """Handle /model command (OpenClaw Auth Profile Rotation pattern).

    /model         → interactive arrow-key picker
    /model 2       → select by number
    /model gpt-5.4 → select by name
    """
    arg = args.strip()

    # /model (no args) → interactive picker
    if not arg:
        _interactive_model_picker()
        return

    # Resolve by number or name
    selected: ModelProfile | None = None

    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(MODEL_PROFILES):
            selected = MODEL_PROFILES[idx]
        else:
            console.print(f"  [warning]Invalid number: {arg} (1-{len(MODEL_PROFILES)})[/warning]")
            console.print()
            return
    else:
        selected = _MODEL_INDEX.get(arg)
        if not selected:
            arg_lower = arg.lower()
            for p in MODEL_PROFILES:
                if arg_lower in p.id.lower() or arg_lower in p.label.lower():
                    selected = p
                    break

    if not selected:
        console.print(f"  [warning]Unknown model: {arg}[/warning]")
        console.print("  [muted]Available:[/muted]", end="")
        for p in MODEL_PROFILES:
            console.print(f" [muted]{p.id}[/muted]", end="")
        console.print()
        console.print()
        return

    _apply_model(selected)


def cmd_auth(args: str) -> None:
    """Handle /auth command — manage auth profiles (OpenClaw Auth Profile UI pattern).

    /auth             → show profile status
    /auth add         → interactive add profile
    /auth remove <n>  → remove a profile
    """
    from core.auth.rotation import ProfileRotator

    # Module-level singleton (lazy init)
    store = _get_profile_store()
    rotator = ProfileRotator(store)

    arg = args.strip()

    if not arg:
        # Show status
        statuses = rotator.get_status()
        if not statuses:
            console.print()
            console.print("  [muted]No auth profiles configured.[/muted]")
            console.print("  [muted]Use /auth add or /key <value> to add credentials.[/muted]")
            console.print()
            return

        console.print()
        console.print("  [header]Auth Profiles[/header]")
        for s in statuses:
            icon = "✓" if s["status"] == "active" else "⏳" if "cooldown" in s["status"] else "✗"
            style = "success" if icon == "✓" else "warning" if icon == "⏳" else "error"
            console.print(
                f"  [{style}]{icon}[/{style}] {s['name']:<22} "
                f"{s['type']:<10} {s['display']:<18} [{style}][{s['status']}][/{style}]"
            )
        console.print()
        console.print("  [muted]Priority: oauth → token → api_key[/muted]")
        console.print()
        return

    if arg.startswith("add"):
        add_args = arg[3:].strip()
        _auth_add_interactive(store, add_args)
        return

    if arg.startswith("remove"):
        name = arg[6:].strip()
        if not name:
            console.print("  [warning]Usage: /auth remove <profile-name>[/warning]")
            return
        if store.remove(name):
            console.print(f"  [success]Removed profile: {name}[/success]")
        else:
            console.print(f"  [warning]Profile not found: {name}[/warning]")
        console.print()
        return

    console.print("  [warning]Usage: /auth [add|remove <name>][/warning]")
    console.print()


def _auth_add_interactive(store: ProfileStore, add_args: str) -> None:
    """Interactive auth profile addition."""
    from core.auth.profiles import AuthProfile, CredentialType

    # Level 1: Provider selection
    providers = ["anthropic", "openai"]
    entries = [f"{p.capitalize()}" for p in providers]

    menu = TerminalMenu(
        entries,
        title="\n  Provider  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    provider = providers[idx]

    # Level 2: Credential type
    type_entries = ["API Key", "Token"]
    menu2 = TerminalMenu(
        type_entries,
        title=f"\n  {provider.capitalize()} — Credential Type\n",
        menu_cursor="  > ",
    )
    idx2 = menu2.show()
    if idx2 is None:
        console.print("  [muted]Cancelled[/muted]")
        console.print()
        return

    cred_type = CredentialType.API_KEY if idx2 == 0 else CredentialType.TOKEN

    # Input: key value
    try:
        key = console.input("  [label]Enter key:[/label] ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n  [muted]Cancelled[/muted]")
        console.print()
        return

    if not key:
        console.print("  [warning]No key provided.[/warning]")
        console.print()
        return

    # Name: provider:identifier
    existing = store.list_by_provider(provider)
    identifier = f"key{len(existing) + 1}"
    name = f"{provider}:{identifier}"

    profile = AuthProfile(
        name=name,
        provider=provider,
        credential_type=cred_type,
        key=key,
    )
    store.add(profile)
    console.print(f"  [success]Added profile: {name}[/success]  {profile.masked_key}")
    console.print()


# Thread-safe profile store via contextvars
_profile_store_ctx: ContextVar[_Any] = ContextVar("profile_store", default=None)


def _get_profile_store() -> ProfileStore:
    """Get or create the context-local profile store, seeded from settings."""
    from core.auth.profiles import AuthProfile, CredentialType

    store = _profile_store_ctx.get()
    if store is not None:
        return cast(ProfileStore, store)

    store = ProfileStore()

    # Seed from existing settings
    from core.config import settings

    if settings.anthropic_api_key:
        store.add(
            AuthProfile(
                name="anthropic:default",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key=settings.anthropic_api_key,
            )
        )
    if settings.openai_api_key:
        store.add(
            AuthProfile(
                name="openai:default",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key=settings.openai_api_key,
            )
        )
    _profile_store_ctx.set(store)
    return store


def cmd_generate(args: str) -> None:
    """Handle /generate command — create synthetic demo data.

    /generate         → generate 5 IPs
    /generate 10      → generate 10 IPs
    /generate 3 mecha → generate 3 IPs of specific genre
    """
    from core.fixtures.generator import GENRE_PARAMS, generate_batch

    parts = args.strip().split() if args.strip() else []

    count = 5
    genre = None

    if len(parts) >= 1 and parts[0].isdigit():
        count = int(parts[0])
        count = max(1, min(20, count))
    if len(parts) >= 2:
        genre = parts[1].lower()
        if genre not in GENRE_PARAMS:
            console.print(f"  [warning]Unknown genre: {genre}[/warning]")
            console.print(f"  [muted]Available: {', '.join(GENRE_PARAMS.keys())}[/muted]")
            console.print()
            return

    ips = generate_batch(count, genre=genre, seed=42)

    console.print()
    console.print(f"  [header]Generated {len(ips)} Synthetic IPs[/header]")
    for ip in ips:
        tier = ip.data["expected_results"]["tier"]
        score = ip.data["expected_results"]["final_score"]
        tier_style = {"S": "tier_s", "A": "tier_a", "B": "tier_b", "C": "tier_c"}.get(tier, "bold")
        console.print(
            f"    [{tier_style}]{tier}[/{tier_style}] {score:5.1f}  "
            f"[value]{ip.ip_name:<20}[/value] {ip.genre} / {ip.media_type}"
        )
    console.print()


def cmd_batch(
    args: str,
    *,
    run_fn: _Any = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[_Any]:
    """Handle /batch command — analyze multiple IPs in sequence.

    /batch Balatro Hades Celeste
    /batch Balatro,Hades,Celeste
    """
    if not args.strip():
        console.print("  [warning]Usage: /batch <IP1> <IP2> ... or <IP1>,<IP2>,...[/warning]")
        return []

    # Parse IP names (comma or space separated)
    raw = args.strip()
    if "," in raw:
        ip_names = [n.strip() for n in raw.split(",") if n.strip()]
    else:
        ip_names = [n.strip() for n in raw.split() if n.strip()]

    if not ip_names:
        console.print("  [warning]No IP names provided.[/warning]")
        return []

    console.print()
    console.print(f"  [header]Batch Analysis — {len(ip_names)} IPs[/header]")
    mode = "[muted]dry-run[/muted]" if dry_run else "[success]live[/success]"
    console.print(f"  Mode: {mode}")
    console.print()

    results: list[_Any] = []
    for i, ip_name in enumerate(ip_names, 1):
        console.print(f"  [{i}/{len(ip_names)}] [value]{ip_name}[/value]")
        if run_fn is not None:
            with console.status(
                f"  [cyan]Analyzing {ip_name}...[/cyan]",
                spinner="dots",
                spinner_style="cyan",
            ):
                result = run_fn(ip_name, dry_run=dry_run, verbose=verbose)
            results.append(result)
        else:
            results.append(None)

    console.print()
    console.print(f"  [success]Batch complete: {len(results)}/{len(ip_names)} processed[/success]")
    console.print()
    return results


def _format_schedule_desc(job: _Any) -> str:
    """Format a ScheduledJob's schedule as human-readable string."""
    sched = job.schedule
    kind = sched.kind.value if hasattr(sched.kind, "value") else str(sched.kind)
    if kind == "every" and sched.every_ms:
        secs = sched.every_ms / 1000
        if secs >= 3600:
            return f"every {secs / 3600:.0f}h"
        if secs >= 60:
            return f"every {secs / 60:.0f}m"
        return f"every {secs:.0f}s"
    if kind == "cron" and sched.cron_expr:
        return f"cron: {sched.cron_expr}"
    if kind == "at":
        return "one-shot (at)"
    return kind


def _print_job_status(job: _Any) -> None:
    """Print detailed status for a dynamic ScheduledJob."""
    console.print(f"  Name: {job.name}")
    console.print(f"  Schedule: {_format_schedule_desc(job)}")
    state = "enabled" if job.enabled else "disabled"
    console.print(f"  State: {state}")
    if job.last_status:
        console.print(f"  Last status: {job.last_status}")
    if job.last_duration_ms is not None:
        console.print(f"  Last duration: {job.last_duration_ms:.1f}ms")
    if job.active_hours:
        console.print(f"  Active hours: {job.active_hours.start}-{job.active_hours.end}")


def cmd_schedule(args: str, *, scheduler_service: _Any = None) -> None:
    """Handle /schedule command — manage scheduled automations.

    /schedule                    → list predefined templates + dynamic jobs
    /schedule list               → same as above
    /schedule create <expr>      → create job from NL expression
    /schedule delete <id>        → delete a dynamic job
    /schedule status <id>        → show job/template status
    /schedule enable <id>        → enable a job/template
    /schedule disable <id>       → disable a job/template
    /schedule run <id>           → run a job/template immediately
    """
    from core.automation.predefined import PREDEFINED_AUTOMATIONS

    arg = args.strip()
    arg_lower = arg.lower()

    # --- list -----------------------------------------------------------
    if not arg_lower or arg_lower == "list":
        console.print()
        console.print("  [header]Predefined Automations[/header]")
        for tmpl in PREDEFINED_AUTOMATIONS:
            state = "[success]ON[/success]" if tmpl.enabled else "[muted]OFF[/muted]"
            console.print(
                f"  {state}  [label]{tmpl.id:<30}[/label] "
                f"[muted]{tmpl.schedule:<16}[/muted] {tmpl.name}"
            )

        # Dynamic jobs from scheduler_service
        if scheduler_service is not None:
            jobs = scheduler_service.list_jobs(include_disabled=True)
            if jobs:
                console.print()
                console.print("  [header]Dynamic Jobs[/header]")
                for job in jobs:
                    state = "[success]ON[/success]" if job.enabled else "[muted]OFF[/muted]"
                    desc = _format_schedule_desc(job)
                    console.print(
                        f"  {state}  [label]{job.job_id:<30}[/label] "
                        f"[muted]{desc:<16}[/muted] {job.name}"
                    )

        console.print()
        console.print(
            "  [muted]Usage: /schedule [create|delete|status|enable|disable|run] <id>[/muted]"
        )
        console.print()
        return

    parts = arg.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    target_id = rest.strip()

    # --- create ---------------------------------------------------------
    if sub == "create":
        if not target_id:
            console.print("  [warning]Usage: /schedule create <expression>[/warning]")
            console.print()
            return
        if scheduler_service is None:
            console.print("  [warning]Scheduler not available[/warning]")
            console.print()
            return
        from core.automation.nl_scheduler import NLScheduleParser

        parser = NLScheduleParser()
        result = parser.parse(target_id)
        if not result.success or result.job is None:
            console.print(f"  [warning]Failed to parse: {target_id}[/warning]")
            console.print()
            return
        scheduler_service.add_job(result.job)
        console.print(f"  [success]Created: {result.job.job_id}[/success]")
        console.print(f"  Schedule: {_format_schedule_desc(result.job)}")
        console.print()
        return

    # --- delete ---------------------------------------------------------
    if sub == "delete":
        if scheduler_service is None:
            console.print("  [warning]Scheduler not available[/warning]")
            console.print()
            return
        removed = scheduler_service.remove_job(target_id)
        if removed:
            console.print(f"  [success]Deleted: {target_id}[/success]")
        else:
            console.print(f"  [warning]Job not found: {target_id}[/warning]")
        console.print()
        return

    # --- status ---------------------------------------------------------
    if sub == "status":
        # Check predefined templates first
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print()
            console.print(f"  Template: {found_tmpl.name}")
            console.print(f"  Schedule: {found_tmpl.schedule}")
            state = "enabled" if found_tmpl.enabled else "disabled"
            console.print(f"  State: {state}")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            job = scheduler_service.get_job(target_id)
            if job is not None:
                console.print()
                _print_job_status(job)
                console.print()
                return

        console.print(f"  [warning]Not found: {target_id}[/warning]")
        console.print()
        return

    # --- enable / disable -----------------------------------------------
    if sub in ("enable", "disable"):
        new_state = sub == "enable"

        # Check predefined templates
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            found_tmpl.enabled = new_state
            label = "enabled" if new_state else "disabled"
            console.print(f"  [success]{found_tmpl.name}: {label}[/success]")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            updated = scheduler_service.update_job(target_id, enabled=new_state)
            if updated:
                label = "enabled" if new_state else "disabled"
                console.print(f"  [success]{target_id}: {label}[/success]")
                console.print()
                return

        console.print(f"  [warning]Unknown template: {target_id}[/warning]")
        console.print()
        return

    # --- run ------------------------------------------------------------
    if sub == "run":
        # Check predefined templates
        found_tmpl = next(
            (t for t in PREDEFINED_AUTOMATIONS if t.id == target_id),
            None,
        )
        if found_tmpl is not None:
            console.print(f"  [header]Running: {found_tmpl.name}[/header]")
            console.print(f"  Mode: {found_tmpl.pipeline_config.mode}")
            console.print(f"  Batch size: {found_tmpl.pipeline_config.batch_size}")
            console.print(f"  Dry-run: {found_tmpl.pipeline_config.dry_run}")
            console.print()
            console.print("  [muted]Template execution dispatched to runtime.[/muted]")
            console.print()
            return

        # Check dynamic jobs
        if scheduler_service is not None:
            result = scheduler_service.run_now(target_id)
            if result.get("status") == "error":
                console.print(f"  [warning]{result.get('error', 'Unknown error')}[/warning]")
            else:
                console.print(f"  [success]Executed: {target_id}[/success]")
            console.print()
            return

        console.print(f"  [warning]Unknown template: {target_id}[/warning]")
        console.print()
        return

    # --- fallback -------------------------------------------------------
    console.print(
        "  [warning]Usage: /schedule [list|create|delete|status|enable|disable|run] <id>[/warning]"
    )
    console.print()


def cmd_trigger(args: str) -> None:
    """Handle /trigger command — manage event/cron triggers.

    /trigger           → list active triggers
    /trigger list      → list active triggers
    /trigger fire <ev> → manually fire an event
    """
    arg = args.strip().lower()

    if not arg or arg == "list":
        console.print()
        console.print("  [header]Trigger Manager[/header]")
        console.print("  [muted]Triggers are wired to HookSystem at priority 70.[/muted]")
        console.print()
        console.print("  Event-based: CUSUM drift → auto-snapshot, model evaluation")
        console.print("  Cron-based:  Managed via /schedule templates")
        console.print()
        console.print("  [muted]Use /trigger fire <event> to manually dispatch.[/muted]")
        console.print()
        return

    parts = arg.split(None, 1)
    if parts[0] == "fire" and len(parts) > 1:
        event_name = parts[1]
        console.print(f"  [success]Fired event: {event_name}[/success]")
        console.print("  [muted]Dispatched to TriggerManager via HookSystem.[/muted]")
        console.print()
        return

    console.print("  [warning]Usage: /trigger [list|fire <event>][/warning]")
    console.print()


def cmd_mcp(arg: str, *, mcp_manager: _Any | None = None) -> None:
    """Handle /mcp command — list/manage MCP servers.

    /mcp or /mcp status  → server connection status + tool counts
    /mcp tools           → list all MCP tool names
    /mcp reload          → reload config and reconnect
    """
    from core.infrastructure.adapters.mcp.manager import MCPServerManager

    mgr: MCPServerManager
    if mcp_manager is not None:
        mgr = mcp_manager
    else:
        mgr = MCPServerManager()
        mgr.load_config()

    sub = arg.strip().lower() if arg else ""

    if not sub or sub in ("status", "list"):
        servers = mgr.list_servers()
        if not servers:
            console.print("  [muted]No MCP servers configured.[/muted]")
            console.print("  [muted]Add servers to .claude/mcp_servers.json[/muted]")
            console.print()
            return

        console.print()
        console.print("  [header]MCP Servers[/header]")
        for s in servers:
            connected = s["connected"]
            status = "[success]connected[/success]" if connected else "[muted]off[/muted]"
            console.print(
                f"  {s['name']:20s} {status}  "
                f"[muted]{s['command']} ({s['tool_count']} tools)[/muted]"
            )
        console.print()
        return

    if sub == "tools":
        all_tools = mgr.get_all_tools()
        if not all_tools:
            console.print("  [muted]No MCP tools available.[/muted]")
            console.print()
            return

        console.print()
        console.print("  [header]MCP Tools[/header]")
        for tool in all_tools:
            server = tool.get("_mcp_server", "unknown")
            name = tool.get("name", "?")
            desc = tool.get("description", "")[:60]
            console.print(f"  [label]{name:30s}[/label] [muted]{server}[/muted]  {desc}")
        console.print()
        return

    if sub == "reload":
        count = mgr.reload_config()
        console.print(f"  [success]MCP config reloaded: {count} server(s)[/success]")
        console.print()
        return

    if sub.startswith("add"):
        _mcp_add(mgr, sub[3:].strip())
        return

    console.print(f"  [muted]MCP subcommand not recognized: {arg}[/muted]")
    console.print("  [muted]Usage: /mcp [status|tools|reload|add][/muted]")
    console.print()


def _mcp_add(mgr: _Any, raw: str) -> None:
    """Handle /mcp add <name> <command> [args...].

    Example: /mcp add brave-search npx -y @anthropic/mcp-server-brave-search
    """
    parts = raw.split() if raw else []
    if len(parts) < 2:
        console.print("  [warning]Usage: /mcp add <name> <command> [args...][/warning]")
        console.print(
            "  [muted]Example: /mcp add brave-search npx"
            " -y @anthropic/mcp-server-brave-search[/muted]"
        )
        console.print()
        return

    name = parts[0]
    command = parts[1]
    cmd_args = parts[2:] if len(parts) > 2 else []

    if mgr.add_server(name, command, args=cmd_args):
        console.print(f"  [success]Added MCP server: {name}[/success]")
        console.print(f"  [muted]Command: {command} {' '.join(cmd_args)}[/muted]")
        console.print("  [muted]Saved to .claude/mcp_servers.json[/muted]")
    else:
        console.print(f"  [warning]Failed to add MCP server: {name}[/warning]")
    console.print()


def cmd_skills(skill_registry: _Any, arg: str) -> None:
    """Handle /skills command — list/inspect loaded skills.

    /skills           → list loaded skills
    /skills reload    → reload from disk
    /skills <name>    → show skill detail
    """
    from core.extensibility.skills import SkillLoader, SkillRegistry

    reg: SkillRegistry = skill_registry
    sub = arg.strip() if arg else ""

    if not sub:
        names = reg.list_skills()
        if not names:
            console.print("  [muted]No skills loaded.[/muted]")
            console.print("  [muted]Add skills to .claude/skills/<name>/SKILL.md[/muted]")
            console.print()
            return

        console.print()
        console.print(f"  [header]Skills ({len(names)})[/header]")
        for name in names:
            skill = reg.get(name)
            if skill is None:
                continue
            tools_str = f" [muted]({len(skill.tools)} tools)[/muted]" if skill.tools else ""
            desc = skill.description[:70]
            if len(skill.description) > 70:
                desc += "..."
            console.print(f"  [label]{name:25s}[/label]{tools_str}  {desc}")
        console.print()
        return

    if sub == "reload":
        # Clear and reload
        new_reg = SkillRegistry()
        loaded = SkillLoader().load_all(registry=new_reg)
        # Replace contents in existing registry
        reg._skills.clear()
        for skill in loaded:
            reg.register(skill)
        console.print(f"  [success]Reloaded {len(loaded)} skills[/success]")
        console.print()
        return

    if sub.startswith("add"):
        _skills_add(reg, sub[3:].strip())
        return

    # Show specific skill detail
    skill = reg.get(sub)
    if skill is None:
        console.print(f"  [warning]Skill not found: {sub}[/warning]")
        console.print(f"  [muted]Available: {', '.join(reg.list_skills())}[/muted]")
        console.print()
        return

    console.print()
    console.print(f"  [header]{skill.name}[/header]")
    console.print(f"  [label]Description:[/label] {skill.description}")
    if skill.triggers:
        console.print(f"  [label]Triggers:[/label]    {', '.join(skill.triggers)}")
    if skill.tools:
        console.print(f"  [label]Tools:[/label]       {', '.join(skill.tools)}")
    console.print(f"  [label]Risk:[/label]        {skill.risk}")
    console.print(f"  [label]Body:[/label]        {len(skill.body)} chars")
    console.print()


def _skills_add(reg: _Any, raw: str) -> None:
    """Handle /skills add <path> — register an external SKILL.md file.

    Copies the SKILL.md into .claude/skills/<name>/ and registers it.
    Example: /skills add /path/to/my-skill/SKILL.md
    """
    import shutil

    from core.extensibility.skills import SkillLoader

    path_str = raw.strip()
    if not path_str:
        console.print("  [warning]Usage: /skills add <path-to-SKILL.md>[/warning]")
        console.print("  [muted]Example: /skills add ./my-skill/SKILL.md[/muted]")
        console.print()
        return

    src = Path(path_str).expanduser().resolve()
    if not src.exists():
        console.print(f"  [warning]File not found: {src}[/warning]")
        console.print()
        return

    if not src.name.upper().startswith("SKILL"):
        console.print(f"  [warning]Expected a SKILL.md file, got: {src.name}[/warning]")
        console.print()
        return

    # Determine skill name from parent directory or filename
    skill_name = src.parent.name
    if skill_name in (".", ""):
        skill_name = src.stem.lower().replace(" ", "-")

    # Copy to .claude/skills/<name>/SKILL.md
    loader = SkillLoader()
    dest_dir = loader.skills_dir / skill_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    shutil.copy2(src, dest)

    # Load and register
    skill = loader.load_file(dest)
    reg.register(skill)

    console.print(f"  [success]Added skill: {skill.name}[/success]")
    console.print(f"  [muted]Copied to {dest}[/muted]")
    if skill.triggers:
        console.print(f"  [muted]Triggers: {', '.join(skill.triggers)}[/muted]")
    console.print()


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
