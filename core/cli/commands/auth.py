"""``/auth`` slash command — auth profile rotator (legacy entry point).

Hosts ``cmd_auth`` and the OAuth-status / interactive-add helpers used by
the legacy auth UI; ``/login`` is the v0.50+ unified replacement but the
``/auth`` subcommand surface remains addressable. Extracted from the
monolithic ``core/cli/commands.py`` (Tier 3 #9) — every function body is
preserved byte-identical from the legacy module.

Tests that monkeypatch ``core.cli.commands.console`` reach the call sites
here through the deferred ``import core.cli.commands as _pkg`` lookup,
mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging

from simple_term_menu import TerminalMenu

from core.auth.profiles import ProfileStore

log = logging.getLogger(__name__)


def _auth_login_status() -> None:
    """Show OAuth status + offer interactive login for missing providers."""
    import shutil
    import subprocess  # nosec B404

    from core.cli import commands as _pkg

    _pkg.console.print()
    _pkg.console.print("  [header]OAuth Login Status[/header]")

    # -- Check current status --
    providers: list[dict[str, str | bool]] = []

    # Anthropic — OAuth disabled (ToS violation since 2026-01-09)
    _pkg.console.print(
        "  [muted]—[/muted] Anthropic  [muted]OAuth disabled (ToS — API key only)[/muted]"
    )
    providers.append({"name": "Anthropic", "cli": "claude", "ok": True})  # skip login prompt

    # OpenAI
    codex_ok = False
    try:
        from core.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_creds = read_codex_cli_credentials(force_refresh=True)
        if codex_creds:
            acct = codex_creds.get("account_id", "unknown")[:12]
            _pkg.console.print(
                f"  [success]✓[/success] OpenAI     Codex CLI OAuth (account: {acct}...)"
            )
            codex_ok = True
    except Exception:  # noqa: S110
        pass
    if not codex_ok:
        _pkg.console.print("  [error]✗[/error] OpenAI     [muted]not logged in[/muted]")
    providers.append({"name": "OpenAI", "cli": "codex", "ok": codex_ok})

    # -- Offer interactive login for missing providers --
    missing = [p for p in providers if not p["ok"]]
    if not missing:
        _pkg.console.print()
        _pkg.console.print("  [success]All providers authenticated via OAuth.[/success]")
        _pkg.console.print()
        return

    _pkg.console.print()
    for p in missing:
        cli_name = str(p["cli"])
        cli_path = shutil.which(cli_name)
        if not cli_path:
            _pkg.console.print(
                f"  [muted]{p['name']}:[/muted]  "
                f"[warning]{cli_name} CLI not installed[/warning]  "
                f"[muted](install then run /auth login)[/muted]"
            )
            continue

        _pkg.console.print(
            f"  [muted]{p['name']}:[/muted]  "
            f"[bold]{cli_name} login[/bold] — "
            f"opens browser for OAuth"
        )
        try:
            resp = (
                _pkg.console.input(f"  [header]Run {cli_name} login now? [Y/n][/header] ")
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            _pkg.console.print()
            continue

        if resp in ("n", "no"):
            continue

        _pkg.console.print(f"  [muted]Opening browser for {p['name']} login...[/muted]")
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                [cli_path, "login"],
                timeout=120,
            )
            if result.returncode == 0:
                _pkg.console.print(f"  [success]{p['name']} login successful![/success]")
                # Re-read credentials + update ProfileStore
                _sync_oauth_profile_after_login(cli_name)
            else:
                _pkg.console.print(
                    f"  [warning]{p['name']} login failed (exit code {result.returncode})[/warning]"
                )
        except subprocess.TimeoutExpired:
            _pkg.console.print(f"  [warning]{p['name']} login timed out (120s)[/warning]")
        except OSError as exc:
            _pkg.console.print(f"  [warning]{p['name']} login error: {exc}[/warning]")

    _pkg.console.print()


def _sync_oauth_profile_after_login(cli_name: str) -> None:
    """Re-read OAuth credentials and update ProfileStore after login."""
    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg

    store = _pkg._get_profile_store()

    if cli_name == "claude":
        # Anthropic OAuth disabled — ToS prohibits third-party use
        return

    if cli_name == "codex":
        from core.auth.codex_cli_oauth import (
            invalidate_cache as codex_invalidate,
        )
        from core.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_invalidate()
        codex_creds = read_codex_cli_credentials(force_refresh=True)
        if codex_creds:
            profile = AuthProfile(
                name="openai-codex:codex-cli",
                provider="openai-codex",
                credential_type=CredentialType.OAUTH,
                key=codex_creds["access_token"],
                refresh_token=codex_creds.get("refresh_token", ""),
                expires_at=codex_creds.get("expires_at", 0.0),
                managed_by="codex-cli",
            )
            store.add(profile)


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
                "  [muted]Use /auth login to check OAuth status,"
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
                "  [muted]Tip: /auth login to set up OAuth (saves API costs)[/muted]"
            )
        _pkg.console.print()
        return

    if arg.startswith("login"):
        _auth_login_status()
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

    _pkg.console.print("  [warning]Usage: /auth [login|add|remove <name>][/warning]")
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
