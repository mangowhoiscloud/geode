"""Non-secret model policy owned by one running session.

Persisted preferences seed new sessions. Explicit session changes replace this
validated value; changing process-global defaults never edits an existing value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from core.config import Settings


class SessionModelConfig(BaseModel):
    """The bounded model-policy subset, not a Settings or credential snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    model: str = Field(min_length=1, max_length=256)
    effort: str = Field(min_length=1, max_length=32)
    source: str = Field(min_length=1, max_length=128)
    reflection_model: str = Field(default="", max_length=256)
    reflection_source: str = Field(default="", max_length=128)
    judge_model: str = Field(default="", max_length=256)
    judge_source: str = Field(default="", max_length=128)
    judgment_engine: Literal["llm", "jev"] = "llm"
    jev_provider: Literal["auto", "typesafe", "openrouter"] = "auto"
    reflection_max_tokens: int = Field(default=512, gt=0)
    temperature_agent_loop: float = Field(default=1.0, ge=0.0, le=2.0, allow_inf_nan=False)
    temperature_reflection: float = Field(default=1.0, ge=0.0, le=2.0, allow_inf_nan=False)

    def updated(self, changes: dict[str, Any]) -> SessionModelConfig:
        """Validate the complete candidate before publishing any changed field."""
        return type(self).model_validate({**self.model_dump(), **changes})


def capture_session_model_config(
    settings: Settings, *, model: str, effort: str, source: str
) -> SessionModelConfig:
    """Resolve auxiliary route preferences once, outside pure value validation."""
    from core.config import _resolve_provider
    from core.llm.adapters._source_inference import infer_source

    reflection = settings.cognitive_reflection_model
    judge = settings.judge_model
    return SessionModelConfig(
        model=model,
        effort=effort,
        source=source,
        reflection_model=reflection,
        reflection_source=infer_source(_resolve_provider(reflection)) if reflection else "",
        judge_model=judge,
        judge_source=infer_source(_resolve_provider(judge)) if judge else "",
        judgment_engine=settings.judgment_engine,
        jev_provider=settings.jev_provider,
        reflection_max_tokens=settings.cognitive_reflection_max_tokens,
        temperature_agent_loop=settings.temperature_agent_loop,
        temperature_reflection=settings.temperature_reflection,
    )
