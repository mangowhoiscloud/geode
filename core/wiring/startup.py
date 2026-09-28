"""Startup data inspection — lifecycle-pure half of the v0.86.0 split.

Originally lived in ``core/cli/startup.py``. v0.86.0 split that module by
responsibility: pure inspection / IO / dataclasses (this file) versus the
interactive wizard surfaces (``core/cli/onboarding.py``). Lifecycle code
must remain free of ``console.input``/``console.print`` so that headless
processes (serve, IPC poller) can call it without an attached TTY.

Public surface:
  * ``auto_generate_env`` — copy ``.env.example`` to ``.env`` (placeholder safe)
  * ``check_readiness`` / ``ReadinessReport`` / ``Capability`` — gateway:startup data
  * ``setup_project_memory`` / ``setup_user_profile`` — first-run scaffolding

Detects environment readiness:
  Any locally usable model credential route → full mode (LLM enabled)
  None                                      → caller surfaces the wizard

Availability is inspected locally; upstream credential acceptance is not tested.
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

    Copies .env.example to .env. A line whose value is empty or a
    placeholder (``sk-ant-...``, ``...``) is emitted COMMENTED
    (``# KEY=``) rather than as an active blank ``KEY=`` — an active blank
    secret entry reads as "key present but empty" and can shadow the
    authoritative global ``~/.geode/.env`` value. Real values are kept.

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
        # An empty or placeholder value is not a real credential — emit it
        # commented so the generated .env documents the available keys
        # without an active blank entry that could shadow the global value.
        if value == "" or _is_placeholder(value):
            lines.append(f"# {key.strip()}=")
        else:
            lines.append(line)

    tmp_path = env_path.with_suffix(".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(env_path)
    log.info(".env auto-generated from .env.example")
    return True


def _is_placeholder(value: str) -> bool:
    """Shared placeholder rule (SoT: ``core.config.env_io.is_placeholder``).

    Lazy import keeps this module free of the pydantic-settings load cost at
    import time, matching the ``__getattr__`` settings deferral above.
    """
    from core.config.env_io import is_placeholder

    return is_placeholder(value)


def has_available_llm_credential(provider: str | None = None) -> bool:
    """Inspect whether any known model has a usable route for this provider.

    This startup boundary hydrates persisted accounts once. The routing owner
    checks model plans, source policy and account eligibility without a live call.
    """
    try:
        from core.config import _resolve_provider, settings
        from core.llm.adapters.registry import active_registry_snapshot, normalize_registry_provider
        from core.llm.model_catalog import MODEL_OFFERINGS
        from core.llm.routing import model_available
        from core.wiring.container import ensure_profile_store

        ensure_profile_store()
        defaults = (
            registration.provider_spec.profile.default_model()
            for registration in active_registry_snapshot().registrations.values()
            if registration.provider_spec is not None
        )
        candidates = dict.fromkeys(
            (
                settings.model,
                *defaults,
                *(entry.id for entry in MODEL_OFFERINGS),
                "openrouter/openrouter/auto",  # dynamic route, no finite offering catalog
            )
        )
        return any(
            model_available(model)
            for model in candidates
            if model
            and (
                provider is None
                or normalize_registry_provider(_resolve_provider(model)) == provider
            )
        )
    except Exception:
        log.debug("Credential route inspection failed", exc_info=True)
        return False


def _has_any_llm_key() -> bool:
    """Legacy onboarding name; includes stored and managed credential routes."""
    return has_available_llm_credential()


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

    Any usable model route unblocks full mode; no network authentication is attempted.
    """
    root = project_root or Path(".")
    report = ReadinessReport()

    # Read the same route/eligibility decision as model selection and requests.
    has_credential = _has_any_llm_key()
    report.has_api_key = has_credential
    if has_credential:
        report.capabilities.append(Capability(name="LLM Analysis", available=True))
    else:
        report.capabilities.append(
            Capability(
                name="LLM Analysis",
                available=False,
                reason=(
                    "No LLM credential — set a key (Anthropic/OpenAI/ZhipuAI) "
                    "or log in to a subscription"
                ),
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
                reason="" if profile_exists else "run `geode init` to create it",
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

    # 5. Block only when there is no usable credential at all (key or OAuth)
    report.blocked = not has_credential
    report.force_dry_run = not has_credential  # backward-compat

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
