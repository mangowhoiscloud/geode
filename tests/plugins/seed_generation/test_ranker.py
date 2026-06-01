"""Tests for ``plugins.seed_generation.agents.ranker``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — `_ReverseOrderManager` returns votes in
  reverse submission order to simulate completion-order. Tests verify
  Ranker still pairs by task_id (via `parse_structured_output`'s
  pin_field) rather than position.
- **P7 Caller-Callee Contract** — vote schema (match_id / winner /
  rationale) + winner whitelist enforced via `_REQUIRED_VOTE_FIELDS`
  + `_VALID_WINNER_LABELS`.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, cast

import pytest
from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.ranker import Ranker
from plugins.seed_generation.orchestrator import PipelineState
from plugins.seed_generation.picker import VoterBinding


def _voters() -> list[VoterBinding]:
    return [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="claude-haiku-4-5", provider="anthropic", source="api_key"),
    ]


def _state_with_candidates(n: int) -> PipelineState:
    state = PipelineState(
        run_id="t-ranker",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
    )
    state.candidates = [
        {
            "id": f"c-{i:02d}",
            "path": f"fake-run/candidates/c-{i:02d}.md",
            "target_dim": "broken_tool_use",
            "gen_tag": "gen2",
            "task_id": f"gen-c-{i:02d}",
            "duration_ms": 1000.0,
        }
        for i in range(n)
    ]
    return state


def _good_vote(match_id: str, winner: str = "A") -> dict[str, Any]:
    return {
        "match_id": match_id,
        "winner": winner,
        "rationale": "test rationale",
    }


class _AlwaysAWinsManager:
    """All voters say A wins on every match."""

    def __init__(self) -> None:
        self.received_tasks: list[SubTask] = []

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks.extend(tasks)
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output=_good_vote(t.args["match_id"], winner="A"),
                duration_ms=10.0,
            )
            for t in tasks
        ]


class _SplitVotesManager:
    """First voter A, second B, third tie → 3-way split → tie outcome."""

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        winners = ["A", "B", "tie"]
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output=_good_vote(t.args["match_id"], winner=winners[i % 3]),
                duration_ms=10.0,
            )
            for i, t in enumerate(tasks)
        ]


class _OneFailureManager:
    """1 voter fails per match — 2 votes survive → quorum still met."""

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        results: list[SubResult] = []
        for i, t in enumerate(tasks):
            if i % 3 == 0:
                results.append(
                    SubResult(
                        task_id=t.task_id,
                        description=t.description,
                        success=False,
                        error="forced",
                        duration_ms=10.0,
                    )
                )
            else:
                results.append(
                    SubResult(
                        task_id=t.task_id,
                        description=t.description,
                        success=True,
                        output=_good_vote(t.args["match_id"], winner="A"),
                        duration_ms=10.0,
                    )
                )
        return results


class _MostFailManager:
    """2 of 3 voters fail per match → quorum lost → match skipped."""

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        results: list[SubResult] = []
        for i, t in enumerate(tasks):
            if i % 3 < 2:
                results.append(
                    SubResult(
                        task_id=t.task_id,
                        description=t.description,
                        success=False,
                        error="forced",
                        duration_ms=10.0,
                    )
                )
            else:
                results.append(
                    SubResult(
                        task_id=t.task_id,
                        description=t.description,
                        success=True,
                        output=_good_vote(t.args["match_id"], winner="A"),
                        duration_ms=10.0,
                    )
                )
        return results


class _DelayedAlwaysAWinsManager:
    """All voters say A wins, with a sleep that exposes match concurrency."""

    def __init__(self) -> None:
        self.received_tasks: list[SubTask] = []
        self.active = 0
        self.max_active = 0
        self.started_match_ids: list[str] = []
        self.finished_match_ids: list[str] = []

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        self.received_tasks.extend(tasks)
        match_id = str(tasks[0].args["match_id"]) if tasks else "unknown"
        self.started_match_ids.append(match_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        self.finished_match_ids.append(match_id)
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output=_good_vote(t.args["match_id"], winner="A"),
                duration_ms=10.0,
            )
            for t in tasks
        ]


def test_ranker_requires_two_voters() -> None:
    with pytest.raises(ValueError, match=r"requires"):
        Ranker(manager=_AlwaysAWinsManager(), voters=[_voters()[0]])  # type: ignore[arg-type]


def test_ranker_validates_empty_candidates() -> None:
    state = PipelineState(
        run_id="t",
        target_dim="x",
        gen_tag="gen2",
        candidates_requested=3,
    )
    manager = _AlwaysAWinsManager()
    result = asyncio.run(Ranker(manager=manager, voters=_voters()).aexecute(state))  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_ranker_single_candidate_short_circuits() -> None:
    state = _state_with_candidates(1)
    manager = _AlwaysAWinsManager()
    result = asyncio.run(Ranker(manager=manager, voters=_voters()).aexecute(state))  # type: ignore[arg-type]
    assert result.success
    assert result.output["survivors"] == ["c-00"]


def test_ranker_produces_elo_ratings_and_survivors() -> None:
    state = _state_with_candidates(4)
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        rng=random.Random(42),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    ratings = result.output["elo_ratings"]
    survivors = result.output["survivors"]
    assert isinstance(ratings, dict)
    assert isinstance(survivors, list)
    assert set(ratings.keys()) == {c["id"] for c in state.candidates}
    assert len(survivors) > 0


def test_ranker_dispatches_3_voters_per_match() -> None:
    state = _state_with_candidates(3)
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    asyncio.run(ranker.aexecute(state))
    # Each match has 3 voters; total tasks = 3 * match_count
    assert len(manager.received_tasks) % 3 == 0


def test_ranker_dispatches_matches_concurrently() -> None:
    """PR-RANKER-PARALLEL — independent matches are fanned out together."""
    state = _state_with_candidates(5)
    manager = _DelayedAlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    assert manager.max_active > 1, (
        "Ranker should dispatch multiple match panels concurrently; "
        f"observed max_active={manager.max_active}"
    )
    assert len(manager.started_match_ids) == len(manager.finished_match_ids)


def test_ranker_applies_elo_after_parallel_dispatch_in_match_plan_order() -> None:
    """Elo remains deterministic even when match calls complete asynchronously."""
    from plugins.seed_generation.tournament import (
        MatchOutcome,
        apply_match,
        initial_ratings,
        plan_matches,
    )

    seed = 42
    state = _state_with_candidates(4)
    manager = _DelayedAlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        rng=random.Random(seed),
    )
    result = asyncio.run(ranker.aexecute(state))

    candidate_ids = [c["id"] for c in state.candidates]
    expected = initial_ratings(candidate_ids)
    voter_ids = tuple(f"{v.provider}.{v.source}" for v in _voters())
    for match in plan_matches(candidate_ids, rng=random.Random(seed)):
        apply_match(
            expected,
            MatchOutcome(
                match_id=match.match_id,
                a=match.a,
                b=match.b,
                winner="A",
                votes=("A", "A", "A"),
                voter_ids=voter_ids,
            ),
        )
    assert result.output["elo_ratings"] == expected
    assert manager.max_active > 1


def test_ranker_writes_partial_checkpoint(tmp_path: Any) -> None:
    """PR-RANKER-PARTIAL-CHECKPOINT — final prefix is resumable."""
    from plugins.seed_generation.checkpointer import load_partial_ranker_checkpoint
    from plugins.seed_generation.tournament import plan_matches

    seed = 7
    state = _state_with_candidates(5)
    state.run_dir = tmp_path
    manager = _DelayedAlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        rng=random.Random(seed),
    )
    result = asyncio.run(ranker.aexecute(state))

    assert result.success
    ck = load_partial_ranker_checkpoint(tmp_path)
    assert ck is not None
    expected_plan = plan_matches([c["id"] for c in state.candidates], rng=random.Random(seed))
    assert ck.total_matches == len(expected_plan)
    assert ck.completed_match_ids == [match.match_id for match in expected_plan]
    assert ck.partial_ratings == result.output["elo_ratings"]


def test_ranker_resumes_from_partial_checkpoint_without_replaying_completed_match(
    tmp_path: Any,
) -> None:
    """A partial checkpoint skips the already-applied match prefix."""
    from plugins.seed_generation.checkpointer import write_partial_ranker_checkpoint
    from plugins.seed_generation.tournament import (
        MatchOutcome,
        apply_match,
        initial_ratings,
        plan_matches,
    )

    seed = 11
    state = _state_with_candidates(4)
    state.run_dir = tmp_path
    candidate_ids = [c["id"] for c in state.candidates]
    match_plan = plan_matches(candidate_ids, rng=random.Random(seed))
    first = match_plan[0]
    voter_ids = tuple(f"{v.provider}.{v.source}" for v in _voters())
    first_outcome = MatchOutcome(
        match_id=first.match_id,
        a=first.a,
        b=first.b,
        winner="A",
        votes=("A", "A", "A"),
        voter_ids=voter_ids,
    )
    partial_ratings = initial_ratings(candidate_ids)
    apply_match(partial_ratings, first_outcome)
    write_partial_ranker_checkpoint(
        tmp_path,
        completed_match_ids=[first.match_id],
        partial_ratings=partial_ratings,
        partial_outcomes_serialised=[
            {
                "match_id": first_outcome.match_id,
                "a": first_outcome.a,
                "b": first_outcome.b,
                "winner": first_outcome.winner,
                "votes": list(first_outcome.votes),
                "voter_ids": list(first_outcome.voter_ids),
            }
        ],
        total_matches=len(match_plan),
    )

    manager = _DelayedAlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        rng=random.Random(seed),
    )
    result = asyncio.run(ranker.aexecute(state))

    expected = initial_ratings(candidate_ids)
    for match in match_plan:
        apply_match(
            expected,
            MatchOutcome(
                match_id=match.match_id,
                a=match.a,
                b=match.b,
                winner="A",
                votes=("A", "A", "A"),
                voter_ids=voter_ids,
            ),
        )
    assert result.output["elo_ratings"] == expected
    assert first.match_id not in manager.started_match_ids
    assert set(manager.started_match_ids) == {match.match_id for match in match_plan[1:]}


def test_ranker_split_votes_become_ties() -> None:
    state = _state_with_candidates(3)
    manager = _SplitVotesManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    # All-tie matches → ratings unchanged
    for cid, rating in result.output["elo_ratings"].items():
        assert rating == 1000.0, f"{cid}: tie should leave rating == 1000.0"


def test_ranker_handles_partial_voter_failure() -> None:
    state = _state_with_candidates(3)
    manager = _OneFailureManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    # 2/3 voters succeeded → quorum met → matches counted
    survivors = result.output["survivors"]
    assert len(survivors) > 0


def test_ranker_skips_match_on_quorum_loss() -> None:
    state = _state_with_candidates(3)
    manager = _MostFailManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    # Quorum lost on every match → ratings all stay at 1000.0
    for rating in result.output["elo_ratings"].values():
        assert rating == 1000.0


def test_ranker_drops_invalid_winner_label() -> None:
    class _BadWinnerManager:
        async def adelegate(self, tasks, *, announce: bool = True) -> list:
            """Async sibling for Phase-C tests."""
            return self.delegate(tasks, announce=announce)

        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output=_good_vote(t.args["match_id"], winner="banana"),
                    duration_ms=10.0,
                )
                for t in tasks
            ]

    state = _state_with_candidates(3)
    ranker = Ranker(
        manager=_BadWinnerManager(),  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    # All votes rejected → quorum lost → no rating change
    for rating in result.output["elo_ratings"].values():
        assert rating == 1000.0


def test_ranker_accepts_text_json_fallback() -> None:
    class _TextJsonManager:
        async def adelegate(self, tasks, *, announce: bool = True) -> list:
            """Async sibling for Phase-C tests."""
            return self.delegate(tasks, announce=announce)

        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output={"text": json.dumps(_good_vote(t.args["match_id"]))},
                    duration_ms=10.0,
                )
                for t in tasks
            ]

    state = _state_with_candidates(3)
    ranker = Ranker(
        manager=_TextJsonManager(),  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success


def test_ranker_announce_false_propagates() -> None:
    class _CapturingManager:
        def __init__(self) -> None:
            self.received_announce: bool | None = None

        async def adelegate(self, tasks, *, announce: bool = True) -> list:
            """Async sibling for Phase-C tests."""
            return self.delegate(tasks, announce=announce)

        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            self.received_announce = announce
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output=_good_vote(t.args["match_id"]),
                    duration_ms=10.0,
                )
                for t in tasks
            ]

    state = _state_with_candidates(3)
    manager = _CapturingManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    asyncio.run(ranker.aexecute(state))
    assert manager.received_announce is False


def test_ranker_match_id_pinned_in_parse() -> None:
    """Even if LLM echoes a wrong match_id, the task's match_id wins."""

    class _WrongMatchIdManager:
        async def adelegate(self, tasks, *, announce: bool = True) -> list:
            """Async sibling for Phase-C tests."""
            return self.delegate(tasks, announce=announce)

        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output={
                        "match_id": "WRONG-from-llm",
                        "winner": "A",
                        "rationale": "x",
                    },
                    duration_ms=10.0,
                )
                for t in tasks
            ]

    state = _state_with_candidates(3)
    ranker = Ranker(
        manager=_WrongMatchIdManager(),  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    # The vote is accepted because match_id is re-pinned from the task,
    # not from the LLM echo. Ratings should update.
    assert result.success
    assert any(r > 1000.0 for r in result.output["elo_ratings"].values())


def test_ranker_survivors_count_respects_k() -> None:
    state = _state_with_candidates(8)
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        survivors_k=3,
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert len(result.output["survivors"]) == 3


def test_ranker_emits_elo_log_tsv(tmp_path: Any) -> None:
    """Ranker writes <run_dir>/elo_log.tsv per AgentDef contract.

    P1a — header now prepends ``gen_tag`` so cross-generation joins work.
    """
    state = _state_with_candidates(3)
    state.run_dir = tmp_path
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    asyncio.run(ranker.aexecute(state))
    log_path = tmp_path / "elo_log.tsv"
    assert log_path.is_file()
    content = log_path.read_text(encoding="utf-8")
    # Header + at least one row
    lines = [line for line in content.splitlines() if line]
    assert lines[0].startswith("gen_tag\tmatch_id\t")
    assert len(lines) > 1
    # Every data row starts with the state's gen_tag.
    for row in lines[1:]:
        assert row.startswith(state.gen_tag + "\t")


def test_ranker_no_elo_log_when_run_dir_unset() -> None:
    """Without state.run_dir, Ranker still completes (test fixtures often omit)."""
    state = _state_with_candidates(3)
    state.run_dir = None
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success


# CSP-8 (2026-05-22) — pre-CSP-8 ``proximity_graph`` tests removed.
# The Ranker no longer consumes ``state.proximity_graph`` (Proximity
# reverted to LLM-clustering pattern); bracket seeding is pure
# random-shuffle. The legacy "Ranker doesn't blow up without graph"
# guard collapses into the rest of the suite's happy-path tests.


def test_ranker_voter_description_includes_pilot_means() -> None:
    """Pilot dim_means flow into the voter task description when present."""
    state = _state_with_candidates(2)
    state.pilot_scores = {
        "c-00": {
            "candidate_id": "c-00",
            "dim_means": {"dim_01": 0.71, "dim_02": 0.55},
            "dim_stderr": {"dim_01": 0.1, "dim_02": 0.2},
            "status": "ok",
        },
        "c-01": {
            "candidate_id": "c-01",
            "dim_means": {"dim_01": 0.42},
            "dim_stderr": {"dim_01": 0.05},
            "status": "ok",
        },
    }
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    asyncio.run(ranker.aexecute(state))
    # At least one task's description should mention dim_01 from pilot means.
    descriptions = [t.description for t in manager.received_tasks]
    assert any("dim_01" in d for d in descriptions), descriptions[:1]


def test_ranker_voter_spawn_carries_per_voter_model() -> None:
    """PR-VOTER-PROVIDER-WIRE (2026-05-25) — each SubTask carries
    ``model=voter.model`` so the worker's adapter resolution honors
    the manifest binding instead of falling back to ``settings.model``.

    Pre-fix evidence (smoke 17 RESUME): voter binding
    ``model="claude-opus-4-7", source="claude-cli"`` was dispatched
    via the codex-cli subprocess adapter because ``SubTask`` carried
    only ``source``; ``worker_model`` fell back to ``settings.model``
    and ``_resolve_provider`` mapped that to an openai key, so
    ``resolve_for("openai", "adapter")`` picked codex-cli instead of
    claude-cli. This test pins the wire so a regression that drops
    the ``model=voter.model`` propagation fails here instead of
    silently re-routing to the wrong adapter.
    """
    state = _state_with_candidates(2)
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=manager,  # type: ignore[arg-type]
        voters=_voters(),
        rng=random.Random(0),
    )
    asyncio.run(ranker.aexecute(state))

    # Voter list from ``_voters()``: claude-sonnet, gpt-5.5, claude-haiku.
    expected_models = [
        ("anthropic", "claude-sonnet-4-6"),
        ("openai", "gpt-5.5"),
        ("anthropic", "claude-haiku-4-5"),
    ]
    # Each match dispatches 3 voters; iterate by 3 and assert.
    assert len(manager.received_tasks) % 3 == 0, "expected 3 voters per match"
    for match_idx in range(0, len(manager.received_tasks), 3):
        for slot, (expected_provider, expected_model) in enumerate(expected_models):
            task = manager.received_tasks[match_idx + slot]
            assert task.model == expected_model, (
                f"voter slot {slot}: expected model {expected_model!r}, "
                f"got {task.model!r}. PR-VOTER-PROVIDER-WIRE regression — "
                f"SubTask.model must carry voter.model so adapter resolution "
                f"picks the right (provider, source) pair."
            )
            # task_id encoding includes voter_id = "{provider}.{source}".
            assert expected_provider in task.task_id


def test_sub_task_model_field_wins_over_settings_default() -> None:
    """SubAgentManager._build_request honors ``task.model`` over
    ``settings.model`` (and over agent_ctx model). This is the
    contract that makes PR-VOTER-PROVIDER-WIRE work — without it,
    every voter would inherit the parent's default model regardless
    of the voter binding.
    """
    from core.agent.sub_agent import SubTask

    # Verify the new field exists on SubTask with the right default.
    t = SubTask(task_id="t-1", description="d", task_type="analyze")
    assert hasattr(t, "model")
    assert t.model == ""  # back-compat default

    # Per-task override.
    t2 = SubTask(task_id="t-2", description="d", task_type="analyze", model="claude-opus-4-7")
    assert t2.model == "claude-opus-4-7"


def test_ranker_voter_task_ids_unique_across_duplicate_bindings() -> None:
    """Two voters sharing (provider, source) produce DISTINCT task_ids.

    PR-CODEX-GPT55-OUTPUT-EMIT fix-up (Codex MCP catch, 2026-05-26).
    The default panel in
    ``plugins/seed_generation/seed_generation.plugin.toml`` ships TWO
    ``openai.openai-codex`` voters (cost-balance: 2x codex + 1x
    claude-cli). Pre-fix the task_id shape
    ``vote-{match_id}-{provider}.{source}`` collided across the two
    codex voters, and ``SubAgentManager._deduplicate`` silently
    dropped one — so the advertised 3-voter panel actually dispatched
    only 2 voters per match. The fix injects a per-voter ordinal
    (``v{idx:02d}``) into the task_id so duplicate bindings stay
    distinct. Same pattern as ``mutation_eval.py``.
    """
    from plugins.seed_generation.tournament import MatchPlan

    # Replicate the default manifest: two duplicate openai-codex bindings
    # plus one claude-cli binding.
    voters = [
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
    ]
    ranker = Ranker(
        manager=_AlwaysAWinsManager(),  # type: ignore[arg-type]
        voters=voters,
        rng=random.Random(0),
    )
    match = MatchPlan(match_id="m000", a="c-00", b="c-01")
    tasks = ranker._build_voter_tasks(
        match,
        pilot_means={"c-00": {}, "c-01": {}},
        candidate_bodies={"c-00": "body a", "c-01": "body b"},
    )

    # 1. One task per voter — never collapsed by dedup.
    assert len(tasks) == 3, (
        f"Ranker must spawn one task per voter (got {len(tasks)} for 3 voters). "
        f"Pre-fix the two duplicate openai-codex bindings collided on task_id "
        f"and SubAgentManager._deduplicate dropped one."
    )

    # 2. All task_ids must be unique.
    task_ids = [t.task_id for t in tasks]
    assert len(set(task_ids)) == 3, (
        f"Voter task_ids must be unique even for duplicate (provider, source) "
        f"bindings — got {task_ids}. Pre-fix shape was "
        f"'vote-{{match_id}}-{{provider}}.{{source}}' which collided."
    )

    # 3. Pin the actual shape so a regression to the un-disambiguated form
    #    fails loudly (not just silently). The ordinal MUST appear in the
    #    task_id string.
    for idx, task in enumerate(tasks):
        assert f"-v{idx:02d}-" in task.task_id, (
            f"Voter {idx} task_id={task.task_id!r} missing the 'v{idx:02d}' "
            f"ordinal — Codex MCP catch (2026-05-26) requires per-voter "
            f"disambiguation in the task_id."
        )


def test_ranker_voter_task_ids_match_mutation_eval_shape() -> None:
    """Cross-module consistency: ranker + mutation_eval share the v-ordinal shape.

    Both modules dispatch the same VOTE_SCHEMA panel; both must
    survive duplicate (provider, source) bindings. Pinning the shape
    here prevents the two from drifting back out of sync.
    """
    from plugins.seed_generation.tournament import MatchPlan

    voters = _voters()
    ranker = Ranker(
        manager=_AlwaysAWinsManager(),  # type: ignore[arg-type]
        voters=voters,
        rng=random.Random(0),
    )
    match = MatchPlan(match_id="match-xy", a="c-00", b="c-01")
    tasks = ranker._build_voter_tasks(
        match,
        pilot_means={"c-00": {}, "c-01": {}},
        candidate_bodies={"c-00": "x", "c-01": "y"},
    )
    # ranker shape: vote-{match_id}-v{idx:02d}-{provider}.{source}
    expected_first = f"vote-match-xy-v00-{voters[0].provider}.{voters[0].source}"
    assert tasks[0].task_id == expected_first, (
        f"Ranker task_id shape drifted from mutation_eval — "
        f"got {tasks[0].task_id!r}, expected {expected_first!r}."
    )


# ── PR-SEEDGEN-DIFFICULTY-SELECTION — difficulty-calibrated survivor pick ──


def _state_with_pilot_difficulty(n: int, hard_idx: int) -> PipelineState:
    """A candidate state where ``c-{hard_idx}`` has the HIGHEST pilot
    target_dim elicitation (hardest seed) regardless of how the Elo
    tournament shakes out. All other candidates carry low target_dim
    elicitation. ``target_dim`` is ``broken_tool_use`` (see
    ``_state_with_candidates``).
    """
    state = _state_with_candidates(n)
    state.pilot_scores = {}
    for i in range(n):
        # The hard candidate elicits 9.0; everyone else a low 1.0.
        target_mean = 9.0 if i == hard_idx else 1.0
        state.pilot_scores[f"c-{i:02d}"] = {
            "candidate_id": f"c-{i:02d}",
            "dim_means": {"broken_tool_use": target_mean},
            "dim_stderr": {"broken_tool_use": 0.1},
            "status": "ok",
        }
    return state


def test_ranker_difficulty_mode_picks_hardest_seed_first() -> None:
    """Difficulty mode surfaces the high-elicitation seed as the #1
    survivor even when Elo would not rank it first."""
    hard_idx = 5
    state = _state_with_pilot_difficulty(8, hard_idx=hard_idx)
    manager = _AlwaysAWinsManager()
    ranker = Ranker(
        manager=cast(Any, manager),
        voters=_voters(),
        selection="difficulty",
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    survivors = result.output["survivors"]
    assert survivors[0] == f"c-{hard_idx:02d}", (
        f"difficulty mode must rank the hardest seed (pilot target_dim 9.0) "
        f"first; got survivors={survivors}"
    )


def test_ranker_difficulty_mode_can_invert_elo_order() -> None:
    """On the SAME final ratings, elo and difficulty modes disagree:
    elo picks its top-rated seed, difficulty picks the high-elicitation
    seed — confirming the modes are genuinely different selection paths."""
    hard_idx = 5
    state_elo = _state_with_pilot_difficulty(8, hard_idx=hard_idx)
    state_diff = _state_with_pilot_difficulty(8, hard_idx=hard_idx)

    elo_ranker = Ranker(
        manager=cast(Any, _AlwaysAWinsManager()),
        voters=_voters(),
        selection="elo",
        rng=random.Random(0),
    )
    diff_ranker = Ranker(
        manager=cast(Any, _AlwaysAWinsManager()),
        voters=_voters(),
        selection="difficulty",
        rng=random.Random(0),
    )
    elo_result = asyncio.run(elo_ranker.aexecute(state_elo))
    diff_result = asyncio.run(diff_ranker.aexecute(state_diff))

    # Same RNG + same manager → identical Elo ratings in both runs.
    assert elo_result.output["elo_ratings"] == diff_result.output["elo_ratings"]
    # Difficulty always leads with the hardest seed; elo leads with its
    # top-Elo seed. The hard seed need not be elo's top, so the two
    # survivor lists differ here (the whole point of the feature).
    assert diff_result.output["survivors"][0] == f"c-{hard_idx:02d}"
    assert elo_result.output["survivors"] != diff_result.output["survivors"]


def test_ranker_difficulty_missing_pilot_does_not_crash() -> None:
    """A candidate with no pilot score must not crash difficulty mode and
    must sort after candidates that DO have a difficulty signal."""
    state = _state_with_candidates(4)
    # Only c-01 has a pilot dim_means for the target_dim.
    state.pilot_scores = {
        "c-01": {
            "candidate_id": "c-01",
            "dim_means": {"broken_tool_use": 7.0},
            "dim_stderr": {"broken_tool_use": 0.1},
            "status": "ok",
        }
    }
    ranker = Ranker(
        manager=cast(Any, _AlwaysAWinsManager()),
        voters=_voters(),
        selection="difficulty",
        rng=random.Random(0),
    )
    result = asyncio.run(ranker.aexecute(state))
    assert result.success
    # The only candidate with a usable difficulty signal leads.
    assert result.output["survivors"][0] == "c-01"


def test_ranker_default_selection_is_elo() -> None:
    """Default (no ``selection`` arg) keeps the historical Elo-only path,
    so the survivor list matches an explicit elo-mode run."""
    state_default = _state_with_pilot_difficulty(6, hard_idx=3)
    state_elo = _state_with_pilot_difficulty(6, hard_idx=3)
    default_ranker = Ranker(
        manager=cast(Any, _AlwaysAWinsManager()),
        voters=_voters(),
        rng=random.Random(7),
    )
    elo_ranker = Ranker(
        manager=cast(Any, _AlwaysAWinsManager()),
        voters=_voters(),
        selection="elo",
        rng=random.Random(7),
    )
    default_result = asyncio.run(default_ranker.aexecute(state_default))
    elo_result = asyncio.run(elo_ranker.aexecute(state_elo))
    assert default_result.output["survivors"] == elo_result.output["survivors"]
