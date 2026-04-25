"""Infrastructure wiring — policies, tools, LLM adapters, auth, lanes.

Extracted from core.runtime as standalone functions (formerly module-level and staticmethods).
"""

from __future__ import annotations

import logging
from typing import Any

from core.config import settings
from core.gateway.auth.cooldown import CooldownTracker
from core.gateway.auth.profiles import ProfileStore
from core.gateway.auth.rotation import ProfileRotator
from core.llm.providers.openai import OpenAIAdapter
from core.llm.router import ClaudeAdapter, LLMClientPort
from core.orchestration.lane_queue import LaneQueue
from core.tools.analysis import ExplainScoreTool, PSMCalculateTool, RunAnalystTool, RunEvaluatorTool
from core.tools.policy import PolicyChain, ToolPolicy
from core.tools.registry import ToolRegistry, ToolSearchTool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_GLOBAL_CONCURRENCY = 8
DEFAULT_GATEWAY_CONCURRENCY = 4

# Module-level accessors set by build_auth().
# Both runtime LLM dispatch and the CLI (`/login`, `/auth`) read from the
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
            denied_tools={"run_analyst", "run_evaluator", "send_notification"},
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
    """Build ToolRegistry with all 21 tools registered."""
    registry = ToolRegistry()
    # Analysis (4)
    registry.register(RunAnalystTool())
    registry.register(RunEvaluatorTool())
    registry.register(PSMCalculateTool())
    registry.register(ExplainScoreTool())
    # Data (3)
    from core.tools.data_tools import CortexAnalystTool, CortexSearchTool, QueryMonoLakeTool

    registry.register(QueryMonoLakeTool())
    registry.register(CortexAnalystTool())
    registry.register(CortexSearchTool())
    # Signals (5)
    from core.tools.signal_tools import (
        GoogleTrendsTool,
        RedditSentimentTool,
        SteamInfoTool,
        TwitchStatsTool,
        WebSearchTool,
        YouTubeSearchTool,
    )

    registry.register(YouTubeSearchTool())
    registry.register(RedditSentimentTool())
    registry.register(TwitchStatsTool())
    registry.register(SteamInfoTool())
    registry.register(GoogleTrendsTool())
    registry.register(WebSearchTool())
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
    # Meta-tool: tool_search (enables deferred loading)
    registry.register(ToolSearchTool(registry))
    return registry


def build_default_lanes() -> LaneQueue:
    """Build the unified LaneQueue with workload-specific lanes.

    OpenClaw pattern: SessionLane → Workload Lane → Global Lane → Execute.

    Lane hierarchy::

        SessionLane (per-key serial, max=256)
            ↓
        Workload Lanes (per-workload cap)
        ├── "gateway"  (max=4)  — Slack/Discord/Telegram messages
        └── (CLI/sub-agent use global only)
            ↓
        "global" (max=8) — total system capacity

    Gateway messages acquire ["session", "gateway", "global"].
    CLI/sub-agents acquire ["session", "global"] (no workload lane).
    This prevents Gateway from starving CLI when busy.
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
    return queue


# ---------------------------------------------------------------------------
# Tool executor factory
# ---------------------------------------------------------------------------


def make_tool_executor(
    llm_adapter: LLMClientPort,
    registry: ToolRegistry,
    policy_chain: PolicyChain,
) -> Any:
    """Create a tool_fn callable that binds generate_with_tools to registry.

    Returns a callable with the same signature as LLMToolCallable:
        (system, user, *, tools, tool_executor, ...) -> ToolUseResult

    If no explicit tool_executor is provided, falls back to registry.execute
    with the default policy chain.
    """

    def _default_tool_executor(name: str, **kwargs: Any) -> dict[str, Any]:
        return registry.execute(name, policy=policy_chain, **kwargs)

    def _tool_fn(
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Any = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        executor = tool_executor or _default_tool_executor
        return llm_adapter.generate_with_tools(
            system,
            user,
            tools=tools,
            tool_executor=executor,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
        )

    return _tool_fn


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

    from core.gateway.auth.profiles import AuthProfile, CredentialType

    profile_store = ProfileStore()

    # Claude Code OAuth — DISABLED (Anthropic ToS violation since 2026-01-09).
    # Anthropic prohibits OAuth token usage outside Claude Code/claude.ai.
    # Code preserved for reference; re-enable only if policy changes.
    # See: https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access

    # Codex CLI OAuth — OpenAI managed credential
    try:
        from core.gateway.auth.codex_cli_oauth import (
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

    # Register managed token refreshers
    try:
        from core.gateway.auth.codex_cli_oauth import refresh_codex_cli_token

        profile_rotator.register_refresher("codex-cli", refresh_codex_cli_token)
    except Exception:
        log.debug("Codex CLI refresher registration skipped")

    return profile_store, profile_rotator, cooldown_tracker


def build_llm_adapters(
    tool_registry: ToolRegistry,
    policy_chain: PolicyChain,
) -> tuple[LLMClientPort, LLMClientPort | None]:
    """Build LLM adapters and inject callables into contextvars."""
    from core.llm.router import set_llm_callable

    llm_adapter: LLMClientPort = ClaudeAdapter()
    secondary_adapter: LLMClientPort | None = None
    if settings.openai_api_key:
        secondary_adapter = OpenAIAdapter()

    tool_fn = make_tool_executor(llm_adapter, tool_registry, policy_chain)
    set_llm_callable(
        llm_adapter.generate_structured,
        llm_adapter.generate,
        parsed_fn=llm_adapter.generate_parsed,
        tool_fn=tool_fn,
        secondary_json_fn=(secondary_adapter.generate_structured if secondary_adapter else None),
        secondary_parsed_fn=(secondary_adapter.generate_parsed if secondary_adapter else None),
    )
    return llm_adapter, secondary_adapter
