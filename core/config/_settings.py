"""Pydantic Settings class — isolated module so the heavy pydantic_settings
import tree only loads when a Settings instance is actually requested.

This module is loaded lazily via ``core.config.__getattr__``. Direct callers
should import ``settings`` (not the class) from ``core.config``; the class is
exposed only for type hints and test fixtures.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.paths import GLOBAL_ENV_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEODE_",
        # P2 (v0.95.x) — was literal `str(Path.home() / ".geode" / ".env")`
        env_file=(".env", str(GLOBAL_ENV_FILE)),
        extra="ignore",
    )

    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key", "ANTHROPIC_API_KEY"),
    )
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY"),
    )
    zai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("zai_api_key", "ZAI_API_KEY"),
    )
    # PR-1 G-E (2026-05-21) — bumped from claude-opus-4-6 to match
    # routing.toml [model.defaults] anthropic. ANTHROPIC_PRIMARY constant
    # is the source of truth; this default mirrors it.
    model: str = "claude-opus-4-7"
    learning_extract_model: str = Field(
        default="glm-4.7-flash",
        validation_alias=AliasChoices("learning_extract_model", "GEODE_LEARNING_EXTRACT_MODEL"),
        description=(
            "Free-tier GLM model used by ``core.hooks.llm_extract_learning`` "
            "(PR-1 G-D). Pre-fix this was a hardcoded literal inside the "
            "hook; the field surfaces the knob so operators can flip to "
            "a different free model without editing the hook."
        ),
    )
    # PR-3 C-2 (2026-05-21) — Reflection node knobs. The reflection
    # step runs one extra LLM call per tool-use round to populate
    # ``CognitiveState.hypotheses`` / ``confidence``, so operators
    # who want the loop to stay zero-extra-cost can flip the toggle.
    # Default model is Haiku 4.5 — cheapest current Claude that
    # still follows the JSON schema reliably; operators who want
    # higher quality reflection can switch to opus / sonnet.
    cognitive_reflection_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "cognitive_reflection_enabled",
            "GEODE_COGNITIVE_REFLECTION_ENABLED",
        ),
        description=(
            "When True (default) the agentic loop calls the reflection "
            "node after every tool-use round to derive hypotheses + "
            "confidence. When False the cognitive cycle stays "
            "PERCEIVE → PLAN → ACT → OBSERVE → REFLECT (deterministic) "
            "with no extra LLM call. PR-3 C-2."
        ),
    )
    cognitive_reflection_model: str = Field(
        default="claude-haiku-4-5-20251001",
        validation_alias=AliasChoices(
            "cognitive_reflection_model",
            "GEODE_COGNITIVE_REFLECTION_MODEL",
        ),
        description=(
            "Model used by the reflection node. Default is Haiku 4.5 "
            "(cheapest Claude family that still follows the JSON "
            "schema). Operators wanting higher-fidelity reflection can "
            "set this to opus / sonnet. PR-3 C-2."
        ),
    )
    cognitive_reflection_max_tokens: int = Field(
        default=512,
        validation_alias=AliasChoices(
            "cognitive_reflection_max_tokens",
            "GEODE_COGNITIVE_REFLECTION_MAX_TOKENS",
        ),
        description=(
            "Max tokens for the reflection LLM call. The output is a "
            "small JSON object (hypotheses[<=5] + confidence + "
            "next_action_hint); 512 leaves headroom without bloating "
            "cost. PR-3 C-2."
        ),
    )
    cognitive_reflection_interval: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices(
            "cognitive_reflection_interval",
            "GEODE_COGNITIVE_REFLECTION_INTERVAL",
        ),
        description=(
            "Reflection fires every Nth tool-use round. ``1`` (default) "
            "= every round (current PR-3 behaviour, zero regression). "
            "``3`` = round 1, 4, 7, 10... (skip 2 rounds between calls). "
            "Higher values cut the extra-LLM-call overhead at the cost "
            "of staler hypotheses + confidence. The first round always "
            "runs so the loop sees an LLM-derived belief snapshot "
            "before any throttling kicks in. PR-C (2026-05-21)."
        ),
    )
    verbose: bool = False
    checkpoint_db: str = "geode_checkpoints.db"

    # L4.5 Automation — Drift Detection
    drift_scan_cron: str = "0 */6 * * *"  # Every 6 hours
    drift_warning_threshold: float = 2.5
    drift_critical_threshold: float = 4.0

    # L4.5 Automation — Outcome Tracking
    outcome_tracking_enabled: bool = True

    # L4.5 Automation — Snapshot Manager
    snapshot_dir: str = ""  # empty = auto-resolve via paths.resolve_snapshots_dir()
    snapshot_max_recent: int = 30
    snapshot_gc_threshold: int = 60  # auto-prune when count exceeds this

    # L4.5 Automation — Trigger Manager
    trigger_scheduler_interval_s: float = 60.0

    # L4.5 Automation — Advanced Scheduler
    scheduler_interval_s: float = 1.0  # 1s check interval (claude-code pattern)
    scheduler_auto_start: bool = True
    scheduler_jitter_enabled: bool = True  # Deterministic per-job jitter
    scheduler_max_jitter_ms: float = 900_000.0  # 15 min cap

    # L2 Memory — Session
    session_ttl_hours: float = 4.0
    session_storage_dir: str = ""  # file-backed persistence dir (empty = in-memory only)

    # L2 Memory — Redis/PostgreSQL (simulation URLs)
    redis_url: str = ""
    postgres_url: str = ""

    # L2 Memory — Organization
    organization_fixture_dir: str = ""

    # Tier 0.5 — User Profile
    user_profile_dir: str = ""  # global dir override (default: ~/.geode/user_profile)

    # L4.5 Automation — Model Registry
    model_registry_dir: str = ""  # empty = auto-resolve via paths.resolve_models_dir()

    # MCP Server URLs
    steam_mcp_url: str = ""
    brave_mcp_url: str = ""
    brave_api_key: str = ""
    kg_memory_mcp_url: str = ""

    # Ensemble — Multi-LLM mode
    ensemble_mode: str = "single"  # single | cross
    secondary_analysts: str = "player_experience,discovery"
    primary_analysts: str = "game_mechanics,growth_potential"

    # Graph — Feedback Loop
    confidence_threshold: float = 0.7
    max_iterations: int = 5
    interrupt_nodes: str = ""  # comma-separated node names, e.g. "verification,scoring"

    # LLM — Router & Verification
    # PR-1 G-E — same bump as ``model`` field above.
    router_model: str = "claude-opus-4-7"
    default_secondary_model: str = "gpt-5.4"  # see OPENAI_PRIMARY
    agreement_threshold: float = 0.67

    # Sub-Agent Orchestration (P2)
    max_subagent_depth: int = 1  # 최대 재귀 깊이 (depth=1 강제, Claude Code 패턴)
    max_total_subagents: int = 15  # 세션 내 최대 서브에이전트 수
    subagent_max_rounds: int = 0  # 0 = unlimited (time-based control)
    subagent_max_tokens: int = 32768  # 서브에이전트 출력 토큰 제한 (부모와 동일)

    # Token Guard — tool result truncation threshold (0 = unlimited)
    max_tool_result_tokens: int = 25000  # 0 = no limit; clear_tool_uses handles overflow

    # Tool Result Offloading — store large results to filesystem (P0 token optimization)
    tool_offload_threshold: int = 15000  # tokens; 0 = disabled
    tool_offload_ttl_hours: float = 4.0  # TTL for offloaded results
    observation_mask_keep_rounds: int = 3  # keep recent N rounds unmasked

    # Agentic Loop — time budget (Karpathy P3, OpenClaw Attempt Loop)
    agentic_loop_time_budget: float = 0.0  # 0 = no time limit; >0 = wall-clock seconds

    # Agentic Loop — thinking budget (DTR: Extended Thinking / reasoning tokens)
    agentic_thinking_budget: int = 0  # 0 = disabled; >0 = thinking token budget per call (legacy)

    # Agentic Loop — effort level (replaces thinking_budget for Opus 4.6+ / Sonnet 4.6+)
    # Maps to Anthropic output_config.effort + OpenAI reasoning.effort.
    # v0.56.0 R4-mini — ``xhigh`` added; Opus 4.7-only (the adapter
    # downgrades to ``"max"`` on Opus 4.6 / Sonnet 4.6).
    agentic_effort: str = "high"  # "low" | "medium" | "high" | "max" | "xhigh"

    # Credential source — chosen via the ``/login source`` picker. The picker
    # reads available sources at runtime (local Claude OAuth keychain,
    # Codex auth.json JWT, env-var API key) and persists the user's
    # choice here so :mod:`plugins.petri_audit.models.to_inspect_model`
    # routes ids through the matching provider prefix. ``"auto"`` =
    # legacy behaviour (env / OAuth detection order); explicit values
    # take precedence. No subscription-plan names are hardcoded — the
    # picker labels each source with the plan info pulled from the
    # active credential blob.
    anthropic_credential_source: str = "auto"  # "auto" | "oauth" | "api_key" | "none"
    openai_credential_source: str = "auto"  # "auto" | "oauth" | "api_key" | "none"

    # Cost guard — session-level cost limit (0 = no limit)
    cost_limit_usd: float = 0.0  # fires COST_WARNING at 80%, COST_LIMIT_EXCEEDED at 100%

    # Computer Use — desktop automation (requires pyautogui)
    computer_use_enabled: bool = True  # default on; pyautogui import guard handles missing dep

    # Context Compaction — overflow prevention
    compact_keep_recent: int = 10  # messages to preserve during compaction/prune

    # Notification — external messaging
    notification_channel: str = "slack"  # default notification channel
    notification_recipient: str = "#geode-alerts"  # default recipient
    notification_on_pipeline_end: bool = True
    notification_on_pipeline_error: bool = True
    notification_on_drift: bool = True

    # Gateway — inbound messaging
    gateway_enabled: bool = False  # GEODE_GATEWAY_ENABLED=true to enable
    gateway_poll_interval_s: float = 3.0

    # L4 Gateway Hooks — external webhook endpoint
    webhook_enabled: bool = False  # GEODE_WEBHOOK_ENABLED=true to enable
    webhook_port: int = 8765

    # Calendar — external calendar sync
    calendar_sync_on_trigger: bool = False  # auto-sync on TRIGGER_FIRED

    # Sandbox — file tool path validation (Claude Code parity)
    sandbox_max_file_size_bytes: int = 262_144  # 256KB pre-read guard
    sandbox_max_read_tokens: int = 25_000  # post-read token estimate guard
    sandbox_max_glob_results: int = 100  # GlobTool max results
    sandbox_max_grep_results: int = 50  # GrepTool max files
    sandbox_max_grep_line_chars: int = 200  # GrepTool match line truncation

    # HITL Level — Human-in-the-loop control
    # 0 = autonomous (skip all prompts), 1 = write-only (prompt only for writes),
    # 2 = all prompts (default, ask everything)
    hitl_level: int = 2

    # Plan Mode — Autonomous Execution
    plan_auto_execute: bool = False  # GEODE_PLAN_AUTO_EXECUTE=true to enable

    # LLM Connection — httpx pool & timeout tuning
    llm_max_connections: int = 20  # httpx pool: max total connections
    llm_max_keepalive_connections: int = 5  # httpx pool: max idle keep-alive connections
    llm_keepalive_expiry: float = 30.0  # idle conn TTL (match API server timeout)
    llm_connect_timeout: float = 5.0  # TCP connect timeout (fail fast)
    llm_read_timeout: float = 300.0  # response read timeout (5min for 1M context)
    llm_write_timeout: float = 30.0  # request write timeout (seconds)
    llm_pool_timeout: float = 10.0  # wait for available connection from pool (seconds)
    llm_retry_base_delay: float = 2.0  # base delay for exponential backoff (seconds)
    llm_retry_max_delay: float = 30.0  # max delay cap for retries (seconds)
    llm_max_retries: int = 3  # max retry attempts per model

    # v0.52.4 — per-provider auth-mode escape hatch (Codex CLI parity).
    # Default routing prefers SUBSCRIPTION/OAUTH plans over PAYG when both
    # can serve the requested model (matches openai/codex CLI default).
    # Override per provider when the user deliberately wants metered PAYG:
    #   forced_login_method = {"openai": "apikey"}    # use OPENAI_API_KEY even
    #                                                  # if Codex Plus OAuth is registered
    # Valid values: "subscription" (default), "apikey", "auto" (alias).
    # Reference: openai/codex#2733, #3286.
    forced_login_method: dict[str, str] = {}

    # LLM — Fallback cost ratio control (C2: 0 = unlimited)
    llm_max_fallback_cost_ratio: float = 0.0

    # Pipeline — timeout in seconds (B3: 0 = no timeout)
    pipeline_timeout_s: float = 600.0

    # Concurrency — workload lane limits
    gateway_max_concurrent: int = 4  # max simultaneous Gateway messages
