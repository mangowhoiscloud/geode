"""Non-secret model policy owned by one running session.

Persisted preferences seed new sessions. Explicit session changes replace this
validated value; changing process-global defaults never edits an existing value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from core.config import Settings
    from core.config.policy_source import PolicySourcePaths


def resolve_initial_model(
    settings: Settings | None = None, *, sources: PolicySourcePaths | None = None
) -> tuple[str, str]:
    """Seed an unconfigured session from its sole eligible provider default.

    Explicit model/source/policy choices remain authoritative even when unusable.
    This returns a session preference; it never persists settings or changes an
    existing session (including a restored checkpoint).
    """
    from core.config import _get_settings, _resolve_provider
    from core.config.explain import explain_field
    from core.config.runtime_policy_sources import build_policy_source_bundle
    from core.llm.adapters.registry import active_registry_snapshot, bootstrap_builtins
    from core.llm.registry import PROVIDER_VARIANTS
    from core.llm.routing import _model_plans, infer_source, model_available

    effective = settings if settings is not None else _get_settings()
    bundle = build_policy_source_bundle()
    if sources is None:
        sources = bundle.get("provider_routing")
    bootstrap_builtins(policy_sources=bundle)
    model = effective.model
    source = infer_source(
        _resolve_provider(model), model=model, sources=sources, settings=effective
    )

    def explicit(field: str) -> bool:
        if field not in type(effective).model_fields:
            # A plugin may own an external policy field; its provenance is not
            # ours to interpret as an unset preference.
            return True
        if (
            field in effective.model_fields_set
            or getattr(effective, field) != type(effective).model_fields[field].default
        ):
            return True
        winner = explain_field(field).winner
        return winner is None or winner.layer != "code default"

    specs = dict(PROVIDER_VARIANTS)
    for registration in active_registry_snapshot().registrations.values():
        if registration.provider_spec is not None:
            specs[registration.provider_spec.id] = registration.provider_spec
    source_fields = {spec.credential.settings_field for spec in specs.values()} - {""}
    if (
        explicit("model")
        or any(explicit(field) for field in source_fields)
        or effective.forced_login_method
        or _model_plans(model, sources)
        or model_available(model, source=source)
    ):
        return model, source
    candidates: set[tuple[str, str]] = set()
    for spec in specs.values():
        candidate = spec.profile.default_model()
        if not candidate:
            continue
        selected = infer_source(
            spec.profile.provider, model=candidate, sources=sources, settings=effective
        )
        if model_available(candidate, source=selected):
            candidates.add((candidate, selected))
    return next(iter(candidates)) if len(candidates) == 1 else (model, source)


class ModelRouteQuery(BaseModel):
    """A nonsecret request for the backend's current route eligibility."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=256)
    source: Literal["payg", "subscription", "adapter"] | None = None


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
    settings: Settings,
    *,
    model: str,
    effort: str,
    source: str,
    sources: PolicySourcePaths | None = None,
) -> SessionModelConfig:
    """Resolve auxiliary route preferences once, outside pure value validation."""
    from core.config import _resolve_provider
    from core.llm.routing import infer_source

    reflection = settings.cognitive_reflection_model
    judge = settings.judge_model
    return SessionModelConfig(
        model=model,
        effort=effort,
        source=source,
        reflection_model=reflection,
        reflection_source=infer_source(
            _resolve_provider(reflection), model=reflection, sources=sources, settings=settings
        )
        if reflection
        else "",
        judge_model=judge,
        judge_source=infer_source(
            _resolve_provider(judge), model=judge, sources=sources, settings=settings
        )
        if judge
        else "",
        judgment_engine=settings.judgment_engine,
        jev_provider=settings.jev_provider,
        reflection_max_tokens=settings.cognitive_reflection_max_tokens,
        temperature_agent_loop=settings.temperature_agent_loop,
        temperature_reflection=settings.temperature_reflection,
    )
