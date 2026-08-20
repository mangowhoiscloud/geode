"""OpenAI OAuth (ChatGPT subscription) adapter — manifest-bound facade."""

from __future__ import annotations

from typing import Any

from geode_product.petri_audit.codex_provider import (
    get_codex_oauth_metadata,
    is_codex_oauth_available,
)
from geode_product.petri_audit.codex_provider import (
    register as _register_codex_oauth,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "openai-codex"


def register() -> None:
    """Register the direct OAuth ``ModelAPI`` with inspect_ai."""
    _register_codex_oauth()


def is_available() -> bool:
    """True when the Codex OAuth token resolves."""
    return is_codex_oauth_available()


def metadata() -> dict[str, Any] | None:
    """Return picker-friendly subscription metadata."""
    return get_codex_oauth_metadata()
