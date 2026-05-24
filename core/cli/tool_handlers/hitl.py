"""HITL (Human-in-the-Loop) tool handlers: rate/accept/reject_result, rerun_node."""

from __future__ import annotations

import logging
from typing import Any

from core.cli.tool_handlers.clarification import _clarify
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_hitl_handlers() -> dict[str, Any]:
    """Build HITL feedback tool handlers."""

    _human_ratings: dict[str, dict[str, Any]] = {}
    _result_feedback: dict[str, str] = {}

    def handle_rate_result(**kwargs: Any) -> dict[str, Any]:
        subject = kwargs.get("subject") or kwargs.get("subject_id") or ""
        rating = kwargs.get("rating", 0)
        if not subject:
            return _clarify("rate_result", ["subject"], "어떤 대상에 평점을 매길까요?")
        if not (1 <= rating <= 5):
            return _clarify("rate_result", ["rating"], "평점은 1-5 사이로 입력해주세요.")
        comment = kwargs.get("comment", "")
        _human_ratings[subject] = {
            "rating": rating,
            "comment": comment,
        }
        console.print(f"  [success]✓ Rating saved for {subject}: {rating}/5[/success]")
        log.info(
            "HITL rating: %s = %d/5",
            subject,
            rating,
        )
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
        _result_feedback[subject] = "accepted"
        console.print(f"  [success]✓ Result accepted: {subject}[/success]")
        log.info("HITL accept: %s", subject)
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
        _result_feedback[subject] = "rejected"
        console.print(f"  [warning]✗ Result rejected: {subject}[/warning]")
        log.info(
            "HITL reject: %s (reason=%s)",
            subject,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_result",
            "subject": subject,
            "reason": reason,
            "hint": ("Use rerun_node to re-execute specific pipeline steps."),
        }

    def handle_rerun_node(**kwargs: Any) -> dict[str, Any]:
        node_name = kwargs.get("node_name", "")
        subject = kwargs.get("subject") or kwargs.get("subject_id") or ""
        if not node_name or not subject:
            missing = [k for k, v in {"node_name": node_name, "subject": subject}.items() if not v]
            return _clarify("rerun_node", missing, "재실행할 노드와 대상을 알려주세요.")
        allowed: set[str] = set()
        if node_name not in allowed:
            return {
                "error": (f"Cannot rerun '{node_name}'. Allowed: {sorted(allowed)}"),
            }
        console.print(f"  [header]▸ Rerunning {node_name} for {subject}[/header]")
        log.info(
            "HITL rerun: %s for %s",
            node_name,
            subject,
        )
        return {
            "status": "ok",
            "action": "rerun_node",
            "node_name": node_name,
            "subject": subject,
            "hint": ("Node re-execution queued. Results will update in-place."),
        }

    return {
        "rate_result": handle_rate_result,
        "accept_result": handle_accept_result,
        "reject_result": handle_reject_result,
        "rerun_node": handle_rerun_node,
    }
