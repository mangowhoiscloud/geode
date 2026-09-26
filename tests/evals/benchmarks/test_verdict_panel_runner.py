"""Panel runner with fake engines: order, attempts contract and the substitution rule."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
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
from core.llm.errors import BillingError
from evals.benchmarks import verdict_panel as panel
from evals.benchmarks import verdict_panel_runner as runner
from evals.benchmarks.decision_handoff import JEV_MODEL, ROOT_MODEL
from pydantic import SecretStr
from scripts.eval.contract import validate_attempts

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
