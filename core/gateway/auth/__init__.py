"""Auth Profile System — multi-profile credential management.

OpenClaw-inspired: type priority rotation + cooldown + failover.
"""

from core.gateway.auth.cooldown import CooldownEntry, CooldownTracker
from core.gateway.auth.profiles import (
    TYPE_PRIORITY,
    AuthProfile,
    CredentialType,
    ProfileStore,
)
from core.gateway.auth.rotation import ProfileRotator, calculate_cooldown_ms

__all__ = [
    "TYPE_PRIORITY",
    "AuthProfile",
    "CooldownEntry",
    "CooldownTracker",
    "CredentialType",
    "ProfileRotator",
    "ProfileStore",
    "calculate_cooldown_ms",
]
