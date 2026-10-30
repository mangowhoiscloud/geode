"""Welcome screen rendering for the GEODE thin CLI.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split).
"""

from __future__ import annotations

from pathlib import Path

import typer

from core import __version__
from core.cli.onboarding import clear_dry_run_opt_in, dry_run_opted_in, env_setup_wizard
from core.cli.session_state import _set_readiness
from core.ui.console import console
from core.wiring.startup import (
    ReadinessReport,
    check_readiness,
)


def _render_welcome_brand() -> None:
    """Render the Geodi mascot branding block."""
    from core.config.session import resolve_initial_model
    from core.ui.mascot import render_mascot

    model, _source = resolve_initial_model()
    render_mascot(version=__version__, model=model, cwd=str(Path.cwd()))


def _render_readiness_compact(report: ReadinessReport) -> None:
    """Render readiness PROBLEMS only — silence means healthy."""
    not_ready = [c for c in report.capabilities if c.required and not c.available]
    if not not_ready and not report.blocked:
        return

    for c in not_ready:
        hint = f" [muted]({c.reason})[/muted]" if c.reason else ""
        console.print(f"  [warning]✗[/warning] {c.name}{hint}")

    if report.blocked:
        console.print()
        console.print("  [muted]Use /login to connect an account or API key.[/muted]")

    console.print()


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen with readiness check."""
    readiness = check_readiness()
    if readiness.has_api_key:
        clear_dry_run_opt_in()
    elif not dry_run_opted_in():
        if not env_setup_wizard():
            raise typer.Exit(1)
        # Reinspect only after setup can have changed credential state.
        readiness = check_readiness()

    _render_welcome_brand()
    _set_readiness(readiness)
    _render_readiness_compact(readiness)

    if readiness.blocked:
        console.print(
            "  [muted]Not connected. Setup and session commands are available; "
            "model requests need a usable account.[/muted]\n"
        )
