import json
from pathlib import Path

import pytest
from plugins.crucible.contract import ContractError
from plugins.crucible.runtime_identity import canonical_runtime_hash, runtime_regime_id
from plugins.crucible.runtime_receipt import SharedRuntimeDeadline, load_runtime_receipt

from tests.plugins.crucible.test_promotion import _contract


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_shared_deadline_gives_candidate_the_actual_baseline_remainder(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    clock = _Clock()
    deadline = SharedRuntimeDeadline(contract, 100.0, clock=clock)

    baseline = deadline.begin_arm("baseline")
    assert baseline.allocated_wall_seconds == 100.0
    clock.advance(60.0)
    deadline.finish_arm(baseline, "complete")

    candidate = deadline.begin_arm("candidate")
    assert candidate.allocated_wall_seconds == 40.0
    clock.advance(10.0)
    deadline.finish_arm(candidate, "complete")
    cleanup_started = clock()
    clock.advance(2.0)
    deadline.record_cleanup("fixture_cleanup", cleanup_started)

    path = tmp_path / "runtime.receipt.json"
    written = deadline.write(path, "complete")
    loaded = load_runtime_receipt(path, contract=contract)

    assert loaded == written
    assert loaded["observation"]["observed_wall_seconds"] == 72.0
    assert loaded["cleanup"]["observed_wall_seconds"] == 2.0


def test_runtime_receipt_preserves_a_right_censored_lower_bound(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    clock = _Clock()
    deadline = SharedRuntimeDeadline(contract, 100.0, clock=clock)
    baseline = deadline.begin_arm("baseline")
    clock.advance(101.0)
    deadline.finish_arm(baseline, "right_censored")

    path = tmp_path / "runtime.receipt.json"
    receipt = deadline.write(
        path,
        "right_censored",
        censoring_reason="shared_experiment_deadline",
    )

    loaded = load_runtime_receipt(path, contract=contract)
    assert loaded["observation"]["observed_wall_seconds"] == 101.0
    assert loaded["observation"]["censoring"] == {
        "kind": "right",
        "limit_seconds": 100.0,
        "reason": "shared_experiment_deadline",
    }
    assert receipt["arms"][0]["outcome"] == "right_censored"


def test_runtime_receipt_binds_a_shortened_live_wall_as_a_distinct_regime(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    deadline = SharedRuntimeDeadline(contract, 80.0, clock=_Clock())
    baseline = deadline.begin_arm("baseline")
    deadline.finish_arm(baseline, "complete")
    deadline.record_synthetic_arm("candidate", "screened")
    path = tmp_path / "runtime.receipt.json"
    receipt = deadline.write(path, "complete")

    loaded = load_runtime_receipt(path, contract=contract)

    assert loaded == receipt
    assert loaded["configured_experiment_wall_seconds"] == 80.0
    assert loaded["runtime_regime_id"] == runtime_regime_id(
        contract,
        experiment_wall_seconds=80.0,
    )
    assert loaded["runtime_regime_id"] != runtime_regime_id(contract)


def test_runtime_receipt_rejects_a_wall_above_the_frozen_contract(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    deadline = SharedRuntimeDeadline(contract, 101.0, clock=_Clock())
    baseline = deadline.begin_arm("baseline")
    deadline.finish_arm(baseline, "complete")
    deadline.record_synthetic_arm("candidate", "screened")
    path = tmp_path / "runtime.receipt.json"
    deadline.write(path, "complete")

    with pytest.raises(ContractError, match="exceeds the frozen contract wall"):
        load_runtime_receipt(path, contract=contract)


def test_runtime_receipt_rejects_a_rehashed_semantic_inconsistency(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    clock = _Clock()
    deadline = SharedRuntimeDeadline(contract, 100.0, clock=clock)
    baseline = deadline.begin_arm("baseline")
    deadline.finish_arm(baseline, "complete")
    candidate = deadline.begin_arm("candidate")
    deadline.finish_arm(candidate, "complete")
    path = tmp_path / "runtime.receipt.json"
    deadline.write(path, "complete")

    row = json.loads(path.read_text(encoding="utf-8"))
    row["arms"][1]["outcome"] = "right_censored"
    payload = {key: value for key, value in row.items() if key != "runtime_receipt_id"}
    row["runtime_receipt_id"] = canonical_runtime_hash(payload)
    path.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(ContractError, match="complete runtime receipt"):
        load_runtime_receipt(path, contract=contract)


def test_runtime_receipt_rejects_candidate_budget_replenishment(tmp_path: Path) -> None:
    contract = _contract(stage="train")
    clock = _Clock()
    deadline = SharedRuntimeDeadline(contract, 100.0, clock=clock)
    baseline = deadline.begin_arm("baseline")
    clock.advance(60.0)
    deadline.finish_arm(baseline, "complete")
    candidate = deadline.begin_arm("candidate")
    deadline.finish_arm(candidate, "complete")
    path = tmp_path / "runtime.receipt.json"
    deadline.write(path, "complete")

    row = json.loads(path.read_text(encoding="utf-8"))
    row["arms"][1]["allocated_wall_seconds"] = 100.0
    payload = {key: value for key, value in row.items() if key != "runtime_receipt_id"}
    row["runtime_receipt_id"] = canonical_runtime_hash(payload)
    path.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(ContractError, match="exceeds the shared baseline remainder"):
        load_runtime_receipt(path, contract=contract)


def test_runtime_receipt_cannot_label_an_overrun_complete() -> None:
    contract = _contract(stage="train")
    clock = _Clock()
    deadline = SharedRuntimeDeadline(contract, 100.0, clock=clock)
    baseline = deadline.begin_arm("baseline")
    clock.advance(101.0)
    deadline.finish_arm(baseline, "complete")
    deadline.record_synthetic_arm("candidate", "screened")

    with pytest.raises(ContractError, match="exceeds its configured experiment wall"):
        deadline.payload("complete")


def test_shared_deadline_rejects_out_of_order_arms() -> None:
    deadline = SharedRuntimeDeadline(_contract(stage="train"), 100.0, clock=_Clock())

    with pytest.raises(ContractError, match="requires 'baseline'"):
        deadline.begin_arm("candidate")
