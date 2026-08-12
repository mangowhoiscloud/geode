"""Review checkpoints for complex analysis requests.

``PlanMode`` creates, presents, modifies, approves, or rejects a proposed
checklist.  It deliberately does not execute checklist steps.  Runtime action
belongs to :class:`core.agent.loop.agent_loop.AgenticLoop`; ordinary progress
uses the advisory :class:`core.agent.plan.Plan` and ``update_plan`` surface.
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
    """A complete execution plan for a subject."""

    plan_id: str
    subject_id: str
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

    def execution_order(self, *, strict: bool = False) -> list[list[PlanStep]]:
        """Compute execution order as batches of parallelizable steps.

        Returns a list of batches. Steps within each batch can run in parallel.
        Each batch's dependencies are satisfied by previous batches.

        Args:
            strict: If True, raise ``ValueError`` when unresolvable
                dependencies (circular or missing) are detected instead
                of forcing them into the final batch.
        """
        completed: set[str] = set()
        remaining = list(self.steps)
        batches: list[list[PlanStep]] = []

        while remaining:
            batch = [
                step for step in remaining if all(dep in completed for dep in step.dependencies)
            ]
            if not batch:
                step_ids = [s.step_id for s in remaining]
                if strict:
                    raise ValueError(
                        f"Unresolvable dependencies in plan '{self.plan_id}': "
                        f"steps {step_ids} have circular or missing dependencies"
                    )
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
    ("scope", "Clarify objective and subject", "scope", 5.0, []),
    ("context", "Gather relevant context", "context", 8.0, ["scope"]),
    ("analysis", "Analyze available evidence", "analysis", 12.0, ["context"]),
    (
        "verification",
        "Run generic guardrails and consistency checks",
        "verification",
        8.0,
        ["analysis"],
    ),
    ("synthesis", "Synthesize answer and next actions", "synthesizer", 10.0, ["verification"]),
]


def _make_full_pipeline_plan(plan_id: str, subject_id: str) -> AnalysisPlan:
    """Create a standard generic pipeline plan."""
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
        subject_id=subject_id,
        steps=steps,
        total_estimated_cost=0.50,
    )


def _make_prospect_plan(plan_id: str, subject_id: str) -> AnalysisPlan:
    """Create a lightweight generic plan."""
    steps = [
        PlanStep("scope", "Clarify objective and subject", "scope", 5.0),
        PlanStep("analysis", "Analyze available evidence", "analysis", 12.0, ["scope"]),
        PlanStep(
            "synthesis",
            "Synthesize answer and next actions",
            "synthesizer",
            10.0,
            ["analysis"],
        ),
    ]
    return AnalysisPlan(
        plan_id=plan_id,
        subject_id=subject_id,
        steps=steps,
        total_estimated_cost=0.25,
    )


# Template registry
_PLAN_TEMPLATES: dict[str, Any] = {
    "full_pipeline": _make_full_pipeline_plan,
    "prospect": _make_prospect_plan,
}


class PlanMode:
    """Explicit review-checkpoint manager.

    Usage:
        plan_mode = PlanMode()
        plan = plan_mode.create_plan("subject", template="full_pipeline")
        summary = plan_mode.present_plan(plan)
        plan_mode.approve_plan(plan)
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
        subject_id: str,
        *,
        template: str = "full_pipeline",
        plan_id: str | None = None,
    ) -> AnalysisPlan:
        """Create an analysis plan from a template.

        Args:
            subject_id: Target subject name.
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

        plan: AnalysisPlan = factory(plan_id, subject_id)
        self._plans[plan.plan_id] = plan
        self._stats.created += 1
        log.info(
            "Plan '%s' created for subject '%s' (%d steps, ~%.0fs, ~$%.2f)",
            plan.plan_id,
            subject_id,
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
            "subject_id": plan.subject_id,
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
        """Record approval of a proposed checklist."""
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.PRESENTED):
            raise ValueError(
                f"Cannot approve plan in status '{plan.status.value}'. "
                "Plan must be in DRAFT or PRESENTED status."
            )
        plan.status = PlanStatus.APPROVED
        self._stats.approved += 1
        log.info("Plan '%s' approved", plan.plan_id)

    def modify_plan(
        self,
        plan: AnalysisPlan,
        *,
        template: str | None = None,
        remove_steps: list[str] | None = None,
        add_steps: list[PlanStep] | None = None,
    ) -> AnalysisPlan:
        """Modify an existing plan: change template, add/remove steps."""
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.PRESENTED):
            raise ValueError(
                f"Cannot modify plan in status '{plan.status.value}'. "
                "Plan must be in DRAFT or PRESENTED status."
            )

        if template is not None:
            factory = _PLAN_TEMPLATES.get(template)
            if factory is None:
                raise ValueError(
                    f"Unknown template: '{template}'. Available: {list(_PLAN_TEMPLATES.keys())}"
                )
            rebuilt = factory(plan.plan_id, plan.subject_id)
            plan.steps = rebuilt.steps
            plan.total_estimated_cost = rebuilt.total_estimated_cost
            plan.metadata["template"] = template

        if remove_steps:
            remove_set = set(remove_steps)
            plan.steps = [s for s in plan.steps if s.step_id not in remove_set]
            for idx, step in enumerate(plan.steps):
                new_deps = [d for d in step.dependencies if d not in remove_set]
                if new_deps != step.dependencies:
                    plan.steps[idx] = PlanStep(
                        step_id=step.step_id,
                        description=step.description,
                        node_name=step.node_name,
                        estimated_time_s=step.estimated_time_s,
                        dependencies=new_deps,
                        metadata=step.metadata,
                    )

        if add_steps:
            plan.steps.extend(add_steps)

        plan.total_estimated_time_s = sum(s.estimated_time_s for s in plan.steps)
        plan.status = PlanStatus.DRAFT
        log.info("Plan '%s' modified", plan.plan_id)
        return plan

    def reject_plan(self, plan: AnalysisPlan, *, reason: str = "") -> None:
        """Mark a plan as rejected."""
        plan.status = PlanStatus.REJECTED
        plan.metadata["rejection_reason"] = reason
        self._stats.rejected += 1
        log.info("Plan '%s' rejected: %s", plan.plan_id, reason or "(no reason)")

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

    def to_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "approved": self.approved,
            "rejected": self.rejected,
        }
