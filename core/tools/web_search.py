"""WebSearchTool — signal-flavoured web search tool (``web_search`` name).

PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28) — formerly carried its own
3-provider direct-SDK fallback chain identical to ``GeneralWebSearchTool``.
Now both tools delegate to :func:`core.llm.adapters.dispatch.web_search_via_adapters`
so the active model route drives adapter selection uniformly.

The only meaningful difference between this tool and
``GeneralWebSearchTool`` is the description (signal-pipeline framing vs
general-purpose) and the registered tool name (``web_search`` vs
``general_web_search``). Both are kept until callers consolidate on one
name.
"""

from __future__ import annotations

from typing import Any

_WEB_SEARCH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query (e.g., 'AI release notes 2026').",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5).",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


class WebSearchTool:
    """Signal-flavoured web search tool — uses the adapter registry chain."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for real-time information. Useful for finding "
            "recent news, community discussions, source material, and market "
            "signals."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _WEB_SEARCH_PARAMETERS

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.web_tools import _execute_web_search

        return await _execute_web_search(kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(**kwargs))


__all__ = ["WebSearchTool"]
