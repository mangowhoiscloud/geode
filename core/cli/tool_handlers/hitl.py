"""Result-feedback tool handlers: rate/accept/reject_result.

The feedback handlers persist a model-reported verdict by firing
``HookEvent.RESULT_FEEDBACK``, which the canonical SQLite event sink
persists for indexed history. The event is correlated to the physical tool
call, but it is not proof that a human directly authored the verdict.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.dispatch import fire_hook
from core.hooks.system import HookEvent
from core.tools.handlers.clarification import _clarify
from core.tools.handlers.registration import UniqueEntries
from core.ui.console import console

log = logging.getLogger(__name__)


def _feedback_correlation(kwargs: dict[str, Any]) -> dict[str, str]:
    """Return non-empty session/turn/call keys for the active tool dispatch."""
    from core.agent.cognitive_state_ctx import (
        get_session_id,
        get_tool_call_id,
        get_turn_id,
    )

    context = kwargs.get("_tool_context")
    values = {
        "session_id": str(getattr(context, "session_id", "") or get_session_id()),
        "turn_id": get_turn_id(),
        "tool_call_id": str(getattr(context, "tool_call_id", "") or get_tool_call_id()),
    }
    return {key: value for key, value in values.items() if value}


def _build_hitl_handlers(hooks: Any = None) -> UniqueEntries[str, Any]:
    """Build HITL feedback tool handlers."""

    def handle_rate_result(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject") or kwargs.get("subject_id") or ""
        rating = kwargs.get("rating", 0)
        if not subject:
            return _clarify("rate_result", ["subject"], "어떤 대상에 평점을 매길까요?")
        if not (1 <= rating <= 5):
            return _clarify("rate_result", ["rating"], "평점은 1-5 사이로 입력해주세요.")
        comment = kwargs.get("comment", "")
        fire_hook(
            hooks,
            HookEvent.RESULT_FEEDBACK,
            {
                "subject": subject,
                "verdict": "rated",
                "rating": rating,
                "comment": comment,
                **_feedback_correlation(kwargs),
            },
        )
        console.print(f"  [success]✓ Rating saved for {subject}: {rating}/5[/success]")
        log.info("HITL rating recorded: subject_chars=%d rating=%d", len(str(subject)), rating)
        return {
            "status": "ok",
            "action": "rate_result",
            "subject": subject,
            "rating": rating,
        }

    def handle_accept_result(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject") or kwargs.get("subject_id") or ""
        if not subject:
            return _clarify("accept_result", ["subject"], "어떤 결과를 수락할까요?")
        fire_hook(
            hooks,
            HookEvent.RESULT_FEEDBACK,
            {"subject": subject, "verdict": "accepted", **_feedback_correlation(kwargs)},
        )
        console.print(f"  [success]✓ Result accepted: {subject}[/success]")
        log.info("HITL acceptance recorded: subject_chars=%d", len(str(subject)))
        return {
            "status": "ok",
            "action": "accept_result",
            "subject": subject,
        }

    def handle_reject_result(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject") or kwargs.get("subject_id") or ""
        if not subject:
            return _clarify("reject_result", ["subject"], "어떤 결과를 거부할까요?")
        reason = kwargs.get("reason", "")
        fire_hook(
            hooks,
            HookEvent.RESULT_FEEDBACK,
            {
                "subject": subject,
                "verdict": "rejected",
                "reason": reason,
                **_feedback_correlation(kwargs),
            },
        )
        console.print(f"  [warning]✗ Result rejected: {subject}[/warning]")
        log.info(
            "HITL rejection recorded: subject_chars=%d reason_chars=%d",
            len(str(subject)),
            len(str(reason)),
        )
        return {
            "status": "ok",
            "action": "reject_result",
            "subject": subject,
            "reason": reason,
        }

    return UniqueEntries[str, Any](
        (
            ("rate_result", handle_rate_result),
            ("accept_result", handle_accept_result),
            ("reject_result", handle_reject_result),
        )
    )
