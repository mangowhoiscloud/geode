"""OpenAI Codex OAuth (ChatGPT Plus quota) adapter — manifest-bound facade.

Maps the manifest binding ``[petri.adapter.openai.openai-codex]`` to
the existing :mod:`plugins.petri_audit.codex_provider`. Sibling of
:mod:`plugins.petri_audit.adapters.claude_cli_backend` — re-export
only so the adapter registry has a stable import target.
"""

from __future__ import annotations

from typing import Any

from plugins.petri_audit.codex_provider import (
    get_codex_oauth_metadata,
    is_codex_oauth_available,
)
from plugins.petri_audit.codex_provider import (
    register as _register_codex,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "openai-codex"


def register() -> None:
    """Register the ``openai-codex`` ``ModelAPI`` with inspect_ai."""
    _register_codex()


def is_available() -> bool:
    """True when the Codex OAuth token resolves."""
    return is_codex_oauth_available()


def metadata() -> dict[str, Any] | None:
    """Return picker-friendly subscription metadata."""
    return get_codex_oauth_metadata()
