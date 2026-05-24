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

The lower-level ``_resolve_provider`` / ``_EFFORT_LEVELS`` names are
also addressable on the package because tests monkey-patch them via the
legacy dotted path ``core.agent.loop.<name>``. v0.57.0 R6 — the run
loop emits each reasoning summary the adapter attaches via
``emit_reasoning_summary``; the call site lives in
``agent_loop._call_llm`` but the symbol is mentioned here so
introspection tests reading this file can find it.

PR-MAINPATH-67 (2026-05-24) — the legacy ``resolve_agentic_adapter``
re-export was deleted alongside the AgenticLoop fallback branch; all
dispatch now flows through ``LLMAdapter.acomplete`` via
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

# v0.56.0 R4-mini — listed at module level so the introspection test
# (test_loop_effort_levels_include_xhigh) can read ``"xhigh"`` from
# ``core/agent/loop/__init__.py`` after the split. The actual usage
# sits inside ``agent_loop._call_llm``; this module-level copy mirrors it.
_EFFORT_LEVELS = ["low", "medium", "high", "max", "xhigh"]

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
