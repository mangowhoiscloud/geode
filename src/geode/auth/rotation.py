"""Profile Rotation — type-priority round-robin selection.

OpenClaw pattern: select best available profile by
type priority (oauth > token > api_key), then LRU within same type.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from geode.auth.profiles import AuthProfile, ProfileStore

log = logging.getLogger(__name__)


class ProfileRotator:
    """Selects the best available auth profile for a provider.

    Resolution order:
    1. Filter: available only (not disabled, not expired, not cooling down)
    2. Sort by type priority (oauth > token > api_key)
    3. Within same type: LRU (least recently used first)
    """

    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    def resolve(self, provider: str) -> AuthProfile | None:
        """Resolve the best available profile for a provider.

        Returns None if no profiles are available.
        """
        available = self._store.list_available(provider)
        if not available:
            log.warning("No available profiles for provider=%s", provider)
            return None

        # Sort: type priority first, then LRU
        available.sort(key=lambda p: p.sort_key())
        selected = available[0]

        log.debug(
            "Resolved profile=%s (type=%s) for provider=%s from %d candidates",
            selected.name,
            selected.credential_type.value,
            provider,
            len(available),
        )
        return selected

    def mark_used(self, profile: AuthProfile) -> None:
        """Mark a profile as just used (updates last_used timestamp)."""
        profile.last_used = time.time()

    def mark_success(self, profile: AuthProfile) -> None:
        """Mark a successful API call — reset error count."""
        profile.error_count = 0
        profile.cooldown_until = 0.0

    def mark_failure(self, profile: AuthProfile) -> None:
        """Mark a failed API call — increment errors, apply cooldown."""
        profile.error_count += 1
        cooldown_ms = calculate_cooldown_ms(profile.error_count)
        profile.cooldown_until = time.time() + cooldown_ms / 1000.0
        log.warning(
            "Profile %s failed (count=%d), cooldown=%dms",
            profile.name,
            profile.error_count,
            cooldown_ms,
        )

    def disable(self, profile: AuthProfile, reason: str) -> None:
        """Disable a profile (e.g. quota exceeded, billing issue)."""
        profile.disabled = True
        profile.disabled_reason = reason
        log.info("Profile %s disabled: %s", profile.name, reason)

    def enable(self, profile: AuthProfile) -> None:
        """Re-enable a disabled profile."""
        profile.disabled = False
        profile.disabled_reason = ""
        profile.error_count = 0
        profile.cooldown_until = 0.0

    def get_status(self) -> list[dict[str, Any]]:
        """Get status summary for all profiles."""
        result = []
        for p in self._store.list_all():
            status = "active"
            if p.disabled:
                status = f"disabled:{p.disabled_reason}"
            elif p.is_cooling_down:
                remaining = int(p.cooldown_until - time.time())
                status = f"cooldown {remaining}s"
            elif p.is_expired:
                status = "expired"

            result.append(
                {
                    "name": p.name,
                    "provider": p.provider,
                    "type": p.credential_type.value,
                    "display": p.masked_key,
                    "status": status,
                    "error_count": p.error_count,
                }
            )
        return result


def calculate_cooldown_ms(error_count: int) -> int:
    """Calculate cooldown duration in ms using exponential backoff.

    OpenClaw formula: min(60min, 1min × 5^(n-1)) for n = capped at 4.
    Progression: 1min → 5min → 25min → 60min (max).
    """
    normalized = max(1, error_count)
    result: int = min(60 * 60 * 1000, 60 * 1000 * (5 ** min(normalized - 1, 3)))
    return result
