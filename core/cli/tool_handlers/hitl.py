"""HITL (Human-in-the-Loop) tool handlers: rate/accept/reject_result, rerun_node."""

from __future__ import annotations

import logging
from typing import Any

from core.cli.tool_handlers._helpers import _clarify
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_hitl_handlers() -> dict[str, Any]:
    """Build HITL feedback tool handlers."""

    _human_ratings: dict[str, dict[str, Any]] = {}
    _result_feedback: dict[str, str] = {}

    def handle_rate_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        rating = kwargs.get("rating", 0)
        if not ip_name:
            return _clarify("rate_result", ["ip_name"], "어떤 IP에 평점을 매길까요?")
        if not (1 <= rating <= 5):
            return _clarify("rate_result", ["rating"], "평점은 1-5 사이로 입력해주세요.")
        comment = kwargs.get("comment", "")
        _human_ratings[ip_name] = {
            "rating": rating,
            "comment": comment,
        }
        console.print(f"  [success]✓ Rating saved for {ip_name}: {rating}/5[/success]")
        log.info(
            "HITL rating: %s = %d/5",
            ip_name,
            rating,
        )
        return {
            "status": "ok",
            "action": "rate_result",
            "ip_name": ip_name,
            "rating": rating,
        }

    def handle_accept_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("accept_result", ["ip_name"], "어떤 IP 결과를 수락할까요?")
        _result_feedback[ip_name] = "accepted"
        console.print(f"  [success]✓ Result accepted: {ip_name}[/success]")
        log.info("HITL accept: %s", ip_name)
        return {
            "status": "ok",
            "action": "accept_result",
            "ip_name": ip_name,
        }

    def handle_reject_result(**kwargs: Any) -> dict[str, Any]:
        ip_name = kwargs.get("ip_name", "")
        if not ip_name:
            return _clarify("reject_result", ["ip_name"], "어떤 IP 결과를 거부할까요?")
        reason = kwargs.get("reason", "")
        _result_feedback[ip_name] = "rejected"
        console.print(f"  [warning]✗ Result rejected: {ip_name}[/warning]")
        log.info(
            "HITL reject: %s (reason=%s)",
            ip_name,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_result",
            "ip_name": ip_name,
            "reason": reason,
            "hint": ("Use rerun_node to re-execute specific pipeline steps."),
        }

    def handle_rerun_node(**kwargs: Any) -> dict[str, Any]:
        node_name = kwargs.get("node_name", "")
        ip_name = kwargs.get("ip_name", "")
        if not node_name or not ip_name:
            missing = [k for k, v in {"node_name": node_name, "ip_name": ip_name}.items() if not v]
            return _clarify("rerun_node", missing, "재실행할 노드와 IP를 알려주세요.")
        # Allowlist supplied by the active domain (DomainPort v2). Empty
        # set ⇒ no rerunnable nodes for non-pipeline domains.
        from core.domains.port import get_domain_or_none

        allowed: set[str] = set()
        domain = get_domain_or_none()
        if domain is not None:
            getter = getattr(domain, "get_rerunnable_nodes", None)
            if callable(getter):
                try:
                    allowed = set(getter())
                except Exception:
                    log.debug("get_rerunnable_nodes() failed", exc_info=True)
        if node_name not in allowed:
            return {
                "error": (f"Cannot rerun '{node_name}'. Allowed: {sorted(allowed)}"),
            }
        console.print(f"  [header]▸ Rerunning {node_name} for {ip_name}[/header]")
        log.info(
            "HITL rerun: %s for %s",
            node_name,
            ip_name,
        )
        return {
            "status": "ok",
            "action": "rerun_node",
            "node_name": node_name,
            "ip_name": ip_name,
            "hint": ("Node re-execution queued. Results will update in-place."),
        }

    return {
        "rate_result": handle_rate_result,
        "accept_result": handle_accept_result,
        "reject_result": handle_reject_result,
        "rerun_node": handle_rerun_node,
    }
