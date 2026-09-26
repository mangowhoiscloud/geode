"""Panel runner with fake engines: order, attempts contract and the substitution rule."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
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


def _stability_spec(path: Path, run_id: str, workload_ids: list[str]) -> Path:
    spec: dict[str, Any] = _run_spec()
    spec["run_id"] = run_id
    spec["created_at"] = spec["preregistration"]["frozen_at"] = "2026-01-01T00:00:00Z"
    spec["study"]["primary_metric"] = {
        "name": runner.STABILITY_PRIMARY,
        "unit": "ratio",
        "direction": "maximize",
        "aggregation": "Jev Choice rep1/rep2 both valid and equal / planned states",
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
            tmp_path / f"{primitive}-spec.json", unit.run_ids[primitive], workload_ids
        )
        runner.record_stability_aggregate(unit.outputs[primitive], report, primitive=primitive)
        rows = runner.stability_metric_rows(report, primitive=primitive)
        if primitive == "noul":
            continue  # the Noul run's own primary is set by its frozen run spec
        names = [row["name"] for row in rows]
        assert names[:3] == [
            "jev_choice_pair_consistency",
            "jev_choice_flip_rate_order_rev",
            "jev_choice_flip_rate_para",
        ]
        assert rows[0]["source_locator"]["value"] == "/primary/value"
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
