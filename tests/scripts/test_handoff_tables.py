"""Derived handoff tables keep unknowns, invalid cells and cost authorities separate."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.eval import handoff_tables

from tests.scripts.handoff_phase_fixture import INVALID_TRIAL, build_phase


def _rows(out: Path, table: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (out / f"{table}.jsonl").read_text().splitlines()]


def _export(tmp_path: Path, **kwargs: Any) -> Path:
    out = tmp_path / "tables"
    handoff_tables.export_tables(
        kwargs.pop("phase_dir"),
        out,
        primitive="noul",
        replay_preselected=["fixture-natural-r0-inbox-a-a"],
        independent_units=2,
        **kwargs,
    )
    return out


def test_call_ledger_keeps_unknown_usage_and_latency(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    calls = _rows(out, "call_ledger")
    assert len(calls) == 9  # three valid trials x root/reflection/final judge
    jev = [row for row in calls if row["provider"] == "typesafe"]
    assert {row["trial_name"] for row in jev} == {"fixture-natural-r0-inbox-a-b"}
    (judge,) = jev
    assert judge["cached_input_tokens"] is None and judge["reasoning_tokens"] is None
    assert judge["latency_field"] == "duration_ms" and judge["latency_s"] is None
    assert judge["typesafe_price_estimate_usd"] == pytest.approx(2589 * 0.042 / 1_000_000)
    assert judge["subscription_api_equivalent_estimate_usd"] is None
    assert judge["actual_billed_usd"] is None and judge["billing_status"] == "unknown"
    assert judge["noul_p_missing"] == pytest.approx(0.8) and judge["accepted"] is True
    astra = [row for row in calls if row["provider"] == "openai"]
    assert all(row["latency_s"] and row["latency_s"] > 0 for row in astra)
    assert all(row["subscription_api_equivalent_estimate_usd"] > 0 for row in astra)
    assert all(row["typesafe_price_estimate_usd"] is None for row in astra)
    assert all(row["join_complete"] and row["source_sha256"] for row in calls)
    assert not any("total_cost" in name for row in calls for name in row)


def test_trials_preserve_invalid_cells_and_never_credit_missing_jev(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    trials = {row["trial_name"]: row for row in _rows(out, "e2e_trials")}
    assert len(trials) == 4
    invalid = trials[INVALID_TRIAL]
    assert invalid["validity"] == "invalid" and invalid["outcome"] == "unknown"
    assert invalid["jev_decision_status"] == "unobserved"
    assert invalid["jev_success_credited"] is False
    assert invalid["astra_input_tokens_total"] is None
    assert invalid["subscription_api_equivalent_estimate_usd_total"] is None
    jev = trials["fixture-natural-r0-inbox-a-b"]
    assert jev["jev_decision_status"] == "admitted" and jev["jev_success_credited"] is True
    assert jev["jev_cached_input_tokens_total"] is None  # unreported, not zero
    assert jev["jev_cached_input_tokens_missing_calls"] == 1
    assert jev["judge_latency_sum_s"] is None and jev["judge_latency_missing_calls"] == 1
    assert jev["noul_pred_missing"] is True and jev["noul_true_missing"] is True
    llm = trials["fixture-natural-r0-inbox-a-a"]
    assert llm["jev_decision_status"] == "n/a" and llm["jev_success_credited"] is None
    assert llm["strict_success"] is True and llm["replay_preselected"] is True
    assert llm["actual_billed_usd_total"] is None


def test_llm_route_on_the_jev_arm_is_not_a_jev_success(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run", jev_judge_provider="openai")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    trials = {row["trial_name"]: row for row in _rows(out, "e2e_trials")}
    jev = trials["fixture-natural-r0-inbox-a-b"]
    assert jev["outcome"] == "passed"
    assert jev["jev_decision_status"] == "missing"
    assert jev["jev_success_credited"] is False
    summary = {row["arm_label"]: row for row in _rows(out, "primitive_summary")}
    assert summary["jev"]["jev_missing_or_fallback"] == 1


def test_pairs_and_summary_keep_denominators_explicit(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    pairs = {row["case_id"]: row for row in _rows(out, "e2e_pairs")}
    assert pairs["inbox-a"]["pair_complete"] is True and pairs["inbox-a"]["success_delta"] == 0
    assert pairs["inbox-a"]["runtime_s_delta"] == pytest.approx(1.0)
    assert pairs["inbox-a"]["replay_selected"] is True
    assert pairs["inbox-b"]["pair_complete"] is False
    assert pairs["inbox-b"]["success_delta"] is None and pairs["inbox-b"]["jev_passed"] is None
    summary = {row["arm_label"]: row for row in _rows(out, "primitive_summary")}
    everything = summary["all"]
    assert everything["primary_value"] == "not-measurable"
    assert everything["primary_numerator"] is None and everything["primary_denominator"] is None
    assert (everything["planned_cells"], everything["valid"], everything["invalid"]) == (4, 3, 1)
    assert everything["success_rate_valid"] == 1.0 and everything["success_rate_denominator"] == 3
    assert everything["subscription_api_equivalent_estimate_usd_total"] is None
    assert everything["subscription_api_equivalent_estimate_usd_observed_sum"] > 0
    assert summary["jev"]["median_judge_latency_s"] is None
    assert summary["llm"]["median_judge_latency_s"] == pytest.approx(0.4324)
    assert everything["is_admission_phase"] is False


def test_csv_leaves_unknown_empty_and_outputs_are_append_only(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    with (out / "call_ledger.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    jev = next(row for row in rows if row["provider"] == "typesafe")
    assert jev["cached_input_tokens"] == "" and jev["actual_billed_usd"] == ""
    manifest = json.loads((out / "tables-manifest.json").read_text())
    assert {row["table"] for row in manifest["outputs"]} == set(handoff_tables.TABLES)
    assert any(row["path"] == "run-spec.json" for row in manifest["inputs"])
    with pytest.raises(FileExistsError):
        handoff_tables.export_tables(phase, out, primitive="noul")


def test_billing_reconciliation_needs_request_identity(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    export = tmp_path / "billing.jsonl"
    export.write_text(
        json.dumps(
            {
                "request_id": "req_s-1_2",
                "amount_usd": "0.0001",
                "currency": "USD",
                "provider": "typesafe",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = _export(tmp_path, phase_dir=phase, billing_export=export, billing_source="fixture export")
    calls = _rows(out, "call_ledger")
    reconciled = [row for row in calls if row["billing_status"] == "reconciled"]
    assert len(reconciled) == 1 and reconciled[0]["actual_billed_usd"] == pytest.approx(0.0001)
    trials = {row["trial_name"]: row for row in _rows(out, "e2e_trials")}
    jev = trials["fixture-natural-r0-inbox-a-b"]
    assert jev["actual_billed_usd_total"] is None  # other calls remain unreconciled
    assert jev["actual_billed_usd_observed_sum"] == pytest.approx(0.0001)
    receipt = json.loads((out / "billing-reconciliation.json").read_text())
    assert receipt["complete"] is False and receipt["total_actual_billed_usd"] is None
    assert receipt["matched_calls"] == 1 and receipt["unmatched_export_rows"] == 0


@pytest.mark.parametrize(
    "row",
    [
        {"amount_usd": "0.1"},
        {"request_id": "req_x", "amount_usd": "0.1", "currency": "KRW"},
        {"request_id": "req_x", "amount_usd": "-0.1"},
        {"request_id": "req_x", "amount_usd": "NaN"},
    ],
)
def test_billing_reconciliation_rejects_unverifiable_rows(row: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        handoff_tables.reconcile_billing([], [row], export_sha256="0" * 64, source="fixture")


def test_billing_reconciliation_rejects_duplicate_or_mismatched_identity() -> None:
    call = {"response_id_sha256": None, "provider": "openai"}
    rows = [
        {"request_id": "req_x", "amount_usd": "0.1"},
        {"request_id": "req_x", "amount_usd": "0.1"},
    ]
    with pytest.raises(ValueError, match="repeats"):
        handoff_tables.reconcile_billing([call], rows, export_sha256="0" * 64, source="fixture")
    import hashlib

    keyed = {"response_id_sha256": hashlib.sha256(b"req_y").hexdigest(), "provider": "openai"}
    with pytest.raises(ValueError, match="provider"):
        handoff_tables.reconcile_billing(
            [keyed],
            [{"request_id": "req_y", "amount_usd": "0.1", "provider": "typesafe"}],
            export_sha256="0" * 64,
            source="fixture",
        )


def test_paired_slot_columns_come_from_private_receipts(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run", mode="complete", slots=True, observed_judge_latency=True)[
        "phase_dir"
    ]
    out = _export(tmp_path, phase_dir=phase)
    trials = {row["trial_name"]: row for row in _rows(out, "e2e_trials")}
    llm, jev = trials["fixture-natural-r0-inbox-a-a"], trials["fixture-natural-r0-inbox-a-b"]
    assert llm["slot_id"] == jev["slot_id"] == "r0-inbox-a"
    assert (llm["dispatch_skew_s"], llm["agent_start_skew_s"], llm["pair_sync"]) == (0.2, 3.5, True)
    # Arm b's receipt uses the Run draft names (pair_launch_skew_s, ...): same columns.
    assert (jev["dispatch_skew_s"], jev["agent_start_skew_s"], jev["concurrent_trials"]) == (
        0.2,
        3.5,
        1,
    )
    assert all(row["external_account_usage"] == "unknown" for row in trials.values())
    # Both arms of a slot start together: every call overlaps the sibling's three calls;
    # slots run sequentially, so no call of the other slot overlaps.
    assert all(row["overlapping_calls"] == 3 for row in trials.values())
    assert all(row["overlapping_calls_missing_intervals"] == 0 for row in trials.values())
    pairs = {row["case_id"]: row for row in _rows(out, "e2e_pairs")}
    synced, late = pairs["inbox-a"], pairs["inbox-b"]
    assert (synced["same_slot"], synced["pair_sync"]) == (True, True)
    assert synced["intra_pair_latency_comparable"] is True
    assert synced["judge_latency_s_delta"] is not None
    assert (late["pair_sync"], late["agent_start_skew_s"]) == (False, 42.0)
    assert late["intra_pair_latency_comparable"] is False  # success analysis keeps it
    assert late["success_delta"] == 0
    for table in handoff_tables.TABLES:
        text = (out / f"{table}.jsonl").read_text()
        assert "codex_account_fp12" not in text and "0123456789ab" not in text


def test_slot_columns_stay_unknown_without_receipts_and_reject_contradictions(
    tmp_path: Path,
) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    out = _export(tmp_path, phase_dir=phase)
    for row in _rows(out, "e2e_trials"):
        assert row["slot_id"] is None and row["pair_sync"] is None
        assert row["external_account_usage"] == "unknown"
        # A 0.0 latency placeholder and an invalid cell leave the overlap count unknown.
        assert row["overlapping_calls"] is None and row["overlapping_calls_observed"] == 0
    for row in _rows(out, "e2e_pairs"):
        assert row["pair_sync"] is None and row["intra_pair_latency_comparable"] is False
    slotted = build_phase(tmp_path / "slots", mode="complete", slots=True)["phase_dir"]
    receipt = next((slotted / "private-receipts").glob("*a0000.json"))
    original = json.loads(receipt.read_text())
    for edit, message in (
        ({"pair_launch_skew_s": 0.9}, "disagrees on dispatch_skew_s"),
        ({"pair_sync": False}, "contradicts the recorded agent start skew"),
        ({"agent_start_skew_s": -1}, "non-negative"),
    ):
        receipt.write_text(json.dumps({**original, **edit}))
        with pytest.raises(ValueError, match=message):
            handoff_tables.export_tables(slotted, tmp_path / message[:8], primitive="noul")
