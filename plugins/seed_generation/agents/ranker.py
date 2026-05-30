"""Ranker agent — Phase E of the seed generation (Elo tournament + 3-judge panel).

For each pairwise match in the tournament plan, the Ranker fans out 3
voter sub-agents (one per :class:`VoterBinding` from the picker output)
and majority-votes to determine the match winner. The
:func:`plugins.seed_generation.tournament.apply_match` update is applied
in place to a rolling ``elo_ratings`` dict; final survivors are the
top-K by descending rating.

Per ADR-001 §3 Ranking + the panel diversity gate (manifest-time
``required_diversity_providers ≥ 2``, runtime-validated by the S5.5
picker), the Ranker NEVER judges directly — it only orchestrates the
voters.

Per-voter sub-agent contract (``plugins/seed_generation/agents/ranker.md`` +
voter-specific judges):

.. code-block:: json

   {
     "match_id": "m007",
     "winner": "A" | "B" | "tie",
     "rationale": "<= 200 tokens"
   }

P-checklist application:

- **P1 Stub Fidelity Audit** — tests cover the *completion-order*
  pairing path (results returned in reverse submission order, mixed
  failures, malformed votes).
- **P7 Caller-Callee Contract Pair Read** — the Ranker consumes the
  picker's ``voters`` list and the orchestrator's
  ``state.candidates`` + ``state.pilot_scores`` outputs. Emits
  ``state.elo_ratings`` + ``state.survivors``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plugins.seed_generation.agents.base import (
    BaseSeedAgent,
    SeedAgentResult,
    parse_structured_output,
    sum_sub_result_tokens,
)
from plugins.seed_generation.json_schemas import VOTE_SCHEMA
from plugins.seed_generation.orchestrator import PipelineState
from plugins.seed_generation.picker import VoterBinding
from plugins.seed_generation.tournament import (
    DEFAULT_K_FACTOR,
    DEFAULT_TOP_K,
    MatchOutcome,
    MatchPlan,
    apply_match,
    majority_winner,
    plan_matches,
    top_k,
)

if TYPE_CHECKING:
    from core.agent.sub_agent import SubAgentManager, SubTask

log = logging.getLogger(__name__)

__all__ = ["Ranker"]


_DEFAULT_RANKER_MODEL = "claude-opus-4-7"
_TASK_TYPE = "seed-ranker-vote"
_PARTIAL_CHECKPOINT_EVERY_MATCHES = 10
_PARTIAL_CHECKPOINT_EVERY_SECONDS = 120.0

_REQUIRED_VOTE_FIELDS = ("match_id", "winner", "rationale")
_VALID_WINNER_LABELS = frozenset({"A", "B", "tie"})

# PR-VOTER-PROMPT-ANTI-PHANTOM (2026-05-26, Codex MCP catch) — explicit
# sentinel body when ``_read_candidate_bodies`` can't open or decode a
# candidate .md file. Pre-fix the helper emitted ``""`` and the prompt
# still asserted "Both seed bodies are fully present", so the voter
# would judge against an invisible mismatch. The sentinel surfaces the
# gap directly in the dialogue.jsonl trace + lets a future ranker
# guard escalate to "quorum impossible for this match" rather than
# dispatching a body-less voter call.
_CANDIDATE_BODY_UNAVAILABLE = (
    "[CANDIDATE_BODY_UNAVAILABLE: path={path!r} error={exc!r}]\n"
    "(The orchestrator could not read this candidate's seed body. "
    'Treat this match as ambiguous — emit ``winner: "tie"`` and note '
    "the unavailability in your rationale.)"
)


def _serialise_match_outcome(outcome: MatchOutcome) -> dict[str, Any]:
    return {
        "match_id": outcome.match_id,
        "a": outcome.a,
        "b": outcome.b,
        "winner": outcome.winner,
        "votes": list(outcome.votes),
        "voter_ids": list(outcome.voter_ids),
    }


# PR-LANE-CAP-TIGHTER (v0.99.76, 2026-05-27) — phase-local
# concurrency cap for the ranker's ``asyncio.gather`` match-dispatch
# burst. Sits on top of the per-adapter lanes (claude_cli=3 /
# openai_api=6) and is sized to match them exactly so the gather
# submission queue doesn't grow a hidden depth.
#
# Concurrency budget (default 3-voter panel = 2 codex + 1 claude-cli):
#   3 matches inflight * 3 voters = 9 voter tasks
#     - claude-cli tasks: 3 (1 per match) — saturates claude_cli_lane=3
#     - codex tasks: 6 (2 per match)     — saturates openai_api_lane=6
#   Net: all three caps balance with zero queue behind them.
#
# Why 3 (and not the prior v0.99.75 cap 5): cap 5 still needed ~3 GB
# of free host RAM per burst, but the operator's M3 16 GB host
# typically has 150-750 MB unused at steady state (Slack / Chrome /
# Notion all running). Cap 3 brings the peak burst to ~1.5 GB and
# survives without requiring the operator to close desktop apps
# first — the "safe default" goal.
#
# Operators on bigger hardware should raise all three lockstep,
# e.g. 32 GB host: ``RANKER_MAX_INFLIGHT_MATCHES=6`` +
# ``CLAUDE_CLI_LANE_MAX=6`` + ``OPENAI_API_LANE_MAX=12``.
DEFAULT_RANKER_MAX_INFLIGHT_MATCHES = 3
"""Default match-dispatch cap sized to the local-RSS-safe ceiling on
a 16 GB host (see module-level comment). Operator override via
:data:`RANKER_MAX_INFLIGHT_MATCHES_ENV`."""

RANKER_MAX_INFLIGHT_MATCHES_ENV = "GEODE_RANKER_MAX_INFLIGHT_MATCHES"
"""Operator override — raise / lower the phase-local cap. Invalid
values silently fall back to the default (lane should never harden
into "no slots" from a typo)."""


def resolve_ranker_max_inflight_matches() -> int:
    """Resolve the effective phase-local match-dispatch cap.

    Defaults to :data:`DEFAULT_RANKER_MAX_INFLIGHT_MATCHES`; honours
    :data:`RANKER_MAX_INFLIGHT_MATCHES_ENV` as a positive integer.
    Non-positive / non-integer overrides fall back silently — the cap
    must never harden into 0 mid-run from a typo.
    """
    import os

    raw = os.environ.get(RANKER_MAX_INFLIGHT_MATCHES_ENV, "").strip()
    if not raw:
        return DEFAULT_RANKER_MAX_INFLIGHT_MATCHES
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_RANKER_MAX_INFLIGHT_MATCHES
    if parsed <= 0:
        return DEFAULT_RANKER_MAX_INFLIGHT_MATCHES
    return parsed


class Ranker(BaseSeedAgent):
    """Elo tournament orchestrator with 3-voter judge panel.

    Constructor accepts the resolved ``voters`` list from the S5.5
    picker so the Ranker is decoupled from manifest loading — tests
    can build a 3-voter list explicitly without touching the file
    system or the Petri source-table cross-validator.
    """

    def __init__(
        self,
        manager: SubAgentManager,
        voters: list[VoterBinding],
        *,
        model: str = _DEFAULT_RANKER_MODEL,
        source: str = "auto",
        manifest_role: dict[str, object] | None = None,
        k_factor: float = DEFAULT_K_FACTOR,
        survivors_k: int = DEFAULT_TOP_K,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(
            role="ranker",
            model=model,
            source=source,
            manifest_role=manifest_role,
        )
        if len(voters) < 2:
            raise ValueError(
                f"Ranker requires ≥ 2 voters (panel diversity gate); got {len(voters)}"
            )
        self._manager = manager
        self._voters = voters
        self._k_factor = k_factor
        self._survivors_k = survivors_k
        self._rng = rng

    async def aexecute(self, state: PipelineState) -> SeedAgentResult:
        """Run the Elo tournament against ``state.candidates`` survivors."""
        if not state.candidates:
            return SeedAgentResult(
                role=self.role,
                status="error",
                error_category="validation",
                error_message=(
                    "Ranker requires state.candidates to be non-empty — "
                    "did upstream phases drop all survivors?"
                ),
            )
        if len(state.candidates) < 2:
            # Single candidate trivially survives; emit a degenerate result
            # rather than raising, so the pipeline can complete the run.
            sole = state.candidates[0]["id"]
            return SeedAgentResult(
                role=self.role,
                output={
                    "elo_ratings": {sole: 1000.0},
                    "survivors": [sole],
                },
            )

        candidate_ids = [c["id"] for c in state.candidates]
        # Snapshot pilot dim_means per candidate (read-only) so the
        # voter-task builder can surface the empirical signal to each
        # judge per plugins/seed_generation/agents/ranker.md contract. Absent
        # pilot_scores → empty dict (judges fall back to seed bodies).
        pilot_means: dict[str, dict[str, Any]] = {}
        for cid in candidate_ids:
            entry = state.pilot_scores.get(cid, {})
            means = entry.get("dim_means", {}) if isinstance(entry, dict) else {}
            if isinstance(means, dict):
                pilot_means[cid] = means
        # PR-VOTER-PROMPT-ANTI-PHANTOM (2026-05-26) — pre-fix the
        # voter handoff sent a *literal* relative path string
        # ``"run_dir/candidates/<cid>.md"`` and instructed the model
        # to "Read both candidate seeds". The model could neither
        # resolve nor read that fake path, so it hallucinated
        # session continuity ("I already read both candidate files
        # in the previous turn and can answer from context") and
        # exited on turn 1 with empty output (smoke 18
        # vote-m000-anthropic.claude-cli/dialogue.jsonl). Co-scientist
        # (open-coscientist/src/open_coscientist/nodes/ranking.py
        # ``debate_pair`` flow) instead inlines the full hypothesis
        # body in the user_message — no Read tool needed, no
        # phantom-continuity confusion. Mirror that pattern: read
        # each candidate body once here, pass through ``_play_match``
        # into the handoff. Bounded by ``len(state.candidates) * len(
        # candidate.md)`` ≈ 15 × 2 KB = 30 KB per Ranker invocation;
        # well under any LLM context budget.
        candidate_bodies = self._read_candidate_bodies(state)

        # CSP-8 (2026-05-22) — Proximity now emits clusters
        # (``state.similarity_clusters``) instead of a sparse pairwise
        # graph. Bracket seeding reverts to the legacy random-shuffle
        # policy. The cluster output stays available to the
        # meta_reviewer + operator-readable state.json as a coverage
        # signal but does NOT feed the Elo bracket.
        match_plan = plan_matches(candidate_ids, rng=self._rng)
        from plugins.seed_generation.resume import load_ranker_partial_resume

        resume = load_ranker_partial_resume(
            state.run_dir,
            candidate_ids=candidate_ids,
            match_plan=match_plan,
        )
        ratings = resume.ratings
        log.info(
            "seed-generation ranker: %d candidates → %d matches × %d voters "
            "(resumed=%d pending=%d)",
            len(candidate_ids),
            len(match_plan),
            len(self._voters),
            len(resume.completed_match_ids),
            len(resume.pending_matches),
        )

        outcomes: list[MatchOutcome] = list(resume.outcomes)
        # PR-SEEDS-HIRES (2026-05-26) — accumulate per-match details
        # (voter rationale + Elo before/after deltas) so the hub's
        # tournament page can render the full 3-voter panel breakdown
        # per match. ``state.elo_ratings`` only carries the FINAL ratings;
        # this list carries the per-match trace.
        match_details: list[dict[str, Any]] = []
        # PR-RANKER-PARALLEL (2026-05-26) — dispatch every independent
        # match concurrently, then apply Elo sequentially below. The
        # expensive part is the voter panel call inside ``_play_match``;
        # the rating mutation must stay ordered by ``match_plan`` so the
        # same RNG seed still produces the same final Elo table.
        result_queue: asyncio.Queue[
            tuple[MatchPlan, tuple[MatchOutcome | None, dict[str, Any]]] | None
        ] = asyncio.Queue()
        checkpoint_task: asyncio.Task[None] | None = None
        if state.run_dir is not None and resume.pending_matches:
            checkpoint_task = asyncio.create_task(
                self._partial_checkpoint_loop(
                    run_dir=state.run_dir,
                    match_plan=match_plan,
                    result_queue=result_queue,
                    base_completed_match_ids=list(resume.completed_match_ids),
                    base_ratings=ratings,
                    base_outcomes=outcomes,
                    total_matches=len(match_plan),
                )
            )
        try:
            # PR-LANE-CAP-TIGHTER (v0.99.76, 2026-05-27) — wrap each
            # ``_play_match_with_checkpoint_report`` in a phase-local
            # semaphore acquire so the gather submission queue depth
            # never exceeds :data:`DEFAULT_RANKER_MAX_INFLIGHT_MATCHES`.
            # The per-adapter lanes (claude_cli_lane=3 / openai_api_lane=6)
            # already throttle the downstream subprocess/API calls; this
            # cap keeps the gather "in-flight" task count from balloon-
            # ing past the lane ceiling on a 59-match Loop 1 burst.
            match_semaphore = asyncio.Semaphore(resolve_ranker_max_inflight_matches())

            async def _bounded_play(match: MatchPlan) -> tuple[MatchOutcome | None, dict[str, Any]]:
                async with match_semaphore:
                    return await self._play_match_with_checkpoint_report(
                        match,
                        pilot_means=pilot_means,
                        candidate_bodies=candidate_bodies,
                        result_queue=result_queue,
                    )

            match_results = await asyncio.gather(
                *[_bounded_play(match) for match in resume.pending_matches]
            )
        finally:
            if checkpoint_task is not None:
                await result_queue.put(None)
                with contextlib.suppress(Exception):
                    await checkpoint_task
        for match, (outcome, detail) in zip(resume.pending_matches, match_results, strict=True):
            elo_before = deepcopy(ratings)
            if outcome is None:
                # Detail is still meaningful for quorum-lost matches —
                # surface the partial voter responses in the hub.
                if detail is not None:
                    detail.update(
                        {
                            "winner": None,
                            "elo_before": {
                                match.a: elo_before.get(match.a, 1000.0),
                                match.b: elo_before.get(match.b, 1000.0),
                            },
                            "elo_after": {
                                match.a: elo_before.get(match.a, 1000.0),
                                match.b: elo_before.get(match.b, 1000.0),
                            },
                            "elo_delta_a": 0.0,
                            "elo_delta_b": 0.0,
                            "quorum_lost": True,
                        }
                    )
                    match_details.append(detail)
                continue
            outcomes.append(outcome)
            apply_match(ratings, outcome, k_factor=self._k_factor)
            if detail is not None:
                detail.update(
                    {
                        "winner": outcome.winner,
                        "elo_before": {
                            match.a: elo_before.get(match.a, 1000.0),
                            match.b: elo_before.get(match.b, 1000.0),
                        },
                        "elo_after": {
                            match.a: ratings.get(match.a, 1000.0),
                            match.b: ratings.get(match.b, 1000.0),
                        },
                        "elo_delta_a": ratings.get(match.a, 1000.0)
                        - elo_before.get(match.a, 1000.0),
                        "elo_delta_b": ratings.get(match.b, 1000.0)
                        - elo_before.get(match.b, 1000.0),
                        "quorum_lost": False,
                    }
                )
                match_details.append(detail)

        survivors = top_k(ratings, k=self._survivors_k)
        self._emit_elo_log(state, outcomes, ratings)
        self._persist_tournament_log(state, match_details)
        log.info(
            "seed-generation ranker: %d/%d matches counted, survivors=%s",
            len(outcomes),
            len(match_plan),
            survivors[:3],
        )

        # PR-SEEDGEN-TOKENS (2026-05-30) — total the per-match voter usage
        # stashed on each ``detail["usage"]`` during ``_play_match``. Only
        # freshly-played matches appear in ``match_details`` (resumed runs
        # already counted earlier matches), so no double-counting on resume.
        prompt_tokens = 0
        completion_tokens = 0
        usd_spent = 0.0
        for detail in match_details:
            usage = detail.get("usage")
            if isinstance(usage, dict):
                prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                completion_tokens += int(usage.get("completion_tokens", 0) or 0)
                usd_spent += float(usage.get("usd_spent", 0.0) or 0.0)

        return SeedAgentResult(
            role=self.role,
            output={
                "elo_ratings": ratings,
                "survivors": survivors,
            },
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd_spent=usd_spent,
        )

    async def _play_match_with_checkpoint_report(
        self,
        match: MatchPlan,
        *,
        pilot_means: dict[str, dict[str, Any]],
        candidate_bodies: dict[str, str],
        result_queue: asyncio.Queue[
            tuple[MatchPlan, tuple[MatchOutcome | None, dict[str, Any]]] | None
        ],
    ) -> tuple[MatchOutcome | None, dict[str, Any]]:
        result = await self._play_match(
            match,
            pilot_means=pilot_means,
            candidate_bodies=candidate_bodies,
        )
        await result_queue.put((match, result))
        return result

    async def _partial_checkpoint_loop(
        self,
        *,
        run_dir: Path,
        match_plan: list[MatchPlan],
        result_queue: asyncio.Queue[
            tuple[MatchPlan, tuple[MatchOutcome | None, dict[str, Any]]] | None
        ],
        base_completed_match_ids: list[str],
        base_ratings: dict[str, float],
        base_outcomes: list[MatchOutcome],
        total_matches: int,
    ) -> None:
        """Persist the ordered Elo prefix while match panels run.

        Match calls finish in arbitrary order, but the partial checkpoint
        must only record the deterministic prefix that has been applied
        to Elo in ``match_plan`` order.
        """
        from plugins.seed_generation.checkpointer import write_partial_ranker_checkpoint

        ratings = dict(base_ratings)
        outcomes = list(base_outcomes)
        completed_ids = list(base_completed_match_ids)
        completed_set = set(completed_ids)
        pending_results: dict[str, tuple[MatchOutcome | None, dict[str, Any]]] = {}
        next_idx = 0
        while next_idx < len(match_plan) and match_plan[next_idx].match_id in completed_set:
            next_idx += 1

        last_dump_count = len(completed_ids)
        last_dump_at = time.monotonic()
        force_dump = False

        while True:
            timeout = max(
                0.1,
                _PARTIAL_CHECKPOINT_EVERY_SECONDS - (time.monotonic() - last_dump_at),
            )
            timed_out = False
            try:
                item = await asyncio.wait_for(result_queue.get(), timeout=timeout)
            except TimeoutError:
                timed_out = True
                item = None
                force_dump = True

            if item is None and not timed_out:
                force_dump = True
            elif item is not None:
                match, result = item
                pending_results[match.match_id] = result

            while next_idx < len(match_plan):
                match = match_plan[next_idx]
                if match.match_id in completed_set:
                    next_idx += 1
                    continue
                if match.match_id not in pending_results:
                    break
                result = pending_results.pop(match.match_id)
                outcome, _detail = result
                completed_set.add(match.match_id)
                completed_ids.append(match.match_id)
                if outcome is not None:
                    apply_match(ratings, outcome, k_factor=self._k_factor)
                    outcomes.append(outcome)
                next_idx += 1

            due_by_count = len(completed_ids) - last_dump_count >= _PARTIAL_CHECKPOINT_EVERY_MATCHES
            due_by_time = time.monotonic() - last_dump_at >= _PARTIAL_CHECKPOINT_EVERY_SECONDS
            dirty = len(completed_ids) > last_dump_count
            if dirty and (due_by_count or due_by_time or force_dump):
                try:
                    write_partial_ranker_checkpoint(
                        run_dir,
                        completed_match_ids=completed_ids,
                        partial_ratings=ratings,
                        partial_outcomes_serialised=[
                            _serialise_match_outcome(outcome) for outcome in outcomes
                        ],
                        total_matches=total_matches,
                    )
                except OSError as exc:
                    log.warning(
                        "seed-generation ranker: partial checkpoint write failed — %s",
                        exc,
                    )
                last_dump_count = len(completed_ids)
                last_dump_at = time.monotonic()
                force_dump = False

            if item is None and not timed_out:
                break

    def _read_candidate_bodies(self, state: PipelineState) -> dict[str, str]:
        """Read each candidate's seed .md body once, keyed by candidate id.

        PR-VOTER-PROMPT-ANTI-PHANTOM (2026-05-26) — replaces the
        fake-relative-path handoff with inlined seed bodies so the
        voter sub-agent doesn't need (and can't be tricked into
        hallucinating) a Read tool call.

        Missing / unreadable paths emit a ``_UNAVAILABLE_SENTINEL``
        body (not empty string) — Codex MCP catch (2026-05-26):
        the voter prompt says "Both seed bodies are fully present in
        the handoff", which would be falsely advertised if the body
        silently became ``""``. The sentinel makes the gap visible
        in the dialogue trace + lets a future ranker guard escalate
        to "quorum impossible" rather than dispatching a
        body-less voter call.

        Each candidate .md is read at most once per Ranker
        invocation; for a typical 15-candidate, ~3-5 KB-per-seed run
        that's ~60 KB of disk I/O before the tournament loop kicks
        in. Cumulative voter prompt size is bounded per-call (each
        voter sees exactly two bodies), not aggregated; so the per-
        call context budget is the constraint, not total disk read.
        """
        from pathlib import Path

        bodies: dict[str, str] = {}
        for candidate in state.candidates:
            cid = candidate.get("id")
            path = candidate.get("path")
            if not cid or not path:
                continue
            try:
                bodies[cid] = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                log.warning(
                    "seed-generation ranker: failed to read candidate %s body "
                    "from %s — %s; voter will see UNAVAILABLE sentinel",
                    cid,
                    path,
                    exc,
                )
                bodies[cid] = _CANDIDATE_BODY_UNAVAILABLE.format(path=path, exc=exc)
        return bodies

    async def _play_match(
        self,
        match: MatchPlan,
        *,
        pilot_means: dict[str, dict[str, Any]] | None = None,
        candidate_bodies: dict[str, str] | None = None,
    ) -> tuple[MatchOutcome | None, dict[str, Any]]:
        """Dispatch the 3 voters for one match.

        Returns a tuple ``(outcome, detail)`` where:

        - ``outcome`` is the legacy :class:`MatchOutcome` used by the
          Elo update — ``None`` when quorum is lost (< 2 valid votes).
        - ``detail`` is a rich dict consumed by the hub's tournament
          page renderer: ``{match_id, candidate_a, candidate_b, votes:
          [{voter_id, voter_model, voter_provider, vote, rationale,
          duration_ms}, ...]}``. Always non-empty (so the hub can
          render quorum-lost matches too).
        """
        tasks = self._build_voter_tasks(
            match,
            pilot_means=pilot_means or {},
            candidate_bodies=candidate_bodies or {},
        )
        results = await self._manager.adelegate(tasks, announce=False)
        tasks_by_id: dict[str, Any] = {t.task_id: t for t in tasks}

        # PR-SEEDGEN-TOKENS (2026-05-30) — sum every voter sub-agent's LLM
        # usage for this match. payg voters (API key) report real numbers;
        # subscription / CLI voters report 0 (usage not exposed). Stashed on
        # ``detail["usage"]`` so the phase-level rollup below can total it.
        match_pt, match_ct, match_usd = sum_sub_result_tokens(results)

        votes: list[str] = []
        voter_ids: list[str] = []
        voter_details: list[dict[str, Any]] = []
        for result in results:
            task = tasks_by_id.get(result.task_id)
            if task is None:
                continue
            voter_id = str(task.args.get("voter_id", "?"))
            voter_model = str(task.args.get("voter_model", ""))
            voter_source = str(task.args.get("voter_source", ""))
            duration_ms = float(getattr(result, "duration_ms", 0.0) or 0.0)
            vote_value: str | None = None
            rationale = ""
            parse_error: str | None = None
            if not result.success:
                parse_error = "voter_call_failed"
            else:
                parsed = parse_structured_output(
                    result.output,
                    required_fields=_REQUIRED_VOTE_FIELDS,
                    pin_field="match_id",
                    pin_value=match.match_id,
                )
                if parsed is None:
                    parse_error = "structured_output_parse_failed"
                else:
                    winner = parsed.get("winner")
                    if winner not in _VALID_WINNER_LABELS:
                        log.warning(
                            "seed-generation ranker: match=%s voter=%s invalid winner=%r",
                            match.match_id,
                            voter_id,
                            winner,
                        )
                        parse_error = "invalid_winner_label"
                    else:
                        vote_value = str(winner)
                        rationale = str(parsed.get("rationale") or "")
            voter_details.append(
                {
                    "voter_id": voter_id,
                    "voter_model": voter_model,
                    "voter_provider": voter_source,
                    "vote": vote_value,
                    "rationale": rationale,
                    "duration_ms": duration_ms,
                    "parse_error": parse_error,
                }
            )
            if vote_value is not None:
                votes.append(vote_value)
                voter_ids.append(voter_id)

        detail: dict[str, Any] = {
            "match_id": match.match_id,
            "candidate_a": match.a,
            "candidate_b": match.b,
            "votes": voter_details,
            "usage": {
                "prompt_tokens": match_pt,
                "completion_tokens": match_ct,
                "usd_spent": match_usd,
            },
        }

        if len(votes) < 2:
            # Need ≥ 2 votes to declare a majority. Quorum loss → skip the
            # match entirely so a single judge's failure can't push a
            # candidate up or down.
            log.warning(
                "seed-generation ranker: match=%s quorum lost (%d/%d votes)",
                match.match_id,
                len(votes),
                len(self._voters),
            )
            return None, detail
        winner_label = majority_winner(tuple(votes))  # type: ignore[arg-type]
        return (
            MatchOutcome(
                match_id=match.match_id,
                a=match.a,
                b=match.b,
                winner=winner_label,
                votes=tuple(votes),  # type: ignore[arg-type]
                voter_ids=tuple(voter_ids),
            ),
            detail,
        )

    def _build_voter_tasks(
        self,
        match: MatchPlan,
        *,
        pilot_means: dict[str, dict[str, Any]],
        candidate_bodies: dict[str, str],
    ) -> list[SubTask]:
        """One SubTask per voter for one match."""
        from core.agent.sub_agent import SubTask

        means_a = pilot_means.get(match.a, {})
        means_b = pilot_means.get(match.b, {})
        body_a = candidate_bodies.get(match.a, "")
        body_b = candidate_bodies.get(match.b, "")
        tasks: list[SubTask] = []
        from plugins.seed_generation.agents.base import picker_source_to_adapter_source

        for idx, voter in enumerate(self._voters):
            voter_id = f"{voter.provider}.{voter.source}"
            tasks.append(
                SubTask(
                    # PR-CODEX-GPT55-OUTPUT-EMIT fix-up (Codex MCP catch,
                    # 2026-05-26) — the default judge panel in
                    # ``plugins/seed_generation/seed_generation.plugin.toml``
                    # ships with TWO ``openai.openai-codex`` voters
                    # (cost-balance: 2x codex + 1x claude-cli). Pre-fix
                    # the task_id was ``vote-{match_id}-{provider}.{source}``
                    # which collided for both codex voters;
                    # ``SubAgentManager._deduplicate`` then silently
                    # dropped one, so the advertised 3-voter panel
                    # actually dispatched only 2 voters per match.
                    # The per-voter ordinal ``v{idx:02d}`` disambiguates
                    # duplicate (provider, source) bindings — same
                    # pattern already used by ``mutation_eval.py``.
                    task_id=f"vote-{match.match_id}-v{idx:02d}-{voter_id}",
                    description=self._build_description(
                        match=match,
                        voter=voter,
                        means_a=means_a,
                        means_b=means_b,
                        body_a=body_a,
                        body_b=body_b,
                    ),
                    task_type=_TASK_TYPE,
                    args={
                        "match_id": match.match_id,
                        "candidate_a": match.a,
                        "candidate_b": match.b,
                        "pilot_means_a": means_a,
                        "pilot_means_b": means_b,
                        "voter_id": voter_id,
                        "voter_model": voter.model,
                        "voter_source": voter.source,
                    },
                    agent=f"seed_ranker_voter_{voter.provider}",
                    source=picker_source_to_adapter_source(voter.source),
                    # PR-VOTER-PROVIDER-WIRE (2026-05-25) — per-voter
                    # model override. Pre-fix SubTask only carried
                    # ``source``; ``worker_model`` fell back to the
                    # parent's ``settings.model`` so the resolved
                    # adapter ignored the voter's binding (smoke 17
                    # RESUME: claude-cli voter dispatched via codex-cli
                    # because ``_resolve_provider(settings.model)``
                    # returned the parent's provider, not the voter's).
                    # Now ``task.model = voter.model`` wins in
                    # ``SubAgentManager._build_request``, so
                    # ``(provider, source)`` together pick the right
                    # adapter via ``resolve_for``.
                    model=voter.model,
                    # PR-JSON-WIRE (2026-05-25) — force vote JSON shape.
                    response_schema=VOTE_SCHEMA,
                    # PR-GPT55-EMPTY-OUTPUT-EMIT (Sprint G,
                    # 2026-05-26) — pin ``effort="none"`` for vote
                    # tasks. Supersedes PR-CODEX-GPT55-OUTPUT-EMIT's
                    # ``effort="low"`` which smoke 21 confirmed
                    # ineffective: 7+ codex-oauth-empty-text dumps
                    # produced even with effort="low" (gpt-5.5 still
                    # burned 60-624 output tokens on encrypted
                    # reasoning, output_text="" 100% of calls).
                    # ctx7 OpenAI Responses API spec
                    # (``/websites/developers_openai_api`` →
                    # "Sampling Parameters"): ``reasoning_effort``
                    # enum is ``none, minimal, low, medium, high,
                    # xhigh``; ``none`` disables reasoning entirely
                    # so the model emits user-facing text directly.
                    # The voter A/B/tie task is a single-step
                    # classification — no reasoning depth required.
                    # ``max_output_tokens`` is NOT viable on the
                    # codex-oauth path — the backend rejects it with
                    # 400 ``Unsupported parameter`` (pinned by
                    # ``test_codex_kwargs_does_not_send_max_output_tokens``
                    # and ``core/llm/providers/codex.py:325``).
                    #
                    # PR-VOTER-EFFORT-OVERRIDE-HATCH (Sprint G/H
                    # follow-up, 2026-05-26) — operator override path.
                    # Empty ``voter.effort`` (no operator override in
                    # ``~/.geode/config.toml``) keeps the Sprint G
                    # default ``"none"``; non-empty value flips this
                    # voter to the operator-chosen effort without
                    # requiring a code redeploy. The adapter validates
                    # the value against the model's
                    # ``reasoning_effort_values`` at request time.
                    effort=voter.effort or "none",
                )
            )
        return tasks

    def _build_description(
        self,
        *,
        match: MatchPlan,
        voter: VoterBinding,
        means_a: dict[str, Any],
        means_b: dict[str, Any],
        body_a: str = "",
        body_b: str = "",
    ) -> str:
        """Compose the per-voter user message for the sub-agent.

        Includes Pilot dim_means alongside the *inlined* seed bodies so
        the judge (per ``plugins/seed_generation/agents/ranker.md``)
        can weigh empirical engagement signal against the seed text.
        When pilot_scores is missing for a candidate, the
        corresponding dim_means is empty and the judge falls back to
        seed body alone.

        PR-VOTER-PROMPT-ANTI-PHANTOM (2026-05-26) — pre-fix the
        handoff sent a *literal* ``run_dir/candidates/<cid>.md``
        relative-path string and instructed the model to "Read both
        candidate seeds". The model could neither resolve the path
        (cwd was a per-task isolated dir per PR-RESUME-NO-PERSIST-FIX,
        not the orchestrator run_dir) nor call Read with that fake
        path, so it hallucinated session continuity ("I already read
        both candidate files in the previous turn and can answer
        from context") and exited turn 1 with empty output. Now the
        full seed body is inlined per co-scientist
        (open-coscientist/src/open_coscientist/nodes/ranking.py
        debate_pair pattern) — no Read tool needed, no
        phantom-continuity confusion.
        """
        from plugins.seed_generation.handoff_schemas import embed_handoff

        prose = (
            f"Judge ONE seed-candidate match for the seed-generation Elo "
            f"tournament. See the HANDOFF CONTEXT block below for match_id, "
            f"target_dim, the two candidates' inlined seed bodies "
            f"(``candidate_a.body`` / ``candidate_b.body``), and per-candidate "
            f"pilot dim_means. You are voter "
            f"{voter.provider}.{voter.source} ({voter.model!r}). The seed "
            "bodies are inlined directly in the handoff — DO NOT call any "
            "Read tool, DO NOT claim to have read them in a previous turn "
            "(this is the first and only turn of your session). Weigh the "
            "inlined bodies + dim_means signal and apply the rubric in your "
            "system prompt.\n\n"
            "If either candidate's body starts with "
            "``[CANDIDATE_BODY_UNAVAILABLE:`` the orchestrator failed to "
            "read it from disk — follow the sentinel's instructions "
            '(``winner: "tie"`` + note the unavailability in your '
            "rationale).\n\n"
            "Your FINAL response must be ONLY the JSON object matching the "
            "VOTE_SCHEMA: "
            '`{"match_id": "<id>", "winner": "A"|"B"|"tie", "rationale": "<= 200 tokens"}`. '
            "No prose summary, no preamble. Start with `{` and end with `}`. "
            "Do not skip the rationale."
        )
        means_a_clean = {k: v for k, v in means_a.items() if isinstance(v, (int, float))}
        means_b_clean = {k: v for k, v in means_b.items() if isinstance(v, (int, float))}
        handoff: dict[str, Any] = {
            "match_id": match.match_id,
            "target_dim": getattr(match, "target_dim", "") or "",
            "candidate_a": {
                "id": match.a,
                "body": body_a,
                "pilot_means": means_a_clean,
            },
            "candidate_b": {
                "id": match.b,
                "body": body_b,
                "pilot_means": means_b_clean,
            },
        }
        return embed_handoff(prose, handoff)

    def _emit_elo_log(
        self,
        state: PipelineState,
        outcomes: list[MatchOutcome],
        ratings: dict[str, float],
    ) -> None:
        """Persist per-match log to ``<run_dir>/elo_log.tsv``.

        Per the seed_ranker AgentDef contract — TSV is commit-friendly
        and integrates with the S10 ``results.tsv`` consumer. Skipped
        when ``state.run_dir`` is unset (test fixtures often omit it);
        the Ranker's primary signal stays the in-memory
        ``output["elo_ratings"]``.
        """
        if state.run_dir is None:
            return
        log_path = state.run_dir / "elo_log.tsv"
        try:
            state.run_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("w", encoding="utf-8") as fh:
                # P1a — prepend gen_tag so cross-generation joins work
                # without parsing the run_dir path.
                fh.write("gen_tag\tmatch_id\ta\tb\twinner\tvotes\tvoter_ids\trating_a\trating_b\n")
                for o in outcomes:
                    fh.write(
                        "\t".join(
                            [
                                state.gen_tag,
                                o.match_id,
                                o.a,
                                o.b,
                                o.winner,
                                ",".join(o.votes),
                                ",".join(o.voter_ids),
                                f"{ratings.get(o.a, 0.0):.2f}",
                                f"{ratings.get(o.b, 0.0):.2f}",
                            ]
                        )
                        + "\n"
                    )
        except OSError as exc:
            log.warning(
                "seed-generation ranker: failed to write elo_log.tsv at %s: %s",
                log_path,
                exc,
            )

    def _persist_tournament_log(
        self,
        state: PipelineState,
        match_details: list[dict[str, Any]],
    ) -> None:
        """Persist full per-match record (3-voter panel + Elo delta) to tournament.json.

        PR-SEEDS-HIRES (2026-05-26) — hub renders this on the per-run
        ``/tournament/`` page. ``elo_log.tsv`` (sibling writer) still
        carries the compact TSV view that the S10 results.tsv consumer
        reads; the JSON variant is observability-only.

        Schema::

            {
              "run_id": "...",
              "gen_tag": "...",
              "voter_panel": [{"voter_id": ..., "voter_model": ..., "voter_provider": ...}],
              "matches": [
                {
                  "match_id": "m007",
                  "candidate_a": "...",
                  "candidate_b": "...",
                  "winner": "A" | "B" | "tie" | null,
                  "quorum_lost": bool,
                  "votes": [
                    {"voter_id", "voter_model", "voter_provider", "vote",
                     "rationale", "duration_ms", "parse_error"},
                    ...
                  ],
                  "elo_before": {"a": float, "b": float},
                  "elo_after": {"a": float, "b": float},
                  "elo_delta_a": float,
                  "elo_delta_b": float
                }
              ]
            }

        Skipped when ``state.run_dir`` is unset (test runs). Failures
        log WARNING — observability never crashes the run.
        """
        if state.run_dir is None:
            return
        payload = {
            "run_id": state.run_id,
            "gen_tag": state.gen_tag,
            "voter_panel": [
                {
                    "voter_id": f"{v.provider}.{v.source}",
                    "voter_model": v.model,
                    "voter_provider": v.source,
                }
                for v in self._voters
            ],
            "matches": match_details,
        }
        try:
            state.run_dir.mkdir(parents=True, exist_ok=True)
            target = state.run_dir / "tournament.json"
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning(
                "seed-generation ranker: failed to write tournament.json at %s: %s",
                state.run_dir,
                exc,
            )
