"""Context window management — extracted from AgenticLoop for SRP.

Handles context overflow detection, message pruning, compaction,
aggressive recovery, and strategy resolution.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from typing import Any, Literal

from core.agent.cognitive_state_ctx import get_turn_id
from core.hooks import (
    HookAction,
    HookCorrelation,
    HookName,
    HookRegistry,
    RuntimeEvent,
    RuntimeEventBus,
)
from core.orchestration.context_budget import (
    ABSOLUTE_TOKEN_CEILING,
    ContextBudgetPolicy,
    resolve_context_budget_policy,
)

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class ContextOperationResult:
    action: Literal["compact", "prune", "none"]
    status: Literal["changed", "unchanged", "deferred", "failed", "unsupported"]
    original_count: int
    new_count: int
    error_type: str = ""


class ContextWindowManager:
    """Manages context window overflow detection and compression.

    Extracted from AgenticLoop to isolate context budget concerns.
    Uses composition: AgenticLoop creates and owns this instance.
    """

    def __init__(
        self,
        *,
        hooks: RuntimeEventBus | None,
        hook_registry: HookRegistry | None = None,
        quiet: bool,
        session_id_provider: Callable[[], str | None] | None = None,
        effort_provider: Callable[[], str] | None = None,
        source_provider: Callable[[], str] | None = None,
    ) -> None:
        self._hooks = hooks
        self._hook_registry = hook_registry
        self._quiet = quiet
        # Late-bound: the loop's session_id is assigned after construction, so
        # compaction resolves it at call time — without it the primary overflow
        # path never persists context_artifacts (writer-reader parity).
        self._session_id_provider = session_id_provider
        self._effort_provider = effort_provider
        self._source_provider = source_provider
        self._compacting = False

    async def compact(
        self,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
        *,
        prune: bool = False,
        keep_recent: int | None = None,
        trigger: str = "manual",
        commit: Callable[[], None] | None = None,
        policy: ContextBudgetPolicy | None = None,
    ) -> ContextOperationResult:
        """Run explicit summary or lossful pruning through the same runtime owner."""
        from core.config import settings

        policy = policy or resolve_context_budget_policy(
            model,
            provider=provider,
            source=self._source_provider() if self._source_provider else None,
        )
        return await self._apply_overflow_strategy(
            {
                "strategy": "prune" if prune else "compact",
                "keep_recent": keep_recent
                if keep_recent is not None
                else policy.resolve_keep_recent(settings.compact_keep_recent),
                "policy": policy,
                "trigger": trigger,
                "hard": prune,
                "notify": False,
            },
            messages,
            settings,
            model,
            provider,
            commit=commit,
        )

    async def check_context_overflow(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str,
        *,
        policy: ContextBudgetPolicy | None = None,
        tools_tokens: int | None = None,
    ) -> None:
        """Check context window usage and apply provider-aware compression.

        Strategy by provider:
        - Anthropic: server-side compaction handles warning-level pressure.
          Client only intervenes at the policy critical threshold.
        - OpenAI/GLM: GEODE uses client-side text compaction. It triggers LLM-based
          compaction at warning pressure and emergency prune at critical pressure.

        The early-maintenance ceiling is a local soft preference, not a
        provider input limit or permission to discard otherwise valid history.

        The domain policy chooses the compression strategy. Public PreCompact
        handlers may adjust bounded inputs or defer a soft compaction, but they
        cannot replace the policy at a hard safety boundary.
        """
        try:
            from core.config import settings
            from core.orchestration.context_monitor import ContextMetrics, check_context

            if self._compacting:
                from core.agent.loop import _ContextExhaustedError

                raise _ContextExhaustedError("Context compaction is already in progress")
            policy = policy or resolve_context_budget_policy(
                model,
                provider=provider,
                source=self._source_provider() if self._source_provider else None,
            )

            def measure() -> ContextMetrics:
                return check_context(
                    messages, model, system_prompt=system, tools_tokens=tools_tokens, policy=policy
                )

            metrics = measure()

            if metrics.is_critical:
                log.warning(
                    "Context CRITICAL: %.0f%% (%d/%d tokens) — emergency action",
                    metrics.usage_pct,
                    metrics.estimated_tokens,
                    metrics.context_window,
                )
                if self._hooks:
                    await self._hooks.trigger_async(
                        RuntimeEvent.CONTEXT_CRITICAL,
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
                metrics = measure()
                strategy = await self._resolve_overflow_strategy(metrics, settings, model, provider)
                strategy["hard"] = True
                strategy["source"] = policy.source
                outcome = await self._apply_overflow_strategy(
                    strategy, messages, settings, model, provider
                )

                # Re-check: if still critical after pruning, context is exhausted
                post = measure()
                if post.is_critical and outcome.status not in {"unsupported", "deferred"}:
                    pruned = adaptive_prune(
                        messages,
                        getattr(post, "policy", None) or post.context_window,
                    )
                    from core.orchestration.compaction import repair_tool_pairs

                    messages.clear()
                    messages.extend(repair_tool_pairs(pruned))
                    post = measure()

                if post.is_critical:
                    from core.agent.loop import _ContextExhaustedError

                    raise _ContextExhaustedError(
                        f"Context exhausted: {post.usage_pct:.0f}% after maintenance",
                        policy=policy,
                        system_prompt=system,
                        tools_tokens=tools_tokens,
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
                metrics = measure()
                strategy = await self._resolve_overflow_strategy(metrics, settings, model, provider)
                strategy["source"] = policy.source
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
                    "— attempting soft local maintenance",
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
                post = measure()

                if post.is_ceiling_exceeded:
                    # The route policy also owns soft maintenance; native
                    # compaction must not acquire a second client-side path.
                    strategy = await self._resolve_overflow_strategy(
                        post, settings, model, provider
                    )
                    strategy.update(trigger="ceiling", hard=False, source=policy.source)
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
        *,
        commit: Callable[[], None] | None = None,
    ) -> ContextOperationResult:
        """Execute the overflow strategy (prune or compact)."""
        from core.orchestration.context_monitor import prune_oldest_messages

        action = strategy.get("strategy", "none")
        keep_recent = strategy.get("keep_recent", settings.compact_keep_recent)
        original_count = len(messages)
        trigger = strategy.get("trigger", "overflow")

        def replace_messages(replacement: list[dict[str, Any]]) -> None:
            original = list(messages)
            messages[:] = replacement
            try:
                if commit is not None:
                    commit()
            except BaseException:
                messages[:] = original
                raise

        def finish(
            action: Literal["compact", "prune", "none"],
            status: Literal["changed", "unchanged", "deferred", "failed", "unsupported"],
            error_type: str = "",
        ) -> ContextOperationResult:
            result = ContextOperationResult(
                action, status, original_count, len(messages), error_type
            )
            if action != "none" and strategy.get("notify", True):
                self._notify_context_event(
                    action,
                    original_count=original_count,
                    new_count=len(messages),
                    status=status,
                    trigger=trigger,
                    error_type=error_type,
                )
            return result

        from core.orchestration.compaction import (
            StaleCompactionError,
            can_compact_conversation,
            compact_conversation,
        )

        if action in {"compact", "prune"} and not can_compact_conversation(
            messages, provider=provider, model=model
        ):
            return finish(action, "unsupported")

        if action == "compact":
            if self._compacting:
                return finish("compact", "deferred")
            self._compacting = True
            try:
                session_id = self._session_id_provider() if self._session_id_provider else None
                correlation = HookCorrelation(
                    session_id=session_id or "",
                    turn_id=get_turn_id(),
                )
                if self._hook_registry is not None:
                    pre_compact = await self._hook_registry.invoke(
                        HookName.PRE_COMPACT,
                        payload={
                            "model": model,
                            "provider": provider,
                            "message_count": len(messages),
                            "keep_recent": keep_recent,
                            "trigger": strategy.get("trigger", "overflow"),
                            "hard": bool(strategy.get("hard", False)),
                        },
                        correlation=correlation,
                    )
                    effective_keep = pre_compact.invocation.payload.get("keep_recent")
                    if isinstance(effective_keep, int) and not isinstance(effective_keep, bool):
                        keep_recent = max(1, min(effective_keep, 1_000))
                    deferred = any(
                        decision.action is HookAction.DEFER for decision in pre_compact.decisions
                    )
                    if deferred and not strategy.get("hard", False):
                        log.info("Soft context compaction deferred by PreCompact")
                        return finish("compact", "deferred")
                new_msgs, did_compact = await compact_conversation(
                    messages,
                    provider=provider,
                    model=model,
                    effort=self._effort_provider() if self._effort_provider else None,
                    source=(
                        strategy["source"]
                        if strategy.get("source")
                        else self._source_provider()
                        if self._source_provider
                        else None
                    ),
                    keep_recent=keep_recent,
                    policy=strategy.get("policy"),
                    session_id=session_id,
                    trigger=strategy.get("trigger", "overflow"),
                    hooks=self._hooks,
                    correlation=dataclasses.asdict(correlation),
                )
                if did_compact:
                    try:
                        replace_messages(new_msgs)
                    except Exception as exc:
                        log.warning("Compaction commit failed", exc_info=True)
                        return finish("compact", "failed", type(exc).__name__)
                    if self._hook_registry is not None:
                        try:
                            await self._hook_registry.invoke(
                                HookName.POST_COMPACT,
                                payload={
                                    "model": model,
                                    "provider": provider,
                                    "original_message_count": original_count,
                                    "new_message_count": len(new_msgs),
                                    "keep_recent": keep_recent,
                                    "trigger": strategy.get("trigger", "overflow"),
                                    "persisted": bool(session_id),
                                },
                                correlation=correlation,
                            )
                        except Exception:
                            # Observation cannot undo or prune a committed summary.
                            log.warning("PostCompact notification failed", exc_info=True)
                    return finish("compact", "changed")
            except StaleCompactionError as exc:
                return finish("compact", "deferred", type(exc).__name__)
            except Exception as exc:
                log.warning("Client compaction failed", exc_info=True)
                if not strategy.get("hard", False):
                    return finish("compact", "failed", type(exc).__name__)
            finally:
                self._compacting = False
            # Soft maintenance must not turn a failed summary or durable write
            # into irreversible history loss. Only an explicit hard boundary
            # permits the emergency prune fallback.
            if not strategy.get("hard", False):
                return finish("compact", "unchanged")
            action = "prune"

        if action == "prune":
            # Expand the retained tail to keep parallel call/result pairs intact.
            from core.orchestration.compaction import find_safe_boundary, repair_tool_pairs

            boundary = find_safe_boundary(messages, keep_recent=keep_recent)
            keep_recent = len(messages) - boundary
            pruned = prune_oldest_messages(messages, keep_recent=keep_recent)
            if len(pruned) < original_count:
                try:
                    replace_messages(repair_tool_pairs(pruned))
                except Exception as exc:
                    log.warning("Context prune commit failed", exc_info=True)
                    return finish("prune", "failed", type(exc).__name__)
                log.info(
                    "Emergency pruned: %d → %d messages (keep_recent=%d)",
                    original_count,
                    len(pruned),
                    keep_recent,
                )
                return finish("prune", "changed")
            return finish("prune", "unchanged")
        return finish("none", "unchanged")

    async def aggressive_context_recovery(
        self,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        provider: str = "anthropic",
        *,
        provider_rejected: bool = False,
        policy: ContextBudgetPolicy | None = None,
        tools_tokens: int | None = None,
    ) -> ContextOperationResult:
        """Produce a smaller retry candidate without claiming server acceptance.

        A confirmed input rejection overrides local size estimates. Message
        count is diagnostic: an equal-count summary can still reduce input.
        """
        from core.config import settings
        from core.orchestration.context_monitor import (
            ContextMetrics,
            check_context,
            summarize_tool_results,
        )

        original_count = len(messages)
        if self._compacting:
            return ContextOperationResult("compact", "deferred", original_count, original_count)
        policy = policy or resolve_context_budget_policy(
            model,
            provider=provider,
            source=self._source_provider() if self._source_provider else None,
        )

        def measure() -> ContextMetrics:
            return check_context(
                messages, model, system_prompt=system, tools_tokens=tools_tokens, policy=policy
            )

        before = measure()
        summarize_tool_results(messages, policy)
        post = measure()
        if post.estimated_tokens < before.estimated_tokens and not post.is_critical:
            return ContextOperationResult("none", "changed", original_count, len(messages))
        if not provider_rejected and not post.is_critical:
            return ContextOperationResult("none", "unchanged", original_count, len(messages))

        strategy = await self._resolve_overflow_strategy(post, settings, model, provider)
        strategy.update(
            keep_recent=policy.resolve_aggressive_keep_recent(settings.compact_keep_recent),
            hard=True,
            trigger="provider_overflow" if provider_rejected else "recovery",
            source=policy.source,
        )
        if provider_rejected or strategy.get("strategy") == "none":
            strategy["strategy"] = "compact"
        outcome = await self._apply_overflow_strategy(strategy, messages, settings, model, provider)
        if outcome.status != "changed":
            return outcome
        if measure().estimated_tokens < before.estimated_tokens:
            return outcome
        return ContextOperationResult(outcome.action, "unchanged", original_count, len(messages))

    def _notify_context_event(
        self,
        event_type: str,
        *,
        original_count: int,
        new_count: int,
        status: str = "changed",
        trigger: str = "overflow",
        error_type: str = "",
    ) -> None:
        """Notify user of automatic context compression via UI."""
        if self._quiet:
            return
        try:
            from core.ui.agentic_ui import render_context_event

            render_context_event(
                event_type,
                original_count=original_count,
                new_count=new_count,
                status=status,
                trigger=trigger,
                error_type=error_type,
            )
        except Exception:
            log.debug("Context event notification failed", exc_info=True)

    async def _resolve_overflow_strategy(
        self, metrics: Any, settings: Any, model: str, provider: str
    ) -> dict[str, Any]:
        """Resolve the provider-aware domain policy for context pressure."""
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
        from core.llm.model_capabilities import get_anthropic_model_spec

        native = get_anthropic_model_spec(model) if provider == "anthropic" else None
        if native is not None and native.compaction:
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
        elif is_warning or bool(getattr(metrics, "is_ceiling_exceeded", False)):
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
