"""Startup data inspection — lifecycle-pure half of the v0.86.0 split.

Originally lived in ``core/cli/startup.py``. v0.86.0 split that module by
responsibility: pure inspection / IO / dataclasses (this file) versus the
interactive wizard surfaces (``core/cli/onboarding.py``). Lifecycle code
must remain free of ``console.input``/``console.print`` so that headless
processes (serve, IPC poller) can call it without an attached TTY.

Public surface:
  * ``auto_generate_env`` — copy ``.env.example`` to ``.env`` (placeholder safe)
  * ``detect_subscription_oauth`` — Codex CLI OAuth probe
  * ``check_readiness`` / ``ReadinessReport`` / ``Capability`` — gateway:startup data
  * ``setup_project_memory`` / ``setup_user_profile`` — first-run scaffolding

Detects environment readiness:
  ANY provider key present → full mode (LLM calls enabled)
  No provider key         → caller surfaces the wizard
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.memory.project import ProjectMemory

log = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    """PEP 562 lazy ``settings`` alias.

    Tests historically patch ``core.wiring.startup.settings``; preserve that
    surface without paying the pydantic_settings cost at module import.
    """
    if name == "settings":
        from core.config import settings as _settings

        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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

    tmp_path = env_path.with_suffix(".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(env_path)
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
    from core.config import settings

    if settings.anthropic_api_key and not _is_placeholder(settings.anthropic_api_key):
        return True
    if settings.openai_api_key and not _is_placeholder(settings.openai_api_key):
        return True
    return bool(settings.zai_api_key and not _is_placeholder(settings.zai_api_key))


# ---------------------------------------------------------------------------
# Proactive subscription OAuth detection (v0.54.0)
# ---------------------------------------------------------------------------


def detect_subscription_oauth() -> str | None:
    """Detect a usable subscription-OAuth credential before any wizard runs.

    Currently supports Codex CLI OAuth (ChatGPT Plus / Pro / Business / Edu /
    Enterprise). Anthropic OAuth is intentionally excluded — Anthropic's
    terms of service (effective 2026-01-09) prohibit third-party tools from
    reusing the Claude Code OAuth token; ``core/lifecycle/container.py:271``
    documents the policy decision.

    Returns the provider id (``"openai-codex"``) if a fresh, non-expired
    credential is found and the matching profile is registered in the
    ProfileStore. Returns ``None`` otherwise.
    """
    try:
        from core.auth.codex_cli_oauth import read_codex_cli_credentials
    except ImportError:
        return None

    try:
        creds = read_codex_cli_credentials()
    except Exception:
        log.debug("Codex CLI OAuth probe failed", exc_info=True)
        return None
    if not creds or not creds.get("access_token"):
        return None

    # The Codex CLI credential is real; ensure ProfileStore knows about it.
    # ``build_auth()`` already registers it at startup, but on first run we
    # may need to seed an empty store right after detection.
    try:
        from core.auth.profiles import AuthProfile, CredentialType
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        existing = next(
            (p for p in store.list_all() if p.provider == "openai-codex" and p.key),
            None,
        )
        if existing is None:
            store.add(
                AuthProfile(
                    name="openai-codex:codex-cli",
                    provider="openai-codex",
                    credential_type=CredentialType.OAUTH,
                    key=creds["access_token"],
                    refresh_token=creds.get("refresh_token", ""),
                    expires_at=creds.get("expires_at", 0.0),
                    managed_by="codex-cli",
                )
            )
    except Exception:
        log.debug("Profile registration after OAuth detection failed", exc_info=True)

    return "openai-codex"


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
    has_profile: bool = False
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
            reason="" if mem.exists() else ".geode/memory/PROJECT.md not found",
        )
    )

    # 4. User Profile check (Tier 0.5)
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        profile_exists = profile.exists()
        report.has_profile = profile_exists
        report.capabilities.append(
            Capability(
                name="User Profile",
                available=profile_exists,
                reason="" if profile_exists else "run /profile to set up",
            )
        )
    except Exception:
        report.has_profile = False
        report.capabilities.append(
            Capability(
                name="User Profile",
                available=False,
                reason="load failed",
            )
        )

    # 5. Always-available capabilities
    report.capabilities.append(Capability(name="Dry-Run Analysis", available=True))

    # 5. Block if no LLM key at all
    report.blocked = not has_key
    report.force_dry_run = not has_key  # backward-compat

    return report


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
        log.warning("User profile setup failed: %s", e)
        return False
