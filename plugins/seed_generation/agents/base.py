"""Abstract base for the 7 seed-generation agent roles.

Each concrete role (Generation / Reflection / Proximity / Pilot / Ranker
/ Evolver / Meta-review) is a subclass of :class:`BaseSeedAgent` and
returns a :class:`SeedAgentResult`. The orchestrator
(``plugins.seed_generation.orchestrator.Pipeline``) registers role
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
   ``[seed_generation.role.<name>]`` manifest entry. The manifest carries
   ``default_model`` + ``allowed_models`` + ``role_contract`` (S2.5).
2. ``execute(state)`` — synchronous entry point. The orchestrator
   provides sub-agent isolation and cost rollup.
3. Returns ``SeedAgentResult`` with ``status``, ``output`` payload,
   token usage, optional ``error_message``.

Sub-agent integration
=====================

Every role dispatches through ``SubAgentManager.delegate`` (S2+).
There is no per-role embedding branch — pre-CSP-8 Proximity called
``text_embed`` directly outside the delegate path; CSP-8 reverted
that to the paper's §3 LLM-clustering, and CSP-10 dropped the
remaining ``kind`` plumbing from the manifest / picker / pre-flight.
"""

from __future__ import annotations

import abc
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)

__all__ = ["BaseSeedAgent", "SeedAgentResult", "parse_structured_output"]


def parse_structured_output(
    raw_output: Any,
    *,
    required_fields: Sequence[str],
    pin_field: str | None = None,
    pin_value: Any = None,
) -> dict[str, Any] | None:
    """Extract a structured JSON dict from a sub-agent's SubResult.output.

    Shared parser used by Critic (S3), Pilot (S5), and Ranker voters
    (S6) — all of which dispatch one sub-agent per work item and
    expect a JSON response. Hoisted to base.py to avoid duplicating the
    JSON-as-text fallback + required-field validation across 3+ agents
    (see post-merge audit recommendation, 2026-05-18).

    Accepts either:
    - ``raw_output`` already a dict (most adapters serialize JSON →
      dict in ``SubResult.output`` directly).
    - ``raw_output`` a dict with a ``"text"`` key holding a JSON string
      (fallback for adapters that pass through raw text).

    Returns ``None`` (so the caller drops the result) when:
    - ``raw_output`` is not a dict and has no parseable ``text`` field.
    - The parsed dict is missing ANY of ``required_fields``.

    When ``pin_field`` is provided, the function overrides that key
    with ``pin_value`` after validation — used to pin candidate_id /
    match_id from the task args so a wrong LLM echo can't reroute a
    result to the wrong slot.
    """
    if not isinstance(raw_output, dict):
        return None
    parsed: dict[str, Any] | None = None
    # Prefer the dict-as-structured-output shape when any required field
    # is present (or when there are no required fields and no "text" key,
    # in which case the dict itself is the payload).
    has_required = any(f in raw_output for f in required_fields)
    has_text = isinstance(raw_output.get("text"), str)
    if has_required or (not required_fields and not has_text):
        parsed = dict(raw_output)
    elif has_text:
        try:
            candidate = json.loads(raw_output["text"])
        except json.JSONDecodeError:
            return None
        if isinstance(candidate, dict):
            parsed = candidate
    if parsed is None:
        return None
    missing = [f for f in required_fields if f not in parsed]
    if missing:
        log.warning(
            "seed-generation parse_structured_output: missing required fields %s",
            missing,
        )
        return None
    if pin_field is not None:
        parsed[pin_field] = pin_value
    return parsed


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
    """Abstract contract for a single seed-generation phase role.

    PR-Async-Phase-C step 2 (2026-05-22) — :meth:`aexecute` is now the
    abstract method subclasses MUST override. The sync :meth:`execute`
    is a deprecation shim that calls :meth:`aexecute` via
    :func:`core.async_runtime.run_process_coroutine` so legacy sync
    callers (Pipeline.run) still work while migration is in progress.
    The shim emits ``DeprecationWarning`` and carries a grep anchor
    (``# DEPRECATED-ASYNC-PHASE-C:``) for the bulk-removal pass.

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
    async def aexecute(self, state: Any) -> SeedAgentResult:
        """Run one phase of the pipeline against ``state`` (async).

        ``state`` is the ``PipelineState`` instance (forward type to
        avoid circular import). The agent reads input fields, performs
        its work (typically via ``await self._manager.adelegate(...)``),
        and returns a ``SeedAgentResult`` whose ``output`` the
        orchestrator merges back into the state.
        """

    def execute(self, state: Any) -> SeedAgentResult:
        """[DEPRECATED] Sync sibling of :meth:`aexecute`.

        Bridges async ``aexecute`` to legacy sync ``Pipeline.run``
        call sites until those migrate to ``Pipeline.arun``. The
        bridge uses :func:`run_process_coroutine` which requires no
        running event loop — RuntimeError if the caller already has
        one (in which case they should ``await aexecute(...)``
        directly).

        # DEPRECATED-ASYNC-PHASE-C: removal target after Pipeline /
        # CLI / tool_handler migrate to aexecute / arun fully.
        """
        import warnings

        warnings.warn(
            f"{type(self).__name__}.execute is deprecated; use aexecute (async) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(state))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(role={self.role!r}, "
            f"model={self.model!r}, source={self.source!r})"
        )
