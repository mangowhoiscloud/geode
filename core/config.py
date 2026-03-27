"""GEODE configuration via Pydantic BaseSettings.

Config Cascade (priority high → low):
  1. CLI arguments
  2. Environment variables / .env
  3. Project TOML: .geode/config.toml
  4. Global TOML: ~/.geode/config.toml
  5. Code defaults
"""

from __future__ import annotations

import logging
import os
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.paths import GLOBAL_CONFIG_TOML, GLOBAL_ENV_FILE, PROJECT_CONFIG_TOML

log = logging.getLogger(__name__)

_settings_lock = threading.Lock()

# ---------------------------------------------------------------------------
# TOML Config Cascade
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_TOML
PROJECT_CONFIG_PATH = PROJECT_CONFIG_TOML

# Mapping: TOML dotted key → Settings field name.
# Only mapped keys are applied; unknown TOML keys are silently ignored.
_TOML_TO_SETTINGS: dict[str, str] = {
    "llm.primary_model": "model",
    "llm.secondary_model": "default_secondary_model",
    "llm.router_model": "router_model",
    "output.verbose": "verbose",
    "pipeline.confidence_threshold": "confidence_threshold",
    "pipeline.max_iterations": "max_iterations",
}

DEFAULT_CONFIG_TOML = """\
# GEODE config.toml
# Priority: CLI > env > project .geode/config.toml > global ~/.geode/config.toml > defaults
#
# Uncomment and edit values to override defaults.

[llm]
# primary_model = "claude-opus-4-6"
# secondary_model = "gpt-5.4"
# router_model = "claude-opus-4-6"

[output]
# verbose = false

[pipeline]
# confidence_threshold = 0.7
# max_iterations = 5
"""


def _flatten_toml(
    data: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:
    """Flatten nested TOML dict to dotted-key → value mapping.

    Example:
        {"llm": {"primary_model": "x"}} → {"llm.primary_model": "x"}
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_toml(value, f"{full_key}."))
        else:
            result[full_key] = value
    return result


def _load_toml_config(
    *,
    global_path: Path | None = None,
    project_path: Path | None = None,
) -> dict[str, Any]:
    """Load and merge TOML configs: project overrides global.

    Returns a dict mapping Settings field names to their values.
    Only keys present in _TOML_TO_SETTINGS are returned.
    """
    gp = global_path or GLOBAL_CONFIG_PATH
    pp = project_path or PROJECT_CONFIG_PATH
    merged: dict[str, Any] = {}

    for path in (gp, pp):  # global first (lower prio), project second (higher)
        if not path.exists():
            continue
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
            flat = _flatten_toml(raw)
            for toml_key, settings_field in _TOML_TO_SETTINGS.items():
                if toml_key in flat:
                    merged[settings_field] = flat[toml_key]
        except Exception:
            log.warning("Failed to load TOML config %s, skipping", path, exc_info=True)

    return merged


def _apply_toml_overlay(s: Settings) -> None:
    """Overlay TOML values onto Settings for fields not set by env vars."""
    toml_values = _load_toml_config()
    if not toml_values:
        return

    for field_name, toml_value in toml_values.items():
        # Skip fields that were explicitly set via environment variable.
        # Pydantic Settings loads from GEODE_<FIELD> and .env automatically.
        # We only overlay TOML for fields still at their code default.
        env_key = f"GEODE_{field_name.upper()}"
        if env_key in os.environ:
            continue
        # Also check special alias env vars for API keys
        if field_name in ("anthropic_api_key", "openai_api_key", "zai_api_key"):
            continue
        if hasattr(s, field_name):
            object.__setattr__(s, field_name, toml_value)


GLOBAL_ENV_PATH = GLOBAL_ENV_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEODE_",
        env_file=(".env", str(Path.home() / ".geode" / ".env")),
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
    model: str = "claude-opus-4-6"  # overridden by GEODE_MODEL env var; see ANTHROPIC_PRIMARY
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
    scheduler_interval_s: float = 60.0
    scheduler_auto_start: bool = True

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
    router_model: str = "claude-opus-4-6"  # see ANTHROPIC_PRIMARY
    default_secondary_model: str = "gpt-5.4"  # see OPENAI_PRIMARY
    agreement_threshold: float = 0.67

    # Sub-Agent Orchestration (P2)
    max_subagent_depth: int = 2  # 최대 재귀 깊이 (root=0 → depth 2까지 허용)
    max_total_subagents: int = 15  # 세션 내 최대 서브에이전트 수
    subagent_max_rounds: int = 10  # 서브에이전트 agentic loop 라운드 제한
    subagent_max_tokens: int = 8192  # 서브에이전트 출력 토큰 제한

    # Token Guard — tool result truncation threshold (0 = unlimited)
    max_tool_result_tokens: int = 0  # 0 = no limit; clear_tool_uses handles overflow

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


_settings_instance: Settings | None = None


def _get_settings() -> Settings:
    """Get or create the Settings singleton in a thread-safe manner.

    After Pydantic loads from env/.env, overlays TOML config values
    for fields not explicitly set via environment variables.
    """
    global _settings_instance
    if _settings_instance is not None:
        return _settings_instance
    with _settings_lock:
        # Double-checked locking
        if _settings_instance is None:
            s = Settings()
            _apply_toml_overlay(s)
            _settings_instance = s
        return _settings_instance


settings = _get_settings()

# ---------------------------------------------------------------------------
# Model constants — single source of truth for model names & pricing
# All code MUST reference these instead of hardcoding model strings.
# ---------------------------------------------------------------------------

# Anthropic models
ANTHROPIC_PRIMARY = "claude-opus-4-6"
ANTHROPIC_SECONDARY = "claude-sonnet-4-6"
ANTHROPIC_BUDGET = "claude-haiku-4-5-20251001"
ANTHROPIC_FALLBACK_CHAIN: list[str] = [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY]

# OpenAI models
OPENAI_PRIMARY = "gpt-5.4"
OPENAI_FALLBACK_CHAIN: list[str] = ["gpt-5.4", "gpt-5.2", "gpt-4.1"]

# ZhipuAI (GLM) models — OpenAI-compatible API, separate provider
GLM_PRIMARY = "glm-5"
GLM_FALLBACK_CHAIN: list[str] = ["glm-5", "glm-5-turbo", "glm-4.7-flash"]
GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"


def _resolve_provider(model: str) -> str:
    """Resolve provider name from model ID.

    Prefix-based inference with broad model coverage:
      claude-*   → anthropic
      glm-*      → glm
      gpt-*      → openai
      o3-*/o4-*  → openai
      gemini-*   → google
      deepseek-* → deepseek
      llama-*    → meta
      qwen-*/qwen3* → alibaba
      (fallback) → openai
    """
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("glm-"):
        return "glm"
    if model.startswith(("gpt-", "o3-", "o4-")):
        return "openai"
    if model.startswith("gemini-"):
        return "google"
    if model.startswith("deepseek-"):
        return "deepseek"
    if model.startswith("llama-"):
        return "meta"
    if model.startswith(("qwen-", "qwen3")):
        return "alibaba"
    return "openai"


# Pricing — canonical source: core.llm.token_tracker.MODEL_PRICING
# Re-exported here for backward compatibility.
from core.llm.token_tracker import MODEL_PRICING as MODEL_PRICING  # noqa: E402

# ---------------------------------------------------------------------------
# Model Policy — allowlist / denylist governance (.geode/model-policy.toml)
# ---------------------------------------------------------------------------

MODEL_POLICY_PATH = Path(".geode") / "model-policy.toml"


@dataclass
class ModelPolicy:
    """Model governance policy loaded from .geode/model-policy.toml."""

    allowlist: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    default_model: str = ""


def load_model_policy(policy_path: Path | None = None) -> ModelPolicy:
    """Load .geode/model-policy.toml. Returns empty policy (all allowed) if missing."""
    path = policy_path or MODEL_POLICY_PATH
    if not path.exists():
        return ModelPolicy()
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        section = raw.get("policy", {})
        return ModelPolicy(
            allowlist=section.get("allowlist", []),
            denylist=section.get("denylist", []),
            default_model=section.get("default_model", ""),
        )
    except Exception:
        log.warning("Failed to load model policy from %s, using empty policy", path, exc_info=True)
        return ModelPolicy()


def is_model_allowed(model: str, policy: ModelPolicy | None = None) -> bool:
    """Check if a model is allowed by the policy. Empty policy = all allowed."""
    if policy is None:
        policy = load_model_policy()
    # allowlist takes precedence: if set, only listed models are allowed
    if policy.allowlist:
        return model in policy.allowlist
    # denylist: if set, listed models are blocked
    if policy.denylist:
        return model not in policy.denylist
    return True


# ---------------------------------------------------------------------------
# Routing Config — per-node model routing (.geode/routing.toml)
# ---------------------------------------------------------------------------

ROUTING_CONFIG_PATH = Path(".geode") / "routing.toml"

_routing_config_cache: RoutingConfig | None = None


@dataclass
class RoutingConfig:
    """Per-node model routing loaded from .geode/routing.toml."""

    nodes: dict[str, str] = field(default_factory=dict)
    agentic: dict[str, str] = field(default_factory=dict)


def load_routing_config(path: Path | None = None) -> RoutingConfig:
    """Load .geode/routing.toml. Returns empty config (default model) if missing."""
    global _routing_config_cache
    if _routing_config_cache is not None:
        return _routing_config_cache
    cfg_path = path or ROUTING_CONFIG_PATH
    if not cfg_path.exists():
        _routing_config_cache = RoutingConfig()
        return _routing_config_cache
    try:
        with open(cfg_path, "rb") as f:
            raw = tomllib.load(f)
        _routing_config_cache = RoutingConfig(
            nodes=raw.get("nodes", {}),
            agentic=raw.get("agentic", {}),
        )
        return _routing_config_cache
    except Exception:
        log.warning("Failed to load routing config from %s", cfg_path, exc_info=True)
        _routing_config_cache = RoutingConfig()
        return _routing_config_cache


# Pipeline nodes ALWAYS use these models regardless of user's REPL model.
# When routing.toml has no per-node config, these defaults prevent
# fallback to settings.model (the user's active REPL model like glm-5).
_PIPELINE_NODE_DEFAULTS: dict[str, str] = {
    "analyst": ANTHROPIC_PRIMARY,
    "evaluator": ANTHROPIC_PRIMARY,
    "scoring": ANTHROPIC_PRIMARY,
    "synthesizer": ANTHROPIC_PRIMARY,
}


def get_node_model(node_name: str) -> str | None:
    """Return the model for a pipeline node, or None for default fallback.

    Priority: routing.toml > _PIPELINE_NODE_DEFAULTS > None.
    Pipeline nodes (analyst, evaluator, scoring, synthesizer) always return
    a fixed model so they never inherit the user's REPL model.
    """
    cfg = load_routing_config()
    return cfg.nodes.get(node_name) or _PIPELINE_NODE_DEFAULTS.get(node_name)


def reset_routing_cache() -> None:
    """Clear the routing config cache (for testing)."""
    global _routing_config_cache
    _routing_config_cache = None
