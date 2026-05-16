"""``/auth`` slash command — auth profile management.

Hosts ``cmd_auth`` + the interactive ``add`` wizard. OAuth login flow
moved to ``/login <provider>`` (PR #B, 2026-05-17) — the legacy login
subcommand and its status/sync helpers were removed in the same change.
``/auth`` now surfaces:

- ``/auth``                       → profile rotator status
- ``/auth add``                   → interactive wizard (key / token)
- ``/auth remove <name>``         → delete a profile
- ``/auth set <prov> <source>``   → credential source picker (PR #1203)

Tests that monkeypatch ``core.cli.commands.console`` reach the call sites
here through the deferred ``import core.cli.commands as _pkg`` lookup,
mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging

from simple_term_menu import TerminalMenu

from core.auth.profiles import ProfileStore

log = logging.getLogger(__name__)


def cmd_auth(args: str) -> None:
    """Handle /auth command — manage auth profiles (OpenClaw Auth Profile UI pattern).

    /auth             → show profile status
    /auth add         → interactive add profile
    /auth remove <n>  → remove a profile
    """
    from core.auth.rotation import ProfileRotator
    from core.cli import commands as _pkg

    # Module-level singleton (lazy init)
    store = _pkg._get_profile_store()
    rotator = ProfileRotator(store)

    arg = args.strip()

    if not arg:
        # Show status
        statuses = rotator.get_status()
        if not statuses:
            _pkg.console.print()
            _pkg.console.print("  [muted]No auth profiles configured.[/muted]")
            _pkg.console.print(
                "  [muted]Use /login <provider> to set up OAuth,"
                " or /key <value> for API keys.[/muted]"
            )
            _pkg.console.print()
            return

        _pkg.console.print()
        _pkg.console.print("  [header]Auth Profiles[/header]")
        for s in statuses:
            icon = "✓" if s["status"] == "active" else "●" if "cooldown" in s["status"] else "✗"
            style = "success" if icon == "✓" else "warning" if icon == "●" else "error"
            # Build status suffix with subscription info for OAuth profiles
            status_text = s["status"]
            meta = s.get("metadata", {})
            sub_type = meta.get("subscription_type", "")
            if sub_type:
                sub_label = sub_type.capitalize()
                status_text = f"{status_text} · {sub_label}"
            managed = s.get("managed_by", "")
            if managed:
                status_text = f"{status_text} · managed:{managed}"
            _pkg.console.print(
                f"  [{style}]{icon}[/{style}] {s['name']:<22} "
                f"{s['type']:<10} {s['display']:<18} "
                f"[{style}]{status_text}[/{style}]"
            )
        _pkg.console.print()
        _pkg.console.print("  [muted]Priority: oauth > token > api_key[/muted]")
        # Hint if no OAuth profiles detected
        has_oauth = any(s["type"] == "oauth" for s in statuses)
        if not has_oauth:
            _pkg.console.print(
                "  [muted]Tip: /login <provider> to set up OAuth (saves API costs)[/muted]"
            )
        _pkg.console.print()
        return

    if arg.startswith("add"):
        add_args = arg[3:].strip()
        _auth_add_interactive(store, add_args)
        return

    if arg.startswith("remove"):
        name = arg[6:].strip()
        if not name:
            _pkg.console.print("  [warning]Usage: /auth remove <profile-name>[/warning]")
            return
        if store.remove(name):
            _pkg.console.print(f"  [success]Removed profile: {name}[/success]")
        else:
            _pkg.console.print(f"  [warning]Profile not found: {name}[/warning]")
        _pkg.console.print()
        return

    if arg.startswith("set"):
        set_args = arg[3:].strip()
        _cmd_auth_set(set_args)
        return

    _pkg.console.print(
        "  [warning]Usage: /auth [add|remove <name>|set <provider> <source>][/warning]"
    )
    _pkg.console.print(
        "  [muted]OAuth login lives at /login <provider> (PR #B, 2026-05-17).[/muted]"
    )
    _pkg.console.print()


_VALID_CREDENTIAL_SOURCES: tuple[str, ...] = ("auto", "oauth", "api_key", "none")
_VALID_CREDENTIAL_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")


def _format_credential_source_label(provider: str, source: str) -> str:
    """Human-readable label for the picker — pulls live subscription
    info from the credential blob rather than baking plan names in."""
    import os

    if source == "auto":
        return "auto-detect from env / keychain"
    if source == "none":
        return "disabled"
    if source == "api_key":
        env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        suffix = "(set)" if os.environ.get(env_var) else "(env not set)"
        return f"{env_var} {suffix}"
    if source == "oauth":
        if provider == "anthropic":
            try:
                from plugins.petri_audit.claude_code_provider import get_claude_oauth_metadata

                meta = get_claude_oauth_metadata()
            except ImportError:
                return "Claude subscription (audit extra not installed)"
            if meta is None:
                return "(no Claude credentials in keychain)"
            plan = meta.get("subscription_type") or "unknown plan"
            tier = meta.get("rate_limit_tier")
            tier_label = f" · {tier}" if tier else ""
            return f"Claude {plan}{tier_label}"
        try:
            from plugins.petri_audit.codex_provider import get_codex_oauth_metadata

            meta = get_codex_oauth_metadata()
        except ImportError:
            return "ChatGPT subscription (audit extra not installed)"
        if meta is None:
            return "(no Codex auth.json detected)"
        plan = meta.get("plan_type") or "unknown plan"
        return f"ChatGPT {plan}"
    return source


def _persist_credential_source(provider: str, source: str) -> None:
    """Persist the source choice — settings + .env + config.toml."""
    from core.cli import commands as _pkg
    from core.config import settings
    from core.utils.env_io import upsert_config_toml

    field = "anthropic_credential_source" if provider == "anthropic" else "openai_credential_source"
    env_var = (
        "GEODE_ANTHROPIC_CREDENTIAL_SOURCE"
        if provider == "anthropic"
        else "GEODE_OPENAI_CREDENTIAL_SOURCE"
    )
    try:
        object.__setattr__(settings, field, source)
    except Exception:
        log.debug("auth: settings.%s setattr failed", field, exc_info=True)
    _pkg._upsert_env(env_var, source)
    upsert_config_toml("llm", field, source)


def _cmd_auth_set(args: str) -> None:
    """``/auth set <provider> <source>`` — choose the credential source.

    Available providers: ``anthropic`` / ``openai``.
    Available sources:   ``auto`` (default) / ``oauth`` (subscription) /
                         ``api_key`` (PAYG env) / ``none`` (disabled).
    """
    from core.cli import commands as _pkg

    parts = args.split()
    if len(parts) != 2:
        _pkg.console.print("  [warning]Usage: /auth set <provider> <source>[/warning]")
        _pkg.console.print(
            f"  [muted]providers: {', '.join(_VALID_CREDENTIAL_PROVIDERS)}   "
            f"sources: {', '.join(_VALID_CREDENTIAL_SOURCES)}[/muted]"
        )
        _pkg.console.print()
        return
    provider, source = parts[0].lower(), parts[1].lower()
    if provider not in _VALID_CREDENTIAL_PROVIDERS:
        _pkg.console.print(
            f"  [warning]unknown provider: {provider} "
            f"(use one of {', '.join(_VALID_CREDENTIAL_PROVIDERS)})[/warning]"
        )
        _pkg.console.print()
        return
    if source not in _VALID_CREDENTIAL_SOURCES:
        _pkg.console.print(
            f"  [warning]unknown source: {source} "
            f"(use one of {', '.join(_VALID_CREDENTIAL_SOURCES)})[/warning]"
        )
        _pkg.console.print()
        return
    _persist_credential_source(provider, source)
    label = _format_credential_source_label(provider, source)
    _pkg.console.print(
        f"  [success]✓[/success] {provider} credential source → "
        f"[bold]{source}[/bold]  [muted]({label})[/muted]"
    )
    _pkg.console.print()


def _auth_add_interactive(store: ProfileStore, add_args: str) -> None:
    """Interactive auth profile addition."""
    import sys

    from core.cli import commands as _pkg

    if not sys.stdin.isatty():
        _pkg.console.print("  [warning]/auth add requires an interactive terminal.[/warning]")
        _pkg.console.print("  [muted]Use /key <provider> <value> to set API keys directly.[/muted]")
        _pkg.console.print()
        return

    from core.auth.profiles import AuthProfile, CredentialType

    # Level 1: Provider selection
    providers = ["anthropic", "openai", "glm"]
    entries = ["Anthropic", "OpenAI", "GLM"]

    menu = TerminalMenu(
        entries,
        title="\n  Provider  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        _pkg.console.print("  [muted]Cancelled[/muted]")
        _pkg.console.print()
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
        _pkg.console.print("  [muted]Cancelled[/muted]")
        _pkg.console.print()
        return

    cred_type = CredentialType.API_KEY if idx2 == 0 else CredentialType.TOKEN

    # Input: key value
    try:
        key = _pkg.console.input("  [label]Enter key:[/label] ").strip()
    except (KeyboardInterrupt, EOFError):
        _pkg.console.print("\n  [muted]Cancelled[/muted]")
        _pkg.console.print()
        return

    if not key:
        _pkg.console.print("  [warning]No key provided.[/warning]")
        _pkg.console.print()
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
    _pkg.console.print(f"  [success]Added profile: {name}[/success]  {profile.masked_key}")
    _pkg.console.print()
