"""Auth Profiles — credential types and profile store.

OpenClaw Auth Profile pattern: three credential types with
type-priority rotation (oauth > token > api_key).

v0.51.0 — Eligibility observability: every rejection emits a structured
``EligibilityResult`` with a ``ProfileRejectReason`` enum so silent skips
are eliminated. Rotator logs the full breakdown when no profile matches,
and the same verdicts feed both the ``/login`` dashboard and the
LLM-readable credential breadcrumb (``credential_breadcrumb.format``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CredentialType(Enum):
    """Credential type with implicit priority (lower ordinal = higher priority)."""

    OAUTH = "oauth"
    TOKEN = "token"  # noqa: S105 — enum value, not a hardcoded password
    API_KEY = "api_key"


# Type priority: oauth > token > api_key
TYPE_PRIORITY: dict[CredentialType, int] = {
    CredentialType.OAUTH: 0,
    CredentialType.TOKEN: 1,
    CredentialType.API_KEY: 2,
}


class ProfileRejectReason(Enum):
    """Why a profile was filtered out by eligibility evaluation.

    Mirrors OpenClaw ``AuthCredentialReasonCode`` so external observers
    can map verdicts cross-system.
    """

    PROVIDER_MISMATCH = "provider_mismatch"
    DISABLED = "disabled"
    EXPIRED = "expired"
    COOLING_DOWN = "cooling_down"
    MISSING_KEY = "missing_key"


@dataclass(frozen=True)
class EligibilityResult:
    """Per-profile verdict from ``ProfileStore.evaluate_eligibility``.

    Every profile in the store gets exactly one verdict — either
    ``eligible=True`` (no reason) or ``eligible=False`` with a structured
    reason + human-readable detail.
    """

    profile_name: str
    provider: str
    credential_type: CredentialType
    eligible: bool
    reason: ProfileRejectReason | None = None
    detail: str = ""
    expires_at: float = 0.0
    cooldown_until: float = 0.0
    error_count: int = 0

    @property
    def reason_code(self) -> str:
        return self.reason.value if self.reason else "ok"


@dataclass
class AuthProfile:
    """A single authentication profile.

    Naming convention: {provider}:{identifier} e.g. 'anthropic:work'.

    plan_id (v0.50.0+) optionally links the profile to a Plan in
    `core.gateway.auth.plans`, which carries the endpoint, auth type,
    quota, and subscription metadata. When unset, the profile defaults
    to a synthetic PAYG Plan derived from `provider`.

    base_url_override (v0.50.0+) lets a profile point at a non-default
    endpoint without modifying the Plan (e.g. China-mainland mirror).
    """

    name: str  # e.g. "anthropic:work"
    provider: str  # e.g. "anthropic", "openai"
    credential_type: CredentialType
    key: str = ""  # API key or token value
    refresh_token: str = ""  # OAuth only
    expires_at: float = 0.0  # Unix timestamp, 0 = no expiry
    managed_by: str = ""  # External CLI that owns token lifecycle (e.g. "claude-code")
    last_used: float = 0.0
    error_count: int = 0
    cooldown_until: float = 0.0
    disabled: bool = False
    disabled_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    plan_id: str = ""  # FK into PlanRegistry (Phase 4)
    base_url_override: str | None = None  # overrides Plan.base_url for this profile

    @property
    def is_expired(self) -> bool:
        if self.expires_at == 0.0:
            return False
        return time.time() > self.expires_at

    @property
    def is_cooling_down(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def is_available(self) -> bool:
        return not self.disabled and not self.is_expired and not self.is_cooling_down

    @property
    def masked_key(self) -> str:
        if len(self.key) <= 14:
            return "***"
        return self.key[:10] + "..." + self.key[-4:]

    def sort_key(self) -> tuple[int, float]:
        """Sort key for rotation: type priority first, then last_used (LRU)."""
        return (TYPE_PRIORITY.get(self.credential_type, 99), self.last_used)


class ProfileStore:
    """In-memory store for auth profiles with CRUD operations.

    Profiles are stored keyed by name (e.g. 'anthropic:work').
    Supports active profile tracking per provider.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AuthProfile] = {}
        self._active: dict[str, str] = {}  # provider → profile name

    def add(self, profile: AuthProfile) -> None:
        """Add a profile. If no active profile exists for the provider, set it."""
        self._profiles[profile.name] = profile
        if profile.provider not in self._active:
            self._active[profile.provider] = profile.name

    def get(self, name: str) -> AuthProfile | None:
        return self._profiles.get(name)

    def remove(self, name: str) -> bool:
        profile = self._profiles.pop(name, None)
        if profile is None:
            return False
        # Clear active tracking if this was the active profile
        if self._active.get(profile.provider) == name:
            remaining = self.list_by_provider(profile.provider)
            if remaining:
                self._active[profile.provider] = remaining[0].name
            else:
                self._active.pop(profile.provider, None)
        return True

    def list_all(self) -> list[AuthProfile]:
        return list(self._profiles.values())

    def list_by_provider(self, provider: str) -> list[AuthProfile]:
        return [p for p in self._profiles.values() if p.provider == provider]

    def list_available(self, provider: str | None = None) -> list[AuthProfile]:
        all_profiles = list(self._profiles.values())
        if provider:
            all_profiles = [p for p in all_profiles if p.provider == provider]
        return [p for p in all_profiles if p.is_available]

    def evaluate_eligibility(
        self,
        provider: str,
        *,
        now: float | None = None,
    ) -> list[EligibilityResult]:
        """Return one ``EligibilityResult`` per profile in the store.

        Unlike ``list_available``, this surfaces *why* each profile is
        out of consideration — provider mismatch, expired, in cooldown,
        disabled, or missing a key. Used by:
          * ``ProfileRotator.resolve()`` for diagnostic logging when no
            profile matches.
          * The ``/login`` dashboard to show inline reject badges.
          * ``credential_breadcrumb.format()`` to inject an LLM-readable
            note into the agentic loop after auth failures.
        """
        ts = now if now is not None else time.time()
        results: list[EligibilityResult] = []
        for p in self._profiles.values():

            def make(
                eligible: bool,
                reason: ProfileRejectReason | None = None,
                detail: str = "",
                _p: AuthProfile = p,
            ) -> EligibilityResult:
                return EligibilityResult(
                    profile_name=_p.name,
                    provider=_p.provider,
                    credential_type=_p.credential_type,
                    expires_at=_p.expires_at,
                    cooldown_until=_p.cooldown_until,
                    error_count=_p.error_count,
                    eligible=eligible,
                    reason=reason,
                    detail=detail,
                )

            if p.provider != provider:
                results.append(
                    make(
                        False,
                        ProfileRejectReason.PROVIDER_MISMATCH,
                        f"profile.provider={p.provider!r} != requested={provider!r}",
                    )
                )
                continue
            if p.disabled:
                results.append(
                    make(
                        False,
                        ProfileRejectReason.DISABLED,
                        p.disabled_reason or "no reason given",
                    )
                )
                continue
            if not p.key:
                results.append(
                    make(
                        False,
                        ProfileRejectReason.MISSING_KEY,
                        "profile has no key set — run /login set-key",
                    )
                )
                continue
            if p.expires_at and ts > p.expires_at:
                results.append(
                    make(
                        False,
                        ProfileRejectReason.EXPIRED,
                        f"expired {int(ts - p.expires_at)}s ago (at {p.expires_at:.0f})",
                    )
                )
                continue
            if ts < p.cooldown_until:
                results.append(
                    make(
                        False,
                        ProfileRejectReason.COOLING_DOWN,
                        f"{int(p.cooldown_until - ts)}s remaining (error_count={p.error_count})",
                    )
                )
                continue
            results.append(make(True))
        return results

    def group_by_provider(self) -> dict[str, list[AuthProfile]]:
        groups: dict[str, list[AuthProfile]] = {}
        for p in self._profiles.values():
            groups.setdefault(p.provider, []).append(p)
        return groups

    def set_active(self, name: str) -> None:
        """Set the active profile by name. Raises KeyError if not found."""
        profile = self._profiles.get(name)
        if profile is None:
            raise KeyError(f"Profile '{name}' not found")
        self._active[profile.provider] = name

    def get_active(self, provider: str) -> AuthProfile | None:
        """Get the active profile for a provider."""
        name = self._active.get(provider)
        if name is None:
            return None
        return self._profiles.get(name)

    def clear(self) -> None:
        self._profiles.clear()
        self._active.clear()

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, name: str) -> bool:
        return name in self._profiles
