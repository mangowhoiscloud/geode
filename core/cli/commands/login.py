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
from typing import Any

from simple_term_menu import TerminalMenu

from core.auth.profiles import AuthProfile

log = logging.getLogger(__name__)


_VALID_CREDENTIAL_SOURCES: tuple[str, ...] = ("auto", "oauth", "api_key", "none")
_VALID_CREDENTIAL_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")


_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "codex": "openai",
    "chatgpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "claude-code": "anthropic",
}
"""User-facing provider names → canonical key. Accepts both the marketing
name (``chatgpt``, ``claude``) and the CLI binary name (``codex``,
``claude-code``) so the picker is forgiving of typos and habit."""


def cmd_login(args: str) -> None:
    """Handle /login — unified credentials/plans command.

    Parameter shape: ``/login [<provider>|<subcommand>]``. Providers run
    the OAuth login flow directly (no extra subcommand), so the command
    surface stays grep-able by provider name alone — this is the consolidated
    replacement for the removed legacy auth-login subcommand (PR #B,
    2026-05-17).

    Providers (case-insensitive, aliases accepted)::

        /login openai      — Codex subscription device-code flow (aliases: codex, chatgpt)
        /login anthropic   — Claude subscription login via local `claude` CLI
                             (aliases: claude, claude-code)

    Subcommands::

        /login                — show plans, profiles, routing, quota
        /login add            — interactive wizard (kind → provider → key/OAuth)
        /login set-key <plan> <key>
        /login use <plan>     — pin a plan as the active one for its provider
        /login remove <plan>
        /login route <model> <plan> [<plan>...]
        /login quota          — per-plan usage breakdown
        /login health [<profile>] — eligibility verdict + actionable suggestion
        /login status         — legacy alias of bare /login
    """
    from core.cli import commands as _pkg

    raw = args.strip()
    if not raw:
        _login_show_status()
        return

    parts = raw.split(None, 1)
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    # Provider-as-parameter dispatch: ``/login openai`` /
    # ``/login anthropic`` (+ aliases) run the OAuth flow directly. This
    # path is reached before any subcommand match so a provider name and
    # a subcommand never collide in practice — providers live in
    # ``_PROVIDER_ALIASES``, subcommands are checked below.
    if sub in _PROVIDER_ALIASES:
        _login_oauth(_PROVIDER_ALIASES[sub])
        return

    if sub in ("status", "list", "ls"):
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
        _login_source(rest)
        return
    if sub == "refresh":
        # v0.52 phase 3 — daemon-side reload of auth.toml after thin client
        # writes (e.g. /login openai completed in CLI process). When invoked
        # in CLI process this is a no-op; the actual reload happens when the
        # CLI relays /login refresh to the daemon via IPC.
        #
        # Semantics — ADDITIVE ONLY (v0.52.1 documented invariant):
        #   * Plans/Profiles newly written to auth.toml ARE picked up.
        #   * Plans/Profiles REMOVED from auth.toml are NOT removed from the
        #     daemon's in-memory singletons. Use `/login remove <plan-id>`
        #     for explicit deletion (which goes through the same IPC path
        #     and updates both file + memory atomically).
        #
        # Why additive: lifecycle.container.ensure_profile_store() returns
        # the cached singleton on subsequent calls; load_auth_toml() merges
        # into the existing store rather than rebuilding it. This protects
        # in-flight requests using profiles loaded from .env / managed CLIs
        # (Codex CLI OAuth) which never appear in auth.toml.
        try:
            from core.auth.auth_toml import auth_toml_path, load_auth_toml
            from core.llm.strategies.plan_registry import get_plan_registry
            from core.wiring.container import ensure_profile_store

            registry = get_plan_registry()
            store = ensure_profile_store()
            plans_before = {p.id for p in registry.list_all()}
            profiles_before = {p.name for p in store.list_all()}
            ok = load_auth_toml()
            plans_after = {p.id for p in registry.list_all()}
            profiles_after = {p.name for p in store.list_all()}
            new_plans = plans_after - plans_before
            new_profiles = profiles_after - profiles_before
            # v0.52.2 — production observability for the B7 thin → daemon
            # refresh signal. Pre-fix this branch was completely silent on
            # success, making it impossible to verify the relay was firing.
            log.info(
                "auth.toml reload: file=%s loaded=%s new_plans=%d "
                "new_profiles=%d total_plans=%d total_profiles=%d",
                auth_toml_path(),
                ok,
                len(new_plans),
                len(new_profiles),
                len(plans_after),
                len(profiles_after),
            )
            for plan_id in sorted(new_plans):
                log.info("auth.toml reload: + plan %s", plan_id)
            for profile_name in sorted(new_profiles):
                log.info("auth.toml reload: + profile %s", profile_name)
            # L2 — pre-fix this branch logged via ``log.info`` only, so
            # the operator running ``/login refresh`` from the REPL saw
            # nothing on stdout and could not tell whether the daemon
            # had picked up the new plan/profile. Surface the same
            # counts to the console so the success path is visible.
            from core.cli import commands as _pkg

            if not ok:
                _pkg.console.print(
                    f"  [warning]auth.toml reload failed[/warning]  "
                    f"[muted]({auth_toml_path()})[/muted]\n"
                )
            elif new_plans or new_profiles:
                added = []
                if new_plans:
                    added.append(f"{len(new_plans)} plan{'s' if len(new_plans) != 1 else ''}")
                if new_profiles:
                    added.append(
                        f"{len(new_profiles)} profile{'s' if len(new_profiles) != 1 else ''}"
                    )
                _pkg.console.print(
                    f"  [success]auth.toml reloaded[/success]  [muted]+{' · +'.join(added)}[/muted]"
                )
                for plan_id in sorted(new_plans):
                    _pkg.console.print(f"    [muted]+ plan {plan_id}[/muted]")
                for profile_name in sorted(new_profiles):
                    _pkg.console.print(f"    [muted]+ profile {profile_name}[/muted]")
                _pkg.console.print()
            else:
                _pkg.console.print(
                    f"  [muted]auth.toml reloaded — no new plans or profiles "
                    f"(total: {len(plans_after)} plans, {len(profiles_after)} profiles)[/muted]\n"
                )
        except Exception:
            log.warning("auth.toml reload failed", exc_info=True)
            from core.cli import commands as _pkg

            _pkg.console.print(
                "  [warning]auth.toml reload failed[/warning]  "
                "[muted](see daemon log for traceback)[/muted]\n"
            )
        return
    if sub in ("help", "?"):
        _login_help()
        return

    _pkg.console.print(
        f"\n  [warning]Unknown /login subcommand:[/warning] {sub}\n"
        "  Run [label]/login help[/label] for the full menu.\n"
    )


# ---------------------------------------------------------------------------
# /login subcommands — implementation
# ---------------------------------------------------------------------------


def _login_help() -> None:
    from core.cli import commands as _pkg

    _pkg.console.print(
        "\n  [header]/login[/header] — credentials & subscription plans\n"
        "\n"
        "  [label]/login[/label]                       Show all plans, profiles, routing\n"
        "  [label]/login openai[/label]                OAuth flow (Codex subscription quota)\n"
        "  [label]/login anthropic[/label]             OAuth flow (Claude subscription)\n"
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
        "  [label]/login quota[/label]                 Per-plan quota / usage\n"
        "  [label]/login health[/label] [<profile>]    Eligibility verdict per profile\n"
        "  [label]/login providers[/label]             Provider variants + equivalence map\n"
        "\n"
        "  [muted]Eligibility verdicts (shown next to each profile in /login):[/muted]\n"
        "  [muted]  ok               — profile passes every check, ready to dispatch[/muted]\n"
        "  [muted]  missing_key      — key/token field is empty; rerun add or set-key[/muted]\n"
        "  [muted]  expired          — OAuth token past expires_at; refresh via the[/muted]\n"
        "  [muted]                     owning CLI (`claude` / `codex`) and rerun /login[/muted]\n"
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


def _login_show_status() -> None:
    """Render the unified plans + profiles + routing dashboard.

    Combines OpenClaw `/status` (auth-mode badge), Hermes `hermes status`
    (per-provider expiry + subscription line), and Claude Code Settings
    Status tab (plan + token source + provider).
    """
    from core.auth.oauth_login import get_auth_status as get_oauth_status
    from core.auth.profiles import CredentialType
    from core.cli import commands as _pkg
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()
    registry = get_plan_registry()
    plans = registry.list_all()
    profiles = store.list_all()

    _pkg.console.print()
    _pkg.console.print("  [header]Plans[/header]")
    if not plans and not profiles:
        _pkg.console.print("  [muted]No plans or credentials registered yet.[/muted]")
        _pkg.console.print(
            "  [muted]Run /login add to register a plan, or paste an API key.[/muted]"
        )
        _pkg.console.print()
        return

    if plans:
        for plan in plans:
            usage = registry.usage_for(plan.id)
            subscription_tier = plan.subscription_tier
            if getattr(plan, "provider", "") == "openai-codex":
                from core.auth.oauth_login import chatgpt_plan_label

                subscription_tier = chatgpt_plan_label(subscription_tier)
            tier_label = f" · {subscription_tier}" if subscription_tier else ""
            quota_label = ""
            if plan.quota is not None:
                remaining = usage.remaining_in_window(plan)
                quota_label = (
                    f"  [muted]used {int(usage.weighted_calls)}/{plan.quota.max_calls}"
                    f" ({plan.quota.window_s // 3600}h window, {remaining} left)[/muted]"
                )
            bound = [p for p in profiles if p.plan_id == plan.id]
            mark = "[success]✓[/success]" if bound else "[warning]?[/warning]"
            _pkg.console.print(
                f"  {mark} [bold]{plan.id}[/bold]  "
                f"[muted]{plan.kind.value}[/muted]  {plan.base_url}{tier_label}{quota_label}"
            )
    else:
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
    else:
        # Group by provider for readability
        by_provider: dict[str, list[AuthProfile]] = {}
        for p in profiles:
            by_provider.setdefault(p.provider, []).append(p)
        # v0.51.0 — pre-compute eligibility per provider so each profile row
        # carries an inline reject badge (cooldown / expired / disabled / etc).
        verdicts_by_name: dict[str, str] = {}
        details_by_name: dict[str, str] = {}
        for prov in by_provider:
            for v in store.evaluate_eligibility(prov):
                verdicts_by_name[v.profile_name] = v.reason_code
                details_by_name[v.profile_name] = v.detail
        # X1 — surface the user-pinned active profile per provider so
        # the operator sees which one ``ProfileRotator.resolve`` will
        # pick first. The pin lives in ``ProfileStore.set_active`` and
        # is read through ``get_pinned_active`` (excludes the auto-set
        # legacy active so the badge tracks operator intent, not the
        # first-registered side effect).
        active_by_provider: dict[str, str] = {}
        for prov in by_provider:
            active = store.get_pinned_active(prov)
            if active is not None:
                active_by_provider[prov] = active.name

        for provider in sorted(by_provider.keys()):
            active_name = active_by_provider.get(provider)
            for p in by_provider[provider]:
                badge = {
                    CredentialType.OAUTH: "oauth",
                    CredentialType.TOKEN: "token",
                    CredentialType.API_KEY: "api-key",
                }.get(p.credential_type, "?")
                # L3 — surface Plan binding detail (display_name + kind +
                # subscription_tier) so an OAuth profile row actually
                # says *what subscription* it talks to instead of just an
                # opaque plan id. Falls back to ``(none)`` when the
                # profile is PAYG / unmanaged.
                plan_label = _format_plan_binding(registry, p.plan_id)
                managed = f" · managed:{p.managed_by}" if p.managed_by else ""
                expiry = ""
                if p.expires_at:
                    import time as _t

                    rem = int(p.expires_at - _t.time())
                    expiry = f" · expires {rem // 60}m" if rem > 0 else " · [error]expired[/error]"
                # Eligibility badge — green ✓ when ok, yellow/red with reason otherwise.
                reason = verdicts_by_name.get(p.name, "ok")
                if reason == "ok":
                    badge_str = "[success]✓[/success]"
                else:
                    detail = details_by_name.get(p.name, "")
                    badge_str = f"[warning]✗ {reason}[/warning]"
                    if detail:
                        badge_str += f" [muted]({detail})[/muted]"
                # X1 — mark the active row so ``/login`` shows which
                # profile a call will pick first when multiple are
                # eligible for the same provider.
                active_suffix = " [success](active)[/success]" if p.name == active_name else ""
                _pkg.console.print(
                    f"  {badge_str}  {p.name:<28}{active_suffix} "
                    f"[muted]{badge:<7}[/muted] {p.masked_key} "
                    f"plan={plan_label}{managed}{expiry}"
                )
    _pkg.console.print()

    # Routing section
    routing = registry.all_routing()
    if routing:
        _pkg.console.print("  [header]Routing[/header]")
        for model, plan_ids in sorted(routing.items()):
            chain = " → ".join(plan_ids) if plan_ids else "[muted](none)[/muted]"
            _pkg.console.print(f"  {model:<24} → {chain}")
        _pkg.console.print()

    # OAuth status (shows expiry + email when available)
    try:
        oauth = get_oauth_status()
    except Exception:
        oauth = []
    if oauth:
        _pkg.console.print("  [header]OAuth (external CLIs)[/header]")
        for s in oauth:
            colour = "success" if s.get("status") == "active" else "warning"
            _pkg.console.print(
                f"  [{colour}]{s.get('status', '?'):<8}[/{colour}] "
                f"{s.get('provider', ''):<20} "
                f"{s.get('email') or '-':<24} "
                f"{s.get('expires_in', ''):<10} "
                f"[muted]({s.get('source', '')})[/muted]"
            )
        _pkg.console.print()

    _pkg.console.print(
        "  [muted]Tip: /login add to register a plan · /login quota for usage detail[/muted]\n"
    )


def _login_add_interactive(_args: str) -> None:
    """Interactive wizard — Plan kind → Provider → endpoint/key/OAuth.

    Mirrors OpenClaw setup wizard (`prompter.select` levels) collapsed
    into a single CLI command so existing users can run it any time.
    """
    import sys

    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import (
        GLM_CODING_TIERS,
        default_plan_for_payg,
    )
    from core.wiring.container import ensure_profile_store

    if not sys.stdin.isatty():
        _pkg.console.print(
            "  [warning]/login add requires an interactive terminal.[/warning]\n"
            "  [muted]Set keys via env vars (ZAI_API_KEY, OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY) for non-interactive setup.[/muted]"
        )
        return

    kinds = [
        (
            "subscription",
            "Subscription (GLM Coding Lite/Pro/Max · "
            "ChatGPT Plus/Pro/Pro Lite/Team/Business/Enterprise/Edu · "
            "Claude Pro/Max ×5/Max ×20/Team)",
        ),
        ("payg", "Pay-as-you-go API key (Anthropic, OpenAI, GLM PAYG)"),
        ("oauth", "OAuth borrowed (Codex CLI / Claude Code)"),
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

    registry = get_plan_registry()
    store = ensure_profile_store()

    if kind_id == "subscription":
        # Currently only GLM Coding Plan tiers are templated
        tier_entries = [
            "GLM Coding Lite  ($6/mo · 80 calls/5h · 3× weight on glm-5.1)",
            "GLM Coding Pro   ($30/mo · 240 calls/5h)",
            "GLM Coding Max   ($80/mo · 600 calls/5h)",
        ]
        tier_keys = ["lite", "pro", "max"]
        tmenu = TerminalMenu(
            tier_entries,
            title="\n  Subscription tier?\n",
            menu_cursor="  > ",
        )
        tidx = tmenu.show()
        if tidx is None:
            _pkg.console.print("  [muted]Cancelled[/muted]\n")
            return
        plan = GLM_CODING_TIERS[tier_keys[tidx]]
        try:
            key = _pkg.console.input(f"  [label]{plan.display_name} API key:[/label] ").strip()
        except (KeyboardInterrupt, EOFError):
            _pkg.console.print("\n  [muted]Cancelled[/muted]\n")
            return
        if not key:
            _pkg.console.print("  [warning]No key provided.[/warning]\n")
            return
        registry.add(plan)
        registry.set_routing("glm-5.1", [plan.id, *registry.get_routing("glm-5.1")])
        for m in ("glm-5", "glm-5-turbo", "glm-4.7-flash"):
            registry.set_routing(m, [plan.id, *registry.get_routing(m)])
        store.add(
            AuthProfile(
                name=f"{plan.id}:user",
                provider=plan.provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
        # Reset the GLM client so the next call picks up the new endpoint+key
        try:
            from core.llm.providers.glm import reset_glm_client

            reset_glm_client()
        except Exception:  # noqa: S110 — best-effort cache invalidation
            pass
        _pkg._persist_auth_state()
        _pkg.console.print(
            f"  [success]Registered[/success] {plan.display_name}  "
            f"[muted]({plan.base_url})[/muted]\n"
        )
        return

    if kind_id == "payg":
        providers = [
            ("anthropic", "Anthropic"),
            ("openai", "OpenAI"),
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
        registry.add(plan)
        store.add(
            AuthProfile(
                name=f"{plan.id}:user",
                provider=provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
        # Mirror to settings + .env so legacy fallbacks keep working
        from core.config import settings

        env_field_map = {
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "openai": ("openai_api_key", "OPENAI_API_KEY"),
            "glm": ("zai_api_key", "ZAI_API_KEY"),
        }
        if provider in env_field_map:
            field_name, env_var = env_field_map[provider]
            object.__setattr__(settings, field_name, key)
            _pkg._upsert_env(env_var, key)
        _pkg._persist_auth_state()
        _pkg.console.print(
            f"  [success]Registered[/success] {plan.display_name}  "
            f"[muted](key {_pkg._mask_key(key)})[/muted]\n"
        )
        return

    if kind_id == "oauth":
        oauth_entries = [
            "OpenAI Codex CLI (chatgpt.com/backend-api/codex)",
            "Claude Code (currently disabled — Anthropic ToS)",
        ]
        omenu = TerminalMenu(
            oauth_entries,
            title="\n  OAuth source?\n",
            menu_cursor="  > ",
        )
        oidx = omenu.show()
        if oidx is None:
            _pkg.console.print("  [muted]Cancelled[/muted]\n")
            return
        if oidx == 1:
            _pkg.console.print(
                "  [warning]Claude Code OAuth is disabled (Anthropic ToS, "
                "see core/runtime_wiring/infra.py).[/warning]\n"
            )
            return
        _login_oauth("openai")
        return


def _login_oauth(target: str) -> None:
    """Run the OAuth login flow for a subscription provider.

    ``target`` is the canonical key (``openai`` / ``anthropic``) — the
    caller has already resolved aliases via :data:`_PROVIDER_ALIASES`.
    Each branch is responsible for the provider-specific flow:

    - ``openai``: GEODE-native device-code flow (Codex subscription quota).
    - ``anthropic``: delegate to the local ``claude`` CLI's
      ``claude /login`` browser flow, then sync the keychain blob into
      ``ProfileStore`` so other parts of the system see the credential.
    """
    from core.cli import commands as _pkg

    target = target.lower().strip()
    if target == "openai":
        _pkg.console.print()
        try:
            from core.auth.oauth_login import login_openai

            creds = login_openai()
            if creds:
                import contextlib

                with contextlib.suppress(Exception):
                    from core.llm.providers.codex import reset_codex_client

                    reset_codex_client()
                _pkg.console.print(
                    "  [success]Codex OAuth registered.[/success]  "
                    "[muted]Provider: openai-codex[/muted]\n"
                )
        except Exception as exc:
            _pkg.console.print(f"  [red]Login failed: {exc}[/red]\n")
        return

    if target == "anthropic":
        _login_oauth_anthropic()
        return

    _pkg.console.print(
        f"  [warning]OAuth not implemented for '{target}'.[/warning]\n"
        "  [muted]Available: openai (Codex subscription), anthropic (Claude subscription)[/muted]\n"
    )


def _format_credential_source_label(provider: str, source: str) -> str:
    """Human-readable label for the ``source`` picker — pulls live
    subscription info from the credential blob rather than baking
    plan names into the code."""
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
        from core.auth.oauth_login import chatgpt_plan_label

        return chatgpt_plan_label(meta.get("plan_type"))
    return source


def _persist_credential_source(provider: str, source: str) -> None:
    """Persist the source choice — settings + .env + config.toml.

    Mirrors :func:`core.cli.commands.model._apply_model` — same
    three-location write so the choice survives env wipes (Hermes /
    Codex / Claude Code precedent: durable settings outrank env).
    """
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
        log.debug("login: settings.%s setattr failed", field, exc_info=True)
    _pkg._upsert_env(env_var, source)
    upsert_config_toml("llm", field, source)


def _login_source(args: str) -> None:
    """``/login source <provider> <type>`` — choose the credential source.

    Migrated from the legacy ``/auth set`` (PR #1203, removed alongside
    ``/auth`` in PR #C, 2026-05-17). The picker decides which provider
    prefix ``plugins.petri_audit.models.to_inspect_model`` routes a
    ``claude-*`` / ``gpt-5.*`` id through:

    - ``auto``     — env / keychain auto-detect (default)
    - ``oauth``    — subscription quota (claude-code / openai-codex)
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
    if source not in _VALID_CREDENTIAL_SOURCES:
        _pkg.console.print(
            f"  [warning]unknown type: {source} "
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


def _login_oauth_anthropic() -> None:
    """Anthropic credential setup — API key (PAYG) only on the production path.

    v0.99.10 limits ``/login anthropic`` to the Anthropic Console PAYG
    API key path (Tier 0). Earlier iterations (v0.99.0..v0.99.9) tried
    an owned PKCE flow and a claude-CLI subprocess delegate; both routed
    through the first-party OAuth client ``9d1c250a-…`` which Anthropic's
    2026-04-04 third-party block rejects (or, in the subprocess case,
    spawned a full Claude Code REPL the user got stuck inside).

    The Claude subscription path now lives **only** in
    ``plugins/petri_audit/claude_code_provider.py``: it reads claude's
    keychain in-process (PR #1202) and is consumed solely by Petri
    audit/judge runs. Production GEODE chat/agent stays on a clean
    ``sk-ant-api…`` PAYG key.
    """
    from core.cli import commands as _pkg

    _pkg.console.print()
    _pkg.console.print("  [bold]Anthropic Console PAYG (API key)[/bold]")
    _pkg.console.print("  [muted]Get a key at: https://console.anthropic.com/keys[/muted]")
    _pkg.console.print(
        "  [muted]Claude subscription path is reserved for Petri audit; "
        "see plugins/petri_audit/claude_code_provider.py.[/muted]"
    )
    _pkg.console.print()
    _login_anthropic_api_key()


def _login_anthropic_api_key() -> None:
    """Prompt for an Anthropic API key and persist it to ``auth.toml``.

    Tier 0 (PAYG) — ``sk-ant-api…`` saved under the
    ``anthropic-payg-geode`` plan + profile. No refresh logic, no
    expiry; the key is treated as a single long-lived credential
    identical in shape to ``ANTHROPIC_API_KEY`` env loading.
    """
    import getpass
    from datetime import UTC, datetime

    from core.auth.profiles import AuthProfile, CredentialType
    from core.cli import commands as _pkg
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import Plan, PlanKind
    from core.wiring.container import ensure_profile_store

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
    registry = get_plan_registry()
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
        managed_by="geode-api-key",
        metadata={"last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
    )
    ensure_profile_store().add(profile)
    try:
        from core.auth.auth_toml import save_auth_toml

        save_auth_toml()
    except Exception:
        log.debug("auth.toml persist after anthropic login failed", exc_info=True)

    _pkg.console.print()
    _pkg.console.print("  [success]✓ Anthropic API key saved.[/success]")
    _pkg.console.print("  [muted]Stored: ~/.geode/auth.toml[/muted]\n")


def _login_set_key(rest: str) -> None:
    from core.cli import commands as _pkg

    parts = rest.split(None, 1)
    if len(parts) < 2:
        _pkg.console.print("  [warning]Usage: /login set-key <plan-id> <api-key>[/warning]\n")
        return
    plan_id, key = parts[0], parts[1].strip()

    from core.auth.profiles import AuthProfile, CredentialType
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring.container import ensure_profile_store

    registry = get_plan_registry()
    plan = registry.get(plan_id)
    if plan is None:
        _pkg.console.print(
            f"  [warning]Unknown plan: {plan_id}[/warning]  [muted](use /login add first)[/muted]\n"
        )
        return
    store = ensure_profile_store()
    name = f"{plan.id}:user"
    existing = store.get(name)
    if existing is not None:
        existing.key = key
        existing.error_count = 0
        existing.cooldown_until = 0.0
    else:
        store.add(
            AuthProfile(
                name=name,
                provider=plan.provider,
                credential_type=CredentialType.API_KEY,
                key=key,
                plan_id=plan.id,
            )
        )
    if plan.provider == "glm-coding":
        from core.llm.providers.glm import reset_glm_client

        reset_glm_client()
    _pkg._persist_auth_state()
    _pkg.console.print(
        f"  [success]Updated key[/success] for {plan.display_name}  "
        f"[muted]({_pkg._mask_key(key)})[/muted]\n"
    )


def _login_use(rest: str) -> None:
    from core.cli import commands as _pkg

    plan_id = rest.strip()
    if not plan_id:
        _pkg.console.print("  [warning]Usage: /login use <plan-id>[/warning]\n")
        return
    from core.llm.strategies.plan_registry import get_plan_registry

    registry = get_plan_registry()
    plan = registry.get(plan_id)
    if plan is None:
        _pkg.console.print(f"  [warning]Unknown plan: {plan_id}[/warning]\n")
        return
    # Pin this plan ahead of any other for a few common models in its provider
    model_hints = {
        "glm-coding": ["glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7-flash"],
        "glm": ["glm-5.1", "glm-5", "glm-5-turbo"],
        "openai": ["gpt-5.4", "gpt-5.4-mini"],
        "openai-codex": ["gpt-5.3-codex", "gpt-5.4-mini"],
        "anthropic": ["claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6"],
    }
    for model in model_hints.get(plan.provider, []):
        existing = [pid for pid in registry.get_routing(model) if pid != plan.id]
        registry.set_routing(model, [plan.id, *existing])
    _pkg._persist_auth_state()
    _pkg.console.print(
        f"  [success]Activated[/success] {plan.display_name} for {plan.provider} models.\n"
    )


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
    from core.cli import commands as _pkg
    from core.wiring.container import ensure_profile_store

    name = rest.strip()
    if not name:
        _pkg.console.print("  [warning]Usage: /login use-profile <profile-name>[/warning]\n")
        return
    store = ensure_profile_store()
    profile = store.get(name)
    if profile is None:
        _pkg.console.print(
            f"  [warning]Unknown profile: {name}[/warning]"
            "  [muted](run /login to list all profiles)[/muted]\n"
        )
        return
    store.set_active(name)
    _pkg._persist_auth_state()
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
    from core.cli import commands as _pkg
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()

    # X1.1 mutating subcommands.
    parts = rest.split()
    if parts and parts[0].lower() in ("set", "clear"):
        action = parts[0].lower()
        if len(parts) < 2:
            _pkg.console.print(
                "  [warning]Usage: /login order set <provider> <name1> <name2> …[/warning]\n"
                "  [warning]       /login order clear <provider>[/warning]\n"
            )
            return
        provider = parts[1]
        if action == "clear":
            store.clear_auth_order(provider)
            _pkg._persist_auth_state()
            _pkg.console.print(
                f"  [success]Cleared auth order[/success]  {provider}  "
                "[muted](rotator falls back to LRU/type-priority)[/muted]\n"
            )
            return
        names = parts[2:]
        if not names:
            _pkg.console.print(
                "  [warning]Usage: /login order set <provider> <name1> "
                "[<name2> …][/warning]\n"
                "  [muted]Pass at least one profile name; use "
                "`/login order clear <provider>` to drop a pin.[/muted]\n"
            )
            return
        try:
            store.set_auth_order(provider, names)
        except (KeyError, ValueError) as exc:
            _pkg.console.print(f"  [warning]{exc}[/warning]\n")
            return
        _pkg._persist_auth_state()
        _pkg.console.print(
            f"  [success]Pinned auth order[/success]  {provider}  "
            f"[muted]({' → '.join(names)})[/muted]\n"
        )
        return

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
        _pkg.console.print(f"  [warning]No profiles for provider {target_provider!r}.[/warning]\n")
        return

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
        _pkg.console.print("  [warning]Usage: /login remove <plan-id>[/warning]\n")
        return
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.wiring.container import ensure_profile_store

    registry = get_plan_registry()
    if not registry.remove(plan_id):
        _pkg.console.print(f"  [warning]Plan not found: {plan_id}[/warning]\n")
        return
    store = ensure_profile_store()
    for p in list(store.list_all()):
        if p.plan_id == plan_id:
            store.remove(p.name)
    _pkg._persist_auth_state()
    _pkg.console.print(f"  [success]Removed plan and its profiles:[/success] {plan_id}\n")


def _login_route(rest: str) -> None:
    from core.cli import commands as _pkg

    parts = rest.split()
    if len(parts) < 2:
        _pkg.console.print(
            "  [warning]Usage: /login route <model> <plan-id> [<plan-id>...][/warning]\n"
        )
        return
    model, plan_ids = parts[0], parts[1:]
    from core.llm.strategies.plan_registry import get_plan_registry

    registry = get_plan_registry()
    unknown = [pid for pid in plan_ids if registry.get(pid) is None]
    if unknown:
        _pkg.console.print(f"  [warning]Unknown plan(s): {', '.join(unknown)}[/warning]\n")
        return
    registry.set_routing(model, plan_ids)
    _pkg._persist_auth_state()
    _pkg.console.print(f"  [success]Routing[/success] {model} → " + " → ".join(plan_ids) + "\n")


def _login_quota() -> None:
    from core.cli import commands as _pkg
    from core.llm.strategies.plan_registry import get_plan_registry

    registry = get_plan_registry()
    plans = registry.list_all()
    quoted = [p for p in plans if p.quota is not None]
    if not quoted:
        _pkg.console.print("  [muted]No quota-bearing plans registered.[/muted]\n")
        return
    _pkg.console.print("\n  [header]Plan Quota[/header]")
    for plan in quoted:
        usage = registry.usage_for(plan.id)
        assert plan.quota is not None
        reset_in = usage.seconds_until_reset()
        reset_label = f"{reset_in // 60}m" if reset_in > 0 else "ready"
        _pkg.console.print(
            f"  {plan.id:<24} "
            f"used {int(usage.weighted_calls):>4}/{plan.quota.max_calls} "
            f"· resets in {reset_label}"
            + (
                "  [muted](weights: "
                + ", ".join(f"{m}×{int(w)}" for m, w in plan.quota.model_weights.items())
                + ")[/muted]"
                if plan.quota.model_weights
                else ""
            )
        )
    _pkg.console.print()


# ---------------------------------------------------------------------------
# /login health — per-profile eligibility verdict + actionable suggestion
# ---------------------------------------------------------------------------


_HEALTH_SUGGESTIONS: dict[str, str] = {
    "ok": "Ready to dispatch.",
    "missing_key": "Key/token is empty. Run `/login add` (interactive) or "
    "`/login set-key <plan> <key>` to populate.",
    "expired": "OAuth token past expires_at. Re-run the owning CLI's login "
    "(e.g. `claude` or `codex`) and then `/login refresh` so GEODE "
    "picks the new token up.",
    "cooling_down": "Backoff after consecutive failures. The verdict line "
    "shows the cooldown deadline — wait it out or "
    "`/login use <other-plan>` to switch providers in the meantime.",
    "disabled": "Manually disabled (`/login remove <plan>` to delete, or "
    "edit `~/.geode/auth.toml` to flip `disabled=false`).",
    "provider_mismatch": "Profile belongs to a different provider — info only, no action needed.",
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
    from core.auth.profiles import EligibilityResult
    from core.cli import commands as _pkg
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()
    profiles = store.list_all()
    if not profiles:
        _pkg.console.print(
            "  [muted]No profiles registered. Run `/login add` to create one.[/muted]\n"
        )
        return

    target = rest.strip()

    # When the operator names a profile, narrow down — same matching the
    # rest of the login subcommands use (exact name).
    verdicts: list[EligibilityResult] = []
    seen_providers: set[str] = set()
    for profile in profiles:
        if profile.provider in seen_providers:
            continue
        seen_providers.add(profile.provider)
        verdicts.extend(store.evaluate_eligibility(profile.provider))

    if target:
        narrowed = [v for v in verdicts if v.profile_name == target]
        if not narrowed:
            _pkg.console.print(
                f"\n  [warning]No profile named[/warning] {target}\n"
                "  [muted]Run `/login` to list all profiles.[/muted]\n"
            )
            return
        verdicts = narrowed

    _pkg.console.print("\n  [header]Eligibility[/header]")
    for v in verdicts:
        code = v.reason_code
        badge = "[success]ok[/success]" if v.eligible else f"[warning]{code}[/warning]"
        _pkg.console.print(f"  {badge:<24} [bold]{v.profile_name}[/bold]")
        if v.detail:
            _pkg.console.print(f"    [muted]{v.detail}[/muted]")
        suggestion = _HEALTH_SUGGESTIONS.get(code, "")
        if suggestion:
            _pkg.console.print(f"    → {suggestion}")
    _pkg.console.print()


# ---------------------------------------------------------------------------
# /login providers — variant registry + equivalence map view
# ---------------------------------------------------------------------------


def _login_providers() -> None:
    """Render provider variants + which providers share a model family.

    X3 — pre-fix the equivalence map (``openai ↔ openai-codex``,
    ``glm ↔ glm-coding``) lived only in ``core.llm.registry``; users
    saw the ``provider`` label in ``/login`` / ``/model`` and had no way
    to discover that a Codex subscription token and an OpenAI PAYG key both
    serve a ``gpt-5.x`` request, or that a GLM Coding key shadows the
    PAYG endpoint. Surfacing the table makes the policy auditable
    without grep'ing ``PROVIDER_EQUIVALENCE`` in code.
    """
    from core.cli import commands as _pkg
    from core.llm.registry import PROVIDER_EQUIVALENCE, PROVIDER_VARIANTS
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

    _pkg.console.print("\n  [header]Equivalence map[/header]")
    _pkg.console.print(
        "  [muted]Resolving to the left key tries the right list in order; "
        "a credential from any sibling can serve the request.[/muted]"
    )
    # Singletons (only the provider itself) are noise — show only true
    # equivalence classes with ≥ 2 members.
    multi_member = {k: v for k, v in PROVIDER_EQUIVALENCE.items() if len(v) > 1}
    if not multi_member:
        _pkg.console.print("  [muted]No equivalence classes registered.[/muted]")
    else:
        # Render each class once (de-dup by tuple of members, preserve
        # the dict-insertion entry-point as the key shown).
        seen: set[tuple[str, ...]] = set()
        for base in multi_member:
            members = tuple(PROVIDER_EQUIVALENCE[base])
            if members in seen:
                continue
            seen.add(members)
            _pkg.console.print(f"  [bold]{base:<16}[/bold] → " + " · ".join(members))
    _pkg.console.print()
