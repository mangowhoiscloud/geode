"""Interactive onboarding surfaces — CLI half of the v0.86.0 split.

Originally lived in ``core/cli/startup.py``. v0.86.0 split that module by
responsibility: pure inspection / IO / dataclasses (now in
``core/lifecycle/startup.py``) versus the interactive wizard surfaces
(this file). Functions here drive ``console.input``/``console.print``
loops and dispatch to ``/login`` and ``/key`` slash commands, so they
must NOT be called from headless processes (serve, IPC poller).

Public surface:
  * ``env_setup_wizard`` — top-level three-branch menu (subscription/key/skip)
  * ``detect_api_key`` — natural-language API-key sniffer
  * ``key_registration_gate`` — blocking prompt that accepts ``/login`` /
    ``/key`` / direct paste until a credential is set or the user quits
  * ``render_readiness`` — pretty-printer for ``ReadinessReport``
"""

from __future__ import annotations

import logging
import re
from typing import Any

from core.ui.console import console
from core.utils.env_io import mask_key as _mask_key
from core.utils.env_io import upsert_env as _upsert_env
from core.wiring.startup import ReadinessReport, _has_any_llm_key, detect_subscription_oauth

log = logging.getLogger(__name__)


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
    """Interactive .env setup wizard — runs when no credential is found.

    v0.54.0 — three branches: subscription guidance, API key paste, or
    skip into dry-run mode. Returns True if any credential or skip was
    chosen (i.e. the wizard need not re-run on next launch).
    """
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]Welcome to GEODE.[/bold]\n\n"
            "Pick how you want to talk to the model:\n"
            "  [cyan]1[/cyan]  ChatGPT subscription (Plus / Pro / Business / Edu / Enterprise) "
            "or Claude subscription (Pro / Max ×5 / Max ×20 / Team / Enterprise)\n"
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
        return _wizard_subscription_path()
    if choice == "3":
        console.print(
            "\n  [muted]Skipped. Run [cyan]geode setup[/cyan] later to add a credential.[/muted]\n"
        )
        return True  # user explicitly chose dry-run; suppress re-prompt
    return _wizard_api_key_path()


def _wizard_subscription_path() -> bool:
    """Path A guidance — Codex CLI OAuth (ChatGPT-only).

    GEODE doesn't drive ``codex auth login`` itself; the Codex CLI owns
    that flow. We tell the user the exact two commands and re-probe.
    """
    console.print(
        "\n  [header]Path A — ChatGPT subscription[/header]\n"
        "  Run these in another terminal, then come back:\n\n"
        "    [cyan]brew install codex[/cyan]   "
        "[muted](or: npm install -g @openai/codex)[/muted]\n"
        "    [cyan]codex auth login[/cyan]   "
        "[muted](opens a browser; sign in with your ChatGPT account)[/muted]\n\n"
        "  [muted]Press Enter when done — GEODE will detect the token.[/muted]"
    )
    try:
        console.input("  > ")
    except (KeyboardInterrupt, EOFError):
        console.print("\n  [muted]Setup cancelled.[/muted]\n")
        return False
    provider = detect_subscription_oauth()
    if provider:
        console.print(f"\n  [success]Detected {provider} OAuth credential.[/success]\n")
        return True
    console.print(
        "\n  [warning]No Codex CLI credential found at ~/.codex/auth.json.[/warning]\n"
        "  [muted]Re-run [cyan]geode setup[/cyan] after [cyan]codex auth login[/cyan] "
        "completes.[/muted]\n"
    )
    return False


def _wizard_api_key_path() -> bool:
    """Path B — paste API keys for any of the three providers."""
    from core.config import settings

    any_set = False
    providers = [
        (
            "Anthropic",
            "ANTHROPIC_API_KEY",
            "anthropic_api_key",
            "https://console.anthropic.com/settings/keys",
        ),
        ("OpenAI", "OPENAI_API_KEY", "openai_api_key", "https://platform.openai.com/api-keys"),
        ("ZhipuAI", "ZAI_API_KEY", "zai_api_key", "https://open.bigmodel.cn/usercenter/apikeys"),
    ]

    console.print(
        "\n  [header]Path B — API key[/header]\n"
        "  [muted]Paste each key or press Enter to skip.[/muted]"
    )

    for label, env_var, settings_field, url in providers:
        try:
            console.print(f"\n  [label]{label}[/label] [muted]({url})[/muted]")
            value = console.input("  API key: ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Setup cancelled.[/muted]")
            break

        if not value:
            console.print(f"  [muted]{label}: skipped[/muted]")
            continue

        _upsert_env(env_var, value)
        object.__setattr__(settings, settings_field, value)
        console.print(f"  [success]{label} key set[/success]  {_mask_key(value)}")
        any_set = True

    if any_set:
        console.print("\n  [success].env updated with your API keys.[/success]")
    console.print()
    return any_set


# ---------------------------------------------------------------------------
# API Key Detection (natural language input guard)
# ---------------------------------------------------------------------------

# P2-C (2026-05-17) — credential pattern + env var binding migrated to
# core/config/routing.toml. The wizard now reads both axes from the
# manifest so adding a new provider is a TOML edit, not a code change.


def _key_patterns() -> list[tuple[str, str, str]]:
    """Return ``[(regex, provider, env_var), ...]`` from the routing manifest.

    Lazy — called from :func:`detect_api_key` so the heavy manifest load
    only fires on the natural-language input path (not at module import).
    Falls back to a built-in default if the manifest is unreachable so
    onboarding never crashes on a stale install.
    """
    try:
        from core.config.routing_manifest import load_routing_manifest

        manifest = load_routing_manifest()
    except Exception:
        return [
            (r"^sk-ant-[A-Za-z0-9_-]{10,}$", "anthropic", "ANTHROPIC_API_KEY"),
            (r"^sk-proj-[A-Za-z0-9_-]{10,}$", "openai", "OPENAI_API_KEY"),
            (r"^sk-[A-Za-z0-9_-]{10,}$", "openai", "OPENAI_API_KEY"),
        ]
    env_vars = manifest.credential_env_vars.env_vars
    out: list[tuple[str, str, str]] = []
    for regex, provider in manifest.credential_patterns.patterns.items():
        env_var = env_vars.get(provider)
        if not env_var:
            # Unknown provider — skip (manifest authors should add the env var
            # mapping when introducing a new pattern).
            continue
        out.append((regex, provider, env_var))
    return out


def detect_api_key(text: str) -> tuple[str, str, str] | None:
    """Detect if free-text input is an API key.

    Returns (provider, env_var, key_value) if detected, else None.
    Only matches single-token inputs (no spaces except leading/trailing).
    """
    from core.utils.env_io import is_glm_key

    stripped = text.strip()
    if " " in stripped or "\n" in stripped:
        return None

    for pattern, provider, env_var in _key_patterns():
        if re.match(pattern, stripped):
            return provider, env_var, stripped

    # GLM key: {id}.{secret} pattern — uses shared helper.
    if is_glm_key(stripped):
        try:
            from core.config.routing_manifest import load_routing_manifest

            glm_env = load_routing_manifest().credential_env_vars.env_vars.get("glm", "ZAI_API_KEY")
        except Exception:
            glm_env = "ZAI_API_KEY"
        return "glm", glm_env, stripped

    return None


# ---------------------------------------------------------------------------
# Key Registration Gate
# ---------------------------------------------------------------------------


def key_registration_gate() -> str | None:
    """Block until user provides API key or quits. Returns key or None."""
    from rich.panel import Panel

    from core.config import settings

    console.print(
        Panel(
            "[bold]GEODE needs a credential to talk to an LLM.[/bold]\n\n"
            "  [cyan]/login add[/cyan]                — Interactive wizard "
            "(plans + keys + OAuth)\n"
            "  [cyan]/login openai[/cyan]             — Codex OAuth (subscription quota)\n"
            "  [cyan]/login anthropic[/cyan]          — Claude subscription OAuth\n"
            "  [cyan]/key <sk-ant-...>[/cyan]        — Quick paste (Anthropic)\n"
            "  [cyan]/key openai <sk-...>[/cyan]     — Quick paste (OpenAI)\n"
            "  [cyan]/key glm <key>[/cyan]           — Quick paste (GLM PAYG)\n"
            "  [cyan]/quit[/cyan]                    — exit\n\n"
            "[muted]Or just paste an API key directly.[/muted]",
            title="Credentials Required",
            border_style="yellow",
        )
    )
    while True:
        try:
            user_input = console.input("[header]>[/header] ").strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if user_input.lower() in ("/quit", "quit", "exit"):
            return None

        # /login add — full wizard takes precedence
        if user_input.lower().startswith("/login"):
            from core.cli.commands import cmd_login

            cmd_login(user_input[len("/login") :].strip())
            if _has_any_llm_key():
                return "configured"
            continue

        # /key command
        if user_input.startswith("/key "):
            from core.cli.commands import cmd_key

            changed = cmd_key(user_input[5:].strip())
            if changed and _has_any_llm_key():
                return "configured"
            continue

        # Direct key paste detection
        detected = detect_api_key(user_input)
        if detected:
            provider, env_var, key_value = detected
            settings_field_map = {
                "ANTHROPIC_API_KEY": "anthropic_api_key",
                "OPENAI_API_KEY": "openai_api_key",
                "ZAI_API_KEY": "zai_api_key",
            }
            _upsert_env(env_var, key_value)
            field_name = settings_field_map[env_var]
            object.__setattr__(settings, field_name, key_value)
            console.print(
                f"  [success]{provider.capitalize()} API key set[/success]  {_mask_key(key_value)}"
            )
            return key_value

        console.print("  [muted]Use /key <API_KEY> or paste a key directly[/muted]")


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
