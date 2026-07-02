"""Context overflow action handler — decides compression strategy via Hook.

Provider-aware strategy selection:
- Anthropic: server-side compaction (compact_20260112) handles warning-level
  pressure. Client only intervenes at the resolved policy critical threshold.
- OpenAI/GLM: no server-side compaction. Client triggers LLM-based compaction
  at the resolved policy warning threshold and emergency prune remains a
  fallback when compaction cannot recover enough context.
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
        from core.orchestration.context_budget import resolve_context_budget_policy

        metrics = data.get("metrics", {})
        model: str = data.get("model", "unknown")
        provider: str = data.get("provider", "anthropic")
        context_window = metrics.get("context_window")
        policy = resolve_context_budget_policy(model, context_window=context_window)
        estimated_tokens = metrics.get("estimated_tokens")
        if estimated_tokens is None:
            usage_pct: float = metrics.get("usage_pct", 0)
            estimated_tokens = int(usage_pct / 100 * policy.context_window)
        is_warning = bool(metrics.get("is_warning", estimated_tokens >= policy.warning_tokens))
        is_critical = bool(metrics.get("is_critical", estimated_tokens >= policy.critical_tokens))
        keep_recent = policy.resolve_keep_recent(settings.compact_keep_recent)

        # Anthropic: server-side compaction + clear_tool_uses handle warning pressure.
        # Client only intervenes at the policy critical threshold as an
        # emergency safety net.
        if provider == "anthropic":
            if is_critical:
                return {"strategy": "prune", "keep_recent": keep_recent, "policy": policy}
            return {"strategy": "none"}

        # Non-Anthropic (OpenAI, GLM): no server-side compaction.
        if is_critical or is_warning:
            return {"strategy": "compact", "keep_recent": keep_recent, "policy": policy}

        return {"strategy": "none"}

    return "context_action_handler", _decide_strategy
