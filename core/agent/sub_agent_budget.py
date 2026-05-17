"""Token + cost budget guard for sub-agent invocations.

Sub-agents inherit the parent ``AgenticLoop`` runtime, including LLM tool
calls. Without a budget guard, a runaway prompt loop in a single agent
can burn the entire generation's budget. The seed-pipeline (ADR-001)
runs 7 roles × up to 20 candidates × 60-match Elo tournament — a
worst-case ~$3.60/gen at default pricing. A budget guard adds a
soft warning and a hard kill so the experiment loop cannot silently
double its cost.

Levels
======

``soft``
    Emit ``SUBAGENT_BUDGET_WARNING`` hook event when cumulative cost
    crosses ``soft_usd``. The sub-agent keeps running.

``hard``
    Raise :class:`BudgetExceededError` when cumulative cost crosses
    ``hard_usd``. The orchestrator catches and translates to a
    ``SubAgentResult`` with ``status="error"`` + ``error_category="budget"``.

Cost is derived from :func:`core.llm.pricing_loader.estimate_cost`
(P3-B) — both prompt and completion tokens are tracked per call.

The budget is **per sub-agent invocation**, not pipeline-wide. The
pipeline-wide guard lives in
``plugins/seed_pipeline/cost_preview.py`` (S6.5).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "BudgetExceededError",
    "BudgetGuard",
    "SubAgentBudget",
]


def _env_float(name: str, default: float) -> float:
    """Read ``$name`` from env as a positive float, else ``default``."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = float(raw)
        if val <= 0:
            return default
        return val
    except ValueError:
        log.warning("invalid %s=%r (need positive float), using %.2f", name, raw, default)
        return default


DEFAULT_SOFT_USD = _env_float("SEED_PIPELINE_BUDGET_SOFT_USD", 0.50)
DEFAULT_HARD_USD = _env_float("SEED_PIPELINE_BUDGET_HARD_USD", 2.00)


class BudgetExceededError(RuntimeError):
    """Raised when a sub-agent crosses its hard budget cap.

    Carries the cumulative ``usd_spent`` and the ``hard_usd`` cap so the
    orchestrator can surface both numbers in the resulting
    ``SubAgentResult.error_message``.
    """

    def __init__(self, usd_spent: float, hard_usd: float, agent_id: str) -> None:
        self.usd_spent = usd_spent
        self.hard_usd = hard_usd
        self.agent_id = agent_id
        super().__init__(
            f"sub-agent {agent_id!r} exceeded hard budget: ${usd_spent:.4f} > ${hard_usd:.2f}"
        )


@dataclass
class SubAgentBudget:
    """Per-sub-agent budget state.

    Tracks cumulative cost across all LLM calls made within one
    sub-agent invocation. Reset between invocations.
    """

    agent_id: str
    soft_usd: float = DEFAULT_SOFT_USD
    hard_usd: float = DEFAULT_HARD_USD
    usd_spent: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    soft_warned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_usd(self) -> float:
        """Headroom under the hard cap (clamped at zero)."""
        return max(0.0, self.hard_usd - self.usd_spent)

    def fraction_used(self) -> float:
        """``usd_spent / hard_usd`` clamped to ``[0.0, 1.0]``."""
        if self.hard_usd <= 0:
            return 0.0
        return min(1.0, self.usd_spent / self.hard_usd)


class BudgetGuard:
    """Thread-safe budget tracker + ``record()`` hook for LLM call sites.

    The seed-pipeline orchestrator instantiates one BudgetGuard per
    sub-agent invocation, passes it into the agent's runtime context,
    and reads ``budget.usd_spent`` after the call returns to roll up
    into the pipeline-wide total.

    LLM call sites (or their pricing wrapper) invoke
    :meth:`record_usage` after each completion, providing the
    provider/model + prompt + completion token counts. The guard
    computes the incremental cost via
    :func:`core.llm.pricing_loader.estimate_cost` and either:

    - emits a hook + sets ``soft_warned`` (first crossing of
      ``soft_usd``)
    - raises :class:`BudgetExceededError` (any crossing of
      ``hard_usd``)
    """

    def __init__(
        self,
        agent_id: str,
        *,
        soft_usd: float = DEFAULT_SOFT_USD,
        hard_usd: float = DEFAULT_HARD_USD,
        on_soft_warn: Any | None = None,
    ) -> None:
        if soft_usd > hard_usd:
            raise ValueError(f"soft_usd ({soft_usd}) must be <= hard_usd ({hard_usd})")
        self._budget = SubAgentBudget(
            agent_id=agent_id,
            soft_usd=soft_usd,
            hard_usd=hard_usd,
        )
        self._lock = threading.Lock()
        self._on_soft_warn = on_soft_warn

    @property
    def budget(self) -> SubAgentBudget:
        """Snapshot of the underlying ``SubAgentBudget`` dataclass."""
        return self._budget

    def record_usage(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Record one LLM call's token usage; return cumulative usd.

        Raises :class:`BudgetExceededError` if the new total crosses
        the hard cap.
        """
        from core.llm.token_tracker import calculate_cost

        incremental = calculate_cost(
            model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
        with self._lock:
            self._budget.prompt_tokens += prompt_tokens
            self._budget.completion_tokens += completion_tokens
            self._budget.usd_spent += incremental
            usd_after = self._budget.usd_spent
            soft_crossed_now = not self._budget.soft_warned and usd_after >= self._budget.soft_usd
            if soft_crossed_now:
                self._budget.soft_warned = True
        if soft_crossed_now and self._on_soft_warn is not None:
            try:
                self._on_soft_warn(self._budget)
            except Exception:
                log.warning(
                    "soft-warn callback raised for agent=%r at usd=%.4f",
                    self._budget.agent_id,
                    usd_after,
                    exc_info=True,
                )
        if usd_after > self._budget.hard_usd:
            raise BudgetExceededError(
                usd_spent=usd_after,
                hard_usd=self._budget.hard_usd,
                agent_id=self._budget.agent_id,
            )
        return usd_after
