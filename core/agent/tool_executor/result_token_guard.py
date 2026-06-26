"""Shared helpers — model-aware tool result token limit + guard truncation."""

from __future__ import annotations

import json
from typing import Any


def _compute_model_tool_limit(model: str) -> int:
    """Compute per-tool-result token limit based on model context window.

    Large-window tiers rely on server-side handling.  Small-window tiers cap
    each tool result at the policy-derived share of the context window.
    """
    from core.orchestration.context_budget import resolve_context_budget_policy

    policy = resolve_context_budget_policy(model)
    if policy.tier.name != "small":
        return 0
    return policy.per_tool_result_limit_tokens


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary.

    When *max_tokens* is 0 (default), no truncation is performed.
    """
    from core.config import settings as _settings

    if max_tokens is None:
        max_tokens = _settings.max_tool_result_tokens
    if max_tokens <= 0:
        return result
    try:
        serialized = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return result
    from core.orchestration.context_budget import TOKEN_ESTIMATE_CHARS_PER_TOKEN

    estimated_tokens = len(serialized) // TOKEN_ESTIMATE_CHARS_PER_TOKEN
    if estimated_tokens <= max_tokens:
        return result
    # Preserve summary if present (SubAgentResult always has one)
    if "summary" in result:
        guarded: dict[str, Any] = {
            "summary": result["summary"],
            "_truncated": True,
            "_original_tokens": estimated_tokens,
        }
        for key in ("task_id", "task_type", "status", "error_message", "tier"):
            if key in result:
                guarded[key] = result[key]
        return guarded
    return {
        "_truncated": True,
        "_original_tokens": estimated_tokens,
        "preview": serialized[: max_tokens * TOKEN_ESTIMATE_CHARS_PER_TOKEN],
    }
