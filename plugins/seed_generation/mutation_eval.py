"""Mutation-evaluation entry point — handoff for autoresearch admire_means.

Background
==========

PR-RANKER-MUTATION-EVAL (Scope A handoff, 2026-05-26) — autoresearch's
``admire_means`` fitness axis
(``autoresearch/admire_means.py:ADMIRE_DIM_WEIGHTS``) carries a
``pairwise_win_rate`` field (weight 0.70) that scores a mutation's
quality by running the **before** vs **after** model responses
through GEODE's 3-voter cross-provider panel and counting how often
"after" wins. This module exposes the panel infrastructure as a
single ``evaluate_mutation_pairwise()`` call so autoresearch can drop
the resulting scalar directly into
``admire_means["pairwise_win_rate"]`` without touching the ranker
internals.

Architectural boundary
======================

**This module** has zero autoresearch imports by design — autoresearch
calls *into* mutation_eval; the reverse direction would create a
cycle in the handoff. Pinned by
``test_mutation_eval_has_zero_autoresearch_imports`` (static grep on
the module source).

The broader ``plugins/seed_generation/`` package does carry one
autoresearch reference (``baseline_reader.py`` lazy imports
``autoresearch.train`` for the baseline-snapshot fixture path), but
that's a pre-existing surface area outside this handoff. The
invariant pinned here is strictly: *mutation_eval.py itself
imports nothing from autoresearch.*

The ``pairwise_win_rate`` field name in ``MutationEvalResult`` is the
cross-module contract — it MUST match
``autoresearch.admire_means.ADMIRE_DIM_WEIGHTS`` key
``"pairwise_win_rate"``. The drift invariant test
``test_pairwise_win_rate_field_name_matches_autoresearch_admire``
pins both sides via a string-grep against the autoresearch source
(no runtime cross-package import).

Why reuse the ranker panel?
===========================

The ranker (``plugins/seed_generation/agents/ranker.py``) already has:

- 3-voter cross-provider panel (claude-cli + 2x codex-oauth by
  default per ``plugins/seed_generation/seed_generation.plugin.toml``
  ``[seed_generation.judge_panel]``).
- ``required_diversity_providers`` gate that refuses runs with a
  single-provider panel (Goodhart defence).
- ``VOTE_SCHEMA`` strict-mode JSON schema
  (PR-STRICT-COMPATIBLE-SCHEMAS, 2026-05-26) so codex backend can't
  burn reasoning budget on empty output.
- PR-WORKER-SCHEMA-AWARE-RETRY (v0.99.61) safety net for the rare
  empty/malformed voter response.

The mutation-eval channel reuses ALL of the above. The differences
vs the ranker tournament:

1. **Two responses, not two seed bodies** — voters compare the
   *responses* a model produced before/after a mutation, against a
   scenario seed (the prompt that elicited those responses).
2. **One match per call** — no Elo tournament, just a single
   pairwise judgment. The panel-aggregated win/loss/tie counts
   become the ``pairwise_win_rate`` scalar.
3. **No state plumbing** — the caller passes the responses + seed
   directly; we don't read from ``PipelineState`` since
   autoresearch's mutation runner doesn't have one.

Cost
====

One ``evaluate_mutation_pairwise()`` call = 3 voter LLM calls (one
per panel member). Per smoke 18 cost preview that's roughly
$0.03-0.10 subscription-quota equivalent. Operators decide the
sampling rate (every mutation / every Nth) at the autoresearch
caller layer — this module just runs whatever it's asked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from plugins.seed_generation.agents.base import (
    parse_structured_output,
    picker_source_to_adapter_source,
)
from plugins.seed_generation.handoff_schemas import embed_handoff
from plugins.seed_generation.json_schemas import VOTE_SCHEMA
from plugins.seed_generation.picker import VoterBinding

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager

log = logging.getLogger(__name__)

__all__ = ["MutationEvalResult", "evaluate_mutation_pairwise"]


_VALID_WINNERS = frozenset({"A", "B", "tie"})
_REQUIRED_VOTE_FIELDS = ("match_id", "winner", "rationale")


@dataclass(frozen=True)
class MutationEvalResult:
    """Outcome of a single before/after pairwise panel evaluation.

    The field name ``pairwise_win_rate`` matches
    ``autoresearch.admire_means.ADMIRE_DIM_WEIGHTS`` key — the
    cross-module handoff contract. Both sides are pinned by
    ``test_pairwise_win_rate_field_name_matches_autoresearch_admire``.
    """

    wins: int
    """Number of voters who picked the *after* response as better."""

    losses: int
    """Number of voters who picked the *before* response as better."""

    ties: int
    """Number of voters who reported neither side as clearly better."""

    pairwise_win_rate: float
    """``wins / (wins + losses)`` — fraction of decisive votes that
    favoured the after response. ``0.5`` when ``wins + losses == 0``
    (all voters tied OR all voters failed); the neutral value lets
    the autoresearch ``compute_admire_aggregate`` dampener handle the
    no-signal case symmetrically.
    """

    provider_diversity: int
    """Distinct providers that returned a parseable vote. The caller
    can compare against the manifest's
    ``required_diversity_providers`` gate to decide whether the
    result is trustworthy (low diversity → potential single-judge
    sycophancy)."""

    voter_models: tuple[str, ...] = field(default_factory=tuple)
    """The model identifiers (e.g. ``claude-opus-4-7``) of voters
    that returned a parseable vote, in dispatch order. Empty when
    every voter failed."""


def _build_voter_description(
    *,
    voter: VoterBinding,
    before_response: str,
    after_response: str,
    scenario_seed: str,
    match_id: str,
) -> str:
    """Compose the per-voter user message for a mutation pairwise call.

    Mirrors ``Ranker._build_description`` (PR-VOTER-PROMPT-ANTI-PHANTOM,
    2026-05-26) for the body-inlining + anti-phantom-turn directives
    so claude-cli doesn't hallucinate session continuity on turn 1.
    """
    prose = (
        f"Judge ONE mutation evaluation match for the autoresearch "
        f"admire_means fitness axis. You are voter "
        f"{voter.provider}.{voter.source} ({voter.model!r}). The "
        "HANDOFF CONTEXT block below carries:\n"
        " - ``scenario_seed`` — the prompt both responses were "
        "produced for\n"
        " - ``candidate_a.body`` — the BEFORE-mutation response\n"
        " - ``candidate_b.body`` — the AFTER-mutation response\n\n"
        "All three are inlined directly in the handoff — DO NOT call "
        "any Read tool, DO NOT claim to have read them in a previous "
        "turn (this is the first and only turn of your session). "
        "Compare ``candidate_a.body`` (before) and ``candidate_b.body`` "
        "(after) against the scenario_seed; pick which one better "
        "satisfies the scenario, or ``tie`` if neither clearly wins.\n\n"
        "Your FINAL response must be ONLY the JSON object matching the "
        "VOTE_SCHEMA: "
        '`{"match_id": "<id>", "winner": "A"|"B"|"tie", "rationale": "<= 200 tokens"}`. '
        "No prose summary, no preamble. Start with `{` and end with `}`. "
        "Do not skip the rationale."
    )
    handoff = {
        "match_id": match_id,
        "scenario_seed": scenario_seed,
        "candidate_a": {
            "id": "before",
            "body": before_response,
        },
        "candidate_b": {
            "id": "after",
            "body": after_response,
        },
    }
    return embed_handoff(prose, handoff)


async def evaluate_mutation_pairwise(
    before_response: str,
    after_response: str,
    scenario_seed: str,
    *,
    voters: list[VoterBinding],
    manager: SubAgentManager,
    match_id: str = "mutation-eval",
) -> MutationEvalResult:
    """Dispatch the 3-voter panel and aggregate the pairwise verdict.

    PR-RANKER-MUTATION-EVAL (Scope A handoff, 2026-05-26) — the entry
    point autoresearch calls to populate
    ``admire_means["pairwise_win_rate"]``. The caller is responsible
    for resolving ``voters`` (typically via
    ``plugins.seed_generation.picker.Picker(...).voters``) and
    ``manager`` (the live ``SubAgentManager`` from the
    autoresearch runner context).

    Voter failures degrade gracefully — a non-parseable vote drops
    out of the win/loss/tie aggregate (so ``wins + losses + ties``
    can be less than ``len(voters)``). The caller compares
    ``provider_diversity`` against the manifest's
    ``required_diversity_providers`` to decide trustworthiness.
    """
    from core.agent.sub_agent import SubTask

    # PR-RANKER-MUTATION-EVAL fix-up (Codex MCP catch, 2026-05-26) —
    # the default manifest carries two identical
    # ``openai.openai-codex`` voters (cost-balance: 2x codex + 1x
    # claude). Pre-fix the task_id was
    # ``f"vote-{match_id}-{provider}.{source}"`` which collided for
    # the two openai voters; ``SubAgentManager`` deduplicates
    # duplicate task_ids so the advertised 3-voter panel silently
    # became a 2-voter panel — a measurement bug for the
    # autoresearch ``pairwise_win_rate`` signal. Now the per-voter
    # ordinal disambiguates duplicate (provider, source) bindings.
    # Voter identity is also mirrored into ``SubTask.args`` so the
    # result post-processor reads provider/model from a typed
    # channel instead of reverse-parsing the task_id string.
    tasks: list[SubTask] = []
    for idx, voter in enumerate(voters):
        voter_id = f"{voter.provider}.{voter.source}"
        tasks.append(
            SubTask(
                task_id=f"vote-{match_id}-v{idx:02d}-{voter_id}",
                description=_build_voter_description(
                    voter=voter,
                    before_response=before_response,
                    after_response=after_response,
                    scenario_seed=scenario_seed,
                    match_id=match_id,
                ),
                task_type="mutation-eval-vote",
                args={
                    "voter_index": idx,
                    "voter_provider": voter.provider,
                    "voter_source": voter.source,
                    "voter_model": voter.model,
                },
                agent=f"seed_ranker_voter_{voter.provider}",
                model=voter.model,
                source=picker_source_to_adapter_source(voter.source),
                response_schema=VOTE_SCHEMA,
                # PR-CODEX-GPT55-OUTPUT-EMIT fix-up (Codex MCP catch,
                # 2026-05-26) — mutation_eval voters reuse the same
                # VOTE_SCHEMA + gpt-5.5 A/B/tie shape as the ranker
                # voter pathway. Without an explicit effort pin they
                # would inherit the SubTask difficulty default
                # ("medium" → ``_DIFFICULTY_TO_EFFORT["medium"]``)
                # and reproduce the smoke 20 empty-text failure mode
                # outside the ranker phase. Same ctx7 grounding as
                # ``plugins/seed_generation/agents/ranker.py`` —
                # OpenAI Responses API "Reasoning effort" guidance
                # for single-shot classification + short rationale.
                effort="low",
            )
        )
    results = await manager.adelegate(tasks, announce=False)

    wins = 0
    losses = 0
    ties = 0
    providers_voted: set[str] = set()
    models_voted: list[str] = []

    tasks_by_id = {t.task_id: t for t in tasks}
    for result in results:
        if not result.success:
            log.warning(
                "mutation_eval: voter %s failed — %s",
                result.task_id,
                result.error or "unknown",
            )
            continue
        parsed = parse_structured_output(
            result.output,
            required_fields=_REQUIRED_VOTE_FIELDS,
        )
        if parsed is None:
            log.warning(
                "mutation_eval: voter %s returned malformed vote (output dropped)",
                result.task_id,
            )
            continue
        winner = parsed.get("winner", "")
        if winner not in _VALID_WINNERS:
            log.warning(
                "mutation_eval: voter %s emitted invalid winner=%r (expected A/B/tie)",
                result.task_id,
                winner,
            )
            continue
        # Read voter identity from typed args (not from reverse-parsed
        # task_id) — Codex MCP catch (2026-05-26). args was empty pre-
        # fix; mutation_eval now populates it explicitly above.
        task = tasks_by_id.get(result.task_id)
        if task is not None:
            providers_voted.add(str(task.args.get("voter_provider", "")))
            models_voted.append(str(task.args.get("voter_model", task.model)))
        if winner == "B":
            wins += 1
        elif winner == "A":
            losses += 1
        else:
            ties += 1

    decisive = wins + losses
    pairwise_win_rate = wins / decisive if decisive > 0 else 0.5
    return MutationEvalResult(
        wins=wins,
        losses=losses,
        ties=ties,
        pairwise_win_rate=pairwise_win_rate,
        provider_diversity=len(providers_voted),
        voter_models=tuple(models_voted),
    )
