"""OpenAI Codex OAuth (ChatGPT subscription quota) adapter — manifest-bound facade.

CSA-3 (2026-05-22) — flipped to register the paperclip-style
:mod:`plugins.petri_audit.codex_cli_provider` (``codex-cli``
``ModelAPI``, subprocess-based, CSA-1b) instead of
:mod:`plugins.petri_audit.codex_provider` (``openai-codex`` raw-SDK
OAuth). Sibling of :mod:`plugins.petri_audit.adapters.claude_cli_backend`.

Codex OAuth metadata + availability probes still live on
``codex_provider`` because the keychain resolution is independent of
which ``ModelAPI`` runs the inference.
"""

from __future__ import annotations

from typing import Any

from plugins.petri_audit.codex_cli_provider import (
    register as _register_codex_cli,
)
from plugins.petri_audit.codex_provider import (
    get_codex_oauth_metadata,
    is_codex_oauth_available,
)

__all__ = ["INSPECT_PREFIX", "is_available", "metadata", "register"]

INSPECT_PREFIX = "codex-cli"
"""CSA-3 flip — was previously ``openai-codex``. The CSA-1b provider
registers ``@modelapi(name="codex-cli")`` so the manifest +
``to_inspect_model`` router both land on the subprocess path."""


def register() -> None:
    """Register the ``codex-cli`` ``ModelAPI`` with inspect_ai.

    CSA-3 flip — was previously ``openai-codex``. The subprocess
    path is now the canonical Codex OAuth route.
    """
    _register_codex_cli()


def is_available() -> bool:
    """True when the Codex OAuth token resolves."""
    return is_codex_oauth_available()


def metadata() -> dict[str, Any] | None:
    """Return picker-friendly subscription metadata."""
    return get_codex_oauth_metadata()
