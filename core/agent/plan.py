"""Observation-conditioned advisory planning for :class:`AgenticLoop`.

A :class:`Plan` records ordered intent, not a precompiled execution graph.
The acting model chooses each next action from the latest observation.
Replanning is evidence-triggered, never cadence-triggered.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.loop.agent_loop import AgenticLoop

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REPLAN_MAX_ATTEMPTS",
    "Plan",
    "PlanStep",
    "_replan_max_attempts",
    "parse_replan_response",
    "plan_async",
    "render_plan_for_prompt",
    "replan_async",
    "replan_response_schema",
    "should_replan",
]

DEFAULT_REPLAN_MAX_ATTEMPTS: int = 3


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One verifiable advisory step with no execution metadata."""

    id: str
    description: str
    expected_outcome: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "description": self.description,
            "expected_outcome": self.expected_outcome,
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """Immutable advisory plan for the current session."""

    steps: tuple[PlanStep, ...]
    plan_id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex}")
    current: int = 0
    completed: tuple[int, ...] = ()
    abandoned: tuple[int, ...] = ()
    reasoning: str = ""
    revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "steps": [step.to_dict() for step in self.steps],
            "current": self.current,
            "completed": list(self.completed),
            "abandoned": list(self.abandoned),
            "reasoning": self.reasoning,
            "revision": self.revision,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def current_step(self) -> PlanStep | None:
        if 0 <= self.current < len(self.steps):
            return self.steps[self.current]
        return None

    def remaining_steps(self) -> tuple[PlanStep, ...]:
        return self.steps[self.current :]

    def complete_and_advance(self, count: int) -> Plan:
        """Record ``count`` already-observed completions and advance."""
        remaining = len(self.steps) - self.current
        if count < 0 or count > remaining:
            raise ValueError(f"count must be between 0 and {remaining}, got {count}")
        if count == 0:
            return self
        next_current = self.current + count
        return Plan(
            steps=self.steps,
            plan_id=self.plan_id,
            current=next_current,
            completed=tuple(sorted({*self.completed, *range(self.current, next_current)})),
            abandoned=self.abandoned,
            reasoning=self.reasoning,
            revision=self.revision,
        )

    def abandon_and_advance(self) -> Plan:
        """Abandon the current step after its bounded repair budget."""
        if self.current >= len(self.steps):
            return self
        return Plan(
            steps=self.steps,
            plan_id=self.plan_id,
            current=self.current + 1,
            completed=self.completed,
            abandoned=tuple(sorted({*self.abandoned, self.current})),
            reasoning=self.reasoning,
            revision=self.revision,
        )

    @property
    def done(self) -> bool:
        return self.current >= len(self.steps)


def render_plan_for_prompt(plan: Plan) -> str:
    """Render the unfinished plan as a compact prompt block."""
    current = plan.current_step()
    if current is None:
        return ""
    lines = [
        "<plan>",
        (
            f"Current step {plan.current + 1}/{len(plan.steps)} "
            f"(revision {plan.revision}): {current.description}"
        ),
    ]
    if current.expected_outcome:
        lines.append(f"Expected outcome: {current.expected_outcome}")
    lines.append("Remaining steps:")
    for index, step in enumerate(plan.steps[plan.current :], start=plan.current):
        marker = "→" if index == plan.current else "·"
        lines.append(f"  {marker} {step.id}: {step.description}")
    lines.append(
        "Treat this as advisory intent, not an execution graph. Choose the next "
        "action from current observations. After observing completion, call "
        "update_plan with exact step text and statuses; this records progress "
        "and never executes a step."
    )
    if plan.abandoned:
        abandoned = ", ".join(
            plan.steps[index].id for index in plan.abandoned if 0 <= index < len(plan.steps)
        )
        lines.append(f"Abandoned (repair budget exhausted): {abandoned}")
    lines.append("</plan>")
    return "\n".join(lines)


def _replan_enabled() -> bool:
    raw = os.environ.get("GEODE_REPLAN_ENABLED", "").strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off"}
    try:
        from core.config import settings

        value = getattr(settings, "replan_enabled", None)
        if isinstance(value, bool):
            return value
    except Exception:
        log.debug("plan setting read failed", exc_info=True)
    return True


def _replan_max_attempts() -> int:
    raw = os.environ.get("GEODE_REPLAN_MAX_ATTEMPTS", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value >= 1:
            return value
    try:
        from core.config import settings

        setting_value: Any = getattr(settings, "replan_max_attempts", None)
        if isinstance(setting_value, int) and setting_value >= 1:
            return setting_value
    except Exception:
        log.debug("plan setting read failed", exc_info=True)
    return DEFAULT_REPLAN_MAX_ATTEMPTS


def should_replan(
    *,
    round_idx: int,
    plan: Plan | None,
    verify_failed: bool,
    verify_should_retry: bool,
    low_confidence: bool = False,
) -> str | None:
    """Return the evidence trigger for revising an active plan."""
    if not _replan_enabled():
        return None
    if round_idx == 0 and verify_failed and verify_should_retry:
        return "verify_fail"
    if plan is None or plan.done:
        return None
    if low_confidence:
        return "low_confidence"
    return None


_REPLAN_SYSTEM_PROMPT = """\
Mode: advisory re-planning.
Authority: revise structure only; do not execute tools or claim work is done.
Input: the active plan, latest observed result, and an evidence trigger.

Return exactly one JSON object matching the supplied schema. Keep at most eight
ordered, verifiable steps. The first step must address the observed failure or
uncertainty. Do not encode tool names, tool arguments, dependency edges, or
private chain-of-thought. "reasoning" is one concise selection summary.
"""

_PLAN_SYSTEM_PROMPT = """\
Mode: advisory planning.
Authority: produce structure only; do not execute tools or claim work is done.
Task: turn the operator's objective into an ordered, verifiable plan.

Method:
- Consider 2-4 materially different structures internally.
- Compare prerequisite order, reversibility, observable verification, and
  unnecessary work.
- Select the strongest structure and return only its steps plus a concise
  selection summary. Do not reveal private chain-of-thought.
- Keep at most eight steps. Each expected outcome must be observable.
- Do not preselect tools, arguments, or dependency edges; the acting loop will
  choose its next action from observations available at that time.

Reply with exactly one JSON object matching the supplied schema. "reasoning"
is a short selection summary, not hidden reasoning.
"""


def replan_response_schema() -> dict[str, Any]:
    """Return the shared structured-output schema for plan creation/revision."""
    return {
        "title": "AdvisoryPlanResult",
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "expected_outcome": {"type": "string"},
                    },
                    "required": ["id", "description", "expected_outcome"],
                    "additionalProperties": False,
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["steps", "reasoning"],
        "additionalProperties": False,
    }


def parse_replan_response(raw: str) -> tuple[list[PlanStep], str] | None:
    """Parse a planner response, preserving no execution metadata."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.debug("Planner response not JSON; keeping prior plan", extra={"raw": text[:200]})
        return None
    if not isinstance(payload, dict) or set(payload) != {"steps", "reasoning"}:
        return None
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 8:
        return None
    steps: list[PlanStep] = []
    used_ids: set[str] = set()
    required_step_keys = {"id", "description", "expected_outcome"}
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict) or set(raw_step) != required_step_keys:
            return None
        description = str(raw_step.get("description") or "").strip()
        expected_outcome = str(raw_step.get("expected_outcome") or "").strip()
        step_id = str(raw_step.get("id") or "").strip()
        if not step_id or step_id in used_ids or not description or not expected_outcome:
            return None
        used_ids.add(step_id)
        steps.append(PlanStep(step_id, description, expected_outcome))
    reasoning = str(payload.get("reasoning") or "").strip()
    if not reasoning:
        return None
    return steps, reasoning


async def _track_planner_usage(loop: AgenticLoop, response: Any) -> None:
    track = getattr(loop, "_track_usage_async", None)
    if track is not None:
        try:
            await track(response)
        except Exception:
            log.debug("Planner usage tracking failed", exc_info=True)


def _apply_planning_policy(loop: AgenticLoop, prompt: str) -> str:
    """Apply the lineage-compatible SIL ``decomposition`` policy surface."""
    from core.agent.decomposition_policy import (
        _load_decomposition_policy_override,
        apply_decomposition_policy,
    )

    sources = getattr(loop, "_policy_sources", {}).get("decomposition")
    policy = _load_decomposition_policy_override(sources=sources)
    return apply_decomposition_policy(prompt, policy)


async def plan_async(
    loop: AgenticLoop,
    objective: str,
    *,
    timeout_s: float = 60.0,
) -> Plan | None:
    """Create an advisory plan with action tools disabled."""
    objective = objective.strip()
    if not objective:
        raise ValueError("planning requires a non-empty objective")
    try:
        import asyncio

        response = await asyncio.wait_for(
            loop._call_llm(
                _apply_planning_policy(loop, _PLAN_SYSTEM_PROMPT),
                [{"role": "user", "content": f"Objective:\n{objective}"}],
                model=loop.model,
                response_schema=replan_response_schema(),
                allow_tools=False,
            ),
            timeout=timeout_s,
        )
        if response is None:
            return None
        await _track_planner_usage(loop, response)
        parsed = parse_replan_response((getattr(response, "text", "") or "").strip())
        if parsed is None:
            return None
        steps, reasoning = parsed
        return Plan(steps=tuple(steps), reasoning=reasoning)
    except Exception:
        log.warning("plan_async call failed", exc_info=True)
        return None


def _build_replan_user_prompt(plan: Plan | None, turn_result: Any, trigger: str) -> str:
    parts = [f"Trigger: {trigger}"]
    if plan is not None:
        current = plan.current_step()
        parts.extend(
            (
                f"Prior plan revision: {plan.revision}",
                f"Current step: {current.id if current else '(none)'}",
                "Remaining steps before replan:",
            )
        )
        parts.extend(f"- {step.id}: {step.description}" for step in plan.remaining_steps())
    text = getattr(turn_result, "text", "") or ""
    parts.extend(("", "Latest observed result (truncated 1500 chars):", text[:1500]))
    return "\n".join(parts)


async def replan_async(
    loop: AgenticLoop,
    *,
    plan: Plan | None,
    turn_result: Any,
    trigger: str,
    timeout_s: float = 60.0,
) -> Plan | None:
    """Revise a plan from observed evidence with action tools disabled."""
    try:
        import asyncio

        response = await asyncio.wait_for(
            loop._call_llm(
                _apply_planning_policy(loop, _REPLAN_SYSTEM_PROMPT),
                [
                    {
                        "role": "user",
                        "content": _build_replan_user_prompt(plan, turn_result, trigger),
                    }
                ],
                model=loop.model,
                response_schema=replan_response_schema(),
                allow_tools=False,
            ),
            timeout=timeout_s,
        )
        if response is None:
            return None
        await _track_planner_usage(loop, response)
        parsed = parse_replan_response((getattr(response, "text", "") or "").strip())
        if parsed is None:
            return None
        steps, reasoning = parsed
        return Plan(
            steps=tuple(steps),
            plan_id=plan.plan_id if plan is not None else f"plan_{uuid.uuid4().hex}",
            reasoning=reasoning,
            revision=(plan.revision if plan is not None else 0) + 1,
        )
    except Exception:
        log.warning("replan_async call failed; keeping prior plan", exc_info=True)
        return None
