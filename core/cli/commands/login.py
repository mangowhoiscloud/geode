"""``/login`` slash command — unified credentials/plans command (v0.50.0+).

Hosts ``cmd_login`` plus the ``_login_*`` subcommand helpers (
``_login_help``, ``_login_show_status``, ``_login_add_interactive``,
``_login_oauth``, ``_login_set_key``, ``_login_use``, ``_login_remove``,
``_login_route``, ``_login_quota``). Extracted from the monolithic
``core/cli/commands.py`` (Tier 3 #9) — every function body is preserved
byte-identical from the legacy module.

Tests that monkeypatch ``core.cli.commands.console`` /
``core.cli.commands._upsert_env`` / ``core.cli.commands._mask_key`` reach
the call sites here through the deferred ``import core.cli.commands as
_pkg`` lookup, mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, TypedDict

from simple_term_menu import TerminalMenu

from core.auth.profiles import AuthProfile
from core.cli.onboarding import clear_dry_run_opt_in

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.cli.ipc_client import IPCClient
    from core.config import Settings
    from core.config.policy_source import PolicySourcePaths
    from core.config.session import SessionModelConfig


_VALID_CREDENTIAL_SOURCES: tuple[str, ...] = (
    "auto",
    "oauth",
    "api_key",
    "openai-codex",
    "none",
)
_VALID_CREDENTIAL_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")


_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "codex": "openai",
    "chatgpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
}
"""User-facing provider names → canonical key. Accepts both the marketing
name (``chatgpt``, ``claude``) and the maintained Codex source alias."""


def cmd_login(args: str, *, client: IPCClient | None = None) -> bool:
    """Handle /login — unified credentials/plans command.

    Parameter shape: ``/login [<provider>|<subcommand>]``. OpenAI runs the
    device-code login flow; Anthropic opens API-key setup.

    Providers (case-insensitive, aliases accepted)::

        /login openai      — ChatGPT subscription device-code flow (aliases: codex, chatgpt)
        /login anthropic   — Anthropic API-key setup (alias: claude)

    Subcommands::

        /login                — show plans, profiles, routing, declared quotas
        /login add            — interactive wizard (kind → provider → key/OAuth)
        /login set-key <plan> <key>
        /login use <plan>     — pin a plan as the active one for its provider
        /login remove <plan>
        /login route <model> <plan> [<plan>...]
        /login quota          — declared per-plan call limits
        /login health [<profile>] — eligibility verdict + actionable suggestion
        /login status         — legacy alias of bare /login
    """
    from rich.markup import escape

    from core.cli import commands as _pkg

    try:
        run_login(args, client=client)
    except ValueError as exc:
        _pkg.console.print(f"  [warning]{escape(str(exc))}[/warning]\n")
    except OSError as exc:
        _pkg.console.print(f"  [error]Credential change not saved: {escape(str(exc))}[/error]\n")
    else:
        return True
    return False


# Views and nonsecret changes of daemon-owned state; a thin client relays only
# these, so terminal input and anything else it cannot classify stay local.
DAEMON_LOGIN_SUBCOMMANDS = frozenset(
    {
        *("status", "list", "ls", "quota", "health", "providers", "provider"),
        *("use", "use-profile", "useprofile", "profile-use", "order", "route"),
        *("remove", "rm", "delete", "refresh", "help", "?"),
    }
)
# Flows that read keys or wait for a browser in the user's terminal.
INTERACTIVE_LOGIN_SUBCOMMANDS = frozenset({"add", "new", "google", *_PROVIDER_ALIASES})


def run_login(args: str, *, client: IPCClient | None = None) -> None:
    """Dispatch one /login request; invalid requests and failed writes raise."""
    raw = args.strip()
    if not raw:
        _login_show_status()
        return

    parts = raw.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "google":
        from core.cli.commands.google_login import cmd_login_google

        cmd_login_google(rest)
        return

    # Provider-as-parameter dispatch: ``/login openai`` /
    # ``/login anthropic`` (+ aliases) select the provider route. This
    # path is reached before any subcommand match so a provider name and
    # a subcommand never collide in practice — providers live in
    # ``_PROVIDER_ALIASES``, subcommands are checked below.
    if sub in _PROVIDER_ALIASES:
        _login_oauth(_PROVIDER_ALIASES[sub])
        return

    if sub in ("status", "list", "ls"):
        if rest.strip().lower() == "google":
            from core.cli.commands.google_login import render_google_status

            render_google_status()
            return
        _login_show_status()
        return
    if sub in ("add", "new"):
        _login_add_interactive(rest)
        return
    if sub in ("set-key", "setkey", "key"):
        _login_set_key(rest)
        return
    if sub == "use":
        _login_use(rest)
        return
    if sub in ("use-profile", "useprofile", "profile-use"):
        _login_use_profile(rest)
        return
    if sub == "order":
        _login_order(rest)
        return
    if sub in ("remove", "rm", "delete"):
        _login_remove(rest)
        return
    if sub == "route":
        _login_route(rest)
        return
    if sub == "quota":
        _login_quota()
        return
    if sub == "health":
        _login_health(rest)
        return
    if sub in ("providers", "provider"):
        _login_providers()
        return
    if sub == "source":
        _login_source(rest, client=client)
        return
    if sub == "refresh":
        from core.cli import commands as _pkg

        _pkg.console.print(reload_auth_state())
        return
    if sub in ("help", "?"):
        _login_help()
        return
    raise ValueError(f"Unknown /login subcommand: {sub}. Run /login help for the full menu.")


def reload_auth_state() -> str:
    """Adopt the current auth.toml in this process and describe what changed.

    Thin clients write credentials locally and send this value-free signal.
    The reload validates the whole file and replaces only its owned entries,
    retaining managed/environment objects and in-flight borrowed references.
    A rejected file raises and leaves the live state unchanged; with no file
    there is nothing to adopt.
    """
    from core.auth.auth_toml import auth_toml_path, load_auth_toml
    from core.auth.codex_cli_oauth import invalidate_cache as invalidate_codex_cli_cache
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.mcp.google_workspace_client import reset_google_workspace_client
    from core.wiring.container import ensure_profile_store

    registry = get_plan_registry()
    store = ensure_profile_store()
    plans_before = {p.id for p in registry.list_all()}
    profiles_before = {p.name for p in store.list_all()}
    if auth_toml_path().exists() and not load_auth_toml():
        raise ValueError(
            f"auth.toml reload failed ({auth_toml_path()}); the previous credentials remain active"
        )
    # Imported Codex and Google credentials live outside auth.toml; drop their
    # caches even when there is no file to adopt, but not after a rejection.
    invalidate_codex_cli_cache()
    reset_google_workspace_client()
    plans_after = {p.id for p in registry.list_all()}
    profiles_after = {p.name for p in store.list_all()}
    changes = [
        *(f"+ plan {name}" for name in sorted(plans_after - plans_before)),
        *(f"- plan {name}" for name in sorted(plans_before - plans_after)),
        *(f"+ profile {name}" for name in sorted(profiles_after - profiles_before)),
        *(f"- profile {name}" for name in sorted(profiles_before - profiles_after)),
    ]
    log.info(
        "auth.toml reload: file=%s plans=%d profiles=%d changes=%s",
        auth_toml_path(),
        len(plans_after),
        len(profiles_after),
        changes,
    )
    lines = [
        f"  [success]auth.toml reloaded[/success]  "
        f"[muted]{len(plans_after)} plans, {len(profiles_after)} profiles[/muted]",
        *(f"    [muted]{change}[/muted]" for change in changes),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# /login subcommands — implementation
# ---------------------------------------------------------------------------


def _login_help() -> None:
    from core.cli import commands as _pkg

    _pkg.console.print(
        "\n  [header]/login[/header] — credentials & subscription plans\n"
        "\n"
        "  [label]/login[/label]                       Show all plans, profiles, routing\n"
        "  [label]/login openai[/label]                OAuth flow (ChatGPT subscription quota)\n"
        "  [label]/login anthropic[/label]             Explain Anthropic API-key setup\n"
        "  [label]/login google[/label]                Google Workspace OAuth (BYO client)\n"
        "  [label]/login add[/label]                   Interactive wizard\n"
        "  [label]/login source[/label] <prov> <type>   Pick credential source per provider\n"
        "  [label]/login set-key[/label] <plan> <key>  Update a plan's API key\n"
        "  [label]/login use[/label] <plan>            Pin a plan as active for its provider\n"
        "  [label]/login use-profile[/label] <name>    Pin a profile as active for its provider\n"
        "  [label]/login order[/label] [<provider>]    Show effective profile order per provider\n"
        "  [label]/login order set[/label] <prov> <n1> <n2>…  Pin multi-rank auth order\n"
        "  [label]/login order clear[/label] <prov>    Drop the multi-rank pin\n"
        "  [label]/login route[/label] <model> <plan>… Bind a model to plan(s) in priority order\n"
        "  [label]/login remove[/label] <plan>         Delete a plan\n"
        "  [label]/login quota[/label]                 Declared per-plan call limits\n"
        "  [label]/login health[/label] [<profile>]    Eligibility verdict per profile\n"
        "  [label]/login providers[/label]             Provider variants + equivalence map\n"
        "\n"
        "  [muted]Eligibility verdicts (shown next to each profile in /login):[/muted]\n"
        "  [muted]  ok               — profile passes every check, ready to dispatch[/muted]\n"
        "  [muted]  missing_key      — key/token field is empty; rerun add or set-key[/muted]\n"
        "  [muted]  expired          — OAuth token past expires_at; refresh via the[/muted]\n"
        "  [muted]                     owning CLI (`codex`) and rerun /login[/muted]\n"
        "  [muted]  cooling_down     — consecutive failures tripped backoff; wait for[/muted]\n"
        "  [muted]                     cooldown or run /login health <profile> for ETA[/muted]\n"
        "  [muted]  disabled         — manually disabled (`/login remove` to delete)[/muted]\n"
        "  [muted]  provider_mismatch — not for the queried provider (info only)[/muted]\n"
    )


def _format_plan_binding(registry: Any, plan_id: str) -> str:
    """Render a profile's plan binding as ``<id> (<kind>·<tier or display>)``.

    L3 — pre-fix the ``Profiles`` table only printed ``plan=<id>``, so a
    user looking at ``glm:work`` saw ``plan=glm-coding-lite`` without
    knowing it was a subscription plan vs PAYG, or what tier it belonged
    to. This helper resolves the binding through ``PlanRegistry.get``
    and appends ``kind``, ``display_name`` (when meaningful), and
    ``subscription_tier`` so the row carries the full link.
    Falls back to the bare ``id`` if the plan vanished and to
    ``(none)`` when the profile has no ``plan_id`` set.
    """
    if not plan_id:
        return "[muted](none)[/muted]"
    plan = registry.get(plan_id)
    if plan is None:
        return f"{plan_id} [muted](unbound)[/muted]"
    kind = plan.kind.value
    tier = getattr(plan, "subscription_tier", None)
    if getattr(plan, "provider", "") == "openai-codex":
        from core.auth.oauth_login import chatgpt_plan_label

        tier = chatgpt_plan_label(tier)
    tier_suffix = f"·{tier}" if tier else ""
    display = getattr(plan, "display_name", "") or plan_id
    return f"[bold]{plan_id}[/bold] [muted]({kind}{tier_suffix} · {display})[/muted]"


class LoginQuota(TypedDict):
    """A plan's declared call limit; GEODE does not count calls against it."""

    max_calls: int
    window_s: int


class LoginPlanRow(TypedDict):
    id: str
    provider: str
    kind: str
    display_name: str
    base_url: str
    subscription_tier: str | None
    quota: LoginQuota | None


class LoginProfileRow(TypedDict):
    """One credential without key material; ``expires_at`` is None when it never expires."""

    name: str
    provider: str
    type: str
    plan_id: str | None
    managed_by: str | None
    active: bool
    eligible: bool
    reason: str
    reason_detail: str
    expires_at: float | None


class LoginSnapshot(TypedDict):
    plans: list[LoginPlanRow]
    profiles: list[LoginProfileRow]
    routing: dict[str, list[str]]


def build_login_snapshot() -> LoginSnapshot:
    """Build the nonsecret plan, profile and routing state every /login view reports.

    The dashboard, ``/login health`` and the ``manage_login`` tool render this
    one result; each profile carries its verdict against its own provider.
    """
    from core.auth.profiles import ProfileRejectReason
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()
    registry = get_plan_registry()
    profiles = store.list_all()
    providers = {profile.provider for profile in profiles}
    verdicts = {
        verdict.profile_name: verdict
        for provider in providers
        for verdict in store.evaluate_eligibility(provider)
        if verdict.reason is not ProfileRejectReason.PROVIDER_MISMATCH
    }
    pinned = {
        provider: pin.name
        for provider in providers
        if (pin := store.get_pinned_active(provider)) is not None
    }
    profile_rows: list[LoginProfileRow] = []
    for profile in profiles:
        verdict = verdicts.get(profile.name)
        profile_rows.append(
            {
                "name": profile.name,
                "provider": profile.provider,
                "type": profile.credential_type.value,
                "plan_id": profile.plan_id or None,
                "managed_by": profile.managed_by or None,
                "active": pinned.get(profile.provider) == profile.name,
                "eligible": verdict.eligible if verdict else False,
                "reason": verdict.reason_code if verdict else "unknown",
                "reason_detail": verdict.detail if verdict else "",
                "expires_at": profile.expires_at if profile.expires_at > 0 else None,
            }
        )
    return {
        "plans": [
            {
                "id": plan.id,
                "provider": plan.provider,
                "kind": plan.kind.value,
                "display_name": plan.display_name,
                "base_url": plan.base_url,
                "subscription_tier": plan.subscription_tier,
                "quota": (
                    {"max_calls": plan.quota.max_calls, "window_s": plan.quota.window_s}
                    if plan.quota is not None
                    else None
                ),
            }
            for plan in registry.list_all()
        ],
        "profiles": profile_rows,
        "routing": registry.all_routing(),
    }


def _login_show_status() -> None:
    """Render the login snapshot plus Google Workspace accounts.

    Combines OpenClaw `/status` (auth-mode badge), Hermes `hermes status`
    (per-provider expiry + subscription line), and Claude Code Settings
    Status tab (plan + token source + provider).
    """
    import time

    from core.auth.oauth_login import chatgpt_plan_label
    from core.cli import commands as _pkg
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring.container import ensure_profile_store

    snapshot = build_login_snapshot()
    plans, profiles = snapshot["plans"], snapshot["profiles"]
    try:
        from core.auth.google_oauth import google_account_status

        google_accounts = google_account_status()
    except Exception:
        google_accounts = []

    _pkg.console.print()
    _pkg.console.print("  [header]Plans[/header]")
    if not plans and not profiles and not google_accounts:
        _pkg.console.print("  [muted]No plans or credentials registered yet.[/muted]")
        _pkg.console.print(
            "  [muted]Run /login add to register a plan, or paste an API key.[/muted]"
        )
        _pkg.console.print()
        return

    for plan in plans:
        tier = plan["subscription_tier"]
        if plan["provider"] == "openai-codex":
            tier = chatgpt_plan_label(tier)
        tier_label = f" · {tier}" if tier else ""
        quota = plan["quota"]
        quota_label = ""
        if quota is not None:
            hours = quota["window_s"] // 3600
            quota_label = f"  [muted]quota {quota['max_calls']} calls / {hours}h window[/muted]"
        bound = any(p["plan_id"] == plan["id"] for p in profiles)
        mark = "[success]✓[/success]" if bound else "[warning]?[/warning]"
        _pkg.console.print(
            f"  {mark} [bold]{plan['id']}[/bold]  "
            f"[muted]{plan['kind']}[/muted]  {plan['base_url']}{tier_label}{quota_label}"
        )
    if not plans:
        _pkg.console.print(
            "  [muted]No Plans registered. Profiles below run via PAYG defaults.[/muted]"
        )
    _pkg.console.print()

    # Profiles section — aggregates env-loaded keys + interactively added
    _pkg.console.print("  [header]Profiles[/header]")
    if not profiles:
        _pkg.console.print(
            "  [muted]No credentials. Run /login add or set provider env vars.[/muted]"
        )
    registry = get_plan_registry()
    masked_keys = {p.name: p.masked_key for p in ensure_profile_store().list_all()}
    badges = {"oauth": "oauth", "token": "token", "api_key": "api-key"}
    # Sorting by provider keeps each provider's registration order.
    for p in sorted(profiles, key=lambda row: row["provider"]):
        # L3 — surface Plan binding detail (display_name + kind +
        # subscription_tier) so an OAuth profile row says *what
        # subscription* it talks to instead of just an opaque plan id.
        plan_label = _format_plan_binding(registry, p["plan_id"] or "")
        managed = f" · managed:{p['managed_by']}" if p["managed_by"] else ""
        expiry = ""
        if p["expires_at"] is not None:
            rem = int(p["expires_at"] - time.time())
            expiry = f" · expires {rem // 60}m" if rem > 0 else " · [error]expired[/error]"
        if p["eligible"]:
            badge_str = "[success]✓[/success]"
        else:
            badge_str = f"[warning]✗ {p['reason']}[/warning]"
            if p["reason_detail"]:
                badge_str += f" [muted]({p['reason_detail']})[/muted]"
        # X1 — mark the pinned profile a call picks first for its provider.
        active_suffix = " [success](active)[/success]" if p["active"] else ""
        _pkg.console.print(
            f"  {badge_str}  {p['name']:<28}{active_suffix} "
            f"[muted]{badges.get(p['type'], '?'):<7}[/muted] {masked_keys.get(p['name'], '')} "
            f"plan={plan_label}{managed}{expiry}"
        )
    _pkg.console.print()

    routing = snapshot["routing"]
    if routing:
        _pkg.console.print("  [header]Routing[/header]")
        for model, plan_ids in sorted(routing.items()):
            chain = " → ".join(plan_ids) if plan_ids else "[muted](none)[/muted]"
            _pkg.console.print(f"  {model:<24} → {chain}")
        _pkg.console.print()

    if google_accounts:
        _pkg.console.print("  [header]Google Workspace[/header]")
        for account in google_accounts:
            marker = "[success]●[/success]" if account["active"] else "[muted]○[/muted]"
            bundles = ", ".join(account["services"]) or "identity"
            _pkg.console.print(
                f"  {marker} {account['email']:<28} "
                f"[muted]{bundles} · {len(account['granted_scopes'])} scopes[/muted]"
            )
        _pkg.console.print()

    _pkg.console.print(
        "  [muted]Tip: /login add to register a plan · "
        "/login health for credential detail[/muted]\n"
    )


def _login_add_interactive(_args: str) -> None:
    """Interactive wizard — Plan kind → Provider → endpoint/key/OAuth.

    Mirrors OpenClaw setup wizard (`prompter.select` levels) collapsed
    into a single CLI command so existing users can run it any time.
    """
    import sys

    from core.auth.auth_toml import auth_file_transaction
    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg
    from core.llm.strategies.plans import default_plan_for_payg

    if not sys.stdin.isatty():
        raise ValueError(
            "/login add requires an interactive terminal. Set keys via env vars "
            "(ZAI_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY) "
            "for non-interactive setup."
        )

    kinds = [
        (
            "subscription",
            "ChatGPT subscription (Codex sign-in)",
        ),
        ("payg", "Pay-as-you-go API key (Anthropic, OpenAI, OpenRouter, GLM PAYG)"),
        ("oauth", "OAuth borrowed (Codex CLI)"),
    ]
    menu = TerminalMenu(
        [label for _, label in kinds],
        title="\n  Plan kind?  (↑↓ select, Enter confirm, q cancel)\n",
        menu_cursor="  > ",
        menu_cursor_style=("fg_cyan", "bold"),
    )
    idx = menu.show()
    if idx is None:
        _pkg.console.print("  [muted]Cancelled[/muted]\n")
        return
    kind_id = kinds[idx][0]

    if kind_id == "subscription":
        _login_oauth("openai")
        return

    if kind_id == "payg":
        providers = [
            ("anthropic", "Anthropic"),
            ("openai", "OpenAI"),
            ("openrouter", "OpenRouter"),
            ("glm", "GLM (z.ai PAYG)"),
        ]
        pmenu = TerminalMenu(
            [label for _, label in providers],
            title="\n  Provider?\n",
            menu_cursor="  > ",
        )
        pidx = pmenu.show()
        if pidx is None:
            _pkg.console.print("  [muted]Cancelled[/muted]\n")
            return
        provider = providers[pidx][0]
        try:
            key = _pkg.console.input(f"  [label]{providers[pidx][1]} API key:[/label] ").strip()
        except (KeyboardInterrupt, EOFError):
            _pkg.console.print("\n  [muted]Cancelled[/muted]\n")
            return
        if not key:
            _pkg.console.print("  [warning]No key provided.[/warning]\n")
            return
        plan = default_plan_for_payg(provider, key)
        with auth_file_transaction() as (registry, store):
            registry.add(plan)
            store.add(
                AuthProfile(
                    name=f"{plan.id}:user",
                    provider=provider,
                    credential_type=CredentialType.API_KEY,
                    key=key,
                    plan_id=plan.id,
                ),
                activate=True,
            )
        # Mirror to settings + .env so legacy fallbacks keep working
        from core.config import settings

        env_field_map = {
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "openrouter": ("openrouter_api_key", "OPENROUTER_API_KEY"),
            "glm": ("zai_api_key", "ZAI_API_KEY"),
        }
        if provider in env_field_map:
            field_name, env_var = env_field_map[provider]
            object.__setattr__(settings, field_name, key)
            _pkg._upsert_env(env_var, key)
        clear_dry_run_opt_in()
        _pkg.console.print(
            f"  [success]Registered[/success] {plan.display_name}  "
            f"[muted](key {_pkg._mask_key(key)})[/muted]\n"
        )
        return

    if kind_id == "oauth":
        _login_oauth("openai")
        return


def _login_oauth(target: str) -> None:
    """Activate a subscription provider's supported credential route.

    ``target`` is the canonical key (``openai`` / ``anthropic``) — the
    caller has already resolved aliases via :data:`_PROVIDER_ALIASES`.
    Each branch is responsible for the provider-specific flow:

    - ``openai``: GEODE-native device-code flow (ChatGPT subscription quota).
    - ``anthropic``: prompt for a PAYG API key.
    """
    from core.cli import commands as _pkg

    target = target.lower().strip()
    if target == "openai":
        from core.auth.oauth_login import login_openai
        from core.llm.adapters.registry import invalidate_provider_clients

        _pkg.console.print()
        try:
            creds = login_openai()
        except (ValueError, OSError):
            raise  # Rejected or unsaved credential; cmd_login reports it.
        except Exception as exc:
            # External device-code payloads can fail in any shape; report the
            # cause and keep the REPL alive rather than exiting on it.
            raise ValueError(f"Login failed: {exc}") from exc
        if not creds:
            raise ValueError("ChatGPT login cancelled; no credential was saved")
        invalidate_provider_clients("openai")
        clear_dry_run_opt_in()
        _pkg.console.print(
            "  [success]ChatGPT subscription OAuth registered.[/success]  "
            "[muted]Provider: openai-codex[/muted]\n"
        )
        return

    if target == "anthropic":
        _login_anthropic_api_key()
        return

    raise ValueError(
        f"OAuth not implemented for '{target}'. "
        "Available: openai (ChatGPT subscription), anthropic (API key)"
    )


def _format_credential_source_label(provider: str, source: str) -> str:
    """Human-readable label for the ``source`` picker — pulls live
    subscription info from provider-owned state rather than baking
    plan names into the code."""
    import os

    if source == "auto":
        return "auto-detect from configured credentials"
    if source == "none":
        return "disabled"
    if source == "api_key":
        env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        suffix = "(set)" if os.environ.get(env_var) else "(env not set)"
        return f"{env_var} {suffix}"
    if source in ("oauth", "openai-codex"):
        from core.llm.providers.codex import get_codex_oauth_metadata

        meta = get_codex_oauth_metadata()
        if meta is None:
            return "(no Codex auth.json detected)"
        from core.auth.oauth_login import chatgpt_plan_label

        plan_type = meta.get("plan_type")
        return chatgpt_plan_label(plan_type if isinstance(plan_type, str) else None)
    return source


def _persist_credential_source(provider: str, source: str) -> None:
    """Persist future defaults in TOML and remove obsolete behavior env keys."""
    from core.cli import commands as _pkg
    from core.config import settings
    from core.config.env_io import upsert_config_toml

    field = "anthropic_credential_source" if provider == "anthropic" else "openai_credential_source"
    env_var = (
        "GEODE_ANTHROPIC_CREDENTIAL_SOURCE"
        if provider == "anthropic"
        else "GEODE_OPENAI_CREDENTIAL_SOURCE"
    )
    # C-2 (2026-06-11) — credential_source is a behavior setting, not a
    # secret: toml-only (the toml row is now READ — registered in
    # _TOML_TO_SETTINGS, closing hazard H7's dead write). Stale env lines
    # from earlier releases are cleaned so they stop masking the toml.
    upsert_config_toml("llm", field, source)
    object.__setattr__(settings, field, source)
    if _pkg.remove_env(env_var):
        _pkg.console.print(
            f"  [muted]removed stale {env_var} from .env — config.toml is the durable layer[/muted]"
        )


def session_source_changes(
    config: SessionModelConfig,
    provider: str,
    credential_source: str,
    *,
    settings: Settings | None = None,
    sources: PolicySourcePaths | None = None,
) -> dict[str, Any]:
    """Build a source-only candidate; the caller owns admission and persistence."""
    from core.config import _resolve_provider
    from core.llm.adapters.registry import normalize_registry_provider
    from core.llm.routing import infer_source

    if provider not in _VALID_CREDENTIAL_PROVIDERS:
        raise ValueError(f"Unsupported credential provider {provider!r}")
    if credential_source not in _VALID_CREDENTIAL_SOURCES:
        raise ValueError(f"Unsupported credential source {credential_source!r}")
    changes: dict[str, Any] = {}
    for model_field, source_field in (
        ("model", "source"),
        ("reflection_model", "reflection_source"),
        ("judge_model", "judge_source"),
    ):
        model = getattr(config, model_field)
        if model and normalize_registry_provider(_resolve_provider(model)) == provider:
            changes[source_field] = infer_source(
                provider,
                model=model,
                credential_source=credential_source,
                settings=settings,
                sources=sources,
            )
    return changes


def _login_source(args: str, *, client: IPCClient | None = None) -> None:
    """``/login source <provider> <type>`` — choose the credential source.

    Migrated from the legacy ``/auth set`` (PR #1203, removed alongside
    ``/auth`` in PR #C, 2026-05-17). The picker decides which provider
    prefix ``evals.petri.models.to_inspect_model`` routes a
    ``claude-*`` / ``gpt-5.*`` id through:

    - ``auto``     — configured credential auto-detect (default)
    - ``oauth``    — legacy OpenAI subscription alias
    - ``openai-codex`` — OpenAI subscription route
    - ``api_key``  — PAYG env (ANTHROPIC_API_KEY / OPENAI_API_KEY)
    - ``none``     — disabled
    """
    from core.cli import commands as _pkg

    parts = args.split()
    if len(parts) != 2:
        _pkg.console.print("  [warning]Usage: /login source <provider> <type>[/warning]")
        _pkg.console.print(
            f"  [muted]providers: {', '.join(_VALID_CREDENTIAL_PROVIDERS)}   "
            f"types: {', '.join(_VALID_CREDENTIAL_SOURCES)}[/muted]"
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
    if source == "claude-cli" or (provider == "anthropic" and source == "oauth"):
        from core.config.credential_source import CLAUDE_CLI_RETIRED_MESSAGE

        _pkg.console.print(f"  [warning]{CLAUDE_CLI_RETIRED_MESSAGE}[/warning]\n")
        return
    if source not in _VALID_CREDENTIAL_SOURCES:
        _pkg.console.print(
            f"  [warning]unknown type: {source} "
            f"(use one of {', '.join(_VALID_CREDENTIAL_SOURCES)})[/warning]"
        )
        _pkg.console.print()
        return
    if source == "openai-codex" and provider != "openai":
        _pkg.console.print(
            f"  [warning]{source} is not a credential source for {provider}.[/warning]\n"
        )
        return
    try:
        from core.llm.routing import infer_source

        # A disabled future default is valid; executable choices must agree
        # with forced policy even without a matching role in this session.
        if source != "none":
            infer_source(provider, credential_source=source)
        if client is not None:
            from core.config.runtime_policy_sources import build_policy_source_bundle
            from core.config.session import SessionModelConfig

            changes = session_source_changes(
                SessionModelConfig.model_validate(client.model_config),
                provider,
                source,
                sources=build_policy_source_bundle().get("provider_routing"),
            )
            if changes:
                response = client.apply_model_config(changes)
                if response.get("status") != "applied":
                    raise ValueError(str(response.get("message", "Session source rejected")))
                _pkg.console.print("  Session source applied; saving future defaults.")
        _persist_credential_source(provider, source)
    except (RuntimeError, ValueError, OSError) as exc:
        _pkg.console.print(f"  [warning]Credential source not saved: {exc}[/warning]\n")
        return
    label = _format_credential_source_label(provider, source)
    _pkg.console.print(
        f"  [success]✓[/success] {provider} credential source → "
        f"[bold]{source}[/bold]  [muted]({label})[/muted]"
    )
    if client is None:
        _pkg.console.print("  Defaults saved for new sessions; running sessions are unchanged.")
    _pkg.console.print()


def _login_anthropic_api_key() -> None:
    """Prompt for an Anthropic API key and persist its runtime sources.

    Tier 0 (PAYG) — ``sk-ant-api…`` saved under the
    ``anthropic-payg-geode`` plan + profile. No refresh logic, no
    expiry; the key is treated as a single long-lived credential
    identical in shape to ``ANTHROPIC_API_KEY`` env loading.
    """
    import getpass
    from datetime import UTC, datetime

    from core.auth.auth_toml import auth_file_transaction
    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg
    from core.config import settings
    from core.llm.adapters.registry import invalidate_provider_clients
    from core.llm.strategies.plans import Plan, PlanKind

    try:
        # allow-direct-io: thin handler — getpass hides typed input from screen.
        api_key = getpass.getpass("  Paste sk-ant-… key (hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        _pkg.console.print("  [muted]Cancelled.[/muted]\n")
        return

    if not api_key:
        _pkg.console.print("  [warning]Empty key — aborted.[/warning]\n")
        return
    if not api_key.startswith("sk-ant-"):
        _pkg.console.print("  [warning]Key does not look like sk-ant-… — saving anyway.[/warning]")

    plan_id = "anthropic-payg-geode"
    with auth_file_transaction() as (registry, store):
        plan = registry.get(plan_id) or Plan(
            id=plan_id,
            provider="anthropic",
            kind=PlanKind.PAYG,
            display_name="Anthropic (PAYG)",
            base_url="https://api.anthropic.com",
            auth_type="x-api-key",
        )
        registry.add(plan)
        profile = AuthProfile(
            name=f"{plan_id}:user",
            provider="anthropic",
            credential_type=CredentialType.API_KEY,
            key=api_key,
            plan_id=plan.id,
            expires_at=0.0,
            metadata={"last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
        )
        store.add(profile, activate=True)
    settings.anthropic_api_key = api_key
    _pkg._upsert_env("ANTHROPIC_API_KEY", api_key)
    _persist_credential_source("anthropic", "api_key")
    invalidate_provider_clients("anthropic")
    clear_dry_run_opt_in()

    _pkg.console.print()
    _pkg.console.print("  [success]✓ Anthropic API key saved.[/success]")
    _pkg.console.print("  [muted]Stored: ~/.geode/.env and ~/.geode/auth.toml[/muted]\n")


def _login_set_key(rest: str) -> None:
    from core.auth.auth_toml import auth_file_transaction
    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg

    parts = rest.split(None, 1)
    if len(parts) < 2:
        raise ValueError("Usage: /login set-key <plan-id> <api-key>")
    plan_id, key = parts[0], parts[1].strip()
    with auth_file_transaction() as (registry, store):
        plan = registry.get(plan_id)
        if plan is None:
            raise ValueError(f"Unknown plan: {plan_id} (use /login add first)")
        name = f"{plan.id}:user"
        existing = store.get(name)
        profile = (
            replace(existing, key=key, error_count=0, cooldown_until=0.0)
            if existing is not None
            else AuthProfile(
                name=name,
                provider=plan.provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
        store.add(profile, activate=True)
    if plan.provider == "glm-coding":
        from core.llm.adapters.registry import invalidate_provider_clients

        invalidate_provider_clients("glm")
    clear_dry_run_opt_in()
    _pkg.console.print(
        f"  [success]Updated key[/success] for {plan.display_name}  "
        f"[muted]({_pkg._mask_key(key)})[/muted]\n"
    )


def _login_use(rest: str) -> None:
    from core.cli import commands as _pkg

    plan_id = rest.strip()
    if not plan_id:
        raise ValueError("Usage: /login use <plan-id>")
    from core.auth.auth_toml import auth_file_transaction
    from core.llm.model_catalog import model_ids_for_source, model_source_unavailable_reason
    from core.llm.registry import get_provider_spec

    with auth_file_transaction() as (registry, _store):
        plan = registry.get(plan_id)
        if plan is None:
            raise ValueError(f"Unknown plan: {plan_id}")
        spec = get_provider_spec(plan.provider)
        if spec is None:
            raise ValueError(f"Unknown provider: {plan.provider}")
        reason = model_source_unavailable_reason(
            spec.profile.default_model(),
            provider=spec.profile.provider,
            source=spec.credential.source,
        )
        if reason:
            raise ValueError(reason)
        for model in model_ids_for_source(spec.profile.provider, spec.credential.source):
            existing = [pid for pid in registry.get_routing(model) if pid != plan.id]
            registry.set_routing(model, [plan.id, *existing])
    _pkg.console.print(
        f"  [success]Activated[/success] {plan.display_name} for {plan.provider} models.\n"
    )


def _unstored_profile_message(name: str) -> str:
    """Explain why a profile choice cannot be saved to auth.toml."""
    from core.wiring.container import ensure_profile_store

    if name in ensure_profile_store():
        return (
            f"{name} comes from the environment or an imported CLI login; "
            "auth.toml cannot store a choice for it"
        )
    return f"Unknown profile: {name} (run /login to list all profiles)"


def _login_use_profile(rest: str) -> None:
    """Pin a specific profile as the active credential for its provider.

    X1 — pre-fix the rotator chose the first eligible profile by
    type-priority + LRU sort key, so an operator with multiple OAuth
    profiles for the same provider could not pin a preferred one
    without removing the others. This command wraps
    ``ProfileStore.set_active`` so the next ``ProfileRotator.resolve``
    surfaces the pinned profile first (legacy sort applies to the
    remaining candidates so an ineligible pin gracefully steps aside).
    """
    from core.auth.auth_toml import auth_file_transaction
    from core.cli import commands as _pkg

    name = rest.strip()
    if not name:
        raise ValueError("Usage: /login use-profile <profile-name>")
    with auth_file_transaction() as (_registry, store):
        profile = store.get(name)
        if profile is None:
            raise ValueError(_unstored_profile_message(name))
        store.set_active(name)
    _pkg.console.print(f"  [success]Pinned[/success] {name} as active for {profile.provider}.\n")


def _login_order(rest: str) -> None:
    """Show or mutate the effective profile order per provider.

    Subcommands::

        /login order                       — show every provider's order
        /login order <provider>            — show one provider's order
        /login order set <provider> <n1> <n2> …   — pin multi-rank
        /login order clear <provider>      — drop the pin (back to LRU)

    X1.1 — the rotator tries the listed profiles in order before
    falling back to ``sort_key`` (legacy LRU/type-priority). The
    first list element is also written to the single-active pin
    (``ProfileStore.set_active`` parity) so X1's ``/login`` ``(active)``
    badge stays accurate.
    """
    from core.auth.auth_toml import auth_file_transaction
    from core.cli import commands as _pkg
    from core.wiring.container import ensure_profile_store

    # X1.1 mutating subcommands.
    parts = rest.split()
    if parts and parts[0].lower() in ("set", "clear"):
        action = parts[0].lower()
        if len(parts) < 2:
            raise ValueError(
                "Usage: /login order set <provider> <name1> <name2> … "
                "or /login order clear <provider>"
            )
        provider = parts[1]
        if action == "clear":
            with auth_file_transaction() as (_registry, store):
                store.clear_auth_order(provider)
            _pkg.console.print(
                f"  [success]Cleared auth order[/success]  {provider}  "
                "[muted](rotator falls back to LRU/type-priority)[/muted]\n"
            )
            return
        names = parts[2:]
        if not names:
            raise ValueError(
                "Usage: /login order set <provider> <name1> [<name2> …]. Pass at least "
                "one profile name; use `/login order clear <provider>` to drop a pin."
            )
        with auth_file_transaction() as (_registry, store):
            missing = [name for name in names if name not in store]
            if missing:
                raise ValueError(_unstored_profile_message(missing[0]))
            store.set_auth_order(provider, names)
        _pkg.console.print(
            f"  [success]Pinned auth order[/success]  {provider}  "
            f"[muted]({' → '.join(names)})[/muted]\n"
        )
        return

    store = ensure_profile_store()
    profiles = store.list_all()
    if not profiles:
        _pkg.console.print(
            "  [muted]No profiles registered. Run /login add to create one.[/muted]\n"
        )
        return

    target_provider = rest.strip() or None
    by_provider: dict[str, list[AuthProfile]] = {}
    for p in profiles:
        if target_provider and p.provider != target_provider:
            continue
        by_provider.setdefault(p.provider, []).append(p)

    if not by_provider:
        raise ValueError(f"No profiles for provider {target_provider!r}.")

    _pkg.console.print("\n  [header]Profile order[/header]")
    for provider in sorted(by_provider.keys()):
        # X1.1 — full multi-rank order if set; else fall back to X1
        # single-active pin (head of the implicit one-element list).
        ranked_names = store.get_auth_order(provider)
        if not ranked_names:
            pinned_profile = store.get_pinned_active(provider)
            if pinned_profile is not None:
                ranked_names = [pinned_profile.name]
        verdicts = {v.profile_name: v for v in store.evaluate_eligibility(provider)}
        eligible = [
            p
            for p in by_provider[provider]
            if (v := verdicts.get(p.name)) is not None and v.eligible
        ]
        ineligible = [p for p in by_provider[provider] if p not in eligible]
        # Pull the ranked entries first (preserve operator order),
        # then sort the remaining eligible by sort_key.
        ranked_eligible: list[AuthProfile] = []
        ranked_set: set[str] = set()
        eligible_by_name = {p.name: p for p in eligible}
        for name in ranked_names:
            profile = eligible_by_name.get(name)
            if profile is not None and name not in ranked_set:
                ranked_eligible.append(profile)
                ranked_set.add(name)
        others = [p for p in eligible if p.name not in ranked_set]
        others.sort(key=lambda p: p.sort_key())
        ordered = ranked_eligible + others
        _pkg.console.print(f"  [bold]{provider}[/bold]")
        if not ordered and not ineligible:
            _pkg.console.print("    [muted](no profiles)[/muted]")
            continue
        for idx, p in enumerate(ordered, 1):
            # X1.1 — every entry from ``ranked_eligible`` is part of the
            # operator-supplied auth order ("active" / "rank 1+"); the
            # ``others`` tail rides on the legacy LRU sort ("queued").
            if p in ranked_eligible:
                badge = "[success]active[/success]" if idx == 1 else "[success]ranked[/success]"
            else:
                badge = "[muted]queued[/muted]"
            _pkg.console.print(f"    {idx}. {badge}  {p.name}")
        for p in ineligible:
            v = verdicts.get(p.name)
            reason = v.reason_code if v is not None else "?"
            _pkg.console.print(f"    -. [warning]{reason}[/warning]  {p.name}")
    _pkg.console.print()


def _login_remove(rest: str) -> None:
    from core.cli import commands as _pkg

    plan_id = rest.strip()
    if not plan_id:
        raise ValueError("Usage: /login remove <plan-id>")
    from core.auth.auth_toml import auth_file_transaction

    with auth_file_transaction() as (registry, store):
        if not registry.remove(plan_id):
            raise ValueError(f"Plan not found: {plan_id}")
        for p in list(store.list_all()):
            if p.plan_id == plan_id:
                store.remove(p.name)
    _pkg.console.print(f"  [success]Removed plan and its profiles:[/success] {plan_id}\n")


def _login_route(rest: str) -> None:
    from core.cli import commands as _pkg

    parts = rest.split()
    if len(parts) < 2:
        raise ValueError("Usage: /login route <model> <plan-id> [<plan-id>...]")
    model, plan_ids = parts[0], parts[1:]
    from core.auth.auth_toml import auth_file_transaction

    with auth_file_transaction() as (registry, _store):
        unknown = [pid for pid in plan_ids if registry.get(pid) is None]
        if unknown:
            raise ValueError(f"Unknown plan(s): {', '.join(unknown)}")
        registry.set_routing(model, plan_ids)
    _pkg.console.print(f"  [success]Routing[/success] {model} → " + " → ".join(plan_ids) + "\n")


def _login_quota() -> None:
    """List declared plan quotas; GEODE does not count calls against them."""
    from core.cli import commands as _pkg

    quoted = [
        (plan["id"], quota)
        for plan in build_login_snapshot()["plans"]
        if (quota := plan["quota"]) is not None
    ]
    if not quoted:
        _pkg.console.print("  [muted]No quota-bearing plans registered.[/muted]\n")
        return
    _pkg.console.print("\n  [header]Plan Quota[/header]")
    for plan_id, quota in quoted:
        _pkg.console.print(
            f"  {plan_id:<24} {quota['max_calls']} calls / {quota['window_s'] // 3600}h window"
        )
    _pkg.console.print(
        "  [muted]Declared limits only; check the provider account for current usage.[/muted]\n"
    )


# ---------------------------------------------------------------------------
# /login health — per-profile eligibility verdict + actionable suggestion
# ---------------------------------------------------------------------------


_HEALTH_SUGGESTIONS: dict[str, str] = {
    "ok": "Ready to dispatch.",
    "missing_key": "Key/token is empty. Run `/login add` (interactive) or "
    "`/login set-key <plan> <key>` to populate.",
    "expired": "OAuth token past expires_at. Re-run `codex login` and then "
    "`/login refresh` so GEODE "
    "picks the new token up.",
    "cooling_down": "Backoff after consecutive failures. The verdict line "
    "shows the cooldown deadline — wait it out or "
    "`/login use <other-plan>` to switch providers in the meantime.",
    "disabled": "Manually disabled (`/login remove <plan>` to delete, or "
    "edit `~/.geode/auth.toml` to flip `disabled=false`).",
}


def _login_health(rest: str) -> None:
    """Render eligibility verdicts for one profile or every profile.

    L5 — the `/login` status dashboard already shows an inline reject
    badge (cooldown / expired / etc), but the reason codes are opaque
    until the user knows what each one means. ``/login help`` now
    documents the codes; this subcommand turns the same data into a
    per-profile report with an actionable suggestion ("re-run
    `claude`", "wait Xm", …) so the user can resolve a verdict without
    guessing.
    """
    from core.cli import commands as _pkg

    profiles = build_login_snapshot()["profiles"]
    if not profiles:
        _pkg.console.print(
            "  [muted]No profiles registered. Run `/login add` to create one.[/muted]\n"
        )
        return

    # When the operator names a profile, narrow down — same matching the
    # rest of the login subcommands use (exact name).
    target = rest.strip()
    if target:
        profiles = [p for p in profiles if p["name"] == target]
        if not profiles:
            raise ValueError(f"No profile named {target}. Run `/login` to list all profiles.")

    _pkg.console.print("\n  [header]Eligibility[/header]")
    for p in profiles:
        code = p["reason"]
        badge = "[success]ok[/success]" if p["eligible"] else f"[warning]{code}[/warning]"
        _pkg.console.print(f"  {badge:<24} [bold]{p['name']}[/bold]")
        if p["reason_detail"]:
            _pkg.console.print(f"    [muted]{p['reason_detail']}[/muted]")
        suggestion = _HEALTH_SUGGESTIONS.get(code, "")
        if suggestion:
            _pkg.console.print(f"    → {suggestion}")
    _pkg.console.print()


# ---------------------------------------------------------------------------
# /login providers — variant registry + equivalence map view
# ---------------------------------------------------------------------------


def _login_providers() -> None:
    """Show registered provider families without implying a billing fallback."""
    from core.cli import commands as _pkg
    from core.llm.registry import PROVIDER_VARIANTS
    from core.llm.strategies.plan_registry import get_plan_registry

    registry = get_plan_registry()
    plans = registry.list_all()
    plans_by_provider: dict[str, int] = {}
    for plan in plans:
        plans_by_provider[plan.provider] = plans_by_provider.get(plan.provider, 0) + 1

    _pkg.console.print("\n  [header]Provider variants[/header]")
    # Stable order: registry insertion order, which mirrors the chain user
    # would see in /login status.
    for spec in PROVIDER_VARIANTS.values():
        plan_count = plans_by_provider.get(spec.id, 0)
        plan_badge = f"  [muted]{plan_count} plan{'s' if plan_count != 1 else ''}[/muted]"
        _pkg.console.print(
            f"  [bold]{spec.id:<16}[/bold] "
            f"[muted]{spec.auth_type:<16}[/muted] "
            f"{spec.display_name}"
            f"{plan_badge}"
        )
        _pkg.console.print(f"    [muted]{spec.default_base_url}[/muted]")

    _pkg.console.print("\n  [header]Source alternatives[/header]")
    _pkg.console.print(
        "  [muted]Each model family may expose separate billing sources. "
        "The selected source is fixed; missing credentials never select a sibling.[/muted]"
    )
    families: dict[str, list[str]] = {}
    for spec in PROVIDER_VARIANTS.values():
        families.setdefault(spec.profile.provider, []).append(spec.id)
    for family, members in families.items():
        if len(members) > 1:
            _pkg.console.print(f"  [bold]{family:<16}[/bold] → " + " · ".join(members))
    _pkg.console.print()
