"""Agentic adapter registry — P1 Gateway pattern.

Maps provider names to adapter classes. Dynamic import for lazy loading.
Includes cross-provider fallback map for multi-provider escalation.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from core.config import ANTHROPIC_PRIMARY, OPENAI_PRIMARY

if TYPE_CHECKING:
    from core.llm.router import AgenticLLMPort

log = logging.getLogger(__name__)

# Provider -> "module_path:ClassName"
_ADAPTER_MAP: dict[str, str] = {
    "anthropic": "core.agent.adapters.claude_agentic_adapter:ClaudeAgenticAdapter",
    "openai": "core.agent.adapters.openai_agentic_adapter:OpenAIAgenticAdapter",
    "glm": "core.agent.adapters.glm_agentic_adapter:GlmAgenticAdapter",
}

# Cross-provider fallback: when a provider's chain is exhausted, try these.
# GLM -> OpenAI -> Anthropic (Bug #6 fix: add Anthropic path for GLM)
CROSS_PROVIDER_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "anthropic": [("openai", OPENAI_PRIMARY)],
    "openai": [("anthropic", ANTHROPIC_PRIMARY)],
    "glm": [("openai", OPENAI_PRIMARY), ("anthropic", ANTHROPIC_PRIMARY)],
}


def resolve_agentic_adapter(provider: str) -> AgenticLLMPort:
    """Create an agentic adapter for the given provider.

    Uses dynamic import to avoid loading unused providers.
    """
    entry = _ADAPTER_MAP.get(provider)
    if entry is None:
        # Unknown provider -> default to OpenAI-compatible
        log.warning("Unknown provider '%s', defaulting to openai adapter", provider)
        entry = _ADAPTER_MAP["openai"]

    module_path, class_name = entry.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    adapter: AgenticLLMPort = cls()
    return adapter
