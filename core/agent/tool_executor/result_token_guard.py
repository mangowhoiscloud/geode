"""Shared helpers — model-aware tool result token limit + guard truncation."""

from __future__ import annotations

import json
from typing import Any


def _compute_model_tool_limit(model: str) -> int:
    """Compute per-tool-result token limit based on model context window.

    For large-context models (>=200K), returns 0 (unlimited — server-side handles it).
    For small-context models (<200K, e.g. GLM-5), caps each tool result at 5% of
    the context window to prevent a single result from consuming the budget.
    """
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

    ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)
    if ctx >= 200_000:
        return 0  # trust server-side clear_tool_uses
    return ctx // 20  # 5% of context window


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
    estimated_tokens = len(serialized) // 4
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
        "preview": serialized[: max_tokens * 4],
    }
