"""Startup checks — OpenClaw gateway:startup + hook eligibility pattern.

Detects environment readiness:
  ANY provider key present → full mode (LLM calls enabled)
  No provider key         → .env setup wizard → key registration gate
  .env missing            → interactive wizard to create .env

Reports capability status like OpenClaw's `hooks check --json`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.cli._helpers import mask_key as _mask_key
from core.cli._helpers import upsert_env as _upsert_env
from core.config import settings
from core.memory.project import ProjectMemory
from core.ui.console import console

log = logging.getLogger(__name__)


def auto_generate_env(project_root: Path | None = None) -> bool:
    """Auto-generate .env from .env.example if .env is absent.

    Copies .env.example to .env, replacing placeholder values
    (like ``sk-ant-...`` or ``...``) with empty strings so that
    the Settings loader does not treat them as real keys.

    Returns True if .env was generated, False otherwise.
    """
    root = project_root or Path(".")
    env_path = root / ".env"
    example_path = root / ".env.example"

    if env_path.exists():
        return False
    if not example_path.exists():
        return False

    raw = example_path.read_text(encoding="utf-8")
    lines: list[str] = []
    for line in raw.splitlines():
        # Skip commented-out lines — keep as-is
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            lines.append(line)
            continue
        # Split on first '='
        key, _, value = line.partition("=")
        value = value.strip()
        # Replace placeholder values with empty string
        if _is_placeholder(value):
            lines.append(f"{key}=")
        else:
            lines.append(line)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info(".env auto-generated from .env.example")
    return True


def _is_placeholder(value: str) -> bool:
    """Check if a .env value is a placeholder (not a real credential)."""
    # Exact ellipsis
    if value == "...":
        return True
    # Patterns like sk-ant-..., sk-..., lsv2_pt_..., BSA..., etc.
    return bool(value.endswith("..."))


def _has_any_llm_key() -> bool:
    """Check if ANY LLM provider API key is configured."""
    if settings.anthropic_api_key and settings.anthropic_api_key != "sk-ant-...":
        return True
    if settings.openai_api_key and settings.openai_api_key != "sk-...":
        return True
    return bool(settings.zai_api_key and settings.zai_api_key != "...")


# ---------------------------------------------------------------------------
# .env Setup Wizard
# ---------------------------------------------------------------------------


def env_setup_wizard() -> bool:
    """Interactive .env setup wizard — runs when .env is absent.

    Guides user through setting up API keys for available providers.
    Enter to skip, Ctrl+C to abort. Returns True if any key was set.
    """
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]Welcome to GEODE![/bold]\n\n"
            "No .env file found. Let's set up your API keys.\n"
            "Enter each key or press Enter to skip.\n"
            "Press Ctrl+C to abort at any time.",
            title="Setup Wizard",
            border_style="cyan",
        )
    )

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
        console.print("\n  [success].env created with your API keys.[/success]")
    console.print()
    return any_set


# ---------------------------------------------------------------------------
# API Key Detection (natural language input guard)
# ---------------------------------------------------------------------------

# Patterns: sk-ant-* → anthropic, sk-proj-*/sk-* → openai, hex.hex → glm
_KEY_PATTERNS: list[tuple[str, str, str]] = [
    (r"^sk-ant-[A-Za-z0-9_-]{10,}$", "anthropic", "ANTHROPIC_API_KEY"),
    (r"^sk-proj-[A-Za-z0-9_-]{10,}$", "openai", "OPENAI_API_KEY"),
    (r"^sk-[A-Za-z0-9_-]{10,}$", "openai", "OPENAI_API_KEY"),
]


def detect_api_key(text: str) -> tuple[str, str, str] | None:
    """Detect if free-text input is an API key.

    Returns (provider, env_var, key_value) if detected, else None.
    Only matches single-token inputs (no spaces except leading/trailing).
    """
    from core.cli._helpers import is_glm_key

    stripped = text.strip()
    if " " in stripped or "\n" in stripped:
        return None

    for pattern, provider, env_var in _KEY_PATTERNS:
        if re.match(pattern, stripped):
            return provider, env_var, stripped

    # GLM key: {id}.{secret} pattern — uses shared helper
    if is_glm_key(stripped):
        return "glm", "ZAI_API_KEY", stripped

    return None


# ---------------------------------------------------------------------------
# Key Registration Gate
# ---------------------------------------------------------------------------


def key_registration_gate() -> str | None:
    """Block until user provides API key or quits. Returns key or None."""
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]GEODE requires at least one LLM API key to operate.[/bold]\n\n"
            "  [cyan]/key <sk-ant-...>[/cyan]        — Anthropic\n"
            "  [cyan]/key openai <sk-...>[/cyan]     — OpenAI\n"
            "  [cyan]/key glm <key>[/cyan]           — ZhipuAI (GLM)\n"
            "  [cyan]/quit[/cyan]                    — exit\n\n"
            "[muted]Or just paste an API key directly.[/muted]",
            title="API Key Required",
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
# Readiness Report
# ---------------------------------------------------------------------------


@dataclass
class Capability:
    """A single system capability with eligibility status."""

    name: str
    available: bool
    reason: str = ""


@dataclass
class ReadinessReport:
    """System readiness report (OpenClaw hook eligibility pattern)."""

    capabilities: list[Capability] = field(default_factory=list)
    has_api_key: bool = False
    has_env_file: bool = False
    has_memory: bool = False
    blocked: bool = False
    force_dry_run: bool = False  # backward-compat alias

    @property
    def all_ready(self) -> bool:
        return all(c.available for c in self.capabilities)


def check_readiness(project_root: Path | None = None) -> ReadinessReport:
    """Check system readiness (OpenClaw gateway:startup pattern).

    ANY provider key (Anthropic/OpenAI/ZhipuAI) unblocks full mode.
    """
    root = project_root or Path(".")
    report = ReadinessReport()

    # 1. API Key check — any provider key suffices
    has_key = _has_any_llm_key()
    report.has_api_key = has_key
    if has_key:
        report.capabilities.append(Capability(name="LLM Analysis", available=True))
    else:
        report.capabilities.append(
            Capability(
                name="LLM Analysis",
                available=False,
                reason="No LLM API key set (Anthropic/OpenAI/ZhipuAI)",
            )
        )

    # 2. .env file check
    env_path = root / ".env"
    env_example_path = root / ".env.example"
    report.has_env_file = env_path.exists()
    if not env_path.exists() and env_example_path.exists():
        report.capabilities.append(
            Capability(
                name="Environment",
                available=False,
                reason="cp .env.example .env",
            )
        )

    # 3. Project Memory check
    mem = ProjectMemory(root)
    report.has_memory = mem.exists()
    report.capabilities.append(
        Capability(
            name="Project Memory",
            available=mem.exists(),
            reason="" if mem.exists() else ".claude/MEMORY.md not found",
        )
    )

    # 4. Always-available capabilities
    report.capabilities.append(Capability(name="Dry-Run Analysis", available=True))
    report.capabilities.append(Capability(name="IP Search", available=True))

    # 5. Block if no LLM key at all
    report.blocked = not has_key
    report.force_dry_run = not has_key  # backward-compat

    return report


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


def setup_project_memory(project_root: Path | None = None) -> bool:
    """Initialize project memory if not present (OpenClaw boot-md pattern)."""
    mem = ProjectMemory(project_root)
    if mem.exists():
        return False

    created = mem.ensure_structure()
    if created:
        log.info("Project memory initialized at %s", mem.memory_file)
    return created


def setup_user_profile() -> bool:
    """Initialize user profile if not present (~/.geode/user_profile/)."""
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        return profile.ensure_structure()
    except Exception as e:
        log.debug("User profile setup skipped: %s", e)
        return False
