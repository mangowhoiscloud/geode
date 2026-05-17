"""Claude OAuth (subscription quota) adapter — manifest-bound facade.

Maps the manifest binding ``[petri.adapter.anthropic.claude-cli]`` to
the existing :mod:`plugins.petri_audit.claude_code_provider`. The
provider already implements the inspect_ai ``claude-code`` ``ModelAPI``
subclass (OAuth token resolved from the local ``claude`` CLI keychain
+ GEODE auth.toml fallback); this module is a thin re-export so the
adapter registry has a stable import target and so a future P1-G
refactor can collapse the call sites onto the manifest contract
without re-shuffling exports.

The original :mod:`plugins.petri_audit.claude_code_provider` stays the
authoritative implementation for now — P1-G will migrate the routing
in :mod:`plugins.petri_audit.models.to_inspect_model` onto the
manifest, at which point we can decide whether to fold the provider
into this file or keep the indirection. Either way the public surface
documented here is the long-term contract.
"""

from __future__ import annotations

from typing import Any

from plugins.petri_audit.claude_code_provider import (
    get_claude_oauth_metadata,
    is_claude_oauth_available,
)
from plugins.petri_audit.claude_code_provider import (
    register as _register_claude_code,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "claude-code"


def register() -> None:
    """Register the ``claude-code`` ``ModelAPI`` with inspect_ai."""
    _register_claude_code()


def is_available() -> bool:
    """True when the Claude OAuth token resolves (auth.toml or keychain)."""
    return is_claude_oauth_available()


def metadata() -> dict[str, Any] | None:
    """Return picker-friendly subscription metadata.

    Shape — ``{subscription_type, rate_limit_tier, scopes, expires_at,
    source}``. ``None`` when no OAuth token is available. See
    :func:`plugins.petri_audit.claude_code_provider.get_claude_oauth_metadata`
    for the field-level contract.
    """
    return get_claude_oauth_metadata()
