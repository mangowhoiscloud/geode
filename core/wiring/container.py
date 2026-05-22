"""Infrastructure wiring — policies, tools, LLM adapters, auth, lanes.

Extracted from core.runtime as standalone functions (formerly module-level and staticmethods).
"""

from __future__ import annotations

import logging
from typing import Any

from core.auth.cooldown import CooldownTracker
from core.auth.profiles import ProfileStore
from core.auth.rotation import ProfileRotator
from core.llm.providers.openai import OpenAIAdapter
from core.llm.router import ClaudeAdapter, LLMClientPort
from core.orchestration.lane_queue import LaneQueue
from core.tools.policy import PolicyChain, ToolPolicy
from core.tools.registry import ToolRegistry, ToolSearchTool

log = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    """PEP 562 lazy ``settings`` alias for legacy patch sites."""
    if name == "settings":
        from core.config import settings as _settings

        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_GLOBAL_CONCURRENCY = 8
DEFAULT_GATEWAY_CONCURRENCY = 4
# PR-LQ-Phase1 (2026-05-22) — seed-generation lane bumped DOWN from 16 to 4
# to restore the OpenClaw lane hierarchy invariant
# ``max(workload_lane) <= max(global)``. Pre-PR the workload cap (16) was
# strictly larger than the global cap (8), so 16 "seed-generation slots" was
# a false signal — leaf sub-agent calls still funnel through the global lane
# and blocked at 8. The lane cap is now the same load shape the global
# semaphore can actually deliver, and an explicit invariant test in
# ``tests/test_lane_queue.py`` guards future drift. Re-raising the cap is
# fine once the global lane grows OR a Claude-CLI-specific sub-agent lane
# isolates that path (see [[project_lanequeue_handoff_2026_05_22]] Phase 2).
DEFAULT_SEED_PIPELINE_CONCURRENCY = 4

# Module-level accessors set by build_auth().
# Both runtime LLM dispatch and the CLI (`/login`) read from the
# same singletons so a credential added through the UI is immediately seen
# by ProfileRotator.resolve(). Pre-v0.50.0 there were two parallel
# ProfileStore instances and they drifted out of sync.
_profile_store: ProfileStore | None = None
_profile_rotator: ProfileRotator | None = None


def get_profile_rotator() -> ProfileRotator | None:
    """Return the ProfileRotator built by build_auth(), or None if not yet initialized."""
    return _profile_rotator


def get_profile_store() -> ProfileStore | None:
    """Return the ProfileStore built by build_auth(), or None if not yet initialized."""
    return _profile_store


def ensure_profile_store() -> ProfileStore:
    """Return the singleton ProfileStore, building it if necessary.

    Used by CLI commands that may run before the runtime bootstrap (e.g.
    `/login` invoked at startup). Idempotent.
    """
    if _profile_store is None:
        build_auth()
    assert _profile_store is not None  # build_auth populates the singleton
    return _profile_store


# ---------------------------------------------------------------------------
# Default builders
# ---------------------------------------------------------------------------


def build_default_policies() -> PolicyChain:
    """Build default PolicyChain with L1-2 profile/org + L3 mode-based restrictions."""
    from core.tools.policy import build_6layer_chain, load_org_policy, load_profile_policy

    profile = load_profile_policy()
    org = load_org_policy()
    mode_policies = [
        ToolPolicy(
            name="dry_run_block_llm",
            mode="dry_run",
            denied_tools={"send_notification"},
            priority=100,
        ),
        ToolPolicy(
            name="full_block_notification",
            mode="full_pipeline",
            denied_tools={"send_notification"},
            priority=100,
        ),
    ]
    return build_6layer_chain(profile=profile, org=org, mode_policies=mode_policies)


def build_default_registry() -> ToolRegistry:
    """Build ToolRegistry with GEODE core tools registered.

    Specialized tools are expected to be provided by external packages.
    """
    registry = ToolRegistry()
    # Data (3)
    from core.tools.data_tools import CortexAnalystTool, CortexSearchTool, GenerateDataTool

    registry.register(CortexAnalystTool())
    registry.register(CortexSearchTool())
    registry.register(GenerateDataTool())

    # Search (2)
    from core.tools.jobs import WantedJobsSearchTool
    from core.tools.web_search import WebSearchTool

    registry.register(WebSearchTool())
    registry.register(WantedJobsSearchTool())
    # Memory (7)
    from core.tools.memory_tools import (
        MemoryGetTool,
        MemorySaveTool,
        MemorySearchTool,
        RuleCreateTool,
        RuleDeleteTool,
        RuleListTool,
        RuleUpdateTool,
    )

    registry.register(MemorySearchTool())
    registry.register(MemoryGetTool())
    registry.register(MemorySaveTool())
    registry.register(RuleCreateTool())
    registry.register(RuleUpdateTool())
    registry.register(RuleDeleteTool())
    registry.register(RuleListTool())
    # Output (3)
    from core.tools.output_tools import ExportJsonTool, GenerateReportTool, SendNotificationTool

    registry.register(GenerateReportTool())
    registry.register(ExportJsonTool())
    registry.register(SendNotificationTool())
    # Recall (1) — PR-Hermes-1d (2026-05-22). FTS5-backed search over
    # the current project's session messages (Phase 1c index).
    from core.tools.session_search import SessionSearchTool

    registry.register(SessionSearchTool())
    # Meta-tool: tool_search (enables deferred loading)
    registry.register(ToolSearchTool(registry))
    return registry


def build_default_lanes() -> LaneQueue:
    """Build the unified LaneQueue with workload-specific lanes.

    OpenClaw pattern: SessionLane → Workload Lane → Global Lane → Execute.

    Lane hierarchy::

        SessionLane (per-key serial, max=256)
            ↓
        Workload Lanes (per-workload cap, MUST be <= global)
        ├── "gateway"          (max=4)  — Slack/Discord/Telegram messages
        ├── "seed-generation"  (max=4)  — co-scientist 8-role sub-agent pipeline
        └── (CLI/general sub-agent paths use global only)
            ↓
        "global" (max=8) — total system capacity

    Gateway messages acquire ["session", "gateway", "global"].
    Seed-generation phases acquire ["session", "seed-generation", "global"]
    so the workload cap composes with the global cap rather than bypassing
    it. CLI/general sub-agents acquire ["session", "global"] (no workload
    lane). This prevents Gateway from starving CLI when busy and prevents
    seed-generation fan-out from saturating the global slot pool.

    Hierarchy invariant (PR-LQ-Phase1, 2026-05-22): every workload lane's
    ``max_concurrent`` MUST be <= the ``global`` lane's cap. A workload
    cap larger than global is a false signal — the leaf semaphore still
    blocks at the global cap. ``tests/test_lane_queue.py`` pins the
    invariant.
    """
    from core.orchestration.lane_queue import SessionLane

    queue = LaneQueue()
    queue.set_session_lane(
        SessionLane(
            max_sessions=256,
            idle_timeout_s=300.0,
            timeout_s=300.0,
        )
    )
    from core.config import settings

    gw_max = (
        settings.gateway_max_concurrent
        if settings.gateway_max_concurrent > 0
        else DEFAULT_GATEWAY_CONCURRENCY
    )
    queue.add_lane("gateway", max_concurrent=gw_max, timeout_s=30.0)
    queue.add_lane("global", max_concurrent=DEFAULT_GLOBAL_CONCURRENCY, timeout_s=30.0)
    queue.add_lane(
        "seed-generation",
        max_concurrent=DEFAULT_SEED_PIPELINE_CONCURRENCY,
        timeout_s=300.0,
    )
    # PR-LQ-Phase2 (2026-05-22) — surface the module-level
    # claude-cli-subagent lane in the LaneQueue dashboard for parity
    # with the autoresearch-audit lane pattern. The actual semaphore
    # lives at :mod:`core.orchestration.claude_cli_lane`; this lane
    # registration is a dashboard mirror that ``LaneQueue.status()``
    # consumers can read alongside ``gateway`` / ``global`` /
    # ``seed-generation``. Both registrations stay in lockstep by
    # routing through the same constants + ``resolve_*`` resolver.
    from core.orchestration.claude_cli_lane import (
        CLAUDE_CLI_LANE_NAME,
        CLAUDE_CLI_LANE_TIMEOUT_S,
        resolve_claude_cli_lane_max,
    )

    queue.add_lane(
        CLAUDE_CLI_LANE_NAME,
        max_concurrent=resolve_claude_cli_lane_max(),
        timeout_s=CLAUDE_CLI_LANE_TIMEOUT_S,
    )
    return queue


# ---------------------------------------------------------------------------
# Auth + LLM adapters
# ---------------------------------------------------------------------------


def _build_oauth_metadata(creds: Any) -> dict[str, Any]:
    """Extract subscription/rate-limit metadata from Claude Code credentials."""
    meta: dict[str, Any] = {}
    if "subscription_type" in creds:
        meta["subscription_type"] = creds["subscription_type"]
    if "rate_limit_tier" in creds:
        meta["rate_limit_tier"] = creds["rate_limit_tier"]
    return meta


def build_auth() -> tuple[ProfileStore, ProfileRotator, CooldownTracker]:
    """Build auth profile system with API key + OAuth profiles.

    Claude Code OAuth tokens are auto-detected from macOS Keychain or
    ~/.claude/.credentials.json (OpenClaw managedBy pattern).
    ProfileRotator selects OAUTH over API_KEY by type priority.

    Idempotent: returns the cached singleton on subsequent calls so the
    CLI and runtime bootstrap can both reach for the store without
    creating duplicate instances (pre-v0.50.0 caused dispatch/UI drift).
    """
    global _profile_store, _profile_rotator
    if _profile_store is not None and _profile_rotator is not None:
        return _profile_store, _profile_rotator, CooldownTracker()

    from core.auth.profiles import AuthProfile, CredentialType
    from core.config import settings

    profile_store = ProfileStore()

    # Claude Code OAuth — DISABLED (Anthropic ToS violation since 2026-01-09).
    # Anthropic prohibits OAuth token usage outside Claude Code/claude.ai.
    # Code preserved for reference; re-enable only if policy changes.
    # See: https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access

    # Codex CLI OAuth — OpenAI managed credential
    try:
        from core.auth.codex_cli_oauth import (
            read_codex_cli_credentials,
        )

        codex_creds = read_codex_cli_credentials()
        if codex_creds:
            profile_store.add(
                AuthProfile(
                    name="openai-codex:codex-cli",
                    provider="openai-codex",
                    credential_type=CredentialType.OAUTH,
                    key=codex_creds["access_token"],
                    refresh_token=codex_creds.get("refresh_token", ""),
                    expires_at=codex_creds.get("expires_at", 0.0),
                    managed_by="codex-cli",
                    metadata=_build_oauth_metadata(codex_creds),
                )
            )
            log.info(
                "Auth: Codex CLI OAuth detected (account=%s)",
                codex_creds.get("account_id", "unknown"),
            )
    except Exception as exc:
        log.debug("Auth: Codex CLI OAuth not available: %s", exc)

    # API key profiles — fallback
    if settings.anthropic_api_key:
        profile_store.add(
            AuthProfile(
                name="anthropic:default",
                provider="anthropic",
                credential_type=CredentialType.API_KEY,
                key=settings.anthropic_api_key,
            )
        )
    if settings.openai_api_key:
        profile_store.add(
            AuthProfile(
                name="openai:default",
                provider="openai",
                credential_type=CredentialType.API_KEY,
                key=settings.openai_api_key,
            )
        )
    if settings.zai_api_key:
        profile_store.add(
            AuthProfile(
                name="glm:default",
                provider="glm",
                credential_type=CredentialType.API_KEY,
                key=settings.zai_api_key,
            )
        )
    profile_rotator = ProfileRotator(profile_store)
    _profile_rotator = profile_rotator
    _profile_store = profile_store
    cooldown_tracker = CooldownTracker()

    # v0.50.0 — hydrate Plans + user-defined Profiles from ~/.geode/auth.toml.
    # On first run we migrate any env-loaded API keys into the file so the
    # next startup sees them as PAYG plans.
    try:
        from core.auth.auth_toml import auth_toml_path, load_auth_toml, migrate_env_to_toml

        if auth_toml_path().exists():
            load_auth_toml()
        else:
            migrate_env_to_toml()
    except Exception:  # pragma: no cover — bootstrap must never fail on auth I/O
        log.debug("auth.toml hydration skipped", exc_info=True)

    # Register managed token refreshers
    try:
        from core.auth.codex_cli_oauth import refresh_codex_cli_token

        profile_rotator.register_refresher("codex-cli", refresh_codex_cli_token)
    except Exception:
        log.debug("Codex CLI refresher registration skipped")

    return profile_store, profile_rotator, cooldown_tracker


def build_llm_adapters(
    tool_registry: ToolRegistry,
    policy_chain: PolicyChain,
) -> tuple[LLMClientPort, LLMClientPort | None]:
    """Build LLM adapters and inject callables into contextvars."""
    from core.config import settings
    from core.llm.router import set_llm_callable

    llm_adapter: LLMClientPort = ClaudeAdapter()
    secondary_adapter: LLMClientPort | None = None
    if settings.openai_api_key:
        secondary_adapter = OpenAIAdapter()

    set_llm_callable(
        llm_adapter.generate_structured,
        llm_adapter.generate,
        parsed_fn=llm_adapter.generate_parsed,
        secondary_json_fn=(secondary_adapter.generate_structured if secondary_adapter else None),
        secondary_parsed_fn=(secondary_adapter.generate_parsed if secondary_adapter else None),
    )
    return llm_adapter, secondary_adapter
