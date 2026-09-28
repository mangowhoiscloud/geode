"""Credential-gated judgment selection shared by runtime and operator surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from core.config.env_io import is_placeholder

if TYPE_CHECKING:
    from core.config import Settings


def resolve_judgment_route(
    config: Settings, *, engine: str | None = None, provider: str | None = None
) -> tuple[str, SecretStr, str | None] | None:
    """Resolve Jev once per call; a missing key retains the LLM route.

    The returned key is private transport input, never an operator/status field.
    Auto selection is deterministic and is not a failed-request fallback policy.
    """
    if (engine if engine is not None else config.judgment_engine) != "jev":
        return None
    preference = provider if provider is not None else config.jev_provider
    providers = ("typesafe", "openrouter") if preference == "auto" else (preference,)
    for route_provider in providers:
        base_url = None
        if route_provider == "typesafe":
            key = config.typesafe_api_key.get_secret_value()
        else:
            from core.llm.adapters.typesafe import OPENROUTER_JEV_MODEL
            from core.llm.registry import get_provider_spec
            from core.llm.routing import infer_source, resolve_routing

            spec = get_provider_spec("openrouter")
            if spec is None:
                raise RuntimeError("OpenRouter provider composition is not registered")
            source = infer_source("openrouter", model=OPENROUTER_JEV_MODEL, settings=config)
            target = resolve_routing(
                OPENROUTER_JEV_MODEL,
                provider="openrouter",
                source=source,
                base_url=spec.default_base_url,
            )
            key = target.profile.key if target is not None else config.openrouter_api_key
            base_url = target.base_url if target is not None else spec.default_base_url
        key = key.strip()
        if key and not is_placeholder(key):
            return route_provider, SecretStr(key), base_url
    return None


def judgment_status(*, engine: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """Expose preference and effective route without credential fragments."""
    from core.config import settings

    selected_engine = engine if engine is not None else settings.judgment_engine
    selected_provider = provider if provider is not None else settings.jev_provider
    route = resolve_judgment_route(settings, engine=selected_engine, provider=selected_provider)
    return {
        "engine": selected_engine,
        "effective_engine": "jev" if route else "llm",
        "provider": route[0] if route else None,
        "provider_preference": selected_provider,
        "reason": "missing_jev_key" if selected_engine == "jev" and not route else None,
        "cadence": "each_round_and_before_final_response",
    }


def validate_judgment_selection(engine: str, *, provider: str | None = None) -> Settings:
    """Validate preference and precedence without writing defaults or live state."""
    from core.config import settings
    from core.config.explain import explain_field

    updates = {"judgment_engine": engine, "jev_provider": provider or settings.jev_provider}
    candidate = type(settings).model_validate({**settings.model_dump(), **updates})
    if engine == "jev" and resolve_judgment_route(candidate) is None:
        raise ValueError("Jev requires a TypeSafe key or a usable OpenRouter API-key route")
    for field, value in updates.items():
        report = explain_field(field)
        winner = report.winner
        if (
            winner is not None
            and winner.layer not in {"global config.toml", "code default"}
            and str(winner.value) != value
        ):
            raise ValueError(f"{field} is controlled by {winner.layer}; edit that layer first")
    return candidate


def configure_judgment(
    engine: str, *, provider: str | None = None, admitted: Settings | None = None
) -> dict[str, Any]:
    """Persist a checked preference; existing sessions retain their own selection."""
    from core.config import settings
    from core.config.toml_edit import persist_toml_section

    candidate = (
        admitted if admitted is not None else validate_judgment_selection(engine, provider=provider)
    )
    persist_toml_section(
        "judgment", {"engine": candidate.judgment_engine, "provider": candidate.jev_provider}
    )
    for field in ("judgment_engine", "jev_provider"):
        object.__setattr__(settings, field, getattr(candidate, field))
    return judgment_status()
