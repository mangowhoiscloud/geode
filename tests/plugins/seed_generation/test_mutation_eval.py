"""PR-RANKER-MUTATION-EVAL (Scope A handoff, 2026-05-26) — tests for the
``plugins.seed_generation.mutation_eval`` autoresearch entry point.

Four invariants:

1. **Cross-module contract** — ``MutationEvalResult.pairwise_win_rate``
   field name MUST match the key in
   ``autoresearch.admire_means.ADMIRE_DIM_WEIGHTS``. Pin via string
   grep on both source files (no runtime cross-package import — the
   seed_generation plugin must stay autoresearch-free per the
   handoff boundary).

2. **Panel diversity reportable** — ``MutationEvalResult.provider_diversity``
   correctly counts distinct providers from successful votes, so the
   autoresearch caller can compare against the manifest's
   ``required_diversity_providers`` gate.

3. **Graceful partial result** — voter failures (worker failure,
   malformed JSON, invalid winner label) drop out of the aggregate
   without raising; ``wins + losses + ties`` can be less than
   ``len(voters)``.

4. **No autoresearch import** — the mutation_eval module itself MUST
   NOT import anything from ``autoresearch``. Pin via static
   inspection of the source so a future drift PR cannot silently
   re-introduce a cycle.

Plus 1 happy-path aggregation test pinning the wins/losses/ties math.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from plugins.seed_generation.mutation_eval import (
    MutationEvalResult,
    evaluate_mutation_pairwise,
)
from plugins.seed_generation.picker import VoterBinding

# ────────────────────── 1. Cross-module contract ──────────────────────────────


def test_pairwise_win_rate_field_name_matches_autoresearch_admire() -> None:
    """``MutationEvalResult.pairwise_win_rate`` field MUST match the key
    in ``autoresearch.admire_means.ADMIRE_DIM_WEIGHTS``.

    Pinned via string-grep on both source files (NO runtime import of
    autoresearch from this test — the seed_generation plugin must
    stay autoresearch-free per the handoff boundary). A future PR
    that renames either side would trip this test.
    """
    repo_root = Path(__file__).parents[3]
    autoresearch_src = (repo_root / "autoresearch" / "admire_means.py").read_text(encoding="utf-8")
    mutation_eval_src = (repo_root / "plugins" / "seed_generation" / "mutation_eval.py").read_text(
        encoding="utf-8"
    )

    assert '"pairwise_win_rate"' in autoresearch_src, (
        "autoresearch admire_means.ADMIRE_DIM_WEIGHTS lost the "
        "'pairwise_win_rate' key — break the handoff contract."
    )
    assert "pairwise_win_rate" in mutation_eval_src, (
        "mutation_eval module lost the 'pairwise_win_rate' field — "
        "autoresearch admire_means would silently fall back to 0.5 neutral."
    )
    # The dataclass field is named exactly this.
    assert "pairwise_win_rate" in MutationEvalResult.__dataclass_fields__


# ────────────────────── 2. No autoresearch import ─────────────────────────────


def test_mutation_eval_has_zero_autoresearch_imports() -> None:
    """The seed-gen plugin must not depend on autoresearch.

    autoresearch is the *caller* of this module; the reverse direction
    would create a cycle. Uses Python's ``ast`` to walk the actual
    import statements (not a substring match — docstrings + prose
    mentioning ``from autoresearch ...`` as documentation must not
    trip the test).
    """
    import ast

    src = (
        Path(__file__).parents[3] / "plugins" / "seed_generation" / "mutation_eval.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "autoresearch" or alias.name.startswith("autoresearch."):
                    bad_imports.append(f"import {alias.name}")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "autoresearch" or node.module.startswith("autoresearch."))
        ):
            bad_imports.append(f"from {node.module} import ...")
    assert not bad_imports, (
        "mutation_eval declared autoresearch import(s) — "
        "violates the seed-gen → autoresearch handoff boundary "
        f"(seed-gen is the callee, not the caller). Found: {bad_imports}"
    )


# ────────────────────── Test scaffolding ──────────────────────────────────────


@dataclass
class _StubWorkerResult:
    """Minimal stub matching SubAgentManager.adelegate's return shape.

    ``SubResult.output`` (core/agent/sub_agent.py) is typed as
    ``dict[str, Any]`` — the manager deserialises the worker's JSON
    string into a dict before returning. Mirror that here.
    """

    task_id: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class _StubManager:
    """In-process stub of SubAgentManager.adelegate — yields the
    pre-canned outputs in the order tasks were dispatched."""

    def __init__(self, outputs_by_task_id: dict[str, _StubWorkerResult]) -> None:
        self._outputs = outputs_by_task_id

    async def adelegate(
        self,
        tasks: list[Any],
        *,
        announce: bool = True,
    ) -> list[_StubWorkerResult]:
        results: list[_StubWorkerResult] = []
        for task in tasks:
            res = self._outputs.get(task.task_id)
            if res is None:
                results.append(
                    _StubWorkerResult(
                        task_id=task.task_id,
                        success=False,
                        error="stub missing for this task_id",
                    )
                )
            else:
                results.append(res)
        return results


def _three_voter_panel() -> list[VoterBinding]:
    """Default 3-voter cross-provider panel matching the manifest."""
    return [
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
    ]


def _vote_payload(*, match_id: str, winner: str, rationale: str = "ok") -> dict[str, Any]:
    """Build the dict shape the worker's parsed output takes (already
    deserialised — ``SubResult.output: dict[str, Any]``)."""
    return {"match_id": match_id, "winner": winner, "rationale": rationale}


# ────────────────────── 3. Happy-path aggregation ────────────────────────────


def test_aggregates_wins_losses_ties_correctly() -> None:
    """Default 3-voter panel (2x openai + 1x claude) — winners B / B / A
    → wins=2, losses=1, ties=0. Pin pairwise_win_rate = 2/3.

    Codex MCP catch (2026-05-26) — pre-fix the openai duplicate voter
    silently collided on task_id; the manager dedup'd them and the
    test only saw 2 votes. Now per-voter ordinal in task_id
    (``v{idx:02d}``) makes all 3 voters distinct.
    """
    voters = _three_voter_panel()  # 2x openai + 1x claude
    match_id = "mutation-eval-happy"
    outputs = {
        f"vote-{match_id}-v00-openai.openai-codex": _StubWorkerResult(
            task_id=f"vote-{match_id}-v00-openai.openai-codex",
            success=True,
            output=_vote_payload(match_id=match_id, winner="B"),
        ),
        f"vote-{match_id}-v01-openai.openai-codex": _StubWorkerResult(
            task_id=f"vote-{match_id}-v01-openai.openai-codex",
            success=True,
            output=_vote_payload(match_id=match_id, winner="B"),
        ),
        f"vote-{match_id}-v02-anthropic.claude-cli": _StubWorkerResult(
            task_id=f"vote-{match_id}-v02-anthropic.claude-cli",
            success=True,
            output=_vote_payload(match_id=match_id, winner="A"),
        ),
    }
    manager = _StubManager(outputs)

    result = asyncio.run(
        evaluate_mutation_pairwise(
            before_response="before body",
            after_response="after body",
            scenario_seed="scenario",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert result.wins == 2
    assert result.losses == 1
    assert result.ties == 0
    assert result.pairwise_win_rate == pytest.approx(2 / 3)
    assert result.provider_diversity == 2  # openai + anthropic
    # Order preserved — 2x gpt-5.5 then claude-sonnet-4-6.
    assert result.voter_models == ("gpt-5.5", "gpt-5.5", "claude-sonnet-4-6")


def test_duplicate_voter_bindings_not_deduplicated_by_task_id() -> None:
    """Codex MCP catch (2026-05-26) — the default manifest's
    ``2x openai.openai-codex + 1x anthropic.claude-cli`` panel must
    dispatch 3 SubTasks (NOT 2). Pre-fix the task_id format
    ``vote-{match_id}-{provider}.{source}`` collided for the two
    openai voters and ``SubAgentManager`` deduplicated. Now the
    per-voter ordinal ``v{idx:02d}`` disambiguates."""
    import json

    voters = _three_voter_panel()
    match_id = "dup-voter"
    # Three distinct task_ids — confirms the v-ordinal disambiguation.
    outputs = {
        f"vote-{match_id}-v{i:02d}-{v.provider}.{v.source}": _StubWorkerResult(
            task_id=f"vote-{match_id}-v{i:02d}-{v.provider}.{v.source}",
            success=True,
            output=_vote_payload(match_id=match_id, winner="tie"),
        )
        for i, v in enumerate(voters)
    }

    # Capture the dispatched tasks so we can pin the task_id count.
    dispatched: list[str] = []

    class _CapturingStubManager(_StubManager):
        async def adelegate(
            self,
            tasks: list[Any],
            *,
            announce: bool = True,
        ) -> list[_StubWorkerResult]:
            dispatched.extend(t.task_id for t in tasks)
            return await super().adelegate(tasks, announce=announce)

    manager = _CapturingStubManager(outputs)
    result = asyncio.run(
        evaluate_mutation_pairwise(
            before_response="b",
            after_response="a",
            scenario_seed="s",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert len(dispatched) == 3, (
        f"expected 3 distinct task_ids for the default 3-voter panel; "
        f"got {len(dispatched)}: {dispatched}"
    )
    # All distinct — the v-ordinal must disambiguate the openai duplicates.
    assert len(set(dispatched)) == 3
    # All ties so provider_diversity counts both that voted.
    assert result.ties == 3
    assert result.provider_diversity == 2
    # And the voter task carries typed args (provider/model not reverse-
    # parsed from task_id — Codex MCP catch).
    # Use json.dumps to make the assertion failure readable.
    assert all(f"v{i:02d}" in dispatched[i] for i in range(3)), (
        f"voter ordinals out of order: {json.dumps(dispatched)}"
    )


# ────────────────────── 4. Graceful partial result ────────────────────────────


def test_voter_failure_drops_out_of_aggregate() -> None:
    """A failed voter doesn't raise — it's dropped from the panel sum."""
    voters = [
        VoterBinding(model="gpt-5.5", provider="openai", source="openai-codex"),
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
    ]
    match_id = "mutation-eval-partial"
    outputs = {
        f"vote-{match_id}-v00-openai.openai-codex": _StubWorkerResult(
            task_id=f"vote-{match_id}-v00-openai.openai-codex",
            success=False,
            error="codex empty_text",
        ),
        f"vote-{match_id}-v01-anthropic.claude-cli": _StubWorkerResult(
            task_id=f"vote-{match_id}-v01-anthropic.claude-cli",
            success=True,
            output=_vote_payload(match_id=match_id, winner="B"),
        ),
    }
    manager = _StubManager(outputs)

    result = asyncio.run(
        evaluate_mutation_pairwise(
            before_response="before",
            after_response="after",
            scenario_seed="scenario",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert result.wins == 1
    assert result.losses == 0
    assert result.ties == 0
    assert result.pairwise_win_rate == pytest.approx(1.0)
    # Only the claude voter succeeded.
    assert result.provider_diversity == 1
    assert result.voter_models == ("claude-sonnet-4-6",)


def test_all_voters_fail_returns_neutral_win_rate() -> None:
    """When every voter fails → pairwise_win_rate == 0.5 (neutral signal).

    autoresearch's ``compute_admire_aggregate`` will then dampen via
    the human_calibration_corr factor and downstream fitness will
    treat this as no-signal.
    """
    voters = _three_voter_panel()
    match_id = "all-fail"
    outputs: dict[str, _StubWorkerResult] = {}  # every voter falls to stub-missing path
    manager = _StubManager(outputs)

    result = asyncio.run(
        evaluate_mutation_pairwise(
            before_response="x",
            after_response="y",
            scenario_seed="z",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert result.wins == 0
    assert result.losses == 0
    assert result.ties == 0
    assert result.pairwise_win_rate == pytest.approx(0.5)
    assert result.provider_diversity == 0
    assert result.voter_models == ()


def test_invalid_winner_label_drops_out_of_aggregate() -> None:
    """``winner: "neither"`` (not in {A, B, tie}) is rejected silently
    so a malformed vote can't poison the aggregate."""
    voters = [
        VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
    ]
    match_id = "bad-label"
    outputs = {
        f"vote-{match_id}-v00-anthropic.claude-cli": _StubWorkerResult(
            task_id=f"vote-{match_id}-v00-anthropic.claude-cli",
            success=True,
            output=_vote_payload(match_id=match_id, winner="neither"),
        ),
    }
    manager = _StubManager(outputs)

    result = asyncio.run(
        evaluate_mutation_pairwise(
            before_response="b",
            after_response="a",
            scenario_seed="s",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert result.wins == 0
    assert result.losses == 0
    assert result.ties == 0
    assert result.provider_diversity == 0


# ────────────────────── Anti-phantom prompt parity ────────────────────────────


def test_voter_prompt_carries_anti_phantom_directives() -> None:
    """Per PR-VOTER-PROMPT-ANTI-PHANTOM, the voter prompt must explicitly
    disclaim phantom prior-turn continuity. Same defence as the
    ranker tournament path — mutation_eval reuses the same anti-
    hallucination prose to keep claude-cli from emitting
    'I already read both candidate files in the previous turn'."""
    from plugins.seed_generation.mutation_eval import _build_voter_description

    desc = _build_voter_description(
        voter=VoterBinding(model="claude-sonnet-4-6", provider="anthropic", source="claude-cli"),
        before_response="before",
        after_response="after",
        scenario_seed="scenario",
        match_id="m-test",
    )
    assert "DO NOT call any Read tool" in desc
    assert "first and only turn" in desc
    # The bodies are inlined directly into the handoff (no path).
    assert "candidate_a" in desc
    assert "candidate_b" in desc
    assert '"body": "before"' in desc
    assert '"body": "after"' in desc


def test_mutation_eval_voter_tasks_pin_effort_low() -> None:
    """Mutation-eval voter SubTasks pin ``effort="low"``.

    PR-CODEX-GPT55-OUTPUT-EMIT fix-up (Codex MCP catch, 2026-05-26) —
    mutation_eval reuses VOTE_SCHEMA + the gpt-5.5 A/B/tie shape from
    the ranker voter pathway. Without an explicit effort pin the
    SubTask would fall through to ``_DIFFICULTY_TO_EFFORT["medium"]``
    and reproduce the smoke 20 empty-text failure mode (gpt-5.5
    burning the entire output budget on encrypted reasoning items)
    outside the ranker phase. Same ctx7 grounding as
    ``plugins/seed_generation/agents/ranker.py``.
    """
    voters = _three_voter_panel()
    match_id = "effort-pin"
    # Capture the dispatched tasks so we can inspect the SubTask.effort
    # field directly — the result aggregate doesn't expose it.
    dispatched: list[Any] = []

    class _CapturingStubManager(_StubManager):
        async def adelegate(
            self,
            tasks: list[Any],
            *,
            announce: bool = True,
        ) -> list[_StubWorkerResult]:
            dispatched.extend(tasks)
            return await super().adelegate(tasks, announce=announce)

    manager = _CapturingStubManager({})  # outputs empty — we only inspect dispatch
    asyncio.run(
        evaluate_mutation_pairwise(
            before_response="b",
            after_response="a",
            scenario_seed="s",
            voters=voters,
            manager=manager,  # type: ignore[arg-type]
            match_id=match_id,
        )
    )

    assert len(dispatched) == 3, f"expected 3 dispatched voter SubTasks; got {len(dispatched)}"
    for task in dispatched:
        assert task.effort == "low", (
            f"mutation_eval voter SubTask {task.task_id} must pin "
            f"effort='low' (got {task.effort!r}) — without the pin the "
            f"gpt-5.5 voter reproduces the smoke 20 empty-text failure "
            f"outside the ranker phase."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
