"""Auth Profiles — credential types and profile store.

OpenClaw Auth Profile pattern: three credential types with
type-priority rotation (oauth > token > api_key).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CredentialType(Enum):
    """Credential type with implicit priority (lower ordinal = higher priority)."""

    OAUTH = "oauth"
    TOKEN = "token"
    API_KEY = "api_key"


# Type priority: oauth > token > api_key
TYPE_PRIORITY: dict[CredentialType, int] = {
    CredentialType.OAUTH: 0,
    CredentialType.TOKEN: 1,
    CredentialType.API_KEY: 2,
}


@dataclass
class AuthProfile:
    """A single authentication profile.

    Naming convention: {provider}:{identifier} e.g. 'anthropic:work'.
    """

    name: str  # e.g. "anthropic:work"
    provider: str  # e.g. "anthropic", "openai"
    credential_type: CredentialType
    key: str = ""  # API key or token value
    refresh_token: str = ""  # OAuth only
    expires_at: float = 0.0  # Unix timestamp, 0 = no expiry
    last_used: float = 0.0
    error_count: int = 0
    cooldown_until: float = 0.0
    disabled: bool = False
    disabled_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

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
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AuthProfile] = {}

    def add(self, profile: AuthProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, name: str) -> AuthProfile | None:
        return self._profiles.get(name)

    def remove(self, name: str) -> bool:
        return self._profiles.pop(name, None) is not None

    def list_all(self) -> list[AuthProfile]:
        return list(self._profiles.values())

    def list_by_provider(self, provider: str) -> list[AuthProfile]:
        return [p for p in self._profiles.values() if p.provider == provider]

    def list_available(self, provider: str | None = None) -> list[AuthProfile]:
        all_profiles = list(self._profiles.values())
        if provider:
            all_profiles = [p for p in all_profiles if p.provider == provider]
        return [p for p in all_profiles if p.is_available]

    def group_by_provider(self) -> dict[str, list[AuthProfile]]:
        groups: dict[str, list[AuthProfile]] = {}
        for p in self._profiles.values():
            groups.setdefault(p.provider, []).append(p)
        return groups

    def clear(self) -> None:
        self._profiles.clear()

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, name: str) -> bool:
        return name in self._profiles
