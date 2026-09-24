"""Judgment-engine selection inside the existing /model operator surface."""

from __future__ import annotations

import sys
from typing import Any

from core.config.judgment import configure_judgment, judgment_status, resolve_judgment_route


def cmd_judgment(args: str, *, interactive: bool = True) -> dict[str, Any]:
    """Select LLM/Jev without changing the generative root model or its effort."""
    from core.cli import commands as package
    from core.config import settings

    selection = args.strip().lower()
    if not selection and interactive and sys.stdin.isatty():
        from core.cli.effort_picker import pick_model_and_effort

        profiles: list[tuple[str, str, str, str, bool, str | None]] = [
            ("llm", "judgment", "LLM · current generative route", "model", True, None)
        ]
        for provider, label in (("typesafe", "TypeSafe"), ("openrouter", "OpenRouter")):
            candidate = settings.model_copy(
                update={"judgment_engine": "jev", "jev_provider": provider}
            )
            profiles.append(
                (
                    provider,
                    "judgment",
                    f"Jev · {label}",
                    "input",
                    bool(resolve_judgment_route(candidate)),
                    None,
                )
            )
        current = judgment_status()
        active = current["provider"] if current["effective_engine"] == "jev" else "llm"
        result = pick_model_and_effort(profiles, active, "", role_has_effort={"primary": False})
        if result.cancelled:
            return {"status": "cancelled", **current}
        selection = result.model_id
    if not selection or selection == "status":
        status = {"status": "ok", **judgment_status()}
    elif selection in {"llm", "jev", "typesafe", "openrouter"}:
        try:
            status = {
                "status": "ok",
                **configure_judgment(
                    "llm" if selection == "llm" else "jev",
                    provider=selection if selection in {"typesafe", "openrouter"} else None,
                ),
            }
        except (ValueError, OSError) as exc:
            status = {"status": "error", "error": str(exc), **judgment_status()}
    else:
        status = {"status": "error", "error": "Choose llm, jev, typesafe, or openrouter"}
    if status["status"] == "error":
        package.console.print(f"  Judgment selection not applied: {status['error']}")
    else:
        route = status.get("provider") or "existing LLM route"
        package.console.print(f"  Judgment: {status['effective_engine']} · {route}")
        package.console.print("  Reflection: every round and before the final response.")
        if status.get("reason"):
            package.console.print("  Jev key unavailable; using LLM.")
    package.console.print("  /model judgment llm | jev | typesafe | openrouter")
    return status
