"""Regression — Generator must pair results to tasks by task_id, not position.

Pre-S2-fix `zip(tasks, results, strict=False)` (`plugins/seed_generation/agents/
generator.py:151`) silently mismatched candidate metadata with whichever
sub-agent completed first, because `SubAgentManager.delegate` returns
SubResult in *completion order*, not submission order.

This test stub returns results in REVERSE order to simulate variable
LLM latency; the post-fix generator must produce candidates whose
`id` matches the corresponding task's `args["candidate_id"]`.
"""

from __future__ import annotations

from pathlib import Path

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.generator import Generator
from plugins.seed_generation.orchestrator import PipelineState


class _ReverseOrderManager:
    """Returns SubResults in reverse submission order (worst-case latency mix)."""

    def __init__(self) -> None:
        self.received_tasks: list[SubTask] = []

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        results = [
            SubResult(
                task_id=t.task_id,
                description=t.description,
                success=True,
                output={"path": t.args["output_path"]},
                duration_ms=42.0,
            )
            for t in tasks
        ]
        return list(reversed(results))


def _make_state(tmp_path: Path, n: int) -> PipelineState:
    return PipelineState(
        run_id="t-reorder",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
        pool_path_in=Path("plugins/petri_audit/seeds"),
        run_dir=tmp_path,
    )


def test_generator_pairs_by_task_id_under_reverse_order(tmp_path: Path) -> None:
    """A reversed delegate() return must still produce correctly-paired candidates."""
    state = _make_state(tmp_path, n=5)
    manager = _ReverseOrderManager()
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    candidates = result.output["candidates"]
    assert len(candidates) == 5

    # For each returned candidate, look up the original task by candidate_id.
    # The path in candidate dict must match the path baked into that task's
    # args["output_path"]. If zip-by-position were still in effect, candidate
    # 0 would carry task 4's output_path and so on.
    tasks_by_candidate_id = {t.args["candidate_id"]: t for t in manager.received_tasks}
    for cand in candidates:
        original_task = tasks_by_candidate_id[cand["id"]]
        assert cand["path"] == original_task.args["output_path"], (
            f"candidate {cand['id']} carried path {cand['path']} but its "
            f"task's output_path is {original_task.args['output_path']}"
        )
        assert cand["task_id"] == original_task.task_id


class _UnmatchedResultManager:
    """Returns a result whose task_id doesn't match any submitted task."""

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        results = [
            SubResult(task_id=t.task_id, description=t.description, success=True, duration_ms=10)
            for t in tasks
        ]
        # Inject an unmatched result that should NOT contaminate candidates
        results.append(
            SubResult(
                task_id="unmatched-orphan",
                description="orphan",
                success=False,
                error="rogue",
                duration_ms=0,
            )
        )
        return results


def test_generator_handles_unmatched_result(tmp_path: Path) -> None:
    """A SubResult with no corresponding task must be logged as failed, not silently merged."""
    state = _make_state(tmp_path, n=2)
    manager = _UnmatchedResultManager()
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    # Real candidates: 2 (matched). Orphan should not appear.
    assert result.success
    assert len(result.output["candidates"]) == 2
    candidate_ids = {c["task_id"] for c in result.output["candidates"]}
    assert "unmatched-orphan" not in candidate_ids
