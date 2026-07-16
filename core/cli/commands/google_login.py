"""Google Workspace branch of the /login slash command."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from core.auth.google_oauth import (
    GOOGLE_SERVICE_BUNDLES,
    RECOMMENDED_GOOGLE_SERVICES,
    GoogleAccountStore,
    GoogleOAuthError,
    google_account_status,
    login_google,
    normalize_google_services,
    revoke_google_account,
)


def cmd_login_google(args: str) -> None:
    """Handle /login google login, status, account selection, and revoke."""
    from core.cli import commands as _pkg

    try:
        parts = shlex.split(args)
    except ValueError as exc:
        _pkg.console.print(f"  [warning]Invalid /login google arguments: {exc}[/warning]\n")
        return
    if parts and parts[0].lower() in ("help", "?"):
        _render_help()
        return
    if parts and parts[0].lower() in ("status", "accounts", "list", "ls"):
        render_google_status()
        return
    if parts and parts[0].lower() == "services":
        _render_services()
        return
    if parts and parts[0].lower() == "use":
        if len(parts) != 2:
            _pkg.console.print("  [warning]Usage: /login google use <email>[/warning]\n")
            return
        try:
            account = GoogleAccountStore().set_active(parts[1])
        except GoogleOAuthError as exc:
            _pkg.console.print(f"  [red]{exc}[/red]\n")
            return
        _pkg.console.print(f"  [success]Active Google account:[/success] {account.email}\n")
        return
    if parts and parts[0].lower() in ("logout", "remove", "revoke"):
        _logout_google(parts[1:])
        return
    _connect_google(parts)


def _connect_google(parts: list[str]) -> None:
    from core.cli import commands as _pkg

    client_json: Path | None = None
    services: tuple[str, ...] = ()
    services_explicit = False
    replace_services = False
    new_account = False
    timeout_s = 300.0
    index = 0
    try:
        while index < len(parts):
            arg = parts[index]
            if arg == "--client-json":
                index += 1
                client_json = Path(parts[index]).expanduser()
            elif arg.startswith("--client-json="):
                client_json = Path(arg.split("=", 1)[1]).expanduser()
            elif arg == "--services":
                index += 1
                services = normalize_google_services(parts[index].split(","))
                services_explicit = True
            elif arg.startswith("--services="):
                services = normalize_google_services(arg.split("=", 1)[1].split(","))
                services_explicit = True
            elif arg == "--timeout":
                index += 1
                timeout_s = float(parts[index])
            elif arg.startswith("--timeout="):
                timeout_s = float(arg.split("=", 1)[1])
            elif arg == "--replace-services":
                replace_services = True
            elif arg == "--new-account":
                new_account = True
            else:
                raise GoogleOAuthError(f"Unknown option: {arg}")
            index += 1
    except (IndexError, ValueError, GoogleOAuthError) as exc:
        _pkg.console.print(f"  [warning]{exc}[/warning]")
        _pkg.console.print(
            "  [muted]Usage: /login google --client-json PATH "
            "[--services gmail-send,calendar-read,...] [--new-account][/muted]\n"
        )
        return

    store = GoogleAccountStore()
    try:
        active = store.get_active()
    except GoogleOAuthError as exc:
        _pkg.console.print(f"  [red]Google account registry error: {exc}[/red]\n")
        return
    if client_json is None and not os.environ.get("GEODE_GOOGLE_CLIENT_JSON") and active is None:
        try:
            entered = _pkg.console.input(
                "  Google Desktop OAuth client JSON path "
                "[muted](created in Google Cloud Console)[/muted]: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _pkg.console.print("\n  [muted]Cancelled.[/muted]\n")
            return
        if not entered:
            _pkg.console.print("  [warning]Client JSON path is required.[/warning]\n")
            return
        client_json = Path(entered).expanduser()

    if not services_explicit:
        if active is not None and not new_account:
            services = active.services
        else:
            selected_services = _prompt_services()
            if selected_services is None:
                return
            services = selected_services

    effective_services = services
    if active is not None and not new_account and not replace_services:
        effective_services = normalize_google_services((*active.services, *services))
    selected = ", ".join(effective_services) if effective_services else "identity only"
    _pkg.console.print()
    _pkg.console.print("  [bold]Google Workspace OAuth[/bold]")
    _pkg.console.print(f"  [muted]Service bundles: {selected}[/muted]")
    if "gmail-read" in effective_services:
        _pkg.console.print(
            "  [warning]gmail-read is a Google Restricted scope. Public apps may "
            "require verification and a security assessment.[/warning]"
        )
    _pkg.console.print(
        "  [muted]A system browser will open. The callback listens only on "
        "127.0.0.1 with a random port and PKCE.[/muted]\n"
    )

    def announce(url: str) -> None:
        _pkg.console.print("  If the browser does not open, visit:")
        _pkg.console.print(f"  [link={url}]{url}[/link]\n")

    try:
        account = login_google(
            client_json=client_json,
            services=services,
            timeout_s=max(30.0, min(timeout_s, 900.0)),
            account_store=store,
            announce_url=announce,
            replace_services=replace_services,
            new_account=new_account,
        )
    except GoogleOAuthError as exc:
        _pkg.console.print(f"  [red]Google login failed: {exc}[/red]\n")
        return
    from core.mcp.google_workspace_client import reset_google_workspace_client

    reset_google_workspace_client()
    _pkg.console.print(
        f"  [success]Google account connected:[/success] {account.email}\n"
        f"  [muted]Metadata: {store.path} · secrets: OS keyring[/muted]\n"
    )


def _logout_google(parts: list[str]) -> None:
    from core.cli import commands as _pkg

    local_only = "--local-only" in parts
    targets = [part for part in parts if part != "--local-only"]
    if len(targets) > 1:
        _pkg.console.print(
            "  [warning]Usage: /login google logout [email] [--local-only][/warning]\n"
        )
        return
    try:
        removed = revoke_google_account(
            targets[0] if targets else None,
            local_only=local_only,
        )
    except GoogleOAuthError as exc:
        _pkg.console.print(f"  [red]Google logout failed: {exc}[/red]\n")
        return
    from core.mcp.google_workspace_client import reset_google_workspace_client

    reset_google_workspace_client()
    action = "Local credential removed" if local_only else "Google grant revoked"
    _pkg.console.print(f"  [success]{action}:[/success] {removed.email}\n")


def render_google_status() -> None:
    """Render non-secret account and scope-bundle status."""
    from core.cli import commands as _pkg

    try:
        rows = google_account_status()
    except GoogleOAuthError as exc:
        _pkg.console.print(f"  [red]Google account registry error: {exc}[/red]\n")
        return
    _pkg.console.print()
    _pkg.console.print("  [header]Google Workspace[/header]")
    if not rows:
        _pkg.console.print(
            "  [muted]No account connected. Run /login google --client-json PATH.[/muted]\n"
        )
        return
    for row in rows:
        marker = "[success]●[/success]" if row["active"] else "[muted]○[/muted]"
        services = ", ".join(row["services"]) or "identity"
        _pkg.console.print(
            f"  {marker} [bold]{row['email']}[/bold]  "
            f"[muted]{row['status']} · {services} · {len(row['granted_scopes'])} scopes[/muted]"
        )
    _pkg.console.print(
        "  [muted]Use /login google use <email> to switch · "
        "/login google logout [email] to revoke[/muted]\n"
    )


def _render_services() -> None:
    from core.cli import commands as _pkg

    _pkg.console.print()
    _pkg.console.print("  [header]Google service bundles[/header]")
    for name, bundle in GOOGLE_SERVICE_BUNDLES.items():
        default = " [success](recommended)[/success]" if name in RECOMMENDED_GOOGLE_SERVICES else ""
        _pkg.console.print(
            f"  [bold]{name:<18}[/bold] [muted]{bundle.risk:<14}[/muted] "
            f"{bundle.description}{default}"
        )
    _pkg.console.print(
        "\n  [muted]Add bundles with /login google --services a,b. Existing bundles "
        "are reauthorized as a union because installed-app incremental auth is "
        "unsupported.[/muted]\n"
    )


def _prompt_services() -> tuple[str, ...] | None:
    """Require an in-context bundle choice on the first connection."""
    from core.cli import commands as _pkg

    _pkg.console.print(
        "  [bold]Choose only the Google services you need.[/bold]\n"
        "  [muted]Recommended starting set: "
        f"{','.join(RECOMMENDED_GOOGLE_SERVICES)}[/muted]\n"
        "  [muted]Run /login google services for descriptions. "
        "You may enter recommended, all, or identity.[/muted]"
    )
    try:
        entered = _pkg.console.input("  Service bundles (comma-separated): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _pkg.console.print("\n  [muted]Cancelled.[/muted]\n")
        return None
    if not entered:
        _pkg.console.print("  [warning]No services selected; login cancelled.[/warning]\n")
        return None
    if entered == "recommended":
        return RECOMMENDED_GOOGLE_SERVICES
    if entered == "all":
        return normalize_google_services(tuple(GOOGLE_SERVICE_BUNDLES))
    if entered in ("identity", "identity-only"):
        return ()
    try:
        return normalize_google_services(entered.split(","))
    except GoogleOAuthError as exc:
        _pkg.console.print(f"  [warning]{exc}[/warning]\n")
        return None


def _render_help() -> None:
    from core.cli import commands as _pkg

    _pkg.console.print(
        "\n  [header]/login google[/header] — Google Workspace OAuth\n"
        "  [label]/login google --client-json PATH[/label] [--services a,b]\n"
        "      Import a user-owned Google Desktop OAuth client and connect an account.\n"
        "  [label]/login google --new-account[/label]      Connect another Google identity\n"
        "  [label]/login google status[/label]              Show accounts and granted bundles\n"
        "  [label]/login google services[/label]            List least-privilege bundles\n"
        "  [label]/login google use <email>[/label]         Switch the active account\n"
        "  [label]/login google logout [email][/label]      Revoke grant and delete local secret\n"
        "  [muted]Use --replace-services to request only the listed bundles instead of "
        "unioning them with the active account.[/muted]\n"
        "  [muted]The client JSON is read once. Refresh token and client secret go to "
        "the OS keyring; accounts.json contains metadata only.[/muted]\n"
    )
