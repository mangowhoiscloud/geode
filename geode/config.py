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
    model: str = "claude-opus-4-6"
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

    # L4.5 Automation — Trigger Manager
    trigger_scheduler_interval_s: float = 60.0

    # L2 Memory — Session
    session_ttl_hours: float = 4.0

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

    # Graph — Feedback Loop
    confidence_threshold: float = 0.7
    max_iterations: int = 5


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
