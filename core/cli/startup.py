"""Startup checks — OpenClaw gateway:startup + hook eligibility pattern.

Detects environment readiness:
  API key present  → full mode (LLM calls enabled)
  API key absent   → blocked (key registration gate)
  .env missing     → guide user to create from .env.example

Reports capability status like OpenClaw's `hooks check --json`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.config import settings
from core.memory.project import ProjectMemory
from core.ui.console import console

log = logging.getLogger(__name__)


def _mask_key(key: str) -> str:
    """Mask an API key for display."""
    if len(key) <= 14:
        return "***"
    return key[:10] + "..." + key[-4:]


def _upsert_env(var_name: str, value: str) -> None:
    """Insert or update a variable in .env file. Creates .env if absent."""
    import re

    env_path = Path(".env")
    lines: list[str] = []
    found = False

    if env_path.exists():
        raw = env_path.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if re.match(rf"^{re.escape(var_name)}\s*=", line):
                lines.append(f"{var_name}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{var_name}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def key_registration_gate() -> str | None:
    """Block until user provides API key or quits. Returns key or None."""
    from rich.panel import Panel

    console.print(
        Panel(
            "[bold]GEODE requires an Anthropic API key to operate.[/bold]\n\n"
            "  [cyan]/key <YOUR_API_KEY>[/cyan]  — set key and continue\n"
            "  [cyan]/quit[/cyan]               — exit\n\n"
            "[muted]Get a key at: https://console.anthropic.com/settings/keys[/muted]",
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
        if user_input.startswith("/key "):
            key = user_input[5:].strip()
            if key:
                _upsert_env("ANTHROPIC_API_KEY", key)
                settings.anthropic_api_key = key
                console.print(f"  [success]API key set[/success]  {_mask_key(key)}")
                return key
        console.print("  [muted]Use /key <API_KEY> to set your key[/muted]")


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

    Returns a ReadinessReport with capability status for each feature.
    """
    root = project_root or Path(".")
    report = ReadinessReport()

    # 1. API Key check
    has_key = bool(settings.anthropic_api_key and settings.anthropic_api_key != "sk-ant-...")
    report.has_api_key = has_key
    report.capabilities.append(
        Capability(
            name="LLM Analysis",
            available=has_key,
            reason="" if has_key else "ANTHROPIC_API_KEY not set",
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

    # 5. Block if no API key (was force_dry_run)
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
        console.print("  [warning]API key not configured — key registration required[/warning]")
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
