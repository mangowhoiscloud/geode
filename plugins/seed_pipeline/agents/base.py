"""Abstract base for the 7 seed-pipeline agent roles.

Each concrete role (Generation / Reflection / Proximity / Pilot / Ranker
/ Evolver / Meta-review) is a subclass of :class:`BaseSeedAgent` and
returns a :class:`SeedAgentResult`. The orchestrator
(``plugins.seed_pipeline.orchestrator.Pipeline``) registers role
instances via :class:`PipelineRegistry` and calls
:meth:`BaseSeedAgent.execute` once per phase, passing the current
:class:`PipelineState`.

Why a class hierarchy
=====================

Each role has a distinct contract (input schema, output schema, side
effects). The paper (arXiv:2502.18864 Figure 1) defines 6 agent types
with explicit symmetry — Generation / Reflection / Ranking / Evolution
/ Proximity / Meta-review. GEODE adds Pilot to replace the
scientist-in-the-loop human validator with an automated Petri inner-
loop subset. The 7-way symmetry is structural, not premature
abstraction — see ``docs/audits/2026-05-18-plan-a-fidelity-amendment.md``
for the explicit waiver.

Lifecycle
=========

1. ``__init__(role_name, model, source, manifest_role)`` — bind to a
   ``[seed_pipeline.role.<name>]`` manifest entry. The manifest carries
   ``default_model`` + ``allowed_models`` + ``role_contract`` (S2.5).
2. ``execute(state)`` — synchronous entry point. The orchestrator
   wraps each call in its own ``BudgetGuard`` and sub-agent isolation.
3. Returns ``SeedAgentResult`` with ``status``, ``output`` payload,
   token usage, optional ``error_message``.

Sub-agent integration
=====================

For roles that use full ``AgenticLoop`` inheritance (Generator,
Critic, Pilot, Ranker voter, Evolver, Meta-reviewer) the concrete
subclass dispatches through ``SubAgentManager.delegate`` (S2+). The
Proximity role is a pure tool call (``text_embed``) and does not
spawn a sub-agent — the embedding API is called directly.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

__all__ = ["BaseSeedAgent", "SeedAgentResult"]


@dataclass
class SeedAgentResult:
    """Standardized result of one phase-agent invocation.

    Why not reuse ``core.agent.sub_agent.SubAgentResult``? S2-fix
    (2026-05-18) explicit rationale — both dataclasses share ~80% of
    fields (status / duration / token counts / error category), but
    their *aggregation semantics* differ:

    - ``SubAgentResult`` is per-TASK (one spawn → one result), with
      ``task_id`` + ``announced`` flag for the parent loop's announce
      queue. It is N-many per phase when Generator/Ranker fan out.
    - ``SeedAgentResult`` is per-ROLE (one phase → one result),
      consumed by the orchestrator's state merge. Carries ``output``
      dict whose keys (``candidates``, ``reflections``, ``elo_ratings``,
      …) map directly onto ``PipelineState`` fields.

    Wrapping SubAgentResult would force every role to construct a
    fake ``task_id`` and force the orchestrator to know about
    sub-task-vs-phase polymorphism. Keeping them sibling types lets
    each evolve in its own domain. Roles that spawn sub-agents
    (Generator, Ranker, Pilot) translate ``list[SubResult]`` →
    ``SeedAgentResult.output`` inside ``execute()``.
    """

    role: str
    status: Literal["ok", "error", "skipped"] = "ok"
    output: dict[str, Any] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd_spent: float = 0.0
    duration_ms: float = 0.0
    error_category: str | None = None
    error_message: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "ok"


class BaseSeedAgent(abc.ABC):
    """Abstract contract for a single seed-pipeline phase role.

    Subclasses MUST override :meth:`execute`. Phase orchestration,
    budget tracking, and registry lookup are owned by the Pipeline
    class.

    Per the fidelity amendment, the role concrete implementations
    (S2-S8) must perform substantive work — no ``pass`` /
    ``return None`` stubs are permitted in this sprint.
    """

    def __init__(
        self,
        *,
        role: str,
        model: str,
        source: str = "auto",
        manifest_role: dict[str, Any] | None = None,
    ) -> None:
        self.role = role
        self.model = model
        self.source = source
        self.manifest_role = manifest_role or {}

    @abc.abstractmethod
    def execute(self, state: Any) -> SeedAgentResult:
        """Run one phase of the pipeline against ``state``.

        ``state`` is the ``PipelineState`` instance (forward type to
        avoid circular import). The agent reads input fields, performs
        its work, and returns a ``SeedAgentResult`` whose ``output``
        the orchestrator merges back into the state.
        """

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(role={self.role!r}, "
            f"model={self.model!r}, source={self.source!r})"
        )
