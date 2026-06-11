"""Clarification-shaped responses for tool dispatch.

``_clarify`` builds the canonical ``clarification_needed`` dict that the
agent loop renders as a follow-up question; ``_safe_delegate`` translates
the standard ``KeyError`` / ``TypeError`` raised by missing required
kwargs into a ``_clarify`` call so a single missing parameter doesn't
crash the round-trip — the user just gets asked for it.

Renamed from ``_helpers.py`` (PR-CLEANUP-5, 2026-05-23) per the new
CLAUDE.md Naming CANNOT row: catch-all suffixes (``_helpers`` /
``_utils``) hide intent once any caller depends on the module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.tools.base import ToolContext


def _clarify(
    tool: str,
    missing: list[str],
    hint: str,
    **extra: Any,
) -> dict[str, Any]:
    """Standard clarification response for missing required params."""
    return {
        "error": f"{tool} requires: {', '.join(missing)}",
        "clarification_needed": True,
        "missing": missing,
        "hint": hint,
        **extra,
    }


async def _safe_delegate(
    tool_class: type,
    kwargs: dict[str, Any],
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    """Wrap delegated tool execution -- catch KeyError as clarification.

    PR-TOOL-EXEC-CONTEXT (2026-05-28) — when a non-None ``context`` is
    given, inject it as ``_tool_context=`` into the tool's ``aexecute``
    kwargs. Tools that consume LLM-identity (web_search and future
    LLM-backed tools) read ``kwargs.get("_tool_context")``; tools that do
    not care absorb the extra key through their ``**kwargs`` splat.

    PR-LOOP-POLLUTION-FIX (2026-06-12) — now a coroutine awaited on the
    session's event loop. The previous sync shape ran
    ``run_process_coroutine(aexecute(...))`` from a ``to_thread`` worker —
    one throwaway ``asyncio.Runner`` loop per tool call, which combined
    with shared SDK clients to poison httpx connection pools (instant
    APIConnectionError / eternal hang; see core/llm/loop_affinity.py).
    """
    try:
        tool = tool_class()
        aexecute = getattr(tool, "aexecute", None)
        if not callable(aexecute):
            raise TypeError(f"{tool_class.__name__} must implement aexecute()")
        if context is not None:
            kwargs["_tool_context"] = context
        result: dict[str, Any] = await aexecute(**kwargs)
        return result
    except (KeyError, TypeError) as exc:
        param = str(exc).strip("'\"")
        return _clarify(
            tool_class.__name__,
            [param],
            f"'{param}' 값을 알려주세요.",
        )
