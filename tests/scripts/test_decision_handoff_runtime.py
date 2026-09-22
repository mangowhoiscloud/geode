"""Run the real handoff loop, tools, observations and oracle without live providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from evals.benchmarks import decision_handoff_runtime as runtime
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
    assert result["handoff_call_coverage_complete"]
    handoff = json.loads((directory / "handoff.json").read_text())
    root_rows = [row for row in handoff if row["kind"] == "root_request"]
    assert root_rows[0]["tool_result_ids"] == []
    assert "analysis-1" in root_rows[1]["tool_result_ids"]
    assert "lookup-1" in root_rows[2]["tool_result_ids"]
    assert {row["llm_call_id"] for row in root_rows} == {
        row["llm_call_id"]
        for row in result["usage"]["recorded_attempts"]
        if row["purpose"] == "agentic_loop"
    }
    trajectory = json.loads((directory / "trajectory.json").read_text())
    assert trajectory["outcome"] == {"scored": False}
    assert trajectory["integrity"]["scope_complete"]
    assert not trajectory["integrity"]["replay_complete"]
    assert trajectory["events"][-1]["kind"] == "session.ended"
    assert "synthetic-test-key" not in json.dumps(trajectory)
    assert (directory / "session-events.json").stat().st_size > 0
    private = json.loads((directory / "trajectory.private.json").read_text())
    assert private["integrity"]["replay_complete"]
    assert private["integrity"]["quality"]["tool_pairing"]["paired"] == 2


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


@pytest.mark.parametrize("case_id", ["negated-cancel-en", "missing-target", "unsupported-mutation"])
def test_unassisted_root_uses_same_lookup_without_helper(
    case_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY")

    def forbidden_client(**_: Any) -> None:
        raise AssertionError("A0 must not allocate a helper HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
    case = _case(case_id)
    root = _Adapter(_root_responses(case)[1:])
    directory = tmp_path / "a0"
    directory.mkdir()
    result = asyncio.run(runtime.run_arm(case, "a0", directory, root_adapter=root))
    assert result["valid"] and result["passed"], result
    assert result["oracle"]["component_matches"] is None
    assert all(row["purpose"] != "structured_decision" for row in result["call_accounting"])
    assert all(
        {tool.name for tool in request.tools} == {"lookup_order_status"}
        for request in root.requests
    )
    assert all("analyze_request" not in request.system_prompt for request in root.requests)
    assert result["tool_definitions"][0]["parameters"] == runtime.StatusLookupTool().parameters
    handoff = json.loads((directory / "handoff.json").read_text())
    assert runtime.verify_handoff_result(case, result, handoff)["passed"]
    assert result["source_snapshot_complete"]
    assert json.loads((directory / "trajectory.private.json").read_text())["integrity"][
        "replay_complete"
    ]


def test_task_verifier_recomputes_final_and_consumed_lookup_evidence(tmp_path: Path) -> None:
    case = _case("negated-cancel-en")
    directory = tmp_path / "a0"
    directory.mkdir()
    result = asyncio.run(
        runtime.run_arm(case, "a0", directory, root_adapter=_Adapter(_root_responses(case)[1:]))
    )
    handoff = json.loads((directory / "handoff.json").read_text())
    result["oracle"] = {"passed": True}
    result["final_text"] = json.dumps({**case["expected_answer"], "status": "invented"})
    assert not runtime.verify_handoff_result(case, result, handoff)["passed"]
    result["final_text"] = json.dumps(case["expected_answer"])
    lookup = next(row for row in handoff if row.get("tool") == "lookup_order_status")
    lookup["result"]["result"]["status"] = "invented"
    assert not runtime.verify_handoff_result(case, result, handoff)["checks"][
        "lookup_results_match"
    ]


def _inbox_case(index: int | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    fixture = json.loads(
        (pilot.ROOT / "evals/benchmarks/fixtures/decision-handoff-inbox.json").read_text()
    )
    case = fixture["admission"] if index is None else fixture["cases"][index]
    case.update(profile="inbox", request=runtime.inbox_request(case["items"]))
    return case, fixture["orders"]


def _inbox_decisions(
    case: dict[str, Any], *, wrong: bool = False
) -> tuple[dict[str, str], dict[str, Any]]:
    values, answers = {}, {}
    for index, item in enumerate(case["items"]):
        target = (
            f"order_{item['candidates'].index(item['expected_order'])}"
            if item["expected_order"] is not None
            else "none"
        )
        if wrong and index == 0:
            target = "order_0"  # Admission's correct target is its second mention.
        for suffix, value, choices in (
            ("intent", item["expected_intent"], ["status_only", "cancel", "refund", "other"]),
            ("target", target, [*[f"order_{i}" for i in range(len(item["candidates"]))], "none"]),
        ):
            key = item["id"] + "_" + suffix
            values[key] = value
            answers[key] = {
                "type": "choice",
                "choice": value,
                "probabilities": {choice: float(choice == value) for choice in choices},
                "confidence": 1.0,
            }
    return values, {
        "model": pilot.JEV_MODEL,
        "usage": {"input_tokens": 20, "output_tokens": 2},
        "answers": answers,
    }


async def _run_inbox(
    case: dict[str, Any],
    orders: dict[str, str],
    arm: str,
    directory: Path,
    *,
    recover: bool = False,
) -> tuple[dict[str, Any], _Adapter, list[dict[str, Any]]]:
    directory.mkdir()
    values, body = _inbox_decisions(case)
    wrong_values, wrong_body = _inbox_decisions(case, wrong=True)
    responses = []
    if arm != "a0":
        responses.append(_response(calls=(_call("analyze_request", "analysis-1"),)))
    if recover:
        responses.extend(
            [
                _response(
                    calls=(
                        _call(
                            "lookup_order_status",
                            "wrong-read",
                            {"items": [{"id": "admit_one", "order_id": "B-209"}]},
                        ),
                    )
                ),
                _response(calls=(_call("analyze_request", "analysis-2"),)),
            ]
        )
    responses.extend(
        [
            _response(
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
            ),
            _response(
                json.dumps(
                    {
                        "items": [
                            {"id": item["id"], **item["expected_answer"]} for item in case["items"]
                        ]
                    }
                )
            ),
        ]
    )
    root = _Adapter(responses)
    helper = _Adapter(
        [
            _response(json.dumps(value), input_tokens=20)
            for value in ([wrong_values, values] if recover else [values])
        ]
    )
    replies = iter([wrong_body, body] if recover else [body])
    payloads = []

    def transport(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=next(replies))

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await runtime.run_arm(
            case,
            arm,
            directory,
            orders=orders,
            root_adapter=root,
            decision_adapter=helper if arm == "a" else None,
            client=client,
        )
    if arm == "a":
        from html import unescape

        payloads = [
            json.loads(
                unescape(
                    str(request.messages[0].content)
                    .removeprefix("<decision_input>")
                    .removesuffix("</decision_input>")
                )
            )
            for request in helper.requests
        ]
    return result, root, payloads


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("arm", ["a0", "a", "b"])
def test_complete_inbox_uses_one_helper_batch_and_one_lookup_batch(
    index: int, arm: str, tmp_path: Path
) -> None:
    case, orders = _inbox_case(index)
    result, root, payloads = asyncio.run(_run_inbox(case, orders, arm, tmp_path / "inbox"))
    assert result["valid"] and result["passed"], result["oracle"]
    assert result["workload_profile"] == "inbox"
    assert len(result["oracle"]["items"]) == 12
    assert result["oracle"]["analysis_call_count"] == (0 if arm == "a0" else 1)
    assert result["oracle"]["rejudgment_call_count"] == 0
    assert result["oracle"]["lookup_attempt_count"] == 1
    assert result["handoff_call_coverage_complete"]
    assert len(root.requests) == (2 if arm == "a0" else 3)
    assert len(result["call_accounting"]) == (2 if arm == "a0" else 4)
    assert all(
        "Status-only intent means order-status information" in request.system_prompt
        and "including requests to take no action" in request.system_prompt
        for request in root.requests
    )
    if arm != "a0":
        assert len(payloads) == 1 and len(payloads[0]["questions"]) == 24
        assert len(payloads[0]["state"]["items"]) == 12
        assert "expected_" not in json.dumps(payloads)
        handoff = json.loads((tmp_path / "inbox/handoff.json").read_text())
        decision = next(row for row in handoff if row.get("tool") == "analyze_request")
        assert decision["result"]["result"]["primitives"] is None
        assert len(decision["native_primitives"] or {}) == (24 if arm == "b" else 0)
        assert all("probabilities" not in repr(request.messages) for request in root.requests)
    assert "expected_" not in case["request"]
    assert (tmp_path / "inbox/trajectory.private.json").is_file()


@pytest.mark.parametrize("index,prefix", [(1, "context"), (2, "ko")])
def test_inbox_semantics_distinguish_order_subject_from_action_and_unrelated_information(
    index: int, prefix: str
) -> None:
    from evals.benchmarks.decision_handoff import DecisionHandoffTool

    case, _ = _inbox_case(index)
    items = {item["id"]: item for item in case["items"]}
    unrelated = items[f"{prefix}_eleven"]
    no_action = items[f"{prefix}_twelve"]
    assert unrelated["expected_intent"] == no_action["expected_intent"] == "other"
    assert unrelated["expected_order"] is None
    assert no_action["expected_order"] == no_action["candidates"][0]
    assert no_action["expected_answer"] == {
        "order_id": no_action["expected_order"],
        "status": None,
        "disposition": "unsupported",
    }
    payload = DecisionHandoffTool(
        case["request"], "a", requests={key: item["request"] for key, item in items.items()}
    )._payload()
    intent = payload["questions"][f"{prefix}_eleven_intent"]["criteria"]["status_only"]
    target = payload["questions"][f"{prefix}_twelve_target"]
    assert "order-status information" in intent
    assert "Unrelated information requests are other" in intent
    assert "even when no action is requested" in target["instructions"]
    assert target["criteria"]["none"] == (
        "No single listed order is the subject of the current request."
    )
    assert "expected_" not in json.dumps(payload)
    legacy = DecisionHandoffTool(no_action["request"], "a")._payload()
    assert legacy["questions"]["intent"]["criteria"]["status_only"] == (
        "The request asks only for information or order status, not a mutation."
    )
    assert legacy["questions"]["target"]["criteria"]["none"] == (
        "No listed order is targeted, or the target is ambiguous."
    )


@pytest.mark.parametrize("arm", ["a", "b"])
def test_inbox_rejudgment_and_wrong_reads_remain_successful_but_counted(
    arm: str, tmp_path: Path
) -> None:
    case, orders = _inbox_case()
    directory = tmp_path / "recovery"
    result, root, payloads = asyncio.run(_run_inbox(case, orders, arm, directory, recover=True))
    assert result["valid"] and result["passed"], result["oracle"]
    oracle = result["oracle"]
    assert oracle["rejudgment_call_count"] == 1 and oracle["rejudged_item_count"] == 2
    assert oracle["wrong_target_lookup_count"] == oracle["extra_lookup_count"] == 1
    assert oracle["helper_rejudgment_recovery_count"] == 1
    assert len(root.requests) == 5 and len(payloads) == 2
    assert len(result["call_accounting"]) == 7
    assert sum(row["usage"]["input_tokens"] for row in result["call_accounting"]) == 90
    handoff = json.loads((directory / "handoff.json").read_text())
    assert runtime.verify_handoff_result(case, result, handoff) == oracle
    result["final_text"] = json.dumps(
        {
            "items": [
                {"id": item["id"], **item["expected_answer"], "status": "invented"}
                for item in case["items"]
            ]
        }
    )
    assert not runtime.verify_handoff_result(case, result, handoff)["passed"]


@pytest.mark.parametrize("fault", ["candidate", "source", "label", "duplicate"])
def test_incomplete_inbox_fails_before_any_model_call(fault: str, tmp_path: Path) -> None:
    case, orders = _inbox_case()
    if fault == "candidate":
        case["items"][0]["candidates"].pop()
    elif fault == "source":
        case["request"] += "unfrozen"
    elif fault == "label":
        case["items"][0]["expected_answer"]["status"] = "invented"
    else:
        case["items"][1]["id"] = case["items"][0]["id"]
    root = _Adapter([])
    with pytest.raises(ValueError):
        asyncio.run(runtime.run_arm(case, "a0", tmp_path, orders=orders, root_adapter=root))
    assert not root.requests


def test_inbox_verifier_runs_standalone_without_runtime_imports(tmp_path: Path) -> None:
    case, orders = _inbox_case()
    directory = tmp_path / "standalone"
    result, _, _ = asyncio.run(_run_inbox(case, orders, "a0", directory))
    (directory / "case.json").write_text(json.dumps(case))
    (directory / "result.json").write_text(json.dumps(result))
    probe = """import json, runpy, sys
from pathlib import Path
directory = Path(sys.argv[2])
verify = runpy.run_path(sys.argv[1])['verify_handoff_result']
case = json.loads((directory / 'case.json').read_text())
result = json.loads((directory / 'result.json').read_text())
handoff = json.loads((directory / 'handoff.json').read_text())
assert verify(case, result, handoff)['passed']
result['final_text'] = '{}'
assert not verify(case, result, handoff)['passed']
assert not any(name == 'core' or name.startswith('core.') for name in sys.modules)
assert not any(name == 'evals' or name.startswith('evals.') for name in sys.modules)
"""
    subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", probe, str(Path(runtime.__file__).resolve()), str(directory)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_controlled_projection_shares_korean_candidate_boundaries() -> None:
    projection = runtime._WrongHelperProjection(
        "E-536이 아니라 F-645의 상태를 알려줘.", {"intent": "status_only", "order_id": "E-536"}
    )
    assert projection.projected["target"] == {"order_id": "E-536", "start": 0, "end": 5}
    with pytest.raises(ValueError, match="listed source span"):
        runtime._WrongHelperProjection(
            "Q-7318의 상태", {"intent": "status_only", "order_id": "Q-731"}
        )


def test_rejected_lookup_attempt_is_not_a_no_lookup_success(tmp_path: Path) -> None:
    case = _case("missing-target")
    directory = tmp_path / "rejected-lookup"
    directory.mkdir()
    root = _Adapter(
        [
            _response(
                calls=(_call("lookup_order_status", "invalid-read", {"order_id": "UNKNOWN"}),)
            ),
            _response(json.dumps(case["expected_answer"])),
        ]
    )
    result = asyncio.run(runtime.run_arm(case, "a0", directory, root_adapter=root))
    assert result["valid"] and not result["passed"]
    assert result["oracle"]["checks"]["answer_matches"]
    assert not result["oracle"]["checks"]["no_lookup_attempt_when_unneeded"]
    assert result["oracle"]["lookup_attempt_count"] == 1
    assert result["oracle"]["rejected_lookup_count"] == 1
    assert result["oracle"]["extra_lookup_count"] == 0
    handoff = json.loads((directory / "handoff.json").read_text())
    assert runtime.verify_handoff_result(case, result, handoff) == result["oracle"]


def test_scoped_runtime_rejects_unadmitted_call_purpose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.agent.loop import _provider_call

    observe = _provider_call.observe_llm_call

    async def unexpected_purpose(*args: Any, **kwargs: Any) -> Any:
        return await observe(*args, **(kwargs | {"purpose": "memory_dreaming"}))

    monkeypatch.setattr(_provider_call, "observe_llm_call", unexpected_purpose)
    case = _case("negated-cancel-en")
    directory = tmp_path / "unexpected-purpose"
    directory.mkdir()
    result = asyncio.run(
        runtime.run_arm(case, "a0", directory, root_adapter=_Adapter(_root_responses(case)[1:]))
    )
    assert result["oracle"]["passed"]
    assert result["usage"]["attempt_pairing_complete"]
    assert {row["purpose"] for row in result["call_accounting"]} == {"memory_dreaming"}
    assert not result["valid"] and not result["passed"]


@pytest.mark.parametrize("purpose", ["agentic_loop", "structured_decision"])
def test_complete_missing_call_pair_cannot_hide_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: str
) -> None:
    from core.observability.event_store import HookEventStore

    original = HookEventStore.read

    def drop_call(self: Any, **kwargs: Any) -> Any:
        rows = original(self, **kwargs)
        missing = next(
            event.llm_call_id
            for event in rows
            if event.action == "llm.call.ended" and event.payload.get("purpose") == purpose
        )
        return [event for event in rows if event.llm_call_id != missing]

    monkeypatch.setattr(HookEventStore, "read", drop_call)
    result, _, _, _ = asyncio.run(_run(_case("negated-cancel-en"), "a", tmp_path / "missing-call"))
    assert result["oracle"]["passed"]
    assert result["usage"]["attempt_pairing_complete"]
    assert not result["handoff_call_coverage_complete"]
    assert result["error_type"] == "incomplete_handoff_call_coverage"
    assert not result["valid"] and not result["passed"]


def test_root_retry_keeps_one_logical_dispatch_and_all_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.agent.loop import _provider_call

    monkeypatch.setattr(_provider_call, "_FAIL_FAST_RETRY_DELAY_S", 0)
    case = _case("negated-cancel-en")
    directory = tmp_path / "root-retry"
    directory.mkdir()
    root = _Adapter(
        [httpx.ConnectError("synthetic connection failure"), *_root_responses(case)[1:]]
    )
    result = asyncio.run(runtime.run_arm(case, "a0", directory, root_adapter=root))
    receipt = json.loads((directory / "handoff.json").read_text())
    requests = [row for row in receipt if row["kind"] == "root_request"]
    attempts = result["usage"]["recorded_attempts"]
    assert len(root.requests) == len(attempts) == 3
    assert len(requests) == len({row["llm_call_id"] for row in attempts}) == 2
    assert attempts[0]["llm_call_id"] == attempts[1]["llm_call_id"]
    assert attempts[0]["llm_attempt_id"] != attempts[1]["llm_attempt_id"]
    assert result["handoff_call_coverage_complete"]
    assert result["usage"]["attempt_pairing_complete"]
    # Coverage is complete; the transport attempt's missing usage still invalidates the run.
    assert not result["valid"] and result["oracle"]["passed"]


@pytest.mark.parametrize("allow_recovery", [True, False])
def test_wrong_read_then_correct_read_requires_explicit_recovery_contract(
    tmp_path: Path, allow_recovery: bool
) -> None:
    cohort = json.loads(
        (pilot.ROOT / "evals/benchmarks/fixtures/decision-handoff-hard.json").read_text()
    )
    case = dict(cohort["cases"][0])
    assert case["allow_extra_read_lookups"] is True
    if not allow_recovery:
        del case["allow_extra_read_lookups"]
    directory = tmp_path / "read-recovery"
    directory.mkdir()
    root = _Adapter(
        [
            _response(calls=(_call("lookup_order_status", "wrong-read", {"order_id": "C-318"}),)),
            _response(
                calls=(
                    _call(
                        "lookup_order_status", "correct-read", {"order_id": case["expected_order"]}
                    ),
                )
            ),
            _response(json.dumps(case["expected_answer"])),
        ]
    )
    result = asyncio.run(
        runtime.run_arm(case, "a0", directory, root_adapter=root, orders=cohort["orders"])
    )
    assert result["valid"] and result["passed"] is allow_recovery
    handoff = json.loads((directory / "handoff.json").read_text())
    verified = runtime.verify_handoff_result(case, result, handoff)
    assert verified["passed"] is allow_recovery
    assert verified["checks"]["results_consumed_by_root"]
    assert verified["extra_lookup_count"] == 1
    assert verified["wrong_target_lookup_count"] == 1
    assert verified["recovery_after_wrong_lookup"] is allow_recovery
    assert verified == result["oracle"]


@pytest.mark.parametrize("arm", ["a", "b"])
@pytest.mark.parametrize("recovered", [True, False])
def test_controlled_wrong_helper_preserves_real_original_and_consumed_projection(
    arm: str, recovered: bool, tmp_path: Path
) -> None:
    from pydantic import SecretStr

    case = _case("corrected-target-ko")
    original, body = _decisions(case)
    root_case = (
        case
        if recovered
        else {
            **case,
            "expected_order": "A-104",
            "expected_answer": {
                "order_id": "A-104",
                "status": "shipped",
                "disposition": "answered",
            },
        }
    )
    root, helper = _Adapter(_root_responses(root_case)), _Adapter([_response(json.dumps(original))])
    directory = tmp_path / "injected"
    directory.mkdir()

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ) as client:
            return await runtime.run_arm(
                case,
                arm,
                directory,
                root_adapter=root,
                decision_adapter=helper,
                client=client,
                api_key=SecretStr("synthetic-test-key"),
                intervention={"intent": "status_only", "order_id": "A-104"},
            )

    result = asyncio.run(run())
    assert result["valid"] and result["passed"] is recovered
    assert result["oracle"]["component_matches"] is False
    intervention = json.loads((directory / "intervention.json").read_text())
    assert len(intervention) == 1 and intervention[0]["delivered"]
    assert intervention[0]["original_result"]["result"]["target"]["order_id"] == "B-209"
    assert intervention[0]["projected_result"]["result"]["target"]["order_id"] == "A-104"
    assert intervention[0]["projected_result"]["result"]["primitives"] is None
    assert intervention[0]["original_sha256"] != intervention[0]["projected_sha256"]
    assert (
        len([row for row in result["call_accounting"] if row["purpose"] == "structured_decision"])
        == 1
    )
    handoff = json.loads((directory / "handoff.json").read_text())
    observed = next(row for row in handoff if row.get("tool") == "analyze_request")
    assert observed["result"] == intervention[0]["projected_result"]
    assert runtime.verify_handoff_result(case, result, handoff)["passed"] is recovered


def test_harder_candidate_omission_is_not_missing_text_and_has_no_label_leak(
    tmp_path: Path,
) -> None:
    from evals.benchmarks.decision_handoff import DecisionHandoffTool

    cohort = json.loads(
        (pilot.ROOT / "evals/benchmarks/fixtures/decision-handoff-hard.json").read_text()
    )
    assert len(cohort["cases"]) == 9
    assert len({case["id"] for case in cohort["cases"]}) == 9
    assert not (
        {case["id"] for case in cohort["cases"]}
        & {case["id"] for case in json.loads(pilot.FIXTURE.read_text())}
    )
    case = next(case for case in cohort["cases"] if case["family"] == "candidate-omission")
    missing = next(case for case in cohort["cases"] if case["family"] == "missing-text")
    assert case["expected_order"] in case["request"] and missing["expected_order"] is None
    payload = DecisionHandoffTool(case["request"], "a")._payload()
    assert set(payload["state"]["order_mentions"]) == {"order_0"}
    assert payload["state"]["order_mentions"]["order_0"]["order_id"] == "C-318"
    assert "label_rationale" not in json.dumps(payload)
    helper = _Adapter([_response('{"intent":"status_only","target":"none"}')])
    root = _Adapter(_root_responses(case))
    directory = tmp_path / "omission"
    directory.mkdir()
    result = asyncio.run(
        runtime.run_arm(
            case,
            "a",
            directory,
            orders=cohort["orders"],
            decision_adapter=helper,
            root_adapter=root,
        )
    )
    assert result["valid"] and result["passed"]
    assert not result["oracle"]["component_matches"]
    serialized = repr(root.requests) + repr(helper.requests)
    assert case["label_rationale"] not in serialized
    assert "candidate_expectation" not in serialized and "expected_answer" not in serialized


def test_cancellation_preserves_closed_private_snapshot(tmp_path: Path) -> None:
    directory = tmp_path / "cancelled"
    directory.mkdir()
    result = asyncio.run(
        runtime.run_arm(
            _case("negated-cancel-en"),
            "a0",
            directory,
            root_adapter=_Adapter([asyncio.CancelledError("synthetic interruption")]),
        )
    )
    assert not result["valid"] and not result["passed"]
    assert result["error_type"] == "CancelledError"
    assert (directory / "runtime-metadata.json").is_file()
    assert (directory / "trajectory.private.json").is_file()
    assert (directory / "call-events.json").is_file()
    assert result["call_accounting"][0]["total_tokens"] is None
    private = json.loads((directory / "trajectory.private.json").read_text())
    assert private["integrity"]["replay_complete"]
    assert private["events"][-1]["kind"] == "session.ended"


def test_truncated_private_content_invalidates_replay_without_losing_evidence(
    tmp_path: Path,
) -> None:
    case = _case("negated-cancel-en")
    case = {**case, "request": case["request"] + "\n" + "x" * 100_001}
    directory = tmp_path / "truncated"
    directory.mkdir()
    responses = _root_responses(case)[1:]
    result = asyncio.run(runtime.run_arm(case, "a0", directory, root_adapter=_Adapter(responses)))
    assert result["oracle"]["passed"]
    assert not result["valid"] and not result["passed"]
    assert result["error_type"] == "incomplete_replay_evidence"
    assert result["source_snapshot_complete"] is False
    private = json.loads((directory / "trajectory.private.json").read_text())
    assert private["integrity"]["scope_complete"]
    assert private["integrity"]["replay_complete"] is False
    assert private["integrity"]["replay_incompleteness"]
    assert private["events"][-1]["kind"] == "session.ended"
    for filename in ("trajectory.json", "session-events.json", "call-events.json", "handoff.json"):
        assert (directory / filename).is_file()


@pytest.mark.parametrize("arm", ["a0", "a", "b"])
def test_real_handoff_preserves_action_replay_through_native_projectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> None:
    from core.memory.atomic_write import atomic_write_json
    from evals.platforms.harbor_handoff import GeodeHandoffHarborAgent

    case = _case("corrected-target-ko")
    directory = tmp_path / arm
    if arm == "a0":
        directory.mkdir()
        result = asyncio.run(
            runtime.run_arm(case, arm, directory, root_adapter=_Adapter(_root_responses(case)[1:]))
        )
    else:
        result, *_ = asyncio.run(_run(case, arm, directory))
    assert result["valid"] and result["source_snapshot_complete"]
    private_bytes = (directory / "trajectory.private.json").read_bytes()
    (directory / "geode-trajectory.private.json").write_bytes(private_bytes)
    atomic_write_json(
        directory / "runtime-result.json",
        {
            "usage": result["usage"],
            "metadata": {"profile": "decision-handoff", "usage": result["usage"]},
            "tool_definitions": result["tool_definitions"],
        },
    )
    # Only the optional Harbor SDK validator is outside this offline check.
    # Canonical producer, integrity gate, ATIF projector and cast writer are real.
    monkeypatch.setattr("evals.platforms.harbor._write_atif_trajectory", atomic_write_json)
    agent = object.__new__(GeodeHandoffHarborAgent)
    agent.logs_dir = directory
    agent.model_name = runtime.MODEL
    agent.provider = "openai"
    agent.source = "subscription"
    agent.source_revision = "a" * 40
    agent.effort = "xhigh"
    agent.populate_context_post_run(SimpleNamespace())
    assert (directory / "geode-trajectory.private.json").read_bytes() == private_bytes
    atif_path = directory / "trajectory.json"
    atif = json.loads(atif_path.read_text())
    tool_steps = [step for step in atif["steps"] if step.get("tool_calls")]
    assert len(tool_steps) == (1 if arm == "a0" else 2)
    assert {step["tool_calls"][0]["function_name"] for step in tool_steps} == {
        tool["name"] for tool in result["tool_definitions"]
    }
    assert all(
        step["tool_calls"][0]["tool_call_id"] == step["observation"]["results"][0]["source_call_id"]
        for step in tool_steps
    )
    assert atif["steps"][0]["message"] == case["request"]
    assert atif["steps"][-1]["message"] == result["final_text"]
    assert atif["extra"]["source_replay_complete"]
    cast_path = directory / "recording.cast"
    receipt = json.loads((directory / "recording.receipt.json").read_text())
    assert receipt["source"]["sha256"] == hashlib.sha256(atif_path.read_bytes()).hexdigest()
    assert receipt["output"]["sha256"] == hashlib.sha256(cast_path.read_bytes()).hexdigest()
    assert receipt["timing"]["synthetic_timestamp_count"] == 0
    assert receipt["timing"]["clamped_timestamp_count"] == 0
    assert receipt["score_authority"] is False
    assert receipt["privacy"]["publication_state"] == "private-review-required"
