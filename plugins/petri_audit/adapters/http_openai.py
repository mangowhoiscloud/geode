"""HTTP API-key adapter for OpenAI — stock inspect_ai pathway.

Maps the manifest binding ``[petri.adapter.openai.api_key]`` to
inspect_ai's native ``openai/<model>`` provider. Sibling of
:mod:`plugins.petri_audit.adapters.http_anthropic`.
"""

from __future__ import annotations

import os

__all__ = ["INSPECT_PREFIX", "is_available", "register"]

INSPECT_PREFIX = "openai"


def register() -> None:
    """No-op — inspect_ai registers the stock ``OpenAIAPI`` itself."""
    return None


def is_available() -> bool:
    """True when ``OPENAI_API_KEY`` is set in the environment."""
    return bool(os.environ.get("OPENAI_API_KEY"))
