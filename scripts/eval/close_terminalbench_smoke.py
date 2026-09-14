#!/usr/bin/env python3
"""Append missing sidecars for one frozen canonical-timeout/raw-one smoke.

No model calls, raw copies, retry, publication, or retrospective validity changes.
The original failed helper and all existing receipts remain immutable evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from scripts.eval import contract

_OUTPUTS = ("selected-verifier-receipts.json", "attempts.jsonl", "analysis.json")


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _encoded(value: object, *, compact: bool = False) -> bytes:
    return (
        json.dumps(value, indent=None if compact else 2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def _validate_and_publish(
    run: Path,
    captured: dict[str, str],
    outputs: tuple[bytes, ...],
    *,
    write: bool,
) -> None:
    """Validate a disposable hardlink view before append-only publication."""
    with TemporaryDirectory(dir=run.parent, prefix=f".{run.name}-closeout-") as temporary:
        staged = Path(temporary) / run.name
        staged.mkdir()
        for name in captured:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(run / name, target)
        for name, content in zip(_OUTPUTS, outputs, strict=True):
            with (staged / name).open("xb") as stream:
                stream.write(content)
        # Includes attempt, analysis, declared-artifact and selected-evidence validation.
        contract.validate_run_bundle(staged / "run-spec.json")
        _require(
            all(contract._sha256(run / name) == digest for name, digest in captured.items()),
            "Original evidence changed before publication",
        )
        if write:
            _require(
                not any((run / name).exists() for name in _OUTPUTS),
                "An output already exists; never overwrite closure",
            )
            # Not a multi-file transaction: failure propagates and partial output stays
            # visibly incomplete. Analysis is the last consumer; never report success early.
            for name in _OUTPUTS:
                os.link(staged / name, run / name)


def close_smoke(run: Path, expected_spec_sha256: str, *, write: bool = False) -> dict[str, object]:
    """Validate original custody and the full bundle before appending any output."""
    run = run.resolve()
    _require(
        not any((run / name).exists() for name in _OUTPUTS),
        "An output already exists; never overwrite closure",
    )
    captured: dict[str, str] = {}
    refs: dict[str, dict[str, str]] = {}

    def ref(name: str | Path, kind: str = "other") -> dict[str, str]:
        name = str(name)
        contract._validate_relative_reference(name, label="closure evidence")
        path = run / name
        _require(
            not any(part.is_symlink() for part in (path, *path.parents)),
            "Symlink evidence rejected",
        )
        digest = contract._sha256(path)
        _require(name not in captured or captured[name] == digest, "Original evidence changed")
        captured[name] = digest
        if name not in refs or kind != "other":
            refs[name] = {"kind": kind, "path": name, "sha256": digest}
        return refs[name]

    def read(name: str | Path, kind: str = "other") -> dict[str, Any]:
        ref(name, kind)
        return contract._load_json_object(run / name)

    spec = contract.validate_run_spec(run / "run-spec.json")
    spec_sha = ref("run-spec.json")["sha256"]
    _require(spec_sha == expected_spec_sha256, "Original frozen spec digest mismatch")
    _require(
        spec["run_id"] == run.name and spec["preregistration"]["mode"] == "prospective",
        "Expected original prospective run",
    )
    _require(
        spec["privacy"]["classification"] == "internal"
        and spec["reproduction"]["comparison"]["promotion_authority"] == "none",
        "Private diagnostic only",
    )
    _require(
        spec["artifacts"]["trajectory"] is None
        and spec["artifacts"]["attempts"] == "attempts.jsonl"
        and spec["artifacts"]["analysis"] == "analysis.json",
        "Unexpected frozen artifact contract",
    )
    frozen = read("execution-contract.json")
    binding = read("trial-binding.json")
    _require(
        frozen["run_spec_sha256"] == binding["run_spec_sha256"] == spec_sha,
        "Frozen spec binding mismatch",
    )
    _require(
        binding["execution_contract_sha256"] == ref("execution-contract.json")["sha256"],
        "Execution contract changed",
    )
    _require(
        binding["source_sha256"] == frozen["source_sha256"]
        and frozen["source_revision"] == spec["reproduction"]["geode"]["revision"],
        "Source identity mismatch",
    )
    _require(
        frozen["harbor_automatic_retries"]
        == frozen["replacement_attempts"]
        == binding["sequence"]
        == 0,
        "One attempt, zero replacements required",
    )
    for name, digest in {**frozen["tool_sha256"], **frozen["preflight_receipt_sha256"]}.items():
        _require(ref(name)["sha256"] == digest, "Frozen tool or preflight receipt changed")
    for item in frozen["reviewed_notes"].values():
        _require(ref(item["path"])["sha256"] == item["sha256"], "Reviewed protocol changed")
    _require(
        ref("job-live.json")["sha256"] == frozen["job_live_sha256"],
        "Native job configuration changed",
    )
    source = Path(binding["trial_config"]["agent"]["kwargs"]["source_bundle"])
    source = source.relative_to(Path("artifacts/eval/runs") / run.name)
    _require(ref(source)["sha256"] == frozen["source_sha256"], "Frozen source bundle changed")
    native_path = Path(spec["artifacts"]["native_results"])
    job = read(native_path, "native-result")
    trial = native_path.parent / binding["trial_name"]
    native = read(trial / "result.json", "native-result")
    _require(
        list((run / native_path.parent).glob("*/result.json")) == [run / trial / "result.json"],
        "Expected exactly one native trial",
    )
    _require(
        job["n_total_trials"] == 1
        and job["finished_at"]
        and job["stats"]["n_retries"]
        == job["stats"]["n_running_trials"]
        == job["stats"]["n_pending_trials"]
        == 0,
        "Native job is not closed without retries",
    )
    _require(
        native["trial_name"] == binding["trial_name"]
        and native["task_name"] == binding["task_name"] == frozen["expected_task_name"]
        and native["task_checksum"] == binding["task_checksum"] == frozen["expected_task_checksum"],
        "Native task identity mismatch",
    )
    _require(
        native["config"] == binding["trial_config"]
        and job["id"] == binding["trial_config"]["job_id"],
        "Native trial differs from prospective binding",
    )
    _require(native["agent_info"]["version"] == frozen["source_revision"], "Native source mismatch")
    _require(
        native["exception_info"]["exception_type"] == "AgentTimeoutError"
        and native["verifier_result"]["rewards"] == {"reward": 1.0},
        "This closure only handles canonical timeout with raw reward one",
    )
    runtime = read(trial / "agent/runtime-result.json")
    _require(
        runtime["metadata"] == native["agent_result"]["metadata"]
        and runtime["metadata"]["termination_reason"] == "external_cancellation"
        and runtime["metadata"]["error_type"] == "CancelledError",
        "Runtime/native terminal mismatch or internal hold",
    )
    started = contract._parse_datetime(native["agent_execution"]["started_at"])
    finished = contract._parse_datetime(native["agent_execution"]["finished_at"])
    _require(
        started.utcoffset() is not None
        and finished.utcoffset() is not None
        and (finished - started).total_seconds()
        >= spec["reproduction"]["execution"]["timeout_seconds"]
        == frozen["limits"]["agent_sec"],
        "Canonical deadline is not source-backed",
    )
    original = read(spec["artifacts"]["verifier_receipts"], "verifier-receipt")
    previous = original["receipts"][0]
    _require(
        len(original["receipts"]) == 1
        and previous["attempt_id"] == binding["attempt_id"]
        and previous["native_reward"] == 1
        and previous["selected_reward"] == 0
        and previous["validity"] == "valid",
        "Original reviewed timeout selection differs",
    )
    _require(
        ref(previous["adjudication"]["path"])["sha256"] == previous["adjudication"]["sha256"],
        "Original closure note changed",
    )
    observation = read("observation-check.json")
    _require(
        observation["run_spec_sha256"] == spec_sha
        and observation["source_sha256"] == frozen["source_sha256"]
        and observation["trial_name"] == binding["trial_name"],
        "Observation identity mismatch",
    )
    _require(
        observation["observation_valid"] is True
        and observation["accounting"]["uniform_requested_effort"] is True
        and observation["cache_complete"] is False
        and observation["whole_runtime_complete"] is False
        and observation["full_runtime_expansion_ready"] is False,
        "Unexpected observation disposition; no inferred completeness",
    )
    for name, digest in observation["artifact_sha256"].items():
        # ATIF stays supplemental `other`, not an undeclared canonical trajectory.
        kind = "native-result" if name == "result.json" else "other"
        _require(ref(trial / name, kind)["sha256"] == digest, "Observation source changed")
    for name in (
        "close-smoke.original-failure.log",
        "diagnostic-addendum.md",
        "recording/capture-receipt.json",
    ):
        ref(name)
    if (run / "historical-reference.json").exists():
        ref("historical-reference.json")
    # Bind every retained raw file by digest, without opening databases or copying raw bytes.
    for path in sorted((run / "raw").rglob("*")):
        if path.is_file():
            ref(path.relative_to(run))
    capture = read("recording/capture-receipt.json")
    for item in capture["files"] + capture["trial_replay"]["files"]:
        _require(ref(item["path"])["sha256"] == item["sha256"], "Capture custody changed")
    reward_ref = ref(trial / "verifier/reward.txt", "verifier-receipt")
    raw_ref = ref(trial / "result.json", "native-result")
    now = datetime.now(UTC).isoformat()
    metric = {
        "name": spec["study"]["primary_metric"]["name"],
        "value": 0,
        "numerator": 0,
        "denominator": 1,
    }
    receipt = {
        "schema": "terminalbench21.verifier-receipts.v1",
        "run_id": spec["run_id"],
        "run_spec_sha256": spec_sha,
        "selection_rule": spec["study"]["invalidation_rule"],
        "primary_metric": metric,
        "recorded_at": now,
        "authority": "Original frozen timeout rule; raw native reward remains unchanged",
        "supersedes": "Failed postprocessor only; original receipts and raw files remain immutable",
        "producer": {
            "path": "scripts/eval/close_terminalbench_smoke.py",
            "sha256": contract._sha256(Path(__file__)),
            "validator_sha256": contract._sha256(Path(contract.__file__)),
        },
        "receipts": [
            {
                "attempt_id": binding["attempt_id"],
                "validity": "valid",
                "outcome": "failed",
                "selected_reward": 0,
                "native_reward": 1,
                "selection_reason": "canonical-agent-timeout",
                "failure_class": "AgentTimeoutError",
                "raw_result": raw_ref["path"],
                "raw_result_sha256": raw_ref["sha256"],
                "reward_receipt": reward_ref["path"],
                "reward_receipt_sha256": reward_ref["sha256"],
            }
        ],
        "source_hashes": dict(captured),
    }
    receipt_bytes = _encoded(receipt)
    refs[_OUTPUTS[0]] = {
        "kind": "verifier-receipt",
        "path": _OUTPUTS[0],
        "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
    }
    evidence = list(refs.values())
    summary = (
        "Canonical 600-second timeout: valid failed task, selected reward 0/1; "
        "raw post-timeout verifier reward 1 retained. Observation and cache admission "
        "remain incomplete; no in-budget pass or expansion."
    )
    attempt = contract._load_json_object(contract.EVAL_DIR / "eval-attempt.template.json")
    attempt.update(
        run_id=spec["run_id"],
        attempt_id=binding["attempt_id"],
        parent_attempt_id=None,
        sequence=0,
        timing={
            "status": "exact",
            "started_at": native["started_at"],
            "finished_at": native["finished_at"],
            "source_ref": raw_ref["path"],
        },
        validity="valid",
        outcome="failed",
        change={
            "surface": "baseline",
            "description": (
                "Original sole supplementary attempt for historical cell 781; "
                "postprocessor-only closeout, no new execution or historical replacement."
            ),
        },
        expected_effect=spec["study"]["hypothesis"],
        observed_result=summary,
        failure_class="AgentTimeoutError",
        error_ref=raw_ref["path"] + "#/exception_info",
        evidence_refs=evidence,
        selected_for_analysis=True,
    )
    attempts_bytes = _encoded(attempt, compact=True)
    primary = dict(
        **metric,
        unit=spec["study"]["primary_metric"]["unit"],
        source_ref=_OUTPUTS[0],
        source_locator={
            field: f"/primary_metric/{field}" for field in ("value", "numerator", "denominator")
        },
    )
    analysis = contract._load_json_object(contract.EVAL_DIR / "eval-analysis.template.json")
    analysis.update(
        run_id=spec["run_id"],
        analyzed_at=now,
        run_spec_sha256=spec_sha,
        attempts_sha256=hashlib.sha256(attempts_bytes).hexdigest(),
        selected_attempt_ids=[binding["attempt_id"]],
        answer=summary,
        metrics=[
            primary,
            {
                "name": "raw_verifier_reward",
                "value": 1,
                "numerator": None,
                "denominator": None,
                "unit": "reward",
                "source_ref": raw_ref["path"],
                "source_locator": None,
            },
            {
                "name": "cache_complete",
                "value": "false",
                "numerator": None,
                "denominator": None,
                "unit": "status",
                "source_ref": "observation-check.json",
                "source_locator": None,
            },
        ],
        decision={
            "outcome": "diagnostic-only",
            "hypothesis_status": "not-supported",
            "rationale": (
                "Frozen canonical timeout selects failure; later raw verifier one does not "
                "prove completion within budget. Missing counters and source/producer custody "
                "limits continue to block collection admission."
            ),
        },
        limitations=[
            "Postprocessor correction only; no new run, retry, source change or release.",
            "Export agreement is not whole-runtime completeness; missing usage stays unknown.",
            "ATIF and cast are derived replay, not canonical trajectory or original PTY authority.",
            "Historical cell 781 and the original full-suite scores/absence remain unchanged.",
            "No in-budget pass, historical repair, measured improvement or training admission.",
        ],
        evidence_refs=evidence,
    )
    _validate_and_publish(
        run,
        captured,
        (receipt_bytes, attempts_bytes, _encoded(analysis)),
        write=write,
    )
    return {
        "written": write,
        "run_id": spec["run_id"],
        "original_files_verified": len(captured),
        "validity": "valid",
        "outcome": "failed",
        "primary_numerator": 0,
        "primary_denominator": 1,
        "raw_verifier_reward": 1,
        "cache_complete": False,
        "full_runtime_expansion_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--run-spec-sha256", required=True)
    parser.add_argument(
        "--write", action="store_true", help="Append only missing outputs after verification"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            close_smoke(args.run_dir, args.run_spec_sha256, write=args.write), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
