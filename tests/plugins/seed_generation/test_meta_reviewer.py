"""Tests for ``plugins.seed_generation.agents.meta_reviewer``."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.meta_reviewer import MetaReviewer
from plugins.seed_generation.orchestrator import PipelineState


def _good_meta() -> dict[str, Any]:
    return {
        "coverage": {"broken_tool_use": 4, "input_hallucination": 3},
        "underrepresented_dims": ["unfaithful_thinking"],
        "overrepresented_dims": ["overrefusal"],
        "next_gen_priors": [
            {"target_dim": "unfaithful_thinking", "weight": 0.4, "rationale": "underrepresented"}
        ],
        "elo_distribution": {"min": 940.0, "p50": 1020.0, "p95": 1180.0},
        "evolution_yield": {"attempted": 5, "successful": 3},
        "session_summary": "Pool well-covered on broken_tool_use; gap on unfaithful_thinking.",
    }


class _StubManager:
    def __init__(
        self,
        *,
        output: Any = None,
        success: bool = True,
        force_unparseable: bool = False,
    ) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._output = output if output is not None else _good_meta()
        self._success = success
        self._force_unparseable = force_unparseable

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        self.received_announce = announce
        if not tasks:
            return []
        t = tasks[0]
        if not self._success:
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=False,
                    error="forced",
                    duration_ms=10.0,
                )
            ]
        output = {"text": "not-valid-json"} if self._force_unparseable else self._output
        return [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output=output,
                duration_ms=42.0,
            )
        ]


def _state_with_full_pipeline_data(n: int = 5) -> PipelineState:
    state = PipelineState(
        run_id="t-meta",
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
    state.reflections = {
        c["id"]: {"strengths": ["a"], "weaknesses": ["b"]} for c in state.candidates
    }
    state.pilot_scores = {
        c["id"]: {"dim_means": {"dim_01": 0.7}, "dim_stderr": {"dim_01": 0.1}, "status": "ok"}
        for c in state.candidates
    }
    state.elo_ratings = {c["id"]: 1000.0 + i * 30 for i, c in enumerate(state.candidates)}
    state.survivors = [c["id"] for c in state.candidates[:3]]
    state.evolved_candidates = [
        {"id": f"{cid}-ev", "parent_id": cid} for cid in state.survivors[:2]
    ]
    return state


def test_meta_reviewer_validates_empty_candidates() -> None:
    state = PipelineState(
        run_id="t",
        target_dim="x",
        gen_tag="gen2",
        candidates_requested=3,
    )
    manager = _StubManager()
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_meta_reviewer_dispatches_single_task() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 1
    task = manager.received_tasks[0]
    assert task.agent == "seed_meta_reviewer"
    assert task.task_type == "seed-meta-review"


def test_meta_reviewer_merges_report_into_meta_review() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert result.success
    meta = result.output["meta_review"]
    assert "coverage" in meta
    assert "next_gen_priors" in meta
    assert "session_summary" in meta


def test_meta_reviewer_drops_malformed_payload() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(output={"partial": "dict"})
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_handles_sub_agent_failure() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(success=False)
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_accepts_text_json_fallback() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager(output={"text": json.dumps(_good_meta())})
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert result.success


def test_meta_reviewer_announce_false() -> None:
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_meta_reviewer_snapshot_includes_counts() -> None:
    """Task args should carry the state snapshot with counts."""
    state = _state_with_full_pipeline_data(5)
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    snapshot = task.args["snapshot"]
    assert snapshot["candidate_ids"] == [c["id"] for c in state.candidates]
    assert snapshot["evolution_yield"]["successful"] == 2  # 2 evolved
    assert snapshot["evolution_yield"]["attempted"] == 3  # 3 survivors
    assert "elo_distribution" in snapshot


def test_meta_reviewer_description_mentions_run_id() -> None:
    state = _state_with_full_pipeline_data(3)
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    desc = manager.received_tasks[0].description
    assert "t-meta" in desc
    assert "broken_tool_use" in desc


def test_meta_reviewer_drops_response_missing_session_summary() -> None:
    """All 7 fields required — missing any → drop."""
    state = _state_with_full_pipeline_data(3)
    partial = _good_meta()
    del partial["session_summary"]
    manager = _StubManager(output=partial)
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "meta_review_failed"


def test_meta_reviewer_empty_elo_ratings_safe() -> None:
    """elo_distribution computation tolerates empty elo_ratings dict."""
    state = _state_with_full_pipeline_data(3)
    state.elo_ratings = {}
    manager = _StubManager()
    result = asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    assert result.success
    snapshot = manager.received_tasks[0].args["snapshot"]
    assert snapshot["elo_distribution"]["min"] == 0.0


def test_meta_reviewer_coverage_aggregates_target_dims() -> None:
    """Snapshot coverage groups candidates by target_dim."""
    state = _state_with_full_pipeline_data(2)
    state.candidates[1]["target_dim"] = "input_hallucination"
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    snapshot = manager.received_tasks[0].args["snapshot"]
    assert snapshot["coverage"]["broken_tool_use"] == 1
    assert snapshot["coverage"]["input_hallucination"] == 1


# ── PR-CSP-13a — meta_reviewer reads state.debate_transcripts ─────────────


def test_meta_reviewer_omits_debate_block_when_empty() -> None:
    """``num_turns=0`` path: empty debate_transcripts → snapshot has no
    ``debate_summary`` key and the description doesn't mention "Debate".

    Pins read-write parity back-compat (Codex MCP MEDIUM fix-up): the
    meta-reviewer prompt is byte-equivalent to pre-PR-CSP-13a behavior
    when no debate ran. The snapshot dict is rendered into the worker's
    "Parameters:" prompt line, so omitting the key entirely matters —
    a ``debate_summary: None`` row would still break byte-equivalence.
    """
    state = _state_with_full_pipeline_data(3)
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "debate_summary" not in task.args["snapshot"]
    assert "Debate (Loop 2)" not in task.description


def test_meta_reviewer_filters_stale_debate_transcripts() -> None:
    """Iteration cycle N≥1 — ``debate_transcripts`` accumulates entries
    from prior iterations (PipelineState.merge uses dict.update), but
    ``state.candidates`` was replaced on iteration promotion. The
    summary must report only candidates in the *current* batch.
    """
    state = _state_with_full_pipeline_data(2)
    # state.candidates ids look like ``cand-0``, ``cand-1`` per the fixture.
    state.debate_transcripts = {
        # Current batch — should count.
        state.candidates[0]["id"]: [{"turn": 1, "speaker": "A", "content": "x"}],
        # Stale — left over from a prior iteration's candidates pool.
        "old-cand-from-iter-0": [{"turn": 1, "speaker": "A", "content": "ghost"}],
    }
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    debate = task.args["snapshot"]["debate_summary"]
    assert debate["candidates_with_debate"] == 1, (
        "stale debate transcript leaked into current-iteration summary"
    )
    assert debate["sample_candidate_id"] == state.candidates[0]["id"]
    assert "old-cand-from-iter-0" not in task.description


def test_meta_reviewer_filters_all_stale_yields_no_block() -> None:
    """Edge case — every transcript is stale → summary returns ``None``
    and the description omits the block (back-compat preserved even
    when the dict is non-empty)."""
    state = _state_with_full_pipeline_data(2)
    state.debate_transcripts = {
        "old-cand-A": [{"turn": 1, "speaker": "A", "content": "x"}],
        "old-cand-B": [{"turn": 1, "speaker": "B", "content": "y"}],
    }
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "debate_summary" not in task.args["snapshot"]
    assert "Debate (Loop 2)" not in task.description


def test_meta_reviewer_emits_debate_summary_when_populated() -> None:
    """``num_turns >= 2`` path: snapshot carries aggregate counts; description
    references the Loop 2 signal."""
    state = _state_with_full_pipeline_data(3)
    # Use the fixture's actual candidate ids so the staleness filter
    # passes (Codex MCP MEDIUM fix-up).
    cid0 = state.candidates[0]["id"]
    cid1 = state.candidates[1]["id"]
    # Two of the three candidates ran debates; pre-fill the state with the
    # shape Generator writes via ``_read_debate_sidecars``.
    state.debate_transcripts = {
        cid0: [
            {"turn": 1, "speaker": "A", "content": "x"},
            {"turn": 2, "speaker": "B", "content": "y"},
            {"turn": 3, "speaker": "A", "content": "z"},
        ],
        cid1: [
            {"turn": 1, "speaker": "A", "content": "p"},
            {"turn": 2, "speaker": "B", "content": "q"},
        ],
    }
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    debate = task.args["snapshot"]["debate_summary"]
    assert debate is not None
    assert debate["candidates_with_debate"] == 2
    assert debate["total_turns"] == 5
    assert debate["avg_turns"] == 2.5
    # Deterministic sample picking — alphabetically first over filtered set.
    assert debate["sample_candidate_id"] == min(cid0, cid1)
    # Description references the debate signal so the LLM is forced
    # to attribute its effect (per the system prompt's quality bar).
    assert "Debate (Loop 2)" in task.description
    assert "2 of 3 candidates" in task.description


def test_meta_reviewer_debate_block_under_500_chars() -> None:
    """Debate block must not blow the context budget — the snapshot is an
    aggregate, not a transcript dump."""
    state = _state_with_full_pipeline_data(3)
    # Worst case: every current candidate has a max-budget (6-turn) debate.
    # Use the fixture's actual ids so the staleness filter passes.
    state.debate_transcripts = {
        c["id"]: [
            {"turn": t, "speaker": "A" if t % 2 else "B", "content": "x" * 500} for t in range(1, 7)
        ]
        for c in state.candidates
    }
    manager = _StubManager()
    asyncio.run(MetaReviewer(manager=manager).aexecute(state))  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    # Locate the debate block — measured from ``Debate (Loop 2)`` to the
    # JSON-enforce gate (which now ends the description per
    # PR-ROLE-JSON-ENFORCE-EXTENSION 2026-05-26; pre-fix the debate
    # block was the final fragment). It must be small (the LLM should
    # call read_document for the sidecar bodies if it wants the actual
    # text).
    desc = task.description
    debate_start = desc.find("Debate (Loop 2)")
    assert debate_start != -1
    gate_start = desc.find("FINAL response must be ONLY", debate_start)
    debate_block_end = gate_start if gate_start != -1 else len(desc)
    debate_block_len = debate_block_end - debate_start
    assert debate_block_len < 500, (
        f"debate block grew to {debate_block_len} chars — aggregate must stay terse"
    )


def test_meta_reviewer_debate_summary_grep_provable_read_path() -> None:
    """Read-write parity invariant: meta_reviewer.py must grep-prove that
    it reads ``debate_transcripts``. Pins CSP-13a's closing of the
    Phase 1 (PR #1504) Codex MCP MEDIUM defer."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "seed_generation"
        / "agents"
        / "meta_reviewer.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "debate_transcripts" in text, (
        "meta_reviewer.py must reference debate_transcripts to close the "
        "Loop 2 read-write parity gap"
    )
    assert "_debate_summary" in text


# Reserved — unused JSON helper for follow-up debug ergonomics
_ = json
