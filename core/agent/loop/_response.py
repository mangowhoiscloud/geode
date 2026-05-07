"""Response handling: text/content extraction, usage tracking, tool refresh.

Extracted from the monolithic ``core/agent/loop.py`` (Tier 3 #7). Each
function takes the ``AgenticLoop`` as the first parameter (``loop``)
and reads/writes its state. Convergence/error-tracking helpers live
here too because they share the response-handling lifecycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.hooks import HookEvent

from ._helpers import get_agentic_tools

if TYPE_CHECKING:
    from .loop import AgenticLoop

log = logging.getLogger(__name__)


def refresh_tools(loop: AgenticLoop) -> int:
    """Reload MCP tools into the tool list without reconstructing the loop.

    Called after install_mcp_server to make new tools available immediately.
    Rebuilds the unified tool list with deferred loading applied.
    Returns number of newly added tools.
    """
    if loop._mcp_manager is None:
        return 0
    old_count = len(loop._tools)
    mcp_tool_list = loop._mcp_manager.get_all_tools()
    loop._tools = get_agentic_tools(loop._tool_registry, mcp_tools=mcp_tool_list)
    new_count = len(loop._tools)
    return max(0, new_count - old_count)


def extract_text(loop: AgenticLoop, response: Any) -> str:
    """Extract text content from response blocks."""
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def serialize_content(loop: AgenticLoop, content: list[Any]) -> list[dict[str, Any]]:
    """Serialize content blocks to plain dicts for message history."""
    serialized: list[dict[str, Any]] = []
    for block in content:
        if block.type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            serialized.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return serialized


def track_usage(loop: AgenticLoop, response: Any) -> None:
    """Track token usage for cost monitoring."""
    if not response.usage:
        return
    try:
        from core.llm.token_tracker import get_tracker
        from core.ui.agentic_ui import render_tokens

        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        think_tok = getattr(response.usage, "thinking_tokens", 0) or 0
        tracker = get_tracker()
        usage = tracker.record(
            loop.model,
            in_tok,
            out_tok,
            thinking_tokens=think_tok,
        )
        if not loop._quiet:
            render_tokens(loop.model, in_tok, out_tok, cost_usd=usage.cost_usd)
        log.info(
            "LLM call: model=%s in=%d out=%d think=%d cost=$%.4f",
            loop.model,
            in_tok,
            out_tok,
            think_tok,
            usage.cost_usd,
        )

        # Hook: COST_WARNING / COST_LIMIT_EXCEEDED
        if loop._hooks:
            from core.config import settings

            cost_limit = getattr(settings, "cost_limit_usd", 0.0)
            if cost_limit > 0:
                total_cost = tracker.accumulator.total_cost_usd
                pct = total_cost / cost_limit
                if pct >= 1.0:
                    loop._hooks.trigger(
                        HookEvent.COST_LIMIT_EXCEEDED,
                        {"total_cost_usd": total_cost, "limit_usd": cost_limit},
                    )
                elif pct >= 0.8:
                    loop._hooks.trigger(
                        HookEvent.COST_WARNING,
                        {"total_cost_usd": total_cost, "limit_usd": cost_limit, "pct": pct},
                    )
    except Exception:
        log.debug("Failed to track usage", exc_info=True)


def update_tool_error_tracking(loop: AgenticLoop, tool_results: list[dict[str, Any]]) -> None:
    """Update tool error tracking. Delegates to ConvergenceDetector."""
    loop._convergence.update_tool_error_tracking(tool_results, loop._tool_processor.tool_log)


def check_convergence_break(loop: AgenticLoop) -> bool:
    """Check for stuck loop. Delegates to ConvergenceDetector."""
    return loop._convergence.check_convergence_break()
