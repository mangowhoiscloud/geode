"""Offline admission, accounting and append-only handoff pilot evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

import dotenv
import pytest
from scripts.eval import decision_handoff_pilot as pilot
from scripts.eval.contract import validate_analysis, validate_attempts, validate_run_spec


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("offline test must not read private credentials or launch a real child")

    monkeypatch.setattr(dotenv, "dotenv_values", forbidden)
    monkeypatch.setattr(pilot.subprocess, "run", forbidden)
    monkeypatch.setattr(pilot.shutil, "which", lambda _name: "/synthetic/git")
    monkeypatch.setattr(
        pilot.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else "",
    )


def _spec(tmp_path: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    spec = json.loads((pilot.ROOT / "docs/eval/eval-run-spec.template.json").read_text())
    cases = json.loads(pilot.FIXTURE.read_text())
    ids = [case["id"] for case in cases]
    spec.update(run_id="offline-handoff-pilot", created_at="2026-01-01T00:00:00Z")
    spec["preregistration"].update(
        frozen_at=spec["created_at"], live_test_approved=True, operator="offline-test"
    )
    spec["study"] = {
        "research_question": "Does the helper change the root task's verified success?",
        "research_gap": "A selector-only result did not establish root continuation.",
        "hypothesis": "Both helpers enable the same root task completion rate.",
        "primary_metric": dict(pilot.PRIMARY_METRIC),
        "decision_rule": "Report a bounded diagnostic, without adoption authority.",
        "invalidation_rule": "Any incomplete pair makes the primary unmeasurable.",
        "analysis_plan": "Preserve failures, partial usage and every attempted paired task.",
    }
    spec["reproduction"] = {
        "geode": {"revision": "a" * 40, "branch": "offline", "dirty": False},
        "harness": {"name": "handoff", "source": "local", "revision": "a" * 40},
        "model": {
            "provider": "openai",
            "label": pilot.MODEL,
            "route": "subscription",
            "reasoning": "xhigh",
        },
        "environment": {
            "platform": "offline-test",
            "architecture": "test",
            "reset_strategy": "Fresh temporary directory for every arm.",
            "initial_state_ref": f"sha256:{pilot._sha(pilot.FIXTURE)}",
        },
        "execution": {
            "command_redacted": "decision_handoff_pilot --run-spec run-spec.json",
            "ordered_workload_ids": ids,
            "workload_ids_sha256": hashlib.sha256(
                json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest(),
            "repetitions": 1,
            "seed_schedule": ["unseeded-fixed-fixture"],
            "max_concurrency": 1,
            "timeout_seconds": 180,
            "budget": {"kind": "combined", "limit": None, "unit": "uncapped"},
        },
        "comparison": {
            "claim_class": "diagnostic",
            "comparator": f"root-with-typesafe:{pilot.JEV_MODEL}:choice",
            "comparability": "direct",
            "promotion_authority": "none",
        },
    }
    spec["artifacts"].update(native_results="results.json")
    spec["privacy"]["redaction_boundary"] = "Private synthetic data; no account content."
    path = tmp_path / "run-spec.json"
    path.write_text(json.dumps(spec))
    assert validate_run_spec(path) == spec
    return path, spec, cases


def _call(
    purpose: str, model: str, usage: dict[str, Any], error: str | None = None
) -> dict[str, Any]:
    return {
        "purpose": purpose,
        "model": model,
        "llm_attempt_id": purpose,
        **pilot._accounting(
            {
                "response_model": model,
                "usage": usage,
                "error_type": error,
            }
        ),
    }


def _result(case: dict[str, Any], arm: str) -> dict[str, Any]:
    calls = [
        _call(
            "agentic_loop",
            pilot.MODEL,
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
            },
        ),
        _call(
            "structured_decision",
            pilot.MODEL if arm == "a" else pilot.JEV_MODEL,
            {
                "input_tokens": 5,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
            },
        ),
    ]
    return {
        "case_id": case["id"],
        "arm": arm,
        "valid": True,
        "passed": True,
        "error_type": None,
        "elapsed_seconds": 1.5,
        "call_accounting": calls,
        "usage": {
            "attempt_pairing_complete": True,
            "observation_status": "no_known_faults",
            "terminal_event_count": len(calls),
        },
    }


def _write_child(directory: Path, result: dict[str, Any]) -> None:
    pilot._write(directory / "result.json", result)
    for name in ("session-events.json", "call-events.json", "trajectory.json", "handoff.json"):
        pilot._write(directory / name, [])


@pytest.mark.parametrize(
    ("usage", "total", "observed"),
    [
        ({}, None, 0),
        ({"input_tokens": 0, "output_tokens": 0}, 0, 0),
        ({"input_tokens": 7}, None, 7),
        ({"output_tokens": 2}, None, 2),
        ({"input_tokens": True, "output_tokens": 2}, None, 2),
    ],
)
def test_accounting_distinguishes_missing_zero_and_partial(usage, total, observed):
    accounted = pilot._accounting({"usage": usage, "response_model": pilot.MODEL})
    assert accounted["total_tokens"] == total
    assert accounted["known_input_output_sum"] == observed
    assert accounted["reported_cost_usd"] is None
    assert accounted["subscription_api_equivalent_estimate_usd"] is None


def test_accounting_prices_cache_once_and_does_not_infer_invoice():
    accounted = pilot._accounting(
        {
            "response_model": pilot.MODEL,
            "cost_usd": 123,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_input_tokens": 200,
                "cache_write_tokens": 100,
                "reasoning_tokens": 40,
            },
        }
    )
    expected = (700 * 10 + 200 * 1 + 100 * 12.5 + 100 * 50) / 1_000_000
    assert accounted["total_tokens"] == 1100
    assert accounted["subscription_api_equivalent_estimate_usd"] == pytest.approx(expected)
    assert accounted["subscription_api_equivalent_bounds_usd"] == pytest.approx(
        [expected, expected]
    )
    assert accounted["reported_cost_usd"] is None
    missing = pilot._accounting(
        {"response_model": pilot.MODEL, "usage": {"input_tokens": 1000, "output_tokens": 100}}
    )
    assert missing["subscription_api_equivalent_estimate_usd"] is None
    assert missing["subscription_api_equivalent_bounds_usd"] == pytest.approx([0.006, 0.0175])


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 8, "cache_write_tokens": 3},
        {"input_tokens": 10, "output_tokens": 5, "reasoning_tokens": 6},
    ],
)
def test_contradictory_usage_keeps_raw_counts_but_not_valid_totals_or_price(usage):
    for model in (pilot.MODEL, pilot.JEV_MODEL):
        accounted = pilot._accounting({"response_model": model, "usage": usage})
        assert accounted["contradictory_usage"] is True
        assert accounted["total_tokens"] is None
        assert accounted["usage"]["input_tokens"] == 10
        assert accounted["typesafe_price_estimate_usd"] is None
        assert accounted["subscription_api_equivalent_estimate_usd"] is None


def test_typesafe_partial_input_price_and_provider_limit_are_separate_from_tokens():
    partial = pilot._accounting({"response_model": pilot.JEV_MODEL, "usage": {"input_tokens": 100}})
    assert partial["typesafe_price_estimate_usd"] == pytest.approx(100 * 0.042 / 1_000_000)
    assert partial["total_tokens"] is None
    large = pilot._accounting(
        {"response_model": pilot.JEV_MODEL, "usage": {"input_tokens": 64_001, "output_tokens": 0}}
    )
    assert large["total_tokens"] == 64_001
    assert large["typesafe_price_estimate_usd"] is None
    overflow = pilot._accounting(
        {"response_model": pilot.MODEL, "usage": {"input_tokens": 1, "output_tokens": 10**400}}
    )
    assert overflow["total_tokens"] == 1 + 10**400
    assert overflow["subscription_api_equivalent_bounds_usd"] is None


def test_typesafe_pinned_tariff_has_machine_readable_units_and_authority():
    tariff = pilot.PRICE_REFERENCE["typesafe"]
    assert tariff["model"] == "jev-1.13.0"
    assert tariff["source"] == "https://docs.typesafe.ai/models"
    assert tariff["checked_at"] == "2026-09-21"
    assert tariff["currency"] == "USD"
    assert tariff["unit"] == "USD per 1000000 input tokens"
    assert tariff["cents_unit"] == "US cents per 1000000 input tokens"
    assert tariff["input_usd_per_million"] == float(pilot.JEV_INPUT_USD_PER_MILLION) == 0.042
    assert (
        tariff["input_us_cents_per_million"] == float(pilot.JEV_INPUT_USD_PER_MILLION * 100) == 4.2
    )
    assert tariff["output_usd_per_million"] == 0
    assert tariff["charged_token_field"] == "input_tokens"
    assert tariff["cost_authority"] == "published-input-token-tariff-calculation"
    assert tariff["not_an_invoice"] is True


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens"), [(318, 34), (318, 0), (318, None), (0, 34), (0, None)]
)
def test_typesafe_free_output_preserves_actual_usage_without_charging_it(
    input_tokens, output_tokens
):
    # The official API example reports 318 input and 34 output tokens.
    usage = {"input_tokens": input_tokens}
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    accounted = pilot._accounting(
        {
            "response_model": pilot.JEV_MODEL,
            "response_id": "synthetic-request-id",
            "usage": usage,
            "cost_usd": 99,
        }
    )
    expected_usd = Decimal(input_tokens) * Decimal("0.042") / 1_000_000
    assert accounted["usage"]["input_tokens"] == input_tokens
    assert accounted["usage"]["output_tokens"] == output_tokens
    assert accounted["total_tokens"] == (
        input_tokens + output_tokens if output_tokens is not None else None
    )
    assert accounted["typesafe_price_estimate_usd"] == float(expected_usd)
    assert accounted["typesafe_price_estimate_us_cents"] == float(expected_usd * 100)
    assert accounted["reported_cost_usd"] is None
    assert accounted["response_id"] == "synthetic-request-id"


@pytest.mark.parametrize("input_tokens", [None, False, -1])
def test_typesafe_missing_or_invalid_input_never_becomes_zero_cost(input_tokens):
    accounted = pilot._accounting(
        {
            "response_model": pilot.JEV_MODEL,
            "usage": {"input_tokens": input_tokens, "output_tokens": 34},
        }
    )
    assert accounted["usage"]["output_tokens"] == 34
    assert accounted["typesafe_price_estimate_usd"] is None
    assert accounted["typesafe_price_estimate_us_cents"] is None
    assert accounted["reported_cost_usd"] is None


def test_typesafe_subcent_aggregate_uses_unrounded_input_tariff_not_output_completeness():
    calls = [
        _call("structured_decision", pilot.JEV_MODEL, {"input_tokens": count})
        for count in (1, 2, 3)
    ]
    aggregate = pilot._aggregate_accounting(calls, complete=True)
    usd = aggregate["costs"]["typesafe_price_estimate_usd"]
    cents = aggregate["costs"]["typesafe_price_estimate_us_cents"]
    expected_usd = Decimal(6) * Decimal("0.042") / 1_000_000
    assert all(0 < row["typesafe_price_estimate_us_cents"] < 1 for row in calls)
    assert usd["total"] == usd["observed_sum"] == float(expected_usd)
    assert cents["total"] == cents["observed_sum"] == float(expected_usd * 100)
    assert usd["missing_calls"] == cents["missing_calls"] == 0
    assert cents["unit"] == "US cents" and cents["currency"] == "USD"
    assert usd["authority"] == cents["authority"] == "published-input-token-tariff-calculation"
    assert aggregate["usage"]["output_tokens"]["missing_calls"] == 3
    assert aggregate["total_tokens"]["total"] is None
    calls.append(_call("structured_decision", pilot.JEV_MODEL, {"output_tokens": 34}))
    partial = pilot._aggregate_accounting(calls, complete=True)
    assert partial["costs"]["typesafe_price_estimate_us_cents"]["total"] is None
    assert partial["costs"]["typesafe_price_estimate_us_cents"]["observed_sum"] == float(
        expected_usd * 100
    )
    assert partial["costs"]["typesafe_price_estimate_usd"]["missing_calls"] == 1


def test_summary_groups_root_auxiliary_and_failed_consumption_without_filling_unknowns(tmp_path):
    _, _, cases = _spec(tmp_path)
    baseline, assisted = _result(cases[0], "a"), _result(cases[0], "b")
    assisted["call_accounting"].append(
        _call("agentic_loop", pilot.MODEL, {"input_tokens": 3}, "TimeoutError")
    )
    assisted["usage"]["terminal_event_count"] = 3
    assisted.update(valid=False, passed=False)
    summary = pilot._summary([{"a": baseline, "b": assisted}], "invalid_runtime_observation")
    assert summary["value"] == "not-measurable"
    by_arm = summary["arms"]
    assert by_arm["a"]["accounting"]["total_tokens"]["total"] == 17
    partial = by_arm["b"]["accounting"]
    assert partial["total_tokens"]["total"] is None
    assert partial["known_input_output_sum"] == 20
    assert partial["failed_calls"] == 1
    assert partial["usage"]["output_tokens"]["missing_calls"] == 1
    purposes = by_arm["b"]["by_purpose"]
    assert purposes["agentic_loop"]["known_input_output_sum"] == 15
    jev = purposes["structured_decision"]["costs"]["typesafe_price_estimate_usd"]
    assert jev["applicable_calls"] == jev["observed_calls"] == 1
    assert jev["total"] == pytest.approx(5 * 0.042 / 1_000_000)
    cents = purposes["structured_decision"]["costs"]["typesafe_price_estimate_us_cents"]
    assert cents["total"] == pytest.approx(jev["total"] * 100)
    assert partial["costs"]["reported_cost_usd"]["total"] is None
    assert partial["whole_runtime_complete"] is False


def test_preflight_is_clean_pinned_and_provider_free(tmp_path):
    path, spec, cases = _spec(tmp_path)
    assert pilot.preflight(path) == (spec, cases)
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize(
    "drift",
    ["unapproved", "revision", "harness", "fixture", "metric", "comparator", "cap", "future"],
)
def test_preflight_rejects_drift_without_artifacts(tmp_path, drift):
    path, spec, _ = _spec(tmp_path)
    if drift == "unapproved":
        spec["preregistration"]["live_test_approved"] = False
    elif drift == "future":
        spec["preregistration"]["frozen_at"] = "2999-01-01T00:00:00Z"
    elif drift in {"revision", "harness"}:
        spec["reproduction"]["harness" if drift == "harness" else "geode"]["revision"] = "b" * 40
    elif drift == "fixture":
        spec["reproduction"]["environment"]["initial_state_ref"] = "sha256:" + "b" * 64
    elif drift == "metric":
        spec["study"]["primary_metric"]["name"] = "mislabelled"
    elif drift == "comparator":
        spec["reproduction"]["comparison"]["comparator"] = "different-comparator"
    else:
        spec["reproduction"]["execution"]["budget"]["limit"] = 1
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        pilot.preflight(path)
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize("artifact", ["private", "results.json", "attempts.jsonl", "analysis.json"])
def test_preflight_rejects_existing_output(tmp_path, artifact):
    path, _, _ = _spec(tmp_path)
    (tmp_path / artifact).touch()
    with pytest.raises(ValueError, match="fresh run"):
        pilot.preflight(path)


def test_preflight_rejects_dirty_source(tmp_path, monkeypatch):
    path, _, _ = _spec(tmp_path)
    monkeypatch.setattr(
        pilot.subprocess,
        "check_output",
        lambda command, **kwargs: "a" * 40 if command[1] == "rev-parse" else " M file",
    )
    with pytest.raises(ValueError, match="clean pinned source"):
        pilot.preflight(path)


@pytest.mark.parametrize("failure_class", [None, "decision_response_rejected"])
def test_execute_binds_results_before_last_append_and_preserves_semantic_failure(
    tmp_path, monkeypatch, failure_class
):
    from core.memory import atomic_write

    path, spec, cases = _spec(tmp_path)
    dispatched = []
    previous_bytes = b""
    real_append = atomic_write.append_jsonl

    def append(target, row):
        nonlocal previous_bytes
        assert target.read_bytes() == previous_bytes
        if row["sequence"] == 4:
            result_ref = next(ref for ref in row["evidence_refs"] if ref["path"] == "results.json")
            assert result_ref["sha256"] == pilot._sha(tmp_path / "results.json")
        real_append(target, row)
        assert target.read_bytes().startswith(previous_bytes)
        previous_bytes = target.read_bytes()

    def child(command, **kwargs):
        index, arm = int(command[3]), command[5]
        if index:
            assert len((tmp_path / "attempts.jsonl").read_text().splitlines()) == index
        result = _result(cases[index], arm)
        if index == 2 and arm == "b":
            result["passed"] = False  # Valid semantic failure is not retried or invalidated.
            result["error_type"] = failure_class
        _write_child(Path(command[7]), result)
        dispatched.append((index, arm))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(atomic_write, "append_jsonl", append)
    monkeypatch.setattr(pilot.subprocess, "run", child)
    pilot.execute(path, spec, cases)
    attempts = validate_attempts(tmp_path / "attempts.jsonl")
    validate_analysis(
        tmp_path / "analysis.json", run_spec_path=path, attempts_path=tmp_path / "attempts.jsonl"
    )
    assert len(dispatched) == 10
    assert dispatched[:4] == [(0, "a"), (0, "b"), (1, "b"), (1, "a")]
    assert [row["outcome"] for row in attempts] == [
        "passed",
        "passed",
        "failed",
        "passed",
        "passed",
    ]
    assert all(
        row["observed_result"] == "Paired native task evidence retained." for row in attempts
    )
    assert attempts[2]["failure_class"] == failure_class
    summary = json.loads((tmp_path / "results.json").read_text())
    assert (summary["value"], summary["numerator"], summary["denominator"]) == (-0.2, -1, 5)
    assert summary["arms"]["a"]["accounting"]["total_tokens"]["total"] == 85
    assert summary["arms"]["b"]["by_purpose"]["structured_decision"]["total_tokens"]["total"] == 25
    assert any(ref["path"].endswith("trajectory.json") for ref in attempts[-1]["evidence_refs"])


@pytest.mark.parametrize("phase", ["before-first", "after-first", "before-second"])
@pytest.mark.parametrize("drift", ["head", "dirty", "unavailable"])
def test_source_drift_stops_dispatch_and_retains_available_evidence(
    tmp_path, monkeypatch, phase, drift
):
    path, spec, cases = _spec(tmp_path)
    checks = 0
    drift_check = {"before-first": 2, "after-first": 3, "before-second": 4}[phase]
    dispatched = []

    def source(command, **kwargs):
        nonlocal checks
        if command[1] == "rev-parse":
            checks += 1
            if checks >= drift_check and drift == "unavailable":
                raise subprocess.CalledProcessError(128, command)
            return "b" * 40 if checks >= drift_check and drift == "head" else "a" * 40
        return " M changed-source.py" if checks >= drift_check and drift == "dirty" else ""

    def child(command, **kwargs):
        index, arm = int(command[3]), command[5]
        dispatched.append((index, arm))
        _write_child(Path(command[7]), _result(cases[index], arm))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pilot.subprocess, "check_output", source)
    monkeypatch.setattr(pilot.subprocess, "run", child)
    pilot.execute(path, spec, cases)
    assert len(dispatched) == (0 if phase == "before-first" else 1)
    attempts = validate_attempts(tmp_path / "attempts.jsonl")
    assert len(attempts) == 1
    assert (attempts[0]["validity"], attempts[0]["outcome"]) == ("invalid", "unknown")
    validate_analysis(
        tmp_path / "analysis.json", run_spec_path=path, attempts_path=tmp_path / "attempts.jsonl"
    )
    summary = json.loads((tmp_path / "results.json").read_text())
    assert summary["stop_reason"] == "source_drift"
    assert summary["value"] == "not-measurable"
    if dispatched:
        assert any(
            ref["path"] == "private/00-a/result.json" for ref in attempts[0]["evidence_refs"]
        )
        accounting = summary["arms"]["a"]["accounting"]
        assert accounting["known_input_output_sum"] == 17
        assert accounting["total_tokens"]["total"] == (None if phase == "after-first" else 17)


@pytest.mark.parametrize("failure", ["exit", "timeout", "interrupt", "cancel", "db-only"])
def test_execute_preserves_failed_child_artifacts_and_partial_consumption(
    tmp_path, monkeypatch, failure
):
    path, spec, cases = _spec(tmp_path)
    dispatched = 0
    original = (
        KeyboardInterrupt("private parent interruption")
        if failure == "interrupt"
        else asyncio.CancelledError()
    )

    def child(command, **kwargs):
        nonlocal dispatched
        dispatched += 1
        directory = Path(command[7])
        if failure == "exit":
            _write_child(directory, _result(cases[0], "a"))
            return subprocess.CompletedProcess(command, 1)
        if failure != "db-only":
            pilot._write(
                directory / "call-events.json",
                [
                    {
                        "action": "llm.call.ended",
                        "llm_attempt_id": "partial-call",
                        "payload": {
                            "purpose": "agentic_loop",
                            "model": pilot.MODEL,
                            "response_model": pilot.MODEL,
                            "error_type": "TimeoutError",
                            "usage": {"input_tokens": 7},
                        },
                    }
                ],
            )
        (directory / "sessions.db").write_bytes(b"synthetic partial database")
        if failure in {"interrupt", "cancel"}:
            raise original
        raise subprocess.TimeoutExpired(command, 210)

    monkeypatch.setattr(pilot.subprocess, "run", child)
    if failure in {"interrupt", "cancel"}:
        with pytest.raises(type(original)) as caught:
            pilot.execute(path, spec, cases)
        assert caught.value is original
    else:
        pilot.execute(path, spec, cases)
    assert dispatched == 1
    attempts = validate_attempts(tmp_path / "attempts.jsonl")
    assert len(attempts) == 1
    assert (attempts[0]["validity"], attempts[0]["outcome"]) == ("invalid", "unknown")
    assert attempts[0]["observed_result"] == (
        "Incomplete or invalid attempt; only available partial evidence retained."
    )
    refs = attempts[0]["evidence_refs"]
    assert any(ref["path"] == "results.json" for ref in refs)
    assert any(
        ref["path"].endswith("result.json" if failure == "exit" else "sessions.db") for ref in refs
    )
    validate_analysis(
        tmp_path / "analysis.json", run_spec_path=path, attempts_path=tmp_path / "attempts.jsonl"
    )
    summary = json.loads((tmp_path / "results.json").read_text())
    assert summary["value"] == "not-measurable"
    accounting = summary["arms"]["a"]["accounting"]
    assert accounting["known_input_output_sum"] == (
        17 if failure == "exit" else 0 if failure == "db-only" else 7
    )
    assert accounting["total_tokens"]["total"] is None
    assert accounting["retained_attempt_coverage_complete"] is False
    assert summary["arms"]["b"]["attempted_tasks"] == 0


def test_parent_interruption_after_first_arm_keeps_partial_pair(tmp_path, monkeypatch):
    path, spec, cases = _spec(tmp_path)
    dispatched = []
    interrupted = KeyboardInterrupt("private parent interruption")

    def child(command, **kwargs):
        arm = command[5]
        dispatched.append(arm)
        if arm == "a":
            _write_child(Path(command[7]), _result(cases[0], arm))
            return subprocess.CompletedProcess(command, 0)
        raise interrupted

    monkeypatch.setattr(pilot.subprocess, "run", child)
    with pytest.raises(KeyboardInterrupt) as caught:
        pilot.execute(path, spec, cases)
    assert caught.value is interrupted
    assert dispatched == ["a", "b"]
    attempts = validate_attempts(tmp_path / "attempts.jsonl")
    assert len(attempts) == 1 and attempts[0]["outcome"] == "unknown"
    assert any(ref["path"] == "private/00-a/result.json" for ref in attempts[0]["evidence_refs"])
    validate_analysis(
        tmp_path / "analysis.json", run_spec_path=path, attempts_path=tmp_path / "attempts.jsonl"
    )
    summary = json.loads((tmp_path / "results.json").read_text())
    assert summary["stop_reason"] == "parent_interrupted"
    assert summary["arms"]["a"]["accounting"]["total_tokens"]["total"] == 17
    assert summary["arms"]["b"]["accounting"]["total_tokens"]["total"] is None


def test_execute_revalidates_before_credentials_or_dispatch(tmp_path):
    path, spec, cases = _spec(tmp_path)
    spec["preregistration"]["live_test_approved"] = False
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="approved prospective freeze"):
        pilot.execute(path, spec, cases)
    assert not (tmp_path / "private").exists()


def test_malformed_child_accounting_cannot_become_measured_success(tmp_path, monkeypatch):
    path, spec, cases = _spec(tmp_path)

    def child(command, **kwargs):
        result = _result(cases[0], "a")
        result["call_accounting"] = ["not an accounting row"]
        _write_child(Path(command[7]), result)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pilot.subprocess, "run", child)
    pilot.execute(path, spec, cases)
    attempts = validate_attempts(tmp_path / "attempts.jsonl")
    assert len(attempts) == 1 and attempts[0]["validity"] == "invalid"
    summary = json.loads((tmp_path / "results.json").read_text())
    assert summary["value"] == "not-measurable"
    assert summary["stop_reason"] == "invalid_child_accounting"
