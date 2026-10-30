"""Startup data inspection — lifecycle-pure half of the v0.86.0 split.

Originally lived in ``core/cli/startup.py``. v0.86.0 split that module by
responsibility: pure inspection / IO / dataclasses (this file) versus the
interactive wizard surfaces (``core/cli/onboarding.py``). Lifecycle code
must remain free of ``console.input``/``console.print`` so that headless
processes (serve, IPC poller) can call it without an attached TTY.

Public surface:
  * ``check_readiness`` / ``ReadinessReport`` / ``Capability`` — gateway:startup data

Detects environment readiness:
  Any locally usable model credential route → setup may be skipped
  None                                      → caller surfaces the wizard

Availability is inspected locally; upstream credential acceptance is not tested.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.memory.project import ProjectMemory

log = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Readiness Report
# ---------------------------------------------------------------------------


@dataclass
class Capability:
    """A single system capability with eligibility status."""

    name: str
    available: bool
    reason: str = ""
    required: bool = True


@dataclass
class ReadinessReport:
    """System readiness report (OpenClaw hook eligibility pattern)."""

    capabilities: list[Capability] = field(default_factory=list)
    has_api_key: bool = False
    has_env_file: bool = False
    has_memory: bool = False
    has_profile: bool = False
    blocked: bool = False
    force_dry_run: bool = False  # explicit audit override; not inferred from missing auth

    @property
    def all_ready(self) -> bool:
        return all(c.available for c in self.capabilities if c.required)


def check_readiness(project_root: Path | None = None) -> ReadinessReport:
    """Check system readiness (OpenClaw gateway:startup pattern).

    Any usable route satisfies setup; prompt admission checks the selected route.
    """
    root = project_root or Path(".")
    report = ReadinessReport()

    # Read the same route/eligibility decision as model selection and requests.
    has_credential = has_available_llm_credential()
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
                reason="optional project configuration",
                required=False,
            )
        )

    # 3. Project Memory check
    mem = ProjectMemory(root)
    report.has_memory = mem.exists()
    report.capabilities.append(
        Capability(
            name="Project Memory",
            available=report.has_memory,
            reason="" if report.has_memory else "optional; created when saving project memory",
            required=False,
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
                reason="" if profile_exists else "optional; run `geode init` to create it",
                required=False,
            )
        )
    except Exception:
        report.has_profile = False
        report.capabilities.append(
            Capability(
                name="User Profile",
                available=False,
                reason="load failed",
                required=False,
            )
        )

    # 5. Always-available capabilities
    report.capabilities.append(Capability(name="Setup and session commands", available=True))

    # 5. Block only when there is no usable credential at all (key or OAuth)
    report.blocked = not has_credential

    return report
