"""Profile Rotation — type-priority round-robin selection.

OpenClaw pattern: select best available profile by
type priority (oauth > token > api_key), then LRU within same type.

Managed token lifecycle:
- Proactive refresh: re-read from external storage if expiry within 120s
- 401 auto-refresh: re-read on auth failure before applying cooldown
- Hermes ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from core.gateway.auth.profiles import AuthProfile, EligibilityResult, ProfileStore

# Module-level cache of the most recent eligibility breakdown per provider.
# Read by ``credential_breadcrumb.format()`` so the LLM-facing system
# message reflects the same verdicts the rotator just considered.
_LAST_VERDICTS: dict[str, list[EligibilityResult]] = {}


def get_last_eligibility_verdicts(provider: str) -> list[EligibilityResult]:
    """Return the verdicts captured by the last ``ProfileRotator.resolve(provider)`` call.

    Used by ``credential_breadcrumb.format()`` to inject an LLM-readable
    note after auth failures. Empty list if nothing has been resolved yet.
    """
    return list(_LAST_VERDICTS.get(provider, ()))


log = logging.getLogger(__name__)

# Hermes pattern: refresh 2 min before expiry
_REFRESH_SKEW_S = 120.0

# Type alias for managed token refresh functions.
# Signature: (profile) -> bool (True if token was updated)
ManagedRefreshFn = Callable[[AuthProfile], bool]


class ProfileRotator:
    """Selects the best available auth profile for a provider.

    Resolution order:
    1. Filter: available only (not disabled, not expired, not cooling down)
    2. Sort by type priority (oauth > token > api_key)
    3. Within same type: LRU (least recently used first)

    Managed token support:
    - Register refresh functions per managed_by label
    - Proactive refresh on resolve() if expiry within 120s
    - Auto-refresh on mark_failure() before applying cooldown
    """

    def __init__(self, store: ProfileStore) -> None:
        self._store = store
        self._refreshers: dict[str, ManagedRefreshFn] = {}

    def register_refresher(self, managed_by: str, fn: ManagedRefreshFn) -> None:
        """Register a refresh function for managed profiles.

        Args:
            managed_by: Label matching AuthProfile.managed_by (e.g. "codex-cli").
            fn: Callable(profile) -> bool. Re-reads token from external storage.
        """
        self._refreshers[managed_by] = fn

    def resolve(self, provider: str) -> AuthProfile | None:
        """Resolve the best available profile for a provider.

        v0.51.0 — Calls ``ProfileStore.evaluate_eligibility`` so every
        rejection emits a structured reason. The full verdict list is
        cached per-provider for ``credential_breadcrumb.format()`` and
        the ``/login`` dashboard to render.

        If the selected profile is managed and expires within 120s,
        proactively re-reads from external storage before returning.
        Returns None if no profiles are eligible.
        """
        verdicts = self._store.evaluate_eligibility(provider)
        _LAST_VERDICTS[provider] = verdicts

        eligible_profiles: list[AuthProfile] = []
        for verdict in verdicts:
            if verdict.eligible:
                profile = self._store.get(verdict.profile_name)
                if profile is not None:
                    eligible_profiles.append(profile)

        if not eligible_profiles:
            rejected = [v for v in verdicts if not v.eligible]
            if rejected:
                log.warning(
                    "No eligible profiles for provider=%s (evaluated %d, rejected %d): %s",
                    provider,
                    len(verdicts),
                    len(rejected),
                    "; ".join(f"{v.profile_name}={v.reason_code}({v.detail})" for v in rejected),
                )
            else:
                log.warning("No profiles registered for provider=%s", provider)
            return None

        # Sort: type priority first, then LRU
        eligible_profiles.sort(key=lambda p: p.sort_key())
        selected = eligible_profiles[0]

        # Proactive refresh: re-read if managed + expiring within skew
        if selected.managed_by and selected.expires_at > 0:
            remaining = selected.expires_at - time.time()
            if remaining < _REFRESH_SKEW_S:
                self._try_managed_refresh(selected, reason="proactive")

        log.debug(
            "Resolved profile=%s (type=%s) for provider=%s from %d candidates",
            selected.name,
            selected.credential_type.value,
            provider,
            len(eligible_profiles),
        )
        return selected

    def mark_used(self, profile: AuthProfile) -> None:
        """Mark a profile as just used (updates last_used timestamp)."""
        profile.last_used = time.time()

    def mark_success(self, profile: AuthProfile) -> None:
        """Mark a successful API call — reset error count."""
        profile.error_count = 0
        profile.cooldown_until = 0.0

    def mark_failure(self, profile: AuthProfile, *, is_auth_error: bool = False) -> None:
        """Mark a failed API call — increment errors, apply cooldown.

        For managed profiles with auth errors (401/403), attempts to re-read
        the token from external storage before applying cooldown. If the token
        changed, resets error count (Hermes 401 auto-refresh pattern).

        Args:
            profile: The profile that failed.
            is_auth_error: True if the error was an authentication failure (401/403).
        """
        # 401 auto-refresh for managed profiles
        if is_auth_error and profile.managed_by:
            refreshed = self._try_managed_refresh(profile, reason="401")
            if refreshed:
                # Token updated — reset errors, skip cooldown
                profile.error_count = 0
                profile.cooldown_until = 0.0
                log.info(
                    "Profile %s: 401 auto-refresh succeeded, errors reset",
                    profile.name,
                )
                return

        profile.error_count += 1
        cooldown_ms = calculate_cooldown_ms(profile.error_count)
        profile.cooldown_until = time.time() + cooldown_ms / 1000.0
        log.warning(
            "Profile %s failed (count=%d), cooldown=%dms",
            profile.name,
            profile.error_count,
            cooldown_ms,
        )

    def _try_managed_refresh(self, profile: AuthProfile, *, reason: str) -> bool:
        """Attempt to refresh a managed profile's token from external storage.

        Returns True if the token was actually updated.
        """
        refresher = self._refreshers.get(profile.managed_by)
        if refresher is None:
            log.debug(
                "No refresher for managed_by=%s (profile=%s)",
                profile.managed_by,
                profile.name,
            )
            return False
        try:
            updated = refresher(profile)
            if updated:
                log.info(
                    "Managed refresh (%s): %s token updated",
                    reason,
                    profile.name,
                )
            return updated
        except Exception:
            log.debug("Managed refresh failed for %s", profile.name, exc_info=True)
            return False

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

            entry: dict[str, Any] = {
                "name": p.name,
                "provider": p.provider,
                "type": p.credential_type.value,
                "display": p.masked_key,
                "status": status,
                "error_count": p.error_count,
            }
            if p.managed_by:
                entry["managed_by"] = p.managed_by
            if p.metadata:
                entry["metadata"] = p.metadata
            result.append(entry)
        return result


def calculate_cooldown_ms(error_count: int) -> int:
    """Calculate cooldown duration in ms using exponential backoff.

    OpenClaw formula: min(60min, 1min × 5^(n-1)) for n = capped at 4.
    Progression: 1min → 5min → 25min → 60min (max).
    """
    normalized = max(1, error_count)
    result: int = min(60 * 60 * 1000, 60 * 1000 * (5 ** min(normalized - 1, 3)))
    return result
