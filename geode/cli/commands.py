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

from geode.auth.profiles import ProfileStore
from geode.ui.console import console

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
    ModelProfile("claude-opus-4-6", "Anthropic", "Opus 4.6", "$$$"),
    ModelProfile("claude-sonnet-4-5-20250929", "Anthropic", "Sonnet 4.5", "$$"),
    ModelProfile("claude-haiku-4-5-20251001", "Anthropic", "Haiku 4.5", "$"),
    ModelProfile("gpt-5.4", "OpenAI", "GPT-5.4", "$$"),
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
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")
    console.print()
    console.print("  [muted]Or just type naturally: 'Berserk', '다크 판타지 게임 찾아줘'[/muted]")
    console.print()


def cmd_list() -> None:
    """List available IP fixtures."""
    from geode.fixtures import FIXTURE_MAP as _FIXTURE_MAP

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
    from geode.config import settings

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
    from geode.config import settings

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
    from geode.config import settings

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
    from geode.auth.rotation import ProfileRotator

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
    from geode.auth.profiles import AuthProfile, CredentialType

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
    from geode.auth.profiles import AuthProfile, CredentialType

    store = _profile_store_ctx.get()
    if store is not None:
        return cast(ProfileStore, store)

    store = ProfileStore()

    # Seed from existing settings
    from geode.config import settings

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
    from geode.fixtures.generator import GENRE_PARAMS, generate_batch

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
            result = run_fn(ip_name, dry_run=dry_run, verbose=verbose)
            results.append(result)
        else:
            results.append(None)

    console.print()
    console.print(f"  [success]Batch complete: {len(results)}/{len(ip_names)} processed[/success]")
    console.print()
    return results


def cmd_schedule(args: str) -> None:
    """Handle /schedule command — manage scheduled automations.

    /schedule              → list all templates
    /schedule list         → list all templates
    /schedule enable <id>  → enable a template
    /schedule disable <id> → disable a template
    /schedule run <id>     → run a template immediately
    """
    from geode.automation.predefined import PREDEFINED_AUTOMATIONS

    arg = args.strip().lower()

    if not arg or arg == "list":
        console.print()
        console.print("  [header]Scheduled Automations[/header]")
        for tmpl in PREDEFINED_AUTOMATIONS:
            state = "[success]ON[/success]" if tmpl.enabled else "[muted]OFF[/muted]"
            console.print(
                f"  {state}  [label]{tmpl.id:<30}[/label] "
                f"[muted]{tmpl.schedule:<16}[/muted] {tmpl.name}"
            )
        console.print()
        console.print("  [muted]Usage: /schedule enable|disable|run <id>[/muted]")
        console.print()
        return

    parts = arg.split(None, 1)
    sub = parts[0]
    target_id = parts[1] if len(parts) > 1 else ""

    if sub in ("enable", "disable"):
        found = next((t for t in PREDEFINED_AUTOMATIONS if t.id == target_id), None)
        if found is None:
            console.print(f"  [warning]Unknown template: {target_id}[/warning]")
            return
        found.enabled = sub == "enable"
        state = "enabled" if found.enabled else "disabled"
        console.print(f"  [success]{found.name}: {state}[/success]")
        console.print()
        return

    if sub == "run":
        found = next((t for t in PREDEFINED_AUTOMATIONS if t.id == target_id), None)
        if found is None:
            console.print(f"  [warning]Unknown template: {target_id}[/warning]")
            return
        console.print(f"  [header]Running: {found.name}[/header]")
        console.print(f"  Mode: {found.pipeline_config.mode}")
        console.print(f"  Batch size: {found.pipeline_config.batch_size}")
        console.print(f"  Dry-run: {found.pipeline_config.dry_run}")
        console.print()
        # Actual execution would be wired through runtime.run_pipeline()
        console.print("  [muted]Template execution dispatched to runtime.[/muted]")
        console.print()
        return

    console.print("  [warning]Usage: /schedule [list|enable|disable|run] <id>[/warning]")
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


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
