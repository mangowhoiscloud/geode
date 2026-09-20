"""Run the real handoff loop, tools, observations and oracle without live providers."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from scripts.eval import decision_handoff_pilot as pilot


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from core import paths
    from core.config import settings
    from core.llm import token_tracker, usage_store

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(paths, "GEODE_HOME", tmp_path / "geode-home")
    monkeypatch.setattr(usage_store, "_store", usage_store.UsageStore(tmp_path / "usage"))
    monkeypatch.setattr(settings, "cognitive_reflection_enabled", False)
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setenv("GEODE_VERIFY_MODE", "rule_based")
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-key")
    token = token_tracker._tracker_ctx.set(token_tracker.TokenTracker())
    try:
        yield
    finally:
        token_tracker._tracker_ctx.reset(token)


class _Adapter:
    name = "mock-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, responses: list[AdapterCallResult | BaseException]) -> None:
        self.responses = iter(responses)
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def _response(
    text: str = "", *, calls: tuple[dict[str, Any], ...] = (), input_tokens: int = 10
) -> AdapterCallResult:
    return AdapterCallResult(
        text=text,
        tool_uses=calls,
        stop_reason="completed",
        response_model=pilot.MODEL,
        usage=UsageSummary(
            input_tokens=input_tokens,
            output_tokens=2,
            cached_input_tokens=0,
            cache_write_tokens=0,
            cached_input_tokens_present=True,
            cache_write_tokens_present=True,
        ),
    )


def _call(name: str, identifier: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": identifier, "name": name, "input": arguments or {}}


def _case(identifier: str) -> dict[str, Any]:
    return next(case for case in json.loads(pilot.FIXTURE.read_text()) if case["id"] == identifier)


def _decisions(case: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    orders = list(dict.fromkeys(re.findall(r"\b[A-Z]-\d{3}\b", case["request"])))
    target = f"order_{orders.index(case['expected_order'])}" if case["expected_order"] else "none"
    decision = {"intent": case["expected_intent"], "target": target}
    answers = {}
    for name, choices in (
        ("intent", ["status_only", "cancel", "refund", "other"]),
        ("target", [*[f"order_{index}" for index in range(len(orders))], "none"]),
    ):
        answers[name] = {
            "type": "choice",
            "choice": decision[name],
            "probabilities": {choice: float(choice == decision[name]) for choice in choices},
            "confidence": 1.0,
        }
    return decision, {
        "model": pilot.JEV_MODEL,
        "usage": {"input_tokens": 20, "output_tokens": 2},
        "answers": answers,
    }


def _root_responses(
    case: dict[str, Any], *, mode: str = "normal"
) -> list[AdapterCallResult | BaseException]:
    analysis = _call("analyze_request", "analysis-1")
    lookup = _call("lookup_order_status", "lookup-1", {"order_id": case["expected_order"]})
    final = dict(case["expected_answer"])
    if mode == "wrong_answer":
        final["status"] = "invented"
    if mode == "fake_handoff":
        return [_response(json.dumps(final))]
    if mode == "same_batch":
        return [_response(calls=(analysis, lookup)), _response(json.dumps(final))]
    rows: list[AdapterCallResult | BaseException] = [_response(calls=(analysis,))]
    if mode == "root_error":
        rows.append(ValueError("synthetic root failure"))
        return rows
    if case["expected_answer"]["disposition"] == "answered":
        rows.append(_response(calls=(lookup,)))
    rows.append(_response(json.dumps(final)))
    return rows


async def _run(
    case: dict[str, Any], arm: str, directory: Path, *, mode: str = "normal"
) -> tuple[dict[str, Any], _Adapter, _Adapter, list[dict[str, Any]]]:
    directory.mkdir()
    decision, body = _decisions(case)
    root_case = case
    if mode in {"helper_wrong_recovered", "helper_wrong_followed"}:
        orders = list(dict.fromkeys(re.findall(r"\b[A-Z]-\d{3}\b", case["request"])))
        wrong_order = next(order for order in orders if order != case["expected_order"])
        decision["target"] = f"order_{orders.index(wrong_order)}"
        target = body["answers"]["target"]
        target["choice"] = decision["target"]
        target["probabilities"] = {
            key: float(key == decision["target"]) for key in target["probabilities"]
        }
        if mode == "helper_wrong_followed":
            root_case = {
                **case,
                "expected_order": wrong_order,
                "expected_answer": {
                    "order_id": wrong_order,
                    "status": "shipped" if wrong_order == "A-104" else "delivered",
                    "disposition": "answered",
                },
            }
    root = _Adapter(_root_responses(root_case, mode=mode))
    decision_result = _response(json.dumps(decision), input_tokens=20)
    if mode == "helper_refusal":
        decision_result = replace(decision_result, stop_reason="refusal")
        body["answers"]["intent"]["type"] = "refusal"
    elif mode == "helper_shape":
        decision_result = replace(decision_result, text="malformed decision")
        body["answers"] = "malformed decision"
    elif mode == "helper_schema":
        decision_result = replace(decision_result, text='{"intent":"unknown","target":"none"}')
        body["answers"]["intent"]["choice"] = "unknown"
    elif mode == "helper_model":
        decision_result = replace(decision_result, response_model="different-model")
        body["model"] = "different-model"
    elif mode == "helper_usage":
        decision_result = replace(
            decision_result,
            usage=UsageSummary(input_tokens_present=False, output_tokens_present=False),
        )
        body["usage"] = {}
    helper = _Adapter(
        [
            ConnectionError("synthetic transport failure")
            if mode == "helper_transport"
            else decision_result
        ]
    )
    requests: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        if mode == "helper_transport":
            raise httpx.ConnectError("synthetic transport failure", request=request)
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await pilot.run_arm(
            case, arm, directory, decision_adapter=helper, root_adapter=root, client=client
        )
    return result, root, helper, requests


@pytest.mark.parametrize("arm", ["a", "b"])
def test_real_root_continues_after_source_bound_decision(arm: str, tmp_path: Path) -> None:
    case = _case("corrected-target-ko")
    directory = tmp_path / f"run-{arm}"
    result, root, helper, requests = asyncio.run(_run(case, arm, directory))
    assert result["valid"] and result["passed"], json.dumps(
        {"oracle": result["oracle"], "native_verify": result["native_verify"]}, indent=2
    )
    assert all(result["oracle"]["checks"].values())
    assert result["oracle"]["component_matches"]
    assert len(root.requests) == 3
    assert len(helper.requests) == (1 if arm == "a" else 0)
    assert len(requests) == (1 if arm == "b" else 0)
    assert all(
        request.model == pilot.MODEL and request.effort == "xhigh" for request in root.requests
    )
    assert [row["purpose"] for row in result["call_accounting"]].count("structured_decision") == 1
    assert len(result["call_accounting"]) == 4
    assert sum(row["usage"]["input_tokens"] for row in result["call_accounting"]) == 50
    assert result["usage"]["attempt_pairing_complete"]
    handoff = json.loads((directory / "handoff.json").read_text())
    root_rows = [row for row in handoff if row["kind"] == "root_request"]
    assert root_rows[0]["tool_result_ids"] == []
    assert "analysis-1" in root_rows[1]["tool_result_ids"]
    assert "lookup-1" in root_rows[2]["tool_result_ids"]
    trajectory = json.loads((directory / "trajectory.json").read_text())
    assert trajectory["outcome"] == {"scored": False}
    assert trajectory["integrity"]["scope_complete"]
    assert not trajectory["integrity"]["replay_complete"]
    assert trajectory["events"][-1]["kind"] == "session.ended"
    assert "synthetic-test-key" not in json.dumps(trajectory)
    assert (directory / "session-events.json").stat().st_size > 0


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("case_id", ["ambiguous-target", "missing-target", "unsupported-mutation"])
def test_root_handles_unavailable_action_or_target_without_lookup(
    arm: str, case_id: str, tmp_path: Path
) -> None:
    directory = tmp_path / "run"
    result, root, _, _ = asyncio.run(_run(_case(case_id), arm, directory))
    assert result["valid"] and result["passed"], result
    assert len(root.requests) == 2
    assert result["oracle"]["checks"]["lookup_matches"]
    handoff = json.loads((directory / "handoff.json").read_text())
    assert [row["tool"] for row in handoff if row["kind"] == "tool_result"] == ["analyze_request"]


@pytest.mark.parametrize("mode", ["wrong_answer", "fake_handoff", "same_batch"])
def test_mechanical_completion_cannot_replace_task_or_handoff_evidence(
    mode: str, tmp_path: Path
) -> None:
    result, _, _, _ = asyncio.run(
        _run(_case("negated-cancel-en"), "a", tmp_path / "run", mode=mode)
    )
    assert not result["passed"]
    assert result["valid"], result
    assert not result["oracle"]["passed"]
    failed_check = {
        "wrong_answer": "answer_matches",
        "fake_handoff": "analysis_first",
        "same_batch": "lookup_after_interpretation",
    }[mode]
    assert result["oracle"]["checks"][failed_check] is False


def test_root_failure_preserves_completed_usage_and_invalidates_result(tmp_path: Path) -> None:
    directory = tmp_path / "run"
    result, root, _, _ = asyncio.run(
        _run(_case("negated-cancel-en"), "a", directory, mode="root_error")
    )
    assert not result["valid"] and not result["passed"]
    assert len(root.requests) == 2
    failed = [row for row in result["call_accounting"] if row["error_type"]]
    assert len(failed) == 1
    assert failed[0]["error_type"] == "ValueError"
    assert failed[0]["usage"]["input_tokens"] is None
    assert failed[0]["usage"]["output_tokens"] is None
    assert sum(row["usage"]["input_tokens"] or 0 for row in result["call_accounting"]) == 30
    assert (directory / "handoff.json").is_file()
    assert (directory / "trajectory.json").is_file()


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("mode", ["helper_refusal", "helper_shape", "helper_schema"])
def test_rejected_helper_response_is_valid_failure_without_losing_usage(
    arm: str, mode: str, tmp_path: Path
) -> None:
    directory = tmp_path / "run"
    result, _, helper, _ = asyncio.run(_run(_case("negated-cancel-en"), arm, directory, mode=mode))
    assert result["valid"] and not result["passed"], result
    assert result["error_type"] == "decision_response_rejected"
    assert len(helper.requests) == (1 if arm == "a" else 0)
    decision_calls = [
        row for row in result["call_accounting"] if row["purpose"] == "structured_decision"
    ]
    assert len(decision_calls) == 1
    assert decision_calls[0]["usage"]["input_tokens"] == 20
    assert decision_calls[0]["usage"]["output_tokens"] == 2
    assert decision_calls[0]["error_type"] is None
    handoff = json.loads((directory / "handoff.json").read_text())
    analyses = [row for row in handoff if row.get("tool") == "analyze_request"]
    assert len(analyses) == 1 and "error" in analyses[0]["result"]
    assert "result" not in analyses[0]["result"]


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("mode", ["helper_transport", "helper_model", "helper_usage"])
def test_helper_observation_or_route_failure_remains_invalid(
    arm: str, mode: str, tmp_path: Path
) -> None:
    result, _, _, _ = asyncio.run(
        _run(_case("negated-cancel-en"), arm, tmp_path / "run", mode=mode)
    )
    assert not result["valid"] and not result["passed"]
    calls = [row for row in result["call_accounting"] if row["purpose"] == "structured_decision"]
    assert len(calls) == 1
    if mode == "helper_model":
        assert calls[0]["usage"]["input_tokens"] == 20
        assert calls[0]["error_type"] is None
    else:
        assert calls[0]["usage"]["input_tokens"] is None


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("recovered", [True, False])
def test_wrong_helper_decision_does_not_determine_root_task_success(
    arm: str, recovered: bool, tmp_path: Path
) -> None:
    mode = "helper_wrong_recovered" if recovered else "helper_wrong_followed"
    result, root, _, _ = asyncio.run(
        _run(_case("corrected-target-ko"), arm, tmp_path / "run", mode=mode)
    )
    assert result["valid"] and result["passed"] is recovered, result
    assert result["oracle"]["component_matches"] is False
    assert result["oracle"]["checks"]["results_consumed_by_root"] is True
    assert result["oracle"]["checks"]["lookup_after_interpretation"] is True
    assert result["oracle"]["checks"]["lookup_matches"] is recovered
    assert len(root.requests) == 3


@pytest.mark.parametrize("failure_at", ["constructor", "snapshot"])
def test_owned_resources_close_when_initialization_or_snapshot_fails(
    failure_at: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.hooks import system
    from core.observability.event_store import HookEventStore

    case = _case("negated-cancel-en")
    _, body = _decisions(case)
    hooks: list[system.HookSystem] = []
    initialize_hooks = system.HookSystem.__init__

    def track_hooks(instance: system.HookSystem) -> None:
        initialize_hooks(instance)
        hooks.append(instance)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    monkeypatch.setattr(system.HookSystem, "__init__", track_hooks)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    root = _Adapter(_root_responses(case))
    if failure_at == "constructor":
        case = {**case, "request": ""}
        expected_error: type[Exception] = ValueError
    else:
        expected_error = OSError
        read = HookEventStore.read

        def fail_snapshot(store: HookEventStore, *args: Any, **kwargs: Any) -> Any:
            if len(root.requests) == 3:
                raise OSError("synthetic snapshot failure")
            return read(store, *args, **kwargs)

        monkeypatch.setattr(HookEventStore, "read", fail_snapshot)
    directory = tmp_path / "run"
    directory.mkdir()
    with pytest.raises(expected_error):
        asyncio.run(pilot.run_arm(case, "b", directory, root_adapter=root))
    assert hooks and all(instance.closed for instance in hooks) and client.is_closed
    assert len(root.requests) == (0 if failure_at == "constructor" else 3)


@pytest.mark.parametrize("missing", ["checkpoint", "timeline"])
def test_missing_canonical_store_rejects_before_model_dispatch(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.memory.session_checkpoint import SessionCheckpoint
    from core.observability.session_timeline import SessionTimeline

    def fail_initialization(*_: Any, **__: Any) -> None:
        raise OSError("synthetic storage unavailable")

    owner = SessionCheckpoint if missing == "checkpoint" else SessionTimeline
    monkeypatch.setattr(owner, "__init__", fail_initialization)
    root = _Adapter([])
    helper = _Adapter([])
    with pytest.raises(RuntimeError, match="canonical checkpoint or session timeline"):
        asyncio.run(
            pilot.run_arm(
                _case("negated-cancel-en"),
                "a",
                tmp_path,
                root_adapter=root,
                decision_adapter=helper,
            )
        )
    assert not root.requests and not helper.requests


@pytest.mark.parametrize("missing", ["terminal", "tool_result"])
def test_incomplete_canonical_evidence_cannot_pass(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.observability.session_timeline import SessionTimeline

    method = "record_session_end" if missing == "terminal" else "record_tool_result"
    monkeypatch.setattr(SessionTimeline, method, lambda *_args, **_kwargs: None)
    directory = tmp_path / "run"
    result, _, _, _ = asyncio.run(_run(_case("negated-cancel-en"), "a", directory))
    assert result["oracle"]["passed"]
    assert not result["valid"] and not result["passed"]
    assert result["error_type"] == "incomplete_session_evidence"
    trajectory = json.loads((directory / "trajectory.json").read_text())
    assert not trajectory["integrity"]["scope_complete"]
    if missing == "tool_result":
        assert trajectory["events"][-1]["kind"] == "session.ended"
    assert sum(row["usage"]["input_tokens"] for row in result["call_accounting"]) == 50


def test_baseline_does_not_allocate_typesafe_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_client(**_: Any) -> None:
        raise AssertionError("baseline must not construct a TypeSafe HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    case = _case("negated-cancel-en")
    decision, _ = _decisions(case)
    directory = tmp_path / "run"
    directory.mkdir()
    result = asyncio.run(
        pilot.run_arm(
            case,
            "a",
            directory,
            root_adapter=_Adapter(_root_responses(case)),
            decision_adapter=_Adapter([_response(json.dumps(decision), input_tokens=20)]),
        )
    )
    assert result["valid"] and result["passed"]


def test_child_clears_inherited_financial_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_COST_LIMIT_USD", "0.0001")
    directory = tmp_path / "child"
    directory.mkdir()
    probe = """
import sys
from pathlib import Path
from scripts.eval import decision_handoff_pilot as pilot

async def inspect_settings(case, arm, directory):
    from core.config import settings
    from core.paths import GEODE_HOME, STATE_ROOT
    return {"cost_limit_usd": settings.cost_limit_usd,
            "geode_home": str(GEODE_HOME), "state_root": str(STATE_ROOT)}

pilot.run_arm = inspect_settings
pilot._run_child(0, "a", Path(sys.argv[1]))
"""
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe, str(directory)],
        cwd=pilot.ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads((directory / "result.json").read_text())
    assert result == {
        "cost_limit_usd": 0,
        "geode_home": str(directory / "geode-home"),
        "state_root": str(directory / "state"),
    }
