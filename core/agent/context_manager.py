"""Context window management — extracted from AgenticLoop for SRP.

Handles context overflow detection, message pruning, compaction,
aggressive recovery, and strategy resolution.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.orchestration.context_budget import (
    ABSOLUTE_TOKEN_CEILING,
    PRUNE_ACTIVATION_MESSAGE_COUNT,
    resolve_context_budget_policy,
)

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
        session_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._hooks = hooks
        self._quiet = quiet
        # Late-bound: the loop's session_id is assigned after construction, so
        # compaction resolves it at call time — without it the primary overflow
        # path never persists context_artifacts (writer-reader parity).
        self._session_id_provider = session_id_provider

    def maybe_prune_messages(self, messages: list[dict[str, Any]]) -> None:
        """Prune old messages when conversation exceeds 5 rounds (10 msgs).

        Keeps first user message + bridge + recent messages for context budget.
        Ensures:
        1. user/assistant alternation is preserved
        2. No orphaned tool_result messages (each tool_result must follow
           an assistant message containing the matching tool_use block)
        """
        if len(messages) <= PRUNE_ACTIVATION_MESSAGE_COUNT:
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

    async def check_context_overflow(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
    ) -> None:
        """Check context window usage and apply provider-aware compression.

        Strategy by provider:
        - Anthropic: server-side compaction handles warning-level pressure.
          Client only intervenes at the policy critical threshold.
        - OpenAI/GLM: no server-side compaction. Client triggers LLM-based
          compaction at warning pressure and emergency prune at critical pressure.

        The policy also carries the absolute ceiling that avoids large-context
        rate-limit pool separation before percentage thresholds become relevant.

        Compression strategy is delegated to the CONTEXT_OVERFLOW_ACTION hook handler.
        If no handler is registered or all fail, falls back to the resolved policy.
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
                    await self._hooks.trigger_async(
                        HookEvent.CONTEXT_CRITICAL,
                        {"metrics": dataclasses.asdict(metrics), "model": model},
                    )

                from core.orchestration.context_monitor import (
                    adaptive_prune,
                    summarize_tool_results,
                )

                summarize_tool_results(
                    messages,
                    getattr(metrics, "policy", None) or metrics.context_window,
                )
                metrics = check_context(messages, model, system_prompt=system)
                strategy = await self._resolve_overflow_strategy(metrics, settings, model, provider)
                await self._apply_overflow_strategy(strategy, messages, settings, model, provider)

                # Re-check: if still critical after pruning, context is exhausted
                post = check_context(messages, model, system_prompt=system)
                if post.is_critical:
                    pruned = adaptive_prune(
                        messages,
                        getattr(post, "policy", None) or post.context_window,
                    )
                    from core.orchestration.compaction import repair_tool_pairs

                    messages.clear()
                    messages.extend(repair_tool_pairs(pruned))
                    post = check_context(messages, model, system_prompt=system)

                if post.is_critical:
                    from core.agent.loop import _ContextExhaustedError

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
                strategy = await self._resolve_overflow_strategy(metrics, settings, model, provider)
                if strategy.get("strategy") == "compact":
                    await self._apply_overflow_strategy(
                        strategy, messages, settings, model, provider
                    )
                else:
                    from core.orchestration.context_monitor import summarize_tool_results

                    summarized, _tok_before, _tok_after = summarize_tool_results(
                        messages,
                        metrics.policy or metrics.context_window,
                    )
                    if summarized > 0:
                        log.info(
                            "Context at %.0f%%: summarized %d large tool results",
                            metrics.usage_pct,
                            summarized,
                        )

            elif metrics.is_ceiling_exceeded:
                from core.orchestration.context_monitor import (
                    summarize_tool_results,
                )

                log.info(
                    "Context ceiling: %d tokens > %dK ceiling (%.0f%% of %dK window) "
                    "— compressing to avoid rate limit pool separation",
                    metrics.estimated_tokens,
                    metrics.policy.absolute_ceiling_tokens // 1000
                    if metrics.policy
                    else ABSOLUTE_TOKEN_CEILING // 1000,
                    metrics.usage_pct,
                    metrics.context_window // 1000,
                )

                # Phase 1: summarize large tool results
                summarized, _tok_before, _tok_after = summarize_tool_results(
                    messages,
                    metrics.policy or ABSOLUTE_TOKEN_CEILING,
                )
                post = check_context(messages, model, system_prompt=system)

                if post.is_ceiling_exceeded:
                    # Phase 2: compact conversation
                    keep_recent = (
                        post.policy.resolve_keep_recent(settings.compact_keep_recent)
                        if post.policy
                        else settings.compact_keep_recent
                    )
                    strategy = {
                        "strategy": "compact",
                        "keep_recent": keep_recent,
                        "policy": post.policy,
                        "trigger": "ceiling",
                    }
                    await self._apply_overflow_strategy(
                        strategy, messages, settings, model, provider
                    )

        except Exception as exc:
            from core.agent.loop import _ContextExhaustedError

            if isinstance(exc, _ContextExhaustedError):
                raise
            log.debug("Context monitor check failed", exc_info=True)

    async def _apply_overflow_strategy(
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
            from core.orchestration.compaction import compact_conversation

            try:
                session_id = self._session_id_provider() if self._session_id_provider else None
                new_msgs, did_compact = await compact_conversation(
                    messages,
                    provider=provider,
                    model=model,
                    keep_recent=keep_recent,
                    policy=strategy.get("policy"),
                    session_id=session_id,
                    trigger=strategy.get("trigger", "overflow"),
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
                from core.orchestration.compaction import repair_tool_pairs

                messages.clear()
                messages.extend(repair_tool_pairs(pruned))
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

    async def aggressive_context_recovery(
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
            metrics = check_context(messages, model, system_prompt=system)
            summarized, _tok_before, _tok_after = summarize_tool_results(
                messages,
                metrics.policy or metrics.context_window,
            )
            if summarized > 0:
                log.info("Aggressive recovery: summarized %d tool results", summarized)

            # Check if summarization alone resolved it
            post = check_context(messages, model, system_prompt=system)
            if not post.is_critical:
                return original_count - len(messages) + summarized

            # Phase 2: delegate to CONTEXT_OVERFLOW_ACTION hook for strategy
            strategy = await self._resolve_overflow_strategy(post, settings, model, provider)

            aggressive_keep = (
                post.policy.resolve_aggressive_keep_recent(settings.compact_keep_recent)
                if post.policy
                else max(3, settings.compact_keep_recent // 2)
            )
            strategy["keep_recent"] = aggressive_keep

            # Force prune if hook returned "none" — aggressive recovery must act
            if strategy.get("strategy") == "none":
                strategy["strategy"] = "prune"

            await self._apply_overflow_strategy(strategy, messages, settings, model, provider)

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
            from core.ui.agentic_ui import render_context_event

            render_context_event(event_type, original_count=original_count, new_count=new_count)
        except Exception:
            log.debug("Context event notification failed", exc_info=True)

    async def _resolve_overflow_strategy(
        self, metrics: Any, settings: Any, model: str, provider: str
    ) -> dict[str, Any]:
        """Ask CONTEXT_OVERFLOW_ACTION hook for compression strategy, with fallback."""
        if self._hooks:
            results = await self._hooks.trigger_with_result_async(
                HookEvent.CONTEXT_OVERFLOW_ACTION,
                {
                    "metrics": dataclasses.asdict(metrics),
                    "model": model,
                    "provider": provider,
                },
            )
            for result in results:
                if result.success and result.data.get("strategy"):
                    result.data.setdefault("policy", getattr(metrics, "policy", None))
                    result.data.setdefault("trigger", "overflow_hook")
                    return result.data

        policy = getattr(metrics, "policy", None)
        if policy is None:
            policy = resolve_context_budget_policy(
                model,
                context_window=getattr(metrics, "context_window", None),
            )
        keep_recent = (
            policy.resolve_keep_recent(settings.compact_keep_recent)
            if policy is not None
            else settings.compact_keep_recent
        )
        estimated_tokens = getattr(metrics, "estimated_tokens", None)
        if estimated_tokens is None:
            estimated_tokens = int(getattr(metrics, "usage_pct", 0.0) / 100 * policy.context_window)
        is_critical = bool(
            getattr(metrics, "is_critical", estimated_tokens >= policy.critical_tokens)
        )
        is_warning = bool(getattr(metrics, "is_warning", estimated_tokens >= policy.warning_tokens))
        if provider == "anthropic":
            if is_critical:
                return {
                    "strategy": "prune",
                    "keep_recent": keep_recent,
                    "policy": policy,
                    "trigger": "critical",
                }
            return {"strategy": "none", "policy": policy, "trigger": "warning"}

        if is_critical:
            return {
                "strategy": "compact",
                "keep_recent": keep_recent,
                "policy": policy,
                "trigger": "critical",
            }
        elif is_warning:
            return {
                "strategy": "compact",
                "keep_recent": keep_recent,
                "policy": policy,
                "trigger": "warning",
            }
        return {"strategy": "none", "policy": policy, "trigger": "ok"}

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
