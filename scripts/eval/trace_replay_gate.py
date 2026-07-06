#!/usr/bin/env python3
"""Crucible G1 trace replay gate for R1/T1.

This is a zero-live-call reject gate. It consumes the failure manifest produced
by ``build_failure_manifest.py`` and checks whether each candidate guard has a
trace-local intervention point on failures while staying inert on passing
controls. It cannot promote a candidate; it only decides whether the candidate
is coherent enough to spend subscription quota on G2 micro-sim.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "tmp/crucible_failure_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "tmp/crucible_g1_trace_replay.json"


@dataclass(frozen=True)
class GuardVerdict:
    guard: str
    verdict: str
    failures_total: int
    failures_supported: int
    controls_total: int
    controls_blocked: int
    notes: list[str]

    @property
    def support_rate(self) -> float:
        return self.failures_supported / self.failures_total if self.failures_total else 0.0

    @property
    def control_block_rate(self) -> float:
        return self.controls_blocked / self.controls_total if self.controls_total else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "guard": self.guard,
            "verdict": self.verdict,
            "failures_total": self.failures_total,
            "failures_supported": self.failures_supported,
            "support_rate": round(self.support_rate, 4),
            "controls_total": self.controls_total,
            "controls_blocked": self.controls_blocked,
            "control_block_rate": round(self.control_block_rate, 4),
            "notes": self.notes,
        }


def _has_argument_or_missing_write(row: dict[str, Any]) -> bool:
    return bool(row.get("argument_diffs") or row.get("failed_expected_writes"))


def _has_unmet_terminal_assertion(row: dict[str, Any]) -> bool:
    return bool(row.get("unmet_env_assertions") or row.get("failed_expected_writes"))


def _r1_failure_supported(row: dict[str, Any]) -> bool:
    return (
        row.get("domain") == "retail"
        and row.get("candidate_guard") == "R1"
        and _has_argument_or_missing_write(row)
    )


def _t1_failure_supported(row: dict[str, Any]) -> bool:
    return (
        row.get("domain") == "telecom"
        and row.get("candidate_guard") == "T1"
        and _has_unmet_terminal_assertion(row)
    )


def _r1_control_blocked(row: dict[str, Any]) -> bool:
    return row.get("domain") == "retail" and bool(row.get("failed_expected_writes"))


def _t1_control_blocked(row: dict[str, Any]) -> bool:
    return row.get("domain") == "telecom" and bool(row.get("unmet_env_assertions"))


def _guard_rows(manifest: dict[str, Any], guard: str, *, failures: bool) -> list[dict[str, Any]]:
    key = "failures" if failures else "controls"
    return [row for row in manifest.get(key, []) if row.get("candidate_guard") == guard]


def _evaluate_guard(manifest: dict[str, Any], guard: str) -> GuardVerdict:
    failure_rows = _guard_rows(manifest, guard, failures=True)
    control_rows = _guard_rows(manifest, guard, failures=False)
    if guard == "R1":
        supported = [row for row in failure_rows if _r1_failure_supported(row)]
        blocked = [row for row in control_rows if _r1_control_blocked(row)]
    elif guard == "T1":
        supported = [row for row in failure_rows if _t1_failure_supported(row)]
        blocked = [row for row in control_rows if _t1_control_blocked(row)]
    else:
        raise ValueError(f"unknown guard: {guard}")

    support_rate = len(supported) / len(failure_rows) if failure_rows else 0.0
    block_rate = len(blocked) / len(control_rows) if control_rows else 0.0
    if support_rate >= 0.8 and block_rate == 0:
        verdict = "PASS_TO_G2"
    elif support_rate >= 0.8 and block_rate <= 0.05:
        verdict = "PASS_TO_G2_WITH_CONTROLS"
    else:
        verdict = "REJECT_G1"
    notes = [
        "G1 is reject-only and uses evaluator gold traces; it cannot prove live improvement.",
        f"support_threshold=0.80 observed={support_rate:.3f}",
        f"control_block_threshold=0.05 observed={block_rate:.3f}",
    ]
    if blocked:
        notes.append(
            "blocked_control_task_ids=" + ",".join(str(row.get("task_id")) for row in blocked[:10])
        )
        notes.append("include blocked controls in G2 micro-sim before any targeted mini run")
    return GuardVerdict(
        guard=guard,
        verdict=verdict,
        failures_total=len(failure_rows),
        failures_supported=len(supported),
        controls_total=len(control_rows),
        controls_blocked=len(blocked),
        notes=notes,
    )


def _cluster_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get("cluster") or "") for row in rows).items()))


def run(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    verdicts = [_evaluate_guard(manifest, guard).to_json() for guard in ("R1", "T1")]
    return {
        "metadata": {
            "schema": "crucible_g1_trace_replay.v1",
            "source_manifest": str(manifest_path),
            "purpose": "reject-only G1 screen before subscription micro-sim",
        },
        "verdicts": verdicts,
        "failure_clusters": _cluster_counts(manifest.get("failures", [])),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for verdict in result["verdicts"]:
        print(
            f"{verdict['guard']}: {verdict['verdict']} | "
            f"support={verdict['failures_supported']}/{verdict['failures_total']} "
            f"controls_blocked={verdict['controls_blocked']}/{verdict['controls_total']}"
        )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
