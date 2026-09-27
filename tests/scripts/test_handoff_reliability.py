"""Repetition reliability from e2e_trials: pass@n / pass^n over one frozen set (06 §6)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.eval import contract, denominator_coverage, handoff_tables

from tests.scripts.handoff_phase_fixture import build_phase

RUN = "geode-jev-verdict-e2e-natural-r{rep}-20260926-fixture"


def _phase(tmp_path: Path, rep: int, **kwargs: Any) -> Path:
    kwargs.setdefault("mode", "complete")
    run_id = kwargs.pop("run_id", RUN.format(rep=rep))
    root = tmp_path / f"r{rep}-{kwargs.pop('tag', 'x')}"
    return build_phase(root, repetition=rep, run_id=run_id, **kwargs)["phase_dir"]


def _pair(tmp_path: Path, **kwargs: Any) -> tuple[Path, Path]:
    # llm (arm a): inbox-b fails in r0. jev (arm b): inbox-a fails in r1.
    r0 = _phase(tmp_path, 0, failing=frozenset({("inbox-b", "a")}), **kwargs)
    r1 = _phase(tmp_path, 1, failing=frozenset({("inbox-a", "b")}), **kwargs)
    return r0, r1


def _export(phases: list[Path], out: Path, ns: tuple[int, ...] = (1, 2)) -> dict[str, Any]:
    return handoff_tables.export_reliability(phases, out, primitive="noul", unit="u7", ns=ns)


def test_repetitions_combine_by_arm_and_task_with_task_level_estimators(tmp_path: Path) -> None:
    r0, r1 = _pair(tmp_path)
    out = r1 / "tables"
    summary = _export([r0, r1], out)
    assert summary["run_spec_sha256s"] == sorted(
        hashlib.sha256((phase / "run-spec.json").read_bytes()).hexdigest() for phase in (r0, r1)
    )
    for arm in ("llm", "jev"):
        entry = summary["arms"][arm]["n"]
        assert entry["1"]["pass_at_n"]["value"] == pytest.approx(0.75)
        assert entry["1"]["pass_hat_n"]["value"] == pytest.approx(0.75)
        assert entry["2"]["pass_at_n"] == {"value": 1.0, "numerator": 2.0, "denominator": 2}
        # Task-level pass^2 is 1/2; a pooled 0.75**2 plug-in would claim 0.5625.
        assert entry["2"]["pass_hat_n"]["value"] == pytest.approx(0.5)
        assert entry["2"]["status"] == "measured"
        assert (entry["2"]["planned_tasks"], entry["2"]["complete_tasks"]) == (2, 2)
        assert entry["2"]["incomplete_tasks"] == 0
        assert (
            entry["2"]["expected_repetitions"],
            entry["2"]["observed_repetitions"],
            entry["2"]["valid_repetitions"],
        ) == (4, 4, 4)
    rows = [json.loads(line) for line in (out / "reliability.jsonl").read_text().splitlines()]
    assert [(row["arm_label"], row["case_id"]) for row in rows] == [
        ("jev", "inbox-a"),
        ("jev", "inbox-b"),
        ("llm", "inbox-a"),
        ("llm", "inbox-b"),
    ]
    llm_b = rows[3]
    assert (llm_b["trials"], llm_b["successes"], llm_b["complete"]) == (2, 1, True)
    assert [pointer["repetition"] for pointer in llm_b["repetitions"]] == [0, 1]
    assert {pointer["trial_name"] for pointer in llm_b["repetitions"]} == {
        "fixture-natural-r0-inbox-b-a",
        "fixture-natural-r1-inbox-b-a",
    }
    for pointer in llm_b["repetitions"]:
        assert pointer["attempt_id"].startswith(pointer["run_id"])
        assert pointer["run_spec_sha256"] in summary["run_spec_sha256s"]
        assert pointer["source_ref"].startswith("trials/") and pointer["source_sha256"]
    assert all(len(values) == 1 for values in llm_b["contract"].values())
    assert (
        summary["rows"]["sha256"]
        == hashlib.sha256((out / "reliability.jsonl").read_bytes()).hexdigest()
    )
    text = (out / "reliability_summary.json").read_text()
    assert str(tmp_path) not in text and str(tmp_path) not in json.dumps(rows)
    with pytest.raises(FileExistsError):
        _export([r0, r1], out)


def _status(summary: dict[str, Any], arm: str, n: int) -> tuple[str, list[str]]:
    entry = summary["arms"][arm]["n"][str(n)]
    return entry["status"], entry["reasons"]


def test_unknown_duplicate_mismatched_and_short_sets_are_not_measurable(tmp_path: Path) -> None:
    # An infrastructure-invalid cell is unknown, never a failure: that arm stops.
    r0 = _phase(tmp_path, 0, mode="incomplete", tag="inv")
    r1 = _phase(tmp_path, 1, tag="inv")
    summary = _export([r0, r1], tmp_path / "unknown")
    assert _status(summary, "jev", 2) == ("not-measurable", ["unknown_outcome"])
    assert summary["arms"]["jev"]["n"]["2"]["pass_hat_n"] == {
        "value": "not-measurable",
        "numerator": None,
        "denominator": None,
    }
    assert summary["arms"]["jev"]["n"]["2"]["incomplete_tasks"] == 1
    assert _status(summary, "llm", 2) == ("measured", [])
    # Two run specs that both claim repetition 0 duplicate every slot.
    dup = _phase(tmp_path, 0, tag="dup", run_id=RUN.format(rep="0b"))
    duplicated = _export([r1, _phase(tmp_path, 0, tag="d0"), dup], tmp_path / "dup")
    assert "duplicate_repetition" in _status(duplicated, "llm", 2)[1]
    # A verifier, policy, reset, payload or task digest that changes between repetitions.
    other = "e" * 64
    for field in (
        "verifier_sha256",
        "policy_digest",
        "reset_digest",
        "case_sha256",
        "task_checksum",
    ):
        changed = _phase(
            tmp_path, 1, tag=f"m-{field}", cell_overrides={("inbox-a", "a"): {field: other}}
        )
        result = _export([_phase(tmp_path, 0, tag=f"b-{field}"), changed], tmp_path / field)
        assert _status(result, "llm", 2) == ("not-measurable", ["contract_mismatch"]), field
        assert _status(result, "jev", 2) == ("measured", [])
    unbound = _phase(
        tmp_path, 1, tag="unbound", cell_overrides={("inbox-a", "b"): {"reset_digest": None}}
    )
    result = _export([_phase(tmp_path, 0, tag="u0"), unbound], tmp_path / "unbound")
    assert _status(result, "jev", 1) == ("not-measurable", ["contract_mismatch"])
    # One repetition (U6b-like): pass@1 exists, pass^2 is not measurable (반복 부족).
    single = _export([_phase(tmp_path, 0, tag="single")], tmp_path / "single")
    assert _status(single, "llm", 1) == ("measured", [])
    assert _status(single, "llm", 2) == ("not-measurable", ["insufficient_repetitions"])
    rows = handoff_tables.reliability_metric_rows(
        {**single, "unit": "u6b"}, metrics=(("pass_at", 1), ("pass_hat", 2))
    )
    hat = next(row for row in rows if row["name"] == "u6b_pass_hat_2_arm_a")
    assert hat["value"] == "not-measurable" and hat["source_locator"] is None


def test_plan_errors_fail_closed_before_any_estimate(tmp_path: Path) -> None:
    mislabeled = _phase(
        tmp_path, 0, tag="seed", cell_overrides={("inbox-a", "a"): {"repetition": 1}}
    )
    with pytest.raises(ValueError, match="seed schedule"):
        _export([mislabeled], tmp_path / "seed")
    with pytest.raises(ValueError, match="own run spec"):
        r0 = _phase(tmp_path, 0, tag="same")
        _export([r0, r0], tmp_path / "same")
    with pytest.raises(ValueError, match="short lower-case"):
        handoff_tables.export_reliability(
            [r0], tmp_path / "unit", primitive="noul", unit="U7 all", ns=(1,)
        )


def test_auxiliary_rows_bind_to_the_summary_under_the_unchanged_analysis_schema(
    tmp_path: Path,
) -> None:
    r0, r1 = _pair(tmp_path)
    summary = _export([r0, r1], r1 / "tables")
    analysis_path = r1 / "analysis.json"
    analysis = json.loads(analysis_path.read_text())
    primary = json.loads(json.dumps(analysis["metrics"][0]))
    rows = handoff_tables.reliability_metric_rows(summary)
    assert [row["name"] for row in rows] == [
        "u7_pass_at_1_arm_b",
        "u7_pass_at_2_arm_b",
        "u7_pass_hat_2_arm_b",
        "u7_pass_at_1_arm_a",
        "u7_pass_at_2_arm_a",
        "u7_pass_hat_2_arm_a",
    ]
    hat = rows[-1]
    assert (hat["value"], hat["numerator"], hat["denominator"]) == (0.5, 1.0, 2)
    assert hat["source_ref"] == "tables/reliability_summary.json"
    assert hat["source_locator"]["value"] == "/arms/llm/n/2/pass_hat_n/value"
    summary_file = r1 / "tables/reliability_summary.json"
    analysis["metrics"].extend(rows)
    analysis["evidence_refs"].append(
        {
            "kind": "other",
            "path": "tables/reliability_summary.json",
            "sha256": hashlib.sha256(summary_file.read_bytes()).hexdigest(),
        }
    )
    analysis_path.write_text(json.dumps(analysis))
    paths = {"run_spec_path": r1 / "run-spec.json", "attempts_path": r1 / "attempts.jsonl"}
    contract.validate_analysis(analysis_path, **paths)
    assert analysis["metrics"][0] == primary  # the primary metric and decision are untouched
    # A tampered auxiliary value no longer matches its bound source.
    analysis["metrics"][-1]["value"] = 0.75
    analysis_path.write_text(json.dumps(analysis))
    with pytest.raises(ValueError, match="does not match metric source"):
        contract.validate_analysis(analysis_path, **paths)


def test_primitive_summary_carries_auxiliary_reliability_columns(tmp_path: Path) -> None:
    r0, r1 = _pair(tmp_path)
    tables = r1 / "tables"
    _export([r0, r1], tables)
    summary_path = tables / "reliability_summary.json"
    manifest = handoff_tables.export_tables(r1, tables, primitive="noul", reliability=summary_path)
    rows = {
        row["arm_label"]: row
        for row in map(json.loads, (tables / "primitive_summary.jsonl").read_text().splitlines())
    }
    assert rows["llm"]["reliability_pass_hat_2"] == pytest.approx(0.5)
    assert rows["jev"]["reliability_pass_at_2"] == 1.0
    assert rows["llm"]["reliability_complete_tasks_n2"] == 2
    assert rows["all"]["reliability_pass_at_1"] is None
    assert manifest["reliability_summary"]["sha256"] == rows["llm"]["reliability_summary_sha256"]
    trials = [json.loads(line) for line in (tables / "e2e_trials.jsonl").read_text().splitlines()]
    assert all(
        row["policy_digest"] and row["reset_digest"] and row["verifier_sha256"] for row in trials
    )
    # A phase outside the summary's frozen set cannot borrow its values.
    stranger = _phase(tmp_path, 1, tag="stranger", run_id="geode-jev-other-r1-20260926-fixture")
    with pytest.raises(ValueError, match="not part of the reliability summary"):
        handoff_tables.export_tables(
            stranger, tmp_path / "stranger-tables", primitive="noul", reliability=summary_path
        )


def test_reliability_cli_and_repetition_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    r0, r1 = _pair(tmp_path)
    assert (
        denominator_coverage.main(
            ["repetitions", str(r0), str(r1), "--primitive", "noul", "--n", "2"]
        )
        == 0
    )
    gate = json.loads(capsys.readouterr().out)
    assert gate["covered"] is True and gate["arms"]["llm"]["complete_tasks"] == 2
    assert (
        denominator_coverage.main(["repetitions", str(r0), "--primitive", "noul", "--n", "2"]) == 1
    )
    short = json.loads(capsys.readouterr().out)
    assert short["arms"]["llm"]["reasons"] == ["insufficient_repetitions"]
    out = tmp_path / "cli"
    code = handoff_tables.main(
        [
            "reliability",
            str(r0),
            str(r1),
            "--out",
            str(out),
            "--unit",
            "u7",
            "--primitive",
            "noul",
            "--n",
            "1",
            "--n",
            "2",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"]["llm"] == {"1": "measured", "2": "measured"}
    assert (out / "reliability.jsonl").is_file()
