"""GEODE configuration via Pydantic BaseSettings."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    model: str = "claude-sonnet-4-5-20250929"
    verbose: bool = False
    checkpoint_db: str = "geode_checkpoints.db"


settings = Settings()
