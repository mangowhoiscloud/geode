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


ROW_NAMES = [
    "x1_binary_verdict_accuracy_delta",
    *(f"x1_{engine}_{metric}" for engine in ("jev", "llm") for metric in x1.ROW_METRICS),
    "x1_jev_selective_coverage",
    "x1_jev_selective_risk",
    "x1_mcnemar_b",
    "x1_mcnemar_c",
    *(
        name
        for engine in ("jev", "llm")
        for name in (
            *(f"x1_{engine}_{metric}" for metric in x1.DESCRIPTIVE_ROW_METRICS),
            f"x1_{engine}_frozen_t_accept_brier",
            f"x1_{engine}_frozen_t_accept_ece",
        )
    ),
    "x1_cascade_accuracy",
    "x1_cascade_coverage",
]


def _x1_spec(path: Path, run_id: str, ids: list[str]) -> Path:
    spec: dict[str, Any] = _run_spec()
    spec["run_id"] = run_id
    spec["created_at"] = spec["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec["study"]["primary_metric"] = {
        "name": x1.PRIMARY,
        "unit": "ratio",
        "direction": "target",
        "aggregation": "(Jev binary-correct - Astra binary-correct) / planned states",
        "denominator": len(ids),
    }
    spec["reproduction"]["execution"].update(
        ordered_workload_ids=ids, workload_ids_sha256=_workload_hash(ids)
    )
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _validate(run_dir: Path, spec: Path, rows: list[dict[str, Any]], decision: str) -> None:
    attempts = run_dir / "attempts.jsonl"
    selected = [
        row
        for row in (json.loads(line) for line in attempts.read_text().splitlines())
        if row["selected_for_analysis"]
    ]
    analysis = run_dir / "analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "schema_id": "geode.eval-analysis@1",
                "schema_version": 1,
                "run_id": selected[0]["run_id"],
                "analyzed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_spec_sha256": _sha(spec),
                "attempts_sha256": _sha(attempts),
                "selected_attempt_ids": [row["attempt_id"] for row in selected],
                "answer": "Synthetic X1 binary aggregation; no model was called.",
                "metrics": rows,
                "decision": {
                    "outcome": "diagnostic-only",
                    "hypothesis_status": decision,
                    "rationale": "External validity check on synthetic records.",
                },
                "limitations": ["Synthetic fixture."],
                "evidence_refs": [ref for row in selected for ref in row["evidence_refs"]],
            }
        ),
        encoding="utf-8",
    )
    validate_analysis(analysis, run_spec_path=spec, attempts_path=attempts)


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
    ids = [llm.item_id for llm, _ in pairs]
    spec = _x1_spec(tmp_path / "run-spec.json", "geode-jev-x1", ids)
    rows = x1.x1_metric_rows(report)
    assert [row["name"] for row in rows] == ROW_NAMES
    assert (rows[0]["value"] == NOT_MEASURABLE) is invalid
    _validate(tmp_path, spec, rows, report["decision"])


# ---------------------------------------------------------------------------
# Descriptive metrics (05 §11.4), hand-computed on the eight records above
# ---------------------------------------------------------------------------


def test_descriptive_calibration_error_detection_and_risk_coverage() -> None:
    records = _records()
    raw = {key: value.as_dict() for key, value in x1.accept_calibration(records).items() if value}
    # Valid P(supported): (.9, T), (.6, T), (.3, T), (.6, F), (.1, F), (.2, F).
    assert raw["accept_brier"]["denominator"] == 6
    assert raw["accept_brier"]["value"] == pytest.approx(1.07 / 6)
    # Bins 9, 6 (T and F), 3, 1, 2: |Σ gold − Σ p| = .1 + .2 + .7 + .1 + .2.
    assert raw["accept_ece"]["value"] == pytest.approx(1.3 / 6)
    same = x1.accept_calibration(records, temperature=1.0)
    assert same["accept_brier"] == x1.accept_calibration(records)["accept_brier"]
    sharper = x1.accept_calibration(records, temperature=0.5)["accept_brier"]
    assert sharper is not None and sharper.value != raw["accept_brier"]["value"]
    # Score 1 − q; wrong valid decisions score .5 and .4 against .1, .4, .2, .3.
    auroc = x1.error_detection_auroc(records)
    assert auroc is not None and (auroc.numerator, auroc.denominator) == (7.5, 8)
    # By q: .9 ok, .8 ok, .7 ok, .6 ok (x1-1), .6 wrong (x1-4), .5 wrong; planned 8.
    curve = x1.risk_coverage_summary(records)
    assert curve["aurc"].denominator == 8
    assert curve["aurc"].numerator == pytest.approx(0.2 + 2 / 6)
    assert curve["risk_at"] == {"0.5": 0.0, "0.8": None}  # 80% needs 7 valid outputs


def test_offline_cascade_uses_the_frozen_tau_on_the_jev_receipt_q() -> None:
    def pair(index: int, gold: bool, jev: Any, llm: Any) -> tuple[Any, Any]:
        return (
            x1.binary_record(f"x1-{index}", "c", gold, llm),
            x1.binary_record(f"x1-{index}", "c", gold, jev),
        )

    right, wrong = _receipt("supported", 0.9, 0.9), _receipt("contradicted", 0.1, 0.9)
    pairs = [
        pair(0, True, right, wrong),  # included, Jev right
        pair(1, True, wrong, right),  # included, Jev wrong: Astra is not consulted
        pair(2, True, _receipt("supported", 0.5, 0.5), right),  # q below τ: Astra right
        pair(3, True, None, None),  # invalid Jev, invalid Astra: wrong
    ]
    cascade = x1.offline_cascade(pairs, 0.9)
    assert cascade["coverage"] == {"value": 0.5, "numerator": 2, "denominator": 4}
    assert cascade["accuracy"] == {"value": 0.5, "numerator": 2, "denominator": 4}
    assert x1.offline_cascade(pairs, None)["accuracy"]["value"] == NOT_MEASURABLE


def _state_row(index: int, *, split: str, answer: str, filler: int) -> dict[str, Any]:
    state = {
        "task_contract": "Judge completion.",
        "original_request": "x" * filler,
        "candidate_output": answer,
        "tool_observations": [],
    }
    return {
        "state_id": f"x1-{index}",
        "cluster_id": f"c{index}",
        "source_split": split,
        "state": state,
    }


def test_strata_come_from_inputs_and_reference_agreement_skips_unjudged_rows() -> None:
    states = [
        _state_row(0, split="internal", answer="Done.", filler=10),
        _state_row(1, split="internal", answer="<no_answer>", filler=20),
        _state_row(2, split="om2w", answer="Done.", filler=30),
        _state_row(3, split="om2w", answer="Done.", filler=40),
    ]
    gold_rows = [
        {"state_id": f"x1-{i}", "annotators": count} for i, count in enumerate((1, 2, 3, 1))
    ]
    labels = x1.strata_labels(states, gold_rows)
    assert [labels[f"x1-{i}"]["reviewers"] for i in range(4)] == ["1", "2-3", "2-3", "1"]
    assert [labels[f"x1-{i}"]["no_answer"] for i in range(4)] == ["no", "yes", "no", "no"]
    assert [labels[f"x1-{i}"]["length_quartile"] for i in range(4)] == ["Q1", "Q2", "Q3", "Q4"]
    gold = {"x1-0": True, "x1-1": False, "x1-2": True, "x1-3": False}
    pairs = [
        (
            x1.binary_record(state, f"c{i}", gold[state], _receipt("supported", 0.9, 0.9)),
            x1.binary_record(state, f"c{i}", gold[state], _receipt("contradicted", 0.1, 0.9)),
        )
        for i, state in enumerate(gold)
    ]
    strata = x1.x1_strata(pairs, labels)
    assert strata["source_split"]["internal"]["items"] == 2
    assert strata["source_split"]["om2w"]["jev"] == {"value": 0.5, "numerator": 1, "denominator": 2}
    assert strata["no_answer"]["yes"]["delta"] == {"value": 1.0, "numerator": 1, "denominator": 1}
    with pytest.raises(ValueError, match="reviewer count"):
        x1.strata_labels(states, gold_rows[:3])
    reference = [
        {"state_id": "x1-0", "uv_outcome_success": 1, "gpt_eval_score": -1},
        {"state_id": "x1-1", "uv_outcome_success": 0, "gpt_eval_score": 1},
        {"state_id": "x1-2", "uv_outcome_success": None, "gpt_eval_score": 0},
        {"state_id": "x1-3", "uv_outcome_success": 1, "gpt_eval_score": 0},
        {"state_id": "x1-unplanned", "uv_outcome_success": 1, "gpt_eval_score": 1},
    ]
    agreement = x1.reference_agreement(reference, gold)
    assert agreement["uv_outcome_success"] == {"value": 2 / 3, "numerator": 2, "denominator": 3}
    assert agreement["gpt_eval_score"] == {"value": 1 / 3, "numerator": 1, "denominator": 3}
    assert agreement["mm_is_success_legacy"]["value"] == NOT_MEASURABLE


def test_frozen_temperatures_come_from_the_selection_freeze() -> None:
    freeze = {
        "schema_id": SELECTION_FREEZE_SCHEMA_ID,
        "temperatures": {"choice": {"llm": {"temperature": 1.4}, "jev": {"temperature": None}}},
    }
    assert x1.frozen_temperatures(freeze) == {"llm": 1.4, "jev": None}
    freeze["temperatures"]["choice"]["jev"] = {"temperature": 1.3}
    with pytest.raises(ValueError, match="off the preregistered grid"):
        x1.frozen_temperatures(freeze)


# ---------------------------------------------------------------------------
# Connection to retained Choice-only attempts, gold canary, CLI
# ---------------------------------------------------------------------------


def _gold_file(path: Path, ids: list[str], canary: str) -> dict[str, bool]:
    gold = {state: index % 2 == 0 for index, state in enumerate(ids)}
    path.write_text(
        "".join(
            json.dumps(
                {
                    "state_id": state,
                    "gold_accept": label,
                    "majority_outcome": "Correct" if label else "Incorrect",
                    "votes": {"Correct": int(label), "Incorrect": int(not label)},
                    "annotators": 1,
                    "canary": canary,
                }
            )
            + "\n"
            for state, label in gold.items()
        ),
        encoding="utf-8",
    )
    return gold


def _external_run(
    tmp_path: Path, count: int = 12, concurrency: int = 4, **drive: Any
) -> tuple[Any, list[dict[str, Any]], list[str], list[str]]:
    from evals.benchmarks import verdict_panel as panel
    from evals.benchmarks import verdict_panel_runner as runner

    from tests.evals.benchmarks import test_verdict_panel_runner as panel_tests

    rows = panel_tests._external_rows(count, clusters=count)
    order = panel.ordered_workload_ids([row["state_id"] for row in rows], MANIFEST)
    bodies: list[str] = []

    def transport(request: Any) -> Any:
        bodies.append(request.content.decode())
        return panel_tests._default_transport(request)

    unit = panel_tests._choice_unit(tmp_path, concurrency=concurrency)
    astra = drive.pop("astra", None) or panel_tests._Astra()
    panel_tests._drive(
        unit, runner.workloads_from_states(rows, order), astra=astra, transport=transport, **drive
    )
    sent = bodies + [
        json.dumps([request.system_prompt, *(m.content for m in request.messages)])
        for request in astra.requests
    ]
    return unit, rows, order, sent


def test_retained_choice_attempts_score_end_to_end_and_never_see_gold(tmp_path: Path) -> None:
    canary = "GOLD-CANARY-5f1c9e"
    gold_path = tmp_path / "gold.x1.jsonl"
    ids = [f"x1-{index:016x}" for index in range(12)]
    gold = _gold_file(gold_path, ids, canary)
    gold_path.chmod(0)  # any read on the dispatch path fails
    try:
        unit, rows, order, sent = _external_run(tmp_path)
    finally:
        gold_path.chmod(0o600)
    assert sorted(order) == sorted(ids) and len(sent) == 24
    for token in (canary, "gold_accept", "majority_outcome", '"votes"'):
        assert not any(token in text for text in sent)
    clusters = {row["state_id"]: row["cluster_id"] for row in rows}
    pairs, reasons = x1.x1_pairs(
        unit.outputs["choice"], order, x1.load_gold(gold_path, order), clusters
    )
    assert reasons == [] and [llm.item_id for llm, _ in pairs] == order
    # The fake Astra always says supported, the fake Jev contradicted.
    assert all(llm.accepted and not jev.accepted for llm, jev in pairs)
    assert all(llm.correct == gold[llm.item_id] for llm, _ in pairs)
    report = x1.x1_report(
        pairs,
        split_manifest_sha256=MANIFEST,
        tau=0.8,
        temperatures={"llm": 1.0, "jev": 1.0},
        strata=x1.strata_labels(
            rows, [json.loads(line) for line in gold_path.read_text().splitlines()]
        ),
    )
    assert report["primary"]["value"] == 0.0 and report["mcnemar"]["b"]["numerator"] == 6
    x1.record_x1_aggregate(unit.outputs["choice"], report)
    spec = _x1_spec(tmp_path / "run-spec.json", "geode-jev-external-cuavb-choice-test", order)
    _validate(unit.outputs["choice"], spec, x1.x1_metric_rows(report), report["decision"])


def test_a_stopped_x1_run_is_invalidated_with_its_reasons(tmp_path: Path) -> None:
    from core.llm.errors import BillingError

    from tests.evals.benchmarks import test_verdict_panel_runner as panel_tests

    astra = panel_tests._AstraFails(BillingError("weekly limit reached", provider="openai"))
    unit, rows, order, _ = _external_run(tmp_path, astra=astra, concurrency=1)
    gold = dict.fromkeys(order, True)
    clusters = {row["state_id"]: row["cluster_id"] for row in rows}
    pairs, reasons = x1.x1_pairs(unit.outputs["choice"], order, gold, clusters)
    assert reasons == ["missing_judgment", "selected_invalid_attempt"]
    report = x1.x1_report(pairs, split_manifest_sha256=MANIFEST, tau=None, reasons=reasons)
    assert report["primary"]["value"] == NOT_MEASURABLE and report["decision"] == "invalidated"
    x1.record_x1_aggregate(unit.outputs["choice"], report)
    spec = _x1_spec(tmp_path / "run-spec.json", "geode-jev-external-cuavb-choice-test", order)
    _validate(unit.outputs["choice"], spec, x1.x1_metric_rows(report), report["decision"])


def test_x1_cli_records_the_aggregate_without_a_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unit, rows, order, _ = _external_run(tmp_path)
    states = tmp_path / "states.x1.jsonl"
    states.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    gold = tmp_path / "gold.x1.jsonl"
    _gold_file(gold, order, "canary")
    manifest = tmp_path / "split-manifest.x1.json"
    manifest.write_text('{"unit": "X1"}', encoding="utf-8")
    freeze = tmp_path / "selection-freeze.json"
    freeze.write_text(
        json.dumps(
            {
                "schema_id": SELECTION_FREEZE_SCHEMA_ID,
                "cascade": {"tau": 0.8},
                "temperatures": {
                    "choice": {"llm": {"temperature": 1.0}, "jev": {"temperature": 1.4}}
                },
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference.x1.jsonl"
    reference.write_text(
        "".join(json.dumps({"state_id": s, "uv_outcome_success": 1}) + "\n" for s in order),
        encoding="utf-8",
    )
    spec = _x1_spec(tmp_path / "run-spec.json", "geode-jev-external-cuavb-choice-test", order)
    argv = [
        "--run-spec", str(spec), "--choice", str(unit.outputs["choice"]),
        "--manifest", str(manifest), "--states", str(states), "--gold", str(gold),
        "--selection-freeze", str(freeze), "--reference", str(reference), "--record",
    ]  # fmt: skip
    assert x1.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in printed["metrics"]] == ROW_NAMES
    results = json.loads((unit.outputs["choice"] / x1.RESULTS).read_text())
    assert results["descriptive"]["reference_agreement"]["uv_outcome_success"]["numerator"] == 6
    assert results["descriptive"]["engines"]["jev"]["frozen_t"]["temperature"] == 1.4
    assert set(results["descriptive"]["strata"]) == set(x1.STRATA)
    _validate(unit.outputs["choice"], spec, printed["metrics"], printed["decision"])
