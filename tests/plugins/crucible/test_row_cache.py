import json
from dataclasses import dataclass
from pathlib import Path

from plugins.crucible.row_cache import (
    cached_context,
    cached_rows,
    harvest_arm_rows,
    merge_results,
    missing_task_ids,
    selected_expected_rows,
    synthesized_snapshot,
)


@dataclass(frozen=True)
class _StubContract:
    """Only the identity surface the row cache reads."""

    task_ids: tuple[str, ...] = ("task-b", "task-a", "task-c")
    trials_per_task: int = 2
    baseline_sha: str = "1" * 40
    candidate_sha: str = "2" * 40
    evaluator_sha256: str = "e" * 64
    harness_sha256: str = "b" * 64
    task_pack_sha256: str = "c" * 64
    assay_config_sha256: str = "d" * 64
    contract_id: str = "f" * 64
    assay_config: dict | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assay_config", {"schema": "crucible.tau2-assay.v1"})


def _simulation(
    task_id: str,
    trial: int,
    *,
    reward: float = 0.0,
    termination_reason: str = "user_stop",
) -> dict:
    return {
        "task_id": task_id,
        "trial": trial,
        "termination_reason": termination_reason,
        "reward_info": {"reward": reward},
        "messages": [],
    }


def _partial_raw(rows: list[dict]) -> dict:
    return {
        "info": {"num_trials": 2, "seed": 300},
        "tasks": [{"id": task_id} for task_id in ("task-b", "task-a", "task-c")],
        "simulations": rows,
    }


def test_harvest_lookup_roundtrip_from_partial_results(tmp_path: Path) -> None:
    contract = _StubContract()
    # r23 shape: an interrupted run donates only its finalized simulations.
    stored = harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results=_partial_raw(
            [
                _simulation("task-b", 0),
                _simulation("task-b", 1),
                _simulation("task-a", 0, reward=1.0),
                {"task_id": "task-a", "trial": 1, "termination_reason": None},
            ]
        ),
    )
    assert stored == 3  # the in-flight row (no termination) is never persisted
    rows = cached_rows(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
    )
    assert set(rows) == {("task-b", 0), ("task-b", 1), ("task-a", 0)}
    context = cached_context(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
    )
    assert context is not None and len(context["tasks"]) == 3
    assert missing_task_ids(contract, rows) == ["task-a", "task-c"]


def test_harvest_excludes_r23_infrastructure_placeholders(tmp_path: Path) -> None:
    contract = _StubContract(trials_per_task=1)
    stored = harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.candidate_sha,
        raw_results=_partial_raw(
            [
                _simulation("task-b", 0, reward=1.0),
                _simulation("task-a", 0, termination_reason="infrastructure_error"),
                _simulation("task-c", 0, termination_reason="unexpected_error"),
            ]
        ),
    )

    assert stored == 1
    rows = cached_rows(tmp_path, contract, revision_sha=contract.candidate_sha)
    assert set(rows) == {("task-b", 0)}
    assert missing_task_ids(contract, rows) == ["task-a", "task-c"]


def test_harvest_ignores_unknown_termination_instead_of_masking_abort(tmp_path: Path) -> None:
    contract = _StubContract(trials_per_task=1)
    stored = harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.candidate_sha,
        raw_results=_partial_raw(
            [_simulation("task-b", 0, termination_reason="new_upstream_reason")]
        ),
    )

    assert stored == 0
    assert cached_rows(tmp_path, contract, revision_sha=contract.candidate_sha) == {}


def test_rows_from_a_different_identity_are_ignored(tmp_path: Path) -> None:
    contract = _StubContract()
    harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results=_partial_raw([_simulation("task-a", 0)]),
    )
    other_evaluator = _StubContract(evaluator_sha256="9" * 64)
    assert (
        cached_rows(
            tmp_path,
            other_evaluator,
            revision_sha=other_evaluator.baseline_sha,
        )
        == {}
    )
    assert (
        cached_context(
            tmp_path,
            other_evaluator,
            revision_sha=other_evaluator.baseline_sha,
        )
        is None
    )


def test_tampered_cached_row_is_refused(tmp_path: Path) -> None:
    contract = _StubContract()
    harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results=_partial_raw([_simulation("task-a", 0)]),
    )
    row_files = [path for path in tmp_path.rglob("*.json") if path.name != "context.json"]
    assert len(row_files) == 1
    stored = json.loads(row_files[0].read_text())
    stored["simulation"]["reward_info"]["reward"] = 1.0  # repaired-and-reused, the July sin
    row_files[0].write_text(json.dumps(stored))
    assert cached_rows(tmp_path, contract, revision_sha=contract.baseline_sha) == {}


def test_tampered_cached_context_is_refused(tmp_path: Path) -> None:
    contract = _StubContract()
    harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.baseline_sha,
        raw_results=_partial_raw([_simulation("task-a", 0)]),
    )
    context_path = next(tmp_path.rglob("context.json"))
    stored = json.loads(context_path.read_text())
    stored["info"]["seed"] = 999
    context_path.write_text(json.dumps(stored))

    assert cached_context(tmp_path, contract, revision_sha=contract.baseline_sha) is None


def test_merge_rebuilds_full_results_in_stable_order(tmp_path: Path) -> None:
    contract = _StubContract()
    harvest_arm_rows(
        tmp_path,
        contract,
        revision_sha=contract.candidate_sha,
        raw_results=_partial_raw([_simulation("task-b", 0), _simulation("task-b", 1)]),
    )
    rows = cached_rows(
        tmp_path,
        contract,
        revision_sha=contract.candidate_sha,
    )
    fresh = {
        ("task-a", 0): _simulation("task-a", 0),
        ("task-a", 1): _simulation("task-a", 1),
        ("task-c", 0): _simulation("task-c", 0),
        ("task-c", 1): _simulation("task-c", 1),
    }
    context = cached_context(
        tmp_path,
        contract,
        revision_sha=contract.candidate_sha,
    )
    assert context is not None
    merged = merge_results(context, {**rows, **fresh})
    pairs = [(row["task_id"], row["trial"]) for row in merged["simulations"]]
    assert pairs == [
        ("task-b", 0),
        ("task-b", 1),
        ("task-a", 0),
        ("task-a", 1),
        ("task-c", 0),
        ("task-c", 1),
    ]
    assert len(merged["tasks"]) == 3
    assert not missing_task_ids(
        contract,
        selected_expected_rows(contract, {**rows, **fresh}),
    )


def test_synthesized_snapshot_matches_the_verifier_contract_fields() -> None:
    from tests.plugins.crucible.test_tau2_live import _contract

    contract = _contract()
    raw_sha = "a" * 64
    snapshot = synthesized_snapshot(contract, arm="candidate", raw_sha256=raw_sha)
    from plugins.crucible.verifiers.tau2 import _verify_snapshot

    status, failure_class = _verify_snapshot(
        contract,
        arm="candidate",
        raw_sha256=raw_sha,
        snapshot=snapshot,
    )
    assert status == "complete" and failure_class is None
