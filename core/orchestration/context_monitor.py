"""Context Overflow Detection — proactive token budget monitoring.

Monitors conversation context size against model context window limits.
Emits CONTEXT_CRITICAL hook events
before the API returns a context overflow error.

Karpathy P6 Context Budget pattern: detect and compress before hitting limits.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from core.orchestration.context_budget import (
    ABSOLUTE_TOKEN_CEILING as _ABSOLUTE_TOKEN_CEILING,
)
from core.orchestration.context_budget import (
    DEFAULT_TOOLS_OVERHEAD_TOKENS,
    LARGE_CRITICAL_THRESHOLD_PCT,
    LARGE_WARNING_THRESHOLD_PCT,
    TOKEN_ESTIMATE_CHARS_PER_TOKEN,
    TOOL_ARG_STRING_HEAD_CHARS,
    TOOL_RESULT_SUMMARY_MIN_CHARS,
    ContextBudgetPolicy,
    resolve_context_budget_policy,
)

log = logging.getLogger(__name__)

ABSOLUTE_TOKEN_CEILING = _ABSOLUTE_TOKEN_CEILING
WARNING_THRESHOLD = LARGE_WARNING_THRESHOLD_PCT
CRITICAL_THRESHOLD = LARGE_CRITICAL_THRESHOLD_PCT
CHARS_PER_TOKEN = TOKEN_ESTIMATE_CHARS_PER_TOKEN
_DEFAULT_TOOLS_OVERHEAD = DEFAULT_TOOLS_OVERHEAD_TOKENS


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    """Snapshot of context window usage."""

    estimated_tokens: int
    context_window: int
    usage_pct: float
    remaining_tokens: int
    is_warning: bool
    is_critical: bool
    raw_estimated_tokens: int = 0
    prompt_budget_tokens: int = 0
    remaining_prompt_tokens: int = 0
    warning_tokens: int = 0
    critical_tokens: int = 0
    is_ceiling_exceeded: bool = False
    policy: ContextBudgetPolicy | None = None


def estimate_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages.

    Uses the policy-owned chars/token heuristic.
    Tool-use content (JSON) tends to be slightly more tokens per char,
    so this is an approximation that slightly underestimates.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    # tool_use, tool_result, text blocks
                    text = block.get("text", "") or block.get("content", "")
                    if isinstance(text, str):
                        total_chars += len(text)
                    elif isinstance(text, list):
                        # Nested content (tool_result with list content)
                        for sub in text:
                            if isinstance(sub, dict):
                                total_chars += len(sub.get("text", ""))
                            elif isinstance(sub, str):
                                total_chars += len(sub)
                    # Add overhead for block metadata (type, id, name, etc.)
                    total_chars += len(json.dumps(block, default=str)) - len(str(text))
                elif isinstance(block, str):
                    total_chars += len(block)
    return max(total_chars // CHARS_PER_TOKEN, 1)


def check_context(
    messages: list[dict[str, Any]],
    model: str,
    *,
    system_prompt: str = "",
    tools_tokens: int = 0,
) -> ContextMetrics:
    """Check context window health for the given conversation.

    Args:
        tools_tokens: Estimated tokens for tool definitions sent to the API.
            Defaults to _DEFAULT_TOOLS_OVERHEAD (~10K) when 0.

    Returns a ContextMetrics snapshot with usage percentage and thresholds.
    """
    policy = resolve_context_budget_policy(model)
    context_window = policy.context_window

    system_tokens = len(system_prompt) // CHARS_PER_TOKEN if system_prompt else 0
    message_tokens = estimate_message_tokens(messages)
    overhead = tools_tokens if tools_tokens > 0 else policy.default_tools_overhead_tokens
    raw_estimated = system_tokens + message_tokens + overhead
    estimated = policy.apply_safety_margin(raw_estimated)

    usage_pct = estimated / context_window * 100
    remaining = max(context_window - estimated, 0)
    remaining_prompt = max(policy.effective_prompt_budget_tokens - estimated, 0)

    ceiling_exceeded = (
        estimated > policy.absolute_ceiling_tokens
        and context_window > policy.absolute_ceiling_tokens
    )

    return ContextMetrics(
        raw_estimated_tokens=raw_estimated,
        estimated_tokens=estimated,
        context_window=context_window,
        usage_pct=usage_pct,
        remaining_tokens=remaining,
        prompt_budget_tokens=policy.effective_prompt_budget_tokens,
        remaining_prompt_tokens=remaining_prompt,
        warning_tokens=policy.warning_tokens,
        critical_tokens=policy.critical_tokens,
        is_warning=estimated >= policy.warning_tokens,
        is_critical=estimated >= policy.critical_tokens,
        is_ceiling_exceeded=ceiling_exceeded,
        policy=policy,
    )


def prune_oldest_messages(
    messages: list[dict[str, Any]],
    *,
    keep_recent: int = 10,
) -> list[dict[str, Any]]:
    """Emergency pruning: keep only the most recent N message pairs.

    Preserves system message integrity by keeping the first message
    if it's from the user (initial context), plus the most recent messages.
    """
    if len(messages) <= keep_recent:
        return messages

    # Keep the first message (initial user context) + last N
    return messages[:1] + messages[-keep_recent:]


def _truncate_tool_call_args_json(args: str) -> str:
    """Shrink long string leaves in tool-call JSON while preserving validity."""
    try:
        parsed = json.loads(args)
    except (TypeError, ValueError):
        return args

    def shrink(value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > TOOL_ARG_STRING_HEAD_CHARS:
                return value[:TOOL_ARG_STRING_HEAD_CHARS] + "...[truncated]"
            return value
        if isinstance(value, list):
            return [shrink(v) for v in value]
        if isinstance(value, dict):
            return {k: shrink(v) for k, v in value.items()}
        return value

    return json.dumps(shrink(parsed), ensure_ascii=False)


def _assistant_tool_call_index(messages: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Map tool call ids to ``(name, arguments_json)`` across provider shapes."""
    index: dict[str, tuple[str, str]] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = block.get("id")
                name = block.get("name")
                args = block.get("input", {})
                if isinstance(call_id, str) and isinstance(name, str):
                    index[call_id] = (
                        name,
                        json.dumps(args, ensure_ascii=False, default=str)
                        if not isinstance(args, str)
                        else args,
                    )
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            call_id = call.get("id")
            fn = call.get("function")
            if isinstance(call_id, str) and isinstance(fn, dict):
                name = fn.get("name")
                args = fn.get("arguments", "")
                if isinstance(name, str):
                    index[call_id] = (name, args if isinstance(args, str) else "")
    return index


def _summarize_tool_result(tool_name: str, tool_args: str, tool_content: Any) -> str:
    """Create an informative single-line summary for a pruned tool result."""
    if isinstance(tool_content, list):
        text_parts = []
        image_count = 0
        for part in tool_content:
            if isinstance(part, dict):
                ptype = part.get("type")
                if ptype in {"image", "image_url", "input_image"}:
                    image_count += 1
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
            elif isinstance(part, str):
                text_parts.append(part)
        content_text = "\n".join(text_parts)
        if image_count:
            content_text += f"\n[{image_count} image payload(s) removed]"
    else:
        content_text = str(tool_content or "")

    try:
        args = json.loads(tool_args) if tool_args else {}
    except (TypeError, ValueError):
        args = {}
    if not isinstance(args, dict):
        args = {}

    content_len = len(content_text)
    line_count = content_text.count("\n") + 1 if content_text.strip() else 0

    if tool_name in {"run_bash", "terminal", "shell"}:
        cmd = str(args.get("cmd") or args.get("command") or "")[:120]
        exit_match = re.search(r"(?:exit(?:_code)?|returncode)[\"':=\s]+(-?\d+)", content_text)
        exit_code = exit_match.group(1) if exit_match else "?"
        return f"[{tool_name}] ran `{cmd}` -> exit {exit_code}, {line_count} lines output"
    if tool_name in {"read_file", "file_read"}:
        path = args.get("path") or args.get("file_path") or "?"
        start = args.get("start_line") or args.get("offset") or args.get("line") or 1
        return f"[{tool_name}] read {path} from line {start} ({content_len:,} chars)"
    if tool_name in {"write_file", "file_write", "edit_file", "apply_patch"}:
        path = args.get("path") or args.get("file_path") or "?"
        return f"[{tool_name}] changed {path} ({content_len:,} chars result)"
    if tool_name in {"search_files", "rg", "grep"}:
        pattern = args.get("pattern") or args.get("query") or "?"
        path = args.get("path") or args.get("cwd") or "."
        match = re.search(r"(?:total_count|matches|count)[\"':=\s]+(\d+)", content_text)
        count = match.group(1) if match else "?"
        return f"[{tool_name}] searched `{pattern}` in {path} -> {count} matches"
    if tool_name in {"web_search", "web_fetch", "web_extract"}:
        query = args.get("query") or args.get("url") or args.get("urls") or "?"
        return f"[{tool_name}] {query} ({content_len:,} chars result)"
    if tool_name in {"delegate_task", "subagent"}:
        task = str(args.get("task") or args.get("goal") or "")[:100]
        return f"[{tool_name}] delegated `{task}` ({content_len:,} chars result)"
    if tool_name in {"memory_save", "memory_search", "note_save", "note_read"}:
        action = args.get("action") or tool_name
        target = args.get("target") or args.get("query") or ""
        return f"[{tool_name}] {action} {target}".strip()

    preview_args = " ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:2])
    suffix = f" {preview_args}" if preview_args else ""
    return f"[{tool_name}]{suffix} ({content_len:,} chars result)"


def _compact_tool_content(tool_name: str, tool_args: str, content: Any) -> str:
    estimated = len(json.dumps(content, default=str)) // CHARS_PER_TOKEN
    summary = _summarize_tool_result(tool_name, tool_args, content)
    return f"{summary} [summarized from ~{estimated:,} tokens]"


def _truncate_old_assistant_tool_args(
    messages: list[dict[str, Any]],
    policy: ContextBudgetPolicy,
) -> int:
    modified = 0
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        calls = msg.get("tool_calls")
        if not isinstance(calls, list):
            continue
        new_calls: list[Any] = []
        changed = False
        for call in calls:
            if not isinstance(call, dict):
                new_calls.append(call)
                continue
            fn = call.get("function")
            if not isinstance(fn, dict):
                new_calls.append(call)
                continue
            args = fn.get("arguments")
            if not isinstance(args, str) or len(args) <= policy.summary_tool_args_max_chars:
                new_calls.append(call)
                continue
            new_args = _truncate_tool_call_args_json(args)
            if new_args != args:
                call = {**call, "function": {**fn, "arguments": new_args}}
                changed = True
            new_calls.append(call)
        if changed:
            msg["tool_calls"] = new_calls
            modified += 1
    return modified


def summarize_tool_results(
    messages: list[dict[str, Any]],
    target_window: int | ContextBudgetPolicy,
) -> tuple[int, int, int]:
    """Replace large tool_result content with compact summaries.

    Mutates messages in-place.
    Returns (summarized_count, tokens_before, tokens_after).
    Only targets tool_result blocks exceeding the policy-derived threshold.
    """
    policy = (
        target_window
        if isinstance(target_window, ContextBudgetPolicy)
        else resolve_context_budget_policy(context_window=target_window)
    )
    tokens_before = estimate_message_tokens(messages)
    threshold = policy.tool_summary_threshold_tokens
    summarized = 0
    call_index = _assistant_tool_call_index(messages)
    seen_tool_result_hashes: dict[str, str] = {}

    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) < TOOL_RESULT_SUMMARY_MIN_CHARS:
                continue
            estimated = len(json.dumps(content, default=str)) // CHARS_PER_TOKEN
            if estimated <= threshold:
                continue
            tool_call_id = msg.get("tool_call_id")
            tool_name = str(msg.get("tool_name") or msg.get("name") or "unknown")
            tool_args = ""
            if isinstance(tool_call_id, str) and tool_call_id in call_index:
                tool_name, tool_args = call_index[tool_call_id]
            rendered = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
            if rendered in seen_tool_result_hashes:
                msg["content"] = (
                    "[Duplicate tool output — same content as a more recent call "
                    f"{seen_tool_result_hashes[rendered]}]"
                )
            else:
                seen_tool_result_hashes[rendered] = str(tool_call_id or "?")
                msg["content"] = _compact_tool_content(tool_name, tool_args, content)
            summarized += 1
            continue

        if role != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content", "")
            if isinstance(inner, str) and len(inner) < TOOL_RESULT_SUMMARY_MIN_CHARS:
                continue  # already small
            estimated = len(json.dumps(block, default=str)) // CHARS_PER_TOKEN
            if estimated > threshold:
                tool_use_id = block.get("tool_use_id")
                tool_name, tool_args = (
                    call_index.get(tool_use_id, ("unknown", ""))
                    if isinstance(tool_use_id, str)
                    else ("unknown", "")
                )
                rendered = json.dumps(inner, sort_keys=True, ensure_ascii=False, default=str)
                if rendered in seen_tool_result_hashes:
                    block["content"] = (
                        "[Duplicate tool output — same content as a more recent call "
                        f"{seen_tool_result_hashes[rendered]}]"
                    )
                else:
                    seen_tool_result_hashes[rendered] = str(tool_use_id or "?")
                    block["content"] = _compact_tool_content(tool_name, tool_args, inner)
                summarized += 1

    summarized += _truncate_old_assistant_tool_args(messages, policy)

    tokens_after = estimate_message_tokens(messages)
    if summarized:
        log.info(
            "Summarized %d tool results: %d → %d tokens (-%d)",
            summarized,
            tokens_before,
            tokens_after,
            tokens_before - tokens_after,
        )
    return summarized, tokens_before, tokens_after


def adaptive_prune(
    messages: list[dict[str, Any]],
    target_tokens: int | ContextBudgetPolicy,
) -> list[dict[str, Any]]:
    """Token-aware pruning: build result from newest messages within budget.

    Strategy:
    1. Always keep the first message (initial context)
    2. Always keep the last 2 messages (most recent exchange)
    3. Add middle messages from newest to oldest until budget is reached
    4. Budget is the resolved policy's warning-token budget.
    """
    if len(messages) <= 3:
        return list(messages)

    policy = (
        target_tokens
        if isinstance(target_tokens, ContextBudgetPolicy)
        else resolve_context_budget_policy(context_window=target_tokens)
    )
    budget = policy.prune_budget_tokens
    first = messages[0]
    recent = messages[-2:]
    middle = messages[1:-2]

    base_tokens = estimate_message_tokens([first]) + estimate_message_tokens(recent)
    if base_tokens >= budget:
        # Even first + recent exceeds budget — return minimal
        return [first, *recent]

    remaining_budget = budget - base_tokens
    kept_middle: list[dict[str, Any]] = []

    # Add from newest to oldest
    for msg in reversed(middle):
        msg_tokens = estimate_message_tokens([msg])
        if remaining_budget - msg_tokens >= 0:
            kept_middle.append(msg)
            remaining_budget -= msg_tokens
        # Skip messages that don't fit

    kept_middle.reverse()  # restore chronological order
    result = [first, *kept_middle, *recent]
    tokens_before = estimate_message_tokens(messages)
    tokens_after = estimate_message_tokens(result)
    log.info(
        "Adaptive prune: %d → %d messages, %d → %d tokens (-%d)",
        len(messages),
        len(result),
        tokens_before,
        tokens_after,
        tokens_before - tokens_after,
    )
    return result


def mask_stale_observations(
    messages: list[dict[str, Any]],
    *,
    keep_recent_rounds: int = 3,
) -> int:
    """Replace older tool_result content with compact placeholders.

    Preserves ``type`` and ``tool_use_id`` for API compatibility.
    Only masks tool_result blocks in user messages older than the most
    recent *keep_recent_rounds* assistant->user round-trips.

    Mutates messages in-place.  Returns count of masked blocks.

    JetBrains Research (2025.12): observation masking achieves equivalent
    solve rates to LLM summarization at 52% lower cost and 15% faster.
    """
    # Count assistant messages to determine round boundaries
    assistant_indices: list[int] = [
        i for i, m in enumerate(messages) if m.get("role") == "assistant"
    ]
    if len(assistant_indices) <= keep_recent_rounds:
        return 0  # not enough rounds to mask anything

    # The cutoff: messages before this index are "stale"
    cutoff_idx = assistant_indices[-keep_recent_rounds]

    masked = 0
    for i, msg in enumerate(messages):
        if i >= cutoff_idx:
            break  # only process messages before cutoff
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content", "")
            # Skip already-masked or tiny results
            if isinstance(inner, str) and (inner.startswith("[masked:") or len(inner) < 200):
                continue
            estimated = len(json.dumps(block, default=str)) // CHARS_PER_TOKEN
            block["content"] = f"[masked: {estimated:,} tokens, use recall_tool_result if needed]"
            masked += 1

    if masked:
        log.info("Masked %d stale tool observations (before round -%d)", masked, keep_recent_rounds)
    return masked
