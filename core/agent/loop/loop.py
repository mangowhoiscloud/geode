"""Backward-compatible import shim for the AgenticLoop implementation.

The canonical implementation lives in :mod:`core.agent.loop.agent_loop`.
Keep this module so existing imports such as ``core.agent.loop.loop`` and
``from core.agent.loop import loop`` continue to work while callers migrate.
"""

from __future__ import annotations

from .agent_loop import (
    AGENTIC_TOOLS,
    MAX_TOOL_RESULT_TOKENS,
    TOOL_LAZY_LOAD_THRESHOLD,
    AgenticLoop,
    AgenticResult,
    _context_exhausted_message,
    _ContextExhaustedError,
    get_agentic_tools,
)

__all__ = [
    "AGENTIC_TOOLS",
    "MAX_TOOL_RESULT_TOKENS",
    "TOOL_LAZY_LOAD_THRESHOLD",
    "AgenticLoop",
    "AgenticResult",
    "_ContextExhaustedError",
    "_context_exhausted_message",
    "get_agentic_tools",
]
