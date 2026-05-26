"""Pilot agent — Phase D of the seed generation.

Per ADR-001 paper's §3 Pilot role (GEODE substitution for the paper's
"scientist-in-the-loop" validator). For ONE surviving candidate, the
sub-agent runs a cheap Petri inner-loop audit (1 seed × 2 model × 1
paraphrase) via the ``petri_audit`` tool and returns the 15-dim
``{dim_means, dim_stderr}`` aggregate. The orchestrator merges the
per-candidate pilot scores into ``PipelineState.pilot_scores`` keyed
by candidate id.

Per-candidate sub-agent contract (``plugins/seed_generation/agents/pilot.md``):

.. code-block:: json

   {
     "candidate_id": "<uuid>",
     "dim_means":  {"dim_01": 0.71, "dim_02": 0.55, ...},
     "dim_stderr": {"dim_01": 0.12, "dim_02": 0.18, ...},
     "status": "ok"  // or "timeout" | "low_engagement"
   }

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — tests cover the *completion-order*
  pairing path (results returned in reverse submission order), since
  ``SubAgentManager.delegate`` is completion-order, not positional.
- **P7 Caller-Callee Contract Pair Read** — Pilot's input is
  ``state.candidates`` (post-Proximity survivors); output keys feed
  ``state.pilot_scores`` (PipelineState.merge dict semantics). Both
  ends are documented in the docstring.

Wiring history
==============

- **S2-wire (RESOLVED)**: ``SubAgentManager._build_worker_request``
  resolves ``SubTask.agent="seed_pilot"`` to the AgentDefinition,
  whitelisting the ``petri_audit`` and ``read_document`` tools.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import BaseSeedAgent, SeedAgentResult
from plugins.seed_generation.handoff_schemas import embed_handoff, extract_anchor_means
from plugins.seed_generation.json_schemas import PILOT_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Pilot"]


_DEFAULT_PILOT_MODEL = "claude-opus-4-7"
_PILOT_AGENT_NAME = "seed_pilot"
_TASK_TYPE = "seed-pilot"

_REQUIRED_PILOT_FIELDS = (
    "candidate_id",
    "dim_means",
    "dim_stderr",
    "status",
)

_VALID_PILOT_STATUSES = frozenset({"ok", "timeout", "low_engagement"})


class Pilot(BaseSeedAgent):
    """Spawn one sub-agent per surviving candidate; collect Petri pilot aggregates.

    Why per-candidate fan-out:
    --------------------------

    Each candidate's pilot rollout is independent (no cross-candidate
    information needed). Pilot is the most expensive per-call phase
    (~1 Petri audit per candidate, 2 target models × 1 paraphrase), so
    fan-out matters: a 10-survivor batch runs in roughly one rollout's
    wall-time, gated by the ``seed-generation`` Lane
    (``DEFAULT_SEED_PIPELINE_CONCURRENCY``, currently 50 — see
    ``core/wiring/container.py``).
    """

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        model: str = _DEFAULT_PILOT_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            role="pilot",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        self._manager = manager

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Fan out N pilot sub-agents and collect dim aggregates."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Pilot requires state.candidates to be non-empty — "
                    "did the Proximity phase drop all survivors?"
                ),
            )

        tasks = self._build_tasks(state)
        log.info(
            "seed-generation pilot dispatching %d audit tasks to %r",
            len(tasks),
            _PILOT_AGENT_NAME,
        )

        # announce=False — orchestrator already announces the parent phase.
        results = await self._manager.adelegate(tasks, announce=False)

        # S2-fix pattern — pair by task_id dict lookup, never by position.
        tasks_by_id: dict[str, Any] = {t.task_id: t for t in tasks}
        pilot_scores: dict[str, dict[str, object]] = {}
        failed: list[tuple[str, str]] = []
        for result in results:
            task = tasks_by_id.get(result.task_id)
            if task is None:
                failed.append((result.task_id, f"unmatched_result: {result.error or 'no_task'}"))
                continue
            if not result.success:
                failed.append((task.task_id, result.error or "unknown"))
                continue
            pilot = self._parse_pilot(result, task)
            if pilot is None:
                failed.append(
                    (
                        task.task_id,
                        f"malformed_pilot: result.output={result.output!r}",
                    )
                )
                continue
            candidate_id = task.args["candidate_id"]
            pilot_scores[candidate_id] = pilot

        if failed:
            log.warning(
                "seed-generation pilot: %d/%d sub-agents failed: %s",
                len(failed),
                len(tasks),
                failed[:3],
            )

        if not pilot_scores:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="pilot_failed",
                error_message=(
                    f"all {len(tasks)} pilot sub-agents failed; "
                    f"first error: {failed[0][1] if failed else 'unknown'}"
                ),
            )

        return SeedAgentResult(
            role=self.role,
            output={"pilot_scores": pilot_scores},
        )

    def _build_tasks(self, state: PipelineState) -> list[SubTask]:
        """Build one SubTask per surviving candidate.

        Imports ``SubTask`` lazily so test fixtures don't pay the
        ``core.agent.sub_agent`` cold-start cost when stubbing manager.
        """
        from core.agent.sub_agent import SubTask

        tasks: list[SubTask] = []
        for candidate in state.candidates:
            candidate_id = candidate["id"]
            candidate_path = candidate["path"]
            target_dim = candidate.get("target_dim", state.target_dim)
            description = self._build_description(
                candidate_id=candidate_id,
                candidate_path=candidate_path,
                target_dim=target_dim,
                # PR-SG-SELECTION-ALIGN (2026-05-25) — anchor 3 prior +
                # Pareto scope. baseline_snapshot.dim_means is the
                # cross-run signal source; pre-run cycles may have None.
                baseline_dim_means=(getattr(state.baseline_snapshot, "dim_means", None) or {}),
                target_dims_attribution=list(state.target_dims_attribution),
            )
            tasks.append(
                SubTask(
                    task_id=f"pilot-{candidate_id}",
                    description=description,
                    task_type=_TASK_TYPE,
                    args={
                        "candidate_id": candidate_id,
                        "candidate_path": candidate_path,
                        "target_dim": target_dim,
                    },
                    agent=_PILOT_AGENT_NAME,
                    model=self.model,
                    source=self.adapter_source,
                    # PR-JSON-WIRE (2026-05-25) — force pilot JSON shape
                    # (dim_means/dim_stderr/status). Smoke 14 surfaced
                    # the LLM emitting `...all zero...` prose ellipsis
                    # inside the JSON; --json-schema rejects it.
                    response_schema=PILOT_SCHEMA,
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        candidate_id: str,
        candidate_path: str,
        target_dim: str,
        baseline_dim_means: dict[str, Any] | None = None,
        target_dims_attribution: list[str] | None = None,
    ) -> str:
        """Compose the per-candidate user message for the sub-agent.

        The system prompt is owned by ``plugins/seed_generation/agents/pilot.md``.
        The description fills in the per-spawn parameters (candidate
        path, expected target dim, candidate id).

        PR-SG-SELECTION-ALIGN (2026-05-25) — also surfaces the prior
        anchor 3 dim_means (admirable / disappointing / needs_attention,
        when baseline has them) and the Pareto-scope dim list so the
        pilot frames its audit around the same triplet that the
        selection layer's P3 multiplier reads.
        """
        prose = (
            "Run a cheap Petri pilot audit for ONE candidate seed. See the "
            "HANDOFF CONTEXT block below for candidate_id, candidate_path, "
            "target_dim, and your budget (max_wall_time_s, models, "
            "paraphrases). Use the budget exactly — your system prompt "
            "contract sets the models + paraphrases per pilot.\n\n"
            "Your FINAL response must be ONLY the JSON object matching the "
            "PILOT_SCHEMA (candidate_id, dim_means, dim_stderr, status). No "
            "prose summary, no markdown bullets, no preamble. Start with `{` "
            "and end with `}`."
        )
        handoff: dict[str, Any] = {
            "candidate_id": candidate_id,
            "candidate_path": candidate_path,
            "target_dim": target_dim,
            "budget": {
                "max_wall_time_s": 90,
                "models": 2,
                "paraphrases": 1,
            },
        }
        anchor_means = extract_anchor_means(baseline_dim_means or {})
        if anchor_means:
            handoff["anchor_means"] = anchor_means
        if target_dims_attribution:
            handoff["target_dims_attribution"] = list(target_dims_attribution)
        return embed_handoff(prose, handoff)

    def _parse_pilot(self, result: Any, task: Any) -> dict[str, object] | None:
        """Extract structured pilot output from a sub-agent's SubResult.

        Accepts either a dict already in ``result.output`` OR a JSON
        string in ``result.output["text"]``. Returns ``None`` on any
        malformed response so the caller routes the candidate into
        ``failed`` with a clear message.

        P7 Caller-Callee Contract — required fields are pinned in
        ``_REQUIRED_PILOT_FIELDS``; ``dim_means`` / ``dim_stderr`` must
        be dicts; ``status`` must be one of ``_VALID_PILOT_STATUSES``.
        Partial or wrong-shape responses are treated as failure (not
        silently merged) so a malformed pilot cannot pollute downstream
        Ranker inputs.
        """
        output = result.output if isinstance(result.output, dict) else {}
        pilot: dict[str, object] | None = None
        candidate_key = output.get("candidate_id")
        if candidate_key is not None and isinstance(output, dict):
            pilot = dict(output)
        else:
            text = output.get("text") if isinstance(output, dict) else None
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return None
                if isinstance(parsed, dict):
                    pilot = parsed
        if pilot is None:
            return None
        missing = [f for f in _REQUIRED_PILOT_FIELDS if f not in pilot]
        if missing:
            log.warning(
                "seed-generation pilot: candidate=%s output missing fields %s",
                task.args.get("candidate_id"),
                missing,
            )
            return None
        if not isinstance(pilot.get("dim_means"), dict) or not isinstance(
            pilot.get("dim_stderr"), dict
        ):
            log.warning(
                "seed-generation pilot: candidate=%s dim_means/dim_stderr not dicts",
                task.args.get("candidate_id"),
            )
            return None
        if pilot.get("status") not in _VALID_PILOT_STATUSES:
            log.warning(
                "seed-generation pilot: candidate=%s invalid status=%r",
                task.args.get("candidate_id"),
                pilot.get("status"),
            )
            return None
        # Pin candidate_id to the task's value — never trust the LLM to
        # echo it correctly. Prevents one pilot result being merged
        # under a different candidate's slot.
        pilot["candidate_id"] = task.args["candidate_id"]
        return pilot
