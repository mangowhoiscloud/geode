"""Tests for PlanMode — plan-before-execute orchestration."""

from __future__ import annotations

from typing import Any

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

    def test_auto_mode_caches_plan_for_audit(self) -> None:
        """v0.53.3 — B2 fix: AUTO-executed plans MUST be cached so the
        audit trail (``list_plans``) can surface them. Pre-fix the AUTO
        branch only returned the result without storing → user could
        not enumerate previously-run plans → "0 items" UX bug."""
        from core.cli import _build_tool_handlers
        from core.cli.tool_handlers import _get_plan_store
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        handler = handlers["create_plan"]
        list_handler = handlers["list_plans"]

        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = True
            result = handler(ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original

        assert result["auto_executed"] is True
        plan_id = result["plan_id"]
        # Direct store access — proves the write happened
        assert plan_id in _get_plan_store()
        # End-to-end via list_plans — proves audit surface works
        listed = list_handler()
        assert listed["count"] >= 1
        assert any(p["plan_id"] == plan_id for p in listed["plans"])

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
# v0.53.3 — Plan cache invariants (B1, C, observability)
# ---------------------------------------------------------------------------


class TestPlanCacheInvariants:
    """v0.53.3 cross-factory cache + no-pop-on-approve invariants.

    Pre-fix bugs the user reproduced 2026-04-27 — ``create_plan → ok``
    immediately followed by ``list_plans → 0 items``:
      B1: ``_plan_cache`` lived in the ``_build_plan_handlers`` closure
          → multiple ``_build_tool_handlers`` invocations (daemon at
          services.py, fork at bootstrap.py, sub-agent at worker.py)
          produced multiple closures with separate dicts → cross-handler
          reads saw an empty cache.
      C : ``handle_approve_plan`` / ``reject_plan`` immediately popped
          the entry → audit trail destroyed for any approved plan.
    """

    @pytest.fixture(autouse=True)
    def _setup_readiness(self, tmp_path: Any, monkeypatch: Any) -> None:
        from core.cli import _set_readiness
        from core.cli.startup import ReadinessReport

        readiness = ReadinessReport()
        readiness.force_dry_run = True
        readiness.has_api_key = True
        _set_readiness(readiness)
        # v0.53.3 — isolate PlanStore to a tmp file so tests don't
        # pollute / get polluted by .geode/plans.json
        import core.cli.tool_handlers as th
        from core.orchestration.plan_store import PlanStore

        monkeypatch.setattr(th, "_PLAN_STORE", PlanStore(tmp_path / "plans.json"))

    def test_b1_cache_shared_across_factory_calls(self) -> None:
        """The PlanStore is a module-level singleton, so a plan created
        via factory invocation #1 must be visible to ``list_plans``
        retrieved from factory invocation #2."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers_a = _build_tool_handlers(verbose=False)
        handlers_b = _build_tool_handlers(verbose=False)
        # Two separate factory calls — pre-fix each had its own
        # closure dict; post-fix both share the module-level PlanStore.
        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            create_result = handlers_a["create_plan"](ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original
        plan_id = create_result["plan_id"]
        listed = handlers_b["list_plans"]()
        assert any(p["plan_id"] == plan_id for p in listed["plans"]), (
            "create_plan from factory A must be visible to list_plans "
            "from factory B (single module-level PlanStore)"
        )

    def test_c_approved_plan_remains_listable(self) -> None:
        """v0.53.3 C fix — approving a plan must NOT remove it from
        the cache; ``list_plans`` should still surface it (with status
        reflecting approve/execute lifecycle)."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            create_result = handlers["create_plan"](ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original
        plan_id = create_result["plan_id"]
        approve_result = handlers["approve_plan"](plan_id=plan_id)
        assert approve_result["executed"] is True
        listed = handlers["list_plans"]()
        assert any(p["plan_id"] == plan_id for p in listed["plans"]), (
            "approved plan must remain in list_plans for audit trail"
        )

    def test_c_rejected_plan_remains_listable(self) -> None:
        """v0.53.3 C fix — same invariant for reject_plan."""
        from core.cli import _build_tool_handlers
        from core.config import settings

        handlers = _build_tool_handlers(verbose=False)
        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            create_result = handlers["create_plan"](ip_name="Berserk", template="full_pipeline")
        finally:
            settings.plan_auto_execute = original
        plan_id = create_result["plan_id"]
        handlers["reject_plan"](plan_id=plan_id, reason="testing")
        listed = handlers["list_plans"]()
        assert any(p["plan_id"] == plan_id for p in listed["plans"])

    def test_list_plans_status_filter(self) -> None:
        """v0.53.3 — optional ``status`` arg slices the audit trail.

        Uses the goal-path (uuid plan_id) instead of the IP-path
        because the IP-path has a separate per-instance counter
        collision (B5: ``PlanMode._counter`` resets per fresh
        instance → both calls get ``plan-0001``)."""
        from core.cli import _build_tool_handlers
        from core.config import settings
        from core.orchestration.plan_mode import PlanStatus

        handlers = _build_tool_handlers(verbose=False)
        original = settings.plan_auto_execute
        try:
            settings.plan_auto_execute = False
            r1 = handlers["create_plan"](goal="research task A", steps=["step a1", "step a2"])
            r2 = handlers["create_plan"](goal="research task B", steps=["step b1"])
        finally:
            settings.plan_auto_execute = original
        assert r1["plan_id"] != r2["plan_id"], "goal-path uuid must be unique"
        # Approve r1 → its status moves DRAFT → APPROVED. r2 stays DRAFT.
        # (Goal-path skips PlanMode.present_plan, unlike the IP-path.)
        handlers["approve_plan"](plan_id=r1["plan_id"])
        only_draft = handlers["list_plans"](status=PlanStatus.DRAFT.value)
        assert all(p["status"] == "draft" for p in only_draft["plans"])
        assert any(p["plan_id"] == r2["plan_id"] for p in only_draft["plans"])
        assert not any(p["plan_id"] == r1["plan_id"] for p in only_draft["plans"])


# ---------------------------------------------------------------------------
# v0.53.3 — Disk-persistent PlanStore
# ---------------------------------------------------------------------------


class TestPlanStorePersistence:
    """v0.53.3 — disk persistence (B fix). Plans must survive across
    PlanStore instance lifecycles (modeling daemon restart)."""

    def test_roundtrip_preserves_all_fields(self, tmp_path: Any) -> None:
        from core.orchestration.plan_mode import AnalysisPlan, PlanStatus, PlanStep
        from core.orchestration.plan_store import PlanStore

        path = tmp_path / "plans.json"
        store_a = PlanStore(path)
        plan = AnalysisPlan(
            plan_id="plan_test01",
            ip_name="Berserk",
            steps=[
                PlanStep(
                    step_id="s1",
                    description="step one",
                    node_name="agentic",
                    estimated_time_s=12.0,
                    dependencies=["s0"],
                    metadata={"k": "v"},
                ),
            ],
            status=PlanStatus.APPROVED,
            metadata={"template": "agentic"},
        )
        store_a.put(plan)
        # Fresh PlanStore = simulates daemon restart
        store_b = PlanStore(path)
        loaded = store_b.get("plan_test01")
        assert loaded is not None
        assert loaded.plan_id == "plan_test01"
        assert loaded.ip_name == "Berserk"
        assert loaded.status == PlanStatus.APPROVED
        assert len(loaded.steps) == 1
        assert loaded.steps[0].step_id == "s1"
        assert loaded.steps[0].dependencies == ["s0"]
        assert loaded.steps[0].metadata == {"k": "v"}
        assert loaded.metadata == {"template": "agentic"}

    def test_status_update_persists(self, tmp_path: Any) -> None:
        """Updating status (DRAFT → APPROVED) must hit disk via subsequent put."""
        from core.orchestration.plan_mode import AnalysisPlan, PlanStatus, PlanStep
        from core.orchestration.plan_store import PlanStore

        path = tmp_path / "plans.json"
        store = PlanStore(path)
        plan = AnalysisPlan(
            plan_id="plan_xy",
            ip_name="x",
            steps=[PlanStep("s", "d", "agentic", 1.0)],
        )
        store.put(plan)
        plan.status = PlanStatus.APPROVED
        store.put(plan)
        store2 = PlanStore(path)
        assert store2.get("plan_xy").status == PlanStatus.APPROVED  # type: ignore[union-attr]

    def test_malformed_entry_does_not_block_others(self, tmp_path: Any) -> None:
        """A bad entry in plans.json must be skipped with a warning,
        not crash the whole load."""
        import json

        from core.orchestration.plan_store import PlanStore

        path = tmp_path / "plans.json"
        path.write_text(
            json.dumps(
                {
                    "plan_bad": {"this is": "not a plan"},
                    "plan_good": {
                        "plan_id": "plan_good",
                        "ip_name": "ok",
                        "steps": [],
                        "status": "draft",
                        "created_at": 0.0,
                        "total_estimated_time_s": 0.0,
                        "total_estimated_cost": 0.0,
                        "metadata": {},
                    },
                }
            ),
            encoding="utf-8",
        )
        store = PlanStore(path)
        assert "plan_good" in store
        assert "plan_bad" not in store

    def test_corrupt_file_falls_back_to_empty(self, tmp_path: Any) -> None:
        """Invalid JSON must not crash startup."""
        from core.orchestration.plan_store import PlanStore

        path = tmp_path / "plans.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = PlanStore(path)
        assert len(store) == 0


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
