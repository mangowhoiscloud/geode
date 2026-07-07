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

import logging
from typing import Any

log = logging.getLogger(__name__)


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
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)
        # PR-TOOL-EXEC-CONTEXT (2026-05-28) — consume the loop's LLM
        # identity so dispatch prefers the same (provider, source) the
        # orchestration loop is already using instead of re-resolving via
        # ``infer_source``. Missing context (tool called outside an
        # AgenticLoop) → empty strings → dispatch falls back to its
        # configured provider order.
        ctx = kwargs.get("_tool_context")
        prefer_provider = getattr(ctx, "provider", "") or None
        prefer_source = getattr(ctx, "source", "") or None
        # PR-WEB-SEARCH-MODEL-HINT (2026-06-12) — see GeneralWebSearchTool.
        session_model = getattr(ctx, "model", "") or ""
        from core.llm.adapters.dispatch import (
            AdapterDispatchError,
            AdapterUnavailableError,
            web_search_via_adapters,
        )
        from core.llm.errors import BillingError
        from core.tools.base import tool_error

        try:
            result = await web_search_via_adapters(
                query,
                max_results=max_results,
                prefer_provider=prefer_provider,
                prefer_source=prefer_source,
                model=session_model,
            )
        except BillingError as exc:
            return tool_error(
                str(exc),
                error_type="permission",
                recoverable=False,
                hint=(
                    "Top up the exhausted credential, or switch source via "
                    "/login source <subscription|payg|cli>. No automatic fallback."
                ),
                context={"query": query, "provider": exc.provider},
            )
        except AdapterUnavailableError as exc:
            return tool_error(
                str(exc),
                error_type="dependency",
                recoverable=False,
                hint=(
                    "Your current source has no web_search-capable adapter. "
                    "Run /adapters to list available sources and /login source "
                    "<subscription|payg|cli> to switch explicitly."
                ),
                context={"query": query},
            )
        except AdapterDispatchError as exc:
            return tool_error(
                str(exc),
                error_type="connection",
                recoverable=True,
                hint=(
                    "Retry, rephrase the query, or check adapter availability via "
                    "/adapters. No automatic fallback — this is the single attempt result."
                ),
                context={"query": query},
            )
        return {
            "result": {
                "query": result.query,
                "search_results": result.text,
                "source": result.adapter_name,
                "source_urls": list(result.source_urls),
                # PR-DISPATCH-OBS-EXT (2026-05-28) — see GeneralWebSearchTool
                "adapter_provider": result.adapter_provider,
                "adapter_source": result.adapter_source,
            }
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(**kwargs))


__all__ = ["WebSearchTool"]
