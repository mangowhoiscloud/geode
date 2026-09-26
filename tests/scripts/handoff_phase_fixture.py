"""Synthetic closed Harbor handoff phase for offline data-tool tests.

The files imitate the retained export shapes of ``run_arm``, ``harbor_handoff``
and the private phase runner. They are fixtures, not collection receipts, and
contain no model output or credential.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.observability.trajectory import _digest_private_event_payload, build_trajectory
from evals.benchmarks.decision_handoff_runtime import JEV_MODEL, MODEL, _accounting
from evals.platforms.harbor import _summarize_usage

from tests.scripts.test_eval_contract import _run_spec, _workload_hash

REVISION = "a" * 40
RUN_ID = "geode-jev-noul-natural-20260926-fixture"
FROZEN_AT = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
CELLS: list[dict[str, Any]] = [
    {
        "index": 0,
        "case_id": "inbox-a",
        "arm": "a",
        "verification_engine": "llm",
        "repetition": 0,
        "position": 0,
        "trial_name": "fixture-natural-r0-inbox-a-a",
        "noul_truth": {"has_contradiction": False, "missing_evidence": True},
    },
    {
        "index": 1,
        "case_id": "inbox-a",
        "arm": "b",
        "verification_engine": "jev",
        "repetition": 0,
        "position": 1,
        "trial_name": "fixture-natural-r0-inbox-a-b",
        "noul_truth": {"has_contradiction": False, "missing_evidence": True},
    },
    {
        "index": 2,
        "case_id": "inbox-b",
        "arm": "b",
        "verification_engine": "jev",
        "repetition": 0,
        "position": 0,
        "trial_name": "fixture-natural-r0-inbox-b-b",
        "noul_truth": {"has_contradiction": True, "missing_evidence": True},
    },
    {
        "index": 3,
        "case_id": "inbox-b",
        "arm": "a",
        "verification_engine": "llm",
        "repetition": 0,
        "position": 1,
        "trial_name": "fixture-natural-r0-inbox-b-a",
        "noul_truth": {"has_contradiction": True, "missing_evidence": True},
    },
]
INVALID_TRIAL = "fixture-natural-r0-inbox-b-b"
INVALID_CELL = ("inbox-b", "b")


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


# Frozen repetition contract per arm and case, as a runner writes it into freeze.json.
POLICY_DIGESTS = {"a": _hex("policy:arm-a"), "b": _hex("policy:arm-b")}
RESET_DIGEST = _hex("reset:fresh-container-session-cache")


# Paired concurrent slots (05 v2 §2.4): (launch skew, agent start skew) per case.
SLOT_SKEWS = {"inbox-a": (0.2, 3.5), "inbox-b": (0.4, 42.0)}
ACCOUNT_FP_PLACEHOLDER = "0123456789ab"


def _private_receipt(cell: dict[str, Any], attempt_id: str, run_id: str) -> dict[str, Any]:
    """Runner-owned private trial receipt; arm b uses the Run draft's alias names."""
    launch, start = SLOT_SKEWS[cell["case_id"]]
    receipt: dict[str, Any] = {
        "schema_id": "jev-v3.private-trial-receipt@1",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "trial_name": cell["trial_name"],
        "slot_id": f"r{cell['repetition']}-{cell['case_id']}",
        "position": cell["position"],
        "codex_account_fp12": ACCOUNT_FP_PLACEHOLDER,
        "pair_sync": start <= 30,
        "same_account_external_usage": "unknown",
        "external_usage_reason": "shared-account-video-session",
        "policy_digest": cell["policy_digest"],
        "reset_digest": cell["reset_digest"],
    }
    if cell["arm"] == "a":
        receipt.update(dispatch_skew_s=launch, agent_start_skew_s=start, concurrent_trials=1)
    else:
        receipt.update(
            pair_launch_skew_s=launch, pair_agent_start_skew_s=start, concurrent_trials_active=1
        )
    return receipt


def contract_fields(case_id: str, arm: str) -> dict[str, str]:
    return {
        "policy_digest": POLICY_DIGESTS[arm],
        "reset_digest": RESET_DIGEST,
        "case_sha256": _hex(f"payload:{case_id}"),
        "task_checksum": _hex(f"task:{case_id}"),
        "verifier_sha256": _hex(f"verifier:{case_id}"),
    }


def write_json(path: Path, value: Any) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _usage(provider: str) -> dict[str, int | None]:
    if provider == "typesafe":
        # Jev reports input/output only; cache and reasoning stay unknown, not zero.
        return {
            "input_tokens": 2589,
            "output_tokens": 48,
            "cached_input_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
        }
    return {
        "input_tokens": 3000,
        "output_tokens": 150,
        "cached_input_tokens": 1024,
        "cache_write_tokens": 0,
        "reasoning_tokens": 55,
    }


def _trial(
    phase_dir: Path,
    cell: dict[str, Any],
    *,
    started: datetime,
    judge_provider: str,
    judge_duration_ms: float,
    passed: bool = True,
    extra_lookups: int = 0,
    runner_strict: bool | None = None,
    helper_fields: dict[str, bool] | None = None,
) -> None:
    trial = phase_dir / "trials" / cell["trial_name"]
    agent = trial / "agent"
    session = f"s-{cell['index']}"
    engine = cell["verification_engine"]
    specs = [
        ("agentic_loop", "openai", 7892.9),
        ("cognitive_reflection", "openai", 15972.3),
        ("turn_verification", judge_provider, judge_duration_ms),
    ]
    events: list[SimpleNamespace] = []
    persisted: list[dict[str, Any]] = []
    for number, (purpose, provider, duration_ms) in enumerate(specs):
        attempt = f"llm-{session}:step-{number}:attempt-1"
        call_id = f"llm-{session}:step-{number}"
        stamp = (started + timedelta(seconds=5 + 10 * number)).timestamp()
        payload = {
            "purpose": purpose,
            "model": JEV_MODEL if provider == "typesafe" else MODEL,
            "response_model": JEV_MODEL if provider == "typesafe" else MODEL,
            "provider": provider,
            "adapter": "typesafe" if provider == "typesafe" else "codex_oauth",
            "source": "payg" if provider == "typesafe" else "subscription",
            "effort": "none" if provider == "typesafe" else "xhigh",
            "usage": _usage(provider),
            "response_id": f"{'req' if provider == 'typesafe' else 'resp'}_{session}_{number}",
            "error_type": None,
            "success": True,
        }
        for offset, action in ((0, "llm.call.started"), (1, "llm.call.ended")):
            event = SimpleNamespace(
                action=action,
                id=2 * number + offset + 1,
                occurred_at=stamp + offset,
                session_id=session,
                llm_call_id=call_id,
                llm_attempt_id=attempt,
                tool_call_id=None,
                payload_hash=hashlib.sha256(f"{attempt}{action}".encode()).hexdigest(),
                payload=payload if offset else {"purpose": purpose},
            )
            events.append(event)
            persisted.append(
                {
                    "id": event.id,
                    "action": action,
                    "llm_attempt_id": attempt,
                    "payload_hash": event.payload_hash,
                    # The durable activity row names latency duration_ms.
                    "payload": {**event.payload, "duration_ms": duration_ms}
                    if offset
                    else event.payload,
                }
            )
    usage = _summarize_usage(events)
    usage["source_snapshot_complete"] = True
    accounting = [
        {
            "purpose": event.payload["purpose"],
            "model": event.payload["model"],
            "llm_attempt_id": event.llm_attempt_id,
            **_accounting(event.payload),
        }
        for event in events
        if event.action == "llm.call.ended"
    ]
    truth = cell["noul_truth"]
    verdict = "contradicted" if truth["has_contradiction"] else "insufficient_evidence"
    judge_call = f"llm-{session}:step-2"
    native: dict[str, Any] = (
        {
            "has_contradiction": {
                "type": "noul",
                "noul": 0.9 if truth["has_contradiction"] else 0.1,
            },
            "missing_evidence": {"type": "noul", "noul": 0.8},
        }
        if engine == "jev" and judge_provider == "typesafe"
        else dict(truth)
    )
    oracle = {
        "passed": passed,
        "extra_lookup_count": extra_lookups,
        "wrong_target_lookup_count": 0,
        "false_completion_count": 0,
        "lookup_attempt_count": 1,
        "rejected_lookup_count": 0,
    }
    native_verify = [{"action": "turn.verify.passed", "success": True}]
    # An intent helper cell has no matched final verdict and runs the helper arm itself.
    runtime_arm = "a0" if engine else cell["arm"]
    metadata = {
        "source_revision": REVISION,
        "verify_mode": "llm_judge",
        "effective_verify_mode": "llm_judge",
        "verification_engine": engine,
        "verification_primitive": "noul",
        "profile": "decision-handoff",
        "arm": runtime_arm,
        "execution_started": True,
        "error_type": None,
        "finalization_errors": [],
        "usage": usage,
        "score_authority": "Harbor task verifier, not runtime receipt",
        "geode_session_id": session,
        "termination_reason": "end_turn",
    }
    handoff = {
        "profile": "read-only-decision-handoff",
        "session_id": session,
        "db_path": "/logs/agent/geode-home/projects/-workspace/sessions/sessions.db",
        "source_snapshot_complete": True,
        "arm": runtime_arm,
        "case_id": cell["case_id"],
        "verification_engine": engine,
        "verification_primitive": "noul",
        "valid": True,
        "passed": passed,
        "error_type": None,
        "elapsed_seconds": 12.5 + cell["index"],
        "termination_reason": "end_turn",
        "oracle": oracle,
        "native_verify": native_verify,
        "usage": usage,
        "call_accounting": accounting,
        "verification_metrics": {
            "judgment_attempts": 1,
            "replan_requests": 0,
            "root_requests_consuming_feedback": 0,
        },
    }
    write_json(agent / "handoff-result.json", handoff)
    write_json(
        agent / "runtime-result.json",
        {"usage": usage, "metadata": metadata, "tool_definitions": []},
    )
    write_json(agent / "call-events.json", persisted)
    write_json(agent / "handoff.json", [])
    if engine:
        write_json(
            agent / "verification.json",
            {
                "inputs": [],
                "judgments": [
                    {
                        "engine": engine,
                        "primitive": "noul",
                        "llm_call_id": judge_call,
                        "accepted": True,
                        "verdict": verdict,
                        "native_answer": native,
                        "boolean_projection": dict(truth),
                    }
                ],
                "root_requests": [],
                "root_outputs": [],
            },
        )
    trajectory_events = []
    for ordinal, (kind, payload, call) in enumerate(
        [
            ("session.started", {}, ""),
            ("message.user", {"content": "fixture inbox"}, ""),
            ("tool.called", {"tool": "lookup_order_status", "arguments": {"id": "A-1"}}, "tool-1"),
            ("tool.completed", {"tool": "lookup_order_status", "result": "shipped"}, "tool-1"),
            ("message.assistant", {"content": "fixture answer"}, ""),
            (
                "session.ended",
                {"record_failures": 0, "runtime_observation_status": "no_known_faults"},
                "",
            ),
        ],
        1,
    ):
        trajectory_events.append(
            {
                "event_id": f"{session}-event-{ordinal}",
                "occurred_at": _iso(started + timedelta(seconds=ordinal)),
                "kind": kind,
                "session_id": session,
                "turn_id": "turn-1",
                "call_id": call,
                "actor": "agent",
                "payload": payload,
            }
        )
    full = build_trajectory(
        trajectory_id=f"harbor-{session}",
        source={"harness": "harbor", "session": session},
        events=trajectory_events,
        outcome=metadata,
        provenance={"adapter": "evals.platforms.harbor_handoff"},
        privacy={"review_state": "local"},
        captured_at=_iso(started + timedelta(seconds=40)),
    )
    digest = build_trajectory(
        trajectory_id=full["trajectory_id"],
        source=full["source"],
        events=[
            {**event, "payload": _digest_private_event_payload(event["kind"], event["payload"])}
            for event in full["events"]
        ],
        outcome=full["outcome"],
        provenance=full["provenance"],
        privacy=full["privacy"],
        captured_at=full["captured_at"],
        runtime_event_refs=full["runtime_event_refs"],
    )
    write_json(agent / "geode-trajectory.private.json", full)
    write_json(agent / "geode-trajectory.json", digest)
    write_json(
        trial / "result.json",
        {
            "trial_name": cell["trial_name"],
            "task_name": cell["case_id"],
            "started_at": _iso(started),
            "finished_at": _iso(started + timedelta(seconds=60)),
            "verifier_result": {"rewards": {"reward": 1.0 if passed else 0.0}},
            "exception_info": None,
        },
    )
    write_json(
        trial / "verifier" / "verifier-receipt.json",
        {
            "valid": True,
            "passed": passed,
            "oracle": oracle,
            "native_verify": native_verify,
            "error_type": None,
        },
    )
    write_json(
        trial / "trial-receipt.json",
        {
            **cell,
            "valid": True,
            "passed": passed,
            "error_type": None,
            "host_elapsed_seconds": 55.0 + cell["index"],
            "native_reward": {"reward": 1.0 if passed else 0.0},
            **({"e2e": {"strict_success": runner_strict}} if runner_strict is not None else {}),
            **(helper_fields or {}),
            "semantic_metrics": {
                "judgment_attempts": 1,
                "replan_requests": 0,
                "root_requests_consuming_feedback": 0,
                "false_completion_count": 0,
                "extra_lookup_count": extra_lookups,
                "wrong_target_lookup_count": 0,
                "rejected_lookup_count": 0,
                "lookup_attempt_count": 1,
                "judge_false_acceptance": False,
                "held_delivery": False,
                "repaired_success": False,
            },
        },
    )
    write_json(
        trial / "observation-check.json",
        {
            "observation_valid": True,
            "cache_complete": False,
            "source_reconciliation": {"reconciled": True},
        },
    )
    write_json(trial / "cleanup-observation.json", {"complete": True})
    write_json(trial / "replay-check.json", {"complete": True})


def _invalid_trial(phase_dir: Path, cell: dict[str, Any], *, started: datetime) -> None:
    trial = phase_dir / "trials" / cell["trial_name"]
    write_json(
        trial / "result.json",
        {
            "trial_name": cell["trial_name"],
            "task_name": cell["case_id"],
            "started_at": _iso(started),
            "finished_at": _iso(started + timedelta(seconds=9)),
            "verifier_result": None,
            "exception_info": {"exception_type": "EnvironmentStartTimeoutError"},
        },
    )
    write_json(
        trial / "trial-receipt.json",
        {
            **cell,
            "valid": False,
            "passed": False,
            "error_type": "missing_handoff_result",
            "execution_started": False,
            "host_elapsed_seconds": 9.0,
        },
    )


def build_phase(
    root: Path,
    *,
    mode: str = "incomplete",
    jev_judge_provider: str = "typesafe",
    repetition: int = 0,
    run_id: str = RUN_ID,
    failing: frozenset[tuple[str, str]] = frozenset(),
    cell_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    slots: bool = False,
    observed_judge_latency: bool = False,
    intent: bool = False,
    extra_lookups: frozenset[tuple[str, str]] = frozenset(),
    runner_strict: dict[tuple[str, str], bool] | None = None,
    helper_fields: dict[tuple[str, str], dict[str, bool]] | None = None,
) -> dict[str, Any]:
    """Write one closed phase.

    ``incomplete`` keeps one selected invalid cell and a not-measurable primary.
    ``complete`` makes all four cells valid with a measured primary.
    ``deselected`` is adversarial: the invalid cell is left unselected while the
    analysis still reports a measured primary against the frozen denominator.

    ``repetition`` names this phase's repeat (one run spec per repeat, 05 §2.2),
    ``failing`` lists ``(case_id, arm)`` cells whose task oracle fails, and
    ``cell_overrides`` edits frozen cell fields such as the repetition contract.
    ``slots`` starts both arms of a case together and writes private trial receipts
    (05 v2 §2.4); ``observed_judge_latency`` replaces the 0.0 placeholder latency.
    ``intent`` writes intent helper cells (no matched final verdict, 05 §3.1),
    ``extra_lookups`` gives listed cells one extra lookup, ``runner_strict``
    records a runner's strict_success and ``helper_fields`` the runner's observed
    helper admission, fallback and consumption in the trial receipt.
    """
    if mode not in {"incomplete", "complete", "deselected"}:
        raise ValueError("unknown fixture mode")
    phase_dir = root / "natural"
    phase_dir.mkdir(parents=True)
    spec = _run_spec()
    workload = ["inbox-a", "inbox-b"]
    spec["run_id"] = run_id
    spec["created_at"] = _iso(FROZEN_AT)
    spec["preregistration"].update(frozen_at=_iso(FROZEN_AT), live_test_approved=True)
    spec["study"]["primary_metric"] = {
        "name": "matched_noul_task_success_delta",
        "unit": "ratio",
        "direction": "target",
        "aggregation": "(Jev passed minus LLM passed) / 2 paired executions",
        "denominator": 2,
    }
    execution = spec["reproduction"]["execution"]
    execution.update(
        ordered_workload_ids=workload,
        workload_ids_sha256=_workload_hash(workload),
        repetitions=1,
        seed_schedule=[f"unseeded-provider-inference-repeat-{repetition}"],
    )
    spec["artifacts"] = {
        "native_results": "results.json",
        "trajectory": None,
        "verifier_receipts": None,
        "attempts": "attempts.jsonl",
        "analysis": "analysis.json",
        "publication_manifest": None,
    }
    write_json(phase_dir / "run-spec.json", spec)
    cells = copy.deepcopy(CELLS)
    for cell in cells:
        key = (cell["case_id"], cell["arm"])
        cell.update(
            repetition=repetition,
            trial_name=cell["trial_name"].replace("-r0-", f"-r{repetition}-"),
            **contract_fields(*key),
        )
        if intent:
            cell["verification_engine"] = None
            cell["intent_target_engine"] = "llm" if cell["arm"] == "a" else "jev"
        cell.update((cell_overrides or {}).get(key, {}))
    write_json(
        phase_dir / "freeze.json",
        {"phase": "natural", "source_revision": REVISION, "cells": cells},
    )
    attempts = []
    for cell in cells:
        slot = workload.index(cell["case_id"])
        started = FROZEN_AT + timedelta(minutes=5 + 2 * (slot if slots else cell["index"]))
        key = (cell["case_id"], cell["arm"])
        invalid = mode != "complete" and key == INVALID_CELL
        passed = key not in failing
        if invalid:
            _invalid_trial(phase_dir, cell, started=started)
        else:
            judge_provider = (
                jev_judge_provider if cell["verification_engine"] == "jev" else "openai"
            )
            # One Jev judge keeps the durable 0.0 duration placeholder for a missing latency.
            duration = 0.0 if cell["index"] == 1 and not observed_judge_latency else 432.4
            _trial(
                phase_dir,
                cell,
                started=started,
                judge_provider=judge_provider,
                judge_duration_ms=duration,
                passed=passed,
                extra_lookups=int(key in extra_lookups),
                runner_strict=(runner_strict or {}).get(key),
                helper_fields=(helper_fields or {}).get(key),
            )
        trial = phase_dir / "trials" / cell["trial_name"]
        refs = [
            {
                "kind": "native-result",
                "path": f"trials/{cell['trial_name']}/{name}",
                "sha256": _sha(trial / name),
            }
            for name in ("result.json", "trial-receipt.json")
        ]
        if slots:
            write_json(
                phase_dir / "private-receipts" / f"{run_id}-a{cell['index']:04}.json",
                _private_receipt(cell, f"{run_id}-a{cell['index']:04}", run_id),
            )
        attempts.append(
            {
                "schema_id": "geode.eval-attempt@1",
                "schema_version": 1,
                "run_id": run_id,
                "attempt_id": f"{run_id}-a{cell['index']:04}",
                "parent_attempt_id": None,
                "sequence": cell["index"],
                "timing": {
                    "status": "exact",
                    "started_at": _iso(started),
                    "finished_at": _iso(started + timedelta(seconds=60)),
                    "source_ref": None,
                },
                "validity": "invalid" if invalid else "valid",
                "outcome": "unknown" if invalid else "passed" if passed else "failed",
                "change": {
                    "surface": "natural",
                    "description": (
                        f"{cell['case_id']}, arm {cell['arm']}, repeat {repetition}; no retry"
                    ),
                },
                "expected_effect": "Fixture effect.",
                "observed_result": "Fixture observation.",
                "failure_class": "missing_handoff_result" if invalid else None,
                "error_ref": None,
                "evidence_refs": refs,
                "selected_for_analysis": not (mode == "deselected" and invalid),
            }
        )
    complete = mode == "complete"
    measured = mode in {"complete", "deselected"}
    primary = (
        {"value": 0.0, "numerator": 0, "denominator": 2}
        if measured
        else {"value": None, "numerator": None, "denominator": None}
    )
    results_ref = write_json(
        phase_dir / "results.json",
        {"phase": "natural", "complete": complete, "primary": primary, "actual_charge_usd": None},
    )
    aggregate_id = f"{run_id}-aggregate"
    aggregate_ref = {"kind": "native-result", **results_ref}
    finished = FROZEN_AT + timedelta(minutes=30)
    attempts.append(
        {
            **attempts[-1],
            "attempt_id": aggregate_id,
            "parent_attempt_id": attempts[-1]["attempt_id"],
            "sequence": len(attempts),
            "timing": {
                "status": "exact",
                "started_at": _iso(finished),
                "finished_at": _iso(finished),
                "source_ref": None,
            },
            "validity": "valid" if complete or measured else "invalid",
            "outcome": "mixed" if complete or measured else "unknown",
            "change": {"surface": "analysis-only", "description": "Deterministic aggregate."},
            "failure_class": None if complete or measured else "incomplete_planned_cells",
            "evidence_refs": [aggregate_ref],
            "selected_for_analysis": True,
        }
    )
    attempts_path = phase_dir / "attempts.jsonl"
    attempts_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in attempts), encoding="utf-8"
    )
    selected = [row for row in attempts if row["selected_for_analysis"]]
    write_json(
        phase_dir / "analysis.json",
        {
            "schema_id": "geode.eval-analysis@1",
            "schema_version": 1,
            "run_id": run_id,
            "analyzed_at": _iso(finished + timedelta(minutes=1)),
            "run_spec_sha256": _sha(phase_dir / "run-spec.json"),
            "attempts_sha256": _sha(attempts_path),
            "selected_attempt_ids": [row["attempt_id"] for row in selected],
            "answer": "Fixture analysis for offline data tools.",
            "metrics": [
                {
                    "name": "matched_noul_task_success_delta",
                    "value": primary["value"] if measured else "not-measurable",
                    "numerator": primary["numerator"],
                    "denominator": primary["denominator"],
                    "unit": "ratio",
                    "source_ref": "results.json",
                    "source_locator": {
                        "value": "/primary/value",
                        "numerator": "/primary/numerator",
                        "denominator": "/primary/denominator",
                    }
                    if measured
                    else None,
                }
            ],
            "decision": {
                "outcome": "diagnostic-only",
                "hypothesis_status": "mixed" if measured else "invalidated",
                "rationale": "Synthetic fixture; no model was called.",
            },
            "limitations": ["Synthetic fixture."],
            "evidence_refs": [ref for row in selected for ref in row["evidence_refs"]],
        },
    )
    return {"phase_dir": phase_dir, "cells": cells}
