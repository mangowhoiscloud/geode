"""GoalDecomposer — decompose high-level user goals into sub-task DAGs.

Layer 4 orchestration component that uses an LLM to break complex,
multi-step user requests into structured sub-goal DAGs. Simple requests
(single tool call) pass through without decomposition to avoid overhead.

Cost-aware: uses ANTHROPIC_BUDGET (Haiku) for decomposition to minimize
per-request cost (~$0.01 per decomposition call).

Usage:
    decomposer = GoalDecomposer()
    result = decomposer.decompose("이 게임의 시장성을 종합 평가해줘")
    if result is not None:
        for goal in result.goals:
            print(f"{goal.id} → {goal.tool_name}({goal.tool_args})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from core.config import ANTHROPIC_BUDGET

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SubGoal(BaseModel):
    """A single sub-goal in the decomposed task DAG."""

    id: str = Field(description="Unique identifier (e.g. 'step_1')")
    description: str = Field(description="Human-readable description of this sub-goal")
    tool_name: str = Field(description="Tool to invoke for this sub-goal")
    tool_args: dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")
    depends_on: list[str] = Field(
        default_factory=list, description="IDs of sub-goals that must complete first"
    )


class DecompositionResult(BaseModel):
    """Result of goal decomposition."""

    is_compound: bool = Field(description="Whether the request requires multiple sub-goals")
    goals: list[SubGoal] = Field(default_factory=list, description="Ordered list of sub-goals")
    reasoning: str = Field(default="", description="Brief explanation of the decomposition")


@dataclass
class DecomposerStats:
    """Track decomposer usage statistics."""

    total_calls: int = 0
    compound_detected: int = 0
    simple_passthrough: int = 0
    llm_errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total_calls": self.total_calls,
            "compound_detected": self.compound_detected,
            "simple_passthrough": self.simple_passthrough,
            "llm_errors": self.llm_errors,
        }


# ---------------------------------------------------------------------------
# Heuristic pre-filter — skip LLM if request is clearly simple
# ---------------------------------------------------------------------------

# Single-tool indicators: requests that map to exactly one tool call
_SIMPLE_PATTERNS: list[str] = [
    # Commands
    "/",
    # Single actions
    "목록",
    "리스트",
    "list",
    "도움",
    "help",
    "상태",
    "status",
]


def _is_clearly_simple(text: str) -> bool:
    """Check if the request is clearly single-intent (skip LLM decomposition).

    Returns True for requests that obviously map to a single tool call,
    avoiding unnecessary LLM overhead.
    """
    lower = text.strip().lower()

    # Slash commands are always single-intent
    if lower.startswith("/"):
        return True

    # Very short inputs (< 15 chars) are almost always single-intent
    return len(lower) < 15


# Compound intent indicators — used to detect multi-step requests
_COMPOUND_INDICATORS: list[str] = [
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
]


def _has_compound_indicators(text: str) -> bool:
    """Check if text contains indicators of a compound/multi-step request."""
    lower = text.strip().lower()
    return any(indicator in lower for indicator in _COMPOUND_INDICATORS)


# ---------------------------------------------------------------------------
# GoalDecomposer
# ---------------------------------------------------------------------------


class GoalDecomposer:
    """Decompose high-level user goals into sub-task DAGs.

    Uses a lightweight LLM call (Haiku) to determine if a request
    requires multiple tools and, if so, produces a structured DAG
    of SubGoals with dependency ordering.

    Simple requests are passed through without LLM overhead.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
    ) -> None:
        self._model = model or ANTHROPIC_BUDGET
        self._tool_definitions = tool_definitions
        self._stats = DecomposerStats()

    @property
    def stats(self) -> DecomposerStats:
        return self._stats

    def decompose(
        self,
        user_input: str,
        *,
        tool_definitions: list[dict[str, Any]] | None = None,
    ) -> DecompositionResult | None:
        """Decompose user input into sub-goals if compound.

        Args:
            user_input: Raw user input text.
            tool_definitions: Override tool definitions for this call.

        Returns:
            DecompositionResult if compound request detected.
            None if the request is simple (single tool call).
        """
        self._stats.total_calls += 1

        # Fast path: clearly simple requests skip LLM entirely
        if _is_clearly_simple(user_input):
            self._stats.simple_passthrough += 1
            log.debug("GoalDecomposer: simple passthrough (heuristic)")
            return None

        # Only call LLM if compound indicators are present
        if not _has_compound_indicators(user_input):
            self._stats.simple_passthrough += 1
            log.debug("GoalDecomposer: simple passthrough (no compound indicators)")
            return None

        # Compound indicators detected — call LLM for structured decomposition
        tools = tool_definitions or self._tool_definitions or []
        result = self._llm_decompose(user_input, tools)

        if result is None:
            self._stats.llm_errors += 1
            return None

        if not result.is_compound or len(result.goals) <= 1:
            self._stats.simple_passthrough += 1
            log.debug("GoalDecomposer: LLM determined single-intent")
            return None

        self._stats.compound_detected += 1
        log.info(
            "GoalDecomposer: decomposed into %d sub-goals: %s",
            len(result.goals),
            [g.id for g in result.goals],
        )
        return result

    def _llm_decompose(
        self,
        user_input: str,
        tools: list[dict[str, Any]],
    ) -> DecompositionResult | None:
        """Call LLM to decompose the request into sub-goals."""
        try:
            from core.llm.client import call_llm_parsed
            from core.llm.prompts import load_prompt

            system = load_prompt("decomposer", "system")

            # Build tool summary for the prompt
            tool_summary = self._build_tool_summary(tools)

            user_prompt = f"## Available Tools\n\n{tool_summary}\n\n## User Request\n\n{user_input}"

            result: DecompositionResult = call_llm_parsed(
                system,
                user_prompt,
                output_model=DecompositionResult,
                model=self._model,
                max_tokens=2048,
                temperature=0.0,
            )
            return result

        except Exception as exc:
            # Billing errors must propagate for clean UI handling
            from core.infrastructure.ports.agentic_llm_port import BillingError

            if isinstance(exc, BillingError):
                raise
            log.warning("GoalDecomposer LLM call failed", exc_info=True)
            return None

    @staticmethod
    def _build_tool_summary(tools: list[dict[str, Any]]) -> str:
        """Build a concise tool summary for the decomposition prompt."""
        if not tools:
            return "(no tools available)"

        lines: list[str] = []
        for tool in tools:
            name = tool.get("name", "?")
            desc = tool.get("description", "")
            # Truncate description to first sentence for brevity
            first_sentence = desc.split(".")[0] if desc else ""
            cost = tool.get("cost_tier", "")
            cost_label = f" [{cost}]" if cost else ""
            lines.append(f"- **{name}**{cost_label}: {first_sentence}")

        return "\n".join(lines)

    def build_task_graph_from_goals(
        self,
        result: DecompositionResult,
    ) -> Any:
        """Convert DecompositionResult into a TaskGraph for execution.

        Returns a TaskGraph populated with Tasks from the sub-goals.
        """
        from core.orchestration.task_system import Task, TaskGraph

        graph = TaskGraph()
        for goal in result.goals:
            task = Task(
                task_id=goal.id,
                name=goal.description,
                dependencies=list(goal.depends_on),
                metadata={
                    "tool_name": goal.tool_name,
                    "tool_args": goal.tool_args,
                },
            )
            graph.add_task(task)

        errors = graph.validate()
        if errors:
            log.warning("Goal decomposition produced invalid graph: %s", errors)

        return graph
