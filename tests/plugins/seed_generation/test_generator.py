"""Unit tests for ``plugins.seed_generation.agents.generator``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.generator import Generator
from plugins.seed_generation.orchestrator import PipelineState


class _StubManager:
    """Capture ``delegate(tasks)`` arguments and return canned results."""

    def __init__(self, force_failures: int = 0, fail_all: bool = False) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._force_failures = force_failures
        self._fail_all = fail_all

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        self.received_announce = announce
        results: list[SubResult] = []
        for i, t in enumerate(tasks):
            failed = self._fail_all or i < self._force_failures
            results.append(
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=not failed,
                    output={} if failed else {"path": t.args["output_path"]},
                    error="forced" if failed else None,
                    duration_ms=42.0,
                )
            )
        return results


def _make_state(tmp_path: Path, n: int = 3) -> PipelineState:
    return PipelineState(
        run_id="t-gen",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
        pool_path_in=Path("plugins/petri_audit/seeds"),
        run_dir=tmp_path,
    )


def test_generator_builds_n_tasks_against_seed_generator_agent(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=5)
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 5
    for task in manager.received_tasks:
        assert task.agent == "seed_generator"
        assert task.task_type == "seed-generation"
        assert task.args["target_dim"] == "broken_tool_use"
        assert task.args["gen_tag"] == "gen2"


def test_generator_creates_candidates_dir(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=2)
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert (tmp_path / "candidates").is_dir()


def test_generator_returns_one_candidate_per_success(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=4)
    manager = _StubManager(force_failures=0)
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    candidates = result.output["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 4
    first = candidates[0]
    assert first["target_dim"] == "broken_tool_use"
    assert first["gen_tag"] == "gen2"
    assert first["path"].endswith(".md")
    assert "gen2-000-" in first["id"]
    assert first["task_id"].startswith("gen-gen2-")


def test_generator_drops_failed_sub_agents(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=5)
    manager = _StubManager(force_failures=2)
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert len(result.output["candidates"]) == 3


def test_generator_returns_error_when_all_fail(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=3)
    manager = _StubManager(fail_all=True)
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "generation_failed"
    assert "all 3 candidate sub-agents failed" in (result.error_message or "")


def test_generator_announce_false(tmp_path: Path) -> None:
    """Each candidate spawn must NOT push to the parent's announce queue."""
    state = _make_state(tmp_path, n=2)
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_generator_validates_run_dir(tmp_path: Path) -> None:
    state = PipelineState(
        run_id="t-gen",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=3,
        run_dir=None,  # missing
    )
    manager = _StubManager()
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_generator_validates_candidates_requested(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=0)
    manager = _StubManager()
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_generator_task_description_includes_pool_hint(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=1)
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "broken_tool_use" in task.description
    assert "gen2" in task.description
    assert "seeds" in task.description


def test_generator_task_description_handles_no_pool(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=1)
    state.pool_path_in = None
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "from scratch" in task.description


def test_generator_id_is_unique_across_batch(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=10)
    manager = _StubManager()
    result = Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    ids = {c["id"] for c in result.output["candidates"]}
    assert len(ids) == 10, "candidate ids should be unique"


def test_generator_args_carry_output_path(tmp_path: Path) -> None:
    state = _make_state(tmp_path, n=2)
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    for task in manager.received_tasks:
        assert task.args["output_path"].endswith(".md")
        assert task.args["candidate_id"] in task.args["output_path"]


def test_generator_orchestrator_registry_accepts_generator(tmp_path: Path) -> None:
    """Smoke — registering Generator into PipelineRegistry doesn't error."""
    from plugins.seed_generation.orchestrator import PipelineRegistry

    manager = _StubManager()
    registry = PipelineRegistry()
    registry.register(Generator(manager=manager))  # type: ignore[arg-type]
    assert registry.has("generator")
    assert registry.get("generator") is not None


def test_generator_injects_baseline_evidence_into_description(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """G3 — when state.baseline_snapshot is set and format_evidence_block
    returns a non-empty block, the per-candidate sub-task description
    embeds it as a prefix above the original instructions.

    G2.fix (2026-05-20) — the snapshot no longer carries evidence directly;
    ``format_evidence_block`` extracts from petri's latest .eval on demand.
    The test monkeypatches ``format_evidence_block`` so the agent layer
    can be exercised independently of the on-disk archive.
    """
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    run_dir = tmp_path
    state = _make_state(run_dir, n=2)
    state.baseline_snapshot = BaselineSnapshot(
        dim_means={"broken_tool_use": 7.0},
        dim_stderr={"broken_tool_use": 0.3},
    )
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.format_evidence_block",
        lambda _snap, _dim, **_kw: (
            "Recent audit evidence (latest .eval, on demand)\n"
            "- dim: broken_tool_use\n"
            "  1. seed-anchor — target hallucinated tool result\n"
            "     highlights: - [M9] worst quote"
        ),
    )
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    for task in manager.received_tasks:
        assert "Recent audit evidence" in task.description
        assert "seed-anchor" in task.description
        assert "hallucinated" in task.description
        # Original generator instructions still present.
        assert "Generate ONE Petri audit seed" in task.description


def test_generator_skips_evidence_when_snapshot_is_none(tmp_path: Path) -> None:
    """No baseline snapshot → no evidence prefix, prompts identical to legacy."""
    run_dir = tmp_path
    state = _make_state(run_dir, n=1)
    state.baseline_snapshot = None
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "Recent audit evidence" not in task.description
    assert task.description.startswith("Generate ONE Petri audit seed")


def test_generator_skips_evidence_when_block_is_empty(tmp_path: Path, monkeypatch: Any) -> None:
    """Snapshot present but format_evidence_block returns "" (no .eval, no rows
    for target_dim) → no prefix."""
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    run_dir = tmp_path
    state = _make_state(run_dir, n=1)
    state.baseline_snapshot = BaselineSnapshot(dim_means={"other_dim": 5.0})
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.format_evidence_block",
        lambda _snap, _dim, **_kw: "",
    )
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert "Recent audit evidence" not in manager.received_tasks[0].description


# ---------------------------------------------------------------------------
# G4 — meta_review priors injection (2026-05-20 self-improving-loop wiring)
# ---------------------------------------------------------------------------


def test_generator_injects_priors_block_when_snapshot_present(tmp_path: Path) -> None:
    """meta_review_snapshot → priors block prepended ABOVE baseline evidence."""
    from plugins.seed_generation.baseline_reader import MetaReviewSnapshot

    run_dir = tmp_path
    state = _make_state(run_dir, n=1)
    state.meta_review_snapshot = MetaReviewSnapshot(
        next_gen_priors=[
            {
                "target_dim": "broken_tool_use",
                "weight": 0.7,
                "rationale": "previous run missed tool error mode",
            }
        ],
        underrepresented_dims=["broken_tool_use"],
    )
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "Previous-generation meta-review" in task.description
    assert "broken_tool_use" in task.description
    assert "missed tool error mode" in task.description
    # Original generator instructions still after the block.
    assert "Generate ONE Petri audit seed" in task.description


def test_generator_priors_block_skipped_without_snapshot(tmp_path: Path) -> None:
    run_dir = tmp_path
    state = _make_state(run_dir, n=1)
    state.meta_review_snapshot = None
    manager = _StubManager()
    Generator(manager=manager).execute(state)  # type: ignore[arg-type]
    assert "Previous-generation meta-review" not in manager.received_tasks[0].description
