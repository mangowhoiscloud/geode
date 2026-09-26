"""A measured primary must cover every frozen planned cell."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.eval import contract, denominator_coverage

from tests.scripts.handoff_phase_fixture import build_phase


def _paths(phase: Path) -> dict[str, Path]:
    return {
        "run_spec_path": phase / "run-spec.json",
        "attempts_path": phase / "attempts.jsonl",
    }


def test_not_measurable_primary_with_selected_invalid_cell_is_covered(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]
    report = denominator_coverage.check_denominator_coverage(
        phase / "analysis.json", cells_per_unit=2, forbid_retries=True, **_paths(phase)
    )
    assert report["primary_measured"] is False
    assert (report["planned_cells"], report["selected_valid_attempts"]) == (4, 3)
    assert report["selected_invalid_attempts"] == 1 and report["missing_cells"] == 0


def test_complete_measured_primary_is_covered(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run", mode="complete")["phase_dir"]
    report = denominator_coverage.check_denominator_coverage(
        phase / "analysis.json", cells_per_unit=2, **_paths(phase)
    )
    assert report["primary_measured"] is True and report["selected_valid_attempts"] == 4


def test_deselected_invalid_cell_cannot_keep_a_measured_primary(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run", mode="deselected")["phase_dir"]
    # The existing validator alone accepts this analysis; the denominator is the gap.
    contract.validate_analysis(phase / "analysis.json", **_paths(phase))
    with pytest.raises(ValueError, match="unselected without a recorded successor"):
        denominator_coverage.check_denominator_coverage(
            phase / "analysis.json", cells_per_unit=2, **_paths(phase)
        )


def test_wrong_cells_per_unit_is_rejected(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run", mode="complete")["phase_dir"]
    with pytest.raises(ValueError, match="frozen denominator requires 2"):
        denominator_coverage.check_denominator_coverage(
            phase / "analysis.json", cells_per_unit=1, **_paths(phase)
        )
    with pytest.raises(ValueError, match="positive integer"):
        denominator_coverage.check_denominator_coverage(
            phase / "analysis.json", cells_per_unit=0, **_paths(phase)
        )


def _rewrite_attempts(phase: Path, edit) -> None:
    path = phase / "attempts.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    edit(rows)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    analysis = json.loads((phase / "analysis.json").read_text())
    analysis["attempts_sha256"] = contract._sha256(path)
    analysis["selected_attempt_ids"] = [
        row["attempt_id"] for row in rows if row["selected_for_analysis"]
    ]
    analysis["evidence_refs"] = [
        ref for row in rows if row["selected_for_analysis"] for ref in row["evidence_refs"]
    ]
    (phase / "analysis.json").write_text(json.dumps(analysis))


def test_retry_lineage_is_explicit_and_can_be_forbidden(tmp_path: Path) -> None:
    phase = build_phase(tmp_path / "run")["phase_dir"]

    def supersede(rows: list[dict]) -> None:
        # The invalid cell (sequence 2) is superseded by the next execution row.
        rows[2]["selected_for_analysis"] = False
        rows[3]["parent_attempt_id"] = rows[2]["attempt_id"]

    _rewrite_attempts(phase, supersede)
    report = denominator_coverage.check_denominator_coverage(
        phase / "analysis.json", cells_per_unit=2, **_paths(phase)
    )
    assert report["superseded_attempts"] == 1
    with pytest.raises(ValueError, match="forbids retry lineage"):
        denominator_coverage.check_denominator_coverage(
            phase / "analysis.json", cells_per_unit=2, forbid_retries=True, **_paths(phase)
        )


def test_cli_reports_without_private_payloads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    phase = build_phase(tmp_path / "run", mode="deselected")["phase_dir"]
    code = denominator_coverage.main(
        [
            str(phase / "analysis.json"),
            "--run-spec",
            str(phase / "run-spec.json"),
            "--attempts",
            str(phase / "attempts.jsonl"),
            "--cells-per-unit",
            "2",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["covered"] is False
