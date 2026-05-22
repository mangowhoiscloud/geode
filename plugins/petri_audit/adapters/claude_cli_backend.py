"""Claude OAuth (subscription quota) adapter — manifest-bound facade.

CSA-3 (2026-05-22) — flipped to route through the paperclip-style
:mod:`plugins.petri_audit.claude_cli_provider` (``claude-cli``
``ModelAPI``, subprocess-based) instead of the raw-SDK
:mod:`plugins.petri_audit.claude_code_provider` (``claude-code``
``ModelAPI``). The raw-SDK path empirically hits 100% 429 enforcement
on Claude Max OAuth tokens (verified 2026-05-22 trace-68931.log:
27/27 requests rejected, retry-after 770 sec) while the CLI
subprocess path consumes full subscription quota without throttling.

CSA-1 + CSA-2 together close the auditor + judge tool surface on the
subprocess path — text-only judge via CSA-1, tool_use auditor via
the CSA-2 MCP bridge. CSA-3 is the routing flip that makes
``source="claude-cli"`` in operator config actually pick the new
provider.

Claude OAuth metadata + availability probes still live on
``claude_code_provider`` because the auth.toml / keychain resolution
is independent of which inspect_ai ``ModelAPI`` runs the inference.
We re-export those helpers so the adapter registry's
``is_available`` / ``metadata`` calls keep working.
"""

from __future__ import annotations

from typing import Any

from plugins.petri_audit.claude_cli_provider import (
    register as _register_claude_cli,
)
from plugins.petri_audit.claude_code_provider import (
    get_claude_oauth_metadata,
    is_claude_oauth_available,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "claude-cli"
"""CSA-3 flip — was previously ``claude-code``. The CSA-1 provider
registers ``@modelapi(name="claude-cli")`` so the manifest +
``to_inspect_model`` router both land on the subprocess path."""


def register() -> None:
    """Register the ``claude-cli`` ``ModelAPI`` with inspect_ai.

    CSA-3 flip — was previously ``claude-code``. The subprocess path
    is now the canonical Claude OAuth route.
    """
    _register_claude_cli()


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
