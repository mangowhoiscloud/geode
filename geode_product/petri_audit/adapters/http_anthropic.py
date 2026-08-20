"""HTTP API-key adapter for Anthropic — stock inspect_ai pathway.

Maps the manifest binding ``[petri.adapter.anthropic.api_key]`` to
inspect_ai's native ``anthropic/<model>`` provider. No subclass is
needed because inspect_ai already speaks the Anthropic Messages API
when ``ANTHROPIC_API_KEY`` is present; this module exists so the
adapter registry has a concrete import target + a uniform readiness
probe.

Contract surface:

- :func:`register` is a no-op (stock provider auto-registers).
- :func:`is_available` checks ``ANTHROPIC_API_KEY`` env presence.
- :data:`INSPECT_PREFIX` mirrors the manifest entry so callers can
  build ``f"{INSPECT_PREFIX}/{model}"`` ids without re-parsing the TOML.
"""

from __future__ import annotations

import os

__all__ = ["INSPECT_PREFIX", "is_available", "register"]

INSPECT_PREFIX = "anthropic"


def register() -> None:
    """No-op — inspect_ai registers the stock ``AnthropicAPI`` itself."""
    return None


def is_available() -> bool:
    """True when ``ANTHROPIC_API_KEY`` is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
