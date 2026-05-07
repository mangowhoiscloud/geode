"""Welcome screen rendering for the GEODE thin CLI.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split).
"""

from __future__ import annotations

from pathlib import Path

from core import __version__
from core.cli.onboarding import env_setup_wizard
from core.cli.session_state import _set_readiness
from core.config import settings
from core.lifecycle.startup import (
    ReadinessReport,
    auto_generate_env,
    check_readiness,
    setup_project_memory,
    setup_user_profile,
)
from core.ui.console import console


def _render_welcome_brand() -> None:
    """Render animated Claude Code-style branding with axolotl mascot."""
    from core.ui.mascot import play_mascot_animation

    cwd = str(Path.cwd())
    play_mascot_animation(version=__version__, model=settings.model, cwd=cwd)

    # Show detected project environment
    try:
        from core.utils.project_detect import detect_project_type, get_harness_summary

        info = detect_project_type(Path.cwd())
        parts: list[str] = []
        if info.project_type != "unknown":
            parts.append(f"[label]{info.project_type}[/label]")
            if info.pkg_mgr:
                parts.append(f"({info.pkg_mgr})")
        if info.harnesses:
            parts.append(f"[muted]harness:[/muted] {get_harness_summary(info.harnesses)}")
        if parts:
            console.print(f"  {' '.join(parts)}")
    except Exception:  # noqa: S110
        pass  # Startup display — never block on detection failure


def _render_readiness_compact(report: ReadinessReport) -> None:
    """Render readiness as a compact block."""
    ready = [c for c in report.capabilities if c.available]
    not_ready = [c for c in report.capabilities if not c.available]

    if ready:
        names = "  ".join(f"[success]✓[/success] {c.name}" for c in ready)
        console.print(f"  {names}")
    if not_ready:
        for c in not_ready:
            hint = f" [muted]({c.reason})[/muted]" if c.reason else ""
            console.print(f"  [warning]✗[/warning] {c.name}{hint}")

    if report.blocked:
        console.print()
        console.print("  [warning]API key not configured — key registration required[/warning]")

    console.print()


def _suppress_noisy_warnings() -> None:
    """Suppress known noisy warnings. Delegates to terminal module."""
    from core.cli.terminal import suppress_noisy_warnings

    suppress_noisy_warnings()


def _welcome_screen() -> None:
    """Show Claude Code-style welcome screen with readiness check."""
    _suppress_noisy_warnings()
    _render_welcome_brand()

    # Auto-generate .env from .env.example (placeholder → empty)
    auto_generate_env()

    # v0.54.0 — proactive subscription OAuth detection. If the user already
    # ran ``codex auth login``, GEODE picks up the token from
    # ``~/.codex/auth.json`` and skips the wizard entirely. Anthropic OAuth
    # is intentionally excluded (Anthropic ToS prohibits third-party
    # reuse — see ``core/lifecycle/container.py:271``).
    from core.lifecycle.startup import _has_any_llm_key, detect_subscription_oauth

    if not _has_any_llm_key():
        oauth_provider = detect_subscription_oauth()
        if oauth_provider:
            console.print(f"  [success]OAuth detected: {oauth_provider}[/success]\n")
        else:
            env_path = Path(".env")
            if not env_path.exists():
                env_setup_wizard()

    # OpenClaw gateway:startup — readiness check
    readiness = check_readiness()
    _set_readiness(readiness)
    _render_readiness_compact(readiness)

    # v0.54.0 — surface dry-run mode explicitly. Pre-fix the user could
    # land on a dry-run prompt thinking it was a real LLM call.
    if readiness.force_dry_run:
        console.print(
            "  [warning]Running in dry-run mode (fixture data, no LLM).[/warning]\n"
            "  [muted]Run [cyan]geode setup[/cyan] to add a credential.[/muted]\n"
        )

    # OpenClaw boot-md — initialize project memory if absent
    setup_project_memory()

    # Tier 0.5 — initialize user profile if absent
    setup_user_profile()

    console.print(
        "  [muted]/help[/muted] for commands  [muted]·[/muted]  [muted]type naturally[/muted]"
    )
    console.print()
