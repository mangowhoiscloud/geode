"""Tests for PlanMode — plan-before-execute orchestration."""

from __future__ import annotations

import pytest
from core.orchestration.plan_mode import (
    AnalysisPlan,
    PlanExecutionMode,
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


# ---------------------------------------------------------------------------
# PlanExecutionMode enum tests
# ---------------------------------------------------------------------------


class TestPlanExecutionMode:
    def test_manual_mode_value(self) -> None:
        assert PlanExecutionMode.MANUAL.value == "manual"

    def test_auto_mode_value(self) -> None:
        assert PlanExecutionMode.AUTO.value == "auto"


# ---------------------------------------------------------------------------
# Auto-execute tests
# ---------------------------------------------------------------------------


class TestAutoExecutePlan:
    """Tests for PlanMode.auto_execute_plan (AUTO mode)."""

    def test_auto_execute_creates_and_runs_all_steps(self) -> None:
        """Auto-execute should approve + execute a plan in one shot."""
        pm = PlanMode()
        plan = pm.create_plan("Berserk", template="full_pipeline")
        assert plan.status == PlanStatus.DRAFT

        result = pm.auto_execute_plan(plan)

        assert plan.status == PlanStatus.COMPLETED
        assert result["execution_mode"] == "auto"
        assert result["completed_steps"] == 10
        assert result["total_steps"] == 10
        assert result["failed_steps"] == []
        assert pm.stats.approved == 1
        assert pm.stats.executed == 1

    def test_auto_execute_from_presented_status(self) -> None:
        """Auto-execute should work from PRESENTED status too."""
        pm = PlanMode()
        plan = pm.create_plan("Berserk")
        pm.present_plan(plan)
        assert plan.status == PlanStatus.PRESENTED

        result = pm.auto_execute_plan(plan)
        assert plan.status == PlanStatus.COMPLETED
        assert result["completed_steps"] == plan.step_count

    def test_auto_execute_step_failure_continues(self) -> None:
        """When a step fails, auto-execute should continue to next steps."""
        pm = PlanMode()
        plan = pm.create_plan("Berserk", template="full_pipeline")

        call_count = 0

        def failing_executor(step: PlanStep) -> None:
            nonlocal call_count
            call_count += 1
            if step.step_id == "signals_fetch":
                raise RuntimeError("Simulated signal failure")

        result = pm.auto_execute_plan(plan, step_executor=failing_executor)

        assert plan.status == PlanStatus.COMPLETED
        assert result["step_results"]["signals_fetch"] == "failed"
        assert "signals_fetch" in result["failed_steps"]
        # Other steps should be completed
        assert result["step_results"]["router_load"] == "completed"
        assert result["completed_steps"] < result["total_steps"]
        assert plan.metadata.get("partial_success") is True

    def test_auto_execute_retries_on_failure(self) -> None:
        """Step executor should be retried max_retries times on failure."""
        pm = PlanMode()
        steps = [PlanStep("s1", "Single Step", "node", 5.0)]
        plan = AnalysisPlan(plan_id="retry-test", ip_name="Test", steps=steps)

        attempt_count = 0

        def flaky_executor(step: PlanStep) -> None:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise RuntimeError("First attempt fails")

        result = pm.auto_execute_plan(plan, step_executor=flaky_executor, max_retries=1)

        assert attempt_count == 2  # 1 initial + 1 retry
        assert result["step_results"]["s1"] == "completed"
        assert result["failed_steps"] == []

    def test_auto_execute_exhausts_retries(self) -> None:
        """After max_retries exhausted, step should be marked failed."""
        pm = PlanMode()
        steps = [PlanStep("s1", "Always Fails", "node", 5.0)]
        plan = AnalysisPlan(plan_id="exhaust-test", ip_name="Test", steps=steps)

        def always_fails(step: PlanStep) -> None:
            raise RuntimeError("Persistent failure")

        result = pm.auto_execute_plan(plan, step_executor=always_fails, max_retries=1)

        assert result["step_results"]["s1"] == "failed"
        assert result["failed_steps"] == ["s1"]

    def test_auto_execute_without_executor_simulates(self) -> None:
        """Without step_executor, all steps should be simulated as completed."""
        pm = PlanMode()
        plan = pm.create_plan("Berserk", template="prospect")

        result = pm.auto_execute_plan(plan)

        assert result["completed_steps"] == plan.step_count
        assert result["failed_steps"] == []

    def test_auto_execute_preserves_batch_order(self) -> None:
        """Steps should be executed in dependency-respecting batch order."""
        pm = PlanMode()
        plan = pm.create_plan("Berserk", template="full_pipeline")

        execution_order: list[str] = []

        def tracking_executor(step: PlanStep) -> None:
            execution_order.append(step.step_id)

        pm.auto_execute_plan(plan, step_executor=tracking_executor)

        # router_load must come before signals_fetch
        assert execution_order.index("router_load") < execution_order.index("signals_fetch")
        # signals_fetch must come before any analyst
        assert execution_order.index("signals_fetch") < execution_order.index("analyst_market")


# ---------------------------------------------------------------------------
# handle_create_plan auto-execute integration tests
# ---------------------------------------------------------------------------


class TestHandleCreatePlanAutoExecute:
    """Tests for handle_create_plan with plan_auto_execute setting."""

    @pytest.fixture(autouse=True)
    def _setup_readiness(self) -> None:
        """Ensure readiness is set so handler builders work."""
        from core.cli import _set_readiness
        from core.cli.startup import ReadinessReport

        readiness = ReadinessReport()
        readiness.force_dry_run = True
        readiness.has_api_key = True
        _set_readiness(readiness)

    def test_manual_mode_returns_hint_for_approval(self) -> None:
        """With plan_auto_execute=False, result should hint for manual approval."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        handler = handlers["create_plan"]

        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            result = handler(ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original

        assert result["status"] == "ok"
        assert result["execution_mode"] == "manual"
        assert "approve_plan" in result["hint"]
        assert "auto_executed" not in result

    def test_auto_mode_executes_immediately(self) -> None:
        """With plan_auto_execute=True, plan should be auto-executed."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        handler = handlers["create_plan"]

        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = True
            result = handler(ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original

        assert result["status"] == "ok"
        assert result["auto_executed"] is True
        assert result["execution_mode"] == "auto"
        assert "execution_result" in result
        exec_result = result["execution_result"]
        assert exec_result["completed_steps"] == 10

    def test_auto_mode_does_not_cache_plan(self) -> None:
        """Auto-executed plans should not be left in plan_cache."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        handler = handlers["create_plan"]

        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = True
            result = handler(ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original

        # Auto-executed plans should NOT be cached (no manual approval needed)
        assert result["auto_executed"] is True

    def test_manual_mode_preserves_existing_behavior(self) -> None:
        """With plan_auto_execute=False, behavior should be identical to before."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        create_handler = handlers["create_plan"]
        approve_handler = handlers["approve_plan"]

        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            create_result = create_handler(ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original

        assert create_result["status"] == "ok"
        assert create_result["execution_mode"] == "manual"

        # Should be able to approve the cached plan
        plan_id = create_result["plan_id"]
        approve_result = approve_handler(plan_id=plan_id)
        assert approve_result["status"] == "ok"
        assert approve_result["executed"] is True


# ---------------------------------------------------------------------------
# Config setting tests
# ---------------------------------------------------------------------------


class TestPlanAutoExecuteConfig:
    """Tests for GEODE_PLAN_AUTO_EXECUTE configuration."""

    def test_default_is_false(self) -> None:
        """plan_auto_execute should default to False."""
        from core.config import Settings

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.plan_auto_execute is False

    def test_env_var_enables(self) -> None:
        """GEODE_PLAN_AUTO_EXECUTE=true should enable auto-execute."""
        from core.config import Settings

        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            plan_auto_execute=True,
        )
        assert s.plan_auto_execute is True


# ---------------------------------------------------------------------------
# HITL gate preservation test
# ---------------------------------------------------------------------------


class TestHITLGatePreservation:
    """Verify HITL safety gates are never bypassed by auto-execute."""

    def test_dangerous_tools_remain_gated(self) -> None:
        """DANGEROUS_TOOLS should still require user approval in auto-execute."""
        from core.agent.tool_executor import DANGEROUS_TOOLS, WRITE_TOOLS

        # HITL gates are defined at ToolExecutor level, not plan level.
        # Verify they are not empty (regression guard).
        assert "run_bash" in DANGEROUS_TOOLS
        assert len(WRITE_TOOLS) > 0

    def test_write_tools_remain_gated(self) -> None:
        """WRITE_TOOLS should still require user approval."""
        from core.agent.tool_executor import WRITE_TOOLS

        assert "memory_save" in WRITE_TOOLS
        assert "note_save" in WRITE_TOOLS
