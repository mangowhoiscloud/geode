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

    # Anthropic — Claude subscription OAuth path
    # (Policy retracted 2026-05-17: see PR #1202 + #B for the third-party
    # OAuth path verification; module docstring in
    # ``plugins.petri_audit.claude_code_provider`` carries the ToS
    # gray-area notice.)
    anthropic_ok = False
    try:
        from plugins.petri_audit.claude_code_provider import get_claude_oauth_metadata

        anthropic_meta = get_claude_oauth_metadata()
        if anthropic_meta:
            plan = anthropic_meta.get("subscription_type") or "(plan: unknown)"
            tier = anthropic_meta.get("rate_limit_tier")
            tier_label = f" · {tier}" if tier else ""
            _pkg.console.print(f"  [success]✓[/success] Anthropic  Claude {plan} OAuth{tier_label}")
            anthropic_ok = True
    except Exception:  # noqa: S110
        pass
    if not anthropic_ok:
        _pkg.console.print("  [error]✗[/error] Anthropic  [muted]not logged in[/muted]")
    providers.append({"name": "Anthropic", "cli": "claude", "ok": anthropic_ok})

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
        # Anthropic OAuth — policy retracted 2026-05-17 (see PR #1202 +
        # plugins.petri_audit.claude_code_provider module docstring).
        # We re-read the keychain blob via the same path the provider
        # uses, so the ProfileStore stays consistent with what
        # ``ClaudeOAuthAPI`` would resolve at audit time.
        from plugins.petri_audit.claude_code_provider import (
            get_claude_oauth_metadata,
            resolve_claude_oauth_token,
        )

        token = resolve_claude_oauth_token()
        if not token:
            return
        meta = get_claude_oauth_metadata() or {}
        expires = meta.get("expires_at")
        expires_seconds = float(expires) / 1000.0 if isinstance(expires, int | float) else 0.0
        profile = AuthProfile(
            name="anthropic:claude-code",
            provider="anthropic",
            credential_type=CredentialType.OAUTH,
            key=token,
            expires_at=expires_seconds,
            managed_by="claude-code",
        )
        store.add(profile)
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

    if arg.startswith("set"):
        set_args = arg[3:].strip()
        _cmd_auth_set(set_args)
        return

    _pkg.console.print(
        "  [warning]Usage: /auth [login|add|remove <name>|set <provider> <source>][/warning]"
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
