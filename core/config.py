"""GEODE configuration via Pydantic BaseSettings."""

from __future__ import annotations

import threading

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_settings_lock = threading.Lock()


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


_settings_instance: Settings | None = None


def _get_settings() -> Settings:
    """Get or create the Settings singleton in a thread-safe manner."""
    global _settings_instance
    if _settings_instance is not None:
        return _settings_instance
    with _settings_lock:
        # Double-checked locking
        if _settings_instance is None:
            _settings_instance = Settings()
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
