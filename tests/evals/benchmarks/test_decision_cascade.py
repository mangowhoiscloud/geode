"""Arm C routes each frozen judgment Jev-first with one observed Astra escalation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from evals.benchmarks import decision_handoff_runtime as runtime
from evals.benchmarks.decision_cascade import (
    CASCADE_TAU_GRID,
    cascade_stage_summary,
    cascade_tau,
    cascade_tau_from_selection,
    choice_q,
    decision_receipts,
    primary_route,
)
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL

from tests.scripts.test_decision_handoff_runtime import (
    _Adapter,
    _call,
    _inbox_case,
    _isolated_runtime,  # noqa: F401 - autouse offline runtime isolation
    _response,
    _root_adapter,
)

_LABELS = ("supported", "contradicted", "insufficient_evidence")
_TAU = "0.85"


def astra_answer(verdict: str) -> str:
    """Matched Astra verdict text in contract V1 form (verdict and label probabilities)."""
    return json.dumps(
        {"verdict": verdict, "probabilities": {k: float(k == verdict) for k in _LABELS}}
    )


def jev_body(verdict: str | None, q: float = 1.0) -> dict[str, Any]:
    if verdict is None:
        answers: Any = "malformed"
    else:
        rest = (1.0 - q) / 2
        probabilities = {label: q if label == verdict else rest for label in _LABELS}
        answers = {
            "verdict": {
                "type": "choice",
                "choice": verdict,
                "probabilities": probabilities,
                "confidence": (3 * q - 1) / 2,
            }
        }
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 20, "output_tokens": 2},
        "answers": answers,
    }


def _answers(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    answer = {"items": [{"id": item["id"], **item["expected_answer"]} for item in case["items"]]}
    wrong = json.loads(json.dumps(answer))
    wrong["items"][0]["status"] = "invented"
    return answer, wrong


def _lookup(case: dict[str, Any]) -> Any:
    return _response(
        calls=(
            _call(
                "lookup_order_status",
                "lookup-1",
                {
                    "items": [
                        {"id": item["id"], "order_id": item["expected_order"]}
                        for item in case["items"]
                        if item["expected_answer"]["disposition"] == "answered"
                    ]
                },
            ),
        )
    )


_PLAN = json.dumps(
    {
        "steps": [
            {
                "id": "repair",
                "description": "Correct the observed status",
                "expected_outcome": "Answer matches the recorded lookup",
            }
        ],
        "reasoning": "The verifier requested an evidence-based correction.",
    }
)


def _run_cascade(
    tmp_path: Path,
    *,
    candidates: list[str],
    jev: list[dict[str, Any] | BaseException],
    astra: list[Any],
    tau: str = _TAU,
) -> tuple[dict[str, Any], dict[str, Any], _Adapter, list[dict[str, Any]]]:
    case, orders = _inbox_case()
    directory = tmp_path / "cascade"
    directory.mkdir()
    root_rows: list[Any] = [_lookup(case)]
    for index, text in enumerate(candidates):
        if index:
            root_rows.append(_response(_PLAN))
        root_rows.append(_response(text))
    root = _root_adapter(root_rows)
    judge = _Adapter(astra)
    bodies = iter(jev)
    payloads: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        body = next(bodies)
        if isinstance(body, BaseException):
            raise httpx.ConnectError("synthetic Jev transport failure", request=request)
        return httpx.Response(200, json=body)

    async def execute() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await runtime.run_arm(
                case,
                "a0",
                directory,
                orders=orders,
                root_adapter=root,
                verification_engine="cascade",
                verification_adapter=judge,
                client=client,
                cascade_tau=tau,
            )

    result = asyncio.run(execute())
    evidence = json.loads((directory / "verification.json").read_text())
    return result, evidence, judge, payloads


def _judge_calls(result: dict[str, Any]) -> list[str]:
    return [
        str(row["model"])
        for row in result["call_accounting"]
        if row["purpose"] == "turn_verification"
    ]


def test_tau_grid_matches_preregistration_and_selection_freeze() -> None:
    assert cascade_tau("0.85") == "0.85"
    assert CASCADE_TAU_GRID[0] == "0.50" and CASCADE_TAU_GRID[-3:] == ("0.975", "0.99", "1.00")
    assert len(CASCADE_TAU_GRID) == 13
    for value in ("0.86", 0.85, None, "", " 0.85", "1.0"):
        with pytest.raises(ValueError, match="frozen tau"):
            cascade_tau(value)
    assert cascade_tau_from_selection(0.85) == "0.85"
    assert cascade_tau_from_selection(0.5) == "0.50"
    assert cascade_tau_from_selection(1.0) == "1.00"
    assert cascade_tau_from_selection(0.975) == "0.975"
    for value in (None, 0.86, "0.85", True):
        with pytest.raises(ValueError):
            cascade_tau_from_selection(value)


def test_q_is_the_maximum_label_probability_and_rejection_escalates() -> None:
    native = {"choice": "supported", "probabilities": {"supported": 0.7, "contradicted": 0.3}}
    assert choice_q(native) == 0.7
    admitted = {"accepted": True, "native_answer": native, "q": 0.7}
    assert primary_route(admitted, "0.70")["admitted"] is True
    assert primary_route(admitted, "0.75") == {
        "stage": "primary",
        "tau": "0.75",
        "q": 0.7,
        "admitted": False,
    }
    rejected = primary_route({"accepted": False, "native_answer": None, "q": None}, "0.50")
    assert rejected == {"stage": "primary", "tau": "0.50", "q": None, "admitted": False}
    # Routing reuses the V1 receipt q and rejects a missing or disagreeing copy.
    for q in (None, 0.9, 1):
        with pytest.raises(ValueError, match="contract V1 q"):
            primary_route({**admitted, "q": q}, "0.50")
    for bad in (
        {},
        {"probabilities": {}},
        {"probabilities": {"a": 1.5}},
        {"probabilities": {"a": True}},
    ):
        with pytest.raises(ValueError):
            choice_q(bad)
    rows = [
        {"cascade": {"stage": "primary", "admitted": False}},
        {"cascade": {"stage": "fallback"}},
        {"cascade": {"stage": "primary", "admitted": True}},
    ]
    assert decision_receipts(rows) == rows[1:]


def test_admitted_jev_decision_stands_without_astra_dispatch(tmp_path: Path) -> None:
    case, _ = _inbox_case()
    answer, _wrong = _answers(case)
    result, evidence, judge, payloads = _run_cascade(
        tmp_path, candidates=[json.dumps(answer)], jev=[jev_body("supported", 0.9)], astra=[]
    )
    assert result["valid"] and result["passed"], result
    assert _judge_calls(result) == [JEV_MODEL]
    assert not judge.requests and len(payloads) == 1
    (row,) = evidence["judgments"]
    assert row["engine"] == "jev"
    assert row["cascade"] == {"stage": "primary", "tau": _TAU, "q": 0.9, "admitted": True}
    assert result["cascade_tau"] == _TAU and result["verification_engine"] == "cascade"
    assert result["verification_metrics"]["cascade"] == {
        "jev_primaries": 1,
        "jev_admitted": 1,
        "astra_fallbacks": 0,
        "routing_failures": 0,
    }


def test_low_q_escalates_once_and_the_root_consumes_astra_feedback(tmp_path: Path) -> None:
    case, _ = _inbox_case()
    answer, wrong = _answers(case)
    result, evidence, judge, payloads = _run_cascade(
        tmp_path,
        candidates=[json.dumps(wrong), json.dumps(answer)],
        jev=[jev_body("contradicted", 0.6), jev_body("supported", 0.95)],
        astra=[_response(astra_answer("contradicted"), input_tokens=20)],
    )
    assert result["valid"] and result["passed"], result
    assert result["handoff_call_coverage_complete"]
    assert _judge_calls(result) == [JEV_MODEL, ROOT_MODEL, JEV_MODEL]
    assert len(judge.requests) == 1 and len(payloads) == 2
    primary, fallback, final = evidence["judgments"]
    assert primary["cascade"] == {"stage": "primary", "tau": _TAU, "q": 0.6, "admitted": False}
    assert fallback["engine"] == "llm" and fallback["verdict"] == "contradicted"
    assert fallback["cascade"] == {
        "stage": "fallback",
        "tau": _TAU,
        "primary_call_id": primary["llm_call_id"],
    }
    assert final["cascade"]["admitted"] is True
    first, second, third = evidence["inputs"]
    assert first["state_sha256"] == second["state_sha256"]
    assert second["receipt_prefix_length"] == first["receipt_prefix_length"] + 1
    consumed = [
        row["consumed_feedback"] for row in evidence["root_requests"] if row["consumed_feedback"]
    ]
    assert consumed == [
        [{"judge_call_id": fallback["llm_call_id"], "feedback_sha256": fallback["feedback_sha256"]}]
    ]
    receipts = json.loads((tmp_path / "cascade/handoff.json").read_text())
    judge_rows = [row["llm_call_id"] for row in receipts if row["kind"] == "verification_request"]
    assert judge_rows == [row["llm_call_id"] for row in evidence["inputs"]]
    summary = cascade_stage_summary(
        judge_rows,
        {row["llm_call_id"]: row for row in evidence["inputs"]},
        {row["llm_call_id"]: row for row in evidence["judgments"]},
        {
            row["llm_call_id"]: row
            for row in result["usage"]["recorded_attempts"]
            if row["purpose"] == "turn_verification"
        },
        _TAU,
    )
    assert summary == {
        "judge_calls": 3,
        "jev_primaries": 2,
        "jev_admitted": 1,
        "astra_fallbacks": 1,
        "unanswered_calls": 0,
    }
    assert result["verification_metrics"]["cascade"]["astra_fallbacks"] == 1
    # The Harbor checker admits the real runtime artifacts, not only a synthetic fixture.
    from scripts.eval.check_harbor_observations import _verification_check

    directory = tmp_path / "cascade"
    checked = _verification_check(
        evidence,
        engine="cascade",
        receipt=receipts,
        attempts=result["usage"]["recorded_attempts"],
        call_events=json.loads((directory / "call-events.json").read_text()),
        trajectory=json.loads((directory / "trajectory.private.json").read_text()),
        cascade_tau=_TAU,
    )
    assert checked["cascade"] == summary
    assert checked["completed_judgments"] == 3


def test_rejected_jev_output_always_escalates(tmp_path: Path) -> None:
    case, _ = _inbox_case()
    answer, _wrong = _answers(case)
    result, evidence, judge, _ = _run_cascade(
        tmp_path,
        candidates=[json.dumps(answer)],
        jev=[jev_body(None)],
        astra=[_response(astra_answer("supported"), input_tokens=20)],
    )
    assert result["valid"] and result["passed"], result
    assert _judge_calls(result) == [JEV_MODEL, ROOT_MODEL]
    primary, fallback = evidence["judgments"]
    assert primary["accepted"] is False and primary["cascade"]["q"] is None
    assert fallback["engine"] == "llm" and fallback["accepted"] is True


def test_failed_escalation_fails_closed_and_invalidates_the_trial(tmp_path: Path) -> None:
    case, _ = _inbox_case()
    answer, _wrong = _answers(case)
    result, evidence, _, _ = _run_cascade(
        tmp_path,
        candidates=[json.dumps(answer)],
        jev=[jev_body("supported", 0.6)],
        astra=[ConnectionError("synthetic Astra failure")],
    )
    assert not result["valid"] and not result["passed"]
    assert result["verification_metrics"]["cascade"]["routing_failures"] == 1
    assert [row["engine"] for row in evidence["judgments"]] == ["jev"]
    assert len(evidence["inputs"]) == 2  # The escalation was dispatched and recorded as failed.
    assert any(row.get("error_type") for row in result["call_accounting"])


def test_jev_transport_failure_is_not_rescued_by_astra(tmp_path: Path) -> None:
    case, _ = _inbox_case()
    answer, _wrong = _answers(case)
    result, evidence, judge, _ = _run_cascade(
        tmp_path,
        candidates=[json.dumps(answer)],
        jev=[ConnectionError("synthetic")],
        astra=[_response(astra_answer("supported"))],
    )
    assert not result["valid"] and not result["passed"]
    assert not judge.requests and evidence["judgments"] == []


@pytest.mark.parametrize(
    ("engine", "tau", "primitive", "message"),
    [
        ("cascade", None, "choice", "exactly its frozen tau"),
        ("jev", _TAU, "choice", "exactly its frozen tau"),
        ("cascade", "1.0", "choice", "frozen tau"),
        ("cascade", _TAU, "noul", "Choice verdict only"),
    ],
)
def test_arm_c_contract_is_rejected_before_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
    tau: str | None,
    primitive: str,
    message: str,
) -> None:
    from unittest.mock import Mock

    bootstrap = Mock()
    monkeypatch.setattr("core.llm.adapters.registry.bootstrap_builtins", bootstrap)
    case, orders = _inbox_case()
    root = _root_adapter([])
    with pytest.raises(ValueError, match=message):
        asyncio.run(
            runtime.run_arm(
                case,
                "a0",
                tmp_path,
                orders=orders,
                root_adapter=root,
                verification_engine=engine,
                verification_primitive=primitive,
                cascade_tau=tau,
            )
        )
    bootstrap.assert_not_called()
    assert not root.requests


def _summary_fixture() -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    native = {"probabilities": {"supported": 0.6, "contradicted": 0.4}}
    inputs = {
        "j1": {"state_sha256": "s", "candidate_call_id": "c", "receipt_prefix_length": 4},
        "j2": {"state_sha256": "s", "candidate_call_id": "c", "receipt_prefix_length": 5},
    }
    judgments = {
        "j1": {
            "engine": "jev",
            "accepted": True,
            "native_answer": native,
            "q": 0.6,
            "cascade": {"stage": "primary", "tau": _TAU, "q": 0.6, "admitted": False},
        },
        "j2": {
            "engine": "llm",
            "accepted": True,
            "cascade": {"stage": "fallback", "tau": _TAU, "primary_call_id": "j1"},
        },
    }
    observed = {"j1": {"model": JEV_MODEL}, "j2": {"model": ROOT_MODEL}}
    return ["j1", "j2"], inputs, judgments, observed


@pytest.mark.parametrize(
    "fault",
    [
        "missing-escalation",
        "admitted-escalated",
        "tau",
        "q",
        "state",
        "adjacency",
        "route",
        "orphan-astra",
    ],
)
def test_stage_summary_rejects_wrong_judgment_to_call_mapping(fault: str) -> None:
    ids, inputs, judgments, observed = _summary_fixture()
    assert cascade_stage_summary(ids, inputs, judgments, observed, _TAU)["astra_fallbacks"] == 1
    if fault == "missing-escalation":
        ids = ids[:1]
    elif fault == "admitted-escalated":
        judgments["j1"]["native_answer"] = {
            "probabilities": {"supported": 0.9, "contradicted": 0.1}
        }
        judgments["j1"]["q"] = 0.9
        judgments["j1"]["cascade"].update(q=0.9, admitted=True)
    elif fault == "tau":
        judgments["j1"]["cascade"]["tau"] = "0.80"
    elif fault == "q":
        judgments["j1"]["cascade"]["q"] = 0.61
    elif fault == "state":
        inputs["j2"]["state_sha256"] = "other"
    elif fault == "adjacency":
        inputs["j2"]["receipt_prefix_length"] = 7
    elif fault == "route":
        observed["j2"] = {"model": JEV_MODEL}
    else:
        ids, observed = ["j2"], {"j2": observed["j2"]}
    with pytest.raises(ValueError):
        cascade_stage_summary(ids, inputs, judgments, observed, _TAU)


def test_stage_summary_does_not_escalate_a_jev_transport_failure() -> None:
    ids, inputs, judgments, observed = _summary_fixture()
    summary = cascade_stage_summary(ids[:1], inputs, {}, observed, _TAU)
    assert summary["unanswered_calls"] == 1 and summary["astra_fallbacks"] == 0
    with pytest.raises(ValueError, match="requires an escalated Jev primary"):
        cascade_stage_summary(ids, inputs, {"j2": judgments["j2"]}, observed, _TAU)
