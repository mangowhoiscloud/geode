"""Interactive onboarding surfaces — CLI half of the v0.86.0 split.

Originally lived in ``core/cli/startup.py``. v0.86.0 split that module by
responsibility: pure inspection / IO / dataclasses (now in
``core/lifecycle/startup.py``) versus the interactive wizard surfaces
(this file). Functions here drive ``console.input``/``console.print``
loops and dispatch to ``/login`` and ``/key`` slash commands, so they
must NOT be called from headless processes (serve, IPC poller).

Public surface:
  * ``env_setup_wizard`` — top-level three-branch menu (subscription/key/skip)
  * ``render_readiness`` — pretty-printer for ``ReadinessReport``
"""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path
from typing import Any

from core.config.toml_edit import persist_toml_section
from core.paths import COMPUTER_USE_HELPER_APP_DIR
from core.ui.console import console
from core.wiring.startup import ReadinessReport

log = logging.getLogger(__name__)


def dry_run_opted_in() -> bool:
    """Return whether the user explicitly skipped credential setup."""
    from core.paths import GLOBAL_DRY_RUN_MARKER

    return GLOBAL_DRY_RUN_MARKER.exists()


def _set_dry_run_opt_in(enabled: bool) -> bool:
    """Persist or clear the credential-wizard skip choice."""
    from core.paths import GLOBAL_DRY_RUN_MARKER

    try:
        if enabled:
            GLOBAL_DRY_RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
            GLOBAL_DRY_RUN_MARKER.touch(mode=0o600)
            GLOBAL_DRY_RUN_MARKER.chmod(0o600)
        else:
            GLOBAL_DRY_RUN_MARKER.unlink(missing_ok=True)
        return True
    except OSError as exc:
        log.warning("Failed to persist dry-run setup choice: %s", exc)
        return False


def clear_dry_run_opt_in() -> bool:
    """Clear a stale skip marker after credential state changes."""
    return _set_dry_run_opt_in(False)


def __getattr__(name: str) -> Any:
    """PEP 562 lazy ``settings`` alias for legacy patch sites."""
    if name == "settings":
        from core.config import settings as _settings

        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# .env Setup Wizard
# ---------------------------------------------------------------------------


def env_setup_wizard() -> bool:
    """Interactive credential setup — runs when no usable credential is found.

    v0.54.0 — three branches: subscription guidance, API key paste, or
    skip into dry-run mode. Returns True if any credential or skip was
    chosen (i.e. the wizard need not re-run on next launch).
    """
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]Welcome to GEODE.[/bold]\n\n"
            "Pick how you want to talk to the model:\n"
            "  [cyan]1[/cyan]  ChatGPT subscription sign-in "
            "(Plus / Pro / Business / Edu / Enterprise)\n"
            "  [cyan]2[/cyan]  API key (Anthropic / OpenAI / ZhipuAI GLM)\n"
            "  [cyan]3[/cyan]  Skip — explore in dry-run mode (fixture data, no LLM)\n\n"
            "[muted]Press Ctrl+C to abort at any time.[/muted]",
            title="Setup",
            border_style="cyan",
        )
    )

    try:
        choice = console.input("  Choice [1/2/3]: ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n  [muted]Setup cancelled.[/muted]\n")
        return False

    if choice == "1":
        configured = _wizard_subscription_path()
        if configured:
            clear_dry_run_opt_in()
        return configured
    if choice == "3":
        if _set_dry_run_opt_in(True):
            console.print(
                "\n  [muted]Skipped. Run [cyan]geode setup[/cyan] later "
                "to add a credential.[/muted]\n"
            )
            return True  # persisted skip suppresses the next-launch prompt
        console.print(
            "\n  [warning]Could not save the dry-run choice under GEODE_HOME.[/warning]\n"
        )
        return False
    configured = _wizard_api_key_path()
    if configured:
        clear_dry_run_opt_in()
    return configured


def _wizard_subscription_path() -> bool:
    """Use the same native login entry point as the running terminal."""
    from core.cli.commands import cmd_login

    return cmd_login("openai")


def _wizard_api_key_path() -> bool:
    """Prompt for API keys in the terminal and commit through the auth owner."""
    import getpass

    from core.auth.auth_toml import auth_toml_path, save_api_key

    any_set = False
    providers = [
        ("Anthropic", "anthropic", "https://console.anthropic.com/settings/keys"),
        ("OpenAI", "openai", "https://platform.openai.com/api-keys"),
        ("ZhipuAI", "glm", "https://open.bigmodel.cn/usercenter/apikeys"),
    ]
    console.print("\n  [header]API keys[/header] — press Enter to skip a provider.")
    for label, provider, url in providers:
        try:
            console.print(f"\n  [label]{label}[/label] [muted]({url})[/muted]")
            # allow-direct-io: terminal-owned secret input stays hidden.
            value = getpass.getpass("  API key (hidden): ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Setup cancelled.[/muted]")
            break
        if not value:
            continue
        try:
            save_api_key(value, provider=provider)
        except (ValueError, OSError):
            console.print(f"  [error]{label} credential update failed.[/error]")
            continue
        console.print(f"  [success]{label} key saved[/success]")
        any_set = True
    if any_set:
        console.print(f"\n  [success]API keys saved[/success] [muted]({auth_toml_path()})[/muted]")
    return any_set


# ---------------------------------------------------------------------------
# run_bash command sandbox (Phase F) setup — OS-native, no Docker
# ---------------------------------------------------------------------------


def configure_bash_sandbox() -> None:
    """Interactive ``run_bash`` command-sandbox setup — runs in ``geode setup``.

    The bash sandbox (Phase F) confines each ``run_bash`` command with the
    platform's OS sandbox binary (macOS ``sandbox-exec`` / Linux ``bwrap``) so
    it cannot write outside its working dir or reach the network. It needs only
    that OS binary — **never Docker** — so it can be set up on any machine. This
    detects availability, shows the current mode, and (when available) offers to
    enable it, persisting ``[bash_sandbox] mode`` to config.toml.
    """
    from core.tools.bash_sandbox import bash_sandbox_mode, sandbox_binary_status

    mode = bash_sandbox_mode()
    binname, binpath = sandbox_binary_status()

    console.print("\n  [header]Command sandbox (run_bash)[/header]")
    console.print(
        "  [muted]Confines each shell command (no write outside cwd, no network) via the\n"
        f"  OS sandbox — needs only [cyan]{binname}[/cyan], not Docker.[/muted]"
    )

    if binpath is None:
        console.print(
            f"  [warning]{binname} not available on this host[/warning] "
            f"[muted]— leaving sandbox off (current: {mode}).[/muted]\n"
        )
        return

    console.print(f"  [muted]Available via {binpath}. Current mode: [/muted][bold]{mode}[/bold]")
    try:
        answer = (
            console.input(
                "  Enable command sandbox? [cyan]off[/cyan]/[cyan]on[/cyan]/[cyan]strict[/cyan] "
                f"(Enter = keep {mode}): "
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        console.print("  [muted]Skipped.[/muted]\n")
        return

    if not answer or answer == mode:
        console.print(f"  [muted]Kept mode = {mode}.[/muted]\n")
        return
    if answer not in {"off", "on", "strict"}:
        console.print(f"  [warning]Unknown value {answer!r} — keeping {mode}.[/warning]\n")
        return

    path = persist_toml_section("bash_sandbox", {"mode": answer})
    console.print(f"  [success]Command sandbox set to {answer}[/success] [muted]({path})[/muted]\n")


# ---------------------------------------------------------------------------
# macOS Computer Use Helper setup
# ---------------------------------------------------------------------------


def _computer_helper_build_script() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "scripts" / "macos" / "build_computer_helper.sh"


def configure_computer_use_helper() -> None:
    """Interactive macOS helper setup for CLI-safe desktop computer use.

    The helper is an app bundle so macOS TCC has a stable permission subject
    (``GEODE Computer Use Helper.app``) instead of whichever terminal/Python
    process launched GEODE. It is optional, macOS-only, and reachable from
    ``geode setup`` for both source checkouts and wheel installs.
    """
    if platform.system() != "Darwin":
        return

    from core.tools.computer_use import (
        computer_use_driver,
        computer_use_helper_path,
        computer_use_helper_status,
    )

    console.print("\n  [header]Computer Use helper (macOS)[/header]")
    console.print(
        "  [muted]Builds a small GEODE app bundle that owns Accessibility and\n"
        "  Screen Recording permissions for desktop computer-use.[/muted]"
    )

    helper = computer_use_helper_path()
    if helper is not None:
        status = computer_use_helper_status()
        ax = "trusted" if status.get("ax_trusted") else "not trusted"
        screen = "ok" if status.get("screenshot_ok") else "not granted"
        console.print(
            f"  [success]Helper installed[/success] [muted]({helper})[/muted]\n"
            f"  [muted]Accessibility: {ax}; Screen Recording: {screen}; "
            f"driver={computer_use_driver()}[/muted]"
        )
        return

    build_script = _computer_helper_build_script()
    if not build_script.exists():
        console.print(
            "  [warning]Helper build assets are missing from this install.[/warning]\n"
            "  [muted]Install from a GEODE source checkout or a wheel that includes "
            "scripts/macos/.[/muted]\n"
        )
        return

    try:
        answer = (
            console.input(
                "  Build and enable GEODE Computer Use Helper now? [cyan]y[/cyan]/[cyan]N[/cyan]: "
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        console.print("  [muted]Skipped.[/muted]\n")
        return

    if answer not in {"y", "yes"}:
        console.print("  [muted]Skipped.[/muted]\n")
        return

    try:
        proc = subprocess.run(  # noqa: S603
            [str(build_script), str(COMPUTER_USE_HELPER_APP_DIR)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        console.print(f"  [warning]Helper build failed:[/warning] {exc}\n")
        return

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        console.print(f"  [warning]Helper build failed:[/warning] {detail}\n")
        return

    helper_bin = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    updates = {"driver": "helper"}
    if helper_bin:
        updates["helper_path"] = helper_bin
    path = persist_toml_section("computer_use", updates)
    console.print(
        "  [success]Computer Use Helper built and enabled.[/success]\n"
        f"  [muted]{helper_bin or 'helper path detected from default location'}[/muted]\n"
        f"  [muted]Config updated: {path}[/muted]\n"
        "  [muted]Next: grant Accessibility and Screen Recording to "
        "`GEODE Computer Use Helper.app`, then run `geode doctor`.[/muted]\n"
    )


# ---------------------------------------------------------------------------
# Readiness Display
# ---------------------------------------------------------------------------


def render_readiness(report: ReadinessReport) -> None:
    """Render readiness status to console (OpenClaw hooks check pattern)."""
    for cap in report.capabilities:
        if cap.available:
            console.print(f"  [success]  {cap.name}[/success]")
        else:
            hint = f" [muted]({cap.reason})[/muted]" if cap.reason else ""
            console.print(f"  [warning]  {cap.name}[/warning]{hint}")

    console.print()

    if report.blocked:
        console.print("  [warning]No LLM key configured — key registration required[/warning]")
        console.print()
