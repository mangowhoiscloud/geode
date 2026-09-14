#!/usr/bin/env python3
"""Read-only, private-artifact checks; never execute a trial or grant admission.

Expected trial/task/bundle identities must come from the caller's frozen plan.
The run-spec schema does not own those additional native Harbor identities.
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
from pathlib import Path
from typing import Any

from core.observability.trajectory import (
    _digest_private_event_payload,
    verify_trajectory_integrity,
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
    usage: dict[str, Any], model: dict[str, Any], started: datetime, finished: datetime
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
        _require(
            row["model"] == model["label"]
            and row["provider"] == model["provider"]
            and row.get("source") in (None, model["route"]),
            "recorded attempt model/provider/route mismatch",
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
    path: Path, usage: dict[str, Any], sessions: set[str], full: dict[str, Any]
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
    fields = [
        "scope",
        "recorded_attempts",
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
) -> dict[str, Any]:
    """Validate existing exports, returning only bounded metadata and hashes.

    This is collection evidence, not task validity, provider-field completeness,
    publication approval, billing reconciliation, or permission to run another cell.
    Resource/time/retry/auth admission remains owned by the separate frozen preflight.
    """
    captured: dict[Path, bytes] = {}

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
        native["agent_info"]["name"] == "geode-runtime"
        and native["agent_info"]["version"] == revision,
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
        "verify_mode": "reflexion",
        "external_search_loop": False,
    }
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
        and metadata["verify_mode"] == "reflexion"
        and metadata["execution_started"] is True
        and metadata["finalization_errors"] == []
        and metadata["error_type"] == finalized.get("error_type"),
        "runtime result/finalization mismatch",
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
    accounting = _usage_check(usage, model, started, finished)
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
    for key in ("source", "trajectory_id", "runtime_event_refs"):
        _require(full.get(key) == digest.get(key), "canonical full/digest identity mismatch")
    projected = [
        {**event, "payload": _digest_private_event_payload(event["kind"], event["payload"])}
        for event in full["events"]
    ]
    _require(projected == digest["events"], "canonical full/digest projection mismatch")
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
        source_reconciliation = _reconcile_usage_source(source_db, usage, sessions, full)
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
    expected_atif["agent"].update(
        name="geode-runtime", tool_definitions=runtime["tool_definitions"]
    )
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
        "tool_calls": tools,
        "replay_status": "tool-actions-observed" if tools else "no-tool-action-observed",
        "accounting": accounting,
        "source_reconciliation": source_reconciliation,
        "timing": timing,
        "limits": [
            "physical dispatch coverage is not independently verified",
            *(
                []
                if source_reconciliation
                else ["export agreement only; raw hook payload hashes unverified"]
            ),
            "semantic reward does not authorize retries, execution, or publication",
            "resource/time limits, concurrency, retries and auth need separate frozen preflight",
            "caller must bind expected trial/task/bundle identities to its frozen plan",
            "model/provider/route checks bind requested adapter identity, not backend served model",
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
