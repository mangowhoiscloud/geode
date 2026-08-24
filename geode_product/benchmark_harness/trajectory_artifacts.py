"""Shared GEODE trajectory bridge for third-party benchmark harnesses.

Benchmark-native receipts remain byte-for-byte authoritative for their
verifiers. This module adds a schema-validated GEODE view beside them and
binds that view back to canonical ``sessions.db:session_events`` rows.
Keeping the bridge outside the tau2 candidate runner also prevents publication
machinery from enlarging Crucible's behavior-mutation surface.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import shutil
from collections.abc import Awaitable, Mapping, Sequence
from pathlib import Path
from typing import Any

_ADAPTER_ID = "geode_product.benchmark_harness.trajectory_artifacts"


async def _await_close(outcome: Awaitable[Any]) -> None:
    await outcome


def close_benchmark_session(loop: Any, *, success: bool) -> None:
    """Close a sync benchmark participant through GEODE's async lifecycle."""
    suffix = "completed" if success else "error"
    async_close = getattr(loop, f"amark_session_{suffix}", None)
    if callable(async_close):
        outcome = async_close()
        if inspect.isawaitable(outcome):
            asyncio.run(_await_close(outcome))
            return
    sync_close = getattr(loop, f"mark_session_{suffix}", None)
    if callable(sync_close):
        sync_close()


def geode_session_trace(loop: Any) -> dict[str, str]:
    """Return the lineage field injected into benchmark-native message rows."""
    return {"geode_session_id": str(getattr(loop, "_session_id", "") or "")}


def tau2_session_ids(results: Mapping[str, Any]) -> list[str]:
    """Read GEODE lineage from finalized tau2 messages in first-seen order."""
    session_ids: list[str] = []
    simulations = results.get("simulations")
    if not isinstance(simulations, list):
        return session_ids
    for simulation in simulations:
        if not isinstance(simulation, Mapping):
            continue
        messages = simulation.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            raw_data = message.get("raw_data")
            if not isinstance(raw_data, Mapping):
                continue
            session_id = str(raw_data.get("geode_session_id") or "")
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)
    return session_ids


def geode_trajectory_snapshot_path(snapshot_dir: Path, run_id: str) -> Path:
    """Return the normalized sidecar path without touching native receipts."""
    return snapshot_dir / f"{_slug(run_id)}.geode-trajectory.json"


def tau2_trajectory_snapshot_paths(snapshot_dir: Path, run_id: str) -> tuple[Path, Path]:
    """Return the native receipt and commit-marker paths for one tau2 run."""
    slug = _slug(run_id)
    return snapshot_dir / f"{slug}.trajectory.json", snapshot_dir / f"{slug}.snapshot.json"


def write_tau2_trajectory_snapshot(
    *,
    results_path: Path,
    snapshot_dir: Path,
    run_id: str,
    metadata: Mapping[str, Any],
    companion_artifacts: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[Path, Path]:
    """Atomically publish a tau2 receipt, GEODE view, and commit marker.

    The native receipt remains authoritative. The normalized GEODE sidecar is
    best-effort so a schema-adapter defect cannot destroy tau2's verifier
    evidence; its status and error are recorded in the commit marker.
    """
    trajectory_path, snapshot_path = tau2_trajectory_snapshot_paths(snapshot_dir, run_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stage_dir = snapshot_dir / f".{_slug(run_id)}.stage-{os.getpid()}"
    stage_dir.mkdir(parents=False, exist_ok=False)
    normalized_path = geode_trajectory_snapshot_path(snapshot_dir, run_id)
    try:
        staged_trajectory = stage_dir / trajectory_path.name
        staged_snapshot = stage_dir / snapshot_path.name
        staged_normalized = stage_dir / normalized_path.name
        shutil.copy2(results_path, staged_trajectory)
        raw_artifact_sha256 = hashlib.sha256(staged_trajectory.read_bytes()).hexdigest()
        try:
            export_tau2_trajectory(
                results_path=results_path,
                destination=staged_normalized,
                run_id=run_id,
                raw_artifact_sha256=raw_artifact_sha256,
                metadata=metadata,
                companion_artifacts=companion_artifacts,
            )
            normalized_status = "written"
            normalized_error = None
            normalized_sha256 = hashlib.sha256(staged_normalized.read_bytes()).hexdigest()
        except Exception as exc:
            normalized_status = "failed"
            normalized_error = str(exc)
            normalized_sha256 = None
        snapshot = {
            "schema": "crucible_tau2_trajectory_snapshot.v4",
            "filename_convention": {
                "run_id": (
                    "crucible-tau2-<stage>-<domain>-<arm>-"
                    "<agent_route>-<user_route>-n<tasks>k<trials>-<yyyymmdd>-<seq>"
                ),
                "trajectory": "<run-id>.trajectory.json",
                "runtime_profile": "<run-id>.runtime-profile.json",
                "attempt_manifest": "<run-id>.attempt-manifest.json",
                "snapshot": "<run-id>.snapshot.json",
            },
            "run_id": run_id,
            "raw_results": str(results_path),
            "trajectory_snapshot": str(trajectory_path),
            "raw_artifact_sha256": raw_artifact_sha256,
            "geode_trajectory": (str(normalized_path) if normalized_status == "written" else None),
            "geode_trajectory_sha256": normalized_sha256,
            "geode_trajectory_status": normalized_status,
            "geode_trajectory_error": normalized_error,
            "snapshot_metadata": str(snapshot_path),
            "runtime_profile_artifact": dict(
                (companion_artifacts or {}).get("runtime_profile", {})
            ),
            "attempt_manifest_artifact": dict(
                (companion_artifacts or {}).get("attempt_manifest", {})
            ),
            **metadata,
        }
        staged_snapshot.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(staged_trajectory, trajectory_path)
        if staged_normalized.exists():
            os.replace(staged_normalized, normalized_path)
        # Metadata is the commit marker and is published last.
        os.replace(staged_snapshot, snapshot_path)
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    return trajectory_path, snapshot_path


def export_tau2_trajectory(
    *,
    results_path: Path,
    destination: Path,
    run_id: str,
    raw_artifact_sha256: str,
    metadata: Mapping[str, Any],
    companion_artifacts: Mapping[str, Mapping[str, str]] | None = None,
) -> Path:
    """Project a tau2 receipt through GEODE's shared trajectory validator."""
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions

    results = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(results, dict):
        raise ValueError("tau2 results must be an object")
    simulations = results.get("simulations")
    simulation_rows = simulations if isinstance(simulations, list) else []
    session_ids = tau2_session_ids(results)
    evidence_refs: list[dict[str, Any]] = [
        {
            "kind": "native_receipt",
            "schema_id": "tau2.results@native",
            "reference": raw_artifact_sha256,
            "raw_artifact_sha256": raw_artifact_sha256,
            "authority": "tau2 native results receipt",
        }
    ]
    contract_id = str(metadata.get("experiment_contract_id") or "")
    if contract_id and metadata.get("contract_validation") == "identity_preflight":
        evidence_refs.append(
            {
                "kind": "crucible_evidence",
                "schema_id": "crucible_tau2_trajectory_snapshot.v4",
                "reference": contract_id,
                "contract_id": contract_id,
                "arm": metadata.get("arm"),
                "raw_artifact_sha256": raw_artifact_sha256,
                "authority": "Crucible experiment contract and executable verifier",
            }
        )
    trajectory = trajectory_from_sessions(
        session_ids,
        trajectory_id=f"tau2-{_slug(run_id)}",
        source={
            "harness": "tau2-bench",
            "run": run_id,
            "session": run_id,
            "parents": session_ids,
            "runtime_profile_sha256": (companion_artifacts or {})
            .get("runtime_profile", {})
            .get("sha256"),
            "attempt_manifest_sha256": (companion_artifacts or {})
            .get("attempt_manifest", {})
            .get("sha256"),
        },
        outcome={
            "execution_status": metadata.get("execution_status"),
            "failure_class": metadata.get("failure_class"),
            "simulation_count": len(simulation_rows),
            "domain": metadata.get("domain"),
            "arm": metadata.get("arm"),
        },
        provenance={
            "adapter": _ADAPTER_ID,
            "native_schema": "tau2 results.json",
            "native_results": results_path.name,
            "store": "sessions.db:session_events",
        },
        privacy={
            "review_state": "local",
            "native_results_embedded": False,
            "payloads": "redacted and bounded by SessionEventStore",
        },
        artifact_digests=[
            {"path": results_path.name, "sha256": raw_artifact_sha256},
            *[
                dict(reference)
                for reference in (companion_artifacts or {}).values()
                if reference.get("path") and reference.get("sha256")
            ],
        ],
        evidence_refs=evidence_refs,
        content_policy="digest",
        trajectory_class=("benchmark", "dialogue", "tool", "lifecycle"),
    )
    return export_trajectory(destination, trajectory)


def export_mcpmark_trajectory(
    *,
    loop: Any,
    instruction: str,
    result: Any,
    tool_call_log_file: str,
    model: str,
    provider: str,
    source: str,
    effort: str,
    action_timed_out: bool = False,
) -> Path:
    """Export one MCPMark turn while retaining the native verifier receipt."""
    from core.agent.loop.models import is_successful_task_termination
    from core.observability.trajectory import export_trajectory, trajectory_from_sessions

    log_path = Path(tool_call_log_file)
    trajectory_path = log_path.with_name(f"{log_path.stem}.trajectory.json")
    digests = _existing_digests((log_path,))
    session_id = str(getattr(loop, "_session_id", "") or "")
    instruction_hash = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    trajectory = trajectory_from_sessions(
        (session_id,),
        trajectory_id=f"mcpmark-{session_id or instruction_hash[:16]}",
        source={
            "harness": "mcpmark",
            "run": session_id,
            "session": session_id or "unbound-mcpmark-session",
            "task": instruction_hash,
            "parents": [session_id] if session_id else [],
        },
        outcome={
            "success": not bool(getattr(result, "error", None))
            and is_successful_task_termination(getattr(result, "termination_reason", "")),
            "turn_count": getattr(result, "rounds", 0),
            "termination_reason": str(getattr(result, "termination_reason", "") or ""),
            "error": str(getattr(result, "error", "") or ""),
        },
        provenance={
            "adapter": _ADAPTER_ID,
            "model": model,
            "provider": provider,
            "source": source,
            "effort": effort,
            "store": "sessions.db:session_events",
        },
        privacy={
            "review_state": "local",
            "instruction_persisted": False,
            "instruction_embedded": False,
            "payloads": "dialogue and tool bodies replaced by SHA-256 digests",
        },
        artifact_digests=digests,
        content_policy="digest",
        trajectory_class=("benchmark", "dialogue", "tool", "lifecycle"),
    )
    if action_timed_out:
        integrity = trajectory["integrity"]
        reason = "MCPMark action deadline right-censored the GEODE turn"
        scope_reasons = list(integrity["scope_incompleteness"])
        if reason not in scope_reasons:
            scope_reasons.append(reason)
        integrity["scope_complete"] = False
        integrity["replay_complete"] = False
        integrity["complete"] = False
        integrity["scope_incompleteness"] = scope_reasons
        integrity["incompleteness"] = list(
            dict.fromkeys([*scope_reasons, *integrity["replay_incompleteness"]])
        )
    return export_trajectory(trajectory_path, trajectory)


def export_codex_mcpmark_trajectory(
    *,
    exec_log_path: Path,
    instruction: str,
    model: str,
    effort: str,
    timeout_error: str = "",
) -> Path:
    """Project ``codex exec --json`` onto the shared immutable trajectory schema."""
    from core.observability.trajectory import build_trajectory, export_trajectory

    lines = [
        line for line in exec_log_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    rows: list[dict[str, Any]] = []
    incomplete_final_record_skipped = False
    for index, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if timeout_error and index == len(lines) - 1:
                incomplete_final_record_skipped = True
                break
            raise
    thread_id = next(
        (str(row.get("thread_id") or "") for row in rows if row.get("type") == "thread.started"),
        "",
    )
    turn_id = "turn-1"
    events: list[dict[str, Any]] = []

    def digest(value: Any) -> dict[str, Any]:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
        ).encode("utf-8")
        return {
            "_omitted_payload_sha256": hashlib.sha256(encoded).hexdigest(),
            "_omitted_payload_bytes": len(encoded),
            "_content_omitted": ["native_value"],
        }

    events.append(
        {
            "kind": "user_message",
            "actor": "user",
            "turn_id": turn_id,
            "payload": {"content": digest(instruction)},
        }
    )
    protocol_violations = 0
    turn_completed = False
    native_failure = ""
    for row in rows:
        event_type = row.get("type")
        if event_type == "item.completed":
            item = row.get("item") or {}
            item_type = str(item.get("type") or "")
            call_id = str(item.get("id") or "")
            if item_type == "mcp_tool_call":
                tool = str(item.get("tool") or "")
                events.extend(
                    (
                        {
                            "kind": "tool_call",
                            "actor": "assistant",
                            "turn_id": turn_id,
                            "call_id": call_id,
                            "payload": {
                                "server": item.get("server"),
                                "tool": tool,
                                "arguments": digest(item.get("arguments")),
                            },
                        },
                        {
                            "kind": "tool_result",
                            "actor": "tool",
                            "turn_id": turn_id,
                            "call_id": call_id,
                            "payload": {
                                "tool": tool,
                                "status": item.get("status"),
                                "result": digest(item.get("result")),
                                "error": digest(item.get("error")),
                            },
                        },
                    )
                )
            elif item_type == "agent_message":
                events.append(
                    {
                        "kind": "assistant_message",
                        "actor": "assistant",
                        "turn_id": turn_id,
                        "payload": {"content": digest(item.get("text"))},
                    }
                )
            elif item_type == "reasoning":
                events.append(
                    {
                        "kind": "reasoning.summary",
                        "actor": "assistant",
                        "turn_id": turn_id,
                        "payload": {"content": digest(item.get("text"))},
                    }
                )
            elif item_type in {"command_execution", "file_change", "collab_tool_call"}:
                protocol_violations += 1
                events.append(
                    {
                        "kind": "benchmark.protocol_violation",
                        "actor": "assistant",
                        "turn_id": turn_id,
                        "call_id": call_id,
                        "payload": {"item_type": item_type, "item": digest(item)},
                    }
                )
        elif event_type == "turn.completed":
            turn_completed = True
            events.append(
                {
                    "kind": "turn.completed",
                    "actor": "system",
                    "turn_id": turn_id,
                    "payload": {"usage": row.get("usage") or {}},
                }
            )
        elif event_type in {"turn.failed", "error"}:
            error = row.get("error") if event_type == "turn.failed" else row
            native_failure = str((error or {}).get("message") or event_type)
            events.append(
                {
                    "kind": "turn.failed",
                    "actor": "system",
                    "turn_id": turn_id,
                    "payload": {"error": digest(error)},
                }
            )

    failure = timeout_error or native_failure
    scope_incompleteness = (
        ["Codex exec timed out before complete native execution scope was established"]
        if timeout_error
        else []
    )
    if incomplete_final_record_skipped:
        scope_incompleteness.append(
            "incomplete final Codex exec JSONL record omitted after timeout"
        )
    raw_sha256 = hashlib.sha256(exec_log_path.read_bytes()).hexdigest()
    trajectory = build_trajectory(
        trajectory_id=f"mcpmark-codex-{thread_id or raw_sha256[:16]}",
        source={
            "harness": "mcpmark",
            "run": thread_id or raw_sha256[:16],
            "session": thread_id or "ephemeral-codex-exec",
            "task": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "parents": [],
        },
        events=events,
        outcome={
            "success": turn_completed and not failure and protocol_violations == 0,
            "failure": failure,
            "protocol_violations": protocol_violations,
        },
        provenance={
            "adapter": _ADAPTER_ID,
            "model": model,
            "provider": "codex-cli",
            "source": "subscription",
            "effort": effort,
            "native_schema": "codex exec JSONL",
        },
        privacy={
            "review_state": "local",
            "native_results_embedded": False,
            "payloads": "prompt, reasoning, tool bodies, and responses replaced by SHA-256 digests",
        },
        integrity={
            "scope_complete": not scope_incompleteness,
            "scope_incompleteness": scope_incompleteness,
            "replay_complete": False,
            "replay_incompleteness": [
                "codex exec JSONL omits per-event timestamps and internal model-call boundaries"
            ],
        },
        evidence_refs=[
            {
                "kind": "native_receipt",
                "schema_id": "codex.exec.jsonl@native",
                "reference": raw_sha256,
                "authority": "Codex exec JSONL event stream",
            }
        ],
        artifact_digests=_existing_digests((exec_log_path,)),
        trajectory_class=("benchmark", "dialogue", "tool"),
    )
    return export_trajectory(exec_log_path.with_name("execution.trajectory.json"), trajectory)


def _existing_digests(paths: Sequence[Path]) -> list[dict[str, str]]:
    return [
        {
            "path": f"{path.parent.name}/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
        if path.is_file()
    ]


def _slug(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "-" for character in value
    )


__all__ = [
    "close_benchmark_session",
    "export_codex_mcpmark_trajectory",
    "export_mcpmark_trajectory",
    "export_tau2_trajectory",
    "geode_session_trace",
    "geode_trajectory_snapshot_path",
    "tau2_session_ids",
    "tau2_trajectory_snapshot_paths",
    "write_tau2_trajectory_snapshot",
]
