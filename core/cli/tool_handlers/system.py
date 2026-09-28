"""System management tool handlers: status, help, model and nonsecret login actions."""

from __future__ import annotations

from typing import Any

from core.tools.handlers.registration import UniqueEntries
from core.ui.console import console


def _build_system_handlers(
    mcp_manager: Any,
    command_registry: Any = None,
) -> UniqueEntries[str, Any]:
    """Build system management tool handlers."""
    from core.cli.commands import show_help
    from core.wiring.startup import check_readiness

    def handle_show_help(**_kwargs: Any) -> dict[str, Any]:
        show_help(command_registry)
        # Surface the registered slashes so the LLM has the same view as /help.
        from core.cli.commands import COMMAND_MAP
        from core.cli.routing import COMMAND_REGISTRY

        registered = COMMAND_REGISTRY if command_registry is None else command_registry
        commands = sorted(COMMAND_MAP.keys() | registered.keys())
        return {"status": "ok", "action": "help", "commands": commands}

    def handle_check_status(**kwargs: Any) -> dict[str, Any]:
        from core import __version__ as geode_version
        from core.cli.session_state import _get_readiness
        from core.config import settings

        owner = getattr(kwargs.get("_tool_context"), "agent_loop", None)
        model_config = owner._model_settings.model_dump() if owner is not None else None
        model = owner.model if owner is not None else settings.model
        from core.llm.routing import model_available
        from core.wiring.startup import has_available_llm_credential

        ant_ok = has_available_llm_credential("anthropic")
        oai_ok = has_available_llm_credential("openai")
        selected_available = model_available(
            model, source=owner._model_settings.source if owner is not None else None
        )
        # Preserve explicit request policy (including audit overrides), but do
        # not infer dry-run from a native host's missing CLI bootstrap.
        readiness = _get_readiness()
        if readiness is not None:
            dry_run = readiness.force_dry_run
        elif owner is not None:
            dry_run = not selected_available
        else:
            dry_run = check_readiness().force_dry_run
        mode = "dry_run" if dry_run else "full_llm"

        console.print()
        console.print(f"  [header]GEODE v{geode_version}[/header]")
        console.print(f"  Model: [bold]{model}[/bold]")
        console.print(f"  Ensemble: [bold]{settings.ensemble_mode}[/bold]")
        ant_status = "[success]configured[/success]" if ant_ok else "[red]not set[/red]"
        oai_status = "[success]configured[/success]" if oai_ok else "[red]not set[/red]"
        console.print(f"  Anthropic default route: {ant_status}")
        console.print(f"  OpenAI default route: {oai_status}")
        console.print(
            f"  Selected model route: {'available' if selected_available else 'unavailable'}"
        )
        console.print(f"  Mode: [bold]{mode}[/bold]")

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
                console.print(f"    [success]OK[/success] {srv['name']} [dim]{desc}[/dim]")
        else:
            console.print("    [muted]No active servers[/muted]")

        console.print()

        return {
            "status": "ok",
            "action": "status",
            "version": geode_version,
            "model": model,
            "model_available": selected_available,
            "scope": "session" if owner is not None else "defaults",
            "model_config": model_config,
            "ensemble": settings.ensemble_mode,
            "anthropic_configured": ant_ok,
            "openai_configured": oai_ok,
            "mode": mode,
            "mcp_status": mcp_status,
        }

    async def handle_switch_model(**kwargs: Any) -> dict[str, Any]:
        from core.agent.loop._model_switching import stage_session_model_config
        from core.cli.commands._state import get_model_profiles
        from core.cli.commands.model import resolve_model_hint
        from core.config import _resolve_provider
        from core.llm.routing import infer_source
        from core.tools.base import tool_error

        loop = getattr(kwargs.get("_tool_context"), "agent_loop", None)
        if loop is None:
            return tool_error("Model selection requires an owning session", error_type="dependency")
        current = loop._model_settings
        hint = str(kwargs.get("model_hint", "")).strip()
        role = kwargs.get("role", "primary")
        if not hint or hint == "status":
            return {"status": "ok", "scope": "session", "model_config": current.model_dump()}
        try:
            if role == "judgment":
                if hint not in {"llm", "jev", "typesafe", "openrouter"}:
                    raise ValueError("Choose llm, jev, typesafe, or openrouter")
                candidate = current.updated(
                    {
                        "judgment_engine": "llm" if hint == "llm" else "jev",
                        "jev_provider": hint
                        if hint in {"typesafe", "openrouter"}
                        else current.jev_provider,
                    }
                )
            elif role == "primary":
                selected = resolve_model_hint(
                    hint,
                    get_model_profiles(
                        configured_model_ids=(
                            current.model,
                            current.reflection_model,
                            current.judge_model,
                        ),
                        openai_source=current.source,
                    ),
                )
                provider = _resolve_provider(selected.id)
                source = (
                    current.source
                    if provider == loop._provider
                    else infer_source(provider, model=selected.id)
                )
                candidate = current.updated({"model": selected.id, "source": source})
            else:
                raise ValueError("Choose primary or judgment")
            if not stage_session_model_config(loop, candidate):
                return {"status": "applied", "changed": False, "model_config": current.model_dump()}
            return {
                "status": "pending",
                "scope": "session",
                "model_config": candidate.model_dump(),
                "note": "Validated; applies to this session after the complete tool batch.",
            }
        except (RuntimeError, ValueError) as exc:
            return tool_error(str(exc), error_type="validation")

    def handle_manage_login(**kwargs: Any) -> dict[str, Any]:
        """Expose credential-free status and admitted plan/source changes."""
        from core.cli.commands.login import (
            INTERACTIVE_LOGIN_SUBCOMMANDS,
            build_login_snapshot,
            run_login,
        )
        from core.slash_routing import DAEMON_LOGIN_SUBCOMMANDS
        from core.tools.base import classify_tool_exception, tool_error

        sub = (kwargs.get("subcommand") or "status").strip().lower()
        args = (kwargs.get("args") or "").strip()
        if sub == "source":
            from core.agent.loop._model_switching import stage_session_model_config
            from core.cli.commands.login import session_source_changes

            loop = getattr(kwargs.get("_tool_context"), "agent_loop", None)
            if loop is None:
                return tool_error(
                    "Source selection requires an owning session", error_type="dependency"
                )
            try:
                provider, source = args.lower().split()
                changes = session_source_changes(loop._model_settings, provider, source)
                if not changes:
                    raise ValueError("The provider is not used by this session")
                candidate = loop._model_settings.updated(changes)
                changed = stage_session_model_config(loop, candidate)
                return {
                    "status": "pending" if changed else "applied",
                    "changed": changed,
                    "scope": "session",
                    "model_config": candidate.model_dump(),
                }
            except (RuntimeError, ValueError) as exc:
                return tool_error(str(exc), error_type="validation")
        if sub in INTERACTIVE_LOGIN_SUBCOMMANDS or sub in {"set-key", "setkey", "key"}:
            # Interactive attempts outlive this tool call's deadline and cannot be
            # cancelled from here; the user's terminal owns them.
            return tool_error(
                "Credential entry and sign-in require the user's terminal. "
                "Ask the user to run `/login add` there; never request or pass a key in chat.",
                error_type="validation",
            )
        if sub not in DAEMON_LOGIN_SUBCOMMANDS:
            return tool_error("Unsupported nonsecret login action", error_type="validation")
        login_input = "" if sub in ("status", "list", "ls") else f"{sub} {args}".strip()
        try:
            run_login(login_input)
        except (ValueError, OSError) as exc:
            return classify_tool_exception(exc, "manage_login")
        return {
            "status": "ok",
            "action": "login",
            "subcommand": sub or "status",
            **build_login_snapshot(),
        }

    def handle_doctor_slack(**_kwargs: Any) -> dict[str, Any]:
        from core.cli.doctor import format_doctor_report, run_doctor_slack

        report = run_doctor_slack()
        return {"text": format_doctor_report(report), "raw": report}

    return UniqueEntries[str, Any](
        (
            ("show_help", handle_show_help),
            ("check_status", handle_check_status),
            ("switch_model", handle_switch_model),
            ("manage_login", handle_manage_login),
            ("doctor_slack", handle_doctor_slack),
        )
    )
