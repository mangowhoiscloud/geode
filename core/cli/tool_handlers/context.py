"""Context management tool handler — manage_context (status/compact/prune/clear)."""

from __future__ import annotations

from typing import Any, Literal

from core.tools.handlers.registration import UniqueEntries


def _build_context_handlers() -> UniqueEntries[str, Any]:
    """Build context management tool handlers (manage_context)."""

    async def handle_manage_context(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "status")
        force = kwargs.get("force", False)

        from core.cli.commands import get_conversation_context
        from core.config import settings
        from core.orchestration.context_monitor import check_context

        tool_context = kwargs.get("_tool_context")
        loop = tool_context.agent_loop if tool_context is not None else None
        ctx = loop.context if loop is not None else get_conversation_context()
        if ctx is None:
            return {"error": "No active conversation context"}
        turn = loop._turn_state if loop is not None else None
        # The active turn is a deep copy. Mutating only session history here
        # would be overwritten when the completed tool batch is checkpointed.
        messages = turn.messages if turn is not None else ctx.messages
        model = loop.model if loop is not None else settings.model

        if action == "status":
            if not messages:
                return {
                    "status": "ok",
                    "action": "status",
                    "messages": 0,
                    "estimated_tokens": 0,
                }
            metrics = check_context(messages, model)
            return {
                "status": "ok",
                "action": "status",
                "messages": len(messages),
                "estimated_tokens": metrics.estimated_tokens,
                "context_window": metrics.context_window,
                "usage_pct": round(metrics.usage_pct, 1),
                "model": model,
            }
        elif action in {"compact", "prune"}:
            from dataclasses import asdict

            from core.agent.context_manager import ContextOperationResult
            from core.ui.agentic_ui import render_context_event

            # Keep the shipped compact(force=true) spelling as an explicit
            # prune alias; the canonical action now states that intent.
            prune = action == "prune" or bool(force)
            operation: Literal["compact", "prune"] = "prune" if prune else "compact"
            if loop is None:
                result = ContextOperationResult(
                    operation, "unsupported", len(messages), len(messages), "runtime_unavailable"
                )
            else:
                result = await loop._ctx_mgr.compact(
                    messages,
                    model,
                    loop._provider,
                    prune=prune,
                    keep_recent=2 if prune else None,
                    trigger="tool",
                )
            render_context_event(
                result.action,
                original_count=result.original_count,
                new_count=result.new_count,
                status=result.status,
                trigger="tool",
                error_type=result.error_type,
            )
            response = asdict(result)
            if result.status == "failed":
                response["error"] = result.error_type or "context_operation_failed"
            return response
        elif action == "clear":
            if not force:
                return {
                    "status": "confirmation_needed",
                    "action": "clear",
                    "summary": (
                        f"대화 기록 {len(ctx.messages)}개 "
                        "메시지를 삭제합니다. "
                        "force=true로 확인하세요."
                    ),
                    "messages_count": len(ctx.messages),
                }
            ctx.clear()
            return {"status": "ok", "action": "cleared"}

        return {"error": f"Unknown action: {action}"}

    return UniqueEntries[str, Any]((("manage_context", handle_manage_context),))
