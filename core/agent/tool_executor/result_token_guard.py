"""Shared helpers — model-aware tool result token limit + guard truncation."""

from __future__ import annotations

import json
from typing import Any

_MCP_RESULT_KEYS = {
    "_meta",
    "meta",
    "content",
    "structuredContent",
    "structured_content",
    "isError",
    "is_error",
}


def _project_mcp_result(result: dict[str, Any]) -> dict[str, Any]:
    """Choose one MCP CallToolResult representation for model context."""
    if not result or not set(result) <= _MCP_RESULT_KEYS:
        return result
    content = result.get("content")
    if not isinstance(content, list):
        return result

    structured = result.get("structuredContent", result.get("structured_content"))
    if structured is not None:
        projected = structured if isinstance(structured, dict) else {"result": structured}
    elif len(content) == 1 and isinstance(content[0], dict):
        text = content[0].get("text")
        projected = {"result": text} if isinstance(text, str) else {"content": content}
    else:
        projected = {"content": content}

    if result.get("isError", result.get("is_error", False)):
        return {"error": projected}
    return projected


def _compute_model_tool_limit(model: str) -> int | None:
    """Return a tighter model-specific cap, or defer to the global cap.

    Large and standard tiers use the configured global result limit. Small
    tiers use the lower of that limit and their context-derived share. A
    non-positive global limit remains an explicit opt-out.
    """
    from core.config import settings as _settings
    from core.orchestration.context_budget import resolve_context_budget_policy

    policy = resolve_context_budget_policy(model)
    if policy.tier.name != "small":
        return None
    global_limit = _settings.max_tool_result_tokens
    if global_limit <= 0:
        return 0
    return min(global_limit, policy.per_tool_result_limit_tokens)


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary.

    ``None`` uses the configured global limit; values at or below zero disable
    truncation explicitly.
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

    max_chars = max_tokens * TOKEN_ESTIMATE_CHARS_PER_TOKEN
    if len(serialized) <= max_chars:
        return result
    estimated_tokens = (
        len(serialized) + TOKEN_ESTIMATE_CHARS_PER_TOKEN - 1
    ) // TOKEN_ESTIMATE_CHARS_PER_TOKEN

    base: dict[str, Any] = {
        "_truncated": True,
        "_original_tokens": estimated_tokens,
    }
    for key in ("task_id", "task_type", "status", "error_message", "tier"):
        if key in result:
            candidate = {**base, key: result[key]}
            if len(json.dumps(candidate, ensure_ascii=False, default=str)) <= max_chars:
                base = candidate

    key = "summary" if "summary" in result else "preview"
    text = str(result["summary"]) if key == "summary" else serialized
    low, high = 0, len(text)
    guarded: dict[str, Any] = {}
    while low <= high:
        middle = (low + high) // 2
        candidate = {**base, key: text[:middle]}
        if len(json.dumps(candidate, ensure_ascii=False, default=str)) <= max_chars:
            guarded = candidate
            low = middle + 1
        else:
            high = middle - 1
    return guarded
