"""Panel runner with fake engines: order, attempts contract and the substitution rule."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from core.llm.adapters.base import (
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    UsageSummary,
)
from core.llm.errors import BillingError
from evals.benchmarks import verdict_panel as panel
from evals.benchmarks import verdict_panel_runner as runner
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL
from pydantic import SecretStr
from scripts.eval.contract import validate_analysis, validate_attempts

from tests.scripts.test_eval_contract import _run_spec, _workload_hash

EXAMPLE = Path(panel.__file__).parent / "fixtures/jev-verdict-panel-example"
LABELS = ("supported", "contradicted", "insufficient_evidence")


class _Astra:
    name = "fake-subscription"
    provider = "openai"
    source = "subscription"
    billing_type = AdapterBillingType.SUBSCRIPTION

    def __init__(self, *, model: str = ROOT_MODEL, text: str | None = None) -> None:
        self.model = model
        self.text = text
        self.requests: list[AdapterCallRequest] = []

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        assert request.response_schema is not None
        if self.text is not None:
            text = self.text
        elif "verdict" in request.response_schema["properties"]:
            text = json.dumps(
                {
                    "verdict": "supported",
                    "probabilities": {
                        "supported": 0.7,
                        "contradicted": 0.2,
                        "insufficient_evidence": 0.1,
                    },
                }
            )
        else:
            text = json.dumps({"has_contradiction": 0.2, "missing_evidence": 0.6})
        return AdapterCallResult(
            text=text,
            usage=UsageSummary(
                input_tokens=3500,
                output_tokens=40,
                input_tokens_present=True,
                output_tokens_present=True,
            ),
            stop_reason="completed",
            response_model=self.model,
        )


def _jev_body(payload: dict[str, Any]) -> dict[str, Any]:
    questions = payload["questions"]
    if "verdict" in questions:
        answers: dict[str, Any] = {
            "verdict": {
                "type": "choice",
                "choice": "contradicted",
                "probabilities": {
                    "supported": 0.1,
                    "contradicted": 0.8,
                    "insufficient_evidence": 0.1,
                },
                "confidence": 0.7,
            }
        }
    else:
        answers = {key: {"type": "noul", "noul": 0.7} for key in questions}
    return {
        "model": JEV_MODEL,
        "usage": {"input_tokens": 2600, "output_tokens": 0},
        "answers": answers,
    }


Transport = Callable[[httpx.Request], httpx.Response]


def _default_transport(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(_jev_body(json.loads(request.content))))


def _workloads(variants: tuple[str, ...] = ("base",)) -> list[runner.Workload]:
    result = panel.build_panel(EXAMPLE)
    rows = [row for build in result.builds for row in build.states]
    ids = [
        row["state_id"] + ("" if variant == "base" else "#" + variant)
        for row in rows
        for variant in variants
    ]
    return runner.workloads_from_states(rows, panel.ordered_workload_ids(ids, "c" * 64))


class _Guard:
    def __init__(self, fail_after: int | None = None) -> None:
        self.admitted: list[str] = []
        self.recorded: list[tuple[str, int | None]] = []
        self.fail_after = fail_after

    def admit_call(self, attempt_id: str) -> None:
        if self.fail_after is not None and len(self.admitted) >= self.fail_after:
            raise RuntimeError("program cap reached")
        self.admitted.append(attempt_id)

    def record_call(self, attempt_id: str, input_tokens: int | None) -> None:
        self.recorded.append((attempt_id, input_tokens))


def _run(
    tmp_path: Path,
    workloads: list[runner.Workload],
    *,
    astra: _Astra | None = None,
    transport: Transport = _default_transport,
    guard: _Guard | None = None,
    concurrency: int = 4,
    paraphrases: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], runner.PanelUnit]:
    unit = runner.PanelUnit(
        run_ids={
            "choice": "geode-jev-verdict-panel-test-choice",
            "noul": "geode-jev-verdict-panel-test-noul",
        },
        outputs={"choice": tmp_path / "choice", "noul": tmp_path / "noul"},
        session_dir=tmp_path / "session",
        pacing_s=0.0,
        max_concurrency=concurrency,
        heartbeat_s=0.01,
        paraphrases=paraphrases or {},
    )

    async def main() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await runner.PanelRunner(
                unit,
                workloads,
                llm_adapter=astra or _Astra(),
                jev_client=client,
                jev_key=SecretStr("synthetic-key"),
                jev_guard=guard,
            ).run()

    return asyncio.run(main()), unit


def _attempts(unit: runner.PanelUnit, primitive: str) -> list[dict[str, Any]]:
    path = unit.outputs[primitive] / "attempts.jsonl"
    # A unit stopped before a primitive's first call has no attempts for it.
    return validate_attempts(path) if path.exists() else []


def test_complete_unit_writes_two_valid_attempt_files_in_latin_order(tmp_path: Path) -> None:
    workloads = _workloads()
    guard = _Guard()
    summary, unit = _run(tmp_path, workloads, guard=guard, concurrency=1)
    assert summary["planned_calls"] == summary["dispatched_calls"] == 40 and not summary["stopped"]
    for primitive in ("choice", "noul"):
        rows = _attempts(unit, primitive)
        assert len(rows) == 20 and all(
            r["validity"] == "valid" and r["selected_for_analysis"] for r in rows
        )
        assert summary["counts"][primitive]["admitted"] == 20
        receipt = json.loads(
            (unit.outputs[primitive] / rows[0]["evidence_refs"][0]["path"]).read_text()
        )
        assert receipt["receipt"]["contract"] == "v1" and receipt["latency_s"] >= 0
        assert "synthetic-key" not in json.dumps(receipt)
    log = [
        json.loads(line)
        for line in (unit.session_dir / "dispatch-log.jsonl").read_text().splitlines()
    ]
    first = [(row["engine"], row["primitive"]) for row in log[:4]]
    second = [(row["engine"], row["primitive"]) for row in log[4:8]]
    assert first == list(runner.CELLS) and second == list(runner.latin_cells(1))
    assert (unit.session_dir / "heartbeat.jsonl").is_file()
    assert len(guard.admitted) == 20 and all(tokens == 2600 for _, tokens in guard.recorded)
    with pytest.raises(FileExistsError):
        _run(tmp_path, workloads)


def test_rejected_output_is_a_valid_wrong_attempt_and_the_unit_continues(tmp_path: Path) -> None:
    astra = _Astra(text='{"verdict":"supported"}')
    summary, unit = _run(tmp_path, _workloads(), astra=astra)
    assert not summary["stopped"] and summary["counts"]["choice"]["rejected"] == 10
    rejected = [r for r in _attempts(unit, "choice") if r["outcome"] == "failed"]
    assert len(rejected) == 10 and all(
        r["failure_class"] == "invalid_judge_output" for r in rejected
    )
    assert all(r["validity"] == "valid" and r["selected_for_analysis"] for r in rejected)


def _flaky(failures: set[int]) -> Transport:
    calls = {"count": 0}

    def transport(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] in failures:
            raise httpx.ConnectError("synthetic outage", request=request)
        return _default_transport(request)

    return transport


def test_single_transport_failure_is_replaced_once_and_stays_unselected(tmp_path: Path) -> None:
    summary, unit = _run(
        tmp_path, _workloads(("base", "rep1", "rep2")), transport=_flaky({3}), concurrency=1
    )
    assert (
        summary["planned_calls"] == 120 and summary["substitutions"] == 1 and not summary["stopped"]
    )
    rows = _attempts(unit, "choice") + _attempts(unit, "noul")
    failed = [r for r in rows if r["validity"] == "invalid"]
    assert len(failed) == 1 and failed[0]["selected_for_analysis"] is False
    assert failed[0]["failure_class"] == "transport_error"
    children = [r for r in rows if r["parent_attempt_id"] == failed[0]["attempt_id"]]
    assert len(children) == 1 and children[0]["validity"] == "valid"


def test_failed_replacement_stays_selected_and_stops(tmp_path: Path) -> None:
    summary, unit = _run(
        tmp_path, _workloads(("base", "rep1", "rep2")), transport=_flaky({3, 4}), concurrency=1
    )
    assert summary["stopped"] and summary["stop_reason"] == "replacement_failed"
    rows = _attempts(unit, "choice") + _attempts(unit, "noul")
    invalid = [r for r in rows if r["validity"] == "invalid"]
    assert [r["selected_for_analysis"] for r in invalid] == [False, True]
    assert summary["dispatched_calls"] < summary["planned_calls"]


def test_replacement_rate_limit_stops_small_units(tmp_path: Path) -> None:
    summary, unit = _run(tmp_path, _workloads(), transport=_flaky({1}), concurrency=1)
    assert summary["stop_reason"] == "substitution_rate_exceeded" and summary["substitutions"] == 0
    invalid = [
        r for r in _attempts(unit, "choice") + _attempts(unit, "noul") if r["validity"] == "invalid"
    ]
    assert len(invalid) == 1 and invalid[0]["selected_for_analysis"] is True


def test_quota_route_and_harness_failures_stop_without_replacement(tmp_path: Path) -> None:
    class Quota(_Astra):
        async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
            raise BillingError("weekly limit reached", provider="openai", resets_in_seconds=60)

    quota, unit = _run(tmp_path / "quota", _workloads(), astra=Quota(), concurrency=1)
    assert quota["stop_reason"] == "quota_exhausted" and quota["substitutions"] == 0
    assert _attempts(unit, "choice")[0]["failure_class"] == "quota_exhausted"
    drift, unit = _run(
        tmp_path / "drift", _workloads(), astra=_Astra(model="gpt-6-sol"), concurrency=1
    )
    assert drift["stop_reason"] == "route_violation"
    assert _attempts(unit, "choice")[0]["selected_for_analysis"] is True

    class Broken(_Astra):
        async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
            raise KeyError("harness defect")

    broken, _ = _run(tmp_path / "broken", _workloads(), astra=Broken(), concurrency=1)
    assert broken["stop_reason"] == "harness_error"


_REQUEST = httpx.Request("POST", "https://provider.invalid/v1")


def _http(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "synthetic", request=_REQUEST, response=httpx.Response(status, request=_REQUEST)
    )


def _sdk(
    error: type[openai.APIStatusError], status: int, body: object = None
) -> openai.APIStatusError:
    return error("synthetic", response=httpx.Response(status, request=_REQUEST), body=body)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), "transport_error"),
        (httpx.ConnectError("refused"), "transport_error"),
        (httpx.ReadTimeout("slow"), "transport_error"),
        (httpx.RemoteProtocolError("closed without a response"), "transport_error"),
        (openai.APIConnectionError(request=_REQUEST), "transport_error"),
        (openai.APITimeoutError(request=_REQUEST), "transport_error"),
        (_http(408), "transport_error"),
        (_http(500), "transport_error"),
        (_http(503), "transport_error"),
        (_sdk(openai.InternalServerError, 502), "transport_error"),
        (BillingError("weekly limit reached", provider="openai"), "quota_exhausted"),
        (_http(402), "quota_exhausted"),
        (_http(429), "quota_exhausted"),
        (_sdk(openai.RateLimitError, 429), "quota_exhausted"),
        (
            _sdk(openai.PermissionDeniedError, 403, {"error": {"code": "insufficient_quota"}}),
            "quota_exhausted",
        ),
        (_http(401), "harness_error"),
        (_http(403), "harness_error"),
        (_sdk(openai.AuthenticationError, 401), "harness_error"),
        (_http(400), "harness_error"),
        (_sdk(openai.BadRequestError, 400), "harness_error"),
        (_http(404), "harness_error"),
        (KeyError("harness defect"), "harness_error"),
    ],
)
def test_call_failure_class_is_one_table_for_both_runners(
    error: BaseException, expected: str
) -> None:
    assert runner.call_failure_class(error) == expected


def _status_at(failures: set[int], status: int) -> Transport:
    calls = {"count": 0}

    def transport(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] in failures:
            return httpx.Response(status, json={"error": "synthetic"})
        return _default_transport(request)

    return transport


class _AstraFails(_Astra):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error: Exception | None = error

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        error, self.error = self.error, None
        if error is not None:
            raise error
        return await super().acomplete(request)


@pytest.mark.parametrize(
    "fault",
    [
        {"astra": openai.APIConnectionError(request=_REQUEST)},
        {"astra": openai.APITimeoutError(request=_REQUEST)},
        {"transport": _status_at({3}, 503)},
        {"transport": _status_at({3}, 408)},
    ],
)
def test_no_response_failures_on_either_route_are_replaced_once(
    tmp_path: Path, fault: dict[str, Any]
) -> None:
    summary, unit = _run(
        tmp_path,
        _workloads(("base", "rep1", "rep2")),
        astra=_AstraFails(fault["astra"]) if "astra" in fault else None,
        transport=fault.get("transport", _default_transport),
        concurrency=1,
    )
    assert summary["substitutions"] == 1 and not summary["stopped"]
    rows = _attempts(unit, "choice") + _attempts(unit, "noul")
    failed = [r for r in rows if r["validity"] == "invalid"]
    assert len(failed) == 1 and failed[0]["selected_for_analysis"] is False
    assert failed[0]["failure_class"] == "transport_error"
    children = [r for r in rows if r["parent_attempt_id"] == failed[0]["attempt_id"]]
    assert len(children) == 1 and children[0]["validity"] == "valid"


@pytest.mark.parametrize(
    ("fault", "failure"),
    [
        ({"transport": _status_at({1}, 401)}, "harness_error"),
        ({"transport": _status_at({1}, 403)}, "harness_error"),
        ({"transport": _status_at({1}, 429)}, "quota_exhausted"),
        ({"transport": _status_at({1}, 400)}, "harness_error"),
        ({"astra": _sdk(openai.RateLimitError, 429)}, "quota_exhausted"),
        ({"astra": _sdk(openai.AuthenticationError, 401)}, "harness_error"),
    ],
)
def test_quota_credential_and_request_failures_stop_without_replacement(
    tmp_path: Path, fault: dict[str, Any], failure: str
) -> None:
    summary, unit = _run(
        tmp_path,
        _workloads(("base", "rep1", "rep2")),
        astra=_AstraFails(fault["astra"]) if "astra" in fault else None,
        transport=fault.get("transport", _default_transport),
        concurrency=1,
    )
    assert summary["stop_reason"] == failure and summary["substitutions"] == 0
    invalid = [
        r for r in _attempts(unit, "choice") + _attempts(unit, "noul") if r["validity"] == "invalid"
    ]
    assert len(invalid) == 1 and invalid[0]["selected_for_analysis"] is True
    assert invalid[0]["failure_class"] == failure


def test_jev_budget_guard_stops_before_dispatch(tmp_path: Path) -> None:
    guard = _Guard(fail_after=3)
    summary, unit = _run(tmp_path, _workloads(), guard=guard, concurrency=1)
    assert summary["stopped"] and summary["stop_reason"].startswith("jev_budget:")
    assert len(guard.admitted) == 3 and len(guard.recorded) == 3


def test_program_ledger_backs_the_runner_guard_and_stops_at_its_limit(tmp_path: Path) -> None:
    from decimal import Decimal

    from evals.benchmarks.jev_cost_ledger import JevCostLedger, PanelSpendGuard

    ledger = JevCostLedger.create(
        tmp_path / "jev-ledger.jsonl",
        cost_limit_usd="0.001",
        start_limit_usd="0.0002",
        stop_limit_usd="0.0003",
    )
    ledger.admit_unit("u2c-fixture", 20, p95_input_tokens=1)
    guard = PanelSpendGuard(ledger, "u2c-fixture", input_tokens_per_call=2600)
    summary, _unit = _run(tmp_path / "run", _workloads(), guard=guard, concurrency=1)
    # Three settled Jev calls (3 x 2600 x $0.042/M) cross the $0.0003 stop limit.
    assert summary["stopped"] and summary["stop_reason"].startswith("jev_budget:")
    assert guard.exhausted is not None and guard.exhausted.reason == "stop_limit_reached"
    status = ledger.status()
    assert Decimal(status["estimate_usd_total"]) == Decimal("0.000327600")
    assert status["units"]["u2c-fixture"]["settled_calls"] == 3
    assert status["units"]["u2c-fixture"]["open_reservations"] == 0
    assert status["stopped"] is True
    with pytest.raises(ValueError, match="was not admitted"):
        guard.record_call("never-admitted", 1)


def test_stability_variants_need_paraphrases_and_reach_both_engines(tmp_path: Path) -> None:
    workloads = _workloads(("order-rev",))
    summary, unit = _run(tmp_path, workloads, concurrency=1)
    assert not summary["stopped"]
    receipt = json.loads(
        (
            unit.outputs["choice"] / _attempts(unit, "choice")[0]["evidence_refs"][0]["path"]
        ).read_text()
    )
    assert (
        receipt["receipt"]["question_variant"] == "order-rev" and receipt["variant"] == "order-rev"
    )
    with pytest.raises(ValueError):
        _run(tmp_path / "para", _workloads(("para",)))


def test_workload_binding_rejects_unknown_variants_and_state_drift() -> None:
    result = panel.build_panel(EXAMPLE)
    rows = [row for build in result.builds for row in build.states]
    with pytest.raises(ValueError):
        runner.workloads_from_states(rows, [rows[0]["state_id"] + "#other"])
    tampered = [replace_state(rows[0]), *rows[1:]]
    with pytest.raises(ValueError):
        runner.workloads_from_states(tampered, [rows[0]["state_id"]])
    with pytest.raises(ValueError):
        runner.workloads_from_states(rows, [rows[0]["state_id"], rows[0]["state_id"]])


def replace_state(row: dict[str, Any]) -> dict[str, Any]:
    changed = json.loads(json.dumps(row))
    changed["state"]["candidate_output"] += " altered"
    return changed


def test_unit_validation_and_invalidation_rules() -> None:
    with pytest.raises(ValueError):
        runner.PanelUnit(
            run_ids={"choice": "a-choice"}, outputs={}, session_dir=Path("x")
        ).validate()
    with pytest.raises(ValueError):
        runner.PanelUnit(
            run_ids={"choice": "c", "noul": "n"},
            outputs={"choice": Path("c"), "noul": Path("n")},
            session_dir=Path("s"),
            max_concurrency=5,
        ).validate()
    for rule in runner.INVALIDATION_RULES.values():
        assert 10 <= len(rule) <= 2000
    assert "exactly once" in runner.INVALIDATION_RULES["panel"]
    assert "no replacement" in runner.INVALIDATION_RULES["e2e"]
    assert replace(runner.Workload("w", "s", "c", "base", {}), variant="rep1").variant == "rep1"


# ---------------------------------------------------------------------------
# U2s stability: selected attempts -> stability_summary -> analysis rows (v2.2 §3.7-3)
# ---------------------------------------------------------------------------

STABILITY = ("rep1", "rep2", "order-rev", "para")


def _paraphrases() -> dict[str, dict[str, Any]]:
    from evals.benchmarks.decision_verification import base_questions

    return {
        primitive: {
            key: {
                "type": question["type"],
                "instructions": question["instructions"] + " Reworded.",
                "criteria": {
                    label: text + " Reworded." for label, text in question["criteria"].items()
                },
            }
            for key, question in base_questions(primitive).items()
        }
        for primitive in ("choice", "noul")
    }


class _Unstable(_Astra):
    """Astra: identical repeat requests alternate verdicts; paraphrases get rejected."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[str, int] = {}

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        result = await super().acomplete(request)
        content = request.messages[0].content
        assert isinstance(content, str)
        if "Reworded." in content:
            return replace(result, text='{"verdict":"supported"}')  # no probabilities
        if request.response_schema and "verdict" in request.response_schema["properties"]:
            count = self.seen[content] = self.seen.get(content, 0) + 1
            if count == 2:
                label = "insufficient_evidence"
                probabilities = dict.fromkeys(LABELS, 0.1) | {label: 0.8}
                return replace(
                    result, text=json.dumps({"verdict": label, "probabilities": probabilities})
                )
        return result


def _order_sensitive_jev(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    body = _jev_body(payload)
    criteria = list(payload["questions"].get("verdict", {}).get("criteria", {}))
    if criteria and criteria[0] != "supported":  # the criteria-order-reversed question
        body["answers"]["verdict"]["choice"] = "insufficient_evidence"
        body["answers"]["verdict"]["probabilities"] = {
            "supported": 0.1,
            "contradicted": 0.1,
            "insufficient_evidence": 0.8,
        }
    return httpx.Response(200, content=json.dumps(body))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stability_spec(
    path: Path, run_id: str, workload_ids: list[str], primary: str = runner.STABILITY_PRIMARY
) -> Path:
    spec: dict[str, Any] = _run_spec()
    spec["run_id"] = run_id
    spec["created_at"] = spec["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec["study"]["primary_metric"] = {
        "name": primary,
        "unit": "ratio",
        "direction": "maximize",
        "aggregation": "Jev rep1/rep2 both valid and equal / planned states",
        "denominator": len({workload.partition("#")[0] for workload in workload_ids}),
    }
    execution = spec["reproduction"]["execution"]
    execution.update(
        ordered_workload_ids=workload_ids, workload_ids_sha256=_workload_hash(workload_ids)
    )
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _stability_analysis(run_dir: Path, spec: Path, rows: list[dict[str, Any]]) -> Path:
    attempts = [json.loads(line) for line in (run_dir / "attempts.jsonl").read_text().splitlines()]
    selected = [row for row in attempts if row["selected_for_analysis"]]
    invalid = any(row["validity"] != "valid" for row in selected)
    path = run_dir / "analysis.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": "geode.eval-analysis@1",
                "schema_version": 1,
                "run_id": attempts[0]["run_id"],
                "analyzed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_spec_sha256": _sha(spec),
                "attempts_sha256": _sha(run_dir / "attempts.jsonl"),
                "selected_attempt_ids": [row["attempt_id"] for row in selected],
                "answer": "Synthetic U2s stability aggregation; no model was called.",
                "metrics": rows,
                "decision": {
                    "outcome": "diagnostic-only",
                    "hypothesis_status": "invalidated" if invalid else "mixed",
                    "rationale": "Descriptive stability statistics only.",
                },
                "limitations": ["Synthetic fixture."],
                "evidence_refs": [ref for row in selected for ref in row["evidence_refs"]],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_u2s_runner_attempts_feed_stability_summary_and_bind_the_primary(
    tmp_path: Path,
) -> None:
    workloads = [w for w in _workloads(STABILITY) if w.state_id.endswith(("--q1a", "--q1c"))]
    workload_ids = [workload.workload_id for workload in workloads]
    summary, unit = _run(
        tmp_path,
        workloads,
        astra=_Unstable(),
        transport=_order_sensitive_jev,
        concurrency=1,
        paraphrases=_paraphrases(),
    )
    assert not summary["stopped"] and summary["dispatched_calls"] == 8 * 4
    report = runner.stability_report(unit.outputs, workload_ids)
    choice, noul = report["runs"]["choice"], report["runs"]["noul"]
    # Jev: same verdict when repeated, a flip under criteria-order reversal only.
    jev = choice["engines"]["jev"]["summary"]
    assert jev["pair_consistency"] == {"value": 1.0, "numerator": 2, "denominator": 2}
    assert jev["flip_rate"]["order-rev"]["numerator"] == 2
    assert jev["flip_rate"]["para"]["numerator"] == 0
    # Astra: the identical repeat disagrees and the rejected paraphrase is None.
    llm = choice["engines"]["llm"]
    assert llm["summary"]["pair_consistency"]["numerator"] == 0
    assert llm["summary"]["flip_rate"]["para"]["numerator"] == 2
    assert all(item["para"] is None for item in llm["items"])
    assert {item["rep1"] for item in llm["items"]} <= {"supported", "insufficient_evidence"}
    # Noul decisions are canonical boolean projections; variants never become repeats.
    projection = '{"has_contradiction":true,"missing_evidence":true}'
    assert {item["rep1"] for item in noul["engines"]["jev"]["items"]} == {projection}
    assert noul["engines"]["jev"]["summary"]["pair_consistency"]["numerator"] == 2
    assert report["primary"] == {
        "name": "jev_choice_pair_consistency",
        "reasons": [],
        "value": 1.0,
        "numerator": 2,
        "denominator": 2,
    }
    for primitive in ("choice", "noul"):
        spec = _stability_spec(
            tmp_path / f"{primitive}-spec.json",
            unit.run_ids[primitive],
            workload_ids,
            runner.STABILITY_PRIMARIES[primitive],
        )
        runner.record_stability_aggregate(unit.outputs[primitive], report, primitive=primitive)
        rows = runner.stability_metric_rows(report, primitive=primitive)
        names = [row["name"] for row in rows]
        assert names[:3] == [
            f"jev_{primitive}_pair_consistency",
            f"jev_{primitive}_flip_rate_order_rev",
            f"jev_{primitive}_flip_rate_para",
        ]
        assert rows[0]["source_locator"]["value"] == f"/runs/{primitive}/primary/value"
        validate_analysis(
            _stability_analysis(unit.outputs[primitive], spec, rows),
            run_spec_path=spec,
            attempts_path=unit.outputs[primitive] / "attempts.jsonl",
        )


def _synthetic_run(directory: Path, primitive: str, cells: dict[tuple[str, str, str], Any]) -> None:
    """Write attempts and native-result receipts in the runner's retained format.

    A cell value is a decision (admitted), ``"rejected"``, ``"invalid"`` (a selected
    infrastructure-invalid attempt) or ``"transport-then-ok:<decision>"`` (an
    unselected transport failure replaced by an admitted child).
    """
    run_id = f"geode-jev-verdict-panel-stability-{primitive}"
    rows: list[dict[str, Any]] = []

    def record(engine: str, state: str, variant: str, status: str, receipt: Any, **row: Any) -> str:
        attempt_id = f"{run_id}-a{len(rows):05d}"
        evidence = {
            "attempt_id": attempt_id,
            "workload_id": f"{state}#{variant}",
            "state_id": state,
            "cluster_id": "cl-synthetic",
            "variant": variant,
            "engine": engine,
            "primitive": primitive,
            "status": status,
            "error_type": None,
            "observed_result": "synthetic",
        }
        if receipt is not None:
            evidence["receipt"] = receipt
        path = directory / "receipts" / f"{attempt_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        at = f"2026-02-01T00:{len(rows) // 60:02d}:{len(rows) % 60:02d}Z"
        rows.append(
            {
                "schema_id": "geode.eval-attempt@1",
                "schema_version": 1,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "parent_attempt_id": row.pop("parent", None),
                "sequence": len(rows),
                "timing": {
                    "status": "exact",
                    "started_at": at,
                    "finished_at": at,
                    "source_ref": None,
                },
                "change": {"surface": "judgment-panel", "description": "synthetic"},
                "expected_effect": "synthetic",
                "observed_result": "synthetic",
                "error_ref": None,
                "evidence_refs": [
                    {
                        "kind": "native-result",
                        "path": f"receipts/{attempt_id}.json",
                        "sha256": _sha(path),
                    }
                ],
                **row,
            }
        )
        return attempt_id

    def admitted(decision: str) -> dict[str, Any]:
        if primitive == "choice":
            return {"accepted": True, "verdict": decision}
        return {"accepted": True, "boolean_projection": json.loads(decision)}

    valid = {"validity": "valid", "selected_for_analysis": True}
    for (engine, state, variant), value in cells.items():
        if value == "rejected":
            rejected = {"accepted": False, "verdict": None, "boolean_projection": None}
            record(
                engine,
                state,
                variant,
                "rejected",
                rejected,
                outcome="failed",
                failure_class="invalid_judge_output",
                **valid,
            )
        elif value == "invalid":
            record(
                engine,
                state,
                variant,
                "quota_exhausted",
                None,
                validity="invalid",
                outcome="unknown",
                failure_class="quota_exhausted",
                selected_for_analysis=True,
            )
        elif isinstance(value, str) and value.startswith("transport-then-ok:"):
            parent = record(
                engine,
                state,
                variant,
                "transport_error",
                None,
                validity="invalid",
                outcome="unknown",
                failure_class="transport_error",
                selected_for_analysis=False,
            )
            record(
                engine,
                state,
                variant,
                "admitted",
                admitted(value.split(":", 1)[1]),
                outcome="passed",
                failure_class=None,
                parent=parent,
                **valid,
            )
        else:
            record(
                engine,
                state,
                variant,
                "admitted",
                admitted(value),
                outcome="passed",
                failure_class=None,
                **valid,
            )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "attempts.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


NOUL_TT = '{"has_contradiction":true,"missing_evidence":true}'
NOUL_FT = '{"has_contradiction":false,"missing_evidence":true}'


def _full(primitive: str, states: list[str], decisions: dict[str, str]) -> dict:
    return {
        (engine, state, variant): decisions[engine]
        for engine in ("llm", "jev")
        for state in states
        for variant in STABILITY
    }


def _plan(states: list[str]) -> list[str]:
    return [f"{state}#{variant}" for state in states for variant in STABILITY]


def test_u2s_invalid_and_rejected_judgments_are_none_and_replacements_count_once(
    tmp_path: Path,
) -> None:
    states = ["s-a", "s-b", "s-c"]
    choice = _full("choice", states, {"llm": "supported", "jev": "contradicted"})
    choice[("jev", "s-a", "rep2")] = "rejected"
    choice[("jev", "s-b", "order-rev")] = "transport-then-ok:supported"
    choice[("llm", "s-c", "para")] = "rejected"
    noul = _full("noul", states, {"llm": NOUL_FT, "jev": NOUL_TT})
    noul[("jev", "s-c", "rep1")] = "invalid"  # a selected infrastructure-invalid attempt
    outputs = {"choice": tmp_path / "choice", "noul": tmp_path / "noul"}
    _synthetic_run(outputs["choice"], "choice", choice)
    _synthetic_run(outputs["noul"], "noul", noul)
    report = runner.stability_report(outputs, _plan(states))
    jev = report["runs"]["choice"]["engines"]["jev"]
    assert jev["items"][0]["rep2"] is None  # the validator rejection is not filled in
    assert jev["summary"]["pair_consistency"] == {
        "value": 2 / 3,
        "numerator": 2,
        "denominator": 3,
    }
    # The replaced transport failure counts once through its admitted child.
    assert jev["items"][1]["order-rev"] == "supported"
    assert jev["summary"]["flip_rate"]["order-rev"]["numerator"] == 1
    assert (
        report["runs"]["choice"]["engines"]["llm"]["summary"]["flip_rate"]["para"]["numerator"] == 1
    )
    assert report["primary"]["value"] == pytest.approx(2 / 3)
    # Noul: the selected invalid attempt is a None decision and makes that run incomplete.
    noul_jev = report["runs"]["noul"]["engines"]["jev"]
    assert noul_jev["items"][2]["rep1"] is None
    assert noul_jev["summary"]["pair_consistency"]["numerator"] == 2
    assert report["runs"]["noul"]["selected_invalid_attempts"] == 1
    assert report["runs"]["noul"]["complete"] is False
    assert report["runs"]["choice"]["complete"] is True
    # The Noul run's primary stays not-measurable under its selected invalid attempt,
    # while the descriptive summary above keeps the None decision.
    assert report["runs"]["noul"]["primary"] == {
        "name": "jev_noul_pair_consistency",
        "reasons": ["selected_invalid_attempt"],
        "value": "not-measurable",
        "numerator": None,
        "denominator": None,
    }
    noul_rows = {row["name"]: row for row in runner.stability_metric_rows(report, primitive="noul")}
    assert noul_rows["jev_noul_pair_consistency"]["value"] == "not-measurable"
    assert noul_rows["llm_noul_pair_consistency"]["value"] == 1.0
    spec = _stability_spec(
        tmp_path / "noul-spec.json",
        "geode-jev-verdict-panel-stability-noul",
        _plan(states),
        "jev_noul_pair_consistency",
    )
    runner.record_stability_aggregate(outputs["noul"], report, primitive="noul")
    validate_analysis(
        _stability_analysis(outputs["noul"], spec, list(noul_rows.values())),
        run_spec_path=spec,
        attempts_path=outputs["noul"] / "attempts.jsonl",
    )


def test_u2s_missing_variant_is_not_measurable_and_never_filled(tmp_path: Path) -> None:
    states = ["s-a", "s-b"]
    choice = _full("choice", states, {"llm": "supported", "jev": "supported"})
    del choice[("jev", "s-b", "para")]
    noul = _full("noul", states, {"llm": NOUL_FT, "jev": NOUL_TT})
    outputs = {"choice": tmp_path / "choice", "noul": tmp_path / "noul"}
    _synthetic_run(outputs["choice"], "choice", choice)
    _synthetic_run(outputs["noul"], "noul", noul)
    report = runner.stability_report(outputs, _plan(states))
    jev = report["runs"]["choice"]["engines"]["jev"]
    assert jev["status"] == "not-measurable" and jev["missing_variants"] == ["s-b#para"]
    assert jev["summary"] is None and jev["items"][1]["para"] is None
    assert report["primary"] == {
        "name": "jev_choice_pair_consistency",
        "reasons": ["missing_variant"],
        "value": "not-measurable",
        "numerator": None,
        "denominator": None,
    }
    assert report["runs"]["choice"]["engines"]["llm"]["status"] == "measured"
    rows = {row["name"]: row for row in runner.stability_metric_rows(report, primitive="choice")}
    assert rows["jev_choice_pair_consistency"]["source_locator"] is None
    assert rows["jev_choice_flip_rate_para"]["value"] == "not-measurable"
    assert rows["llm_choice_pair_consistency"]["value"] == 1.0
    spec = _stability_spec(
        tmp_path / "spec.json", "geode-jev-verdict-panel-stability-choice", _plan(states)
    )
    runner.record_stability_aggregate(outputs["choice"], report, primitive="choice")
    aggregate = json.loads((outputs["choice"] / "attempts.jsonl").read_text().splitlines()[-1])
    assert aggregate["validity"] == "invalid"
    assert aggregate["failure_class"] == "incomplete_planned_cells"
    validate_analysis(
        _stability_analysis(outputs["choice"], spec, list(rows.values())),
        run_spec_path=spec,
        attempts_path=outputs["choice"] / "attempts.jsonl",
    )
    assert runner.stability_report({"noul": outputs["noul"]}, _plan(states))["primary"][
        "reasons"
    ] == ["choice_run_missing"]


def test_u2s_gold_uses_the_same_representation_after_unseal(tmp_path: Path) -> None:
    states = ["s-a", "s-b"]
    choice = _full("choice", states, {"llm": "supported", "jev": "contradicted"})
    noul = _full("noul", states, {"llm": NOUL_FT, "jev": NOUL_TT})
    outputs = {"choice": tmp_path / "choice", "noul": tmp_path / "noul"}
    _synthetic_run(outputs["choice"], "choice", choice)
    _synthetic_run(outputs["noul"], "noul", noul)
    gold_path = tmp_path / "gold.jsonl"
    gold_rows = [
        {
            "state_id": "orig-a",
            "verdict": "contradicted",
            "has_contradiction": True,
            "missing_evidence": True,
        },
        {
            "state_id": "orig-b",
            "verdict": "supported",
            "has_contradiction": False,
            "missing_evidence": False,
        },
    ]
    gold_path.write_text("".join(json.dumps(row) + "\n" for row in gold_rows))
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"s-a": "orig-a", "s-b": "orig-b"}))
    gold = runner.load_stability_gold(gold_path, aliases)
    report = runner.stability_report(outputs, _plan(states), gold=gold)
    jev = report["runs"]["choice"]["engines"]["jev"]["summary"]
    assert jev["pair_correct_consistency"]["numerator"] == 1
    noul_jev = report["runs"]["noul"]["engines"]["jev"]
    assert noul_jev["items"][0]["gold"] == NOUL_TT
    assert noul_jev["summary"]["pair_correct_consistency"]["numerator"] == 1
    names = {row["name"] for row in runner.stability_metric_rows(report, primitive="noul")}
    assert {"jev_noul_pair_correct_consistency", "llm_noul_pair_correct_consistency"} <= names
    with pytest.raises(ValueError, match="cover every planned"):
        runner.stability_report(outputs, _plan(states), gold={"s-a": gold["s-a"]})
    sealed = runner.stability_report(outputs, _plan(states))
    assert "jev_noul_pair_correct_consistency" not in {
        row["name"] for row in runner.stability_metric_rows(sealed, primitive="noul")
    }


def test_u2s_rejects_unplanned_duplicate_and_tampered_judgments(tmp_path: Path) -> None:
    states = ["s-a"]
    with pytest.raises(ValueError, match="exactly once"):
        runner.stability_plan(["s-a#rep1", "s-a#rep2", "s-a#order-rev"])
    with pytest.raises(ValueError, match="not a stability workload"):
        runner.stability_plan(["s-a"])
    cells = _full("choice", states, {"llm": "supported", "jev": "supported"})
    outputs = {"choice": tmp_path / "choice"}
    _synthetic_run(outputs["choice"], "choice", cells)
    with pytest.raises(ValueError, match="not planned"):
        runner.stability_report(outputs, _plan(["s-z"]))
    rows = (outputs["choice"] / "attempts.jsonl").read_text().splitlines()
    (outputs["choice"] / "attempts.jsonl").write_text("\n".join([*rows, rows[0]]) + "\n")
    with pytest.raises(ValueError, match="selected twice"):
        runner.stability_report(outputs, _plan(states))
    (outputs["choice"] / "attempts.jsonl").write_text("\n".join(rows) + "\n")
    receipt = next((outputs["choice"] / "receipts").iterdir())
    receipt.write_text(receipt.read_text().replace("supported", "contradicted"))
    with pytest.raises(ValueError, match="digest mismatch"):
        runner.stability_report(outputs, _plan(states))


def test_u2s_cli_records_aggregates_without_a_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    states = ["s-a", "s-b"]
    outputs = {"choice": tmp_path / "choice", "noul": tmp_path / "noul"}
    _synthetic_run(
        outputs["choice"],
        "choice",
        _full("choice", states, {"llm": "supported", "jev": "supported"}),
    )
    _synthetic_run(outputs["noul"], "noul", _full("noul", states, {"llm": NOUL_FT, "jev": NOUL_TT}))
    spec = _stability_spec(
        tmp_path / "spec.json", "geode-jev-verdict-panel-stability-choice", _plan(states)
    )
    code = runner.main(
        [
            "stability",
            "--run-spec",
            str(spec),
            "--choice",
            str(outputs["choice"]),
            "--noul",
            str(outputs["noul"]),
            "--record",
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["primary"]["value"] == 1.0
    assert (outputs["noul"] / runner.STABILITY_RESULTS).is_file()
    assert runner.main(["other"]) == 2


# ---------------------------------------------------------------------------
# Byte regression: internal units (U0a, U1, U2c/n, U2s) keep their pre-0025 bytes
# ---------------------------------------------------------------------------


class _SimClock:
    """Simulated monotonic clock: fake engines and pacing sleeps advance it."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)

    def utc(self) -> str:
        at = datetime(2026, 9, 27, tzinfo=UTC) + timedelta(seconds=self.now)
        return at.isoformat().replace("+00:00", "Z")


class _TimedAstra(_Unstable):
    """Deterministic Astra: records every request and takes ``latency`` simulated seconds."""

    def __init__(self, clock: _SimClock, latency: float = 2.5) -> None:
        super().__init__()
        self.clock = clock
        self.latency = latency

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.clock.now += self.latency
        return await super().acomplete(request)


def _timed_jev(
    clock: _SimClock,
    bodies: list[bytes],
    *,
    latency: float = 0.75,
    failures: frozenset[int] = frozenset(),
) -> Transport:
    def transport(request: httpx.Request) -> httpx.Response:
        bodies.append(request.method.encode() + b" " + str(request.url).encode() + b"\n")
        bodies.append(request.content)
        clock.now += latency
        if len(bodies) // 2 in failures:
            raise httpx.ConnectError("synthetic outage", request=request)
        return _order_sensitive_jev(request)

    return transport


def _astra_inputs(requests: list[AdapterCallRequest]) -> bytes:
    return json.dumps(
        [
            {
                "model": request.model,
                "effort": request.effort,
                "system_prompt": request.system_prompt,
                "messages": [[message.role, message.content] for message in request.messages],
                "response_schema": request.response_schema,
                "metadata": request.metadata,
                "allowed_tool_names": sorted(request.allowed_tool_names or ()),
            }
            for request in requests
        ],
        sort_keys=True,
    ).encode()


def _unit_digests(
    tmp_path: Path, unit: runner.PanelUnit, summary: dict[str, Any], inputs: dict[str, bytes]
) -> dict[str, str]:
    """Per-artifact sha256 of everything a unit writes, plus the exact engine inputs."""
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()}
    for primitive, directory in sorted(unit.outputs.items()):
        receipts = hashlib.sha256()
        for path in sorted(directory.rglob("*")):
            if path.parent.name == "receipts":
                receipts.update(path.name.encode() + b"\0" + path.read_bytes())
            elif path.is_file():
                digests[f"{primitive}/{path.name}"] = _sha(path)
        digests[f"{primitive}/receipts"] = receipts.hexdigest()
    digests["dispatch-log"] = _sha(unit.session_dir / "dispatch-log.jsonl")
    if (unit.session_dir / "pair-log.jsonl").exists():
        digests["pair-log"] = _sha(unit.session_dir / "pair-log.jsonl")
    normalized = json.dumps(summary, sort_keys=True).replace(str(tmp_path), "<tmp>")
    digests["summary"] = hashlib.sha256(normalized.encode()).hexdigest()
    return digests


def _timed_run(
    tmp_path: Path,
    workloads: list[runner.Workload],
    *,
    concurrency: int,
    failures: frozenset[int] = frozenset(),
    paraphrases: dict[str, dict[str, Any]] | None = None,
    primitives: tuple[str, ...] = ("choice", "noul"),
    unit_options: dict[str, Any] | None = None,
    latencies: tuple[float, float] = (2.5, 0.75),
) -> tuple[dict[str, Any], runner.PanelUnit, dict[str, bytes]]:
    clock = _SimClock()
    astra = _TimedAstra(clock, latency=latencies[0])
    bodies: list[bytes] = []
    unit = runner.PanelUnit(
        run_ids={p: f"geode-jev-verdict-panel-test-{p}" for p in primitives},
        outputs={p: tmp_path / p for p in primitives},
        session_dir=tmp_path / "session",
        pacing_s=1.0,
        max_concurrency=concurrency,
        heartbeat_s=0.01,
        paraphrases=paraphrases or {},
        **(unit_options or {}),
    )

    async def main() -> dict[str, Any]:
        transport = _timed_jev(clock, bodies, latency=latencies[1], failures=failures)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await runner.PanelRunner(
                unit,
                workloads,
                llm_adapter=astra,
                jev_client=client,
                jev_key=SecretStr("synthetic-key"),
                clock=clock,
                sleep=clock.sleep,
            ).run()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "_now", clock.utc)
        summary = asyncio.run(main())
    inputs = {"astra-requests": _astra_inputs(astra.requests), "jev-requests": b"".join(bodies)}
    return summary, unit, inputs


# sha256 digests recorded at bce6154e8 (before 0025) by this same harness.
_PRE_0025_PANEL = {
    1: {
        "astra-requests": "7b39c3b28a12e5c58e284c62a3999fa4f562c07cebcd342c0a88faa7dc423e14",
        "choice/attempts.jsonl": "315fe0f0102573b78ea2606fdb4b4d0af7b040a0d77f8ade6d49d7e5cfe0bb27",
        "choice/receipts": "46c09716e21b45ba6ac9626ab9bc1696255f3bcd4db76d35a7ad5943a7e016bb",
        "dispatch-log": "ef892e587f3764b1b75fdd0ab13a41f8baa78f6b287719f14282110e7cb3985d",
        "jev-requests": "970861f1e5e133e6de6f6253a81ebb73a50cd276f147783533b73d27cd3b71e1",
        "noul/attempts.jsonl": "8e3def0cbe0aa9c21bde7447a8f7c420e96c149a1820f210ec16fe58e0ef0c14",
        "noul/receipts": "da0e0710400f540faf8a1841c1608b1ca4cc4a39cc533edf7f8d3c8b73a97f49",
        "summary": "79ef8ddcfa253fa1c8747936b8a2ec00f996d75bd70bd802cfdd0c10da0391d1",
    },
    4: {
        "astra-requests": "7b39c3b28a12e5c58e284c62a3999fa4f562c07cebcd342c0a88faa7dc423e14",
        "choice/attempts.jsonl": "6c3106e3020fc044528d7978249dba9d8059068081d94c858fe3a9b7986782d6",
        "choice/receipts": "46c09716e21b45ba6ac9626ab9bc1696255f3bcd4db76d35a7ad5943a7e016bb",
        "dispatch-log": "9abfae8c09dcffe1337a2f587f21135f166c604785b309c9444c6978125db357",
        "jev-requests": "970861f1e5e133e6de6f6253a81ebb73a50cd276f147783533b73d27cd3b71e1",
        "noul/attempts.jsonl": "065ae7672d20173b40b2387de8b55c160fef1eebbd97144fb5c4351b7e7dd7c6",
        "noul/receipts": "da0e0710400f540faf8a1841c1608b1ca4cc4a39cc533edf7f8d3c8b73a97f49",
        "summary": "79ef8ddcfa253fa1c8747936b8a2ec00f996d75bd70bd802cfdd0c10da0391d1",
    },
}
_PRE_0025_STABILITY = {
    "astra-requests": "7d59b8d27ca32358aaf192620f1666c9904e5893ecc8c83a9230203fa43ba67c",
    "choice/attempts.jsonl": "db00ee1c7db055644544fa52a061c5a5140c8fc69996691667d1c7d774fda97a",
    "choice/receipts": "b732788027af3325ffc0d27bab6ece6d06676a86c8b85a84036922b26cb41eb3",
    "choice/stability-results.json": "4cfb5faf9e702247c752480b0b1e46f90d8fc6b6302a675c34de72c3a50c4e2f",
    "dispatch-log": "e4f4be52c1e550e77373e779030f519c1e9166e17978d83e3e6ce0718be6a8f9",
    "jev-requests": "9368eff723c7bebc5553353bff77c391d189bcd06e8daca7ece8e78c01c03b2b",
    "metric-rows": "f01ebae6ba801e3af55fdd674f9d6fb2a9fc7aeff929a253b5365a23a30f4e85",
    "noul/attempts.jsonl": "30e49f9b4667051119650ef19ba04f76587c8812a7cfe4cf421349c955cad9f9",
    "noul/receipts": "6eb6e211181976ab9e0037abc51cdc344a564f604b515e9660b1e99103a2324f",
    "noul/stability-results.json": "4cfb5faf9e702247c752480b0b1e46f90d8fc6b6302a675c34de72c3a50c4e2f",
    "summary": "e79907e29e201094c172cdc3818f2219f071bf57f451ca624c2205b44c4bad8e",
}


@pytest.mark.parametrize("concurrency", [1, 4])
def test_internal_panel_unit_bytes_are_unchanged(tmp_path: Path, concurrency: int) -> None:
    summary, unit, inputs = _timed_run(tmp_path, _workloads(), concurrency=concurrency)
    assert not summary["stopped"] and summary["planned_calls"] == 40
    digests = _unit_digests(tmp_path, unit, summary, inputs)
    assert digests == _PRE_0025_PANEL[concurrency]


def test_internal_stability_unit_bytes_are_unchanged(tmp_path: Path) -> None:
    workloads = _workloads(STABILITY)
    summary, unit, inputs = _timed_run(
        tmp_path, workloads, concurrency=1, failures=frozenset({5}), paraphrases=_paraphrases()
    )
    assert summary["substitutions"] == 1 and not summary["stopped"]
    ids = [workload.workload_id for workload in workloads]
    report = runner.stability_report(unit.outputs, ids)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "_now", lambda: "2026-09-27T01:00:00Z")
        for primitive in ("choice", "noul"):
            runner.record_stability_aggregate(unit.outputs[primitive], report, primitive=primitive)
    rows = {p: runner.stability_metric_rows(report, primitive=p) for p in ("choice", "noul")}
    inputs["metric-rows"] = json.dumps(rows, sort_keys=True).encode()
    digests = _unit_digests(tmp_path, unit, summary, inputs)
    assert digests == _PRE_0025_STABILITY


# sha256 digests recorded at 0a90cf8fe (0025 applied, before 0029) by the same harness.
_PRE_0029_CHOICE_ONLY: dict[str, dict[str, str]] = {
    "latin": {
        "astra-requests": "ad1efd86c4013e7b85d2db4323e01901f1612c5955adef5c117e809f41b6271a",
        "choice/attempts.jsonl": "84b76c30675288d77e2a4ce01b452ab129ff44c8ffb54f9aaafcd4edcbc0cf20",
        "choice/receipts": "0fc6e8367df361e3e63c9b13e15fe40ef1b9e6c36140bc4f55f76dea1cdccb42",
        "dispatch-log": "bed836c8d4ffd8c3abbc2c455aa29c5678a3280af109fa150cf10887508b7898",
        "jev-requests": "f6e48c7d1b258b1cbe6a44f41dfa0daa2c116fedb4189bdc4243b73859612d62",
        "summary": "4ae32d52fc4549c61c0518823007a59104acb92144172feaf118c3ded5d55d48",
    },
    "paired-latency": {
        "astra-requests": "ad1efd86c4013e7b85d2db4323e01901f1612c5955adef5c117e809f41b6271a",
        "choice/attempts.jsonl": "a3b22aaba7c231d4ac571b7ea3859719cb45a4649f3332d2551e1ccc5a398381",
        "choice/receipts": "471568803032410e7a76ce44194d1043d1f4704e2a99c8c3ce7d499f40333fd9",
        "dispatch-log": "a74db3d94280ea15aad71255fae0331c699159c90ff6b080ac027f923ecebeec",
        "jev-requests": "f6e48c7d1b258b1cbe6a44f41dfa0daa2c116fedb4189bdc4243b73859612d62",
        "pair-log": "00e4070a29b662fff414d4422f63d37250b71106ea3fbdab8cbf710c20f5e289",
        "summary": "1b778db735e736f95d2a88440fc1f4d70919c10e84a51fc6ce3ac58e0682b91b",
    },
}


@pytest.mark.parametrize("mode", ["latin", "paired-latency"])
def test_choice_only_unit_bytes_are_unchanged(tmp_path: Path, mode: str) -> None:
    rows = _external_rows(6)
    order = panel.ordered_workload_ids([row["state_id"] for row in rows], "e" * 64)
    # Synchronous fakes cannot overlap in simulated time, so the paired run keeps the
    # clock still inside calls (zero skew) and pacing alone advances it.
    paired = mode == "paired-latency"
    summary, unit, inputs = _timed_run(
        tmp_path,
        runner.workloads_from_states(rows, order),
        concurrency=2 if paired else 4,
        primitives=("choice",),
        unit_options={"mode": mode},
        latencies=(0.0, 0.0) if paired else (2.5, 0.75),
    )
    assert not summary["stopped"] and summary["planned_calls"] == 12
    digests = _unit_digests(tmp_path, unit, summary, inputs)
    assert digests == _PRE_0029_CHOICE_ONLY[mode]


# ---------------------------------------------------------------------------
# Choice-only units (U3, X1a, X1) and the U3 paired latency mode
# ---------------------------------------------------------------------------

MANIFEST = "d" * 64  # stand-in split manifest digest, authored or external
U3_RUN = "geode-jev-verdict-panel-latency-test"


def _external_rows(count: int, clusters: int = 3) -> list[dict[str, Any]]:
    """Synthetic rows in the X1 builder's shape: extra fields around a four-key state."""
    rows = []
    for index in range(count):
        state = {
            "task_contract": "Judge whether the web agent completed the instruction.",
            "original_request": f"Find listing {index} and report its price.",
            "candidate_output": f"Listing {index} costs 12 dollars.",
            "tool_observations": [
                {
                    "tool_call_id": "t000",
                    "tool": "session_start",
                    "input": {"init_url": None},
                    "result": {"start_timestamp": "2026-01-01T00:00:00Z"},
                },
                {
                    "tool_call_id": "t001",
                    "tool": "click",
                    "input": {"thoughts": f"open listing {index}"},
                    "result": None,
                    "timestamp": "2026-01-01T00:00:05Z",
                },
            ],
        }
        canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows.append(
            {
                "state_id": f"x1-{index:016x}",
                "cluster_id": f"om2w:site{index % clusters}",
                "split": "x1",
                "stratum": "fara7b_om2w_browserbase",
                "source_split": "fara7b_om2w_browserbase",
                "language": "en",
                "headline": True,
                "source_task_id": f"synthetic--{index}",
                "truncation": {"applied": False, "actions": 1, "chars_before": 1, "chars_after": 1},
                "state": state,
                "state_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            }
        )
    return rows


def _choice_unit(
    tmp_path: Path,
    *,
    mode: str = runner.LATIN_MODE,
    concurrency: int = 4,
    pacing: float = 0.0,
    run_id: str = "geode-jev-external-cuavb-choice-test",
) -> runner.PanelUnit:
    return runner.PanelUnit(
        run_ids={"choice": run_id},
        outputs={"choice": tmp_path / "choice"},
        session_dir=tmp_path / "session",
        pacing_s=pacing,
        max_concurrency=concurrency,
        heartbeat_s=0.01,
        mode=mode,
    )


def _drive(
    unit: runner.PanelUnit,
    workloads: list[runner.Workload],
    *,
    astra: _Astra | None = None,
    transport: Any = _default_transport,
    guard: Any = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Any = asyncio.sleep,
) -> dict[str, Any]:
    async def main() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await runner.PanelRunner(
                unit,
                workloads,
                llm_adapter=astra or _Astra(),
                jev_client=client,
                jev_key=SecretStr("synthetic-key"),
                jev_guard=guard,
                clock=clock,
                sleep=sleep,
            ).run()

    return asyncio.run(main())


def _receipts(unit: runner.PanelUnit) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(workload, engine) -> retained receipts in attempt order."""
    found: dict[tuple[str, str], list[dict[str, Any]]] = {}
    directory = unit.outputs["choice"]
    for row in validate_attempts(directory / "attempts.jsonl"):
        receipt = json.loads((directory / row["evidence_refs"][0]["path"]).read_text())
        found.setdefault((receipt["workload_id"], receipt["engine"]), []).append(receipt)
    return found


def test_panel_unit_takes_choice_alone_and_pins_the_paired_mode(tmp_path: Path) -> None:
    choice: dict[str, Any] = {"run_ids": {"choice": "c"}, "outputs": {"choice": tmp_path}}
    runner.PanelUnit(session_dir=tmp_path, **choice).validate()
    paired = runner.PanelUnit(
        session_dir=tmp_path, mode=runner.PAIRED_LATENCY_MODE, max_concurrency=2, **choice
    )
    paired.validate()
    assert paired.primitives == ("choice",)
    both: dict[str, Any] = {
        "run_ids": {"choice": "c", "noul": "n"},
        "outputs": {"choice": tmp_path, "noul": tmp_path},
    }
    rejected: list[dict[str, Any]] = [
        {"run_ids": {"noul": "n"}, "outputs": {"noul": tmp_path}},
        {"run_ids": {"choice": "c"}, "outputs": {"choice": tmp_path, "noul": tmp_path}},
        {**choice, "mode": "sequential"},
        {**choice, "mode": runner.PAIRED_LATENCY_MODE},  # four in flight is not one pair
        {**choice, "mode": runner.PAIRED_LATENCY_MODE, "max_concurrency": 1},
        {**both, "mode": runner.PAIRED_LATENCY_MODE, "max_concurrency": 2},
    ]
    for kwargs in rejected:
        with pytest.raises(ValueError):
            runner.PanelUnit(session_dir=tmp_path, **kwargs).validate()
    assert runner.latin_cells(1, runner.CELLS[:2]) == (("jev", "choice"), ("llm", "choice"))


def test_choice_only_unit_runs_an_external_split_in_the_two_cell_rotation(tmp_path: Path) -> None:
    rows = _external_rows(6)
    order = panel.ordered_workload_ids([row["state_id"] for row in rows], MANIFEST)
    workloads = runner.workloads_from_states(rows, order)
    assert {workload.cluster_id for workload in workloads} == {
        "om2w:site0",
        "om2w:site1",
        "om2w:site2",
    }
    unit = _choice_unit(tmp_path)
    summary = _drive(unit, workloads)
    assert summary["planned_calls"] == summary["dispatched_calls"] == 12 and not summary["stopped"]
    assert set(summary["counts"]) == set(summary["attempts"]) == {"choice"}
    assert summary["counts"]["choice"]["admitted"] == 12 and "mode" not in summary
    assert not (tmp_path / "noul").exists()
    log = [
        json.loads(line)
        for line in (unit.session_dir / "dispatch-log.jsonl").read_text().splitlines()
    ]
    assert {row["primitive"] for row in log} == {"choice"}
    for index, workload_id in enumerate(order):
        engines = [row["engine"] for row in log if row["workload_id"] == workload_id]
        assert engines == (["llm", "jev"] if index % 2 == 0 else ["jev", "llm"])
    receipts = _receipts(unit)
    assert set(receipts) == {(state, engine) for state in order for engine in ("llm", "jev")}
    for (state_id, _), (receipt,) in receipts.items():
        assert receipt["primitive"] == "choice" and "call_timing" not in receipt
        assert receipt["receipt"]["contract"] == "v1" and receipt["state_id"] == state_id
        assert "source_task_id" not in json.dumps(receipt)


class _SlowAstra(_Astra):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        await asyncio.sleep(self.delay)
        return await super().acomplete(request)


def _slow_jev(delay: float) -> Any:
    async def transport(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay)
        return _default_transport(request)

    return transport


class _PacedClock:
    """Real monotonic time plus virtual pacing: the runner's sleeps advance an offset."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.monotonic() + self.offset

    async def sleep(self, seconds: float) -> None:
        self.offset += seconds
        await asyncio.sleep(0)


def test_paired_latency_launches_each_pair_together_and_runs_pairs_in_sequence(
    tmp_path: Path,
) -> None:
    rows = _external_rows(8)
    order = panel.ordered_workload_ids([row["state_id"] for row in rows], MANIFEST)
    workloads = runner.workloads_from_states(rows, order)
    unit = _choice_unit(tmp_path, mode=runner.PAIRED_LATENCY_MODE, concurrency=2, run_id=U3_RUN)
    summary = _drive(unit, workloads, astra=_SlowAstra(0.08), transport=_slow_jev(0.02))
    assert summary["mode"] == "paired-latency" and not summary["stopped"]
    assert summary["planned_calls"] == summary["dispatched_calls"] == 16
    assert 0 <= summary["max_dispatch_skew_s"] < 0.25
    receipts = _receipts(unit)
    previous_end = None
    for index, workload_id in enumerate(order):
        (llm,), (jev,) = receipts[(workload_id, "llm")], receipts[(workload_id, "jev")]
        a, b = llm["call_timing"], jev["call_timing"]
        # Launched together: a small launch skew and two calls in flight at once.
        assert abs(a["dispatched_monotonic_s"] - b["dispatched_monotonic_s"]) < 0.25
        assert a["dispatched_monotonic_s"] < b["completed_monotonic_s"]
        assert b["dispatched_monotonic_s"] < a["completed_monotonic_s"]
        first, second = (a, b) if index % 2 == 0 else (b, a)
        assert (first["position"], second["position"]) == (0, 1)
        assert (first["in_flight_panel_calls"], second["in_flight_panel_calls"]) == (0, 1)
        for receipt in (llm, jev):
            timing = receipt["call_timing"]
            span = timing["completed_monotonic_s"] - timing["dispatched_monotonic_s"]
            assert receipt["latency_s"] == pytest.approx(span)
            assert timing["dispatched_at"] <= timing["completed_at"]
        # One pair in flight: the next pair starts after both calls finished.
        start = min(a["dispatched_monotonic_s"], b["dispatched_monotonic_s"])
        if previous_end is not None:
            assert start >= previous_end
        previous_end = max(a["completed_monotonic_s"], b["completed_monotonic_s"])
    pair_log = [
        json.loads(line) for line in (unit.session_dir / "pair-log.jsonl").read_text().splitlines()
    ]
    assert [entry["workload_id"] for entry in pair_log] == order
    assert [entry["launch_order"] for entry in pair_log] == [
        ["llm", "jev"] if index % 2 == 0 else ["jev", "llm"] for index in range(8)
    ]
    assert all(0 <= entry["dispatch_skew_s"] < 0.25 for entry in pair_log)
    report = runner.latency_report(unit.outputs["choice"], order, split_manifest_sha256=MANIFEST)
    assert report["summary"]["comparable_pairs"]["numerator"] == 8
    assert report["summary"]["launched_first"] == {"llm": 4, "jev": 4}
    assert report["primary"]["value"] < 0  # 20 ms Jev against 80 ms Astra
    # Three source clusters are below the ten-cluster interval minimum.
    assert report["primary"]["interval"]["lower"] is None
    assert report["primary"]["decision"] == "mixed"


def test_paired_latency_excludes_pacing_waits_from_latency(tmp_path: Path) -> None:
    rows = _external_rows(4)
    order = [row["state_id"] for row in rows]
    clock = _PacedClock()
    unit = _choice_unit(tmp_path, mode=runner.PAIRED_LATENCY_MODE, concurrency=2, pacing=30.0)
    summary = _drive(
        unit,
        runner.workloads_from_states(rows, order),
        astra=_SlowAstra(0.03),
        transport=_slow_jev(0.01),
        clock=clock,
        sleep=clock.sleep,
    )
    assert not summary["stopped"] and clock.offset > 85  # three paced gaps, simulated
    receipts = _receipts(unit)
    starts = []
    for workload_id in order:
        pair = [receipts[(workload_id, engine)][0] for engine in ("llm", "jev")]
        assert all(receipt["latency_s"] < 5 for receipt in pair)
        starts.append(min(r["call_timing"]["dispatched_monotonic_s"] for r in pair))
    # Pair starts keep the pacing interval. Launch stamps trail each pair start by the
    # launch overhead (session files, Jev ledger fsync), which exceeds 0.1 s on slow CI
    # runners; unpaced starts would sit ~0.03 s apart, so 1 s of slack still separates them.
    assert all(later - earlier > 29.0 for earlier, later in itertools.pairwise(starts))


def test_paired_replacement_stays_inside_its_pair_and_leaves_the_latency_summary(
    tmp_path: Path,
) -> None:
    rows = _external_rows(30, clusters=10)
    order = [row["state_id"] for row in rows]
    calls = {"count": 0}

    async def transport(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        await asyncio.sleep(0.004)
        if calls["count"] == 3:  # the third Jev call gets no response
            raise httpx.ConnectError("synthetic outage", request=request)
        return _default_transport(request)

    unit = _choice_unit(tmp_path, mode=runner.PAIRED_LATENCY_MODE, concurrency=2, run_id=U3_RUN)
    summary = _drive(
        unit, runner.workloads_from_states(rows, order), astra=_SlowAstra(0.04), transport=transport
    )
    assert summary["substitutions"] == 1 and not summary["stopped"]
    assert (
        summary["dispatched_calls"] == 60 and summary["counts"]["choice"]["invalid_unselected"] == 1
    )
    replaced = order[2]
    parent, child = _receipts(unit)[(replaced, "jev")]
    assert parent["status"] == "transport_error" and child["status"] == "admitted"
    # The replacement runs after the failure and before the next pair launches.
    assert (
        child["call_timing"]["dispatched_monotonic_s"]
        >= parent["call_timing"]["completed_monotonic_s"]
    )
    later = [_receipts(unit)[(order[3], engine)][0]["call_timing"] for engine in ("llm", "jev")]
    assert (
        min(t["dispatched_monotonic_s"] for t in later)
        >= child["call_timing"]["completed_monotonic_s"]
    )
    assert child["call_timing"]["in_flight_panel_calls"] <= 1
    report = runner.latency_report(unit.outputs["choice"], order, split_manifest_sha256=MANIFEST)
    assert report["pairs"][2]["excluded_reason"] == "replaced_call"
    assert report["summary"]["excluded_by_reason"]["replaced_call"] == 1
    assert report["summary"]["comparable_pairs"]["numerator"] == 29
    assert report["primary"]["reasons"] == [] and report["primary"]["interval"]["clusters"] == 10
    # Jev (4 ms) completes well before Astra (40 ms, room for slow CI runners): the whole
    # interval is below 0 s.
    assert report["primary"]["interval"]["upper"] < 0
    assert report["primary"]["decision"] == "supported"
    spec = _latency_spec(tmp_path / "spec.json", order)
    runner.record_latency_aggregate(unit.outputs["choice"], report)
    validate_analysis(
        _latency_analysis(unit.outputs["choice"], spec, report),
        run_spec_path=spec,
        attempts_path=unit.outputs["choice"] / "attempts.jsonl",
    )


class _LateJevGuard(_Guard):
    """Delays every Jev launch by two simulated seconds inside its admission."""

    def __init__(self, clock: _PacedClock) -> None:
        super().__init__()
        self.clock = clock

    def admit_call(self, attempt_id: str) -> None:
        super().admit_call(attempt_id)
        self.clock.offset += 2.0


def test_paired_launch_skew_above_one_second_stops_the_unit(tmp_path: Path) -> None:
    rows = _external_rows(4)
    order = [row["state_id"] for row in rows]
    clock = _PacedClock()
    unit = _choice_unit(tmp_path, mode=runner.PAIRED_LATENCY_MODE, concurrency=2, run_id=U3_RUN)
    summary = _drive(
        unit,
        runner.workloads_from_states(rows, order),
        astra=_SlowAstra(0.03),
        transport=_slow_jev(0.01),
        guard=_LateJevGuard(clock),
        clock=clock,
        sleep=clock.sleep,
    )
    assert summary["stopped"] and summary["stop_reason"] == "dispatch_skew_exceeded"
    assert summary["dispatched_calls"] == 2 and summary["max_dispatch_skew_s"] > 1
    report = runner.latency_report(unit.outputs["choice"], order, split_manifest_sha256=MANIFEST)
    assert report["primary"]["reasons"] == [
        "incomplete_planned_pairs",
        "dispatch_skew_exceeded",
        "no_comparable_pairs",
    ]
    assert report["primary"]["value"] == "not-measurable"
    assert report["pairs"][0]["excluded_reason"] == "dispatch_skew_exceeded"
    assert report["summary"]["excluded_by_reason"]["missing_attempt"] == 3
    spec = _latency_spec(tmp_path / "spec.json", order)
    runner.record_latency_aggregate(unit.outputs["choice"], report)
    aggregate = json.loads((unit.outputs["choice"] / "attempts.jsonl").read_text().splitlines()[-1])
    assert aggregate["validity"] == "invalid"
    assert aggregate["failure_class"] == "incomplete_planned_pairs"
    validate_analysis(
        _latency_analysis(unit.outputs["choice"], spec, report),
        run_spec_path=spec,
        attempts_path=unit.outputs["choice"] / "attempts.jsonl",
    )


def _latency_spec(path: Path, workload_ids: list[str], run_id: str = U3_RUN) -> Path:
    spec: dict[str, Any] = _run_spec()
    spec["run_id"] = run_id
    spec["created_at"] = spec["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec["study"]["primary_metric"] = {
        "name": runner.LATENCY_PRIMARY,
        "unit": "s",
        "direction": "target",
        "aggregation": "median over states of (Jev latency - Astra latency); denominator 1",
        "denominator": 1,
    }
    execution = spec["reproduction"]["execution"]
    execution.update(
        ordered_workload_ids=workload_ids,
        workload_ids_sha256=_workload_hash(workload_ids),
        max_concurrency=2,
    )
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _latency_analysis(run_dir: Path, spec: Path, report: dict[str, Any]) -> Path:
    attempts = [json.loads(line) for line in (run_dir / "attempts.jsonl").read_text().splitlines()]
    selected = [row for row in attempts if row["selected_for_analysis"]]
    path = run_dir / "analysis.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": "geode.eval-analysis@1",
                "schema_version": 1,
                "run_id": attempts[0]["run_id"],
                "analyzed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_spec_sha256": _sha(spec),
                "attempts_sha256": _sha(run_dir / "attempts.jsonl"),
                "selected_attempt_ids": [row["attempt_id"] for row in selected],
                "answer": "Synthetic U3 paired latency aggregation; no model was called.",
                "metrics": runner.latency_metric_rows(report),
                "decision": {
                    "outcome": "diagnostic-only",
                    "hypothesis_status": report["primary"]["decision"],
                    "rationale": "Preregistered U3 rule on the within-pair median interval.",
                },
                "limitations": ["Synthetic fixture."],
                "evidence_refs": [ref for row in selected for ref in row["evidence_refs"]],
            }
        ),
        encoding="utf-8",
    )
    return path


def _latency_run(directory: Path, pairs: list[dict[str, Any]], run_id: str = U3_RUN) -> list[str]:
    """Write a paired-latency run in the runner's retained format; return its plan.

    A side is a latency (admitted), ``None`` (never launched) or a
    ``(status, latency)`` tuple with status ``rejected``, ``quota_exhausted`` or
    ``replaced`` (an unselected transport failure, then an admitted child launched
    after its sibling). Pair ``i`` launches at ``100 * i`` seconds, A first on even
    ``i``; ``skew`` (default 2 ms) delays the second launch.
    """
    rows: list[dict[str, Any]] = []

    def record(pair: dict[str, Any], engine: str, status: str, **fields: Any) -> str:
        attempt_id = f"{run_id}-a{len(rows):05d}"
        dispatched, latency, position = fields.pop("timing")
        accepted = status == "admitted"
        evidence: dict[str, Any] = {
            "attempt_id": attempt_id,
            "workload_id": pair["state"],
            "state_id": pair["state"],
            "cluster_id": pair["cluster"],
            "variant": "base",
            "engine": engine,
            "primitive": "choice",
            "status": status,
            "error_type": None,
            "latency_s": latency,
            "observed_result": "synthetic",
            "call_timing": {
                "position": position,
                "in_flight_panel_calls": position,
                "dispatched_at": "2026-02-01T00:00:00Z",
                "completed_at": "2026-02-01T00:00:01Z",
                "dispatched_monotonic_s": dispatched,
                "completed_monotonic_s": dispatched + latency,
            },
        }
        if status in {"admitted", "rejected"}:
            verdict = pair.get("verdicts", {}).get(engine, "supported")
            evidence["receipt"] = {
                "accepted": accepted,
                "verdict": verdict if accepted else None,
                "probabilities": dict.fromkeys(LABELS, 0.1) | {verdict: 0.8} if accepted else None,
            }
        path = directory / "receipts" / f"{attempt_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        rows.append(
            {
                "schema_id": "geode.eval-attempt@1",
                "schema_version": 1,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "parent_attempt_id": fields.pop("parent", None),
                "sequence": len(rows),
                "timing": {
                    "status": "exact",
                    "started_at": "2026-02-01T00:00:00Z",
                    "finished_at": "2026-02-01T00:00:01Z",
                    "source_ref": None,
                },
                "change": {"surface": "judgment-panel", "description": "synthetic"},
                "expected_effect": "synthetic",
                "observed_result": "synthetic",
                "error_ref": None,
                "evidence_refs": [
                    {
                        "kind": "native-result",
                        "path": f"receipts/{attempt_id}.json",
                        "sha256": _sha(path),
                    }
                ],
                **fields,
            }
        )
        return attempt_id

    valid = {"validity": "valid", "selected_for_analysis": True}
    for index, pair in enumerate(pairs):
        engines = ["llm", "jev"] if index % 2 == 0 else ["jev", "llm"]
        for position, engine in enumerate(engines):
            side = pair[engine]
            if side is None:
                continue
            status, latency = ("admitted", side) if isinstance(side, float) else side
            launch = 100.0 * index + position * pair.get("skew", 0.002)
            if status == "replaced":
                parent = record(
                    pair,
                    engine,
                    "transport_error",
                    timing=(launch, 60.0, position),
                    validity="invalid",
                    outcome="unknown",
                    failure_class="transport_error",
                    selected_for_analysis=False,
                )
                record(
                    pair,
                    engine,
                    "admitted",
                    timing=(launch + 60.0, latency, position),
                    parent=parent,
                    outcome="passed",
                    failure_class=None,
                    **valid,
                )
            elif status == "quota_exhausted":
                record(
                    pair,
                    engine,
                    status,
                    timing=(launch, latency, position),
                    validity="invalid",
                    outcome="unknown",
                    failure_class=status,
                    selected_for_analysis=True,
                )
            else:
                record(
                    pair,
                    engine,
                    status,
                    timing=(launch, latency, position),
                    outcome="passed" if status == "admitted" else "failed",
                    failure_class=None if status == "admitted" else "invalid_judge_output",
                    **valid,
                )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "attempts.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    return [pair["state"] for pair in pairs]


def _pairs(deltas: list[float], clusters: int = 12) -> list[dict[str, Any]]:
    """Astra 10 s plus a small spread; Jev = Astra + delta; round-robin clusters."""
    return [
        {
            "state": f"s-{index:03d}",
            "cluster": f"cl-{index % clusters:02d}",
            "llm": 10.0 + index % 5 * 0.25,
            "jev": 10.0 + index % 5 * 0.25 + delta,
        }
        for index, delta in enumerate(deltas)
    ]


@pytest.mark.parametrize(
    ("deltas", "decision"),
    [
        ([-8.0 + index % 3 for index in range(24)], "supported"),
        ([4.0 + index % 3 for index in range(24)], "not-supported"),
        ([(-1.0) ** index * (1 + index % 4) for index in range(24)], "mixed"),
    ],
)
def test_latency_primary_is_the_paired_median_with_cluster_interval_and_decision(
    tmp_path: Path, deltas: list[float], decision: str
) -> None:
    from evals.benchmarks.decision_metrics import bootstrap_seed

    pairs = _pairs(deltas)
    plan = _latency_run(tmp_path / "run", pairs)
    report = runner.latency_report(tmp_path / "run", plan, split_manifest_sha256=MANIFEST)
    primary = report["primary"]
    expected = statistics.median(pair["jev"] - pair["llm"] for pair in pairs)
    assert primary["value"] == pytest.approx(expected) and primary["reasons"] == []
    assert primary["numerator"] == primary["value"] and primary["denominator"] == 1
    interval = primary["interval"]
    assert interval["seed"] == bootstrap_seed(MANIFEST, "paired_median_latency_delta_s")
    assert interval["replicates"] == 2000 and interval["clusters"] == 12
    assert interval["lower"] <= primary["value"] <= interval["upper"]
    assert primary["decision"] == decision
    assert report["summary"]["comparable_pairs"] == {
        "value": 1.0,
        "numerator": 24,
        "denominator": 24,
    }
    assert report["summary"]["max_dispatch_skew_s"]["value"] == pytest.approx(0.002)
    # Same inputs, same bytes: the interval is reproducible from the manifest seed.
    again = runner.latency_report(tmp_path / "run", plan, split_manifest_sha256=MANIFEST)
    assert json.dumps(again, sort_keys=True) == json.dumps(report, sort_keys=True)
    spec = _latency_spec(tmp_path / "spec.json", plan)
    runner.record_latency_aggregate(tmp_path / "run", report)
    rows = {row["name"]: row for row in runner.latency_metric_rows(report)}
    assert rows["paired_median_latency_delta_s"]["source_locator"]["value"] == "/primary/value"
    assert rows["llm_choice_median_latency_s"]["unit"] == "s"
    validate_analysis(
        _latency_analysis(tmp_path / "run", spec, report),
        run_spec_path=spec,
        attempts_path=tmp_path / "run" / "attempts.jsonl",
    )


def test_latency_summary_drops_invalid_pairs_with_reasons_and_accuracy_keeps_them(
    tmp_path: Path,
) -> None:
    pairs = _pairs([-2.0 - index % 3 for index in range(24)])
    pairs[0]["jev"] = ("rejected", 1.0)  # judgment-output invalid: valid, wrong
    pairs[1]["llm"] = ("replaced", 9.0)  # §4.2 child launched after its sibling
    pairs[2]["skew"] = 0.9  # within the one-second tolerance: stays comparable
    pairs[3]["verdicts"] = {"llm": "contradicted"}
    plan = _latency_run(tmp_path / "run", pairs)
    gold = {pair["state"]: {"verdict": "supported"} for pair in pairs}
    report = runner.latency_report(
        tmp_path / "run", plan, split_manifest_sha256=MANIFEST, gold=gold
    )
    summary = report["summary"]
    assert summary["comparable_pairs"]["numerator"] == 22 and summary["excluded_pairs"] == 2
    assert summary["excluded_by_reason"] == {
        "missing_attempt": 0,
        "infrastructure_invalid": 0,
        "replaced_call": 1,
        "judgment_output_invalid": 1,
        "dispatch_skew_exceeded": 0,
    }
    assert [pair["excluded_reason"] for pair in report["pairs"][:3]] == [
        "judgment_output_invalid",
        "replaced_call",
        None,
    ]
    # The replaced side's launch skew is measured between the two original launches.
    assert report["pairs"][1]["dispatch_skew_s"] == pytest.approx(0.002)
    expected = statistics.median(pair["jev"] - pair["llm"] for pair in pairs[2:])
    assert report["primary"]["value"] == pytest.approx(expected)
    assert report["primary"]["reasons"] == []
    # Accuracy keeps all 24 planned states; the Jev rejection counts as wrong.
    assert report["accuracy"]["jev"] == {
        "value": 23 / 24,
        "numerator": 23,
        "denominator": 24,
        "reasons": [],
    }
    assert report["accuracy"]["llm"]["numerator"] == 23  # one wrong verdict
    spec = _latency_spec(tmp_path / "spec.json", plan)
    runner.record_latency_aggregate(tmp_path / "run", report)
    rows = {row["name"]: row for row in runner.latency_metric_rows(report)}
    assert rows["jev_choice_accuracy"]["value"] == pytest.approx(23 / 24)
    assert rows["latency_comparable_pair_ratio"]["numerator"] == 22
    validate_analysis(
        _latency_analysis(tmp_path / "run", spec, report),
        run_spec_path=spec,
        attempts_path=tmp_path / "run" / "attempts.jsonl",
    )


@pytest.mark.parametrize(
    ("change", "reasons", "excluded"),
    [
        ({"jev": ("quota_exhausted", 0.5)}, ["selected_invalid_attempt"], "infrastructure_invalid"),
        ({"jev": None}, ["incomplete_planned_pairs"], "missing_attempt"),
        ({"skew": 1.5}, ["dispatch_skew_exceeded"], "dispatch_skew_exceeded"),
    ],
)
def test_latency_primary_is_not_measurable_for_an_invalid_unit(
    tmp_path: Path, change: dict[str, Any], reasons: list[str], excluded: str
) -> None:
    pairs = _pairs([-2.0] * 12)
    pairs[5].update(change)
    plan = _latency_run(tmp_path / "run", pairs)
    gold = {pair["state"]: {"verdict": "supported"} for pair in pairs}
    report = runner.latency_report(
        tmp_path / "run", plan, split_manifest_sha256=MANIFEST, gold=gold
    )
    assert report["primary"]["reasons"] == reasons
    assert report["primary"]["value"] == "not-measurable"
    assert report["primary"]["decision"] == "invalidated"
    assert report["pairs"][5]["excluded_reason"] == excluded
    assert report["summary"]["excluded_by_reason"][excluded] == 1
    # The descriptive medians still cover the 11 comparable pairs.
    assert report["summary"]["median_latency_s"]["jev"]["value"] != "not-measurable"
    if excluded != "dispatch_skew_exceeded":
        assert report["accuracy"]["jev"]["value"] == "not-measurable"
    spec = _latency_spec(tmp_path / "spec.json", plan)
    runner.record_latency_aggregate(tmp_path / "run", report)
    aggregate = json.loads((tmp_path / "run" / "attempts.jsonl").read_text().splitlines()[-1])
    assert aggregate["validity"] == "invalid" and aggregate["failure_class"] == reasons[0]
    rows = {row["name"]: row for row in runner.latency_metric_rows(report)}
    assert rows["paired_median_latency_delta_s"]["source_locator"] is None
    validate_analysis(
        _latency_analysis(tmp_path / "run", spec, report),
        run_spec_path=spec,
        attempts_path=tmp_path / "run" / "attempts.jsonl",
    )


def test_latency_report_rejects_unpaired_unplanned_and_duplicate_calls(tmp_path: Path) -> None:
    plan = _latency_run(tmp_path / "run", _pairs([-1.0] * 2))
    with pytest.raises(ValueError, match="not planned"):
        runner.latency_report(tmp_path / "run", plan[:1], split_manifest_sha256=MANIFEST)
    with pytest.raises(ValueError, match="SHA-256"):
        runner.latency_report(tmp_path / "run", plan, split_manifest_sha256="manifest")
    with pytest.raises(ValueError, match="cover every planned"):
        runner.latency_report(tmp_path / "run", plan, split_manifest_sha256=MANIFEST, gold={})
    rows = (tmp_path / "run" / "attempts.jsonl").read_text().splitlines()
    (tmp_path / "run" / "attempts.jsonl").write_text("\n".join([*rows, rows[0]]) + "\n")
    with pytest.raises(ValueError, match="twice"):
        runner.latency_report(tmp_path / "run", plan, split_manifest_sha256=MANIFEST)
    # A Latin-mode Choice run carries no call timing, so it is not a U3 run.
    latin = _choice_unit(tmp_path / "latin")
    rows_x = _external_rows(2)
    _drive(latin, runner.workloads_from_states(rows_x, [row["state_id"] for row in rows_x]))
    with pytest.raises(ValueError, match="not a paired-latency attempt"):
        runner.latency_report(
            latin.outputs["choice"],
            [row["state_id"] for row in rows_x],
            split_manifest_sha256=MANIFEST,
        )


def test_latency_cli_records_the_aggregate_without_a_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _latency_run(tmp_path / "run", _pairs([-3.0 + index % 2 for index in range(20)]))
    spec = _latency_spec(tmp_path / "spec.json", plan)
    manifest = tmp_path / "split-manifest.x1.json"
    manifest.write_text('{"schema_id": "geode.jev-external-unit-manifest@1"}\n')
    code = runner.main(
        [
            "latency",
            "--run-spec",
            str(spec),
            "--run-dir",
            str(tmp_path / "run"),
            "--split-manifest",
            str(manifest),
            "--record",
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["primary"]["value"] == pytest.approx(-2.5)
    assert printed["primary"]["decision"] == "supported"
    recorded = json.loads((tmp_path / "run" / runner.LATENCY_RESULTS).read_text())
    assert recorded["split_manifest_sha256"] == _sha(manifest)
    lost = _latency_run(
        tmp_path / "lost",
        [*_pairs([-1.0] * 11), {"state": "s-x", "cluster": "c", "llm": 1.0, "jev": None}],
    )
    spec_lost = _latency_spec(tmp_path / "spec-lost.json", lost)
    assert (
        runner.main(
            [
                "latency",
                "--run-spec",
                str(spec_lost),
                "--run-dir",
                str(tmp_path / "lost"),
                "--split-manifest",
                str(manifest),
            ]
        )
        == 1
    )


# ---------------------------------------------------------------------------
# I-panel: the inbox analyze_request helper as a Choice-only judgment (U0c, U6a)
# ---------------------------------------------------------------------------

IPANEL_RUN = "geode-jev-choice-intent-panel-test"
_IPANEL_TEMPLATES = (
    ("What's the status of {a}?", "status_only", 0, "explicit_status"),
    ("I need to cancel {a}, thanks.", "cancel", 0, "explicit_cancel"),
    ("Please refund {a}.", "refund", 0, "explicit_refund"),
    ("Not {a}, I meant {b}. What's its status?", "status_only", 1, "correction_status"),
    ("Where are all my parcels right now?", "status_only", None, "no_mention"),
)


def _ipanel(families: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A synthetic I-panel in the Run owner's format (``orders`` + ``cases``) and meta rows."""
    orders: dict[str, str] = {}
    cases, meta = [], []
    serial = 100
    for index in range(families):
        family_id = f"ip-t{index:02d}"
        items = []
        for position, (template, intent, target, phenomenon) in enumerate(_IPANEL_TEMPLATES):
            ids = []
            for _ in range(template.count("{")):
                serial += 1
                ids.append(f"{'ABCDEFGH'[serial % 8]}-{serial}")
                orders[ids[-1]] = ("shipped", "cancelled", "processing")[serial % 3]
            request = template.format(**dict(zip("ab", ids, strict=False)))
            expected = ids[target] if target is not None else None
            disposition = (
                ("answered" if expected else "needs_clarification")
                if intent == "status_only"
                else "unsupported"
            )
            items.append(
                {
                    "id": f"q{position + 1}",
                    "request": request,
                    "candidates": ids,
                    "expected_intent": intent,
                    "expected_order": expected,
                    "expected_answer": {
                        "order_id": expected,
                        "status": orders[expected] if disposition == "answered" else None,
                        "disposition": disposition,
                    },
                }
            )
            meta.append(
                {
                    "family_id": family_id,
                    "item_id": f"q{position + 1}",
                    "family_language": "en" if index % 2 == 0 else "mixed",
                    "language": "en",
                    "n_candidates": len(ids),
                    "phenomenon": phenomenon,
                    "gold_intent": intent,
                    "gold_target": expected,
                    "gold_target_key": f"order_{target}" if target is not None else "none",
                    "split": "analysis",
                }
            )
        cases.append({"id": family_id, "items": items})
    return {"authority": "synthetic", "orders": orders, "cases": cases}, meta


def _ipanel_truth(panel_file: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Request text -> (intent, target criteria key) from the labels."""
    from evals.benchmarks.decision_handoff import order_mentions

    truth = {}
    for case in panel_file["cases"]:
        for item in case["items"]:
            keys = {span["order_id"]: key for key, span in order_mentions(item["request"]).items()}
            truth[item["request"]] = (
                item["expected_intent"],
                keys.get(item["expected_order"], "none") if item["expected_order"] else "none",
            )
    return truth


def _helper_payload(request: AdapterCallRequest) -> dict[str, Any]:
    from html import unescape

    content = request.messages[0].content
    assert isinstance(content, str) and content.startswith("<decision_input>")
    return json.loads(
        unescape(content.removeprefix("<decision_input>").removesuffix("</decision_input>"))
    )


def _answers(
    payload: dict[str, Any], truth: dict[str, tuple[str, str]], wrong: set[tuple[str, str]]
) -> dict[str, str]:
    """Correct labels except the (request text, question) pairs in ``wrong``."""
    values = {}
    for key, item in payload["state"]["items"].items():
        intent, target = truth[item["request"]]
        labels = list(payload["questions"][f"{key}_intent"]["criteria"])
        targets = list(payload["questions"][f"{key}_target"]["criteria"])
        # A question with a single option (``none`` alone) cannot be answered wrongly.
        if (item["request"], "intent") in wrong:
            intent = next((label for label in labels if label != intent), intent)
        if (item["request"], "target") in wrong:
            target = next((label for label in targets if label != target), target)
        values[f"{key}_intent"], values[f"{key}_target"] = intent, target
    return values


class _IntentAstra(_Astra):
    """Typed Astra helper: labels only; optional wrong answers and a drifted family."""

    def __init__(
        self,
        truth: dict[str, tuple[str, str]],
        *,
        wrong: set[tuple[str, str]] = frozenset(),
        drift_on: str | None = None,
    ) -> None:
        super().__init__()
        self.truth, self.wrong, self.drift_on = truth, set(wrong), drift_on

    async def acomplete(self, request: AdapterCallRequest) -> AdapterCallResult:
        self.requests.append(request)
        payload = _helper_payload(request)
        values = _answers(payload, self.truth, self.wrong)
        drifted = self.drift_on is not None and any(
            item["request"] == self.drift_on for item in payload["state"]["items"].values()
        )
        await asyncio.sleep(0.002)
        return AdapterCallResult(
            text=json.dumps(values),
            usage=UsageSummary(input_tokens=1200, input_tokens_present=True),
            stop_reason="completed",
            response_model="gpt-6-sol" if drifted else ROOT_MODEL,
        )


def _intent_jev(
    truth: dict[str, tuple[str, str]],
    bodies: list[bytes],
    *,
    wrong: set[tuple[str, str]] = frozenset(),
    bad_sum_on: str | None = None,
    fail_calls: frozenset[int] = frozenset(),
) -> Any:
    async def transport(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        await asyncio.sleep(0.001)
        if len(bodies) in fail_calls:
            raise httpx.ConnectError("synthetic outage", request=request)
        payload = json.loads(request.content)
        values = _answers(payload, truth, set(wrong))
        answers = {}
        for question, chosen in values.items():
            labels = list(payload["questions"][question]["criteria"])
            rest = (0.2 / (len(labels) - 1)) if len(labels) > 1 else 0.0
            probabilities = {label: (0.8 if label == chosen else rest) for label in labels}
            if len(labels) == 1:
                probabilities = {chosen: 1.0}
            answers[question] = {
                "type": "choice",
                "choice": chosen,
                "probabilities": probabilities,
                "confidence": 0.6,
            }
        if bad_sum_on is not None and any(
            item["request"] == bad_sum_on for item in payload["state"]["items"].values()
        ):
            first = next(iter(answers.values()))
            first["probabilities"][first["choice"]] += 0.01  # above the strict 1e-5 bound
        body = {"model": JEV_MODEL, "usage": {"input_tokens": 900, "output_tokens": 0}}
        return httpx.Response(200, content=json.dumps({**body, "answers": answers}))

    return transport


def _intent_unit(tmp_path: Path, *, mode: str = runner.PAIRED_LATENCY_MODE) -> runner.PanelUnit:
    return runner.PanelUnit(
        run_ids={"choice": IPANEL_RUN},
        outputs={"choice": tmp_path / "choice"},
        session_dir=tmp_path / "session",
        pacing_s=0.0,
        max_concurrency=2 if mode == runner.PAIRED_LATENCY_MODE else 4,
        heartbeat_s=0.01,
        mode=mode,
        judgment=runner.INTENT_JUDGMENT,
    )


def _ipanel_spec(path: Path, family_ids: list[str], items: int, *, admission: bool = False) -> Path:
    spec: dict[str, Any] = _run_spec()
    spec["run_id"] = IPANEL_RUN
    spec["created_at"] = spec["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec["study"]["primary_metric"] = (
        {
            "name": runner.INTENT_ADMISSION_PRIMARY,
            "unit": "ratio",
            "direction": "maximize",
            "aggregation": "admitted helper answers / planned calls",
            "denominator": 2 * len(family_ids),
        }
        if admission
        else {
            "name": runner.INTENT_PRIMARY,
            "unit": "ratio",
            "direction": "target",
            "aggregation": "(Jev joint intent+target correct - Astra) / N_items; invalid = wrong",
            "denominator": items,
        }
    )
    execution = spec["reproduction"]["execution"]
    execution.update(
        ordered_workload_ids=family_ids,
        workload_ids_sha256=_workload_hash(family_ids),
        max_concurrency=2,
    )
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _ipanel_analysis(
    run_dir: Path, spec: Path, report: dict[str, Any], *, admission: bool = False
) -> Path:
    attempts = [json.loads(line) for line in (run_dir / "attempts.jsonl").read_text().splitlines()]
    selected = [row for row in attempts if row["selected_for_analysis"]]
    path = run_dir / "analysis.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": "geode.eval-analysis@1",
                "schema_version": 1,
                "run_id": attempts[0]["run_id"],
                "analyzed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "run_spec_sha256": _sha(spec),
                "attempts_sha256": _sha(run_dir / "attempts.jsonl"),
                "selected_attempt_ids": [row["attempt_id"] for row in selected],
                "answer": "Synthetic I-panel helper aggregation; no model was called.",
                "metrics": runner.intent_metric_rows(
                    report,
                    primary=runner.INTENT_ADMISSION_PRIMARY if admission else runner.INTENT_PRIMARY,
                ),
                "decision": {
                    "outcome": "diagnostic-only",
                    "hypothesis_status": report["admission" if admission else "primary"][
                        "decision"
                    ],
                    "rationale": "Preregistered U6a non-inferiority rule on the family interval.",
                },
                "limitations": ["Synthetic designer-style fixture."],
                "evidence_refs": [ref for row in selected for ref in row["evidence_refs"]],
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_ipanel(
    tmp_path: Path,
    families: int,
    *,
    astra: _IntentAstra | None = None,
    transport: Any = None,
    mode: str = runner.PAIRED_LATENCY_MODE,
) -> tuple[dict[str, Any], runner.PanelUnit, dict[str, Any], list[dict[str, Any]], list[str]]:
    panel_file, meta = _ipanel(families)
    truth = _ipanel_truth(panel_file)
    order = panel.ordered_workload_ids([case["id"] for case in panel_file["cases"]], "f" * 64)
    unit = _intent_unit(tmp_path, mode=mode)
    summary = _drive(
        unit,
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), order),
        astra=astra or _IntentAstra(truth),
        transport=transport or _intent_jev(truth, []),
    )
    return summary, unit, panel_file, meta, order


def test_intent_panel_rows_keep_labels_out_and_bind_each_family(tmp_path: Path) -> None:
    panel_file, _ = _ipanel(3)
    rows = runner.intent_panel_rows(panel_file)
    assert [row["state_id"] for row in rows] == ["ip-t00", "ip-t01", "ip-t02"]
    assert all(row["cluster_id"] == row["state_id"] for row in rows)
    for row in rows:
        assert set(row["state"]) == {"items"}
        assert all(set(item) == {"id", "request", "candidates"} for item in row["state"]["items"])
        assert "expected" not in json.dumps(row) and "shipped" not in json.dumps(row)
    workloads = runner.workloads_from_states(rows, ["ip-t02", "ip-t00"])
    assert [workload.cluster_id for workload in workloads] == ["ip-t02", "ip-t00"]
    broken = json.loads(json.dumps(panel_file))
    broken["cases"][0]["items"][0]["candidates"] = []
    with pytest.raises(ValueError, match="candidate"):
        runner.intent_panel_rows(broken)
    twice = {**panel_file, "cases": [panel_file["cases"][0], panel_file["cases"][0]]}
    with pytest.raises(ValueError, match="repeat"):
        runner.intent_panel_rows(twice)


def test_intent_unit_needs_choice_alone_and_base_families(tmp_path: Path) -> None:
    both: dict[str, Any] = {
        "run_ids": {"choice": "c", "noul": "n"},
        "outputs": {"choice": tmp_path, "noul": tmp_path},
    }
    with pytest.raises(ValueError, match="Choice alone"):
        runner.PanelUnit(session_dir=tmp_path, judgment=runner.INTENT_JUDGMENT, **both).validate()
    with pytest.raises(ValueError, match="judgment"):
        runner.PanelUnit(
            run_ids={"choice": "c"},
            outputs={"choice": tmp_path},
            session_dir=tmp_path,
            judgment="score",
        ).validate()
    panel_file, _ = _ipanel(1)
    row = runner.intent_panel_rows(panel_file)[0]
    with pytest.raises(ValueError, match="variants"):
        runner.PanelRunner(
            _intent_unit(tmp_path),
            runner.workloads_from_states([row], ["ip-t00#rep1"]),
            llm_adapter=_Astra(),
            jev_client=None,
            jev_key=None,
        )


def test_panel_and_e2e_helper_send_the_same_request(tmp_path: Path) -> None:
    """The panel family call and the E2E analyze_request tool ask identical questions."""
    from core.hooks.system import HookSystem
    from core.tools.base import ToolContext
    from evals.benchmarks.decision_handoff import DecisionHandoffTool
    from evals.benchmarks.decision_handoff_runtime import inbox_request

    panel_file, _ = _ipanel(1)
    truth = _ipanel_truth(panel_file)
    summary, unit, _, _, _ = _run_ipanel(tmp_path / "panel", 1)
    assert summary["counts"]["choice"]["admitted"] == 2
    panel_astra, panel_bodies = _IntentAstra(truth), []
    _drive(
        _intent_unit(tmp_path / "again"),
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), ["ip-t00"]),
        astra=panel_astra,
        transport=_intent_jev(truth, panel_bodies),
    )
    items = panel_file["cases"][0]["items"]
    requests = {item["id"]: item["request"] for item in items}
    hooks = HookSystem()
    context = ToolContext(
        hooks=hooks,
        session_id="session",
        turn_id="turn",
        step_id="step",
        tool_call_id="helper",
        provider="openai",
        source="subscription",
        model=ROOT_MODEL,
        effort="xhigh",
    )
    e2e_astra, e2e_bodies = _IntentAstra(truth), []

    async def e2e() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_intent_jev(truth, e2e_bodies))
        ) as client:
            source = inbox_request(items)
            return [
                await DecisionHandoffTool(
                    source, "a", adapter=e2e_astra, requests=requests
                ).aexecute(_tool_context=context),
                await DecisionHandoffTool(
                    source, "b", client=client, api_key=SecretStr("k"), requests=requests
                ).aexecute(_tool_context=context),
            ]

    try:
        outputs = asyncio.run(e2e())
    finally:
        hooks.close()
    assert all("result" in output for output in outputs)
    (panel_request,), (e2e_request,) = panel_astra.requests, e2e_astra.requests
    for name in (
        "model",
        "effort",
        "system_prompt",
        "messages",
        "response_schema",
        "allowed_tool_names",
        "tools",
        "tool_choice",
    ):
        assert getattr(panel_request, name) == getattr(e2e_request, name), name
    assert panel_bodies == e2e_bodies and len(panel_bodies) == 1
    # No fixture label or order status reaches either engine.
    sent = json.dumps(_helper_payload(panel_request)) + panel_bodies[0].decode()
    assert "expected" not in sent and "shipped" not in sent and "processing" not in sent
    receipt = json.loads(
        (
            unit.outputs["choice"]
            / validate_attempts(unit.outputs["choice"] / "attempts.jsonl")[0]["evidence_refs"][0][
                "path"
            ]
        ).read_text()
    )["receipt"]
    admitted = (
        outputs[0]["result"]["items"]
        if receipt["engine"] == "llm"
        else outputs[1]["result"]["items"]
    )
    assert receipt["contract"] == "analyze_request-inbox" and receipt["items"] == admitted


def test_intent_unit_scores_joint_accuracy_with_the_family_interval(tmp_path: Path) -> None:
    from evals.benchmarks.decision_metrics import bootstrap_seed

    panel_file, meta = _ipanel(12)
    truth = _ipanel_truth(panel_file)
    requests = [item["request"] for case in panel_file["cases"] for item in case["items"]]
    # Astra misses three targets; Jev misses one intent: delta = (57 - 56 ... ) per item.
    astra = _IntentAstra(
        truth, wrong={(requests[3], "target"), (requests[8], "target"), (requests[13], "target")}
    )
    jev_wrong = {(requests[1], "intent")}
    bodies: list[bytes] = []
    order = panel.ordered_workload_ids([case["id"] for case in panel_file["cases"]], "f" * 64)
    unit = _intent_unit(tmp_path)
    summary = _drive(
        unit,
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), order),
        astra=astra,
        transport=_intent_jev(truth, bodies, wrong=jev_wrong),
    )
    assert not summary["stopped"] and summary["planned_calls"] == summary["dispatched_calls"] == 24
    assert summary["mode"] == "paired-latency" and (unit.session_dir / "pair-log.jsonl").is_file()
    log = [
        json.loads(line)
        for line in (unit.session_dir / "dispatch-log.jsonl").read_text().splitlines()
    ]
    assert [row["workload_id"] for row in log[::2]] == order  # the frozen family order
    assert [row["engine"] for row in log[:4]] == ["llm", "jev", "jev", "llm"]
    # Within-pair helper latency is descriptive here (05 §3.6); the report reads it too.
    latency = runner.latency_report(unit.outputs["choice"], order, split_manifest_sha256="f" * 64)
    assert latency["summary"]["comparable_pairs"]["numerator"] == 12
    report = runner.intent_report(
        unit.outputs["choice"], order, panel=panel_file, meta=meta, split_manifest_sha256="f" * 64
    )
    primary = report["primary"]
    assert (primary["numerator"], primary["denominator"]) == (2, 60)
    assert primary["value"] == pytest.approx(2 / 60) and primary["reasons"] == []
    assert report["engines"]["llm"]["joint_accuracy"] == {
        "value": 57 / 60,
        "numerator": 57,
        "denominator": 60,
    }
    assert report["engines"]["jev"]["intent_accuracy"]["numerator"] == 59
    assert report["engines"]["llm"]["target_accuracy"]["numerator"] == 57
    assert report["engines"]["jev"]["helper_admitted"] == {
        "value": 1.0,
        "numerator": 12,
        "denominator": 12,
    }
    interval = primary["interval"]
    assert interval["seed"] == bootstrap_seed("f" * 64, "intent_joint_accuracy_delta")
    assert interval["clusters"] == 12 and interval["replicates"] == 2000
    assert interval["lower"] > -0.05 and primary["decision"] == "supported"
    strata = report["strata"]
    assert set(strata["phenomenon"]) == {row[3] for row in _IPANEL_TEMPLATES}
    assert strata["target"]["none"]["items"] == 12 and set(strata["n_candidates"]) == {
        "0",
        "1",
        "2",
    }
    assert set(strata["family_language"]) == {"en", "mixed"}
    spec = _ipanel_spec(tmp_path / "spec.json", order, 60)
    runner.record_intent_aggregate(unit.outputs["choice"], report)
    rows = {row["name"]: row for row in runner.intent_metric_rows(report)}
    assert (
        rows["intent_joint_accuracy_delta"]["source_locator"]["numerator"] == "/primary/numerator"
    )
    assert rows["jev_intent_joint_accuracy_phenomenon_correction_status"]["denominator"] == 12
    assert rows["llm_intent_helper_admitted_ratio"]["value"] == 1.0
    assert report["admission"]["numerator"] == 24 and report["admission"]["denominator"] == 24
    assert rows["intent_panel_admission_admitted_ratio"]["source_locator"]["value"] == (
        "/admission/value"
    )
    validate_analysis(
        _ipanel_analysis(unit.outputs["choice"], spec, report),
        run_spec_path=spec,
        attempts_path=unit.outputs["choice"] / "attempts.jsonl",
    )


def test_rejected_helper_output_makes_its_whole_family_wrong(tmp_path: Path) -> None:
    panel_file, meta = _ipanel(12)
    truth = _ipanel_truth(panel_file)
    bad = panel_file["cases"][4]["items"][2]["request"]
    order = [case["id"] for case in panel_file["cases"]]
    unit = _intent_unit(tmp_path, mode=runner.LATIN_MODE)
    summary = _drive(
        unit,
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), order),
        astra=_IntentAstra(truth),
        transport=_intent_jev(truth, [], bad_sum_on=bad),
    )
    assert not summary["stopped"] and summary["counts"]["choice"]["rejected"] == 1
    rejected = [
        row
        for row in validate_attempts(unit.outputs["choice"] / "attempts.jsonl")
        if row["outcome"] == "failed"
    ]
    assert len(rejected) == 1 and rejected[0]["failure_class"] == "invalid_judge_output"
    report = runner.intent_report(
        unit.outputs["choice"], order, panel=panel_file, meta=meta, split_manifest_sha256="f" * 64
    )
    family = [item for item in report["items"] if item["family_id"] == "ip-t04"]
    assert all(
        not item["jev"]["joint_correct"] and item["jev"]["status"] == "rejected" for item in family
    )
    assert report["engines"]["jev"]["joint_accuracy"]["numerator"] == 55
    assert report["engines"]["jev"]["helper_admitted"]["numerator"] == 11
    assert report["engines"]["jev"]["helper_calls"] == {"admitted": 11, "rejected": 1}
    assert report["admission"]["numerator"] == 23 and report["admission"]["decision"] == (
        "not-supported"
    )
    assert report["primary"]["numerator"] == -5 and report["primary"]["reasons"] == []


def test_intent_transport_and_route_failures_follow_the_panel_rules(tmp_path: Path) -> None:
    panel_file, meta = _ipanel(12)
    truth = _ipanel_truth(panel_file)
    order = [case["id"] for case in panel_file["cases"]]
    # A transport failure without a response is §4.2; one in 24 planned calls exceeds 2%.
    unit = _intent_unit(tmp_path / "transport")
    summary = _drive(
        unit,
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), order),
        astra=_IntentAstra(truth),
        transport=_intent_jev(truth, [], fail_calls=frozenset({3})),
    )
    assert summary["stop_reason"] == "substitution_rate_exceeded"
    failed = [
        row
        for row in validate_attempts(unit.outputs["choice"] / "attempts.jsonl")
        if row["validity"] == "invalid"
    ]
    assert [row["failure_class"] for row in failed] == ["transport_error"]
    # With 30 families (60 calls) one replacement fits under 2%: it runs inside the pair
    # and the family is scored once, through the admitted child.
    wide_file, wide_meta = _ipanel(30)
    wide_truth = _ipanel_truth(wide_file)
    wide_order = [case["id"] for case in wide_file["cases"]]
    wide = _intent_unit(tmp_path / "replaced")
    summary = _drive(
        wide,
        runner.workloads_from_states(runner.intent_panel_rows(wide_file), wide_order),
        astra=_IntentAstra(wide_truth),
        transport=_intent_jev(wide_truth, [], fail_calls=frozenset({3})),
    )
    assert summary["substitutions"] == 1 and not summary["stopped"]
    report = runner.intent_report(
        wide.outputs["choice"],
        wide_order,
        panel=wide_file,
        meta=wide_meta,
        split_manifest_sha256="f" * 64,
    )
    assert report["primary"]["reasons"] == [] and report["primary"]["numerator"] == 0
    assert report["engines"]["jev"]["joint_accuracy"]["numerator"] == 150
    assert report["admission"]["numerator"] == 60
    # A drifted Astra model is a route violation: selected, invalid, unit stopped.
    drifted = panel_file["cases"][2]["items"][0]["request"]
    route = _intent_unit(tmp_path / "route")
    summary = _drive(
        route,
        runner.workloads_from_states(runner.intent_panel_rows(panel_file), order),
        astra=_IntentAstra(truth, drift_on=drifted),
        transport=_intent_jev(truth, []),
    )
    assert summary["stop_reason"] == "route_violation"
    report = runner.intent_report(
        route.outputs["choice"], order, panel=panel_file, meta=meta, split_manifest_sha256="f" * 64
    )
    assert report["primary"]["reasons"] == [
        "incomplete_planned_families",
        "selected_invalid_attempt",
    ]
    assert report["primary"]["value"] == "not-measurable"
    assert report["primary"]["decision"] == "invalidated"
    spec = _ipanel_spec(tmp_path / "spec.json", order, 60)
    runner.record_intent_aggregate(route.outputs["choice"], report)
    aggregate = json.loads(
        (route.outputs["choice"] / "attempts.jsonl").read_text().splitlines()[-1]
    )
    assert aggregate["validity"] == "invalid"
    assert aggregate["failure_class"] == "incomplete_planned_families"
    validate_analysis(
        _ipanel_analysis(route.outputs["choice"], spec, report),
        run_spec_path=spec,
        attempts_path=route.outputs["choice"] / "attempts.jsonl",
    )


def test_intent_admission_batch_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """U0c's four admission families: 4 x 2 helper calls, admitted ratio, no interval."""
    summary, unit, panel_file, meta, order = _run_ipanel(tmp_path, 4)
    assert summary["planned_calls"] == 8 and summary["counts"]["choice"]["admitted"] == 8
    panel_path = tmp_path / "i-panel.admission.json"
    panel_path.write_text(json.dumps(panel_file), encoding="utf-8")
    meta_path = tmp_path / "i-panel-meta.jsonl"
    meta_path.write_text("".join(json.dumps(row) + "\n" for row in meta), encoding="utf-8")
    spec = _ipanel_spec(tmp_path / "spec.json", order, 20, admission=True)
    arguments = [
        "intent",
        "--run-spec",
        str(spec),
        "--run-dir",
        str(unit.outputs["choice"]),
        "--panel",
        str(panel_path),
        "--meta",
        str(meta_path),
        "--record",
    ]
    assert runner.main(arguments) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["primary"] == {
        "name": "intent_panel_admission_admitted_ratio",
        "unit": "ratio",
        "reasons": [],
        "value": 1.0,
        "numerator": 8,
        "denominator": 8,
        "decision": "supported",
    }
    assert "intent_joint_accuracy_delta" not in {row["name"] for row in printed["metrics"]}
    recorded = json.loads((unit.outputs["choice"] / runner.INTENT_RESULTS).read_text())
    assert recorded["panel_sha256"] == _sha(panel_path)
    assert recorded["primary"]["interval"]["lower"] is None  # four families < ten clusters
    validate_analysis(
        _ipanel_analysis(unit.outputs["choice"], spec, recorded, admission=True),
        run_spec_path=spec,
        attempts_path=unit.outputs["choice"] / "attempts.jsonl",
    )
    with pytest.raises(ValueError, match="unknown I-panel primary"):
        runner.intent_metric_rows(recorded, primary="other")
    with pytest.raises(ValueError, match="not planned"):
        runner.intent_report(
            unit.outputs["choice"],
            order[:2],
            panel=panel_file,
            meta=meta,
            split_manifest_sha256="f" * 64,
        )
