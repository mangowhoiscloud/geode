"""AgenticLoop package.

Backward-compatible re-exports preserve the public surface that
external callers rely on::

    from core.agent.loop import (
        AGENTIC_TOOLS,
        AgenticLoop,
        AgenticResult,
        _ContextExhaustedError,
        get_agentic_tools,
    )

The lower-level ``_resolve_provider`` name is also addressable on the
package because tests monkey-patch it via the legacy dotted path
``core.agent.loop._resolve_provider``.

All dispatch flows through ``LLMAdapter.acomplete`` via
``core.llm.adapters.resolve_for``.
"""

from __future__ import annotations

# Re-exports of names that monkeypatch / inspection tests target on the
# package — keep them addressable at ``core.agent.loop.<name>`` so that
# ``monkeypatch.setattr("core.agent.loop._resolve_provider", ...)`` and
# similar patches reach the call sites in ``_model_switching``. The
# split-into-package refactor preserves this surface.
from core.config import _resolve_provider as _resolve_provider

from ._tool_factory import AGENTIC_TOOLS, MAX_TOOL_RESULT_TOKENS, get_agentic_tools
from .agent_loop import AgenticLoop
from .models import AgenticResult, _context_exhausted_message, _ContextExhaustedError

__all__ = [
    "AGENTIC_TOOLS",
    "MAX_TOOL_RESULT_TOKENS",
    "AgenticLoop",
    "AgenticResult",
    "_ContextExhaustedError",
    "_context_exhausted_message",
    "_resolve_provider",
    "get_agentic_tools",
]
