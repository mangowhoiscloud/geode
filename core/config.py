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

# Pricing (USD per 1M tokens) — updated 2026-03
# Source: https://developers.openai.com/api/docs/pricing/
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    ANTHROPIC_PRIMARY: {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    ANTHROPIC_SECONDARY: {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    ANTHROPIC_BUDGET: {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
    # OpenAI — GPT-5 family
    "gpt-5.4": {"input": 2.50 / 1_000_000, "output": 15.0 / 1_000_000},
    "gpt-5.2": {"input": 1.75 / 1_000_000, "output": 14.0 / 1_000_000},
    "gpt-5.1": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    "gpt-5": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    # OpenAI — GPT-4 family
    "gpt-4.1": {"input": 2.00 / 1_000_000, "output": 8.0 / 1_000_000},
    "gpt-4.1-mini": {"input": 0.40 / 1_000_000, "output": 1.60 / 1_000_000},
    "gpt-4.1-nano": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    # OpenAI — Reasoning
    "o3": {"input": 2.00 / 1_000_000, "output": 8.0 / 1_000_000},
    "o3-mini": {"input": 1.10 / 1_000_000, "output": 4.40 / 1_000_000},
    "o4-mini": {"input": 1.10 / 1_000_000, "output": 4.40 / 1_000_000},
}
