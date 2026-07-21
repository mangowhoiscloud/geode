"""Context-local audit activation shared by core runtime boundaries.

The Petri plugin owns audit-mode configuration, but core surfaces such as
provider tool injection and prompt assembly must agree on whether the current
task is an unattended audit. A lightweight top-level module avoids importing
the audit reporting package on the provider hot path. A ContextVar carries
config-file activation without importing ``plugins`` into ``core``; the
inherited environment variable remains the fallback for subprocess entry
points.
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token

AUDIT_MODE_ENV_VAR = "GEODE_AUDIT_UNRESTRICTED"
_AUDIT_MODE_TRUTHY = frozenset({"1", "true", "yes"})
_runtime_audit_active: ContextVar[bool | None] = ContextVar(
    "geode_runtime_audit_active",
    default=None,
)


def runtime_audit_active() -> bool:
    """Return whether the current task is running under unrestricted audit."""
    override = _runtime_audit_active.get()
    if override is not None:
        return override
    raw = os.environ.get(AUDIT_MODE_ENV_VAR, "").strip().lower()
    return raw in _AUDIT_MODE_TRUTHY


def set_runtime_audit_active(active: bool | None) -> Token[bool | None]:
    """Set the audit signal for the current context and return its reset token."""
    return _runtime_audit_active.set(active)


def reset_runtime_audit_active(token: Token[bool | None]) -> None:
    """Restore the audit signal previously replaced by ``set``."""
    _runtime_audit_active.reset(token)
