"""X1 binary acceptance scoring, frozen-τ selective risk, McNemar (b, c) and analysis rows."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from evals.benchmarks import external_binary as x1
from evals.benchmarks.decision_metrics import (
    NOT_MEASURABLE,
    SELECTION_FREEZE_SCHEMA_ID,
    bootstrap_seed,
)
from scripts.eval.contract import validate_analysis

from tests.scripts.test_eval_contract import _run_spec, _workload_hash

MANIFEST = "03002e70" + "0" * 56


def _receipt(verdict: str, p_accept: float, q: float) -> dict[str, Any]:
    rest = (1 - p_accept) / 2
    return {
        "accepted": True,
        "verdict": verdict,
        "probabilities": {
            "supported": p_accept,
            "contradicted": rest,
            "insufficient_evidence": rest,
        },
        "q": q,
    }


# (gold_accept, receipt or None for an invalid output); hand-computed below.
_ENGINE = [
    (True, _receipt("supported", 0.9, 0.9)),  # accept, correct
    (True, _receipt("supported", 0.6, 0.6)),  # accept, correct
    (True, _receipt("insufficient_evidence", 0.3, 0.5)),  # reject: false rejection
    (True, {"accepted": False}),  # invalid: false rejection, wrong
    (False, _receipt("supported", 0.6, 0.6)),  # false acceptance
    (False, _receipt("contradicted", 0.1, 0.8)),  # reject, correct
    (False, _receipt("insufficient_evidence", 0.2, 0.7)),  # reject, correct
    (False, None),  # invalid: wrong, never an acceptance
]


def _records() -> list[x1.BinaryRecord]:
    return [
        x1.binary_record(f"x1-{index}", "c", gold, receipt)
        for index, (gold, receipt) in enumerate(_ENGINE)
    ]


def test_binary_record_follows_the_readme_decision_rule() -> None:
    records = _records()
    assert [record.verdict for record in records] == [
        "supported",
        "supported",
        "insufficient_evidence",
        None,
        "supported",
        "contradicted",
        "insufficient_evidence",
        None,
    ]
    assert [record.accepted for record in records] == [1, 1, 0, 0, 1, 0, 0, 0]
    assert [record.correct for record in records] == [1, 1, 0, 0, 0, 1, 1, 0]
    assert (records[3].p_accept, records[3].q) == (None, None)
    with pytest.raises(ValueError, match="needs verdict, probabilities and q"):
        x1.binary_record("x1-bad", "c", True, {"accepted": True, "verdict": "supported"})


def test_hand_computed_engine_metrics() -> None:
    metrics = {
        key: value.as_dict() if value else None
        for key, value in x1.engine_metrics(_records()).items()
    }
    assert metrics["binary_accuracy"] == {"value": 0.5, "numerator": 4, "denominator": 8}
    assert metrics["false_acceptance_rate"] == {"value": 0.25, "numerator": 1, "denominator": 4}
    assert metrics["false_rejection_rate"] == {"value": 0.5, "numerator": 2, "denominator": 4}
    assert metrics["true_positive_rate"]["numerator"] == 2
    assert metrics["true_negative_rate"]["numerator"] == 2
    assert metrics["balanced_accuracy"] == {"value": 0.5, "numerator": 1.0, "denominator": 2}
    # Valid P(supported): successes 0.9, 0.6, 0.3; failures 0.6, 0.1, 0.2 -> U = 3 + 2.5 + 2.
    assert metrics["accept_auroc"] == {"value": 7.5 / 9, "numerator": 7.5, "denominator": 9}
    only_successes = [record for record in _records() if record.gold_accept]
    assert x1.accept_auroc(only_successes) is None


@pytest.mark.parametrize(
    ("tau", "coverage", "risk"),
    [
        # Receipt q: items 0, 5, 6 (q 0.9, 0.8, 0.7). The binary projection
        # max(p, 1 - p) would also include item 2 (0.7) and make the risk 1/4.
        (0.7, (3, 8), (0, 3)),
        (0.95, (0, 8), None),
        (None, None, None),
    ],
)
def test_selective_risk_uses_the_receipt_q_and_the_frozen_tau(
    tau: float | None, coverage: tuple[int, int] | None, risk: tuple[int, int] | None
) -> None:
    result = x1.selective_risk(_records(), tau)
    for name, expected in (("coverage", coverage), ("risk", risk)):
        value = result[name]
        if expected is None:
            assert value is None or value.value is None
        else:
            assert value is not None and (value.numerator, value.denominator) == expected


def _item(index: int, clusters: int, right: bool, separating: bool) -> x1.BinaryRecord:
    gold = index % 2 == 0
    accept = gold if right else not gold
    p = (0.9 if gold else 0.1) if separating else 0.5
    receipt = _receipt("supported" if accept else "contradicted", p, 0.9)
    return x1.binary_record(f"x1-{index:02d}", f"cl-{index % clusters}", gold, receipt)


def _pairs(jev_correct: int, llm_correct: int, clusters: int = 10) -> list[Any]:
    """30 items in ``clusters`` clusters; the first N of each engine are right."""
    return [
        (
            _item(index, clusters, index < llm_correct, separating=False),
            _item(index, clusters, index < jev_correct, separating=True),
        )
        for index in range(30)
    ]


def test_report_primary_interval_mcnemar_and_decision() -> None:
    report = x1.x1_report(_pairs(30, 20), split_manifest_sha256=MANIFEST, tau=0.9)
    assert report["primary"] | {"interval": None} == {
        "name": "x1_binary_verdict_accuracy_delta",
        "reasons": [],
        "value": 10 / 30,
        "numerator": 10,
        "denominator": 30,
        "interval": None,
    }
    interval = report["primary"]["interval"]
    assert interval["seed"] == bootstrap_seed(MANIFEST, "x1_binary_verdict_accuracy_delta")
    assert interval["clusters"] == 10 and interval["lower"] > -0.05
    assert report["jev_accept_auroc_interval"]["lower"] == 1.0
    assert report["mcnemar"] == {
        "b": {"value": 10 / 30, "numerator": 10, "denominator": 30},
        "c": {"value": 0.0, "numerator": 0, "denominator": 30},
    }
    assert report["engines"]["jev"]["selective"]["coverage"]["numerator"] == 30
    assert report["verdicts"]["llm"]["gold_accept"]["contradicted"] == 5
    assert report["decision"] == "supported"
    again = x1.x1_report(_pairs(30, 20), split_manifest_sha256=MANIFEST, tau=0.9)
    assert json.dumps(report, sort_keys=True) == json.dumps(again, sort_keys=True)
    worse = x1.x1_report(_pairs(10, 30), split_manifest_sha256=MANIFEST, tau=0.9)
    assert worse["primary"]["interval"]["upper"] < -0.05 and worse["decision"] == "not-supported"
    assert worse["mcnemar"]["c"]["numerator"] == 20
    few = x1.x1_report(_pairs(30, 20, clusters=5), split_manifest_sha256=MANIFEST, tau=0.9)
    assert few["primary"]["interval"]["lower"] is None and few["decision"] == "mixed"
    stopped = x1.x1_report(
        _pairs(30, 20), split_manifest_sha256=MANIFEST, tau=None, reasons=["missing_judgment"]
    )
    assert stopped["primary"]["value"] == NOT_MEASURABLE and stopped["primary"]["interval"] is None
    assert stopped["decision"] == "invalidated"
    assert stopped["engines"]["jev"]["selective"]["risk"]["value"] == NOT_MEASURABLE
    with pytest.raises(ValueError, match="share item, cluster and human label"):
        x1.x1_report(
            [(_pairs(1, 1)[0][0], _pairs(1, 1)[1][1])], split_manifest_sha256=MANIFEST, tau=None
        )


def test_gold_is_read_for_planned_states_only(tmp_path: Path) -> None:
    gold = tmp_path / "gold.x1.jsonl"
    rows = [
        {"state_id": "x1-a", "gold_accept": True, "votes": {"Correct": 2, "Incorrect": 1}},
        {"state_id": "x1-b", "gold_accept": False},
        {"state_id": "x1-tie", "gold_accept": None},  # outside the plan: ignored
    ]
    gold.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert x1.load_gold(gold, ["x1-b", "x1-a"]) == {"x1-b": False, "x1-a": True}
    for planned in (["x1-a", "x1-missing"], ["x1-tie"]):
        with pytest.raises(ValueError, match="lacks a boolean gold_accept"):
            x1.load_gold(gold, planned)
    gold.write_text(json.dumps(rows[0]) + "\n" + json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gold repeats"):
        x1.load_gold(gold, ["x1-a"])


def test_frozen_tau_comes_from_the_selection_freeze() -> None:
    freeze = {"schema_id": SELECTION_FREEZE_SCHEMA_ID, "cascade": {"tau": 0.9}}
    assert x1.frozen_tau(freeze) == 0.9
    assert x1.frozen_tau(freeze | {"cascade": {"tau": None}}) is None
    with pytest.raises(ValueError, match="off the preregistered grid"):
        x1.frozen_tau(freeze | {"cascade": {"tau": 0.91}})
    with pytest.raises(ValueError, match="not a selection freeze"):
        x1.frozen_tau({"cascade": {"tau": 0.9}})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("reasons", [[], ["selected_invalid_attempt"]])
def test_rows_bind_to_the_report_under_the_evaluation_contract(
    tmp_path: Path, reasons: list[str]
) -> None:
    pairs = _pairs(30, 20)
    report = x1.x1_report(pairs, split_manifest_sha256=MANIFEST, tau=0.9, reasons=reasons)
    results = tmp_path / x1.RESULTS
    results.write_text(json.dumps(report, sort_keys=True, allow_nan=False), encoding="utf-8")
    reference = {"kind": "native-result", "path": x1.RESULTS, "sha256": _sha(results)}
    invalid = bool(reasons)
    at = "2026-02-01T00:00:00Z"
    attempt = {
        "schema_id": "geode.eval-attempt@1",
        "schema_version": 1,
        "run_id": "geode-jev-x1",
        "attempt_id": "geode-jev-x1-aggregate",
        "parent_attempt_id": None,
        "sequence": 0,
        "timing": {"status": "exact", "started_at": at, "finished_at": at, "source_ref": None},
        "validity": "invalid" if invalid else "valid",
        "outcome": "unknown" if invalid else "mixed",
        "change": {"surface": "analysis-only", "description": "Synthetic X1 aggregation."},
        "expected_effect": "Binary acceptance agreement with human labels.",
        "observed_result": "synthetic",
        "failure_class": "incomplete_planned_cells" if invalid else None,
        "error_ref": None,
        "evidence_refs": [reference],
        "selected_for_analysis": True,
    }
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
    spec_doc: dict[str, Any] = _run_spec()
    ids = [llm.item_id for llm, _ in pairs]
    spec_doc["run_id"] = "geode-jev-x1"
    spec_doc["created_at"] = spec_doc["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec_doc["study"]["primary_metric"] = {
        "name": x1.PRIMARY,
        "unit": "ratio",
        "direction": "target",
        "aggregation": "(Jev binary-correct - Astra binary-correct) / planned states",
        "denominator": len(ids),
    }
    spec_doc["reproduction"]["execution"].update(
        ordered_workload_ids=ids, workload_ids_sha256=_workload_hash(ids)
    )
    spec = tmp_path / "run-spec.json"
    spec.write_text(json.dumps(spec_doc), encoding="utf-8")
    rows = x1.x1_metric_rows(report)
    assert [row["name"] for row in rows] == [
        "x1_binary_verdict_accuracy_delta",
        *(f"x1_{engine}_{metric}" for engine in ("jev", "llm") for metric in x1.ROW_METRICS),
        "x1_jev_selective_coverage",
        "x1_jev_selective_risk",
        "x1_mcnemar_b",
        "x1_mcnemar_c",
    ]
    assert (rows[0]["value"] == NOT_MEASURABLE) is invalid
    analysis = tmp_path / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "schema_id": "geode.eval-analysis@1",
                "schema_version": 1,
                "run_id": "geode-jev-x1",
                "analyzed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_spec_sha256": _sha(spec),
                "attempts_sha256": _sha(attempts),
                "selected_attempt_ids": [attempt["attempt_id"]],
                "answer": "Synthetic X1 binary aggregation; no model was called.",
                "metrics": rows,
                "decision": {
                    "outcome": "diagnostic-only",
                    "hypothesis_status": report["decision"],
                    "rationale": "External validity check on synthetic records.",
                },
                "limitations": ["Synthetic fixture."],
                "evidence_refs": [reference],
            }
        ),
        encoding="utf-8",
    )
    validate_analysis(analysis, run_spec_path=spec, attempts_path=attempts)
