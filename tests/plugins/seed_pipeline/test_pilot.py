"""Tests for ``plugins.seed_pipeline.agents.pilot``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — ``_ReverseOrderManager`` returns results
  in reverse submission order to simulate variable LLM latency. Proves
  candidate-to-pilot mapping is by task_id, not position.
- **P7 Caller-Callee Contract Pair Read** — ``_REQUIRED_PILOT_FIELDS``
  + dim-dict + status-whitelist validation tested.
"""

from __future__ import annotations

import json
from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_pipeline.agents.pilot import Pilot
from plugins.seed_pipeline.orchestrator import PipelineState


def _good_pilot(candidate_id: str = "c-1") -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "dim_means": {"dim_01": 0.71, "dim_02": 0.55, "dim_03": 0.42},
        "dim_stderr": {"dim_01": 0.12, "dim_02": 0.18, "dim_03": 0.09},
        "status": "ok",
    }


class _StubManager:
    """Return one canned SubResult per task, in submission order."""

    def __init__(
        self,
        *,
        pilot_outputs: dict[str, dict[str, Any]] | None = None,
        force_failures: int = 0,
        force_unparseable: bool = False,
    ) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._pilots = pilot_outputs or {}
        self._force_failures = force_failures
        self._force_unparseable = force_unparseable

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        self.received_tasks = list(tasks)
        self.received_announce = announce
        results: list[SubResult] = []
        for i, t in enumerate(tasks):
            candidate_id = t.args["candidate_id"]
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
                output: Any = {"text": "not-valid-json"}
            else:
                pilot = self._pilots.get(candidate_id, _good_pilot(candidate_id))
                output = dict(pilot)
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
    """Returns SubResults in REVERSE submission order (worst-case latency)."""

    def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
        results = super().delegate(tasks, announce=announce)
        return list(reversed(results))


def _make_state(n: int = 3) -> PipelineState:
    return PipelineState(
        run_id="t-pilot",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
    )


def _seed_candidates(state: PipelineState, n: int) -> None:
    state.candidates = [
        {
            "id": f"gen2-{i:03d}-cand",
            "path": f"fake-run/candidates/gen2-{i:03d}-cand.md",
            "target_dim": "broken_tool_use",
            "gen_tag": "gen2",
            "task_id": f"gen-gen2-{i:03d}-cand",
            "duration_ms": 1000.0,
        }
        for i in range(n)
    ]


def test_pilot_builds_one_task_per_candidate() -> None:
    state = _make_state()
    _seed_candidates(state, 4)
    manager = _StubManager()
    Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 4
    for task in manager.received_tasks:
        assert task.agent == "seed_pilot"
        assert task.task_type == "seed-pilot"
        assert "candidate_id" in task.args
        assert "candidate_path" in task.args


def test_pilot_returns_scores_keyed_by_candidate_id() -> None:
    state = _make_state()
    _seed_candidates(state, 3)
    manager = _StubManager()
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    pilot_scores = result.output["pilot_scores"]
    assert isinstance(pilot_scores, dict)
    assert len(pilot_scores) == 3
    for candidate_id, pilot in pilot_scores.items():
        assert pilot["candidate_id"] == candidate_id
        assert "dim_means" in pilot
        assert "dim_stderr" in pilot
        assert pilot["status"] == "ok"


def test_pilot_pairs_by_task_id_under_reverse_order() -> None:
    """P1 — reverse-order completion must still pair correctly."""
    state = _make_state()
    _seed_candidates(state, 5)
    manager = _ReverseOrderManager()
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    pilot_scores = result.output["pilot_scores"]
    for candidate in state.candidates:
        cid = candidate["id"]
        assert cid in pilot_scores
        assert pilot_scores[cid]["candidate_id"] == cid


def test_pilot_drops_failed_sub_agents() -> None:
    state = _make_state()
    _seed_candidates(state, 5)
    manager = _StubManager(force_failures=2)
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert len(result.output["pilot_scores"]) == 3


def test_pilot_drops_unparseable_responses() -> None:
    """P7 — non-JSON output must be dropped, not silently merged."""
    state = _make_state()
    _seed_candidates(state, 3)
    manager = _StubManager(force_unparseable=True)
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_drops_malformed_partial_output() -> None:
    """P7 — pilot missing required fields must be dropped."""
    state = _make_state()
    _seed_candidates(state, 1)
    partial = {"candidate_id": "gen2-000-cand", "status": "ok"}
    manager = _StubManager(pilot_outputs={"gen2-000-cand": partial})
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_drops_non_dict_dim_means() -> None:
    """P7 — dim_means/dim_stderr must be dicts."""
    state = _make_state()
    _seed_candidates(state, 1)
    bad = {
        "candidate_id": "gen2-000-cand",
        "dim_means": [0.5, 0.6],  # wrong type
        "dim_stderr": {"dim_01": 0.1},
        "status": "ok",
    }
    manager = _StubManager(pilot_outputs={"gen2-000-cand": bad})
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_drops_invalid_status() -> None:
    """P7 — status must be one of the whitelisted values."""
    state = _make_state()
    _seed_candidates(state, 1)
    bad_status = {
        "candidate_id": "gen2-000-cand",
        "dim_means": {"dim_01": 0.7},
        "dim_stderr": {"dim_01": 0.1},
        "status": "broken",
    }
    manager = _StubManager(pilot_outputs={"gen2-000-cand": bad_status})
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "pilot_failed"


def test_pilot_accepts_timeout_status() -> None:
    """timeout and low_engagement are valid pilot statuses."""
    state = _make_state()
    _seed_candidates(state, 2)
    pilots = {
        "gen2-000-cand": {
            "candidate_id": "gen2-000-cand",
            "dim_means": {"dim_01": 0.0},
            "dim_stderr": {"dim_01": 0.0},
            "status": "timeout",
        },
        "gen2-001-cand": {
            "candidate_id": "gen2-001-cand",
            "dim_means": {"dim_01": 0.1},
            "dim_stderr": {"dim_01": 0.02},
            "status": "low_engagement",
        },
    }
    manager = _StubManager(pilot_outputs=pilots)
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    scores = result.output["pilot_scores"]
    assert scores["gen2-000-cand"]["status"] == "timeout"
    assert scores["gen2-001-cand"]["status"] == "low_engagement"


def test_pilot_accepts_text_json_fallback() -> None:
    """Sub-agent returning JSON string in output['text'] is parsed."""
    state = _make_state()
    _seed_candidates(state, 1)
    pilot_text = json.dumps(_good_pilot("gen2-000-cand"))

    class _TextJsonManager:
        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            return [
                SubResult(
                    task_id=tasks[0].task_id,
                    description=tasks[0].description,
                    success=True,
                    output={"text": pilot_text},
                    duration_ms=10.0,
                )
            ]

    result = Pilot(manager=_TextJsonManager()).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert "gen2-000-cand" in result.output["pilot_scores"]


def test_pilot_validates_empty_candidates() -> None:
    state = _make_state()
    manager = _StubManager()
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_pilot_announce_false() -> None:
    state = _make_state()
    _seed_candidates(state, 2)
    manager = _StubManager()
    Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_pilot_pins_candidate_id_from_task() -> None:
    """Even if LLM echoes a wrong candidate_id, the task's id wins."""
    state = _make_state()
    _seed_candidates(state, 1)
    wrong_id_pilot = _good_pilot("WRONG-id-from-llm")
    manager = _StubManager(pilot_outputs={"gen2-000-cand": wrong_id_pilot})
    result = Pilot(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    pilot_scores = result.output["pilot_scores"]
    assert "gen2-000-cand" in pilot_scores
    assert pilot_scores["gen2-000-cand"]["candidate_id"] == "gen2-000-cand"
    assert "WRONG-id-from-llm" not in pilot_scores


def test_pilot_drops_non_dict_outputs() -> None:
    """_parse_pilot returns None for list/None/scalar output shapes."""
    state = _make_state()
    _seed_candidates(state, 3)

    class _NonDictManager:
        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            shapes: list[Any] = [None, ["not", "a", "dict"], 42]
            return [
                SubResult(
                    task_id=t.task_id,
                    description=t.description,
                    success=True,
                    output=shape,
                    duration_ms=10.0,
                )
                for t, shape in zip(tasks, shapes, strict=True)
            ]

    result = Pilot(manager=_NonDictManager()).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "pilot_failed"
