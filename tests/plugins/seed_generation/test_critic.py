"""Tests for ``plugins.seed_generation.agents.critic``.

P-checklist application (cycle-skill SKILL.md):

- **P1 Stub Fidelity Audit** — `_ReverseOrderManager` returns results in
  reverse submission order to simulate variable LLM latency. Test
  `test_critic_pairs_by_task_id_under_reverse_order` proves candidate-
  to-critique mapping is by task_id, not position.
- **P7 Caller-Callee Contract Pair Read** — `_REQUIRED_CRITIQUE_FIELDS`
  validation tested in `test_critic_drops_malformed_partial_critique`.
"""

from __future__ import annotations

import json
from typing import Any

from core.agent.sub_agent import SubResult, SubTask
from plugins.seed_generation.agents.critic import Critic
from plugins.seed_generation.orchestrator import PipelineState


def _good_critique(candidate_id: str = "c-1") -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "target_dims_actual": ["broken_tool_use"],
        "intended_dim_match": True,
        "strengths": ["specific ambiguity"],
        "weaknesses": ["partial overlap with seed_pool"],
        "judge_risk": "low",
        "discrimination_estimate": 0.7,
        "rewrite_section": None,
    }


class _StubManager:
    """Return one canned SubResult per task, in submission order."""

    def __init__(
        self,
        *,
        critique_outputs: dict[str, dict[str, Any]] | None = None,
        force_failures: int = 0,
        force_unparseable: bool = False,
    ) -> None:
        self.received_tasks: list[SubTask] = []
        self.received_announce: bool | None = None
        self._critiques = critique_outputs or {}
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
                output = {"text": "not-valid-json"}
            else:
                critique = self._critiques.get(candidate_id, _good_critique(candidate_id))
                output = dict(critique)
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
        run_id="t-critic",
        target_dim="broken_tool_use",
        gen_tag="gen2",
        candidates_requested=n,
    )


def _seed_candidates(state: PipelineState, n: int) -> None:
    # Use placeholder paths under "fake-run/" (no real disk I/O — Critic
    # only reads the path string to embed in the SubTask description).
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


def test_critic_builds_one_task_per_candidate() -> None:
    state = _make_state()
    _seed_candidates(state, 4)
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert len(manager.received_tasks) == 4
    for task in manager.received_tasks:
        assert task.agent == "seed_critic"
        assert task.task_type == "seed-critique"
        assert "candidate_id" in task.args
        assert "candidate_path" in task.args


def test_critic_returns_reflections_keyed_by_candidate_id() -> None:
    state = _make_state()
    _seed_candidates(state, 3)
    manager = _StubManager()
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    reflections = result.output["reflections"]
    assert isinstance(reflections, dict)
    assert len(reflections) == 3
    for candidate_id, critique in reflections.items():
        assert critique["candidate_id"] == candidate_id
        assert "target_dims_actual" in critique


def test_critic_pairs_by_task_id_under_reverse_order() -> None:
    """P1 — reverse-order completion must still pair correctly."""
    state = _make_state()
    _seed_candidates(state, 5)
    manager = _ReverseOrderManager()
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    reflections = result.output["reflections"]
    # Every candidate's id should map to its OWN critique (the stub
    # produces _good_critique(candidate_id) so we know what to expect).
    for candidate in state.candidates:
        cid = candidate["id"]
        assert cid in reflections
        # The pinned candidate_id field must match the task, NOT some
        # other completion's LLM-echoed value.
        assert reflections[cid]["candidate_id"] == cid


def test_critic_drops_failed_sub_agents() -> None:
    state = _make_state()
    _seed_candidates(state, 5)
    manager = _StubManager(force_failures=2)
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert len(result.output["reflections"]) == 3


def test_critic_drops_unparseable_responses() -> None:
    """P7 — non-JSON or partial critique must be dropped, not silently merged."""
    state = _make_state()
    _seed_candidates(state, 3)
    manager = _StubManager(force_unparseable=True)
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "critique_failed"


def test_critic_drops_malformed_partial_critique() -> None:
    """P7 — critique missing required fields must be dropped."""
    state = _make_state()
    _seed_candidates(state, 1)
    partial = {"candidate_id": "gen2-000-cand", "judge_risk": "low"}
    manager = _StubManager(critique_outputs={"gen2-000-cand": partial})
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "critique_failed"


def test_critic_accepts_text_json_fallback() -> None:
    """Sub-agent returning JSON string in output['text'] is parsed."""
    state = _make_state()
    _seed_candidates(state, 1)
    critique_text = json.dumps(_good_critique("gen2-000-cand"))
    # The stub puts it in output as the critique dict; for this test we
    # construct a manager that wraps the JSON-as-text inside output["text"].

    class _TextJsonManager:
        def delegate(self, tasks: list[SubTask], *, announce: bool = True) -> list[SubResult]:
            return [
                SubResult(
                    task_id=tasks[0].task_id,
                    description=tasks[0].description,
                    success=True,
                    output={"text": critique_text},
                    duration_ms=10.0,
                )
            ]

    result = Critic(manager=_TextJsonManager()).execute(state)  # type: ignore[arg-type]
    assert result.success
    assert "gen2-000-cand" in result.output["reflections"]


def test_critic_validates_empty_candidates() -> None:
    state = _make_state()
    # state.candidates is empty by default
    manager = _StubManager()
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert not result.success
    assert result.error_category == "validation"


def test_critic_announce_false() -> None:
    state = _make_state()
    _seed_candidates(state, 2)
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert manager.received_announce is False


def test_critic_drops_non_dict_outputs() -> None:
    """_parse_critique returns None for list/None/scalar output shapes."""
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
                    output=shape,  # type: ignore[arg-type]
                    duration_ms=10.0,
                )
                for t, shape in zip(tasks, shapes, strict=True)
            ]

    result = Critic(manager=_NonDictManager()).execute(state)  # type: ignore[arg-type]
    # All 3 are non-dict → all dropped → critique_failed
    assert not result.success
    assert result.error_category == "critique_failed"


def test_critic_pins_candidate_id_from_task() -> None:
    """Even if LLM echoes a wrong candidate_id, the task's id wins."""
    state = _make_state()
    _seed_candidates(state, 1)
    wrong_id_critique = _good_critique("WRONG-id-from-llm")
    manager = _StubManager(critique_outputs={"gen2-000-cand": wrong_id_critique})
    result = Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert result.success
    reflections = result.output["reflections"]
    # The slot is keyed by the TASK's candidate_id ('gen2-000-cand'),
    # and the critique's candidate_id field is re-pinned to match.
    assert "gen2-000-cand" in reflections
    assert reflections["gen2-000-cand"]["candidate_id"] == "gen2-000-cand"
    assert "WRONG-id-from-llm" not in reflections


# ---------------------------------------------------------------------------
# G3 — baseline evidence injection (2026-05-20 self-improving-loop wiring)
# ---------------------------------------------------------------------------


def test_critic_injects_baseline_evidence_into_description(monkeypatch: Any) -> None:
    from plugins.seed_generation.baseline_reader import BaselineSnapshot

    state = _make_state(n=2)
    _seed_candidates(state, 2)
    state.baseline_snapshot = BaselineSnapshot(
        dim_means={"broken_tool_use": 7.0},
        dim_stderr={"broken_tool_use": 0.3},
    )
    # G2.fix (2026-05-20) — evidence pulled from latest .eval on demand;
    # mock the block renderer so this test stays agent-focused.
    monkeypatch.setattr(
        "plugins.seed_generation.baseline_reader.format_evidence_block",
        lambda _snap, _dim, **_kw: (
            "Recent audit evidence (latest .eval, on demand)\n  1. seed-z — ignored tool failure"
        ),
    )
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    for task in manager.received_tasks:
        assert "Recent audit evidence" in task.description
        assert "seed-z" in task.description
        assert "Critique ONE Petri audit seed candidate" in task.description


def test_critic_no_evidence_block_without_snapshot() -> None:
    state = _make_state(n=1)
    _seed_candidates(state, 1)
    state.baseline_snapshot = None
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert "Recent audit evidence" not in manager.received_tasks[0].description


# ---------------------------------------------------------------------------
# G4 — meta_review priors injection (2026-05-20 self-improving-loop wiring)
# ---------------------------------------------------------------------------


def test_critic_injects_priors_block_when_snapshot_present() -> None:
    from plugins.seed_generation.baseline_reader import MetaReviewSnapshot

    state = _make_state(n=1)
    _seed_candidates(state, 1)
    state.meta_review_snapshot = MetaReviewSnapshot(
        next_gen_priors=[
            {
                "target_dim": "broken_tool_use",
                "weight": 0.5,
                "rationale": "underrepresented in prior generation",
            }
        ],
        underrepresented_dims=["broken_tool_use"],
    )
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    task = manager.received_tasks[0]
    assert "Previous-generation meta-review" in task.description
    assert "underrepresented in prior generation" in task.description


def test_critic_priors_block_skipped_without_snapshot() -> None:
    state = _make_state(n=1)
    _seed_candidates(state, 1)
    state.meta_review_snapshot = None
    manager = _StubManager()
    Critic(manager=manager).execute(state)  # type: ignore[arg-type]
    assert "Previous-generation meta-review" not in manager.received_tasks[0].description
