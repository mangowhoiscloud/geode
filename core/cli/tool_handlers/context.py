"""Context management tool handler — manage_context (status/compact/clear)."""

from __future__ import annotations

from typing import Any


def _build_context_handlers() -> dict[str, Any]:
    """Build context management tool handlers (manage_context)."""

    def handle_manage_context(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "status")
        force = kwargs.get("force", False)

        from core.cli.commands import get_conversation_context
        from core.config import settings
        from core.orchestration.context_monitor import check_context

        ctx = get_conversation_context()
        if ctx is None:
            return {"error": "No active conversation context"}

        if action == "status":
            if not ctx.messages:
                return {
                    "status": "ok",
                    "action": "status",
                    "messages": 0,
                    "estimated_tokens": 0,
                }
            metrics = check_context(ctx.messages, settings.model)
            return {
                "status": "ok",
                "action": "status",
                "messages": len(ctx.messages),
                "estimated_tokens": metrics.estimated_tokens,
                "context_window": metrics.context_window,
                "usage_pct": round(metrics.usage_pct, 1),
                "model": settings.model,
            }
        elif action == "compact":
            from core.cli.commands import cmd_compact

            cmd_compact("--hard" if force else "")
            if ctx.messages:
                metrics = check_context(ctx.messages, settings.model)
                return {
                    "status": "ok",
                    "action": "compacted",
                    "messages_after": len(ctx.messages),
                    "estimated_tokens": metrics.estimated_tokens,
                    "usage_pct": round(metrics.usage_pct, 1),
                }
            return {
                "status": "ok",
                "action": "compacted",
                "messages_after": 0,
                "estimated_tokens": 0,
                "usage_pct": 0.0,
            }
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

    return {"manage_context": handle_manage_context}
