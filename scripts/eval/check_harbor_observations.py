#!/usr/bin/env python3
"""Read-only, private-artifact checks; never execute a trial or grant admission.

Expected trial/task/bundle identities must come from the caller's frozen plan.
The run-spec schema does not own those additional native Harbor identities.
The handoff profile also requires an explicit arm and frozen task payload SHA.
An optional closed source database is opened immutable/read-only, never migrated.
Matching retained source rows is not a proof of all physical dispatches.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from core.llm.agentic_response import parse_tool_input
from core.observability.trajectory import (
    _digest_private_event_payload,
    verify_trajectory_integrity,
)
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL
from evals.benchmarks.decision_handoff_runtime import (
    INBOX_SYSTEM,
    _json_digest,
    handoff_call_coverage_complete,
)
from evals.platforms.harbor import (
    _RECORDING_RECEIPT_SCHEMA,
    _atif_trajectory_from_geode,
    _render_asciicast,
    _summarize_usage,
)
from scripts.eval.contract import _strict_json_loads, validate_run_spec

_COUNTERS = ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens")
_SCOPE_BLOCKER = "whole-runtime producer coverage not established"
_PURPOSES = {
    "agentic_loop",
    "turn_verification",
    "cognitive_reflection",
    "candidate_judge",
    "structured_decision",
    "text_completion",
    "context_compaction",
    "learning_extraction",
    "memory_dreaming",
    "context_exhaustion",
    "hosted_search",
}


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _time(value: Any) -> datetime:
    _require(
        isinstance(value, str)
        and re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", value)
        and not value.endswith("-00:00"),
        "timestamp missing/unknown/noncanonical offset",
    )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("timestamp malformed") from None
    _require(parsed.tzinfo is not None, "timestamp timezone missing")
    return parsed


def _harbor_model(module: str, name: str) -> Any:
    # Harbor remains optional; absence fails closed rather than bypassing its schema.
    return getattr(importlib.import_module(f"harbor.models.{module}"), name)


def _usage_check(
    usage: dict[str, Any],
    model: dict[str, Any],
    started: datetime,
    finished: datetime,
    *,
    handoff_arm: str | None = None,
    verification_engine: str | None = None,
) -> dict[str, Any]:
    _require(usage.get("whole_runtime_complete") is False, "unsupported whole-runtime usage claim")
    _require(usage.get("source_snapshot_complete") is True, "usage source snapshot incomplete")
    _require(usage.get("observation_status") == "no_known_faults", "usage observation degraded")
    _require(usage.get("known_sink_failure") is False, "usage sink health missing/degraded")
    _require(
        type(usage.get("mapping_anomaly_events")) is int and usage["mapping_anomaly_events"] == 0,
        "usage mapping anomalies",
    )
    _require(usage.get("attempt_pairing_complete") is True, "producer reports unpaired attempts")
    rows = usage.get("recorded_attempts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("no recorded LLM attempts")
    count = len(rows)
    for key in ("started_events", "call_events", "terminal_event_count"):
        _require(type(usage.get(key)) is int and usage[key] == count, "usage event count mismatch")
    _require(usage.get("recorded_attempts_timestamp_unit") == "unix-seconds-utc", "usage time unit")
    identities = []
    source_ids = []
    purposes: Counter[str] = Counter()
    efforts: Counter[str] = Counter()
    unknown_metadata = 0
    for row in rows:
        _require(isinstance(row, dict), "malformed recorded attempt")
        for field in (
            "session_id",
            "llm_call_id",
            "llm_attempt_id",
            "model",
            "provider",
            "adapter",
        ):
            _require(isinstance(row.get(field), str) and row[field], "missing attempt identity")
        identities.append((row["session_id"], row["llm_attempt_id"]))
        source_ids.append(row.get("source_event_id"))
        _require(type(source_ids[-1]) is int and source_ids[-1] >= 0, "missing source event ID")
        _require(
            isinstance(row.get("source_payload_hash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", row["source_payload_hash"]),
            "missing source payload hash",
        )
        timestamp = row.get("occurred_at")
        _require(
            type(timestamp) in (int, float)
            and math.isfinite(timestamp)
            and started.timestamp() <= timestamp <= finished.timestamp(),
            "invalid/out-of-trial usage timestamp",
        )
        _require(isinstance(row.get("usage"), dict), "recorded attempt usage missing")
        _require(
            all(k in row["usage"] for k in _COUNTERS), "usage counter key lost (not provider null)"
        )
        purpose = row.get("purpose")
        _require(
            purpose is None or (isinstance(purpose, str) and purpose in _PURPOSES),
            "unrecognized observed purpose",
        )
        purposes[purpose or "unknown"] += 1
        effort = row.get("effort")
        _require(
            effort is None
            or (
                isinstance(effort, str)
                and effort
                in {
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                    "ultra",
                }
            ),
            "unrecognized observed effort",
        )
        if handoff_arm is None:
            _require(
                row["model"] == model["label"]
                and row["provider"] == model["provider"]
                and row.get("source") in (None, model["route"]),
                "recorded attempt model/provider/route mismatch",
            )
        else:
            admitted_purposes = {"agentic_loop", "cognitive_reflection", "turn_verification"}
            if handoff_arm != "a0":
                admitted_purposes.add("structured_decision")
            _require(
                purpose in admitted_purposes,
                "handoff attempt purpose mismatch",
            )
            expected_route = (
                (JEV_MODEL, "typesafe", "payg", "none")
                if (handoff_arm == "b" and purpose == "structured_decision")
                or (verification_engine == "jev" and purpose == "turn_verification")
                else (model["label"], model["provider"], model["route"], model["reasoning"])
            )
            _require(
                (row["model"], row["provider"], row.get("source"), effort) == expected_route
                and row.get("response_model") == expected_route[0],
                "handoff observed model/provider/route/effort mismatch",
            )
        efforts[effort or ("not-configured" if purpose == "hosted_search" else "unknown")] += 1
        unknown_metadata += int(
            row.get("source") is None
            or purpose is None
            or (effort is None and purpose != "hosted_search")
        )
    _require(len(set(identities)) == count, "duplicate recorded attempt")
    _require(len(set(source_ids)) == count, "duplicate source event ID")
    counters = {}
    for field in _COUNTERS:
        values = [row["usage"].get(field) for row in rows]
        _require(
            all(v is None or (type(v) is int and v >= 0) for v in values), "invalid usage counter"
        )
        missing = values.count(None)
        observed = sum(v for v in values if v is not None)
        total = None if missing else observed
        _require(
            field in usage
            and type(usage[field]) is type(total)
            and usage[field] == total
            and type(usage.get(f"{field}_observed_sum")) is int
            and usage.get(f"{field}_observed_sum") == observed
            and type(usage.get(f"{field}_missing_events")) is int
            and usage.get(f"{field}_missing_events") == missing,
            "usage counter projection mismatch",
        )
        counters[field] = {"total": total, "observed_sum": observed, "missing_attempts": missing}
    return {
        "attempts": count,
        "purposes": dict(purposes),
        "observed_efforts": dict(efforts),
        "unknown_metadata_attempts": unknown_metadata,
        "counters": counters,
    }


def _reconcile_usage_source(
    path: Path,
    usage: dict[str, Any],
    sessions: set[str],
    full: dict[str, Any],
    *,
    native_verify: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare the complete retained source, not only the exported end IDs.

    A nonempty WAL needs custody-preserving checkpoint/recovery first; immutable
    reads must never silently ignore it. No credentials or payloads are returned.
    """
    from core.observability.event_store import _row_to_event
    from core.observability.session_timeline import _row_to_session_event
    from core.observability.trajectory import _session_trajectory_event, _trajectory_event

    _require(path.is_file(), "source database missing")
    _require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink source rejected")
    wal = path.with_name(path.name + "-wal")
    _require(not wal.is_symlink(), "symlink WAL rejected")
    _require(not wal.exists() or wal.stat().st_size == 0, "uncheckpointed source WAL")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        _require(db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "source database corrupt")
        rows = db.execute("SELECT * FROM hook_events ORDER BY occurred_at DESC, id DESC").fetchall()
        session_rows = db.execute("SELECT * FROM session_events ORDER BY id").fetchall()
    source_sessions = {row["session_id"] for row in session_rows}
    _require(source_sessions == sessions, "canonical source session inventory mismatch")
    source_events = []
    for ordinal, raw in enumerate(session_rows, 1):
        event = _row_to_session_event(raw)
        _require(not event.corrupt_payload, "source session payload hash mismatch")
        source_events.append(
            _trajectory_event(
                _session_trajectory_event(event),
                ordinal=ordinal,
                default_session_id="",
                fallback_occurred_at=full["captured_at"],
            )
        )
    _require(source_events == full["events"], "source/export canonical event mismatch")
    for row in rows:
        _require(
            hashlib.sha256(row["payload_json"].encode()).hexdigest() == row["payload_hash"],
            "source hook payload hash mismatch",
        )
    expected = _summarize_usage([_row_to_event(row) for row in rows])
    if native_verify is not None:
        verdicts = [
            {**event.payload, "action": event.action}
            for row in reversed(rows)
            for event in (_row_to_event(row),)
            if event.action in {"turn.verify.passed", "turn.verify.failed"}
        ]
        _require(verdicts == native_verify, "source/export native verification mismatch")
    # Producers may traverse the same retained rows in either chronological order.
    _require(
        sorted(usage["recorded_attempts"], key=lambda row: row["source_event_id"])
        == sorted(expected["recorded_attempts"], key=lambda row: row["source_event_id"]),
        "source/export usage mismatch",
    )
    fields = [
        "scope",
        "started_events",
        "terminal_event_count",
        "call_events",
        "usage_events",
        "attempt_pairing_complete",
        "mapping_anomaly_events",
    ]
    for counter in _COUNTERS:
        fields.extend((counter, f"{counter}_observed_sum", f"{counter}_missing_events"))
    _require(all(usage.get(k) == expected[k] for k in fields), "source/export usage mismatch")
    _require(
        hashlib.sha256(path.read_bytes()).hexdigest() == before, "source changed during validation"
    )
    _require(not wal.exists() or wal.stat().st_size == 0, "source WAL appeared during validation")
    return {
        "reconciled": True,
        "database_sha256": before,
        "hook_rows": len(rows),
        "session_rows": len(session_rows),
        "session_count": len(sessions),
        "scope": "retained-source-rows-to-export; not physical dispatch coverage",
    }


def _handoff_final_check(
    handoff: dict[str, Any], metadata: dict[str, Any], attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Require a performed semantic final check, separately from task correctness."""
    _require(
        handoff.get("effective_verify_mode")
        == metadata.get("effective_verify_mode")
        == "llm_judge",
        "handoff effective verifier missing/mismatched",
    )
    _require(handoff.get("valid") is True, "handoff execution is not admitted")
    judges = [row for row in attempts if row.get("purpose") == "turn_verification"]
    _require(
        judges and all(not row.get("error_type") for row in judges), "final judge missing/failed"
    )
    verdicts = handoff.get("native_verify")
    if (
        not isinstance(verdicts, list)
        or not verdicts
        or not all(
            isinstance(row, dict)
            and row.get("action") in {"turn.verify.passed", "turn.verify.failed"}
            for row in verdicts
        )
    ):
        raise ValueError("native final verification missing/malformed")
    native_passed = verdicts[-1]["action"] == "turn.verify.passed"
    _require(
        not native_passed or verdicts[-1].get("success") is True, "native pass is inconsistent"
    )
    oracle = handoff.get("oracle")
    if not isinstance(oracle, dict) or type(oracle.get("passed")) is not bool:
        raise ValueError("handoff oracle missing")
    passed = handoff.get("passed")
    _require(
        type(passed) is bool and passed == (native_passed and oracle["passed"]),
        "handoff success contradicts final verification/oracle",
    )
    _require(
        handoff.get("termination_reason") == metadata.get("termination_reason")
        and (
            not passed
            or (metadata.get("termination_reason") == "end_turn" and not metadata.get("error_type"))
        ),
        "failed/cancelled handoff cannot claim success",
    )
    return {
        "requested_verify_mode": metadata["verify_mode"],
        "effective_verify_mode": metadata["effective_verify_mode"],
        "judge_attempts": len(judges),
        "native_verdicts": len(verdicts),
        "native_passed": native_passed,
        "task_passed": passed,
    }


def _verification_check(
    evidence: dict[str, Any],
    *,
    engine: str,
    receipt: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    call_events: Any,
    trajectory: dict[str, Any],
    intervention_spec: dict[str, Any] | None = None,
    intervention_rows: Any = None,
) -> dict[str, int]:
    """Check call provenance and private-receipt consistency, not independent wire text.

    This frozen diagnostic rejects repeated logical call IDs, including recovered
    transport attempts. It does not disable the runtime's general retry facility.
    """
    from core.observability.redaction import redact_and_bound_text
    from evals.benchmarks.decision_verification import (
        _QUESTIONS,
        _REFLECTIONS,
        _Verdict,
        _VerificationState,
    )
    from evals.benchmarks.typesafe_decision import parse_choice_answers

    def indexed(rows: Any) -> dict[str, dict[str, Any]]:
        _require(isinstance(rows, list), "verification rows missing")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            _require(isinstance(row, dict), "verification row malformed")
            key = row.get("llm_call_id")
            _require(
                isinstance(key, str) and key and key not in result,
                "verification call identity; repeated logical calls are not admitted",
            )
            result[key] = row
        return result

    inputs = indexed(evidence.get("inputs"))
    judgments = indexed(evidence.get("judgments"))
    roots = indexed(evidence.get("root_outputs"))
    requests = indexed(evidence.get("root_requests"))
    observed = indexed(attempts)
    root_ids = [
        row["llm_call_id"]
        for row in receipt
        if row["kind"] == "root_request" and row.get("request_role") != "replan"
    ]
    judge_requests = [row for row in receipt if row["kind"] == "verification_request"]
    judge_ids = [row["llm_call_id"] for row in judge_requests]
    _require(
        list(inputs) == judge_ids
        and list(requests) == root_ids
        and list(roots) == [key for key in root_ids if not observed[key].get("error_type")]
        and list(judgments) == [key for key in judge_ids if not observed[key].get("error_type")],
        "verification request/completion coverage mismatch",
    )
    _require(isinstance(call_events, list), "verification native call events missing")
    terminals = {
        row["id"]: row
        for row in call_events
        if isinstance(row, dict) and row.get("action") == "llm.call.ended"
    }
    _require(
        len(terminals) == len(attempts)
        and len(terminals)
        == sum(
            isinstance(row, dict) and row.get("action") == "llm.call.ended" for row in call_events
        ),
        "verification native terminal inventory mismatch",
    )
    for attempt in attempts:
        terminal = terminals.get(attempt["source_event_id"])
        _require(
            terminal
            and terminal.get("llm_attempt_id") == attempt["llm_attempt_id"]
            and terminal.get("payload_hash") == attempt["source_payload_hash"]
            and _json_digest(terminal.get("payload")) == attempt["source_payload_hash"]
            and terminal["payload"].get("llm_call_id") == attempt["llm_call_id"],
            "verification native terminal source mismatch",
        )
    if intervention_spec is not None:
        _require(
            isinstance(intervention_rows, list) and len(intervention_rows) == 1,
            "verification intervention must occur exactly once",
        )
        intervention = intervention_rows[0]
        _require(isinstance(intervention, dict), "verification intervention row malformed")
        injected_id = intervention.get("llm_call_id")
        prefix = intervention.get("receipt_prefix_length")
        native_output = intervention.get("native")
        effective = intervention.get("effective")
        _require(
            injected_id in roots
            and type(prefix) is int
            and prefix
            == next(i + 1 for i, row in enumerate(receipt) if row.get("llm_call_id") == injected_id)
            and intervention.get("kind") == "controlled-candidate-replacement"
            and intervention.get("when") == intervention_spec.get("when")
            and isinstance(native_output, dict)
            and isinstance(native_output.get("text"), str)
            and isinstance(native_output.get("tool_uses"), list)
            and native_output.get("stop_reason") == "completed"
            and intervention.get("native_sha256") == _json_digest(native_output)
            and effective == {"text": intervention_spec.get("candidate_output"), "tool_uses": []}
            and intervention.get("effective_sha256") == _json_digest(effective)
            and roots[injected_id]["text"] == effective["text"]
            and roots[injected_id]["tool_uses"] == []
            and inputs
            and next(iter(inputs.values()))["candidate_call_id"] == injected_id,
            "verification intervention source/effective candidate mismatch",
        )
        terminal = terminals[observed[injected_id]["source_event_id"]]["payload"]
        _require(
            (intervention.get("response_id") or None) == (terminal.get("response_id") or None),
            "verification intervention native response mismatch",
        )
        prior_tools = [row for row in receipt[:prefix] if row["kind"] == "tool_result"]
        if intervention_spec.get("when") == "before_observation":
            _require(
                injected_id == root_ids[0] and not prior_tools, "premature candidate has evidence"
            )
        else:
            _require(
                intervention_spec.get("when") == "after_observation"
                and prior_tools
                and not native_output["tool_uses"],
                "contradicted candidate has no completed observation",
            )
    else:
        _require(intervention_rows is None, "unfrozen verification intervention")
    user_messages = [
        event["payload"].get("content")
        for event in trajectory["events"]
        if event["kind"] == "message.user"
    ]
    candidate_messages = [
        event["payload"].get("content")
        for event in trajectory["events"]
        if event["kind"] == "message.assistant"
    ]
    retained_candidates = {
        (event["payload"].get("candidate_sha256"), event["payload"].get("candidate_bytes"))
        for event in trajectory["events"]
        if event["kind"] in {"verification.decided", "verification.pending"}
    }
    _require(user_messages, "verification original request missing")
    tool_calls = {
        event["call_id"]: event["payload"]
        for event in trajectory["events"]
        if event["kind"] == "tool.called"
    }
    tool_results = {
        event["call_id"]: event["payload"].get("result")
        for event in trajectory["events"]
        if event["kind"] == "tool.completed"
    }
    traced_tools = [tool for root in roots.values() for tool in root["tool_uses"]]
    _require(
        len(traced_tools) == len(tool_calls)
        and {tool["id"] for tool in traced_tools} == tool_calls.keys()
        and all(
            tool["name"] == tool_calls[tool["id"]].get("tool")
            and (arguments := parse_tool_input(tool["input"])) is not None
            and _json_digest(arguments) == _json_digest(tool_calls[tool["id"]].get("arguments"))
            for tool in traced_tools
        )
        and all(
            row.get("result") == tool_results.get(row.get("tool_call_id"))
            for row in receipt
            if row["kind"] == "tool_result"
        ),
        "verification tool source mismatch",
    )
    for request in judge_requests:
        call_id = request["llm_call_id"]
        item = inputs[call_id]
        state = _VerificationState.model_validate(item.get("state")).model_dump()
        source_hash = _json_digest(state)
        prefix_length = item.get("receipt_prefix_length")
        _require(
            type(prefix_length) is int
            and prefix_length == receipt.index(request) + 1
            and state["task_contract"] == INBOX_SYSTEM
            and state["original_request"] == user_messages[0]
            and item.get("state_sha256") == source_hash,
            "verification input/source digest mismatch",
        )
        preceding_roots = [
            row["llm_call_id"]
            for row in receipt[:prefix_length]
            if row["kind"] == "root_request" and row.get("request_role") != "replan"
        ]
        candidate_id = item.get("candidate_call_id")
        _require(
            preceding_roots
            and candidate_id == preceding_roots[-1]
            and candidate_id in roots
            and roots[candidate_id].get("tool_uses") == []
            and isinstance(roots[candidate_id].get("text"), str)
            and state["candidate_output"] == roots[candidate_id]["text"].strip()
            and (
                state["candidate_output"] in candidate_messages
                or (
                    hashlib.sha256(roots[candidate_id]["text"].encode()).hexdigest(),
                    len(roots[candidate_id]["text"].encode()),
                )
                in retained_candidates
            ),
            "verification candidate source mismatch",
        )
        results = {
            row["tool_call_id"]: row["result"]
            for row in receipt[:prefix_length]
            if row["kind"] == "tool_result"
        }
        observations = [
            {
                "tool_call_id": tool["id"],
                "tool": tool["name"],
                "input": tool["input"],
                "result": results.get(tool["id"]),
            }
            for root_id in preceding_roots
            for tool in roots[root_id]["tool_uses"]
        ]
        _require(state["tool_observations"] == observations, "verification tool evidence mismatch")
        if call_id not in judgments:
            continue  # A transport failure has no completed verdict or recovered usage.
        judgment = judgments[call_id]
        native = terminals[observed[call_id]["source_event_id"]]["payload"]
        _require(
            judgment.get("engine") == engine
            and judgment.get("step_id") == request.get("step_id")
            and judgment.get("input_sha256") == judgment.get("source_sha256") == source_hash
            and judgment.get("question_sha256") == _json_digest(_QUESTIONS)
            and all(
                judgment.get(key) == observed[call_id].get(key)
                for key in ("model", "provider", "source")
            )
            and all(
                judgment.get(key) == (native.get(key) or None)
                for key in ("response_id", "response_model", "response_provider")
            )
            and isinstance(judgment.get("raw_answer_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", judgment["raw_answer_sha256"]),
            "verification judgment/native response mismatch",
        )
        raw_answer = judgment.get("raw_answer")
        retention = judgment.get("raw_answer_retention")
        if retention == "complete":
            _require(
                isinstance(raw_answer, str)
                and hashlib.sha256(raw_answer.encode()).hexdigest()
                == judgment["raw_answer_sha256"],
                "verification raw answer digest mismatch",
            )
        else:
            _require(
                retention in {"omitted_sensitive", "omitted_oversize"}
                and raw_answer is None
                and judgment.get("accepted") is False,
                "verification omitted answer was admitted",
            )
        if judgment.get("accepted") is False:
            _require(
                judgment.get("error_type") == "invalid_verifier_response"
                and all(
                    judgment.get(key) is None
                    for key in ("verdict", "native_answer", "projected_payload", "feedback_sha256")
                ),
                "verification rejection fabricated a verdict",
            )
            continue
        _require(judgment.get("accepted") is True, "verification admission missing")
        if not isinstance(raw_answer, str):
            raise ValueError("verification admitted answer has no retained text")
        if engine == "jev":
            answer = parse_choice_answers(raw_answer, _QUESTIONS)
            verdict = answer["verdict"]["choice"]
            native_answer = answer["verdict"]
        else:
            verdict = _Verdict.model_validate_json(raw_answer).verdict
            native_answer = {"verdict": verdict}
        projected = {
            "passed": verdict == "supported",
            "score": float(verdict == "supported"),
            "reflection": _REFLECTIONS[verdict],
        }
        _require(
            judgment.get("verdict") == verdict
            and _json_digest(judgment.get("native_answer")) == _json_digest(native_answer)
            and judgment.get("error_type") is None
            and _json_digest(judgment.get("projected_payload")) == _json_digest(projected)
            and judgment.get("feedback_sha256") == _json_digest(projected),
            "verification native/projected decision mismatch",
        )
    for call_id, root_request in requests.items():
        prior = receipt[
            : next(i for i, row in enumerate(receipt) if row.get("llm_call_id") == call_id)
        ]
        completed = [
            judgments[row["llm_call_id"]]
            for row in prior
            if row["kind"] == "verification_request" and row["llm_call_id"] in judgments
        ]
        _require(
            type(root_request.get("completed_judgments")) is int
            and root_request["completed_judgments"] == len(completed)
            and isinstance(root_request.get("system_prompt"), str),
            "verification root request lineage mismatch",
        )
        consumed = []
        if (
            completed
            and completed[-1]["accepted"]
            and not completed[-1]["projected_payload"]["passed"]
        ):
            latest = completed[-1]
            reflection = latest["projected_payload"]["reflection"]
            feedback = "\n".join(
                f"{key}: {redact_and_bound_text(reflection[key], 400)}"
                for key in ("observation", "lesson", "next_check")
            )
            if escape(feedback, quote=False) in root_request["system_prompt"]:
                consumed.append(
                    {
                        "judge_call_id": latest["llm_call_id"],
                        "feedback_sha256": latest["feedback_sha256"],
                    }
                )
        _require(
            root_request.get("consumed_feedback") == consumed, "verification feedback mismatch"
        )
    return {
        "inputs": len(inputs),
        "completed_judgments": len(judgments),
        "root_requests": len(requests),
        "omitted_native_answers": sum(
            row["raw_answer_retention"] != "complete" for row in judgments.values()
        ),
    }


def validate_observations(
    trial_dir: Path,
    *,
    run_spec_path: Path,
    run_spec_sha256: str,
    source_sha256: str,
    trial_name: str,
    task_name: str,
    task_checksum: str,
    require_uniform_effort: bool = False,
    source_db: Path | None = None,
    handoff_arm: str | None = None,
    handoff_case_sha256: str | None = None,
    expected_verify_mode: str | None = None,
    expected_effective_verify_mode: str | None = None,
    verification_engine: str | None = None,
) -> dict[str, Any]:
    """Validate existing exports, returning only bounded metadata and hashes.

    This is collection evidence, not task validity, provider-field completeness,
    publication approval, billing reconciliation, or permission to run another cell.
    Resource/time/retry/auth admission remains owned by the separate frozen preflight.
    """
    captured: dict[Path, bytes] = {}
    _require(
        (handoff_arm is None and handoff_case_sha256 is None)
        or (
            handoff_arm in ("a0", "a", "b")
            and isinstance(handoff_case_sha256, str)
            and re.fullmatch(r"[a-f0-9]{64}", handoff_case_sha256)
        ),
        "handoff arm and frozen case SHA must be supplied together",
    )
    agent_name = "geode-handoff" if handoff_arm is not None else "geode-runtime"
    _require(
        expected_effective_verify_mode in (None, "llm_judge")
        and (
            expected_effective_verify_mode is None
            or (handoff_arm is not None and source_db is not None)
        ),
        "effective handoff verifier requires its closed source database",
    )
    _require(
        verification_engine in (None, "llm", "jev")
        and (verification_engine is None or handoff_arm == "a0"),
        "matched verification requires an explicit lookup-only handoff arm",
    )
    _require(
        expected_verify_mode in (None, "llm_judge", "reflexion")
        and (handoff_arm is None or expected_verify_mode is None),
        "expected verifier is only configurable for the native judgment profile",
    )
    # Preserve the frozen historical checker default; new native runs pin llm_judge.
    verify_mode = "rule_based" if handoff_arm is not None else (expected_verify_mode or "reflexion")
    if verification_engine is not None:
        verify_mode = "llm_judge"
    handoff_tools = (
        ["lookup_order_status"]
        if handoff_arm == "a0"
        else ["analyze_request", "lookup_order_status"]
    )

    def read(path: Path) -> bytes:
        _require(
            not any(p.is_symlink() for p in (path, *path.parents)), "symlink evidence rejected"
        )
        raw = path.read_bytes()
        _require(raw, "empty evidence file")
        captured[path] = raw
        return raw

    def document(relative: str) -> dict[str, Any]:
        value = _strict_json_loads(read(trial_dir / relative).decode(), label="trial evidence")
        if not isinstance(value, dict):
            raise ValueError("evidence must be a JSON object")
        return value

    spec_bytes = read(run_spec_path)
    _require(hashlib.sha256(spec_bytes).hexdigest() == run_spec_sha256, "run-spec SHA mismatch")
    spec = validate_run_spec(run_spec_path)
    registration = spec["preregistration"]
    _require(
        registration["mode"] == "prospective" and registration["status"] == "frozen",
        "a frozen prospective spec is required",
    )
    reproduction = spec["reproduction"]
    revision = reproduction["geode"]["revision"]
    model = reproduction["model"]
    if handoff_arm is not None:
        _require(
            model
            == {
                "label": ROOT_MODEL,
                "provider": "openai",
                "route": "subscription",
                "reasoning": "xhigh",
            },
            "handoff requires the frozen Astra subscription/xhigh root model",
        )
    _require(reproduction["geode"]["dirty"] is False, "dirty source is not frozen")
    _require(re.fullmatch(r"[a-f0-9]{40}", revision), "invalid source revision")
    _require(re.fullmatch(r"[a-f0-9]{64}", source_sha256), "invalid bundle SHA")
    _require(trial_dir.name == trial_name, "unexpected trial directory")
    native = document("result.json")
    _harbor_model("trial.result", "TrialResult").model_validate(native)
    _require(
        native["trial_name"] == trial_name
        and native["task_name"] == task_name
        and native["task_checksum"] == task_checksum,
        "native trial/task identity mismatch",
    )
    _require(
        native["agent_info"]["name"] == agent_name and native["agent_info"]["version"] == revision,
        "native agent identity mismatch",
    )
    started, finished = _time(native["started_at"]), _time(native["finished_at"])
    _require(_time(registration["frozen_at"]) <= started <= finished, "trial predates freeze/end")
    contract = document("agent/runtime-contract.json")
    expected = {
        "source_revision": revision,
        "source_sha256": source_sha256,
        "model": model["label"],
        "source": model["route"],
        "effort": model["reasoning"],
        "verify_mode": verify_mode,
        "external_search_loop": False,
    }
    if handoff_arm is not None:
        expected.update(
            runtime="evals.benchmarks.decision_handoff_runtime:run_arm",
            profile="decision-handoff",
            arm=handoff_arm,
            case_sha256=handoff_case_sha256,
        )
        _require(contract.get("required_tools") == handoff_tools, "handoff tool contract mismatch")
        _require(
            contract.get("verification_engine") == verification_engine,
            "handoff verification treatment mismatch",
        )
        if verification_engine is not None:
            _require(contract.get("workload_profile") == "inbox", "matched verifier requires inbox")
    _require(all(contract.get(k) == v for k, v in expected.items()), "runtime contract mismatch")
    _require(not contract.get("finalization_errors"), "host finalization failed")
    finalized = document("agent/runtime-finalized.json")
    _require(
        finalized.get("exports_complete") is True
        and finalized.get("status") == "finalized"
        and finalized.get("execution_started") is True
        and finalized.get("finalization_errors") == [],
        "native finalization incomplete",
    )
    runtime = document("agent/runtime-result.json")
    metadata = runtime["metadata"]
    _require(
        metadata["source_revision"] == revision
        and metadata["verify_mode"] == verify_mode
        and metadata["execution_started"] is True
        and metadata["finalization_errors"] == []
        and metadata["error_type"] == finalized.get("error_type"),
        "runtime result/finalization mismatch",
    )
    if handoff_arm is not None:
        _require(
            metadata.get("profile") == "decision-handoff"
            and metadata.get("arm") == handoff_arm
            and metadata.get("verification_engine") == verification_engine,
            "handoff runtime profile/arm mismatch",
        )
        definitions = runtime.get("tool_definitions")
        _require(
            isinstance(definitions, list)
            and len(definitions) == len(handoff_tools)
            and all(
                isinstance(tool, dict) and isinstance(tool.get("name"), str) for tool in definitions
            )
            and sorted(tool.get("name", "") for tool in definitions) == sorted(handoff_tools),
            "handoff runtime tool definitions mismatch",
        )
    usage = runtime["usage"]
    _require(metadata["usage"] == usage, "runtime usage metadata mismatch")
    context = native["agent_result"]
    _require(context["metadata"] == metadata, "Harbor lost/stale runtime metadata")
    _require(
        all(
            context.get(k) is None
            for k in ("n_input_tokens", "n_output_tokens", "n_cache_tokens", "cost_usd")
        ),
        "unsupported whole-runtime Harbor totals",
    )
    accounting = _usage_check(
        usage,
        model,
        started,
        finished,
        handoff_arm=handoff_arm,
        verification_engine=verification_engine,
    )
    final_verification = None
    if handoff_arm is not None:
        handoff = document("agent/handoff-result.json")
        _require(
            handoff.get("session_id") == metadata["geode_session_id"]
            and handoff.get("usage") == usage
            and handoff.get("handoff_call_coverage_complete") is True,
            "handoff result call coverage missing/inconsistent",
        )
        receipt = json.loads(read(trial_dir / "agent/handoff.json"))
        _require(handoff.get("verification_engine") == verification_engine, "judge result mismatch")
        _require(
            isinstance(receipt, list)
            and all(isinstance(row, dict) for row in receipt)
            and handoff_call_coverage_complete(receipt, usage["recorded_attempts"]),
            "handoff dispatch/attempt coverage mismatch",
        )
        if expected_effective_verify_mode is not None:
            final_verification = _handoff_final_check(handoff, metadata, usage["recorded_attempts"])
    uniform_effort = (
        accounting["observed_efforts"] == {model["reasoning"]: accounting["attempts"]}
        and accounting["unknown_metadata_attempts"] == 0
    )
    if require_uniform_effort:
        _require(uniform_effort, "recorded calls do not all match the frozen reasoning effort")
    accounting["uniform_requested_effort"] = uniform_effort
    full = document("agent/geode-trajectory.private.json")
    digest = document("agent/geode-trajectory.json")
    for trajectory in (full, digest):
        integrity = verify_trajectory_integrity(trajectory)
        _require(integrity["scope_complete"], "canonical scope incomplete")
        _require(trajectory["outcome"] == metadata, "canonical outcome metadata mismatch")
        _require(
            trajectory["source"]["session"] == metadata["geode_session_id"], "session mismatch"
        )
        for event in trajectory["events"]:
            _require(
                started <= _time(event["occurred_at"]) <= finished, "event outside trial interval"
            )
            if handoff_arm is not None and event["kind"] in {"tool.called", "tool.completed"}:
                _require(
                    event["payload"].get("tool") in handoff_tools,
                    "handoff observed tool outside frozen profile",
                )
    for key in ("source", "trajectory_id", "runtime_event_refs"):
        _require(full.get(key) == digest.get(key), "canonical full/digest identity mismatch")
    projected = [
        {**event, "payload": _digest_private_event_payload(event["kind"], event["payload"])}
        for event in full["events"]
    ]
    _require(projected == digest["events"], "canonical full/digest projection mismatch")
    verification = None
    if verification_engine is not None:
        intervention_spec = contract.get("verification_intervention")
        _require(
            handoff.get("verification_intervention") == intervention_spec,
            "verification intervention contract/result mismatch",
        )
        intervention_path = trial_dir / "agent/intervention.json"
        intervention_rows = (
            _strict_json_loads(read(intervention_path).decode(), label="verification intervention")
            if intervention_path.exists()
            else None
        )
        verification = _verification_check(
            document("agent/verification.json"),
            engine=verification_engine,
            receipt=json.loads(captured[trial_dir / "agent/handoff.json"]),
            attempts=usage["recorded_attempts"],
            call_events=_strict_json_loads(
                read(trial_dir / "agent/call-events.json").decode(), label="native call events"
            ),
            trajectory=full,
            intervention_spec=intervention_spec,
            intervention_rows=intervention_rows,
        )
    # The ATIF projector keys results by this exact triple, not bare call_id.
    for kind in ("tool.called", "tool.completed"):
        identities = [
            (event["session_id"], event["turn_id"], event["call_id"])
            for event in full["events"]
            if event["kind"] == kind
        ]
        _require(len(set(identities)) == len(identities), "ambiguous canonical tool identity")
    sessions = {event["session_id"] for event in full["events"]}
    for session in sessions:
        last = [event for event in full["events"] if event["session_id"] == session][-1]
        _require(
            session
            and last["kind"] == "session.ended"
            and not last["payload"].get("record_failures")
            and last["payload"].get("runtime_observation_status") == "no_known_faults",
            "canonical session not closed cleanly",
        )
    _require(
        all(row["session_id"] in sessions for row in usage["recorded_attempts"]),
        "usage session absent from canonical trajectory",
    )
    source_reconciliation = None
    if source_db is not None:
        # The database belongs to this exact isolated trial, not a host-wide store.
        _require(source_db.resolve().is_relative_to(trial_dir.resolve()), "source outside trial")
        read(source_db)
        source_reconciliation = _reconcile_usage_source(
            source_db,
            usage,
            sessions,
            full,
            native_verify=handoff["native_verify"] if final_verification is not None else None,
        )
    atif = document("agent/trajectory.json")
    atif_model = _harbor_model("trajectories", "Trajectory")
    expected_atif = _atif_trajectory_from_geode(
        full,
        model=model["label"],
        provider=model["provider"],
        source=model["route"],
        effort=None,
        version=revision,
        metrics={},
    )
    expected_atif["agent"].update(name=agent_name, tool_definitions=runtime["tool_definitions"])
    expected_atif["extra"]["configured_root_effort"] = model["reasoning"]
    _require(
        atif_model.model_validate(atif).to_json_dict()
        == atif_model.model_validate(expected_atif).to_json_dict(),
        "ATIF differs from native canonical projection",
    )
    cast = read(trial_dir / "agent/recording.cast")
    rendered, timing = _render_asciicast(atif)
    _require(cast == rendered.encode(), "recording differs from ATIF reconstruction")
    receipt = document("agent/recording.receipt.json")
    _require(
        receipt["schema_id"] == _RECORDING_RECEIPT_SCHEMA
        and receipt["recording_kind"] == "trajectory-reconstruction"
        and receipt["score_authority"] is False
        and all(type(receipt["timing"].get(k)) is int for k in timing)
        and receipt["timing"] == timing,
        "recording receipt contract mismatch",
    )
    _require(
        receipt["source"]
        == {
            "path": "trajectory.json",
            "sha256": hashlib.sha256(captured[trial_dir / "agent/trajectory.json"]).hexdigest(),
            "schema_version": atif["schema_version"],
            "trajectory_id": atif["trajectory_id"],
        }
        and receipt["output"]
        == {
            "path": "recording.cast",
            "sha256": hashlib.sha256(cast).hexdigest(),
            "format": "asciicast-v2",
        },
        "recording receipt hash/identity mismatch",
    )
    _time(receipt["generated_at"])
    tools = full["integrity"]["quality"]["tool_pairing"]["calls"]
    cache_complete = all(accounting["counters"][k]["total"] is not None for k in _COUNTERS[:3])
    for path, raw in captured.items():
        _require(path.read_bytes() == raw, "evidence changed during validation")
    return {
        "observation_valid": True,
        "cache_complete": cache_complete,
        "whole_runtime_complete": False,
        "full_runtime_expansion_ready": False,
        "blockers": [
            _SCOPE_BLOCKER,
            *([] if cache_complete else ["provider counter coverage incomplete"]),
        ],
        "run_id": spec["run_id"],
        "run_spec_sha256": run_spec_sha256,
        "source_revision": revision,
        "source_sha256": source_sha256,
        "trial_name": trial_name,
        "task_name": task_name,
        "task_checksum": task_checksum,
        **(
            {"handoff_arm": handoff_arm, "handoff_case_sha256": handoff_case_sha256}
            if handoff_arm is not None
            else {}
        ),
        "tool_calls": tools,
        "replay_status": "tool-actions-observed" if tools else "no-tool-action-observed",
        "accounting": accounting,
        "source_reconciliation": source_reconciliation,
        **({"final_verification": final_verification} if final_verification is not None else {}),
        **({"verification": verification} if verification is not None else {}),
        "timing": timing,
        "limits": [
            "physical dispatch coverage is not independently verified",
            *(
                [
                    "matched native answers are checked inside the digest-bound private receipt; "
                    "the durable database does not independently retain their response text",
                    "matched diagnostics reject repeated logical calls and errored attempts; "
                    "this does not disable runtime retry functionality",
                ]
                if verification_engine is not None
                else []
            ),
            *(
                []
                if source_reconciliation
                else ["export agreement only; raw hook payload hashes unverified"]
            ),
            "semantic reward does not authorize retries, execution, or publication",
            "resource/time limits, concurrency, retries and auth need separate frozen preflight",
            "caller must bind expected trial/task/bundle identities to its frozen plan",
            (
                "response-reported model identity does not independently verify backend execution"
                if handoff_arm is not None
                else "model/provider/route checks bind requested adapter identity, "
                "not backend served model"
            ),
        ],
        "artifact_sha256": {
            str(path.relative_to(trial_dir)): hashlib.sha256(raw).hexdigest()
            for path, raw in captured.items()
            if path != run_spec_path
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("--run-spec", required=True, type=Path, dest="run_spec_path")
    parser.add_argument(
        "--source-db", type=Path, help="closed, checkpointed trial-local source database"
    )
    parser.add_argument(
        "--require-uniform-effort",
        action="store_true",
        help="reject missing or different request effort on any recorded root/auxiliary call",
    )
    parser.add_argument("--handoff-arm", choices=("a0", "a", "b"))
    parser.add_argument("--verification-engine", choices=("llm", "jev"))
    parser.add_argument(
        "--expected-effective-verify-mode",
        choices=("llm_judge",),
        help=(
            "current handoff final-check contract; requires --source-db; "
            "omitted preserves historical evidence"
        ),
    )
    parser.add_argument(
        "--expected-verify-mode",
        choices=("llm_judge", "reflexion"),
        help="native profile's frozen verifier; omitted preserves historical reflexion receipts",
    )
    parser.add_argument(
        "--handoff-case-sha256", help="task payload SHA from the frozen handoff plan"
    )
    for name in ("run-spec-sha256", "source-sha256", "trial-name", "task-name", "task-checksum"):
        parser.add_argument(f"--{name}", required=True)
    try:
        report = validate_observations(**vars(parser.parse_args(argv)))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ImportError,
        AttributeError,
        sqlite3.Error,
    ) as error:
        # Validation exceptions can embed private task/model content. Never print them.
        print(
            json.dumps(
                {
                    "observation_valid": False,
                    "full_runtime_expansion_ready": False,
                    "error_type": type(error).__name__,
                }
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 2  # Known scope gap remains an expansion blocker, even for healthy exports.


if __name__ == "__main__":
    raise SystemExit(main())
