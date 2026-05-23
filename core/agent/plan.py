"""Explicit ``Plan`` object + dynamic replan (PR-CL-A1, 2026-05-23).

Replaces the implicit one-shot plan that ``_decomposition.try_decompose``
emitted as a system-prompt suffix string. The plan now lives as a
structured :class:`Plan` object on :class:`SessionMetrics` so:

- The next ``arun`` reads it back and prepends a *current-step* hint to
  the system prompt (verbal-RL pattern from PR-CL-A3 carried over).
- PR-CL-A3 verify gains a new ``step_expected_mismatch`` rubric_miss
  that compares the just-finished turn against
  :class:`PlanStep.expected_outcome`.
- ``_maybe_replan_async`` fires the planner LLM (using
  :data:`settings.plan_model` from PR-CL-A6) when either of the two
  triggers fires:

  - **Verify FAIL trigger**: ``metrics.last_verify_should_retry``.
  - **Cadence trigger**: every ``settings.replan_interval`` rounds
    (``0`` = cadence off).

Frontier alignment (Socratic Q5):

- **ReWOO** (arxiv 2305.18323) — plan / observation decouple → 5x token
  efficiency. ReWOO's *Planner* / *Worker* / *Solver* split is the
  closest 1:1 to GEODE's plan_model / act_model / judge_model now that
  A6 has shipped.
- **Self-Discover** (arxiv 2402.03620) — task-level plan composition →
  10-40x fewer inferences vs ToT / Self-Consistency.
- **Reflexion** (NeurIPS 2023) — verbal RL hint we already prepend
  (A3) interleaves with explicit Plan steps.

I/O failures NEVER raise — observability mustn't break the run it observes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.agent.loop.agent_loop import AgenticLoop

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REPLAN_INTERVAL",
    "DEFAULT_REPLAN_MAX_ATTEMPTS",
    "Plan",
    "PlanStep",
    "_replan_max_attempts",
    "build_plan_from_decomposition",
    "parse_replan_response",
    "render_plan_for_prompt",
    "replan_async",
    "should_replan",
]


# Cadence interval (number of rounds between forced replan calls). ``0``
# disables cadence-based replan entirely (verify FAIL still triggers).
DEFAULT_REPLAN_INTERVAL: int = 5

# Maximum attempts on a single PlanStep before it's marked abandoned and
# the loop moves on to the next step in the plan.
DEFAULT_REPLAN_MAX_ATTEMPTS: int = 3


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One executable step in a :class:`Plan`.

    Frozen so the step is safe to share across threads and serialize to
    JSON without races. ``depends_on`` carries other step ``id`` values
    that must finish before this one is eligible. ``expected_outcome``
    is the comparison anchor PR-CL-A3 verify's
    ``step_expected_mismatch`` rubric uses — if the turn's output text
    contains none of the expected keywords, the step is flagged.
    """

    id: str
    description: str
    expected_outcome: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "expected_outcome": self.expected_outcome,
            "tool_name": self.tool_name,
            "tool_args": dict(self.tool_args),
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """Explicit execution plan for the current AgenticLoop session.

    Frozen — mutations always produce a *new* ``Plan`` (functional style).
    ``current`` is a 0-based index into ``steps``; ``completed`` and
    ``abandoned`` are sorted tuples of indices for replay-friendliness.
    """

    steps: tuple[PlanStep, ...]
    current: int = 0
    completed: tuple[int, ...] = ()
    abandoned: tuple[int, ...] = ()
    reasoning: str = ""  # planner's free-form rationale (verbatim)
    revision: int = 0  # incremented on every replan

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "current": self.current,
            "completed": list(self.completed),
            "abandoned": list(self.abandoned),
            "reasoning": self.reasoning,
            "revision": self.revision,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def current_step(self) -> PlanStep | None:
        """Return the step at ``current`` or ``None`` when the plan is done."""
        if 0 <= self.current < len(self.steps):
            return self.steps[self.current]
        return None

    def remaining_steps(self) -> tuple[PlanStep, ...]:
        return tuple(self.steps[self.current :])

    def advance(self, *, completed: bool = True) -> Plan:
        """Move to the next step. ``completed=False`` marks the current
        step as ``abandoned`` instead — used after exceeding
        ``GEODE_REPLAN_MAX_ATTEMPTS`` retries on the same step."""
        if self.current >= len(self.steps):
            return self
        bucket = "completed" if completed else "abandoned"
        if bucket == "completed":
            new_completed = tuple(sorted({*self.completed, self.current}))
            new_abandoned = self.abandoned
        else:
            new_completed = self.completed
            new_abandoned = tuple(sorted({*self.abandoned, self.current}))
        return Plan(
            steps=self.steps,
            current=self.current + 1,
            completed=new_completed,
            abandoned=new_abandoned,
            reasoning=self.reasoning,
            revision=self.revision,
        )

    @property
    def done(self) -> bool:
        return self.current >= len(self.steps)


# ----------------------------------------------------------------------
# Construction: decomposition result → Plan
# ----------------------------------------------------------------------


def build_plan_from_decomposition(decomp_result: Any) -> Plan | None:
    """Convert a :class:`core.orchestration.goal_decomposer.DecompositionResult`
    (with ``.goals`` list + ``.reasoning``) into an explicit :class:`Plan`.

    Returns ``None`` when the decomposition is empty or unparseable so the
    caller can short-circuit. ``getattr`` is used liberally so the helper
    survives mocked / partial inputs in tests.
    """
    if decomp_result is None:
        return None
    goals = getattr(decomp_result, "goals", None) or []
    if not goals:
        return None
    try:
        steps: list[PlanStep] = []
        for goal in goals:
            steps.append(
                PlanStep(
                    id=str(getattr(goal, "id", "")) or f"step_{len(steps) + 1}",
                    description=str(getattr(goal, "description", "")),
                    expected_outcome=str(getattr(goal, "expected_outcome", "")),
                    tool_name=str(getattr(goal, "tool_name", "")),
                    tool_args=dict(getattr(goal, "tool_args", {}) or {}),
                    depends_on=tuple(str(d) for d in (getattr(goal, "depends_on", None) or [])),
                )
            )
        return Plan(
            steps=tuple(steps),
            reasoning=str(getattr(decomp_result, "reasoning", "") or ""),
        )
    except Exception:
        log.debug("build_plan_from_decomposition failed", exc_info=True)
        return None


# ----------------------------------------------------------------------
# System-prompt rendering
# ----------------------------------------------------------------------


def render_plan_for_prompt(plan: Plan) -> str:
    """Render the current plan state as a `<plan>...</plan>` block.

    Returns the empty string when the plan is done — caller skips the
    suffix mutation cheaply. The block is intentionally compact (one line
    per step, current step marked) so a long plan doesn't crowd the
    system prompt.
    """
    if not plan.steps:
        return ""
    cur = plan.current_step()
    if cur is None:
        return ""
    lines = ["<plan>"]
    lines.append(
        f"You are executing step {plan.current + 1}/{len(plan.steps)} "
        f"(revision {plan.revision}): {cur.description}"
    )
    if cur.expected_outcome:
        lines.append(f"Expected outcome: {cur.expected_outcome}")
    lines.append("Remaining steps:")
    for idx in range(plan.current, len(plan.steps)):
        marker = "→" if idx == plan.current else "·"
        step = plan.steps[idx]
        lines.append(f"  {marker} {step.id}: {step.description}")
    if plan.abandoned:
        ab = ", ".join(plan.steps[i].id for i in plan.abandoned if 0 <= i < len(plan.steps))
        lines.append(f"Abandoned (retry budget exhausted): {ab}")
    lines.append("</plan>")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Replan trigger decision
# ----------------------------------------------------------------------


def _replan_interval() -> int:
    """Resolve the cadence interval.

    Env override wins when explicitly set (so tests / runtime tweaks
    work without re-instantiating the Settings singleton). When no env
    value is present, fall back to ``settings.replan_interval`` which
    carries the TOML cascade + pydantic default. Final fallback to
    :data:`DEFAULT_REPLAN_INTERVAL`. Codex MCP MEDIUM #4 (PR-CL-A1,
    2026-05-23) — original implementation read env only; this version
    honours both surfaces in the right priority order.
    """
    raw = os.environ.get("GEODE_REPLAN_INTERVAL", "").strip()
    if raw:
        try:
            env_value = int(raw)
        except ValueError:
            env_value = -1
        if env_value >= 0:
            return env_value
    try:
        from core.config import settings

        setting_value: Any = getattr(settings, "replan_interval", None)
        if isinstance(setting_value, int) and setting_value >= 0:
            return setting_value
    except Exception:
        log.debug("plan setting read failed", exc_info=True)
    return DEFAULT_REPLAN_INTERVAL


def _replan_enabled() -> bool:
    """Resolve the replan-enabled flag.

    Env override wins when explicitly set; otherwise ``settings.replan_enabled``;
    final default True (Codex MCP MEDIUM #4, PR-CL-A1, 2026-05-23).
    """
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
    """Resolve max-attempts before step abandon (default 3, min 1).

    Env override wins; falls back to ``settings.replan_max_attempts``;
    final default :data:`DEFAULT_REPLAN_MAX_ATTEMPTS` (Codex MCP
    MEDIUM #4, PR-CL-A1, 2026-05-23).
    """
    raw = os.environ.get("GEODE_REPLAN_MAX_ATTEMPTS", "").strip()
    if raw:
        try:
            env_value = int(raw)
        except ValueError:
            env_value = 0
        if env_value >= 1:
            return env_value
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
) -> str | None:
    """Decide whether to call replan this round.

    Returns the trigger name (``"verify_fail"`` / ``"cadence"``) when
    replan should fire, ``None`` otherwise. Dual-trigger policy per
    operator decision (PR-CL-A1 plan): verify FAIL takes priority,
    cadence is a secondary safety net.

    The pure-function signature lets tests assert the trigger logic
    without instantiating the loop.
    """
    if not _replan_enabled():
        return None
    # Verify FAIL trigger — wins over cadence so we replan as soon as
    # the agent has a hint to act on, rather than waiting for the next
    # cadence boundary.
    if verify_failed and verify_should_retry:
        return "verify_fail"
    # Cadence trigger — fires only when a plan already exists (no
    # synthesis from thin air; planning happens at decomposition).
    # Codex MCP MEDIUM #5 (PR-CL-A1, 2026-05-23): the no-plan guard
    # used to live below the cadence check, so cadence fired even
    # without a plan to revise.
    if plan is None:
        return None
    interval = _replan_interval()
    if interval > 0 and round_idx > 0 and round_idx % interval == 0:
        return "cadence"
    return None


# ----------------------------------------------------------------------
# Replan LLM call + response parsing
# ----------------------------------------------------------------------

_REPLAN_SYSTEM_PROMPT = """\
You are a re-planning assistant. Given the agent's current plan,
the just-finished turn's result, and a failure signal, propose a
revised plan covering the remaining work. Reply with a single-line
JSON object — no prose:

  {
    "steps": [
      {"id": "step_1", "description": "...", "expected_outcome": "...",
       "tool_name": "...", "depends_on": []},
      ...
    ],
    "reasoning": "<one sentence>"
  }

Keep the step count ≤ 8 (smaller is better). The first step must
address the failure the previous turn surfaced.
"""


def parse_replan_response(raw: str) -> tuple[list[PlanStep], str] | None:
    """Parse the planner LLM's JSON response into ``(steps, reasoning)``.

    Returns ``None`` when the payload is unparseable so the caller can
    keep the prior plan instead of fabricating one. Tolerates code fences
    around the JSON (some models wrap with ```json``).
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("```")).strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.debug("Replan response not JSON; keeping prior plan", extra={"raw": text[:200]})
        return None
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
    steps: list[PlanStep] = []
    for idx, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue
        steps.append(
            PlanStep(
                id=str(raw_step.get("id") or f"step_{idx + 1}"),
                description=str(raw_step.get("description") or ""),
                expected_outcome=str(raw_step.get("expected_outcome") or ""),
                tool_name=str(raw_step.get("tool_name") or ""),
                tool_args=dict(raw_step.get("tool_args") or {}),
                depends_on=tuple(str(d) for d in (raw_step.get("depends_on") or [])),
            )
        )
    if not steps:
        return None
    reasoning = str(obj.get("reasoning") or "")
    return steps, reasoning


def _build_replan_user_prompt(plan: Plan | None, turn_result: Any, trigger: str) -> str:
    """Render the prior plan + recent turn outcome for the replanner."""
    parts: list[str] = []
    parts.append(f"Trigger: {trigger}")
    if plan is not None:
        cur = plan.current_step()
        parts.append(f"Prior plan revision: {plan.revision}")
        parts.append(f"Current step: {cur.id if cur else '(none — plan exhausted)'}")
        parts.append(
            f"Completed: {[plan.steps[i].id for i in plan.completed if 0 <= i < len(plan.steps)]}"
        )
        parts.append(
            f"Abandoned: {[plan.steps[i].id for i in plan.abandoned if 0 <= i < len(plan.steps)]}"
        )
        parts.append("Remaining steps before replan:")
        for step in plan.remaining_steps():
            parts.append(f"- {step.id}: {step.description}")
    parts.append("")
    parts.append("Last turn result (truncated 1500 chars):")
    text = getattr(turn_result, "text", "") or ""
    parts.append(text[:1500])
    return "\n".join(parts)


async def replan_async(
    loop: AgenticLoop,
    *,
    plan: Plan | None,
    turn_result: Any,
    trigger: str,
    timeout_s: float = 60.0,
) -> Plan | None:
    """Call the planner LLM to revise the plan.

    Uses :data:`settings.plan_model` (PR-CL-A6 knob) so an operator
    running Opus-plan + Sonnet-act sees cost-aware replans. Failures
    return ``None`` so the caller keeps the prior plan rather than
    proceeding plan-less. Bounded by ``asyncio.wait_for`` so a stuck
    planner cannot hang the session.
    """
    try:
        import asyncio

        from core.config import settings

        plan_model_raw = getattr(settings, "plan_model", "")
        plan_model = (
            plan_model_raw.strip() if isinstance(plan_model_raw, str) else ""
        ) or loop.model
        user_prompt = _build_replan_user_prompt(plan, turn_result, trigger)
        response = await asyncio.wait_for(
            loop._call_llm(
                _REPLAN_SYSTEM_PROMPT,
                [{"role": "user", "content": user_prompt}],
                model=plan_model,
            ),
            timeout=timeout_s,
        )
        if response is None:
            return None
        # Record planner usage so cost surfaces in TokenTracker (mirrors
        # the judge-call pattern in PR-CL-A6 ``_verify_llm_judge_async``).
        track = getattr(loop, "_track_usage_async", None)
        if track is not None:
            try:
                await track(response)
            except Exception:
                log.debug("Replan usage tracking failed", exc_info=True)
        raw_text = (getattr(response, "text", "") or "").strip()
        parsed = parse_replan_response(raw_text)
        if parsed is None:
            return None
        steps, reasoning = parsed
        prior_revision = plan.revision if plan is not None else 0
        return Plan(
            steps=tuple(steps),
            current=0,
            reasoning=reasoning,
            revision=prior_revision + 1,
        )
    except Exception:
        log.warning("replan_async call failed; keeping prior plan", exc_info=True)
        return None
