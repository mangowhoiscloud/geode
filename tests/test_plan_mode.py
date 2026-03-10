"""Tests for PlanMode — plan-before-execute orchestration."""

from __future__ import annotations

import pytest
from core.orchestration.plan_mode import (
    AnalysisPlan,
    PlanMode,
    PlanStatus,
    PlanStep,
)


class TestPlanStep:
    def test_plan_step_creation(self):
        step = PlanStep(
            step_id="router_load",
            description="Route + load IP data",
            node_name="router",
            estimated_time_s=8.0,
        )
        assert step.step_id == "router_load"
        assert step.dependencies == []

    def test_plan_step_with_dependencies(self):
        step = PlanStep(
            step_id="signals",
            description="Fetch signals",
            node_name="signals",
            estimated_time_s=6.0,
            dependencies=["router_load"],
        )
        assert step.dependencies == ["router_load"]


class TestAnalysisPlan:
    def test_auto_calculates_total_time(self):
        steps = [
            PlanStep("a", "Step A", "node_a", 10.0),
            PlanStep("b", "Step B", "node_b", 20.0),
        ]
        plan = AnalysisPlan(plan_id="test-1", ip_name="Berserk", steps=steps)
        assert plan.total_estimated_time_s == 30.0

    def test_explicit_total_time_not_overridden(self):
        steps = [PlanStep("a", "Step A", "node_a", 10.0)]
        plan = AnalysisPlan(
            plan_id="test-1",
            ip_name="Berserk",
            steps=steps,
            total_estimated_time_s=99.0,
        )
        assert plan.total_estimated_time_s == 99.0

    def test_step_count(self):
        steps = [PlanStep("a", "A", "n", 1.0), PlanStep("b", "B", "n", 1.0)]
        plan = AnalysisPlan(plan_id="p1", ip_name="Test", steps=steps)
        assert plan.step_count == 2

    def test_get_step(self):
        steps = [PlanStep("a", "Step A", "n", 1.0)]
        plan = AnalysisPlan(plan_id="p1", ip_name="Test", steps=steps)
        assert plan.get_step("a") is not None
        assert plan.get_step("nonexistent") is None

    def test_execution_order_linear(self):
        steps = [
            PlanStep("a", "A", "n", 1.0),
            PlanStep("b", "B", "n", 1.0, dependencies=["a"]),
            PlanStep("c", "C", "n", 1.0, dependencies=["b"]),
        ]
        plan = AnalysisPlan(plan_id="p1", ip_name="Test", steps=steps)
        batches = plan.execution_order()
        assert len(batches) == 3
        assert [s.step_id for s in batches[0]] == ["a"]
        assert [s.step_id for s in batches[1]] == ["b"]
        assert [s.step_id for s in batches[2]] == ["c"]

    def test_execution_order_parallel(self):
        steps = [
            PlanStep("root", "Root", "n", 1.0),
            PlanStep("a", "A", "n", 1.0, dependencies=["root"]),
            PlanStep("b", "B", "n", 1.0, dependencies=["root"]),
            PlanStep("c", "C", "n", 1.0, dependencies=["root"]),
            PlanStep("join", "Join", "n", 1.0, dependencies=["a", "b", "c"]),
        ]
        plan = AnalysisPlan(plan_id="p1", ip_name="Test", steps=steps)
        batches = plan.execution_order()
        assert len(batches) == 3
        # Batch 0: root
        assert len(batches[0]) == 1
        # Batch 1: a, b, c in parallel
        assert len(batches[1]) == 3
        # Batch 2: join
        assert len(batches[2]) == 1


class TestPlanMode:
    def test_create_full_pipeline_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk", template="full_pipeline")
        assert plan.ip_name == "Berserk"
        assert plan.step_count == 10
        assert plan.status == PlanStatus.DRAFT
        assert plan.total_estimated_cost == 1.50
        assert pm.stats.created == 1

    def test_create_prospect_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("OnePiece", template="prospect")
        assert plan.ip_name == "OnePiece"
        assert plan.step_count == 6
        assert plan.total_estimated_cost == 0.80

    def test_unknown_template_raises(self):
        pm = PlanMode()
        with pytest.raises(ValueError, match="nonexistent"):
            pm.create_plan("Test", template="nonexistent")

    def test_present_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        summary = pm.present_plan(plan)
        assert summary["plan_id"] == plan.plan_id
        assert summary["ip_name"] == "Berserk"
        assert summary["status"] == "presented"
        assert summary["step_count"] == 10
        assert "steps" in summary
        assert "parallel_batches" in summary

    def test_approve_and_execute_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        pm.approve_plan(plan)
        assert plan.status == PlanStatus.APPROVED
        assert pm.stats.approved == 1

        result = pm.execute_plan(plan)
        assert plan.status == PlanStatus.COMPLETED
        assert result["status"] == "completed"
        assert len(result["step_results"]) == 10
        assert pm.stats.executed == 1

    def test_execute_unapproved_raises(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        with pytest.raises(ValueError, match="APPROVED"):
            pm.execute_plan(plan)

    def test_reject_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        pm.reject_plan(plan, reason="Too expensive")
        assert plan.status == PlanStatus.REJECTED
        assert plan.metadata["rejection_reason"] == "Too expensive"
        assert pm.stats.rejected == 1

    def test_approve_completed_plan_raises(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        pm.approve_plan(plan)
        pm.execute_plan(plan)
        with pytest.raises(ValueError):
            pm.approve_plan(plan)

    def test_get_plan(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        retrieved = pm.get_plan(plan.plan_id)
        assert retrieved is plan
        assert pm.get_plan("nonexistent") is None

    def test_list_plans_with_filter(self):
        pm = PlanMode()
        pm.create_plan("Berserk")
        plan2 = pm.create_plan("Claymore")
        pm.approve_plan(plan2)

        all_plans = pm.list_plans()
        assert len(all_plans) == 2

        approved = pm.list_plans(status=PlanStatus.APPROVED)
        assert len(approved) == 1
        assert approved[0].ip_name == "Claymore"

    def test_available_templates(self):
        templates = PlanMode.available_templates()
        assert "full_pipeline" in templates
        assert "prospect" in templates

    def test_auto_generated_plan_ids(self):
        pm = PlanMode()
        p1 = pm.create_plan("A")
        p2 = pm.create_plan("B")
        assert p1.plan_id != p2.plan_id
        assert p1.plan_id.startswith("plan-")

    def test_custom_plan_id(self):
        pm = PlanMode()
        plan = pm.create_plan("Berserk", plan_id="my-custom-id")
        assert plan.plan_id == "my-custom-id"

    def test_stats_to_dict(self):
        pm = PlanMode()
        d = pm.stats.to_dict()
        assert set(d.keys()) == {"created", "approved", "rejected", "executed"}
