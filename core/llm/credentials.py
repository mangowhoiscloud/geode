"""LLM credential resolution — shared ProfileRotator key lookup.

Centralizes the OAuth-preferred → API-key-fallback pattern used
by Anthropic and OpenAI providers.

Profile tracking: stores the last-resolved profile per provider
so that success/failure callbacks can notify the ProfileRotator
without re-resolving (OpenClaw ``markAuthProfileGood``/``markAuthProfileFailure`` pattern).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.auth.profiles import AuthProfile

log = logging.getLogger(__name__)

# Last-resolved profile per provider (set in resolve_provider_key, read in callbacks).
_last_profile: dict[str, AuthProfile] = {}


def get_last_profile(provider: str) -> Any:
    """Return the last profile resolved for *provider*, or None."""
    return _last_profile.get(provider)


def resolve_provider_key(provider: str, settings_fallback: str) -> str:
    """Resolve API key via ProfileRotator (OAuth preferred) or settings fallback.

    Stores the resolved profile in ``_last_profile`` for downstream
    ``on_llm_success``/``on_llm_failure`` callbacks.

    Args:
        provider: Provider name for rotator lookup ("anthropic", "openai").
        settings_fallback: API key string from settings (used when rotator unavailable).

    Returns:
        Resolved API key string.
    """
    try:
        from core.lifecycle.container import get_profile_rotator

        rotator = get_profile_rotator()
        if rotator:
            profile = rotator.resolve(provider)
            if profile and profile.key:
                _last_profile[provider] = profile
                rotator.mark_used(profile)
                return profile.key
    except Exception:
        log.debug("ProfileRotator not available for %s, falling back to settings", provider)
    return settings_fallback


def notify_llm_success(provider: str) -> None:
    """Notify ProfileRotator of a successful LLM call.

    Resets error count and cooldown for the last-resolved profile (OpenClaw pattern).
    """
    profile = _last_profile.get(provider)
    if profile is None:
        return
    try:
        from core.lifecycle.container import get_profile_rotator

        rotator = get_profile_rotator()
        if rotator:
            rotator.mark_success(profile)
    except Exception:
        log.debug("notify_llm_success failed for %s", provider)


def notify_llm_failure(provider: str, exc: Exception) -> None:
    """Notify ProfileRotator of a failed LLM call.

    Classifies auth errors (401/403) to trigger managed token refresh.
    """
    profile = _last_profile.get(provider)
    if profile is None:
        return
    try:
        from core.lifecycle.container import get_profile_rotator
        from core.llm.fallback import _is_auth_error

        rotator = get_profile_rotator()
        if rotator:
            rotator.mark_failure(profile, is_auth_error=_is_auth_error(exc))
    except Exception:
        log.debug("notify_llm_failure failed for %s", provider)
