#!/usr/bin/env python3
"""Private, frozen root → decision tool → root continuation diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.benchmarks.decision_handoff_runtime import (  # noqa: F401 — existing CLI/test surface
    ANSWER_SCHEMA,
    JEV_INPUT_USD_PER_MILLION,
    JEV_MODEL,
    MODEL,
    PRICE_REFERENCE,
    PRIMARY_METRIC,
    SYSTEM,
    HandoffReceipt,
    StatusLookupTool,
    _accounting,
    _aggregate_accounting,
    _oracle,
    _sha,
    _write,
    run_arm,
)
from scripts.eval.contract import validate_analysis, validate_attempts, validate_run_spec

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "evals/benchmarks/fixtures/decision-handoff.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_is_pinned(reproduction: dict[str, Any]) -> bool:
    """Require the same clean source before and after every child dispatch."""
    git = shutil.which("git")
    if git is None:
        return False
    try:
        revision = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()  # noqa: S603
        dirty = subprocess.check_output([git, "status", "--porcelain"], cwd=ROOT, text=True)  # noqa: S603
    except (OSError, subprocess.CalledProcessError):
        return False
    return (
        not dirty
        and reproduction["geode"]["revision"] == revision
        and reproduction["harness"]["revision"] == revision
        and reproduction["geode"]["dirty"] is False
    )


def preflight(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec = validate_run_spec(path)
    reproduction = spec["reproduction"]
    execution = reproduction["execution"]
    cases = json.loads(FIXTURE.read_text())
    checks = {
        "clean pinned source": _source_is_pinned(reproduction),
        "approved prospective freeze": (
            spec["preregistration"]["mode"] == "prospective"
            and spec["preregistration"]["status"] == "frozen"
            and spec["preregistration"]["live_test_approved"] is True
            and datetime.fromisoformat(spec["preregistration"]["frozen_at"].replace("Z", "+00:00"))
            <= datetime.now(UTC)
        ),
        "fixture": (
            reproduction["environment"]["initial_state_ref"] == f"sha256:{_sha(FIXTURE)}"
            and len(cases) == 5
            and execution["ordered_workload_ids"] == [case["id"] for case in cases]
        ),
        "root route": reproduction["model"]
        == {"provider": "openai", "label": MODEL, "route": "subscription", "reasoning": "xhigh"},
        "uncapped fixed workload": (
            execution["budget"] == {"kind": "combined", "limit": None, "unit": "uncapped"}
            and execution["repetitions"] == 1
            and execution["max_concurrency"] == 1
            and execution["timeout_seconds"] == 180
        ),
        "question and comparator": (
            spec["study"]["primary_metric"] == PRIMARY_METRIC
            and reproduction["comparison"]
            == {
                "claim_class": "diagnostic",
                "comparator": f"root-with-typesafe:{JEV_MODEL}:choice",
                "comparability": "direct",
                "promotion_authority": "none",
            }
        ),
        "private fixed destinations": (
            spec["privacy"]["classification"] != "public"
            and spec["artifacts"]["native_results"] == "results.json"
            and spec["artifacts"]["attempts"] == "attempts.jsonl"
            and spec["artifacts"]["analysis"] == "analysis.json"
        ),
        "fresh run": not any(
            (path.parent / name).exists()
            for name in ("private", "results.json", "attempts.jsonl", "analysis.json")
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("Handoff preflight failed: " + ", ".join(failures))
    return spec, cases


def _run_child(case_index: int, arm: str, directory: Path) -> None:
    if "core.paths" in sys.modules:
        raise RuntimeError("runtime imported before isolation")
    os.umask(0o077)
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    os.environ["GEODE_HOME"] = str(directory / "geode-home")
    os.environ["GEODE_STATE_ROOT"] = str(directory / "state")
    os.environ["GEODE_VERIFY_MODE"] = "rule_based"
    os.environ["GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR"] = "1"
    os.environ["GEODE_JUDGE_MODEL"] = ""
    os.environ["GEODE_COGNITIVE_REFLECTION_MODEL"] = ""
    os.environ.pop("GEODE_SESSION_TIME_BUDGET_S", None)
    os.chdir(workspace)
    logging.disable(logging.CRITICAL)
    from core.config import settings

    settings.llm_max_retries = 1
    settings.cost_limit_usd = 0
    case = json.loads(FIXTURE.read_text())[case_index]
    result = asyncio.run(run_arm(case, arm, directory))
    _write(directory / "result.json", result)


def _summary(pairs: list[dict[str, Any]], stop_reason: str | None) -> dict[str, Any]:
    measurable = len(pairs) == 5 and all(
        len(pair) == 2 and all(row["valid"] for row in pair.values()) for pair in pairs
    )
    delta = (
        sum(int(pair["b"]["passed"]) - int(pair["a"]["passed"]) for pair in pairs)
        if measurable
        else None
    )
    arms = {}
    for arm in ("a", "b"):
        rows = [pair[arm] for pair in pairs if arm in pair]
        calls = [call for row in rows for call in row.get("call_accounting", [])]
        complete = bool(rows) and all(
            row.get("usage", {}).get("attempt_pairing_complete") is True
            and row.get("usage", {}).get("observation_status") == "no_known_faults"
            and row.get("usage", {}).get("terminal_event_count")
            == len(row.get("call_accounting", []))
            and not row.get("accounting_incomplete", False)
            for row in rows
        )
        latencies = [row["elapsed_seconds"] for row in rows if "elapsed_seconds" in row]
        purposes = sorted({call.get("purpose") or "unknown" for call in calls})
        arms[arm] = {
            "attempted_tasks": len(rows),
            "passed_tasks": sum(row["passed"] is True for row in rows),
            "valid_tasks": sum(row["valid"] is True for row in rows),
            "median_elapsed_seconds": statistics.median(latencies) if latencies else None,
            "accounting": _aggregate_accounting(calls, complete=complete),
            "by_purpose": {
                purpose: _aggregate_accounting(
                    [call for call in calls if (call.get("purpose") or "unknown") == purpose],
                    complete=complete,
                )
                for purpose in purposes
            },
        }
    return {
        "value": delta / 5 if delta is not None else "not-measurable",
        "numerator": delta,
        "denominator": 5 if measurable else None,
        "stop_reason": stop_reason,
        "attempted_pairs": len(pairs),
        "paired_tasks": sum(len(pair) == 2 for pair in pairs),
        "price_reference": PRICE_REFERENCE,
        "cost_limitation": (
            "Public-price estimates and subscription API equivalents are not invoices."
        ),
        "arms": arms,
    }


def _child_artifacts(directory: Path, run_dir: Path) -> list[dict[str, str]]:
    """Bind available private evidence, even when a killed child wrote no result."""
    files = {
        directory / name
        for name in (
            "result.json",
            "session-events.json",
            "call-events.json",
            "trajectory.json",
            "trajectory.private.json",
            "handoff.json",
            "runtime-metadata.json",
            "intervention.json",
        )
        if (directory / name).is_file()
    }
    files.update(
        artifact
        for artifact in directory.rglob("*")
        if artifact.is_file() and artifact.name.endswith((".db", ".db-wal", ".db-shm"))
    )
    return [
        {
            "kind": "native-result" if artifact.name == "result.json" else "other",
            "path": artifact.relative_to(run_dir).as_posix(),
            "sha256": _sha(artifact),
        }
        for artifact in sorted(files)
    ]


def _child_result(directory: Path, case_id: str, arm: str, error: str | None) -> dict[str, Any]:
    """Retain partial child accounting without promoting an incomplete task."""
    from scripts.eval.contract import _strict_json_loads

    result: dict[str, Any] = {}
    result_path = directory / "result.json"
    if result_path.is_file():
        try:
            loaded = _strict_json_loads(result_path.read_text(), label="child result")
            if not isinstance(loaded, dict):
                raise ValueError("child result must be an object")
            result = loaded
            if (result.get("case_id"), result.get("arm")) != (case_id, arm):
                error = error or "child_identity_mismatch"
            if type(result.get("valid")) is not bool or type(result.get("passed")) is not bool:
                error = error or "invalid_child_result"
        except (ValueError, UnicodeError):
            error = error or "invalid_child_result"
    else:
        error = error or "missing_child_result"
    accounting = result.get("call_accounting")
    if not isinstance(accounting, list) or not all(
        isinstance(row, dict) and isinstance(row.get("usage"), dict) for row in accounting
    ):
        error = error or "invalid_child_accounting"
        result["call_accounting"] = []
        result["accounting_incomplete"] = True
        call_path = directory / "call-events.json"
        if call_path.is_file():
            try:
                events = _strict_json_loads(call_path.read_text(), label="partial call events")
                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, dict) or event.get("action") != "llm.call.ended":
                            continue
                        payload = event.get("payload")
                        if isinstance(payload, dict):
                            result["call_accounting"].append(
                                {
                                    "purpose": payload.get("purpose"),
                                    "model": payload.get("model"),
                                    "llm_attempt_id": event.get("llm_attempt_id"),
                                    **_accounting(payload),
                                }
                            )
            except (ValueError, UnicodeError):
                pass  # Bytes remain digest-bound; malformed records are not fabricated usage.
    usage = result.get("usage")
    if not isinstance(usage, dict):
        result["usage"] = {}
        result["accounting_incomplete"] = True
    if result.get("valid") is True and (
        not result["call_accounting"]
        or result["usage"].get("attempt_pairing_complete") is not True
        or result["usage"].get("observation_status") != "no_known_faults"
        or result["usage"].get("terminal_event_count") != len(result["call_accounting"])
        or any(
            row.get("total_tokens") is None or row.get("error_type")
            for row in result["call_accounting"]
        )
    ):
        error = error or "invalid_child_accounting"
    if error:
        result.update(valid=False, passed=False, error_type=error, accounting_incomplete=True)
    return result


def execute(path: Path, spec: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    from core.memory.atomic_write import append_jsonl
    from dotenv import dotenv_values

    admitted_spec, admitted_cases = preflight(path)
    if spec != admitted_spec or cases != admitted_cases:
        raise ValueError("execution arguments differ from the frozen run spec or fixture")
    key = os.environ.get("TYPESAFE_API_KEY") or dotenv_values(
        Path.home() / ".geode/.env", interpolate=False
    ).get("TYPESAFE_API_KEY")
    if not key:
        raise ValueError("TYPESAFE_API_KEY unavailable")
    frozen_hash, fixture_hash = _sha(path), _sha(FIXTURE)
    private = path.parent / "private"
    private.mkdir(mode=0o700)
    attempts_path = path.parent / "attempts.jsonl"
    attempts_path.touch(mode=0o600, exist_ok=False)
    env = dict(os.environ, TYPESAFE_API_KEY=key, PYTHONPATH=str(ROOT))
    attempts: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    evidence: list[dict[str, str]] = []
    stop_reason = None
    interruption: BaseException | None = None
    summary: dict[str, Any] = {}
    for index, case in enumerate(cases):
        started = _now()
        arms: dict[str, Any] = {}
        refs: list[dict[str, str]] = []
        for arm in ("a", "b") if index % 2 == 0 else ("b", "a"):
            if not _source_is_pinned(spec["reproduction"]):
                stop_reason = "source_drift"
                break
            if _sha(path) != frozen_hash or _sha(FIXTURE) != fixture_hash:
                stop_reason = "input_drift"
                break
            directory = private / f"{index:02d}-{arm}"
            directory.mkdir(mode=0o700)
            try:
                completed = subprocess.run(  # noqa: S603 — fixed local runner, frozen case/arm
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--child-case",
                        str(index),
                        "--arm",
                        arm,
                        "--output",
                        str(directory),
                    ],
                    env=env,
                    cwd=ROOT,
                    capture_output=True,
                    timeout=210,
                    check=False,
                )
                error = "child_process_failure" if completed.returncode else None
            except subprocess.TimeoutExpired:
                error = "child_process_timeout"
            except OSError:
                error = "child_process_start_failure"
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as exc:
                interruption = exc
                error = "parent_interrupted"
            if not _source_is_pinned(spec["reproduction"]):
                error = error or "source_drift"
            refs.extend(_child_artifacts(directory, path.parent))
            arms[arm] = _child_result(directory, case["id"], arm, error)
            if not arms[arm]["valid"]:
                stop_reason = arms[arm]["error_type"] or "invalid_runtime_observation"
                break
        pairs.append(arms)
        valid = len(arms) == 2 and all(row["valid"] for row in arms.values())
        if stop_reason or index == len(cases) - 1:
            summary = _summary(pairs, stop_reason)
            refs.append(_write(path.parent / "results.json", summary))
        failure_class = None if valid else "invalid_handoff_attempt"
        if valid and any(
            row.get("error_type") == "decision_response_rejected" for row in arms.values()
        ):
            failure_class = "decision_response_rejected"
        attempt = json.loads((ROOT / "docs/eval/eval-attempt.template.json").read_text())
        attempt.update(
            run_id=spec["run_id"],
            attempt_id=f"attempt-{index:02d}",
            sequence=index,
            timing={
                "status": "exact",
                "started_at": started,
                "finished_at": _now(),
                "source_ref": None,
            },
            validity="valid" if valid else "invalid",
            outcome=("passed" if all(row["passed"] for row in arms.values()) else "failed")
            if valid
            else "unknown",
            change={"surface": "structured-decision-tool", "description": case["id"]},
            expected_effect="Compare the same root task with an Astra or Jev decision helper.",
            observed_result=(
                "Paired native task evidence retained."
                if valid
                else "Incomplete or invalid attempt; only available partial evidence retained."
            ),
            failure_class=failure_class,
            evidence_refs=refs,
        )
        attempts.append(attempt)
        evidence.extend(refs)
        append_jsonl(attempts_path, attempt)
        print(
            f"Completed {case['id']}: valid={valid}; "
            f"A={arms.get('a', {}).get('passed')}; B={arms.get('b', {}).get('passed')}",
            flush=True,
        )
        if stop_reason:
            break
    measurable = summary["numerator"] is not None
    validate_attempts(attempts_path)
    analysis = json.loads((ROOT / "docs/eval/eval-analysis.template.json").read_text())
    analysis.update(
        run_id=spec["run_id"],
        analyzed_at=_now(),
        run_spec_sha256=frozen_hash,
        attempts_sha256=_sha(attempts_path),
        selected_attempt_ids=[row["attempt_id"] for row in attempts],
        answer=(
            "Local root continuation diagnostic; no default adoption or general benchmark claim."
        ),
        metrics=[
            {
                "name": PRIMARY_METRIC["name"],
                "value": summary["value"],
                "numerator": summary["numerator"],
                "denominator": summary["denominator"],
                "unit": "ratio",
                "source_ref": "results.json",
                "source_locator": {
                    "value": "/value",
                    "numerator": "/numerator",
                    "denominator": "/denominator",
                }
                if measurable
                else None,
            }
        ],
        decision={
            "outcome": "diagnostic-only",
            "hypothesis_status": "mixed" if measurable else "invalidated",
            "rationale": (
                "Five synthetic tasks test wiring and behavior, "
                "not calibrated confidence or broad superiority."
            ),
        },
        limitations=[
            "Same root, different decision model/interface bundles; one repetition.",
            "Runtime cost fields and public-price estimates are not subscription invoices.",
            "Native rule-based verification is mechanical; "
            "the scenario oracle owns task correctness.",
        ],
        evidence_refs=evidence,
    )
    _write(path.parent / "analysis.json", analysis)
    validate_analysis(
        path.parent / "analysis.json", run_spec_path=path, attempts_path=attempts_path
    )
    if interruption is not None:
        raise interruption


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--child-case", type=int, choices=range(5), help=argparse.SUPPRESS)
    parser.add_argument("--arm", choices=("a", "b"), help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_case is not None:
        if args.arm is None or args.output is None:
            parser.error("child execution requires an arm and output")
        _run_child(args.child_case, args.arm, args.output.resolve())
        return
    if args.run_spec is None:
        parser.error("--run-spec is required")
    path = args.run_spec.resolve()
    spec, cases = preflight(path)
    if args.execute:
        execute(path, spec, cases)
    else:
        print("Handoff preflight passed; no model calls.")


if __name__ == "__main__":
    main()
