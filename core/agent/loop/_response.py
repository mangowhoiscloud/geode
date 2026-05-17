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
    from .agent_loop import AgenticLoop

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


def _record_usage(loop: AgenticLoop, response: Any) -> Any | None:
    """Record token usage and return the tracker for cost-budget hooks."""
    if not response or not getattr(response, "usage", None):
        return None
    from core.llm.token_tracker import get_tracker
    from core.ui.agentic_ui import render_tokens

    in_tok = int(getattr(response.usage, "input_tokens", 0) or 0)
    out_tok = int(getattr(response.usage, "output_tokens", 0) or 0)
    think_tok = int(getattr(response.usage, "thinking_tokens", 0) or 0)
    cache_create = int(getattr(response.usage, "cache_creation_tokens", 0) or 0)
    cache_read = int(getattr(response.usage, "cache_read_tokens", 0) or 0)
    tracker = get_tracker()
    usage = tracker.record(
        loop.model,
        in_tok,
        out_tok,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
        thinking_tokens=think_tok,
    )
    if not loop._quiet:
        render_tokens(loop.model, in_tok, out_tok, cost_usd=usage.cost_usd)
    log.info(
        "LLM call: model=%s in=%d out=%d think=%d cache_w=%d cache_r=%d cost=$%.4f",
        loop.model,
        in_tok,
        out_tok,
        think_tok,
        cache_create,
        cache_read,
        usage.cost_usd,
    )
    return tracker


def _cost_hook_payload(loop: AgenticLoop, tracker: Any) -> tuple[HookEvent, dict[str, Any]] | None:
    if not loop._hooks:
        return None

    from core.config import settings

    cost_limit = getattr(settings, "cost_limit_usd", 0.0)
    if cost_limit <= 0:
        return None
    total_cost = tracker.accumulator.total_cost_usd
    pct = total_cost / cost_limit
    if pct >= 1.0:
        return (
            HookEvent.COST_LIMIT_EXCEEDED,
            {"total_cost_usd": total_cost, "limit_usd": cost_limit},
        )
    if pct >= 0.8:
        return (
            HookEvent.COST_WARNING,
            {"total_cost_usd": total_cost, "limit_usd": cost_limit, "pct": pct},
        )
    return None


def track_usage(loop: AgenticLoop, response: Any) -> None:
    """Track token usage for cost monitoring.

    Defect A F-A2 (2026-05-11) — three hardenings:

    1. ``getattr(..., 0)`` fallback for every counter so a wrapper /
       mock with partial attributes no longer triggers an
       ``AttributeError`` that the broad ``except`` block silently
       swallows. The petri live (#1020) showed exactly this silent
       loss on the openai stack — completion was non-empty, response
       arrived, but every call was dropped here.
    2. Forward ``cache_creation_tokens`` / ``cache_read_tokens`` to
       ``tracker.record`` so prompt-cache usage is finally recorded
       per-call (the normalize layer started populating these in F-A2
       as well — see ``agentic_response.ResponseUsage``).
    3. Promote the swallowed exception path from ``log.debug`` to
       ``log.warning``. The failure was historically silent; making
       it warning-level surfaces future regressions without breaking
       the loop.
    """
    try:
        tracker = _record_usage(loop, response)
        if tracker is None:
            return

        # Hook: COST_WARNING / COST_LIMIT_EXCEEDED
        hook_payload = _cost_hook_payload(loop, tracker)
        if hook_payload is not None:
            event, data = hook_payload
            assert loop._hooks is not None
            loop._hooks.trigger(event, data)
    except Exception:
        log.warning("Failed to track usage", exc_info=True)


async def track_usage_async(loop: AgenticLoop, response: Any) -> None:
    """Async usage tracking path for ``AgenticLoop.arun``."""
    try:
        tracker = _record_usage(loop, response)
        if tracker is None:
            return
        hook_payload = _cost_hook_payload(loop, tracker)
        if hook_payload is not None:
            event, data = hook_payload
            assert loop._hooks is not None
            await loop._hooks.trigger_async(event, data)
    except Exception:
        log.warning("Failed to track usage", exc_info=True)


def update_tool_error_tracking(loop: AgenticLoop, tool_results: list[dict[str, Any]]) -> None:
    """Update tool error tracking. Delegates to ConvergenceDetector."""
    loop._convergence.update_tool_error_tracking(tool_results, loop._tool_processor.tool_log)


def check_convergence_break(loop: AgenticLoop) -> bool:
    """Check for stuck loop. Delegates to ConvergenceDetector."""
    return loop._convergence.check_convergence_break()
