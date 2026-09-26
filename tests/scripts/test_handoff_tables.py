"""Derived handoff tables keep unknowns, invalid cells and cost authorities separate."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
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


_OBSERVED = {
    "helper_admitted": True,
    "helper_fallback_used": False,
    "helper_feedback_consumed": True,
}
HELPERS_OK = {(case, arm): dict(_OBSERVED) for case in ("inbox-a", "inbox-b") for arm in "ab"}


def _trials(tmp_path: Path, name: str, **kwargs: Any) -> dict[str, dict[str, Any]]:
    phase = build_phase(tmp_path / name, mode="complete", **kwargs)["phase_dir"]
    out = tmp_path / f"{name}-tables"
    handoff_tables.export_tables(phase, out, primitive="choice")
    return {row["case_id"] + "/" + row["schedule_arm"]: row for row in _rows(out, "e2e_trials")}


def test_strict_success_follows_the_preregistered_unit_rule(tmp_path: Path) -> None:
    violation = frozenset({("inbox-a", "a")})
    # Verdict unit (matched final verdict): §3.1 strict success has no lookup condition.
    verdict = _trials(tmp_path, "verdict", extra_lookups=violation)
    row, clean = verdict["inbox-a/a"], verdict["inbox-b/a"]
    assert row["strict_rule"] == "verdict" and row["extra_lookup_count"] == 1
    assert row["strict_success"] is True and row["strict_success_with_lookup"] is False
    assert row["judgments_admitted"] is True and row["feedback_consumption_complete"] is True
    assert row["false_completion"] is False
    assert clean["strict_success"] is True and clean["strict_success_with_lookup"] is True
    # Intent unit (helper arms): the same extra lookup fails strict success.
    intent = _trials(
        tmp_path, "intent", intent=True, extra_lookups=violation, helper_fields=HELPERS_OK
    )
    row, clean = intent["inbox-a/a"], intent["inbox-b/a"]
    assert row["strict_rule"] == "intent" and row["runtime_arm"] == "a"
    assert row["strict_success"] is False and row["strict_success_with_lookup"] is False
    assert row["judgments_admitted"] is None  # no matched judgments on helper arms
    assert clean["strict_success"] is True and clean["strict_success_with_lookup"] is True
    # A failed task oracle fails both rules.
    failed = _trials(
        tmp_path,
        "failed",
        intent=True,
        failing=frozenset({("inbox-b", "b")}),
        helper_fields=HELPERS_OK,
    )
    assert failed["inbox-b/b"]["strict_success"] is False


def _rewrite_verification(phase: Path, trial: str, edit: Callable[[dict], None]) -> None:
    path = phase / "trials" / trial / "agent/verification.json"
    value = json.loads(path.read_text())
    edit(value)
    path.write_text(json.dumps(value))


def test_verdict_strict_success_needs_admitted_judgments_and_consumed_feedback(
    tmp_path: Path,
) -> None:
    phase = build_phase(tmp_path / "run", mode="complete")["phase_dir"]
    trial = "fixture-natural-r0-inbox-a-a"
    negative = {
        "llm_call_id": "judge-0",
        "accepted": True,
        "projected_payload": {"passed": False},
    }

    def unconsumed(value: dict) -> None:
        value["judgments"].insert(0, dict(negative))

    _rewrite_verification(phase, trial, unconsumed)
    out = tmp_path / "unconsumed"
    handoff_tables.export_tables(phase, out, primitive="noul")
    row = next(r for r in _rows(out, "e2e_trials") if r["trial_name"] == trial)
    assert row["feedback_consumption_complete"] is False and row["strict_success"] is False

    def consumed(value: dict) -> None:
        value["root_requests"] = [{"consumed_feedback": [{"judge_call_id": "judge-0"}]}]

    _rewrite_verification(phase, trial, consumed)
    out = tmp_path / "consumed"
    handoff_tables.export_tables(phase, out, primitive="noul")
    row = next(r for r in _rows(out, "e2e_trials") if r["trial_name"] == trial)
    assert row["feedback_consumption_complete"] is True and row["strict_success"] is True

    def rejected(value: dict) -> None:
        value["judgments"][-1]["accepted"] = False

    _rewrite_verification(phase, trial, rejected)
    out = tmp_path / "rejected"
    handoff_tables.export_tables(phase, out, primitive="noul")
    row = next(r for r in _rows(out, "e2e_trials") if r["trial_name"] == trial)
    assert row["judgments_admitted"] is False and row["strict_success"] is False


def test_escalated_cascade_primary_is_not_a_decisive_judgment() -> None:
    primary = {
        "llm_call_id": "jev-1",
        "accepted": True,
        "projected_payload": {"passed": False},
        "cascade": {"stage": "primary", "tau": "0.85", "q": 0.6, "admitted": False},
    }
    fallback = {
        "llm_call_id": "llm-1",
        "accepted": True,
        "projected_payload": {"passed": True},
        "cascade": {"stage": "fallback", "tau": "0.85", "primary_call_id": "jev-1"},
    }
    components = handoff_tables._strict_components(
        {"judgments": [primary, fallback], "root_requests": []},
        {"oracle": {"passed": True}},
        {},
        "turn.verify.passed",
    )
    assert components == {
        "judgments_admitted": True,
        "feedback_consumption_complete": True,
        "false_completion": False,
    }
    false_pass = handoff_tables._strict_components(
        {"judgments": [fallback]}, {"oracle": {"passed": False}}, {}, "turn.verify.passed"
    )
    assert false_pass["false_completion"] is True


def test_runner_strict_success_is_checked_never_overwritten(tmp_path: Path) -> None:
    violation = frozenset({("inbox-a", "a")})
    agreeing = _trials(
        tmp_path, "agree", extra_lookups=violation, runner_strict={("inbox-a", "a"): True}
    )
    assert agreeing["inbox-a/a"]["runner_strict_success"] is True
    # A runner that folded the lookup condition into a verdict unit disagrees with §3.1.
    phase = build_phase(
        tmp_path / "disagree",
        mode="complete",
        extra_lookups=violation,
        runner_strict={("inbox-a", "a"): False},
    )["phase_dir"]
    with pytest.raises(ValueError, match=r"disagrees with the §3\.1 verdict recomputation"):
        handoff_tables.export_tables(phase, tmp_path / "disagree-tables", primitive="choice")
    intent = build_phase(
        tmp_path / "intent",
        mode="complete",
        intent=True,
        extra_lookups=violation,
        runner_strict={("inbox-a", "a"): True},
        helper_fields=HELPERS_OK,
    )["phase_dir"]
    with pytest.raises(ValueError, match="intent recomputation False"):
        handoff_tables.export_tables(intent, tmp_path / "intent-tables", primitive="choice")


def test_intent_strict_success_needs_observed_helper_admission_and_consumption(
    tmp_path: Path,
) -> None:
    rejected = {**HELPERS_OK, ("inbox-a", "b"): {**_OBSERVED, "helper_admitted": False}}
    fallback = {**rejected, ("inbox-b", "b"): {**_OBSERVED, "helper_fallback_used": True}}
    rows = _trials(tmp_path, "helper", intent=True, helper_fields=fallback)
    # The Jev helper was rejected (or an LLM decided after a Jev failure), yet the root
    # answered correctly: reward 1 is not strict success (05 §3.1, fallback rule).
    assert rows["inbox-a/b"]["native_reward"] == 1.0
    assert rows["inbox-a/b"]["strict_success"] is False
    assert rows["inbox-b/b"]["helper_fallback_used"] is True
    assert rows["inbox-b/b"]["strict_success"] is False
    assert rows["inbox-a/a"]["strict_success"] is True
    # Unobserved helper facts leave strict success null with a reason, never assumed.
    missing = {**HELPERS_OK, ("inbox-a", "a"): {"helper_admitted": True}}
    rows = _trials(tmp_path, "missing", intent=True, helper_fields=missing)
    row = rows["inbox-a/a"]
    assert row["strict_success"] is None and row["strict_success_with_lookup"] is None
    assert row["strict_unobserved"] == [
        "helper_fallback_used unobserved",
        "helper_feedback_consumed unobserved",
    ]
    rows = _trials(tmp_path, "none", intent=True)
    assert all(row["strict_success"] is None for row in rows.values())
    assert rows["inbox-b/a"]["strict_unobserved"][0] == "helper_admitted unobserved"


def test_helper_observations_come_from_the_call_ledger_and_must_agree() -> None:
    oracle = {"checks": {"results_consumed_by_root": True}}
    jev_ok = {"role": "helper", "provider": "typesafe", "accepted": True, "error_type": None}
    jev_rejected = {**jev_ok, "accepted": False}
    llm_after_jev = {**jev_ok, "provider": "openai"}
    observed = handoff_tables._helper_observations([], [jev_ok], oracle, "jev")
    assert observed == {
        "helper_admitted": True,
        "helper_fallback_used": False,
        "helper_feedback_consumed": True,
    }
    assert (
        handoff_tables._helper_observations([], [jev_rejected], oracle, "jev")["helper_admitted"]
        is False
    )
    fallback = handoff_tables._helper_observations([], [jev_rejected, llm_after_jev], {}, "jev")
    assert fallback["helper_fallback_used"] is True
    assert fallback["helper_feedback_consumed"] is None  # no receipt or oracle observation
    unknown = handoff_tables._helper_observations([], [{**jev_ok, "accepted": None}], {}, "jev")
    assert unknown["helper_admitted"] is None
    assert handoff_tables._helper_observations([], [], {}, "jev")["helper_admitted"] is None
    with pytest.raises(ValueError, match="helper_admitted"):
        handoff_tables._helper_observations(
            [{"helper_admitted": True}], [jev_rejected], oracle, "jev"
        )
