import pytest
from core.orchestration.plan_mode import (
    AnalysisPlan,
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

    assert summary["subject_id"] == "subject-1"
    assert summary["step_count"] == 5
    assert plan.status == PlanStatus.APPROVED
    assert mode.stats.to_dict() == {"created": 1, "approved": 1, "rejected": 0}


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


def test_plan_mode_has_no_execution_surface() -> None:
    mode = PlanMode()

    assert not hasattr(mode, "execute_plan")
    assert not hasattr(mode, "auto_execute_plan")


def test_plan_lookup_and_filters() -> None:
    mode = PlanMode()
    draft = mode.create_plan("draft")
    approved = mode.create_plan("approved")
    mode.approve_plan(approved)

    assert mode.get_plan(draft.plan_id) is draft
    assert mode.list_plans(status=PlanStatus.APPROVED) == [approved]
    assert set(mode.available_templates()) == {"full_pipeline", "prospect"}
