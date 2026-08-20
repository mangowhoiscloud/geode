"""Claude OAuth (subscription quota) adapter — manifest-bound facade.

CSA-3 (2026-05-22) — flipped to route through the paperclip-style
:mod:`geode_product.petri_audit.claude_cli_provider` (``claude-cli``
``ModelAPI``, subprocess-based). The retired raw-SDK path empirically hit
100% 429 enforcement
on Claude Max OAuth tokens (verified 2026-05-22 trace-68931.log:
27/27 requests rejected, retry-after 770 sec) while the CLI
subprocess path consumes full subscription quota without throttling.

CSA-1 + CSA-2 together close the auditor + judge tool surface on the
subprocess path — text-only judge via CSA-1, tool_use auditor via
the CSA-2 MCP bridge. CSA-3 is the routing flip that makes
``source="claude-cli"`` in operator config actually pick the new
provider.

Claude OAuth metadata and availability probes are kernel-owned because
credential resolution is independent of the Inspect provider.
"""

from __future__ import annotations

from typing import Any

from core.auth.claude_cli_oauth import (
    get_claude_oauth_metadata,
    is_claude_oauth_available,
)

from geode_product.petri_audit.claude_cli_provider import (
    register as _register_claude_cli,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "claude-cli"
"""Historical artifacts may contain the retired ``claude-code`` prefix. The CSA-1 provider
registers ``@modelapi(name="claude-cli")`` so the manifest +
``to_inspect_model`` router both land on the subprocess path."""


def register() -> None:
    """Register the ``claude-cli`` ``ModelAPI`` with inspect_ai.

    The subprocess path is the canonical Claude subscription route.
    """
    _register_claude_cli()


def is_available() -> bool:
    """True when the Claude OAuth token resolves (auth.toml or keychain)."""
    return is_claude_oauth_available()


def metadata() -> dict[str, Any] | None:
    """Return picker-friendly subscription metadata.

    Shape — ``{subscription_type, rate_limit_tier, scopes, expires_at,
    source}``. ``None`` when no OAuth token is available. See
    :func:`core.auth.claude_cli_oauth.get_claude_oauth_metadata`
    for the field-level contract.
    """
    return get_claude_oauth_metadata()
