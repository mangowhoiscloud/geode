"""LLM credential resolution — shared ProfileRotator key lookup.

Centralizes the OAuth-preferred → API-key-fallback pattern used
by Anthropic and OpenAI providers.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def resolve_provider_key(provider: str, settings_fallback: str) -> str:
    """Resolve API key via ProfileRotator (OAuth preferred) or settings fallback.

    Args:
        provider: Provider name for rotator lookup ("anthropic", "openai").
        settings_fallback: API key string from settings (used when rotator unavailable).

    Returns:
        Resolved API key string.
    """
    try:
        from core.runtime_wiring.infra import get_profile_rotator

        rotator = get_profile_rotator()
        if rotator:
            profile = rotator.resolve(provider)
            if profile and profile.key:
                rotator.mark_used(profile)
                return profile.key
    except Exception:
        log.debug("ProfileRotator not available for %s, falling back to settings", provider)
    return settings_fallback
