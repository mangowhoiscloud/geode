"""Codex-style advisory plan progress handler."""

from __future__ import annotations

import logging
from typing import Any

from core.tools.handlers.clarification import _clarify
from core.tools.handlers.registration import UniqueEntries

log = logging.getLogger(__name__)


def _build_plan_handlers() -> UniqueEntries[str, Any]:
    """Return the single non-executing plan progress surface."""

    def handle_update_plan(**kwargs: Any) -> dict[str, Any]:
        plan_items = kwargs.get("plan")
        if not isinstance(plan_items, list):
            return _clarify("update_plan", ["plan"], "진행 항목 목록을 알려주세요.")

        explanation = str(kwargs.get("explanation") or "").strip()
        cleaned: list[dict[str, str]] = []
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step") or "").strip()
            status = str(item.get("status") or "pending").strip()
            if not step:
                continue
            if status not in counts:
                return {
                    "error": (
                        f"Invalid plan status: {status}. Expected pending, "
                        "in_progress, or completed."
                    )
                }
            cleaned.append({"step": step, "status": status})
            counts[status] += 1

        if not cleaned:
            return _clarify("update_plan", ["plan"], "비어 있지 않은 진행 항목이 필요합니다.")

        rank = {"completed": 0, "in_progress": 1, "pending": 2}
        status_ranks = [rank[item["status"]] for item in cleaned]
        linear = (
            counts["in_progress"] <= 1
            and (counts["pending"] + counts["in_progress"] == 0 or counts["in_progress"] == 1)
            and status_ranks == sorted(status_ranks)
        )

        synced = False
        advanced = False
        current: int | None = None
        plan_id = ""
        revision: int | None = None
        done = False
        try:
            from core.agent.plan import Plan
            from core.observability.session_metrics import current_session_metrics
            from core.observability.session_timeline import (
                SessionEventKind,
                current_session_timeline,
            )

            metrics = current_session_metrics()
            active = metrics.active_plan
            if isinstance(active, Plan):
                submitted = [item["step"] for item in cleaned]
                remaining = active.remaining_steps()
                remaining_texts = (
                    [step.description for step in remaining],
                    [f"{step.id}: {step.description}" for step in remaining],
                )
                full_texts = (
                    [step.description for step in active.steps],
                    [f"{step.id}: {step.description}" for step in active.steps],
                )
                completed_prefix = next(
                    (index for index, item in enumerate(cleaned) if item["status"] != "completed"),
                    len(cleaned),
                )
                advance_count: int | None = None
                if linear and submitted in remaining_texts:
                    advance_count = completed_prefix
                elif (
                    linear
                    and not active.abandoned
                    and submitted in full_texts
                    and completed_prefix >= active.current
                ):
                    advance_count = completed_prefix - active.current
                if advance_count is not None:
                    updated = active.complete_and_advance(advance_count)
                    advanced = updated.current != active.current
                    if advanced:
                        metrics.set_active_plan(updated, reset_attempts=True)
                        timeline = current_session_timeline()
                        if timeline is not None:
                            changed = tuple(
                                step.id for step in active.steps[active.current : updated.current]
                            )
                            timeline.record_plan_state(
                                SessionEventKind.PLAN_COMPLETED
                                if updated.done
                                else SessionEventKind.PLAN_PROGRESSED,
                                updated,
                                trigger="update_plan",
                                changed_step_ids=changed,
                            )
                    current = updated.current
                    plan_id = updated.plan_id
                    revision = updated.revision
                    done = updated.done
                    synced = True
        except Exception:
            log.debug("Runtime advisory plan progress sync skipped", exc_info=True)

        from core.ui.agentic_ui import render_progress_plan

        render_progress_plan(cleaned, explanation=explanation)
        return {
            "status": "ok",
            "action": "update_plan",
            "plan": cleaned,
            "counts": counts,
            "runtime_plan_synced": synced,
            "runtime_plan_advanced": advanced,
            "runtime_plan_current": current,
            "runtime_plan_id": plan_id,
            "runtime_plan_revision": revision,
            "runtime_plan_done": done,
            "hint": "Progress plan updated. Continue with the task; no approval is required.",
        }

    return UniqueEntries[str, Any]((("update_plan", handle_update_plan),))
