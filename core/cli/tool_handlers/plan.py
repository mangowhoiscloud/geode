"""Plan-mode tool handlers (create/approve/reject/modify/list).

The disk-persistent ``PlanStore`` singleton (`_PLAN_STORE`) lives at the
package level (``core.cli.tool_handlers.__init__``) so test fixtures can
``monkeypatch.setattr(th, "_PLAN_STORE", ...)`` without reaching into a
sub-module. The package's ``_get_plan_store()`` accessor is what
``_build_plan_handlers`` calls.
"""

from __future__ import annotations

import logging
from typing import Any

from core.cli.tool_handlers.clarification import _clarify
from core.ui.console import console

log = logging.getLogger(__name__)


def _build_plan_handlers(force_dry: bool) -> dict[str, Any]:
    """Build plan mode tool handlers (multi-plan store keyed by plan_id)."""
    from core.cli.tool_handlers import _get_plan_store

    store = _get_plan_store()

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
        # --dangerously-skip-permissions treats the plan-approval stop as just
        # another HITL gate: skip it and run the plan immediately (plan → action).
        # Per-session (ContextVar), same source the approval gates read.
        from core.agent.safety import current_skip_permissions
        from core.config import settings
        from core.orchestration.plan_mode import PlanExecutionMode, PlanMode

        auto_execute = settings.plan_auto_execute or current_skip_permissions()

        goal = kwargs.get("goal", "")
        subject = kwargs.get("subject") or kwargs.get("subject_id", "")
        custom_steps = kwargs.get("steps", [])
        plan_summary: dict[str, Any] = {}

        if goal or subject:
            import uuid

            from core.orchestration.plan_mode import AnalysisPlan, PlanStep

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
            planner = PlanMode()
            plan_summary = {"goal": goal or plan_title, "steps": len(steps)}
        else:
            return _clarify("create_plan", ["goal"], "어떤 작업의 계획을 세울까요?")

        # Display plan steps with HITL approval prompt
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
        if not auto_execute:
            console.print(
                "  [dim]→ 승인(approve_plan) · 수정(modify_plan) · 거부(reject_plan)[/dim]"
            )
        console.print()
        log.info(
            "Plan '%s' created for '%s' (%d steps)",
            plan.plan_id,
            plan_title,
            plan.step_count,
        )

        # AUTO mode: approve and execute immediately without user intervention
        if auto_execute:
            store.put(plan)
            log.info(
                "PlanStore write (AUTO): plan_id=%s len=%d",
                plan.plan_id,
                len(store),
            )
            console.print(f"  [bold cyan]▸ Auto-executing plan {plan.plan_id}[/bold cyan]")
            exec_result = planner.auto_execute_plan(plan)
            store.put(plan)

            completed = exec_result.get("completed_steps", 0)
            total = exec_result.get("total_steps", 0)
            failed = exec_result.get("failed_steps", [])

            if failed:
                console.print(
                    f"  [warning]Partial success: {completed}/{total} steps "
                    f"(failed: {', '.join(failed)})[/warning]"
                )
            else:
                console.print(f"  [success]✓ All {total} steps completed[/success]")
            console.print()

            return {
                "status": "ok",
                "action": "plan",
                "plan_id": plan.plan_id,
                "subject": plan.subject_id,
                "template": template,
                "step_count": plan.step_count,
                "steps": [s.description for s in plan.steps],
                "summary": plan_summary,
                "execution_mode": PlanExecutionMode.AUTO.value,
                "auto_executed": True,
                "execution_result": exec_result,
                "hint": "Plan auto-executed.",
            }

        # MANUAL mode: persist plan and wait for user approval
        store.put(plan)
        log.info(
            "PlanStore write (MANUAL): plan_id=%s len=%d",
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
            "execution_mode": PlanExecutionMode.MANUAL.value,
            "hint": ("Use approve_plan, reject_plan, or modify_plan to proceed."),
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
        result = planner.execute_plan(plan)
        store.put(plan)

        subject = plan.subject_id
        console.print(f"  [success]✓ Plan approved: {subject}[/success]")
        console.print()
        log.info("Plan '%s' approved for '%s'", plan.plan_id, subject)
        return {
            "status": "ok",
            "action": "approve_plan",
            "plan_id": plan.plan_id,
            "executed": True,
            "result": str(result)[:500],
            "hint": f"Plan approved for {subject}.",
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

    return {
        "create_plan": handle_create_plan,
        "approve_plan": handle_approve_plan,
        "reject_plan": handle_reject_plan,
        "modify_plan": handle_modify_plan,
        "list_plans": handle_list_plans,
    }
