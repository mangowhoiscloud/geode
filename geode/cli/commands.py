"""Slash command dispatch — extracted from CLI REPL.

OpenClaw-inspired Binding Router pattern: static command → handler mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from simple_term_menu import TerminalMenu

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
    ModelProfile("gpt-5.3", "OpenAI", "GPT-5.3", "$$$"),
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
    console.print("  [label]/help[/label]               — Show this help")
    console.print("  [label]/quit[/label]               — Exit GEODE")
    console.print()
    console.print("  [muted]Or just type naturally: 'Berserk', '다크 판타지 게임 찾아줘'[/muted]")
    console.print()


def cmd_list() -> None:
    """List available IP fixtures."""
    from geode.nodes.cortex import _FIXTURE_MAP

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
    /model gpt-5.3 → select by name
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


def _auth_add_interactive(store, add_args: str) -> None:
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


# Module-level profile store singleton
_profile_store: object | None = None  # ProfileStore (lazy import)


def _get_profile_store():
    """Get or create the module-level profile store, seeded from settings."""
    from geode.auth.profiles import AuthProfile, CredentialType, ProfileStore

    global _profile_store  # noqa: PLW0603
    if _profile_store is not None:
        return _profile_store

    _profile_store = ProfileStore()

    # Seed from existing settings
    from geode.config import settings

    if settings.anthropic_api_key:
        _profile_store.add(
            AuthProfile(
                name="anthropic:default",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key=settings.anthropic_api_key,
            )
        )
    if settings.openai_api_key:
        _profile_store.add(
            AuthProfile(
                name="openai:default",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key=settings.openai_api_key,
            )
        )
    return _profile_store


def cmd_generate(args: str) -> None:
    """Handle /generate command — create synthetic demo data.

    /generate         → generate 5 IPs
    /generate 10      → generate 10 IPs
    /generate 3 mecha → generate 3 IPs of specific genre
    """
    from geode.data.generator import GENRE_PARAMS, generate_batch

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


def resolve_action(cmd: str) -> str | None:
    """Resolve a slash command to its action name. Returns None if unknown."""
    return COMMAND_MAP.get(cmd)
