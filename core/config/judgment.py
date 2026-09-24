"""Credential-gated judgment selection shared by runtime and operator surfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from core.config.env_io import is_placeholder

if TYPE_CHECKING:
    from core.config import Settings


def resolve_judgment_route(config: Settings) -> tuple[str, SecretStr] | None:
    """Resolve Jev once per call; a missing key retains the LLM route.

    The returned key is private transport input, never an operator/status field.
    Auto selection is deterministic and is not a failed-request fallback policy.
    """
    if config.judgment_engine != "jev":
        return None
    providers = (
        ("typesafe", "openrouter") if config.jev_provider == "auto" else (config.jev_provider,)
    )
    for provider in providers:
        key = (
            config.typesafe_api_key.get_secret_value()
            if provider == "typesafe"
            else config.openrouter_api_key
        ).strip()
        if key and not is_placeholder(key):
            return provider, SecretStr(key)
    return None


def judgment_status() -> dict[str, Any]:
    """Expose preference and effective route without credential fragments."""
    from core.config import settings

    route = resolve_judgment_route(settings)
    return {
        "engine": settings.judgment_engine,
        "effective_engine": "jev" if route else "llm",
        "provider": route[0] if route else None,
        "provider_preference": settings.jev_provider,
        "reason": "missing_jev_key" if settings.judgment_engine == "jev" and not route else None,
        "cadence": "each_round_and_before_final_response",
    }


def configure_judgment(engine: str, *, provider: str | None = None) -> dict[str, Any]:
    """Apply an explicit operator selection to the existing global config owner.

    Higher-priority env/project settings are not erased to make a picker appear
    effective. The caller gets an error naming the masking field instead.
    """
    from core.config import settings
    from core.config.explain import explain_field
    from core.config.toml_edit import persist_toml_section

    updates = {"judgment_engine": engine, "jev_provider": provider or settings.jev_provider}
    candidate = type(settings).model_validate({**settings.model_dump(), **updates})
    if engine == "jev" and resolve_judgment_route(candidate) is None:
        raise ValueError(
            "Jev requires TYPESAFE_API_KEY or OPENROUTER_API_KEY for the selected route"
        )
    for field, value in updates.items():
        report = explain_field(field)
        winner = report.winner
        if (
            winner is not None
            and winner.layer not in {"global config.toml", "code default"}
            and str(winner.value) != value
        ):
            raise ValueError(f"{field} is controlled by {winner.layer}; edit that layer first")
    persist_toml_section(
        "judgment", {"engine": candidate.judgment_engine, "provider": candidate.jev_provider}
    )
    for field in updates:
        object.__setattr__(settings, field, getattr(candidate, field))
    return judgment_status()
