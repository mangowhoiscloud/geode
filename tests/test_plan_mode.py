import pytest
from core.orchestration.plan_mode import (
    AnalysisPlan,
    PlanExecutionMode,
    PlanMode,
    PlanStatus,
    PlanStep,
)


def test_analysis_plan_batches_and_strict_cycle_detection() -> None:
    plan = AnalysisPlan(
        plan_id="plan-1",
        subject_id="subject-1",
        steps=[
            PlanStep("scope", "Scope", "scope", 1),
            PlanStep("analysis", "Analyze", "analysis", 2, ["scope"]),
            PlanStep("synthesis", "Synthesize", "synthesis", 3, ["analysis"]),
        ],
    )

    assert plan.total_estimated_time_s == 6
    assert [[step.step_id for step in batch] for batch in plan.execution_order()] == [
        ["scope"],
        ["analysis"],
        ["synthesis"],
    ]

    cyclic = AnalysisPlan(
        plan_id="cycle",
        subject_id="subject-1",
        steps=[
            PlanStep("a", "A", "a", 1, ["b"]),
            PlanStep("b", "B", "b", 1, ["a"]),
        ],
    )
    with pytest.raises(ValueError):
        cyclic.execution_order(strict=True)


def test_plan_mode_lifecycle_and_summary() -> None:
    mode = PlanMode()
    plan = mode.create_plan("subject-1", template="full_pipeline")

    summary = mode.present_plan(plan)
    mode.approve_plan(plan)
    result = mode.execute_plan(plan)

    assert summary["subject_id"] == "subject-1"
    assert summary["step_count"] == 5
    assert result["status"] == PlanStatus.COMPLETED.value
    assert result["step_results"] == {
        "scope": "completed",
        "context": "completed",
        "analysis": "completed",
        "verification": "completed",
        "synthesis": "completed",
    }
    assert mode.stats.to_dict() == {"created": 1, "approved": 1, "rejected": 0, "executed": 1}


def test_modify_reject_and_template_errors() -> None:
    mode = PlanMode()
    plan = mode.create_plan("subject-1", template="prospect")
    mode.modify_plan(
        plan,
        remove_steps=["analysis"],
        add_steps=[PlanStep("review", "Review", "review", 1)],
    )

    assert [step.step_id for step in plan.steps] == ["scope", "synthesis", "review"]
    mode.reject_plan(plan, reason="not needed")
    assert plan.status == PlanStatus.REJECTED
    assert plan.metadata["rejection_reason"] == "not needed"

    with pytest.raises(ValueError):
        mode.create_plan("subject-1", template="missing")
    with pytest.raises(ValueError):
        mode.modify_plan(plan, template="missing")


def test_auto_execute_retries_and_records_partial_success() -> None:
    mode = PlanMode()
    plan = mode.create_plan("subject-1", template="prospect")
    attempts: dict[str, int] = {}

    def executor(step: PlanStep) -> None:
        attempts[step.step_id] = attempts.get(step.step_id, 0) + 1
        if step.step_id == "analysis":
            raise RuntimeError("boom")

    result = mode.auto_execute_plan(plan, step_executor=executor, max_retries=1)

    assert result["execution_mode"] == PlanExecutionMode.AUTO.value
    assert result["completed_steps"] == 2
    assert result["failed_steps"] == ["analysis"]
    assert attempts["analysis"] == 2
    assert plan.metadata["partial_success"] is True


def test_plan_lookup_and_filters() -> None:
    mode = PlanMode()
    draft = mode.create_plan("draft")
    approved = mode.create_plan("approved")
    mode.approve_plan(approved)

    assert mode.get_plan(draft.plan_id) is draft
    assert mode.list_plans(status=PlanStatus.APPROVED) == [approved]
    assert set(mode.available_templates()) == {"full_pipeline", "prospect"}
