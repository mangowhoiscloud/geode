"""Plan Mode — plan-before-execute for complex analysis requests.

Layer 4 orchestration component that creates an execution plan,
presents it for user approval, and executes steps in dependency order.

For complex multi-IP or full-pipeline requests, PlanMode:
1. Creates a plan with ordered steps and estimated time/cost
2. Presents the plan for user review
3. Executes approved steps via the TaskSystem
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class PlanStatus(Enum):
    """Lifecycle status of an analysis plan."""

    DRAFT = "draft"
    PRESENTED = "presented"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class PlanStep:
    """A single step in the analysis plan."""

    step_id: str
    description: str
    node_name: str
    estimated_time_s: float
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisPlan:
    """A complete execution plan for an IP analysis."""

    plan_id: str
    ip_name: str
    steps: list[PlanStep]
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    total_estimated_time_s: float = 0.0
    total_estimated_cost: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_estimated_time_s == 0.0 and self.steps:
            self.total_estimated_time_s = sum(s.estimated_time_s for s in self.steps)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def get_step(self, step_id: str) -> PlanStep | None:
        """Find a step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def execution_order(self) -> list[list[PlanStep]]:
        """Compute execution order as batches of parallelizable steps.

        Returns a list of batches. Steps within each batch can run in parallel.
        Each batch's dependencies are satisfied by previous batches.
        """
        completed: set[str] = set()
        remaining = list(self.steps)
        batches: list[list[PlanStep]] = []

        while remaining:
            batch = [
                step for step in remaining if all(dep in completed for dep in step.dependencies)
            ]
            if not batch:
                # Circular dependency or missing dependency — add all remaining
                log.warning(
                    "Plan '%s': unresolvable dependencies, forcing remaining %d steps",
                    self.plan_id,
                    len(remaining),
                )
                batches.append(remaining)
                break

            batches.append(batch)
            completed.update(step.step_id for step in batch)
            remaining = [s for s in remaining if s.step_id not in completed]

        return batches


# ---------------------------------------------------------------------------
# Standard plan templates
# ---------------------------------------------------------------------------

_FULL_PIPELINE_STEPS: list[tuple[str, str, str, float, list[str]]] = [
    ("router_load", "Route + load IP data and signals", "router", 8.0, []),
    ("signals_fetch", "Fetch market signals and trends", "signals", 6.0, ["router_load"]),
    ("analyst_market", "Market analyst evaluation", "analyst", 12.0, ["signals_fetch"]),
    ("analyst_creative", "Creative quality analyst evaluation", "analyst", 12.0, ["signals_fetch"]),
    ("analyst_technical", "Technical depth analyst evaluation", "analyst", 12.0, ["signals_fetch"]),
    (
        "analyst_community",
        "Community momentum analyst evaluation",
        "analyst",
        12.0,
        ["signals_fetch"],
    ),
    (
        "evaluators",
        "Multi-axis evaluator scoring",
        "evaluators",
        10.0,
        ["analyst_market", "analyst_creative", "analyst_technical", "analyst_community"],
    ),
    ("scoring", "Compute composite score and tier", "scoring", 5.0, ["evaluators"]),
    ("verification", "Run guardrails and bias checks", "verification", 8.0, ["scoring"]),
    (
        "synthesis",
        "Generate value narrative and action plan",
        "synthesizer",
        10.0,
        ["verification"],
    ),
]


def _make_full_pipeline_plan(plan_id: str, ip_name: str) -> AnalysisPlan:
    """Create a standard full pipeline plan."""
    steps = [
        PlanStep(
            step_id=sid,
            description=desc,
            node_name=node,
            estimated_time_s=est,
            dependencies=deps,
        )
        for sid, desc, node, est, deps in _FULL_PIPELINE_STEPS
    ]
    return AnalysisPlan(
        plan_id=plan_id,
        ip_name=ip_name,
        steps=steps,
        total_estimated_cost=1.50,
    )


def _make_prospect_plan(plan_id: str, ip_name: str) -> AnalysisPlan:
    """Create a prospect (non-gamified IP) plan — skips PSM/signals."""
    steps = [
        PlanStep("router_load", "Route + load IP data", "router", 8.0),
        PlanStep("analyst_creative", "Creative quality analysis", "analyst", 12.0, ["router_load"]),
        PlanStep("analyst_market", "Market potential analysis", "analyst", 12.0, ["router_load"]),
        PlanStep(
            "evaluators",
            "Multi-axis evaluation",
            "evaluators",
            10.0,
            ["analyst_creative", "analyst_market"],
        ),
        PlanStep("scoring", "Compute prospect score", "scoring", 5.0, ["evaluators"]),
        PlanStep("synthesis", "Generate prospect narrative", "synthesizer", 10.0, ["scoring"]),
    ]
    return AnalysisPlan(
        plan_id=plan_id,
        ip_name=ip_name,
        steps=steps,
        total_estimated_cost=0.80,
    )


# Template registry
_PLAN_TEMPLATES: dict[str, Any] = {
    "full_pipeline": _make_full_pipeline_plan,
    "prospect": _make_prospect_plan,
}


class PlanMode:
    """Plan-before-execute orchestrator.

    Usage:
        plan_mode = PlanMode()
        plan = plan_mode.create_plan("Berserk", template="full_pipeline")
        summary = plan_mode.present_plan(plan)
        plan_mode.approve_plan(plan)
        results = plan_mode.execute_plan(plan)
    """

    def __init__(self) -> None:
        self._plans: dict[str, AnalysisPlan] = {}
        self._counter = 0
        self._stats = _PlanModeStats()

    @property
    def stats(self) -> _PlanModeStats:
        return self._stats

    def create_plan(
        self,
        ip_name: str,
        *,
        template: str = "full_pipeline",
        plan_id: str | None = None,
    ) -> AnalysisPlan:
        """Create an analysis plan from a template.

        Args:
            ip_name: Target IP name.
            template: Plan template name (full_pipeline, prospect).
            plan_id: Optional custom plan ID.

        Raises:
            ValueError: If template is unknown.
        """
        factory = _PLAN_TEMPLATES.get(template)
        if factory is None:
            raise ValueError(
                f"Unknown plan template: '{template}'. Available: {list(_PLAN_TEMPLATES.keys())}"
            )

        if plan_id is None:
            self._counter += 1
            plan_id = f"plan-{self._counter:04d}"

        plan: AnalysisPlan = factory(plan_id, ip_name)
        self._plans[plan.plan_id] = plan
        self._stats.created += 1
        log.info(
            "Plan '%s' created for IP '%s' (%d steps, ~%.0fs, ~$%.2f)",
            plan.plan_id,
            ip_name,
            plan.step_count,
            plan.total_estimated_time_s,
            plan.total_estimated_cost,
        )
        return plan

    def present_plan(self, plan: AnalysisPlan) -> dict[str, Any]:
        """Generate a presentation summary of the plan.

        Returns a dict suitable for Rich console output or API response.
        """
        plan.status = PlanStatus.PRESENTED
        batches = plan.execution_order()

        summary: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "ip_name": plan.ip_name,
            "status": plan.status.value,
            "step_count": plan.step_count,
            "total_estimated_time_s": plan.total_estimated_time_s,
            "total_estimated_cost": plan.total_estimated_cost,
            "parallel_batches": len(batches),
            "steps": [
                {
                    "step_id": step.step_id,
                    "description": step.description,
                    "node": step.node_name,
                    "estimated_time_s": step.estimated_time_s,
                    "dependencies": step.dependencies,
                }
                for step in plan.steps
            ],
        }
        return summary

    def approve_plan(self, plan: AnalysisPlan) -> None:
        """Mark a plan as approved for execution."""
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.PRESENTED):
            raise ValueError(
                f"Cannot approve plan in status '{plan.status.value}'. "
                "Plan must be in DRAFT or PRESENTED status."
            )
        plan.status = PlanStatus.APPROVED
        self._stats.approved += 1
        log.info("Plan '%s' approved", plan.plan_id)

    def reject_plan(self, plan: AnalysisPlan, *, reason: str = "") -> None:
        """Mark a plan as rejected."""
        plan.status = PlanStatus.REJECTED
        plan.metadata["rejection_reason"] = reason
        self._stats.rejected += 1
        log.info("Plan '%s' rejected: %s", plan.plan_id, reason or "(no reason)")

    def execute_plan(self, plan: AnalysisPlan) -> dict[str, Any]:
        """Execute an approved plan (simulation for demo).

        In production, this delegates to TaskSystem for real execution.
        For demo purposes, returns a simulated execution summary.

        Raises:
            ValueError: If plan is not approved.
        """
        if plan.status != PlanStatus.APPROVED:
            raise ValueError(
                f"Cannot execute plan in status '{plan.status.value}'. Plan must be APPROVED first."
            )

        plan.status = PlanStatus.EXECUTING
        start_time = time.time()

        # Simulate execution by computing batch structure
        batches = plan.execution_order()
        step_results: dict[str, str] = {}
        for batch_idx, batch in enumerate(batches):
            for step in batch:
                step_results[step.step_id] = "completed"
                log.debug(
                    "Plan '%s' batch %d: step '%s' completed (simulated)",
                    plan.plan_id,
                    batch_idx,
                    step.step_id,
                )

        elapsed = time.time() - start_time
        plan.status = PlanStatus.COMPLETED
        self._stats.executed += 1

        result = {
            "plan_id": plan.plan_id,
            "status": plan.status.value,
            "step_results": step_results,
            "batches_executed": len(batches),
            "elapsed_s": elapsed,
        }
        log.info("Plan '%s' execution completed (%.3fs)", plan.plan_id, elapsed)
        return result

    def get_plan(self, plan_id: str) -> AnalysisPlan | None:
        """Retrieve a plan by ID."""
        return self._plans.get(plan_id)

    def list_plans(self, *, status: PlanStatus | None = None) -> list[AnalysisPlan]:
        """List plans, optionally filtered by status."""
        plans = list(self._plans.values())
        if status is not None:
            plans = [p for p in plans if p.status == status]
        return plans

    @staticmethod
    def available_templates() -> list[str]:
        """List available plan templates."""
        return list(_PLAN_TEMPLATES.keys())


class _PlanModeStats:
    """Track plan mode statistics."""

    def __init__(self) -> None:
        self.created: int = 0
        self.approved: int = 0
        self.rejected: int = 0
        self.executed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "approved": self.approved,
            "rejected": self.rejected,
            "executed": self.executed,
        }
