"""Offline native/handoff export gates; fixtures are not actual collection receipts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.observability.trajectory import _digest_private_event_payload, build_trajectory
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL
from evals.benchmarks.decision_handoff_runtime import INBOX_SYSTEM, _json_digest
from evals.platforms.harbor import (
    _atif_trajectory_from_geode,
    _summarize_usage,
    write_harbor_recording,
)
from scripts.eval import check_harbor_observations as gate

from tests.scripts.test_eval_contract import _run_spec


@pytest.mark.parametrize("export_order", ["ascending", "descending"])
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "dropped-pair",
        "tool-pair",
        "tool-content",
        "session-hash",
        "payload-hash",
        "session",
        "wal",
        "usage-counter",
        "attempt-counter",
        "attempt-identity",
        "attempt-duplicate",
        "attempt-replaced",
    ],
)
def test_source_reconciliation_reads_complete_snapshot_without_mutating(
    tmp_path: Path, fault: str | None, export_order: str
) -> None:
    from core.hooks import HookEvent, HookSystem
    from core.observability.event_store import HookEventStore
    from core.observability.hook_persistence import HookPersistenceSink
    from core.observability.session_timeline import (
        SessionEventKind,
        SessionEventStore,
        SessionEventWrite,
    )
    from core.observability.trajectory import trajectory_from_sessions

    path = tmp_path / "sessions.db"
    store = HookEventStore(path)
    hooks = HookSystem()
    hooks.register_sink(HookPersistenceSink(store, session_key="trial", run_id="run"))
    for index in range(2):
        payload = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "llm_call_id": f"call-{index}",
            "llm_attempt_id": f"attempt-{index}",
            "model": "gpt-5.6-sol",
            "provider": "openai",
            "adapter": "codex_oauth",
            "purpose": "agentic_loop",
            "source": "subscription",
            "effort": "max",
        }
        hooks.trigger(HookEvent.LLM_CALL_STARTED, payload)
        hooks.trigger(
            HookEvent.LLM_CALL_ENDED,
            {
                **payload,
                "latency_ms": 1,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cached_input_tokens": 0,
                    "cache_write_tokens": None,
                },
            },
        )
    rows = store.read()
    hooks.close()
    timeline = SessionEventStore(path)
    for kind, payload in (
        (SessionEventKind.SESSION_STARTED, {}),
        (SessionEventKind.USER_MESSAGE, {"content": "fixture task"}),
        (SessionEventKind.TOOL_CALLED, {"tool": "run_bash", "arguments": {"command": "true"}}),
        (SessionEventKind.TOOL_COMPLETED, {"tool": "run_bash", "result": "ok"}),
        (
            SessionEventKind.SESSION_ENDED,
            {"record_failures": 0, "runtime_observation_status": "no_known_faults"},
        ),
    ):
        timeline.append(
            SessionEventWrite(
                session_id="session-1",
                kind=kind,
                turn_id="turn-1",
                call_id="tool-1"
                if kind in {SessionEventKind.TOOL_CALLED, SessionEventKind.TOOL_COMPLETED}
                else "",
                payload=payload,
            )
        )
    full = trajectory_from_sessions(
        ["session-1"],
        trajectory_id="source-check",
        source={"harness": "harbor", "session": "session-1"},
        db_path=path,
    )
    with sqlite3.connect(path) as db:
        if fault == "payload-hash":
            db.execute("UPDATE hook_events SET payload_hash = ? WHERE id = 1", ("0" * 64,))
        if fault == "session-hash":
            db.execute("UPDATE session_events SET payload_hash = ? WHERE id = 1", ("0" * 64,))
    db.close()
    if fault == "wal":
        path.with_name(path.name + "-wal").write_bytes(b"uncheckpointed evidence")
    selected_rows = (
        rows if fault != "dropped-pair" else [r for r in rows if r.llm_call_id == "call-0"]
    )
    usage = _summarize_usage(selected_rows)
    usage["recorded_attempts"].sort(
        key=lambda row: row["source_event_id"], reverse=export_order == "descending"
    )
    if fault == "usage-counter":
        usage["input_tokens"] += 1
    if fault == "attempt-counter":
        usage["recorded_attempts"][0]["usage"]["input_tokens"] += 1
    if fault == "attempt-identity":
        usage["recorded_attempts"][0]["source_event_id"] += 100
    if fault == "attempt-duplicate":
        usage["recorded_attempts"].append(copy.deepcopy(usage["recorded_attempts"][0]))
    if fault == "attempt-replaced":
        usage["recorded_attempts"][1] = copy.deepcopy(usage["recorded_attempts"][0])
    if fault in {"tool-pair", "tool-content"}:
        if fault == "tool-pair":
            full["events"] = [e for e in full["events"] if not e["kind"].startswith("tool.")]
        else:
            full["events"][2]["payload"]["arguments"]["command"] = "false"
        full = build_trajectory(
            trajectory_id=full["trajectory_id"],
            source=full["source"],
            events=full["events"],
            outcome=full["outcome"],
            provenance=full["provenance"],
            privacy=full["privacy"],
            captured_at=full["captured_at"],
        )
        # Self-consistent full/digest/ATIF/cast projections must not hide source loss.
        _projections(tmp_path, full)
    before = path.read_bytes()
    sessions = {"unrelated"} if fault == "session" else {"session-1"}
    if fault:
        with pytest.raises(ValueError):
            gate._reconcile_usage_source(path, usage, sessions, full)
    else:
        result = gate._reconcile_usage_source(path, usage, sessions, full)
        assert result["reconciled"] is True
        assert result["database_sha256"] == hashlib.sha256(before).hexdigest()
        assert result["hook_rows"] == 4
        assert result["session_rows"] == 5
    assert path.read_bytes() == before


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _rewrite(path: Path, edit: Any) -> None:
    value = json.loads(path.read_text())
    edit(value)
    _write(path, value)


@pytest.fixture
def trial(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "task-1__trial"
    agent = root / "agent"
    agent.mkdir(parents=True)
    spec = _run_spec()
    spec["reproduction"]["harness"]["name"] = "harbor"
    spec["reproduction"]["model"] = {
        "provider": "openai",
        "label": "gpt-5.6-sol",
        "route": "subscription",
        "reasoning": "max",
    }
    spec_path = tmp_path / "run-spec.json"
    _write(spec_path, spec)
    ended = SimpleNamespace(
        action="llm.call.ended",
        id=2,
        occurred_at=1786233661.0,
        session_id="session-1",
        llm_call_id="call-1",
        llm_attempt_id="attempt-1",
        payload_hash="c" * 64,
        payload={
            "model": "gpt-5.6-sol",
            "provider": "openai",
            "adapter": "codex_oauth",
            "purpose": "agentic_loop",
            "source": "subscription",
            "effort": "max",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "cache_write_tokens": None,
            },
        },
    )
    usage = _summarize_usage(
        [
            SimpleNamespace(
                action="llm.call.started", session_id="session-1", llm_attempt_id="attempt-1"
            ),
            ended,
        ]
    )
    usage["source_snapshot_complete"] = True
    metadata = {
        "source_revision": "a" * 40,
        "verify_mode": "reflexion",
        "execution_started": True,
        "geode_session_id": "session-1",
        "termination_reason": "end_turn",
        "error_type": None,
        "finalization_errors": [],
        "usage": usage,
    }
    runtime = {"metadata": metadata, "usage": usage, "tool_definitions": []}
    _write(agent / "runtime-result.json", runtime)
    _write(
        agent / "runtime-finalized.json",
        {
            "exports_complete": True,
            "status": "finalized",
            "execution_started": True,
            "error_type": None,
            "finalization_errors": [],
        },
    )
    _write(
        agent / "runtime-contract.json",
        {
            "source_revision": "a" * 40,
            "source_sha256": "b" * 64,
            "model": "gpt-5.6-sol",
            "source": "subscription",
            "effort": "max",
            "verify_mode": "reflexion",
            "external_search_loop": False,
        },
    )
    _write(
        root / "result.json",
        {
            "task_name": "task-1",
            "trial_name": root.name,
            "trial_uri": root.as_uri(),
            "task_id": {"path": "/app/task-1"},
            "task_checksum": "d" * 64,
            "config": {"task": {"path": "/app/task-1"}},
            "agent_info": {"name": "geode-runtime", "version": "a" * 40},
            "started_at": "2026-08-09T00:01:00Z",
            "finished_at": "2026-08-09T00:02:00Z",
            "agent_result": {"metadata": metadata},
            "verifier_result": {"rewards": {"reward": 0}},
            "exception_info": None,
        },
    )
    events = []
    for ordinal, (kind, payload, call) in enumerate(
        [
            ("session.started", {}, ""),
            ("message.user", {"content": "fixture task"}, ""),
            ("tool.called", {"tool": "run_bash", "arguments": {"command": "true"}}, "tool-1"),
            ("tool.completed", {"tool": "run_bash", "result": "ok", "status": "success"}, "tool-1"),
            ("message.assistant", {"content": "fixture completion"}, ""),
            (
                "session.ended",
                {"record_failures": 0, "runtime_observation_status": "no_known_faults"},
                "",
            ),
        ],
        1,
    ):
        events.append(
            {
                "event_id": f"event-{ordinal}",
                "occurred_at": f"2026-08-09T00:01:0{ordinal}Z",
                "kind": kind,
                "session_id": "session-1",
                "turn_id": "turn-1",
                "call_id": call,
                "actor": "agent",
                "payload": payload,
            }
        )
    full = build_trajectory(
        trajectory_id="harbor-session-1",
        source={"harness": "harbor", "session": "session-1"},
        events=events,
        outcome=metadata,
        provenance={"adapter": "evals.platforms.harbor_runtime"},
        privacy={"review_state": "local"},
        captured_at="2026-08-09T00:01:10Z",
    )
    _projections(agent, full)
    return {
        "trial_dir": root,
        "run_spec_path": spec_path,
        "run_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "source_sha256": "b" * 64,
        "trial_name": root.name,
        "task_name": "task-1",
        "task_checksum": "d" * 64,
    }


def _projections(
    agent: Path,
    full: dict[str, Any],
    *,
    model: str = "gpt-5.6-sol",
    agent_name: str = "geode-runtime",
    effort: str = "max",
    tool_definitions: list[dict[str, Any]] | None = None,
) -> None:
    _write(agent / "geode-trajectory.private.json", full)
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
    )
    _write(agent / "geode-trajectory.json", digest)
    atif = _atif_trajectory_from_geode(
        full,
        model=model,
        provider="openai",
        source="subscription",
        effort=None,
        version="a" * 40,
        metrics={},
    )
    atif["agent"].update(name=agent_name, tool_definitions=tool_definitions or [])
    atif["extra"]["configured_root_effort"] = effort
    _write(agent / "trajectory.json", atif)
    write_harbor_recording(agent / "trajectory.json", overwrite=True)


@pytest.fixture
def model_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise our cross-artifact logic without installing the optional Harbor SDK.
    # A separate integration case below uses Harbor's real native/ATIF models.
    class Model:
        @staticmethod
        def model_validate(value: dict[str, Any]) -> SimpleNamespace:
            return SimpleNamespace(to_json_dict=lambda: value)

    monkeypatch.setattr(gate, "_harbor_model", lambda *args: Model)


def test_valid_semantic_zero_is_not_retried_and_scope_still_blocks(trial, model_boundary):
    root = trial["trial_dir"]
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = gate.validate_observations(**trial)
    assert result["observation_valid"] is True
    assert result["cache_complete"] is True
    assert result["whole_runtime_complete"] is False
    assert result["full_runtime_expansion_ready"] is False
    assert result["accounting"]["counters"]["cached_input_tokens"]["total"] == 0
    assert result["accounting"]["counters"]["cache_write_tokens"]["total"] is None
    assert result["replay_status"] == "tool-actions-observed"
    assert len(result["artifact_sha256"]) == 9
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "missing",
    [
        "runtime-result.json",
        "geode-trajectory.private.json",
        "geode-trajectory.json",
        "trajectory.json",
        "recording.cast",
        "recording.receipt.json",
    ],
)
def test_finalized_true_is_insufficient_when_export_missing(trial, model_boundary, missing):
    (trial["trial_dir"] / "agent" / missing).unlink()
    with pytest.raises(FileNotFoundError):
        gate.validate_observations(**trial)


@pytest.mark.parametrize(
    "mutation", ["cast", "receipt", "atif", "digest", "identity", "stale", "naive"]
)
def test_altered_or_stale_projection_is_rejected(trial, model_boundary, mutation):
    root = trial["trial_dir"]
    agent = root / "agent"
    if mutation == "cast":
        (agent / "recording.cast").write_text("altered")
    elif mutation == "receipt":
        _rewrite(agent / "recording.receipt.json", lambda p: p["source"].update(sha256="e" * 64))
    elif mutation == "atif":
        _rewrite(agent / "trajectory.json", lambda p: p["steps"][1].update(message="altered"))
    elif mutation == "digest":
        _rewrite(
            agent / "geode-trajectory.json",
            lambda p: p["events"][2]["payload"].update(tool="wrong"),
        )
    elif mutation == "identity":
        _rewrite(root / "result.json", lambda p: p.update(trial_name="older-trial"))
    else:
        _rewrite(
            root / "result.json",
            lambda p: p.update(
                started_at="2020-01-01T00:00:00Z" if mutation == "stale" else "2026-08-09T00:01:00"
            ),
        )
    with pytest.raises(ValueError):
        gate.validate_observations(**trial)


def _replace_usage(root: Path, usage: dict[str, Any]) -> None:
    agent = root / "agent"
    _rewrite(
        agent / "runtime-result.json",
        lambda p: (p.update(usage=usage), p["metadata"].update(usage=usage)),
    )
    _rewrite(root / "result.json", lambda p: p["agent_result"]["metadata"].update(usage=usage))
    for name in ("geode-trajectory.private.json", "geode-trajectory.json"):
        _rewrite(agent / name, lambda p: p["outcome"].update(usage=usage))
    if (agent / "handoff-result.json").exists():
        _rewrite(agent / "handoff-result.json", lambda p: p.update(usage=usage))


def test_missing_cache_is_null_not_zero_or_collection_failure(trial, model_boundary):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][0]["usage"]["cached_input_tokens"] = None
    usage.update(cached_input_tokens=None, cached_input_tokens_missing_events=1)
    _replace_usage(root, usage)
    result = gate.validate_observations(**trial)
    assert result["observation_valid"] is True
    assert result["cache_complete"] is False
    assert result["accounting"]["counters"]["cached_input_tokens"]["total"] is None
    assert result["full_runtime_expansion_ready"] is False


@pytest.mark.parametrize("effort", ["max", "medium", None])
def test_uniform_effort_gate_checks_auxiliary_calls(trial, model_boundary, effort):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][0].update(purpose="cognitive_reflection", effort=effort)
    _replace_usage(root, usage)
    report = gate.validate_observations(**trial)
    assert report["accounting"]["uniform_requested_effort"] is (effort == "max")
    if effort == "max":
        assert gate.validate_observations(**trial, require_uniform_effort=True)["observation_valid"]
    else:
        with pytest.raises(ValueError, match="frozen reasoning effort"):
            gate.validate_observations(**trial, require_uniform_effort=True)


@pytest.mark.parametrize(
    "mutation", ["empty", "counter", "duplicate", "degraded", "whole", "snapshot"]
)
def test_usage_false_completeness_rejected(trial, model_boundary, mutation):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    if mutation == "empty":
        usage["recorded_attempts"] = []
    elif mutation == "duplicate":
        usage["recorded_attempts"].append(copy.deepcopy(usage["recorded_attempts"][0]))
    else:
        usage.update(
            {
                "counter": {"cached_input_tokens": 7},
                "degraded": {"observation_status": "degraded"},
                "whole": {"whole_runtime_complete": True},
                "snapshot": {"source_snapshot_complete": False},
            }[mutation]
        )
    _replace_usage(root, usage)
    with pytest.raises(ValueError):
        gate.validate_observations(**trial)


def test_no_tool_action_is_reported_without_inventing_trace(trial, model_boundary):
    agent = trial["trial_dir"] / "agent"
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    full = build_trajectory(
        trajectory_id=previous["trajectory_id"],
        source=previous["source"],
        events=[e for e in previous["events"] if not e["kind"].startswith("tool.")],
        outcome=previous["outcome"],
        provenance=previous["provenance"],
        privacy=previous["privacy"],
    )
    _projections(agent, full)
    result = gate.validate_observations(**trial)
    assert result["tool_calls"] == 0
    assert result["replay_status"] == "no-tool-action-observed"


@pytest.mark.parametrize("name", ["geode-trajectory.private.json", "geode-trajectory.json"])
def test_each_canonical_projection_rejects_false_integrity(trial, model_boundary, name):
    _rewrite(
        trial["trial_dir"] / "agent" / name,
        lambda value: value["integrity"].update(record_count=0),
    )
    with pytest.raises(ValueError, match="record_count does not match events"):
        gate.validate_observations(**trial)


def test_cli_never_reports_expansion_green_or_prints_private_error(trial, model_boundary, capsys):
    args = [str(trial["trial_dir"]), "--run-spec", str(trial["run_spec_path"])]
    for name, value in trial.items():
        if name not in {"trial_dir", "run_spec_path"}:
            args.extend(["--" + name.replace("_", "-"), str(value)])
    assert gate.main(args) == 2
    assert json.loads(capsys.readouterr().out)["full_runtime_expansion_ready"] is False
    (trial["trial_dir"] / "agent/trajectory.json").write_text('{"private task body":')
    assert gate.main(args) == 1
    assert "private task body" not in capsys.readouterr().out


def test_real_harbor_native_and_atif_schema_when_installed(trial):
    if importlib.util.find_spec("harbor") is None:
        pytest.skip("optional Harbor SDK not installed; run in the frozen Harbor environment")
    assert gate.validate_observations(**trial)["observation_valid"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "different-model"),
        ("provider", "anthropic"),
        ("source", "api-key"),
        ("purpose", "unrecognized"),
        ("purpose", []),
        ("purpose", {}),
        ("effort", []),
        ("effort", {}),
        ("effort", True),
        ("occurred_at", True),
        ("occurred_at", float("inf")),
        ("occurred_at", 1),
        ("source_event_id", True),
    ],
)
def test_wrong_attempt_route_or_untyped_observation_rejected(trial, model_boundary, field, value):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][0][field] = value
    _replace_usage(root, usage)
    with pytest.raises(ValueError):
        gate.validate_observations(**trial)


@pytest.mark.parametrize(
    "field",
    [
        "cached_input_tokens",
        "cached_input_tokens_observed_sum",
        "cached_input_tokens_missing_events",
        "mapping_anomaly_events",
    ],
)
def test_boolean_is_not_an_observed_zero(trial, model_boundary, field):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage[field] = False
    _replace_usage(root, usage)
    with pytest.raises(ValueError):
        gate.validate_observations(**trial)


def test_absent_cache_key_is_export_loss_not_provider_null(trial, model_boundary):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    del usage["recorded_attempts"][0]["usage"]["cached_input_tokens"]
    usage.update(cached_input_tokens=None, cached_input_tokens_missing_events=1)
    _replace_usage(root, usage)
    with pytest.raises(ValueError, match="key lost"):
        gate.validate_observations(**trial)


@pytest.mark.parametrize(
    ("purpose", "effort"),
    [
        ("cognitive_reflection", "medium"),
        ("turn_verification", "max"),
        ("structured_decision", "medium"),
        ("context_compaction", "max"),
        ("learning_extraction", "max"),
        ("memory_dreaming", "max"),
        ("context_exhaustion", "max"),
    ],
)
def test_observed_call_purpose_and_effort_are_retained(trial, model_boundary, purpose, effort):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][0].update(purpose=purpose, effort=effort)
    _replace_usage(root, usage)
    report = gate.validate_observations(**trial)
    assert report["accounting"]["observed_efforts"] == {effort: 1}
    assert report["accounting"]["purposes"] == {purpose: 1}


def test_legacy_missing_metadata_is_unknown_not_root_default(trial, model_boundary):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    for field in ("purpose", "source", "effort"):
        usage["recorded_attempts"][0].pop(field, None)
    _replace_usage(root, usage)
    report = gate.validate_observations(**trial)
    assert report["accounting"]["unknown_metadata_attempts"] == 1
    assert report["accounting"]["purposes"] == {"unknown": 1}
    assert report["accounting"]["observed_efforts"] == {"unknown": 1}


@pytest.mark.parametrize(
    "value",
    [
        True,
        "bad",
        "2026-08-09T00:01:00-00:00",
        "2026-08-09T00:01:00-0000",
        "2026-08-09T00:01:00-00",
    ],
)
def test_invalid_or_unknown_timezone_is_not_inferred(trial, model_boundary, value):
    _rewrite(trial["trial_dir"] / "result.json", lambda p: p.update(started_at=value))
    with pytest.raises(ValueError):
        gate.validate_observations(**trial)


def test_bound_spec_hash_cannot_be_reused_after_edit(trial, model_boundary):
    _rewrite(trial["run_spec_path"], lambda p: p.update(run_id="another-run"))
    with pytest.raises(ValueError, match="SHA mismatch"):
        gate.validate_observations(**trial)


def test_boolean_recording_count_is_not_zero(trial, model_boundary):
    _rewrite(
        trial["trial_dir"] / "agent/recording.receipt.json",
        lambda p: p["timing"].update(synthetic_timestamp_count=False),
    )
    with pytest.raises(ValueError, match="recording receipt contract mismatch"):
        gate.validate_observations(**trial)


@pytest.mark.parametrize("status", [None, "degraded", "unavailable"])
def test_session_sink_health_is_required_for_fresh_observations(trial, model_boundary, status):
    agent = trial["trial_dir"] / "agent"
    full = json.loads((agent / "geode-trajectory.private.json").read_text())
    full["events"][-1]["payload"]["runtime_observation_status"] = status
    _projections(agent, full)
    with pytest.raises(ValueError, match="session not closed cleanly"):
        gate.validate_observations(**trial)


@pytest.mark.parametrize("other_session", [False, True])
def test_tool_identity_matches_projectors_session_turn_call_key(
    trial, model_boundary, other_session
):
    agent = trial["trial_dir"] / "agent"
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    added = copy.deepcopy(previous["events"][2:4])
    for index, event in enumerate(added, 1):
        event.update(event_id=f"another-{index}", occurred_at=f"2026-08-09T00:01:04.{index}Z")
        if other_session:
            event["session_id"] = "child-session"
    added[1]["payload"]["result"] = "different result"
    if other_session:
        terminal = copy.deepcopy(previous["events"][-1])
        terminal.update(event_id="child-end", session_id="child-session")
        added.append(terminal)
    full = build_trajectory(
        trajectory_id=previous["trajectory_id"],
        source=previous["source"],
        events=[*previous["events"][:-2], *added, *previous["events"][-2:]],
        outcome=previous["outcome"],
        provenance=previous["provenance"],
        privacy=previous["privacy"],
    )
    _projections(agent, full)
    if other_session:
        report = gate.validate_observations(**trial)
        assert report["tool_calls"] == 2
    else:
        with pytest.raises(ValueError, match="ambiguous canonical tool identity"):
            gate.validate_observations(**trial)


def _handoff_trial(
    trial: dict[str, Any],
    arm: str,
    *,
    reflection: bool = False,
    verification_engine: str | None = None,
) -> dict[str, Any]:
    """Build offline profile evidence through the existing usage/ATIF producers."""
    root = trial["trial_dir"]
    agent = root / "agent"
    model = {
        "provider": "openai",
        "label": "gpt-6-astra",
        "route": "subscription",
        "reasoning": "xhigh",
    }
    _rewrite(trial["run_spec_path"], lambda spec: spec["reproduction"].update(model=model))
    names = ["lookup_order_status"]
    if arm != "a0":
        names.insert(0, "analyze_request")
    definitions = [{"name": name, "parameters": {}} for name in names]
    events = []
    purposes = ["agentic_loop"] + ([] if arm == "a0" else ["structured_decision"])
    if reflection:
        purposes.append("cognitive_reflection")
    if verification_engine:
        purposes.append("agentic_loop")
        purposes.append("turn_verification")
    for index, purpose in enumerate(purposes, 1):
        jev = (arm == "b" and purpose == "structured_decision") or (
            verification_engine == "jev" and purpose == "turn_verification"
        )
        identity = {
            "session_id": "session-1",
            "llm_call_id": f"call-{index}",
            "llm_attempt_id": f"attempt-{index}",
            "tool_call_id": "tool-1" if purpose == "structured_decision" else "",
        }
        events.extend(
            [
                SimpleNamespace(action="llm.call.started", **identity),
                SimpleNamespace(
                    action="llm.call.ended",
                    id=index * 2,
                    occurred_at=1786233661.0 + index,
                    payload_hash=hashlib.sha256(str(index).encode()).hexdigest(),
                    **identity,
                    payload={
                        "model": "jev-1.13.0" if jev else model["label"],
                        "response_model": "jev-1.13.0" if jev else model["label"],
                        "provider": "typesafe" if jev else "openai",
                        "adapter": "typesafe-decision-handoff" if jev else "codex_oauth",
                        "purpose": purpose,
                        "source": "payg" if jev else "subscription",
                        "effort": "none" if jev else "xhigh",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "cached_input_tokens": 0,
                            "cache_write_tokens": None,
                        },
                    },
                ),
            ]
        )
    if verification_engine:
        for event in events:
            if event.action == "llm.call.ended":
                event.payload["llm_call_id"] = event.llm_call_id
                event.payload["response_id"] = "response-" + event.llm_call_id
                if event.payload["provider"] == "typesafe":
                    event.payload["response_provider"] = "typesafe"
                event.payload_hash = _json_digest(event.payload)
    usage = _summarize_usage(events)
    usage["source_snapshot_complete"] = True
    _write(
        agent / "handoff-result.json",
        {
            "session_id": "session-1",
            "usage": usage,
            "handoff_call_coverage_complete": True,
            **({"verification_engine": verification_engine} if verification_engine else {}),
        },
    )
    receipt = [{"kind": "root_request", "llm_call_id": "call-1"}]
    if arm != "a0":
        receipt.append({"kind": "tool_result", "tool": "analyze_request", "tool_call_id": "tool-1"})
    if reflection:
        receipt.append(
            {
                "kind": "reflection_request",
                "llm_call_id": f"call-{purposes.index('cognitive_reflection') + 1}",
            }
        )
    if verification_engine:
        receipt.extend(
            [
                {
                    "kind": "tool_result",
                    "tool": "lookup_order_status",
                    "tool_call_id": "tool-1",
                    "result": "ok",
                },
                {"kind": "root_request", "llm_call_id": f"call-{len(purposes) - 1}"},
                {
                    "kind": "verification_request",
                    "llm_call_id": f"call-{len(purposes)}",
                    "step_id": "step-judge",
                },
            ]
        )
    _write(agent / "handoff.json", receipt)
    runtime = json.loads((agent / "runtime-result.json").read_text())
    metadata = runtime["metadata"]
    metadata.update(verify_mode="rule_based", profile="decision-handoff", arm=arm, usage=usage)
    if verification_engine:
        metadata.update(verify_mode="llm_judge", verification_engine=verification_engine)
    runtime.update(usage=usage, tool_definitions=definitions)
    _write(agent / "runtime-result.json", runtime)
    _rewrite(
        root / "result.json",
        lambda value: (
            value["agent_info"].update(name="geode-handoff"),
            value["agent_result"].update(metadata=metadata),
        ),
    )
    _rewrite(
        agent / "runtime-contract.json",
        lambda contract: contract.update(
            model=model["label"],
            effort="xhigh",
            verify_mode="llm_judge" if verification_engine else "rule_based",
            runtime="evals.benchmarks.decision_handoff_runtime:run_arm",
            profile="decision-handoff",
            arm=arm,
            case_sha256="e" * 64,
            required_tools=names,
            **(
                {"verification_engine": verification_engine, "workload_profile": "inbox"}
                if verification_engine
                else {}
            ),
        ),
    )
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    for event in previous["events"]:
        if event["kind"].startswith("tool."):
            event["payload"]["tool"] = names[0]
    full = build_trajectory(
        trajectory_id=previous["trajectory_id"],
        source=previous["source"],
        events=previous["events"],
        outcome=metadata,
        provenance={"adapter": "evals.platforms.harbor_handoff"},
        privacy=previous["privacy"],
        captured_at=previous["captured_at"],
    )
    _projections(
        agent,
        full,
        model=model["label"],
        agent_name="geode-handoff",
        effort="xhigh",
        tool_definitions=definitions,
    )
    if verification_engine:
        from evals.benchmarks.decision_verification import _QUESTIONS, _REFLECTIONS

        judge_id = f"call-{len(purposes)}"
        candidate_id = f"call-{len(purposes) - 1}"
        state = {
            "task_contract": INBOX_SYSTEM,
            "original_request": "fixture task",
            "candidate_output": "fixture completion",
            "tool_observations": [
                {
                    "tool_call_id": "tool-1",
                    "tool": "lookup_order_status",
                    "input": {"command": "true"},
                    "result": "ok",
                }
            ],
        }
        native_answer: dict[str, Any] = (
            {"verdict": "supported"}
            if verification_engine == "llm"
            else {
                "type": "choice",
                "choice": "supported",
                "probabilities": {
                    "supported": 0.8,
                    "contradicted": 0.1,
                    "insufficient_evidence": 0.1,
                },
                "confidence": 0.6,
            }
        )
        projected = {"passed": True, "score": 1.0, "reflection": _REFLECTIONS["supported"]}
        raw_answer = json.dumps(
            native_answer if verification_engine == "llm" else {"verdict": native_answer}
        )
        _write(
            agent / "verification.json",
            {
                "inputs": [
                    {
                        "llm_call_id": judge_id,
                        "candidate_call_id": candidate_id,
                        "state": state,
                        "state_sha256": _json_digest(state),
                        "receipt_prefix_length": len(receipt),
                    }
                ],
                "judgments": [
                    {
                        "llm_call_id": judge_id,
                        "step_id": "step-judge",
                        "engine": verification_engine,
                        "model": ROOT_MODEL if verification_engine == "llm" else JEV_MODEL,
                        "provider": "openai" if verification_engine == "llm" else "typesafe",
                        "source": "subscription" if verification_engine == "llm" else "payg",
                        "response_id": "response-" + judge_id,
                        "response_model": ROOT_MODEL if verification_engine == "llm" else JEV_MODEL,
                        "response_provider": None if verification_engine == "llm" else "typesafe",
                        "input_sha256": _json_digest(state),
                        "source_sha256": _json_digest(state),
                        "question_sha256": _json_digest(_QUESTIONS),
                        "raw_answer_sha256": hashlib.sha256(raw_answer.encode()).hexdigest(),
                        "raw_answer": raw_answer,
                        "raw_answer_retention": "complete",
                        "accepted": True,
                        "verdict": "supported",
                        "native_answer": native_answer,
                        "projected_payload": projected,
                        "feedback_sha256": _json_digest(projected),
                        "error_type": None,
                    }
                ],
                "root_outputs": [
                    {
                        "llm_call_id": "call-1",
                        "text": "",
                        "tool_uses": [
                            {
                                "id": "tool-1",
                                "name": "lookup_order_status",
                                "input": {"command": "true"},
                            }
                        ],
                    },
                    {"llm_call_id": candidate_id, "text": "fixture completion", "tool_uses": []},
                ],
                "root_requests": [
                    {
                        "llm_call_id": call_id,
                        "completed_judgments": 0,
                        "system_prompt": INBOX_SYSTEM,
                        "consumed_feedback": [],
                    }
                    for call_id in ("call-1", candidate_id)
                ],
            },
        )
        _write(
            agent / "call-events.json",
            [
                {
                    "id": event.id,
                    "payload_hash": event.payload_hash,
                    "payload": event.payload,
                    "llm_attempt_id": event.llm_attempt_id,
                    "action": event.action,
                }
                for event in events
                if event.action == "llm.call.ended"
            ],
        )
    return {
        **trial,
        "run_spec_sha256": hashlib.sha256(trial["run_spec_path"].read_bytes()).hexdigest(),
        "handoff_arm": arm,
        "handoff_case_sha256": "e" * 64,
        **({"verification_engine": verification_engine} if verification_engine else {}),
    }


@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_matched_verifier_is_explicit_and_keeps_root_route(trial, model_boundary, engine):
    options = _handoff_trial(trial, "a0", reflection=True, verification_engine=engine)
    report = gate.validate_observations(**options)
    assert report["accounting"]["purposes"]["turn_verification"] == 1
    assert report["accounting"]["attempts"] == 4
    assert "agent/verification.json" in report["artifact_sha256"]
    assert "agent/call-events.json" in report["artifact_sha256"]
    assert not report["whole_runtime_complete"]
    with pytest.raises(ValueError):
        gate.validate_observations(**(options | {"verification_engine": None}))
    with pytest.raises(ValueError):
        gate.validate_observations(
            **(options | {"verification_engine": "jev" if engine == "llm" else "llm"})
        )


@pytest.mark.parametrize("engine", ["llm", "jev"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "missing_native_events",
        "source_hash",
        "input_hash",
        "question_hash",
        "candidate_call",
        "candidate_text",
        "original_request",
        "tool_observation",
        "prefix",
        "dropped_judgment",
        "duplicate_judgment",
        "response_id",
        "native_answer",
        "raw_answer",
        "projected",
        "feedback_hash",
        "root_output",
        "root_request",
        "consumption",
        "native_event",
    ],
)
def test_matched_verification_rejects_missing_or_altered_lineage(
    trial: dict[str, Any], model_boundary: None, engine: str, fault: str
) -> None:
    options = _handoff_trial(trial, "a0", reflection=True, verification_engine=engine)
    agent = trial["trial_dir"] / "agent"
    path = agent / "verification.json"
    evidence = json.loads(path.read_text())
    item, judgment = evidence["inputs"][0], evidence["judgments"][0]
    if fault == "missing":
        path.unlink()
    elif fault == "missing_native_events":
        (agent / "call-events.json").unlink()
    elif fault == "native_event":
        _rewrite(
            agent / "call-events.json",
            lambda rows: rows[-1]["payload"].update(response_id="altered"),
        )
    else:
        if fault == "source_hash":
            item["state_sha256"] = "0" * 64
        elif fault == "input_hash":
            judgment["input_sha256"] = "0" * 64
        elif fault == "question_hash":
            judgment["question_sha256"] = "0" * 64
        elif fault == "candidate_call":
            item["candidate_call_id"] = "call-1"
        elif fault in {"candidate_text", "original_request", "tool_observation"}:
            state = item["state"]
            if fault == "candidate_text":
                state["candidate_output"] = "invented candidate"
                evidence["root_outputs"][-1]["text"] = state["candidate_output"]
            elif fault == "original_request":
                state["original_request"] = "invented request"
            else:
                state["tool_observations"] = []
            digest = _json_digest(state)
            item["state_sha256"] = judgment["input_sha256"] = judgment["source_sha256"] = digest
        elif fault == "prefix":
            item["receipt_prefix_length"] -= 1
        elif fault == "dropped_judgment":
            evidence["judgments"] = []
        elif fault == "duplicate_judgment":
            evidence["judgments"].append(copy.deepcopy(judgment))
        elif fault == "response_id":
            judgment["response_id"] = "another-response"
        elif fault == "native_answer":
            judgment["native_answer"]["verdict" if engine == "llm" else "choice"] = "contradicted"
        elif fault == "raw_answer":
            judgment["raw_answer"] = "changed original"
        elif fault == "projected":
            judgment["projected_payload"]["reflection"]["lesson"] = "invented lesson"
            judgment["feedback_sha256"] = _json_digest(judgment["projected_payload"])
        elif fault == "feedback_hash":
            judgment["feedback_sha256"] = "0" * 64
        elif fault == "root_output":
            evidence["root_outputs"].pop(0)
        elif fault == "root_request":
            evidence["root_requests"][0]["completed_judgments"] = 1
        else:
            evidence["root_requests"][0]["consumed_feedback"] = [
                {
                    "judge_call_id": judgment["llm_call_id"],
                    "feedback_sha256": judgment["feedback_sha256"],
                }
            ]
        _write(path, evidence)
    with pytest.raises((ValueError, FileNotFoundError)):
        gate.validate_observations(**options)


@pytest.mark.parametrize("engine", ["llm", "jev"])
def test_matched_completed_rejection_is_preserved_without_fabricated_repair(
    trial: dict[str, Any], model_boundary: None, engine: str
) -> None:
    options = _handoff_trial(trial, "a0", verification_engine=engine)
    path = trial["trial_dir"] / "agent/verification.json"

    def reject(evidence: dict[str, Any]) -> None:
        evidence["judgments"][0].update(
            accepted=False,
            error_type="invalid_verifier_response",
            verdict=None,
            native_answer=None,
            projected_payload=None,
            feedback_sha256=None,
        )

    _rewrite(path, reject)
    report = gate.validate_observations(**options)
    assert report["verification"]["completed_judgments"] == 1
    _rewrite(path, lambda evidence: evidence["judgments"][0].update(verdict="contradicted"))
    with pytest.raises(ValueError, match="rejection fabricated"):
        gate.validate_observations(**options)


@pytest.mark.parametrize("altered", [False, True])
def test_matched_held_candidate_uses_native_digest_not_delivered_message(
    trial: dict[str, Any], model_boundary: None, altered: bool
) -> None:
    options = _handoff_trial(trial, "a0", verification_engine="llm")
    agent = trial["trial_dir"] / "agent"
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    event = next(row for row in previous["events"] if row["kind"] == "message.assistant")
    event["kind"] = "verification.pending"
    event["payload"] = {
        "candidate_sha256": "0" * 64
        if altered
        else hashlib.sha256(b"fixture completion").hexdigest(),
        "candidate_bytes": len(b"fixture completion"),
        "verify_attempt": 0,
        "root_turn_id": "turn-1",
    }
    full = build_trajectory(
        trajectory_id=previous["trajectory_id"],
        source=previous["source"],
        events=previous["events"],
        outcome=previous["outcome"],
        provenance=previous["provenance"],
        privacy=previous["privacy"],
        captured_at=previous["captured_at"],
    )
    _projections(
        agent,
        full,
        model=ROOT_MODEL,
        agent_name="geode-handoff",
        effort="xhigh",
        tool_definitions=[{"name": "lookup_order_status", "parameters": {}}],
    )
    if altered:
        with pytest.raises(ValueError, match="candidate source"):
            gate.validate_observations(**options)
    else:
        assert gate.validate_observations(**options)["observation_valid"]


def test_matched_gate_rejects_recovered_attempts_with_repeated_logical_id(
    trial: dict[str, Any], model_boundary: None
) -> None:
    _handoff_trial(trial, "a0", verification_engine="llm")
    agent = trial["trial_dir"] / "agent"
    attempts = json.loads((agent / "runtime-result.json").read_text())["usage"]["recorded_attempts"]
    repeated = dict(attempts[0], llm_attempt_id="recovered-attempt", source_event_id=100)
    with pytest.raises(ValueError, match="repeated logical calls"):
        gate._verification_check(
            json.loads((agent / "verification.json").read_text()),
            engine="llm",
            receipt=json.loads((agent / "handoff.json").read_text()),
            attempts=[*attempts, repeated],
            call_events=json.loads((agent / "call-events.json").read_text()),
            trajectory=json.loads((agent / "geode-trajectory.private.json").read_text()),
        )


@pytest.mark.parametrize("retention", ["omitted_sensitive", "omitted_oversize"])
def test_matched_gate_preserves_explicit_raw_omission_only_for_rejected_completion(
    trial: dict[str, Any], model_boundary: None, retention: str
) -> None:
    options = _handoff_trial(trial, "a0", verification_engine="llm")
    path = trial["trial_dir"] / "agent/verification.json"

    def omit(evidence: dict[str, Any]) -> None:
        evidence["judgments"][0].update(
            accepted=False,
            error_type="invalid_verifier_response",
            verdict=None,
            native_answer=None,
            projected_payload=None,
            feedback_sha256=None,
            raw_answer=None,
            raw_answer_retention=retention,
        )

    _rewrite(path, omit)
    report = gate.validate_observations(**options)
    assert report["verification"]["omitted_native_answers"] == 1
    assert any("does not independently retain" in item for item in report["limits"])
    _rewrite(path, lambda evidence: evidence["judgments"][0].update(accepted=True))
    with pytest.raises(ValueError, match="omitted answer was admitted"):
        gate.validate_observations(**options)


@pytest.mark.parametrize("arm", ["a0", "a", "b"])
def test_handoff_reflection_is_accounted_without_relabeling_as_root(trial, model_boundary, arm):
    options = _handoff_trial(trial, arm, reflection=True)
    report = gate.validate_observations(**options)
    assert report["observation_valid"] is True
    assert report["accounting"]["purposes"]["cognitive_reflection"] == 1
    assert report["accounting"]["attempts"] == (2 if arm == "a0" else 3)
    assert report["whole_runtime_complete"] is False


def test_native_current_judge_mode_must_match_frozen_expectation(trial, model_boundary):
    root = trial["trial_dir"]
    agent = root / "agent"
    _rewrite(agent / "runtime-contract.json", lambda value: value.update(verify_mode="llm_judge"))
    _rewrite(
        agent / "runtime-result.json",
        lambda value: value["metadata"].update(verify_mode="llm_judge"),
    )
    _rewrite(
        root / "result.json",
        lambda value: value["agent_result"]["metadata"].update(verify_mode="llm_judge"),
    )
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    previous["outcome"]["verify_mode"] = "llm_judge"
    _projections(agent, previous)
    with pytest.raises(ValueError, match="runtime contract mismatch"):
        gate.validate_observations(**trial)
    assert gate.validate_observations(**trial, expected_verify_mode="llm_judge")[
        "observation_valid"
    ]


@pytest.mark.parametrize("arm", ["a0", "a", "b"])
def test_explicit_handoff_profile_preserves_scope_blocker(trial, model_boundary, arm):
    options = _handoff_trial(trial, arm)
    root = trial["trial_dir"]
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = gate.validate_observations(**options)
    assert report["observation_valid"] is True
    assert report["whole_runtime_complete"] is False
    assert report["full_runtime_expansion_ready"] is False
    assert gate._SCOPE_BLOCKER in report["blockers"]
    assert report["handoff_arm"] == arm
    assert report["handoff_case_sha256"] == "e" * 64
    accounting = report["accounting"]
    assert accounting["attempts"] == (1 if arm == "a0" else 2)
    assert accounting["unknown_metadata_attempts"] == 0
    assert accounting["uniform_requested_effort"] is (arm != "b")
    if arm == "b":
        assert accounting["observed_efforts"] == {"xhigh": 1, "none": 1}
        with pytest.raises(ValueError, match="frozen reasoning effort"):
            gate.validate_observations(**options, require_uniform_effort=True)
    else:
        assert gate.validate_observations(**options, require_uniform_effort=True)[
            "observation_valid"
        ]
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_handoff_is_never_inferred_from_untrusted_artifacts(trial, model_boundary):
    options = _handoff_trial(trial, "b")
    del options["handoff_arm"], options["handoff_case_sha256"]
    with pytest.raises(ValueError, match="native agent identity mismatch"):
        gate.validate_observations(**options)


@pytest.mark.parametrize("kind", ["root_request", "tool_result"])
def test_handoff_checks_dispatch_receipts_against_observed_calls(trial, model_boundary, kind):
    options = _handoff_trial(trial, "b")
    path = trial["trial_dir"] / "agent/handoff.json"
    rows = json.loads(path.read_text())
    _write(path, [row for row in rows if row["kind"] != kind])
    with pytest.raises(ValueError, match="dispatch/attempt coverage mismatch"):
        gate.validate_observations(**options)


@pytest.mark.parametrize(
    ("arm", "case_sha"),
    [("b", None), (None, "e" * 64), ("other", "e" * 64), ("a", "bad"), ("a0", "E" * 64)],
)
def test_handoff_profile_requires_explicit_arm_and_frozen_case_sha(
    trial, model_boundary, arm, case_sha
):
    with pytest.raises(ValueError, match="supplied together"):
        gate.validate_observations(**trial, handoff_arm=arm, handoff_case_sha256=case_sha)


@pytest.mark.parametrize(
    ("arm", "index", "field", "value"),
    [
        ("a0", 0, "purpose", "structured_decision"),
        ("a0", 0, "response_model", None),
        ("a0", 0, "effort", None),
        ("a", 1, "response_model", "jev-1.13.0"),
        ("a", 1, "effort", "medium"),
        ("b", 0, "response_model", "gpt-5.6-sol"),
        ("b", 0, "source", None),
        ("b", 0, "effort", "none"),
        ("b", 0, "purpose", "memory_dreaming"),
        ("b", 1, "response_model", None),
        ("b", 1, "response_model", "jev-1.12.0"),
        ("b", 1, "model", "gpt-6-astra"),
        ("b", 1, "provider", "openai"),
        ("b", 1, "source", "subscription"),
        ("b", 1, "effort", "xhigh"),
        ("b", 1, "effort", None),
        ("b", 1, "purpose", "agentic_loop"),
        ("b", 1, "purpose", None),
    ],
)
def test_handoff_checks_observed_route_response_model_and_effort(
    trial, model_boundary, arm, index, field, value
):
    options = _handoff_trial(trial, arm)
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][index][field] = value
    _replace_usage(root, usage)
    with pytest.raises(ValueError, match="handoff"):
        gate.validate_observations(**options)


@pytest.mark.parametrize(
    "mutation",
    [
        "arm",
        "case",
        "profile",
        "assembly",
        "required-tools",
        "extra-definition",
        "missing-definition",
        "duplicate-definition",
        "observed-tool",
        "runtime-arm",
        "source",
        "task",
        "dirty",
        "spec-hash",
        "root-model",
    ],
)
def test_handoff_profile_cannot_bypass_identity_tools_or_freeze(trial, model_boundary, mutation):
    options = _handoff_trial(trial, "b")
    root = trial["trial_dir"]
    agent = root / "agent"
    contract_edits = {
        "arm": {"arm": "a"},
        "case": {"case_sha256": "f" * 64},
        "profile": {"profile": "native"},
        "assembly": {"runtime": "core.wiring.runtime:build_runtime"},
        "required-tools": {
            "required_tools": ["analyze_request", "lookup_order_status", "run_bash"]
        },
        "source": {"source_sha256": "f" * 64},
    }
    if mutation in contract_edits:
        _rewrite(
            agent / "runtime-contract.json", lambda value: value.update(contract_edits[mutation])
        )
    elif mutation.endswith("definition"):

        def alter_definitions(value):
            definitions = value["tool_definitions"]
            if mutation == "extra-definition":
                definitions.append({"name": "run_bash", "parameters": {}})
            elif mutation == "missing-definition":
                definitions.pop()
            else:
                definitions[1] = copy.deepcopy(definitions[0])

        _rewrite(agent / "runtime-result.json", alter_definitions)
    elif mutation == "observed-tool":
        _rewrite(
            agent / "geode-trajectory.private.json",
            lambda value: value["events"][2]["payload"].update(tool="run_bash"),
        )
    elif mutation == "runtime-arm":
        _rewrite(agent / "runtime-result.json", lambda value: value["metadata"].update(arm="a"))
    elif mutation == "task":
        _rewrite(root / "result.json", lambda value: value.update(task_checksum="f" * 64))
    elif mutation in {"dirty", "root-model"}:

        def alter_spec(value):
            if mutation == "dirty":
                value["reproduction"]["geode"]["dirty"] = True
            else:
                value["reproduction"]["model"]["label"] = "gpt-5.6-sol"

        _rewrite(options["run_spec_path"], alter_spec)
        options["run_spec_sha256"] = hashlib.sha256(
            options["run_spec_path"].read_bytes()
        ).hexdigest()
    else:
        _rewrite(options["run_spec_path"], lambda value: value.update(run_id="another-run"))
    with pytest.raises(ValueError):
        gate.validate_observations(**options)


def test_handoff_unknown_counter_is_not_zero_or_expansion_permission(trial, model_boundary):
    options = _handoff_trial(trial, "b")
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][1]["usage"]["cached_input_tokens"] = None
    usage.update(cached_input_tokens=None, cached_input_tokens_missing_events=1)
    _replace_usage(root, usage)
    report = gate.validate_observations(**options)
    assert report["cache_complete"] is False
    assert report["accounting"]["counters"]["cached_input_tokens"]["total"] is None
    assert report["accounting"]["counters"]["cached_input_tokens"]["observed_sum"] == 0
    assert report["whole_runtime_complete"] is False


def test_handoff_cli_keeps_exit_two_for_scope_blocker(trial, model_boundary, capsys):
    options = _handoff_trial(trial, "b")
    arguments = [str(options["trial_dir"]), "--run-spec", str(options["run_spec_path"])]
    for name, value in options.items():
        if name not in {"trial_dir", "run_spec_path"}:
            arguments.extend(["--" + name.replace("_", "-"), str(value)])
    assert gate.main(arguments) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["observation_valid"] is True
    assert report["handoff_arm"] == "b"
    assert report["whole_runtime_complete"] is False


@pytest.mark.parametrize("arm", ["a0", "a", "b"])
def test_real_harbor_handoff_schemas_when_installed(trial, arm):
    if importlib.util.find_spec("harbor") is None:
        pytest.skip("optional Harbor SDK not installed; run in the frozen Harbor environment")
    assert gate.validate_observations(**_handoff_trial(trial, arm))["observation_valid"] is True
