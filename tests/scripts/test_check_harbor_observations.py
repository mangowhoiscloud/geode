"""Offline native export gates; fixture bytes are not actual collection receipts."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.observability.trajectory import _digest_private_event_payload, build_trajectory
from evals.platforms.harbor import (
    _atif_trajectory_from_geode,
    _summarize_usage,
    write_harbor_recording,
)
from scripts.eval import check_harbor_observations as gate

from tests.scripts.test_eval_contract import _run_spec


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


def _projections(agent: Path, full: dict[str, Any]) -> None:
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
        model="gpt-5.6-sol",
        provider="openai",
        source="subscription",
        effort=None,
        version="a" * 40,
        metrics={},
    )
    atif["agent"].update(name="geode-runtime", tool_definitions=[])
    atif["extra"]["configured_root_effort"] = "max"
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


def test_reflection_medium_does_not_inherit_root_max(trial, model_boundary):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    usage["recorded_attempts"][0].update(purpose="cognitive_reflection", effort="medium")
    _replace_usage(root, usage)
    report = gate.validate_observations(**trial)
    assert report["accounting"]["observed_efforts"] == {"medium": 1}
    assert report["accounting"]["purposes"] == {"cognitive_reflection": 1}


def test_legacy_missing_metadata_is_unknown_not_root_default(trial, model_boundary):
    root = trial["trial_dir"]
    usage = json.loads((root / "agent/runtime-result.json").read_text())["usage"]
    for field in ("purpose", "source", "effort"):
        usage["recorded_attempts"][0].pop(field, None)
    _replace_usage(root, usage)
    report = gate.validate_observations(**trial)
    assert report["accounting"]["unknown_metadata_attempts"] == 1
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
