"""Legacy terminal key entry; auth.toml owns operator-managed API keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.cli.onboarding import clear_dry_run_opt_in

if TYPE_CHECKING:
    from core.cli.commands._state import ModelProfile


def cmd_key(args: str) -> bool:
    """Render an interactive key change; machine callers use ``run_key``."""
    from rich.markup import escape

    from core.cli import commands as _pkg
    from core.observability.redaction import redact_secrets

    try:
        return run_key(args)
    except (ValueError, OSError) as exc:
        detail = escape(redact_secrets(str(exc)))
        _pkg.console.print(f"  [warning]Credential update failed: {detail}[/warning]\n")
        return False


def run_key(args: str) -> bool:
    """Handle /key command (legacy; prefer /login).

    Return whether a key was changed; rejected or incomplete changes raise.
    """
    from core.auth.auth_toml import save_api_key
    from core.cli import commands as _pkg

    parts = args.split(None, 1) if args else []

    if not parts:
        _pkg.console.print(
            "\n  [muted]/key redirects to /login. Use /login add for hidden key input, "
            "or /login set-key <plan-id> to update an existing plan.[/muted]"
        )
        _pkg.cmd_login("")
        return False

    explicit = parts[0].lower() in {"openai", "openrouter", "glm"}
    if explicit:
        provider = parts[0].lower()
        if len(parts) < 2:
            raise ValueError(f"Usage: /key {provider} <API_KEY>")
        value = parts[1].strip()
    else:
        value = args.strip()
        if value.startswith("sk-ant-"):
            provider = "anthropic"
        elif value.startswith("sk-or-v1-"):
            provider = "openrouter"
        elif value.startswith("sk-"):
            provider = "openai"
        elif _pkg._is_glm_key(value):
            provider = "glm"
        else:
            raise ValueError(
                "Unrecognized key prefix. Use /key <provider> <API_KEY> or /login add."
            )
    if not value or any(char.isspace() for char in value):
        raise ValueError("API key must be nonempty and contain no whitespace.")

    plan = save_api_key(value, provider=provider)
    clear_dry_run_opt_in()
    _pkg.console.print(f"  [success]{plan.display_name} API key set[/success]")
    if not explicit:
        _pkg.console.print(
            "  [muted]Tip: /login add to manage plans and subscription sign-in.[/muted]"
        )
    _pkg.console.print()
    return True


def _check_provider_key(selected: ModelProfile) -> None:
    """Warn using the same model/source route as request admission."""
    from core.cli import commands as _pkg
    from core.llm.routing import model_available
    from core.wiring.container import ensure_profile_store

    ensure_profile_store()
    if not model_available(selected.id):
        _pkg.console.print(
            f"  [warning]Warning: No usable credential route for {selected.id}. "
            "Check /login and the selected source.[/warning]"
        )
