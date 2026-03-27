"""Context overflow action handler — decides compression strategy via Hook.

This is the first Hook handler that returns a recommendation dict to the caller,
enabling extensible compression strategy selection in AgenticLoop._check_context_overflow.
"""

from __future__ import annotations

from typing import Any

from core.hooks.system import HookEvent


def make_context_action_handler() -> tuple[str, Any]:
    """Return a hook handler that decides compression strategy based on context metrics.

    Returns:
        Tuple of (handler_name, handler_function).
        The handler returns a dict with ``strategy`` and optional ``keep_recent`` keys.
    """

    def _decide_strategy(event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
        from core.config import settings

        metrics = data.get("metrics", {})
        context_window: int = metrics.get("context_window", 1_000_000)
        usage_pct: float = metrics.get("usage_pct", 0)

        if context_window < 200_000:
            # Small-context model: aggressive prune
            return {"strategy": "prune", "keep_recent": min(settings.compact_keep_recent, 5)}
        elif usage_pct >= 95:
            # Critical threshold: standard prune from settings
            return {"strategy": "prune", "keep_recent": settings.compact_keep_recent}
        else:
            return {"strategy": "none"}

    return "context_action_handler", _decide_strategy
