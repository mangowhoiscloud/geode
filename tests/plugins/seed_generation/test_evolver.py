"""Tests for ``plugins.seed_generation.agents.evolver``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — `_ReverseOrderManager` returns results in
  reverse submission order; tests verify Evolver still pairs by task_id
  via `parse_structured_output`'s pin_field.
- **P7 Caller-Callee Contract Pair Read** — Evolver consumes
  ``state.survivors`` + ``state.reflections`` + ``state.pilot_scores``;
  emits rows mirroring ``state.candidates`` schema plus provenance.
"""

from __future__ import annotations

from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.evolver import Evolver
from plugins.seed_generation.orchestrator import PipelineState


def _good_evolve(parent_id: str = "c-1", verdict: str = "ok") -> dict[str, Any]:
    return {
        "parent_id": parent_id,
        "evolved_id": f"{parent_id}-ev",
        "evolved_path": f"fake-run/candidates_evolved/{parent_id}-ev.md",
        "rewrite_section": "Body",
        "verdict": verdict,
        "notes": "test notes",
    }


class _StubManager:
    def __init__(
        self,
        *,
        evolve_outputs: dict[str, dict[str, Any]] | None = None,
        force_failures: int = 0,
        force_unparseable: bool = False,
    ) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._evolves = evolve_outputs or {}
        self._force_failures = force_failures
        self._force_unparseable = force_unparseable

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        self.received_announce = announce
        results: list[SubResult] = []
        for i, t in enumerate(tasks):
            parent_id = t.args["parent_id"]
            failed = i < self._force_failures
            if failed:
                results.append(
                    SubResult(
                        task_id=t.task_id,
                        description=t.description,
                        success=False,
                        error="forced",
                        duration_ms=10.0,
                    )
                )
                continue
            if self._force_unparseable:
                output: Any = {"text": "not-json"}
            else:
                output = dict(self._evolves.get(parent_id, _good_evolve(parent_id)))
            results.append(
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output=output,
                    duration_ms=42.0,
                )
            )
        return results


class _ReverseOrderManager(_StubManager):
    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        results = super().delegate(tasks, announce=announce)
        return list(reversed(results))


def _state_with_survivors(n: int) -> PipelineState:
    state = PipelineState(
        run_id="t-evolver",
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
    state.survivors = [c["id"] for c in state.candidates]
    state.reflections = {
        c["id"]: {
            "rewrite_section": "Body",
            "weaknesses": ["partial overlap with seed_pool"],
        }
        for c in state.candidates
    }
    state.pilot_scores = {
        c["id"]: {
            "dim_means": {"dim_01": 0.7},
            "dim_stderr": {"dim_01": 0.1},
            "status": "ok",
        }
        for c in state.candidates
    }
    return state


def test_evolver_validates_empty_survivors() -> None:
    state = PipelineState(
        run_id="t",
        target_dim="x",
        gen_tag="gen2",
        candidates_requested=3,
    )
    manager = _StubManager()
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_evolver_validates_survivors_without_candidates() -> None:
    """Survivor id not in state.candidates → skipped + validation error."""
    state = PipelineState(
        run_id="t",
        target_dim="x",
        gen_tag="gen2",
        candidates_requested=3,
    )
    state.survivors = ["ghost-1"]
    manager = _StubManager()
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_evolver_builds_one_task_per_survivor() -> None:
    state = _state_with_survivors(3)
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 3
    for task in manager.received_tasks:
        assert task.agent == "seed_evolver"
        assert task.task_type == "seed-evolve"
        assert "parent_id" in task.args
        assert "rewrite_section" in task.args


def test_evolver_returns_evolved_candidates_rows() -> None:
    state = _state_with_survivors(3)
    manager = _StubManager()
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    rows = result.output["evolved_candidates"]
    assert len(rows) == 3
    for row in rows:
        assert row["id"].endswith("-ev")
        assert "parent_id" in row
        assert row["rewrite_section"] == "Body"


def test_evolver_pairs_by_task_id_under_reverse_order() -> None:
    """P1 — reverse-order completion must still pair correctly via pin_field."""
    state = _state_with_survivors(5)
    manager = _ReverseOrderManager()
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    rows = result.output["evolved_candidates"]
    for row in rows:
        # parent_id should match a survivor id, not be the LLM echo of some other id
        assert row["parent_id"] in state.survivors


def test_evolver_drops_failed_sub_agents() -> None:
    state = _state_with_survivors(5)
    manager = _StubManager(force_failures=2)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert len(result.output["evolved_candidates"]) == 3


def test_evolver_drops_unparseable_responses() -> None:
    state = _state_with_survivors(3)
    manager = _StubManager(force_unparseable=True)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "evolution_failed"


def test_evolver_skips_evolution_skipped_verdict() -> None:
    """Verdict 'evolution_skipped' → original kept, no row emitted."""
    state = _state_with_survivors(3)
    skipped = {cid: _good_evolve(cid, verdict="evolution_skipped") for cid in state.survivors}
    manager = _StubManager(evolve_outputs=skipped)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success  # no rows → failure
    assert result.error_category == "evolution_failed"


def test_evolver_skips_failed_verdict() -> None:
    state = _state_with_survivors(3)
    failed_verdicts = {cid: _good_evolve(cid, verdict="failed") for cid in state.survivors}
    manager = _StubManager(evolve_outputs=failed_verdicts)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "evolution_failed"


def test_evolver_drops_invalid_verdict() -> None:
    """Verdict not in whitelist → dropped."""
    state = _state_with_survivors(1)
    bad = {state.survivors[0]: _good_evolve(state.survivors[0], verdict="weird")}
    manager = _StubManager(evolve_outputs=bad)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "evolution_failed"


def test_evolver_mixed_verdicts() -> None:
    """Some 'ok', some skipped — only 'ok' rows survive."""
    state = _state_with_survivors(3)
    outputs = {
        "c-00": _good_evolve("c-00", verdict="ok"),
        "c-01": _good_evolve("c-01", verdict="evolution_skipped"),
        "c-02": _good_evolve("c-02", verdict="ok"),
    }
    manager = _StubManager(evolve_outputs=outputs)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    rows = result.output["evolved_candidates"]
    assert len(rows) == 2
    parent_ids = {r["parent_id"] for r in rows}
    assert parent_ids == {"c-00", "c-02"}


def test_evolver_pins_parent_id_from_task() -> None:
    """LLM echoes a wrong parent_id; the task's parent_id wins."""
    state = _state_with_survivors(1)
    wrong = _good_evolve("WRONG-from-llm")
    outputs = {"c-00": wrong}
    manager = _StubManager(evolve_outputs=outputs)
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    rows = result.output["evolved_candidates"]
    assert rows[0]["parent_id"] == "c-00"


def test_evolver_announce_false() -> None:
    state = _state_with_survivors(2)
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_evolver_description_includes_pilot_means() -> None:
    state = _state_with_survivors(1)
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    desc = manager.received_tasks[0].description
    assert "dim_01" in desc
    assert "Body" in desc  # rewrite_section


def test_evolver_description_default_rewrite_section_when_missing() -> None:
    """Reflection without rewrite_section → defaults to 'Body'."""
    state = _state_with_survivors(1)
    state.reflections["c-00"] = {"weaknesses": ["partial overlap"]}
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert task.args["rewrite_section"] == "Body"


def test_evolver_evolved_row_schema_mirrors_candidates() -> None:
    """Evolved row has the same schema as state.candidates plus provenance."""
    state = _state_with_survivors(1)
    manager = _StubManager()
    result = Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    row = result.output["evolved_candidates"][0]
    for key in ("id", "path", "target_dim", "gen_tag", "task_id", "duration_ms"):
        assert key in row, f"missing {key}"
    # Provenance-specific
    assert "parent_id" in row
    assert "rewrite_section" in row
    assert "notes" in row


# ---------------------------------------------------------------------------
# G3 — baseline evidence injection (2026-05-20 self-improving-loop wiring)
# ---------------------------------------------------------------------------


def test_evolver_injects_baseline_evidence_into_description(monkeypatch: Any) -> None:
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    state = _state_with_survivors(n=1)
    state.baseline_snapshot = BaselineSnapshot(
        dim_means={"broken_tool_use": 7.0},
        dim_stderr={"broken_tool_use": 0.3},
    )
    # G2.fix (2026-05-20) — evidence pulled from latest .eval on demand.
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.format_evidence_block",
        lambda _snap, _dim, **_kw: (
            "Recent audit evidence (latest .eval, on demand)\n"
            "  1. seed-evolver — target ignored verification step"
        ),
    )
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    for task in manager.received_tasks:
        assert "Recent audit evidence" in task.description
        assert "seed-evolver" in task.description
        # Original pilot signals still present.
        assert "Pilot dim_means" in task.description


def test_evolver_no_evidence_block_without_snapshot() -> None:
    state = _state_with_survivors(n=1)
    state.baseline_snapshot = None
    manager = _StubManager()
    Evolver(manager=manager).execute(state)  # type: ignore[arg-type]
    assert "Recent audit evidence" not in manager.received_tasks[0].description
