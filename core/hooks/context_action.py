"""Context overflow action handler — decides compression strategy via Hook.

Provider-aware strategy selection:
- Anthropic: server-side compaction (compact_20260112) handles everything.
  Client only intervenes at 95% as emergency safety net.
- OpenAI/GLM: no server-side compaction. Client triggers LLM-based compaction
  at 80% and emergency prune at 95%.
"""

from __future__ import annotations

from typing import Any

from core.hooks.system import HookEvent


def make_context_action_handler() -> tuple[str, Any]:
    """Return a hook handler that decides compression strategy based on context metrics.

    Returns:
        Tuple of (handler_name, handler_function).
        The handler returns a dict with ``strategy`` and optional ``keep_recent`` keys.
        Strategies: "none" | "compact" | "prune"
    """

    def _decide_strategy(event: HookEvent, data: dict[str, Any]) -> dict[str, Any]:
        from core.config import settings

        metrics = data.get("metrics", {})
        context_window: int = metrics.get("context_window", 1_000_000)
        usage_pct: float = metrics.get("usage_pct", 0)
        provider: str = data.get("provider", "anthropic")

        # Anthropic: server-side compaction + clear_tool_uses handle 80-95%.
        # Client only intervenes at 95% as emergency safety net.
        if provider == "anthropic":
            if usage_pct >= 95:
                return {"strategy": "prune", "keep_recent": settings.compact_keep_recent}
            return {"strategy": "none"}

        # Non-Anthropic (OpenAI, GLM): no server-side compaction.
        # Small-context models get aggressive treatment.
        if context_window < 200_000:
            if usage_pct >= 80:
                return {"strategy": "prune", "keep_recent": min(settings.compact_keep_recent, 5)}
            return {"strategy": "none"}

        # Large-context non-Anthropic models: compact at 80%, prune at 95%.
        if usage_pct >= 95:
            return {"strategy": "prune", "keep_recent": settings.compact_keep_recent}
        elif usage_pct >= 80:
            return {"strategy": "compact", "keep_recent": settings.compact_keep_recent}

        return {"strategy": "none"}

    return "context_action_handler", _decide_strategy
