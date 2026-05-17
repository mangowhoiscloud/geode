"""System management tool handlers: status, help, model, key, auth, login."""

from __future__ import annotations

import logging
from typing import Any

from core.ui.console import console

log = logging.getLogger(__name__)


def _build_system_handlers(
    readiness: Any,
    force_dry: bool,
    mcp_manager: Any,
) -> dict[str, Any]:
    """Build system management tool handlers."""
    from core.cli import _set_readiness
    from core.cli.commands import cmd_key, cmd_login, cmd_model, show_help
    from core.cli.onboarding import render_readiness
    from core.wiring.startup import check_readiness

    def handle_show_help(**_kwargs: Any) -> dict[str, Any]:
        show_help()
        # Generic command list — domain-specific entries flow through
        # COMMAND_MAP (which the active domain extends via
        # ``register_slash_commands`` at bootstrap). We surface the
        # registered slashes so the LLM has the same view as ``/help``.
        from core.cli.commands import COMMAND_MAP

        commands = sorted(COMMAND_MAP.keys())
        return {"status": "ok", "action": "help", "commands": commands}

    def handle_check_status(**_kwargs: Any) -> dict[str, Any]:
        from core import __version__ as geode_version
        from core.config import settings
        from core.domains.port import get_domain_or_none

        # Fixture count is domain-specific — sourced via DomainPort.
        domain = get_domain_or_none()
        fixture_count = 0
        if domain is not None:
            try:
                fixture_count = len(domain.list_fixtures())
            except Exception:
                log.debug("Domain list_fixtures() failed", exc_info=True)

        ant_ok = bool(settings.anthropic_api_key)
        oai_ok = bool(settings.openai_api_key)
        mode = "full_llm" if (readiness and not readiness.force_dry_run) else "dry_run"

        console.print()
        console.print(f"  [header]GEODE v{geode_version}[/header]")
        console.print(f"  Model: [bold]{settings.model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_status = "[green]configured[/green]" if ant_ok else "[red]not set[/red]"
        oai_status = "[green]configured[/green]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic API: {ant_status}")
        console.print(f"  OpenAI API: {oai_status}")
        console.print(f"  Mode: [bold]{mode}[/bold]")
        console.print(f"  Fixtures: [bold]{fixture_count} subjects[/bold]")

        # MCP status
        mcp_status = (
            mcp_manager.get_status()
            if mcp_manager is not None
            else {"active": [], "active_count": 0, "available_inactive": [], "catalog_total": 0}
        )

        console.print()
        console.print("  [header]MCP Servers[/header]")
        active = mcp_status["active"]
        if active:
            for srv in active:
                desc = f" -- {srv['description']}" if srv["description"] else ""
                console.print(f"    [green]OK[/green] {srv['name']} [dim]{desc}[/dim]")
        else:
            console.print("    [muted]No active servers[/muted]")

        console.print()

        return {
            "status": "ok",
            "action": "status",
            "version": geode_version,
            "model": settings.model,
            "ensemble": settings.ensemble_mode,
            "anthropic_configured": ant_ok,
            "openai_configured": oai_ok,
            "mode": mode,
            "fixture_count": fixture_count,
            "mcp_status": mcp_status,
        }

    def handle_switch_model(**kwargs: Any) -> dict[str, Any]:
        from core.config import settings

        model_hint = kwargs.get("model_hint", "")
        # Only update settings — do NOT call loop.update_model_async() here.
        # The AgenticLoop checks for model drift at the start of each round
        # and applies the change safely between LLM calls (not mid-call).
        cmd_model(model_hint)
        return {
            "status": "ok",
            "action": "model_deferred",
            "current_model": settings.model,
            "ensemble": settings.ensemble_mode,
            "note": "Model change applied. Will take effect on next round.",
        }

    def handle_set_api_key(**kwargs: Any) -> dict[str, Any]:
        from core.config import settings

        key_value = kwargs.get("key_value", "")
        changed = cmd_key(key_value)
        if changed:
            new_readiness = check_readiness()
            _set_readiness(new_readiness)
            render_readiness(new_readiness)
        return {
            "status": "ok",
            "action": "key",
            "changed": changed,
            "anthropic_configured": bool(settings.anthropic_api_key),
            "openai_configured": bool(settings.openai_api_key),
        }

    def handle_manage_auth(**kwargs: Any) -> dict[str, Any]:
        """Deprecated — redirects to ``manage_login``.

        PR #C (2026-05-17) removed the standalone ``/auth`` slash
        command; this LLM tool entry stays as a backwards-compat
        adapter so existing prompts that still call ``manage_auth``
        keep working. The body forwards ``sub_action`` to
        ``handle_manage_login`` as the ``subcommand`` argument.
        """
        sub_action = (kwargs.get("sub_action") or "").strip().lower()
        # Map legacy /auth subactions to /login equivalents
        legacy_to_login = {"": "status", "add": "add", "remove": "remove", "set": "source"}
        first_token = sub_action.split(None, 1)[0] if sub_action else ""
        login_sub = legacy_to_login.get(first_token, "status")
        login_args = ""
        if " " in sub_action:
            login_args = sub_action.split(None, 1)[1]
        return handle_manage_login(subcommand=login_sub, args=login_args)

    def handle_manage_login(**kwargs: Any) -> dict[str, Any]:
        """Natural-language entry to /login (Plans + Profiles + OAuth + Routing)."""

        sub = (kwargs.get("subcommand") or "status").strip().lower()
        args = (kwargs.get("args") or "").strip()
        login_input = "" if sub in ("", "status", "list", "ls") else f"{sub} {args}".strip()
        cmd_login(login_input)

        try:
            from core.llm.routing.plan_registry import get_plan_registry
            from core.wiring.container import ensure_profile_store

            store = ensure_profile_store()
            registry = get_plan_registry()
            plans_payload = []
            for plan in registry.list_all():
                usage = registry.usage_for(plan.id)
                plans_payload.append(
                    {
                        "id": plan.id,
                        "provider": plan.provider,
                        "kind": plan.kind.value,
                        "display_name": plan.display_name,
                        "base_url": plan.base_url,
                        "subscription_tier": plan.subscription_tier,
                        "quota_max": (plan.quota.max_calls if plan.quota else None),
                        "quota_used": int(usage.weighted_calls),
                    }
                )
            # v0.51.0 — annotate each profile with its current eligibility
            # verdict per the profile's own provider. This lets the LLM see
            # *why* a credential is unusable (cooldown / expired / disabled
            # / missing key) without needing a second tool call.
            #
            # Skip cross-provider iterations: ``evaluate_eligibility(prov)``
            # returns a PROVIDER_MISMATCH verdict for every profile whose
            # provider != prov, but those are noise here — we want each
            # profile's verdict against its OWN provider. Without this
            # filter the dict-key ``(name, profile.provider)`` collides
            # across iterations and the last-iterated provider's mismatch
            # verdict overwrites the real one, so a healthy PAYG profile
            # surfaces as ``eligible=False / provider_mismatch`` to the
            # LLM and the dashboard. Mirrors the same filter applied in
            # ``credential_breadcrumb.format``.
            from core.auth.profiles import ProfileRejectReason

            verdict_index: dict[tuple[str, str], tuple[bool, str, str]] = {}
            for prov in {p.provider for p in store.list_all()}:
                for v in store.evaluate_eligibility(prov):
                    if v.reason is ProfileRejectReason.PROVIDER_MISMATCH:
                        continue
                    verdict_index[(v.profile_name, v.provider)] = (
                        v.eligible,
                        v.reason_code,
                        v.detail,
                    )

            profiles_payload = []
            for p in store.list_all():
                eligible, reason, detail = verdict_index.get(
                    (p.name, p.provider), (False, "unknown", "")
                )
                profiles_payload.append(
                    {
                        "name": p.name,
                        "provider": p.provider,
                        "type": p.credential_type.value,
                        "plan_id": p.plan_id or None,
                        "managed_by": p.managed_by or None,
                        "eligible": eligible,
                        "reason": reason,
                        "reason_detail": detail,
                    }
                )
            routing_payload = registry.all_routing()
        except Exception:
            plans_payload = []
            profiles_payload = []
            routing_payload = {}

        return {
            "status": "ok",
            "action": "login",
            "subcommand": sub or "status",
            "plans": plans_payload,
            "profiles": profiles_payload,
            "routing": routing_payload,
        }

    def handle_doctor_slack(**_kwargs: Any) -> dict[str, Any]:
        from core.cli.doctor import format_doctor_report, run_doctor_slack

        report = run_doctor_slack()
        return {"text": format_doctor_report(report), "raw": report}

    return {
        "show_help": handle_show_help,
        "check_status": handle_check_status,
        "switch_model": handle_switch_model,
        "set_api_key": handle_set_api_key,
        "manage_auth": handle_manage_auth,
        "manage_login": handle_manage_login,
        "doctor_slack": handle_doctor_slack,
    }
