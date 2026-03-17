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
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

_settings_lock = threading.Lock()

# ---------------------------------------------------------------------------
# TOML Config Cascade
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_PATH = Path.home() / ".geode" / "config.toml"
PROJECT_CONFIG_PATH = Path(".geode") / "config.toml"

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
        if field_name in ("anthropic_api_key", "openai_api_key"):
            continue
        if hasattr(s, field_name):
            object.__setattr__(s, field_name, toml_value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEODE_",
        env_file=".env",
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
    snapshot_dir: str = ".geode/snapshots"
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
    model_registry_dir: str = ".geode/models"

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
    max_tool_result_tokens: int = 0  # 0 = no limit; frontier consensus: compression > hard cap

    # Plan Mode — Autonomous Execution
    plan_auto_execute: bool = False  # GEODE_PLAN_AUTO_EXECUTE=true to enable

    # LLM Connection — httpx pool & timeout tuning
    llm_max_connections: int = 20  # httpx pool: max total connections
    llm_max_keepalive_connections: int = 5  # httpx pool: max idle keep-alive connections
    llm_keepalive_expiry: float = 15.0  # idle conn TTL (shorter = fewer stale)
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
ANTHROPIC_SECONDARY = "claude-sonnet-4-5-20250929"
ANTHROPIC_BUDGET = "claude-haiku-4-5-20251001"
ANTHROPIC_FALLBACK_CHAIN: list[str] = [ANTHROPIC_PRIMARY, ANTHROPIC_SECONDARY]

# OpenAI models
OPENAI_PRIMARY = "gpt-5.4"
OPENAI_FALLBACK_CHAIN: list[str] = ["gpt-5.4", "gpt-5.2", "gpt-4.1"]

# Pricing — canonical source: core.llm.token_tracker.MODEL_PRICING
# Re-exported here for backward compatibility.
from core.llm.token_tracker import MODEL_PRICING as MODEL_PRICING  # noqa: E402
