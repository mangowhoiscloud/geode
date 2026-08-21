"""Planning tool handlers.

``update_plan`` is the Codex-style progress surface: it replaces the
current visible checklist for this turn and never waits for approval.
``create_plan`` / ``approve_plan`` remain for explicit review checkpoints.

The disk-persistent ``PlanStore`` singleton (`_PLAN_STORE`) lives at the
package level (``core.cli.tool_handlers.__init__``) so test fixtures can
``monkeypatch.setattr(th, "_PLAN_STORE", ...)`` without reaching into a
sub-module. The package's ``_get_plan_store()`` accessor is what
``_build_plan_handlers`` calls.
"""

from __future__ import annotations

import logging
from typing import Any

from core.tools.handlers.clarification import _clarify
from core.tools.handlers.registration import UniqueEntries
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_plan_handlers() -> UniqueEntries[str, Any]:
    """Build plan mode tool handlers (multi-plan store keyed by plan_id)."""
    from core.cli.tool_handlers import _get_plan_store

    store = _get_plan_store()

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
                        "Invalid plan status: "
                        f"{status}. Expected pending, in_progress, or completed."
                    )
                }
            cleaned.append({"step": step, "status": status})
            counts[status] += 1

        if not cleaned:
            return _clarify("update_plan", ["plan"], "비어 있지 않은 진행 항목이 필요합니다.")

        rank = {"completed": 0, "in_progress": 1, "pending": 2}
        status_ranks = [rank[item["status"]] for item in cleaned]
        has_linear_progress = (
            counts["in_progress"] <= 1
            and (counts["pending"] + counts["in_progress"] == 0 or counts["in_progress"] == 1)
            and status_ranks == sorted(status_ranks)
        )

        runtime_plan_synced = False
        runtime_plan_advanced = False
        runtime_plan_current: int | None = None
        runtime_plan_id = ""
        runtime_plan_revision: int | None = None
        runtime_plan_done = False
        try:
            from core.agent.plan import Plan
            from core.observability.session_metrics import current_session_metrics
            from core.observability.session_timeline import (
                SessionEventKind,
                current_session_timeline,
            )

            metrics = current_session_metrics()
            active_plan = metrics.active_plan
            if isinstance(active_plan, Plan):
                remaining = active_plan.remaining_steps()
                submitted = [item["step"] for item in cleaned]
                remaining_texts = (
                    [step.description for step in remaining],
                    [f"{step.id}: {step.description}" for step in remaining],
                )
                full_texts = (
                    [step.description for step in active_plan.steps],
                    [f"{step.id}: {step.description}" for step in active_plan.steps],
                )
                completed_prefix = next(
                    (index for index, item in enumerate(cleaned) if item["status"] != "completed"),
                    len(cleaned),
                )
                advance_count: int | None = None
                if has_linear_progress and submitted in remaining_texts:
                    advance_count = completed_prefix
                elif (
                    has_linear_progress
                    and not active_plan.abandoned
                    and submitted in full_texts
                    and completed_prefix >= active_plan.current
                ):
                    advance_count = completed_prefix - active_plan.current
                if advance_count is not None:
                    updated = active_plan.complete_and_advance(advance_count)
                    runtime_plan_advanced = updated.current != active_plan.current
                    if runtime_plan_advanced:
                        metrics.set_active_plan(updated, reset_attempts=True)
                        timeline = current_session_timeline()
                        if timeline is not None:
                            changed = tuple(
                                step.id
                                for step in active_plan.steps[active_plan.current : updated.current]
                            )
                            timeline.record_plan_state(
                                SessionEventKind.PLAN_COMPLETED
                                if updated.done
                                else SessionEventKind.PLAN_PROGRESSED,
                                updated,
                                trigger="update_plan",
                                changed_step_ids=changed,
                            )
                    runtime_plan_current = updated.current
                    runtime_plan_id = updated.plan_id
                    runtime_plan_revision = updated.revision
                    runtime_plan_done = updated.done
                    runtime_plan_synced = True
        except Exception:
            log.debug("Runtime advisory plan progress sync skipped", exc_info=True)

        from core.ui.agentic_ui import render_progress_plan

        render_progress_plan(cleaned, explanation=explanation)

        log.info(
            "Progress plan updated: total=%d pending=%d in_progress=%d completed=%d",
            len(cleaned),
            counts["pending"],
            counts["in_progress"],
            counts["completed"],
        )
        return {
            "status": "ok",
            "action": "update_plan",
            "plan": cleaned,
            "counts": counts,
            "runtime_plan_synced": runtime_plan_synced,
            "runtime_plan_advanced": runtime_plan_advanced,
            "runtime_plan_current": runtime_plan_current,
            "runtime_plan_id": runtime_plan_id,
            "runtime_plan_revision": runtime_plan_revision,
            "runtime_plan_done": runtime_plan_done,
            "hint": "Progress plan updated. Continue with the task; no approval is required.",
        }

    def _resolve_plan(plan_id: str) -> Any | None:
        """Resolve plan by ID, falling back to most recent."""
        plan = store.get(plan_id) if plan_id else None
        if plan is None:
            keys = store.keys()
            if keys:
                last_key = keys[-1]
                plan = store.get(last_key)
                if plan is not None:
                    log.debug(
                        "Plan ID '%s' not found, using latest '%s'",
                        plan_id,
                        last_key,
                    )
        return plan

    def handle_create_plan(**kwargs: Any) -> dict[str, Any]:
        goal = kwargs.get("goal", "")
        subject = kwargs.get("subject") or kwargs.get("subject_id", "")
        custom_steps = kwargs.get("steps", [])
        plan_summary: dict[str, Any] = {}

        if goal or subject:
            import uuid

            from core.orchestration.plan_mode import AnalysisPlan, PlanMode, PlanStep

            template = "agentic"
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            plan_title = subject or goal
            if custom_steps:
                steps = [
                    PlanStep(
                        step_id=f"step_{i}",
                        description=desc,
                        node_name="agentic",
                        estimated_time_s=10.0,
                    )
                    for i, desc in enumerate(custom_steps, 1)
                ]
            else:
                steps = [
                    PlanStep(
                        step_id="step_1",
                        description=goal or plan_title,
                        node_name="agentic",
                        estimated_time_s=30.0,
                    )
                ]
            plan = AnalysisPlan(plan_id=plan_id, subject_id=plan_title, steps=steps)
            PlanMode().present_plan(plan)
            plan_summary = {"goal": goal or plan_title, "steps": len(steps)}
        else:
            return _clarify("create_plan", ["goal"], "어떤 작업의 계획을 세울까요?")

        # Display review checkpoint steps. Routine progress should use
        # update_plan; this path is for explicit approval checkpoints.
        console.print()
        console.print(f"  [header]● Plan: {plan_title}[/header]")
        console.print()
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    [bold]{i}.[/bold] {step.description}")
        console.print()
        console.print(
            f"  [muted]예상: {plan.total_estimated_time_s:.0f}s · "
            f"{plan.step_count} 단계 · plan_id={plan.plan_id}[/muted]"
        )
        console.print("  [dim]→ 승인 checkpoint: approve_plan · modify_plan · reject_plan[/dim]")
        console.print()
        log.info(
            "Plan '%s' created for '%s' (%d steps)",
            plan.plan_id,
            plan_title,
            plan.step_count,
        )

        # Persist the review checkpoint. Approval records authority only; the
        # AgenticLoop remains the sole owner of tool execution.
        store.put(plan)
        log.info(
            "PlanStore write: plan_id=%s len=%d",
            plan.plan_id,
            len(store),
        )
        return {
            "status": "ok",
            "action": "plan",
            "plan_id": plan.plan_id,
            "subject": plan.subject_id,
            "template": template,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
            "summary": plan_summary,
            "checkpoint_status": plan.status.value,
            "approved": False,
            "executed": False,
            "hint": (
                "Review checkpoint created. Use approve_plan, reject_plan, "
                "or modify_plan only if the user explicitly wants this gate."
            ),
        }

    def handle_approve_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        plan = _resolve_plan(plan_id)
        if plan is None:
            return {"error": "No plan to approve. Use create_plan first."}

        if plan_id and plan.plan_id != plan_id:
            return {"error": (f"Plan ID mismatch: expected {plan.plan_id}, got {plan_id}")}

        from core.orchestration.plan_mode import PlanMode

        planner = PlanMode()
        planner.approve_plan(plan)
        store.put(plan)

        subject = plan.subject_id
        console.print(f"  [success]✓ Plan approved: {subject}[/success]")
        console.print()
        log.info("Plan '%s' approved for '%s'", plan.plan_id, subject)
        return {
            "status": "ok",
            "action": "approve_plan",
            "plan_id": plan.plan_id,
            "checkpoint_status": plan.status.value,
            "approved": True,
            "executed": False,
            "hint": (
                f"Plan approved for {subject}. Approval does not execute steps; "
                "continue through the agent loop and report observed progress with update_plan."
            ),
        }

    def handle_reject_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        reason = kwargs.get("reason", "")
        plan = _resolve_plan(plan_id)
        if plan is None:
            return {"error": "No plan to reject."}

        from core.orchestration.plan_mode import PlanMode

        planner = PlanMode()
        planner.reject_plan(plan, reason=reason)
        store.put(plan)
        console.print(f"  [warning]✗ Plan rejected: {plan.subject_id}[/warning]")
        log.info(
            "Plan '%s' rejected (reason=%s)",
            plan.plan_id,
            reason or "(none)",
        )
        return {
            "status": "ok",
            "action": "reject_plan",
            "plan_id": plan.plan_id,
            "reason": reason,
        }

    def handle_modify_plan(**kwargs: Any) -> dict[str, Any]:
        plan_id = kwargs.get("plan_id", "")
        plan = _resolve_plan(plan_id)
        if plan is None:
            return {"error": "No plan to modify."}

        template = kwargs.get("template")
        remove = kwargs.get("remove_steps")
        from core.orchestration.plan_mode import PlanMode

        planner = PlanMode()
        planner.modify_plan(
            plan,
            template=template,
            remove_steps=remove,
        )
        store.put(plan)
        console.print(f"  [header]● Plan modified: {plan.subject_id}[/header]")
        for i, step in enumerate(plan.steps, 1):
            console.print(f"    {i}. {step.description}")
        console.print()
        log.info(
            "Plan '%s' modified (%d steps)",
            plan.plan_id,
            plan.step_count,
        )
        return {
            "status": "ok",
            "action": "modify_plan",
            "plan_id": plan.plan_id,
            "step_count": plan.step_count,
            "steps": [s.description for s in plan.steps],
        }

    def handle_list_plans(**kwargs: Any) -> dict[str, Any]:
        all_plans = store.list_all()
        log.info("PlanStore read (list_plans): len=%d", len(all_plans))
        status_filter = str(kwargs.get("status", "")).strip().lower()
        plans = []
        for plan in all_plans:
            if status_filter and plan.status.value != status_filter:
                continue
            plans.append(
                {
                    "plan_id": plan.plan_id,
                    "subject_id": plan.subject_id,
                    "status": plan.status.value,
                    "steps": plan.step_count,
                }
            )
        return {
            "status": "ok",
            "action": "list_plans",
            "count": len(plans),
            "plans": plans,
        }

    return UniqueEntries[str, Any](
        (
            ("update_plan", handle_update_plan),
            ("create_plan", handle_create_plan),
            ("approve_plan", handle_approve_plan),
            ("reject_plan", handle_reject_plan),
            ("modify_plan", handle_modify_plan),
            ("list_plans", handle_list_plans),
        )
    )
