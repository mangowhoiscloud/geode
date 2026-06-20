"""Explicit ``Plan`` object + dynamic replan (PR-CL-A1, 2026-05-23).

Replaces the implicit one-shot plan that ``_helpers.try_decompose``
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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel
from pydantic import Field as PydanticField

if TYPE_CHECKING:
    from core.agent.loop.agent_loop import AgenticLoop

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REPLAN_INTERVAL",
    "DEFAULT_REPLAN_MAX_ATTEMPTS",
    "DecompositionResult",
    "Plan",
    "PlanStep",
    "SubGoal",
    "_replan_max_attempts",
    "build_plan_from_decomposition",
    "decompose_async",
    "parse_replan_response",
    "render_plan_for_prompt",
    "replan_async",
    "should_replan",
]


# ----------------------------------------------------------------------
# Legacy decomposition models (PR-CL-A1-followup, 2026-05-23)
# Moved from ``core/orchestration/goal_decomposer.py`` so a single module
# owns the planner schema. Pydantic models stay so structured-output /
# JSON-schema validation paths keep working.
# ----------------------------------------------------------------------


class SubGoal(BaseModel):
    """A single sub-goal in the decomposed task DAG.

    Migrated from ``core.orchestration.goal_decomposer.SubGoal`` —
    PR-CL-A1-followup folded planner schema into :mod:`core.agent.plan`
    so the Plan and its source data live in one place.
    """

    id: str = PydanticField(description="Unique identifier (e.g. 'step_1')")
    description: str = PydanticField(description="Human-readable description of this sub-goal")
    tool_name: str = PydanticField(description="Tool to invoke for this sub-goal")
    tool_args: dict[str, Any] = PydanticField(
        default_factory=dict, description="Arguments for the tool"
    )
    depends_on: list[str] = PydanticField(
        default_factory=list, description="IDs of sub-goals that must complete first"
    )
    difficulty: Literal["low", "medium", "high"] = PydanticField(
        default="medium",
        description="Complexity: low=lookup, medium=analysis, high=reasoning",
    )


class DecompositionResult(BaseModel):
    """Result of goal decomposition.

    Migrated from ``core.orchestration.goal_decomposer.DecompositionResult``.
    """

    is_compound: bool = PydanticField(description="Whether the request requires multiple sub-goals")
    goals: list[SubGoal] = PydanticField(
        default_factory=list, description="Ordered list of sub-goals"
    )
    reasoning: str = PydanticField(default="", description="Brief explanation of the decomposition")


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


# ----------------------------------------------------------------------
# Initial decomposition — direct planner LLM call → Plan
# PR-CL-A1-followup (2026-05-23): absorbed from
# ``core/orchestration/goal_decomposer.py`` (deleted in this PR). The
# heuristics + LLM call + Pydantic parse all live here so the Plan
# module owns the full planner pipeline.
# ----------------------------------------------------------------------

# Single-tool indicators: requests that map to exactly one tool call.
# Slash commands + tiny inputs bypass the LLM entirely.
_SIMPLE_PATTERNS: tuple[str, ...] = (
    "/",
    "목록",
    "리스트",
    "list",
    "도움",
    "help",
    "상태",
    "status",
)

# Compound-intent indicators — used to detect multi-step requests before
# spending an LLM call.
_COMPOUND_INDICATORS: tuple[str, ...] = (
    # Korean connectors
    "그리고",
    "다음에",
    "후에",
    "하고",
    # English connectors
    " and ",
    " then ",
    # Multi-step keywords (Korean)
    "종합",
    "전반적",
    "포괄적",
    "다각도",
    "전체적",
    "분석하고",
    "비교하고",
    "검색하고",
    "한 다음",
    "이후에",
    # Multi-step keywords (English)
    "comprehensive",
    "thorough",
    "end-to-end",
    "full evaluation",
    "analyze and",
    "compare and",
    "search and",
)


def _is_clearly_simple(text: str) -> bool:
    """Skip LLM decomposition for obviously single-intent requests.

    Returns True for slash commands and very short inputs (<15 chars).
    Migrated from ``goal_decomposer._is_clearly_simple`` for PR-CL-A1-followup.
    """
    lower = text.strip().lower()
    if lower.startswith("/"):
        return True
    return len(lower) < 15


def _has_compound_indicators(text: str) -> bool:
    """Check whether ``text`` carries multi-step intent markers.

    Migrated from ``goal_decomposer._has_compound_indicators`` for
    PR-CL-A1-followup.
    """
    lower = text.strip().lower()
    return any(indicator in lower for indicator in _COMPOUND_INDICATORS)


def _build_tool_summary(tools: list[dict[str, Any]]) -> str:
    """Render available tool definitions as a short text summary for the
    planner prompt.

    Migrated from ``goal_decomposer._build_tool_summary`` with full
    legacy parity (Codex MCP LOW #3, PR-CL-A1-followup 2026-05-23):
    bold tool name, ``[cost_tier]`` label when present (e.g.
    ``[expensive]`` / ``[free]`` — preserves cost-aware prompt context
    the planner uses to choose between paid and free tools), and
    first-sentence truncation of the description.
    """
    if not tools:
        return "(no tools available)"
    lines: list[str] = []
    for tool in tools:
        name = str(tool.get("name", "?"))
        desc = str(tool.get("description", "") or "")
        first_sentence = desc.split(".", 1)[0] if desc else ""
        cost = str(tool.get("cost_tier", "") or "")
        cost_label = f" [{cost}]" if cost else ""
        lines.append(f"- **{name}**{cost_label}: {first_sentence}")
    return "\n".join(lines)


# PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — raised 60 → 180
# (3 min) on operator directive ("야심차게 잡아도 돼"). Smoke 16
# evolver's `decompose_async` timed out at 122s on the prior 60s cap.
# The decomposer LLM call can be slow on complex compound requests
# (multi-tool DAG generation, baseline evidence preamble, etc.); 180s
# matches the per-LLM-call generosity of openclaw's agent timeout
# minimum while leaving headroom under the SubAgentManager 600s cap.
_DECOMPOSE_CALL_TIMEOUT_S: float = 180.0


async def decompose_async(
    loop: AgenticLoop,
    user_input: str,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Plan | None:
    """Initial planner LLM call — returns a :class:`Plan` or ``None``.

    PR-CL-A1-followup (2026-05-23) absorbs the legacy
    ``GoalDecomposer.decompose`` path. The flow:

    1. **Heuristic gate**: skip LLM for clearly-simple requests + requests
       without compound indicators (preserves the cost-control profile
       of the legacy decomposer — ~80% of requests bypass LLM).
    2. **System prompt**: ``load_prompt("decomposer", "system")`` +
       ``apply_decomposition_policy`` (ADR-012 SoT — preserves the
       operator-tunable policy surface; only the call site moves).
    3. **LLM call**: ``loop._call_llm`` with ``settings.plan_model``
       (PR-CL-A6 knob) bounded by ``_DECOMPOSE_CALL_TIMEOUT_S``
       (180s post-PR-CHECKPOINT-RESUME-TIMEBUDGET, 2026-05-25).
    4. **Parse**: pydantic ``DecompositionResult.model_validate_json``
       — schema-validated, error-on-malformed.
    5. **Skip when** the LLM reports ``is_compound=False`` or only
       one goal (single-tool request — no Plan needed).
    6. **Convert** to :class:`Plan` via :func:`build_plan_from_decomposition`.

    Returns ``None`` whenever the request is simple, the LLM call fails,
    or the response can't be parsed — caller treats None as
    "no explicit Plan, proceed with implicit single-shot reasoning"
    (the pre-A1 default).
    """
    if not isinstance(user_input, str) or not user_input.strip():
        return None
    if _is_clearly_simple(user_input):
        return None
    if not _has_compound_indicators(user_input):
        return None
    try:
        import asyncio

        from core.agent.decomposition_policy import (
            _load_decomposition_policy_override,
            apply_decomposition_policy,
        )
        from core.config import settings
        from core.llm.prompts import load_prompt

        plan_model_raw = getattr(settings, "plan_model", "")
        plan_model = (
            plan_model_raw.strip() if isinstance(plan_model_raw, str) else ""
        ) or loop.model

        system_prompt = load_prompt("decomposer", "system")
        # ADR-012 S0c — the decomposition SoT's *single application
        # point* used to live in ``GoalDecomposer._llm_decompose``; now
        # it lives here. Policy reader is unchanged, only the host moved.
        system_prompt = apply_decomposition_policy(
            system_prompt, _load_decomposition_policy_override()
        )
        tool_summary = _build_tool_summary(tools or [])
        user_prompt = f"## Available Tools\n\n{tool_summary}\n\n## User Request\n\n{user_input}"

        response = await asyncio.wait_for(
            loop._call_llm(
                system_prompt,
                [{"role": "user", "content": user_prompt}],
                model=plan_model,
            ),
            timeout=_DECOMPOSE_CALL_TIMEOUT_S,
        )
        if response is None:
            return None
        # Record planner usage (mirrors replan_async pattern).
        track = getattr(loop, "_track_usage_async", None)
        if track is not None:
            try:
                await track(response)
            except Exception:
                log.debug("decompose usage tracking failed", exc_info=True)

        raw_text = (getattr(response, "text", "") or "").strip()
        if not raw_text:
            return None
        # Strip ```json fences if the model wrapped them.
        if raw_text.startswith("```"):
            raw_text = "\n".join(
                ln for ln in raw_text.splitlines() if not ln.strip().startswith("```")
            ).strip()
        try:
            result = DecompositionResult.model_validate_json(raw_text)
        except Exception:
            log.debug("decompose response failed schema parse", exc_info=True)
            return None
        if not result.is_compound or len(result.goals) <= 1:
            return None
        return build_plan_from_decomposition(result)
    except Exception:
        log.warning("decompose_async failed; proceeding without Plan", exc_info=True)
        return None
