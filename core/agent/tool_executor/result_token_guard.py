"""Shared helpers — model-aware tool result token limit + guard truncation."""

from __future__ import annotations

import json
from typing import Any

from core.orchestration.context_budget import MIN_TOOL_RESULT_TOKENS

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


# Failure control fields a truncated result keeps (see _guard_tool_result).
_ERROR_CONTROL_KEYS = ("recoverable", "outcome_uncertain", "effect_applied", "error_type")


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


def tool_result_char_limit(model: str = "", *, offload_threshold: int | None = None) -> int | None:
    """Largest serialized result the processor passes through unchanged.

    Mirrors ``ToolCallProcessor._serialize_tool_result``: a result is offloaded
    once its estimated tokens exceed the offload threshold (``None`` reads the
    configured one; non-positive disables it) and truncated past the
    model-aware guard limit. Returns None when neither bounds the result.
    """
    from core.config import settings as _settings
    from core.orchestration.context_budget import TOKEN_ESTIMATE_CHARS_PER_TOKEN

    threshold = _settings.tool_offload_threshold if offload_threshold is None else offload_threshold
    guard = _compute_model_tool_limit(model) if model else None
    if guard is None:
        guard = _settings.max_tool_result_tokens
    limits = [max(tokens, MIN_TOOL_RESULT_TOKENS) for tokens in (threshold, guard) if tokens > 0]
    return min(limits) * TOKEN_ESTIMATE_CHARS_PER_TOKEN if limits else None


def _guard_tool_result(
    result: dict[str, Any],
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Truncate oversized tool results while preserving summary.

    ``None`` uses the configured global limit; values at or below zero disable
    truncation explicitly, and positive values below ``MIN_TOOL_RESULT_TOKENS``
    are raised to it.
    """
    from core.config import settings as _settings

    if max_tokens is None:
        max_tokens = _settings.max_tool_result_tokens
    if max_tokens <= 0:
        return result
    max_tokens = max(max_tokens, MIN_TOOL_RESULT_TOKENS)
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
    # A failure's control fields outrank metadata and preview: the error (as a
    # bounded prefix), whether a retry can help, and whether an effect landed
    # survive truncation, so the model and convergence tracking still see it.
    error = result.get("error")
    error_text = "" if not error else error if isinstance(error, str) else _dumps(error)
    if error_text:
        # Reserve one character first so the flags below cannot crowd it out.
        base = _with_fitting(base, {"error": error_text[:1]}, max_chars)
    base = _with_fitting(base, result, max_chars, _ERROR_CONTROL_KEYS)
    if "error" in base:
        base = _fit_prefix(base, "error", error_text, max_chars) or base
    base = _with_fitting(
        base, result, max_chars, ("task_id", "task_type", "status", "error_message", "tier")
    )

    key = "summary" if "summary" in result else "preview"
    text = str(result["summary"]) if key == "summary" else serialized
    return _fit_prefix(base, key, text, max_chars) or base


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _with_fitting(
    base: dict[str, Any],
    source: dict[str, Any],
    max_chars: int,
    keys: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Add each of ``keys`` (default: all) from ``source`` that still fits, in order."""
    for key in source if keys is None else keys:
        if key in source:
            candidate = {**base, key: source[key]}
            if len(_dumps(candidate)) <= max_chars:
                base = candidate
    return base


def _fit_prefix(base: dict[str, Any], key: str, text: str, max_chars: int) -> dict[str, Any] | None:
    """Return ``base`` with the longest prefix of ``text`` at ``key`` that fits, or None."""
    low, high = 0, len(text)
    fitted: dict[str, Any] | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = {**base, key: text[:middle]}
        if len(_dumps(candidate)) <= max_chars:
            fitted = candidate
            low = middle + 1
        else:
            high = middle - 1
    return fitted


# Public projection boundary used by packaged benchmark adapters.
project_mcp_result = _project_mcp_result
guard_tool_result = _guard_tool_result
