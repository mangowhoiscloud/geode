"""Context window management — extracted from AgenticLoop for SRP.

Handles context overflow detection, message pruning, compaction,
aggressive recovery, and strategy resolution.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from core.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)


class ContextWindowManager:
    """Manages context window overflow detection and compression.

    Extracted from AgenticLoop to isolate context budget concerns.
    Uses composition: AgenticLoop creates and owns this instance.
    """

    def __init__(
        self,
        *,
        hooks: HookSystem | None,
        quiet: bool,
    ) -> None:
        self._hooks = hooks
        self._quiet = quiet

    def maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Prune old messages when conversation exceeds 5 rounds (10 msgs).

        Keeps first user message + bridge + recent messages for context budget.
        Ensures:
        1. user/assistant alternation is preserved
        2. No orphaned tool_result messages (each tool_result must follow
           an assistant message containing the matching tool_use block)
        """
        if len(messages) <= 30:
            return
        first = messages[0]
        # Walk backward to find a safe cut point:
        # - Must be a "user" role message
        # - Must NOT be a tool_result message (those need a preceding tool_use)
        safe_cut = None
        for candidate in range(-4, -(len(messages)), -1):
            idx = len(messages) + candidate
            if idx <= 0:
                break
            msg = messages[idx]
            if msg["role"] != "user":
                continue
            content = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                continue  # Skip — orphaned tool_result after pruning
            safe_cut = candidate
            break

        if safe_cut is None:
            return

        recent = messages[safe_cut:]
        bridge: dict[str, Any] = {
            "role": "assistant",
            "content": [{"type": "text", "text": "(earlier rounds omitted)"}],
        }
        messages.clear()
        messages.extend([first, bridge, *recent])
        log.debug("Pruned messages: kept first + bridge + %d recent", len(recent))

    def check_context_overflow(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
    ) -> None:
        """Check context window usage and apply provider-aware compression.

        Strategy by provider:
        - Anthropic: server-side compaction (compact_20260112) handles 80%+ automatically.
          Client only intervenes at 95% as emergency prune safety net.
        - OpenAI/GLM: no server-side compaction. Client triggers LLM-based compaction
          at 80% and emergency prune at 95%.

        Absolute ceiling (200K tokens):
        - Large-context models (1M) hit rate limit pool separation at >200K tokens.
          Percentage thresholds (80%=800K) are too distant to catch this.
          When estimated > 200K on a >200K-window model, force tool result
          summarization + compact to stay under the ceiling.

        Compression strategy is delegated to the CONTEXT_OVERFLOW_ACTION hook handler.
        If no handler is registered or all fail, falls back to hardcoded defaults.
        """
        try:
            from core.config import settings
            from core.orchestration.context_monitor import check_context

            metrics = check_context(messages, model, system_prompt=system)

            if metrics.is_critical:
                log.warning(
                    "Context CRITICAL: %.0f%% (%d/%d tokens) — emergency action",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    self._hooks.trigger(
                        HookEvent.CONTEXT_CRITICAL,
                        {"metrics": dataclasses.asdict(metrics), "model": model},
                    )

                strategy = self._resolve_overflow_strategy(metrics, settings, model, provider)
                self._apply_overflow_strategy(strategy, messages, settings, model, provider)

                # Re-check: if still critical after pruning, context is exhausted
                post = check_context(messages, model, system_prompt=system)
                if post.is_critical:
                    from core.agent.agentic_loop import _ContextExhaustedError

                    raise _ContextExhaustedError(
                        f"Context exhausted: {post.usage_pct:.0f}% after pruning"
                    )

            elif metrics.is_warning:
                # Step 1: mask stale observations (cheapest — no LLM call)
                from core.orchestration.context_monitor import mask_stale_observations

                mask_keep = settings.observation_mask_keep_rounds
                masked = mask_stale_observations(messages, keep_recent_rounds=mask_keep)
                if masked > 0:
                    log.info(
                        "Context at %.0f%%: masked %d stale observations",
                        metrics.usage_pct,
                        masked,
                    )

                # Step 2: compact or summarize
                strategy = self._resolve_overflow_strategy(metrics, settings, model, provider)
                if strategy.get("strategy") == "compact":
                    self._apply_overflow_strategy(strategy, messages, settings, model, provider)
                else:
                    from core.orchestration.context_monitor import summarize_tool_results

                    summarized, _tok_before, _tok_after = summarize_tool_results(
                        messages,
                        metrics.context_window,
                    )
                    if summarized > 0:
                        log.info(
                            "Context at %.0f%%: summarized %d large tool results",
                            metrics.usage_pct,
                            summarized,
                        )

            elif metrics.is_ceiling_exceeded:
                from core.orchestration.context_monitor import (
                    ABSOLUTE_TOKEN_CEILING,
                    summarize_tool_results,
                )

                log.info(
                    "Context ceiling: %d tokens > %dK ceiling (%.0f%% of %dK window) "
                    "— compressing to avoid rate limit pool separation",
                    metrics.estimated_tokens,
                    ABSOLUTE_TOKEN_CEILING // 1000,
                    metrics.usage_pct,
                    metrics.context_window // 1000,
                )

                # Phase 1: summarize large tool results
                summarized, _tok_before, _tok_after = summarize_tool_results(
                    messages,
                    ABSOLUTE_TOKEN_CEILING,
                )
                post = check_context(messages, model, system_prompt=system)

                if post.is_ceiling_exceeded:
                    # Phase 2: compact conversation
                    strategy = {"strategy": "compact", "keep_recent": settings.compact_keep_recent}
                    self._apply_overflow_strategy(strategy, messages, settings, model, provider)

        except Exception:
            log.debug("Context monitor check failed", exc_info=True)

    def _apply_overflow_strategy(
        self,
        strategy: dict[str, Any],
        messages: list[dict[str, Any]],
        settings: Any,
        model: str,
        provider: str,
    ) -> None:
        """Execute the overflow strategy (prune or compact)."""
        from core.orchestration.context_monitor import prune_oldest_messages

        action = strategy.get("strategy", "none")
        keep_recent = strategy.get("keep_recent", settings.compact_keep_recent)

        if action == "compact":
            import asyncio

            from core.orchestration.compaction import compact_conversation

            try:
                new_msgs, did_compact = asyncio.get_event_loop().run_until_complete(
                    compact_conversation(
                        messages,
                        provider=provider,
                        model=model,
                        keep_recent=keep_recent,
                    )
                )
                if did_compact:
                    original_count = len(messages)
                    messages.clear()
                    messages.extend(new_msgs)
                    self._notify_context_event(
                        "compact",
                        original_count=original_count,
                        new_count=len(new_msgs),
                    )
                    return
            except Exception:
                log.warning("Client compaction failed — falling back to prune", exc_info=True)
            # Fall through to prune on failure
            action = "prune"

        if action == "prune":
            pruned = prune_oldest_messages(messages, keep_recent=keep_recent)
            original_count = len(messages)
            if len(pruned) < original_count:
                messages.clear()
                messages.extend(pruned)
                log.info(
                    "Emergency pruned: %d → %d messages (keep_recent=%d)",
                    original_count,
                    len(pruned),
                    keep_recent,
                )
                self._notify_context_event(
                    "prune",
                    original_count=original_count,
                    new_count=len(pruned),
                )

    def aggressive_context_recovery(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str = "anthropic",
    ) -> int:
        """Last-resort context recovery: aggressive prune + tool result summarization.

        Delegates strategy selection to CONTEXT_OVERFLOW_ACTION hook (same path
        as normal overflow) with aggressive keep_recent override.

        Returns number of messages freed, or 0 if recovery failed.
        """
        try:
            from core.config import settings
            from core.orchestration.context_monitor import (
                check_context,
                summarize_tool_results,
            )

            original_count = len(messages)

            # Phase 1: summarize large tool_result blocks in-place
            ctx_window = getattr(
                check_context(messages, model, system_prompt=system),
                "context_window",
                200_000,
            )
            summarized, _tok_before, _tok_after = summarize_tool_results(messages, ctx_window)
            if summarized > 0:
                log.info("Aggressive recovery: summarized %d tool results", summarized)

            # Check if summarization alone resolved it
            post = check_context(messages, model, system_prompt=system)
            if not post.is_critical:
                return original_count - len(messages) + summarized

            # Phase 2: delegate to CONTEXT_OVERFLOW_ACTION hook for strategy
            strategy = self._resolve_overflow_strategy(post, settings, model, provider)

            # Override keep_recent aggressively (halved, min 3)
            aggressive_keep = max(3, settings.compact_keep_recent // 2)
            strategy["keep_recent"] = aggressive_keep

            # Force prune if hook returned "none" — aggressive recovery must act
            if strategy.get("strategy") == "none":
                strategy["strategy"] = "prune"

            self._apply_overflow_strategy(strategy, messages, settings, model, provider)

            # Final check
            post2 = check_context(messages, model, system_prompt=system)
            if not post2.is_critical:
                return original_count - len(messages)

            return 0  # recovery failed
        except Exception:
            log.warning("Aggressive context recovery failed", exc_info=True)
            return 0

    def _notify_context_event(
        self,
        event_type: str,
        *,
        original_count: int,
        new_count: int,
    ) -> None:
        """Notify user of automatic context compression via UI."""
        if self._quiet:
            return
        try:
            from core.cli.ui.agentic_ui import render_context_event

            render_context_event(event_type, original_count=original_count, new_count=new_count)
        except Exception:
            log.debug("Context event notification failed", exc_info=True)

    def _resolve_overflow_strategy(
        self, metrics: Any, settings: Any, model: str, provider: str
    ) -> dict[str, Any]:
        """Ask CONTEXT_OVERFLOW_ACTION hook for compression strategy, with fallback."""
        if self._hooks:
            results = self._hooks.trigger_with_result(
                HookEvent.CONTEXT_OVERFLOW_ACTION,
                {
                    "metrics": dataclasses.asdict(metrics),
                    "model": model,
                    "provider": provider,
                },
            )
            for result in results:
                if result.success and result.data.get("strategy"):
                    return result.data

        # Fallback: hardcoded default (no handler registered or all failed)
        keep_recent = settings.compact_keep_recent
        if provider == "anthropic":
            if metrics.usage_pct >= 95:
                return {"strategy": "prune", "keep_recent": keep_recent}
            return {"strategy": "none"}

        # Non-Anthropic: compact at 80%, prune at 95%
        if metrics.context_window < 200_000:
            keep_recent = min(keep_recent, 5)
        if metrics.usage_pct >= 95:
            return {"strategy": "prune", "keep_recent": keep_recent}
        elif metrics.usage_pct >= 80:
            return {"strategy": "compact", "keep_recent": keep_recent}
        return {"strategy": "none"}

    @staticmethod
    def repair_messages(messages: list[dict[str, Any]]) -> None:
        """Remove orphaned tool_result messages that lack a preceding tool_use.

        Scans backward and removes any user message whose content is entirely
        tool_result blocks without matching tool_use in the prior assistant msg.
        """
        i = len(messages) - 1
        while i >= 1:
            msg = messages[i]
            if msg["role"] != "user":
                i -= 1
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                i -= 1
                continue
            # Check if ALL blocks are tool_result
            tr_ids = {
                b["tool_use_id"]
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result"
            }
            if not tr_ids:
                i -= 1
                continue
            # Check preceding assistant message for matching tool_use
            if i > 0 and messages[i - 1]["role"] == "assistant":
                prev_content = messages[i - 1].get("content", [])
                if isinstance(prev_content, list):
                    tu_ids = {
                        b.get("id")
                        for b in prev_content
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    }
                    if tr_ids <= tu_ids:
                        i -= 1
                        continue  # All tool_results have matching tool_use — OK
            # Orphaned — remove this tool_result message and its preceding
            # assistant message (which also lost its tool_use context)
            log.debug("Removing orphaned tool_result at index %d", i)
            messages.pop(i)
            if i > 0 and messages[i - 1]["role"] == "assistant":
                prev_c = messages[i - 1].get("content", [])
                if isinstance(prev_c, list):
                    has_tool_use = any(
                        isinstance(b, dict) and b.get("type") == "tool_use" for b in prev_c
                    )
                    if not has_tool_use:
                        messages.pop(i - 1)
                        i -= 1
            i -= 1
