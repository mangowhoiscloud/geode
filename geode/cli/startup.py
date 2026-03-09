"""Startup checks — OpenClaw gateway:startup + hook eligibility pattern.

Detects environment readiness and applies Graceful Degradation:
  API key present  → full mode (LLM calls enabled)
  API key absent   → dry-run mode (fixture data only)
  .env missing     → guide user to create from .env.example

Reports capability status like OpenClaw's `hooks check --json`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from geode.config import settings
from geode.memory.project import ProjectMemory
from geode.ui.console import console

log = logging.getLogger(__name__)


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
    force_dry_run: bool = False

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

    # 5. Force dry-run if no API key
    report.force_dry_run = not has_key

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

    if report.force_dry_run:
        console.print("  [warning]API key not configured — dry-run mode only[/warning]")
        console.print("  [muted]To enable LLM analysis:[/muted]")

        if not report.has_env_file:
            console.print("    [muted]1. cp .env.example .env[/muted]")
            console.print("    [muted]2. Edit .env with your ANTHROPIC_API_KEY[/muted]")
        else:
            console.print("    [muted]Set ANTHROPIC_API_KEY in .env[/muted]")

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
