"""Arm C checker contract: each judgment maps to a Jev primary and at most one escalation.

Receipts come from the real matched adapters over offline transports, so the fixture
follows whichever judgment contract is installed. The frozen Harbor 0.22.0 schema cases
at the end also cover Noul; they skip unless that exact SDK is installed, e.g.
``uv run --offline --with harbor==0.22.0 pytest -q tests/scripts/test_check_harbor_cascade.py``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    UsageSummary,
)
from core.observability.trajectory import build_trajectory
from evals.benchmarks.decision_cascade import primary_route
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL
from evals.benchmarks.decision_handoff_runtime import INBOX_SYSTEM, _json_digest
from evals.benchmarks.decision_verification import MatchedVerifierAdapter
from evals.platforms.harbor import _summarize_usage
from pydantic import SecretStr
from scripts.eval import check_harbor_observations as gate

from tests.evals.benchmarks.test_decision_cascade import astra_answer, jev_body
from tests.scripts import test_check_harbor_observations as _checker_tests

# Shared fixtures and builders; pytest registers fixture objects bound as module attributes.
trial = _checker_tests.trial
model_boundary = _checker_tests.model_boundary
_handoff_trial = _checker_tests._handoff_trial
_projections = _checker_tests._projections
_rewrite = _checker_tests._rewrite
_write = _checker_tests._write

TAU = "0.85"
_MODEL = {"provider": "openai", "label": ROOT_MODEL, "route": "subscription", "reasoning": "xhigh"}
_STATE = {
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
# scenario -> Jev primary (verdict, q) and the Astra escalation verdict, if any
_SCENARIOS: dict[str, tuple[tuple[str | None, float], str | None]] = {
    "admitted": (("supported", 0.9), None),
    "escalated": (("supported", 0.6), "supported"),
    "rejected": ((None, 1.0), "supported"),
}


class _Astra:
    name = "synthetic-astra"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, call_id: str, verdict: str) -> None:
        self.result = AdapterCallResult(
            text=astra_answer(verdict),
            usage=UsageSummary(input_tokens=10, output_tokens=2),
            stop_reason="completed",
            response_model=ROOT_MODEL,
            response_id="response-" + call_id,
        )

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        return self.result


def _receipt(engine: str, call_id: str, verdict: str | None, q: float = 1.0) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    request = AdapterCallRequest(
        model=JEV_MODEL if engine == "jev" else ROOT_MODEL,
        messages=(Message("user", json.dumps(_STATE)),),
        effort="none" if engine == "jev" else "xhigh",
        tool_choice="none",
        allowed_tool_names=frozenset(),
        metadata={"verification_correlation": {"llm_call_id": call_id, "step_id": "step-judge"}},
    )

    async def run() -> None:
        if engine == "llm":
            assert verdict is not None
            adapter = MatchedVerifierAdapter(
                "llm", llm_adapter=_Astra(call_id, verdict), receipts=receipts
            )
            await adapter.acomplete(request)
            return

        def transport(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=jev_body(verdict, q),
                headers={"x-typesafe-request-id": "response-" + call_id},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = MatchedVerifierAdapter(
                "jev", client=client, api_key=SecretStr("synthetic-key"), receipts=receipts
            )
            await adapter.acomplete(request)

    asyncio.run(run())
    (row,) = receipts
    return row


def _cascade_trial(trial: dict[str, Any], scenario: str = "escalated") -> dict[str, Any]:
    """Build one arm C Harbor trial through the existing usage/trajectory producers."""
    (jev_verdict, q), astra_verdict = _SCENARIOS[scenario]
    root = trial["trial_dir"]
    agent = root / "agent"
    _rewrite(trial["run_spec_path"], lambda spec: spec["reproduction"].update(model=_MODEL))
    judgments = [_receipt("jev", "call-3", jev_verdict, q)]
    judgments[0]["cascade"] = primary_route(judgments[0], TAU)
    assert judgments[0]["cascade"]["admitted"] is (astra_verdict is None)
    if astra_verdict is not None:
        judgments.append(_receipt("llm", "call-4", astra_verdict))
        judgments[1]["cascade"] = {"stage": "fallback", "tau": TAU, "primary_call_id": "call-3"}
    purposes = ["agentic_loop", "agentic_loop", *["turn_verification"] * len(judgments)]
    events = []
    for index, purpose in enumerate(purposes, 1):
        call_id = f"call-{index}"
        jev = call_id == "call-3"
        judgment = next((row for row in judgments if row["llm_call_id"] == call_id), None)
        payload: dict[str, Any] = {
            "model": JEV_MODEL if jev else ROOT_MODEL,
            "response_model": JEV_MODEL if jev else ROOT_MODEL,
            "provider": "typesafe" if jev else "openai",
            "adapter": "matched-verifier-jev"
            if jev
            else "matched-verifier-llm"
            if judgment is not None
            else "codex_oauth",
            "purpose": purpose,
            "source": "payg" if jev else "subscription",
            "effort": "none" if jev else "xhigh",
            "usage": {
                "input_tokens": 20 if jev else 10,
                "output_tokens": 2,
                "cached_input_tokens": None if jev else 0,
                "cache_write_tokens": None,
            },
            "llm_call_id": call_id,
            "response_id": "response-" + call_id,
        }
        if judgment is not None and judgment.get("response_provider"):
            payload["response_provider"] = judgment["response_provider"]
        identity = {
            "session_id": "session-1",
            "llm_call_id": call_id,
            "llm_attempt_id": f"attempt-{index}",
            "tool_call_id": "",
        }
        events.extend(
            [
                SimpleNamespace(action="llm.call.started", **identity),
                SimpleNamespace(
                    action="llm.call.ended",
                    id=index * 2,
                    occurred_at=1786233661.0 + index,
                    payload_hash=_json_digest(payload),
                    payload=payload,
                    **identity,
                ),
            ]
        )
    usage = _summarize_usage(events)
    usage["source_snapshot_complete"] = True
    tau = {"verification_engine": "cascade", "cascade_tau": TAU}
    _write(
        agent / "handoff-result.json",
        {
            "session_id": "session-1",
            "usage": usage,
            "handoff_call_coverage_complete": True,
            **tau,
        },
    )
    receipt: list[dict[str, Any]] = [
        {"kind": "root_request", "llm_call_id": "call-1"},
        {
            "kind": "tool_result",
            "tool": "lookup_order_status",
            "tool_call_id": "tool-1",
            "result": "ok",
        },
        {"kind": "root_request", "llm_call_id": "call-2"},
    ]
    inputs = []
    for judgment in judgments:
        receipt.append(
            {
                "kind": "verification_request",
                "llm_call_id": judgment["llm_call_id"],
                "step_id": "step-judge",
            }
        )
        inputs.append(
            {
                "llm_call_id": judgment["llm_call_id"],
                "candidate_call_id": "call-2",
                "state": _STATE,
                "state_sha256": _json_digest(_STATE),
                "receipt_prefix_length": len(receipt),
            }
        )
    _write(agent / "handoff.json", receipt)
    definitions = [{"name": "lookup_order_status", "parameters": {}}]
    runtime = json.loads((agent / "runtime-result.json").read_text())
    metadata = runtime["metadata"]
    metadata.update(
        verify_mode="llm_judge", profile="decision-handoff", arm="a0", usage=usage, **tau
    )
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
            model=ROOT_MODEL,
            effort="xhigh",
            verify_mode="llm_judge",
            runtime="evals.benchmarks.decision_handoff_runtime:run_arm",
            profile="decision-handoff",
            arm="a0",
            case_sha256="e" * 64,
            required_tools=["lookup_order_status"],
            workload_profile="inbox",
            **tau,
        ),
    )
    previous = json.loads((agent / "geode-trajectory.private.json").read_text())
    for event in previous["events"]:
        if event["kind"].startswith("tool."):
            event["payload"]["tool"] = "lookup_order_status"
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
        model=ROOT_MODEL,
        agent_name="geode-handoff",
        effort="xhigh",
        tool_definitions=definitions,
    )
    _write(
        agent / "verification.json",
        {
            "inputs": inputs,
            "judgments": judgments,
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
                {"llm_call_id": "call-2", "text": "fixture completion", "tool_uses": []},
            ],
            "root_requests": [
                {
                    "llm_call_id": call_id,
                    "completed_judgments": 0,
                    "system_prompt": INBOX_SYSTEM,
                    "consumed_feedback": [],
                }
                for call_id in ("call-1", "call-2")
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
        "handoff_arm": "a0",
        "handoff_case_sha256": "e" * 64,
        "verification_engine": "cascade",
        "cascade_tau": TAU,
    }


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_cascade_judgment_to_call_mapping_is_admitted(
    trial: dict[str, Any], model_boundary: Any, scenario: str
) -> None:
    report = gate.validate_observations(**_cascade_trial(trial, scenario))
    assert report["observation_valid"] is True
    escalated = _SCENARIOS[scenario][1] is not None
    assert report["verification"]["cascade"] == {
        "judge_calls": 1 + escalated,
        "jev_primaries": 1,
        "jev_admitted": int(not escalated),
        "astra_fallbacks": int(escalated),
        "unanswered_calls": 0,
    }
    assert report["accounting"]["purposes"]["turn_verification"] == 1 + escalated


def _edit_verification(agent: Path, edit: Any) -> None:
    _rewrite(agent / "verification.json", edit)


@pytest.mark.parametrize(
    "fault",
    [
        "tau-argument",
        "tau-contract",
        "tau-metadata",
        "q-tampered",
        "admission-flipped",
        "engine-relabel",
        "fallback-link",
        "fallback-state",
        "missing-tau",
        "noul",
    ],
)
def test_cascade_checker_rejects_wrong_mapping_or_treatment(
    trial: dict[str, Any], model_boundary: Any, fault: str
) -> None:
    arguments = _cascade_trial(trial, "escalated")
    agent = arguments["trial_dir"] / "agent"
    if fault == "tau-argument":
        arguments["cascade_tau"] = "0.80"
    elif fault == "tau-contract":
        _rewrite(agent / "runtime-contract.json", lambda value: value.update(cascade_tau="0.80"))
    elif fault == "tau-metadata":
        _rewrite(agent / "handoff-result.json", lambda value: value.update(cascade_tau="0.80"))
    elif fault == "q-tampered":
        _edit_verification(agent, lambda value: value["judgments"][0]["cascade"].update(q=0.99))
    elif fault == "admission-flipped":
        _edit_verification(
            agent, lambda value: value["judgments"][0]["cascade"].update(admitted=True)
        )
    elif fault == "engine-relabel":
        _edit_verification(agent, lambda value: value["judgments"][1].update(engine="jev"))
    elif fault == "fallback-link":
        _edit_verification(
            agent,
            lambda value: value["judgments"][1]["cascade"].update(primary_call_id="call-2"),
        )
    elif fault == "fallback-state":
        _edit_verification(
            agent, lambda value: value["inputs"][1].update(candidate_call_id="call-1")
        )
    elif fault == "missing-tau":
        arguments["cascade_tau"] = None
    else:
        arguments["verification_primitive"] = "noul"
    with pytest.raises(ValueError):
        gate.validate_observations(**arguments)


def test_admitted_primary_cannot_hide_an_extra_astra_judgment(
    trial: dict[str, Any], model_boundary: Any
) -> None:
    arguments = _cascade_trial(trial, "escalated")
    agent = arguments["trial_dir"] / "agent"

    def admit(value: dict[str, Any]) -> None:
        route = value["judgments"][0]["cascade"]
        route.update(q=0.9, admitted=True)
        probabilities = value["judgments"][0]["native_answer"]["probabilities"]
        probabilities.update(supported=0.9, contradicted=0.05, insufficient_evidence=0.05)

    _edit_verification(agent, admit)
    with pytest.raises(ValueError):
        gate.validate_observations(**arguments)


def test_cli_accepts_cascade_only_with_its_tau(
    trial: dict[str, Any], model_boundary: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = _cascade_trial(trial, "admitted")
    argv = [str(arguments["trial_dir"]), "--run-spec", str(arguments["run_spec_path"])]
    for name in (
        "run_spec_sha256",
        "source_sha256",
        "trial_name",
        "task_name",
        "task_checksum",
        "handoff_arm",
        "handoff_case_sha256",
        "verification_engine",
    ):
        argv.extend(["--" + name.replace("_", "-"), str(arguments[name])])
    assert gate.main(argv) == 1
    assert json.loads(capsys.readouterr().out)["observation_valid"] is False
    assert gate.main([*argv, "--cascade-tau", TAU]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["observation_valid"] is True
    assert report["verification"]["cascade"]["jev_admitted"] == 1


_HARBOR_022 = importlib.util.find_spec("harbor") is not None and (
    importlib.metadata.version("harbor") == "0.22.0"
)
_requires_harbor_022 = pytest.mark.skipif(
    not _HARBOR_022,
    reason="frozen Harbor 0.22.0 SDK not installed; use uv run --offline --with harbor==0.22.0",
)


@_requires_harbor_022
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_real_harbor_022_cascade_schemas(trial: dict[str, Any], scenario: str) -> None:
    assert gate.validate_observations(**_cascade_trial(trial, scenario))["observation_valid"]


@_requires_harbor_022
@pytest.mark.parametrize("engine", ["llm", "jev"])
@pytest.mark.parametrize("conditions", [(False, False), (True, False), (False, True), (True, True)])
def test_real_harbor_022_noul_condition_schemas(
    trial: dict[str, Any], engine: str, conditions: tuple[bool, bool]
) -> None:
    arguments = _handoff_trial(
        trial,
        "a0",
        verification_engine=engine,
        verification_primitive="noul",
        noul_conditions=conditions,
    )
    assert gate.validate_observations(**arguments)["observation_valid"] is True


@_requires_harbor_022
@pytest.mark.parametrize(
    ("arm", "engine"), [("a0", None), ("a", None), ("b", None), ("a0", "llm"), ("a0", "jev")]
)
def test_real_harbor_022_choice_handoff_schemas(
    trial: dict[str, Any], arm: str, engine: str | None
) -> None:
    arguments = _handoff_trial(trial, arm, verification_engine=engine)
    assert gate.validate_observations(**arguments)["observation_valid"] is True
