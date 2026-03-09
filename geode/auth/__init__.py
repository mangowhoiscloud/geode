"""Auth Profile System — multi-profile credential management.

OpenClaw-inspired: type priority rotation + cooldown + failover.
"""

from geode.auth.cooldown import CooldownEntry, CooldownTracker
from geode.auth.profiles import (
    TYPE_PRIORITY,
    AuthProfile,
    CredentialType,
    ProfileStore,
)
from geode.auth.rotation import ProfileRotator, calculate_cooldown_ms

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
