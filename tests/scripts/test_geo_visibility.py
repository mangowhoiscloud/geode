from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.eval.geo_visibility import _validate_live_approval, validate_and_measure


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    workload_ids = [
        f"GEO-0{root}.{suffix}" for root in range(1, 7) for suffix in ("root", "p1", "p2", "p3")
    ]
    frozen_at = "2026-08-23T00:00:00Z"
    workload_path = tmp_path / "workload.json"
    workload = {
        "schema_id": "geode.geo-workload@1",
        "schema_version": 1,
        "run_id": "geo-quality-test",
        "profile": "geo-visibility-v1",
        "observation_mode": "offline",
        "frozen_at": frozen_at,
        "engine": "example-search",
        "model": "example-model",
        "locale": "ko-KR",
        "account_state": "fresh-session-history-disabled",
        "repetitions": 1,
        "live_approval_receipt": None,
        "target_prefixes": ["https://mangowhoiscloud.github.io/geode"],
        "items": [
            {
                "id": workload_id,
                "root_id": workload_id.split(".", 1)[0],
                "kind": "root" if workload_id.endswith(".root") else "paraphrase",
                "query": f"Frozen query {index}",
            }
            for index, workload_id in enumerate(workload_ids, start=1)
        ],
    }
    _write_json(workload_path, workload)

    native_observations: dict[str, Any] = {}
    verifier_observations: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    target = "https://mangowhoiscloud.github.io/geode/docs/"
    other = "https://example.com/reference"
    for index, workload_id in enumerate(workload_ids):
        observation_id = f"obs-{index + 1:02d}"
        query = workload["items"][index]["query"]
        retrieval = [{"url": target if index % 2 == 0 else other, "rank": 1}]
        target_cited = index < 8
        citations = [{"url": target, "visible_rank": 1 if index < 4 else 4}] if target_cited else []
        absorption = index < 6 if target_cited else None
        quality = (
            [
                {
                    "claim_id": f"claim-{index + 1}",
                    "source_url": target,
                    "supported": index < 7,
                }
            ]
            if target_cited
            else []
        )
        quality_claims_expected = 1 if target_cited else None
        native_observations[observation_id] = {
            "query": query,
            "engine": "example-search",
            "model": "example-model",
            "locale": "ko-KR",
            "account_state": "fresh-session-history-disabled",
            "observed_at": "2026-08-23T00:05:00Z",
            "search_activated": True,
            "retrieval": retrieval,
            "citations": citations,
        }
        if target_cited:
            verifier_observations[observation_id] = {
                "absorption": absorption,
                "quality": quality,
                "quality_claims_expected": quality_claims_expected,
            }
        rows.append(
            {
                "observation_id": observation_id,
                "workload_id": workload_id,
                "repetition": 1,
                "query": query,
                "engine": "example-search",
                "model": "example-model",
                "locale": "ko-KR",
                "account_state": "fresh-session-history-disabled",
                "observed_at": "2026-08-23T00:05:00Z",
                "search_activated": True,
                "retrieval": retrieval,
                "citations": citations,
                "absorption": absorption,
                "quality": quality,
                "quality_claims_expected": quality_claims_expected,
                "native_receipt": {"path": "native.json", "sha256": "pending"},
                "native_source_locator": {
                    "query": f"/observations/{observation_id}/query",
                    "engine": f"/observations/{observation_id}/engine",
                    "model": f"/observations/{observation_id}/model",
                    "locale": f"/observations/{observation_id}/locale",
                    "account_state": f"/observations/{observation_id}/account_state",
                    "observed_at": f"/observations/{observation_id}/observed_at",
                    "search_activated": f"/observations/{observation_id}/search_activated",
                    "retrieval": f"/observations/{observation_id}/retrieval",
                    "citations": f"/observations/{observation_id}/citations",
                },
                "verifier_receipt": (
                    {"path": "verifier.json", "sha256": "pending"} if target_cited else None
                ),
                "verifier_source_locator": {
                    "absorption": (
                        f"/observations/{observation_id}/absorption" if target_cited else None
                    ),
                    "quality": (
                        f"/observations/{observation_id}/quality" if target_cited else None
                    ),
                    "quality_claims_expected": (
                        f"/observations/{observation_id}/quality_claims_expected"
                        if target_cited
                        else None
                    ),
                },
            }
        )

    native_path = tmp_path / "native.json"
    verifier_path = tmp_path / "verifier.json"
    rubric_path = tmp_path / "verifier-rubric.json"
    _write_json(native_path, {"observations": native_observations})
    _write_json(verifier_path, {"observations": verifier_observations})
    _write_json(
        rubric_path,
        {
            "schema_id": "geode.geo-verifier-rubric@1",
            "absorption": "Whether the cited target contributes to the answer.",
            "quality": "Audit every target-linked claim for source support.",
        },
    )
    for row in rows:
        row["native_receipt"]["sha256"] = _sha256(native_path)
        if row["verifier_receipt"] is not None:
            row["verifier_receipt"]["sha256"] = _sha256(verifier_path)

    results_path = tmp_path / "native-results.json"
    _write_json(
        results_path,
        {
            "schema_id": "geode.geo-native-results@1",
            "schema_version": 1,
            "run_id": "geo-quality-test",
            "workload_sha256": _sha256(workload_path),
            "collected_at": "2026-08-23T00:10:00Z",
            "verifier_context": {
                "producer": "example-independent-verifier",
                "version": "1",
                "rubric": {"path": "verifier-rubric.json", "sha256": _sha256(rubric_path)},
            },
            "observations": rows,
        },
    )
    run_spec_path = tmp_path / "run-spec.json"
    _write_json(
        run_spec_path,
        {
            "schema_id": "geode.eval-run-spec@1",
            "schema_version": 1,
            "run_id": "geo-quality-test",
            "created_at": frozen_at,
            "preregistration": {
                "mode": "prospective",
                "status": "frozen",
                "frozen_at": frozen_at,
                "live_test_approved": True,
                "operator": "test-operator",
            },
            "study": {
                "research_question": "Does the frozen GEO workload cite the target pages?",
                "research_gap": "No repeated observation receipt exists for this surface.",
                "hypothesis": "Target citation selection will be observable per query.",
                "primary_metric": {
                    "name": "citation_selection",
                    "unit": "ratio",
                    "direction": "maximize",
                    "aggregation": "target-cited observations / all repeated prompts",
                    "denominator": 24,
                },
                "decision_rule": "Remain diagnostic; this run has no promotion authority.",
                "invalidation_rule": "Invalidate missing, duplicate, or unbound observations.",
                "analysis_plan": "Report every GEO stage separately with its own denominator.",
            },
            "reproduction": {
                "geode": {"revision": "a" * 40, "branch": "test", "dirty": False},
                "harness": {
                    "name": "geo-visibility",
                    "source": "GEODE source checkout",
                    "revision": "v1",
                },
                "model": {
                    "provider": "example",
                    "label": "example-model",
                    "route": "other",
                    "reasoning": "none",
                },
                "environment": {
                    "platform": "test",
                    "architecture": "test",
                    "reset_strategy": "fresh session for every frozen query",
                    "initial_state_ref": f"workload.json#sha256={_sha256(workload_path)}",
                },
                "execution": {
                    "command_redacted": "python scripts/eval/geo_visibility.py ...",
                    "ordered_workload_ids": workload_ids,
                    "workload_ids_sha256": hashlib.sha256(
                        json.dumps(workload_ids, separators=(",", ":")).encode()
                    ).hexdigest(),
                    "repetitions": 1,
                    "seed_schedule": [0],
                    "max_concurrency": 1,
                    "timeout_seconds": 60,
                    "budget": {"kind": "wall-time", "limit": 60, "unit": "seconds"},
                },
                "comparison": {
                    "claim_class": "diagnostic",
                    "comparator": None,
                    "comparability": "not-comparable",
                    "promotion_authority": "none",
                },
            },
            "artifacts": {
                "native_results": "native-results.json",
                "trajectory": None,
                "verifier_receipts": "verifier.json",
                "attempts": "attempts.jsonl",
                "analysis": "analysis.json",
                "publication_manifest": None,
            },
            "privacy": {
                "classification": "internal",
                "redaction_boundary": "Raw answers and verifier bodies remain inside the run directory.",
            },
        },
    )
    return run_spec_path, workload_path, results_path


def test_geo_visibility_emits_vector_without_aggregate_score(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)

    payload = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )

    assert payload["observations"] == {"expected": 24, "observed": 24}
    assert payload["search_activation"] == {"numerator": 24, "denominator": 24}
    assert payload["run_spec_sha256"] == _sha256(run_spec)
    assert payload["quality_claim_coverage"] == {
        "audited_claims": 8,
        "expected_claims": 8,
        "audited_target_cited_responses": 8,
        "target_cited_responses": 8,
    }
    assert "aggregate_score" not in payload
    assert {
        stage: (row["numerator"], row["denominator"], row["status"])
        for stage, row in payload["vector"].items()
    } == {
        "F": (None, None, "not_measured"),
        "R": (12, 24, "measured"),
        "C": (8, 24, "measured"),
        "P": (4, 8, "measured"),
        "A": (6, 8, "measured"),
        "Q": (7, 8, "partial"),
        "O": (None, None, "not_measured"),
    }


def test_geo_visibility_rejects_observation_matrix_drift(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["observations"].pop()
    _write_json(results, payload)

    with pytest.raises(ValueError, match="observation matrix drift"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_unbound_native_projection(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["observations"][0]["citations"] = []
    _write_json(results, payload)

    with pytest.raises(ValueError, match="citations does not match its native receipt"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


@pytest.mark.parametrize(
    ("approved", "message"),
    [
        (False, "prospective operator approval"),
        (True, "digest-bound approval receipt"),
    ],
)
def test_geo_visibility_rejects_live_work_without_operator_approval(
    tmp_path: Path,
    approved: bool,
    message: str,
) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    workload_payload = json.loads(workload.read_text(encoding="utf-8"))
    workload_payload["observation_mode"] = "live"
    workload_payload["repetitions"] = 5
    _write_json(workload, workload_payload)
    results_payload = json.loads(results.read_text(encoding="utf-8"))
    results_payload["workload_sha256"] = _sha256(workload)
    _write_json(results, results_payload)
    run_payload = json.loads(run_spec.read_text(encoding="utf-8"))
    run_payload["preregistration"]["live_test_approved"] = approved
    run_payload["reproduction"]["environment"]["initial_state_ref"] = (
        f"workload.json#sha256={_sha256(workload)}"
    )
    run_payload["reproduction"]["execution"]["repetitions"] = 5
    run_payload["reproduction"]["execution"]["seed_schedule"] = [0, 1, 2, 3, 4]
    _write_json(run_spec, run_payload)

    with pytest.raises(ValueError, match=message):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_receipt_bound_query_drift(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    native_path = tmp_path / "native.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    native["observations"]["obs-01"]["query"] = "Different executed query"
    _write_json(native_path, native)

    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["observations"][0]["query"] = "Different executed query"
    for observation in payload["observations"]:
        observation["native_receipt"]["sha256"] = _sha256(native_path)
    _write_json(results, payload)

    with pytest.raises(ValueError, match="query does not match the frozen workload"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_incomplete_quality_claim_universe(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    verifier_path = tmp_path / "verifier.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["observations"]["obs-01"]["quality"] = []
    _write_json(verifier_path, verifier)

    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["observations"][0]["quality"] = []
    for observation in payload["observations"]:
        if observation["verifier_receipt"] is not None:
            observation["verifier_receipt"]["sha256"] = _sha256(verifier_path)
    _write_json(results, payload)

    with pytest.raises(ValueError, match="cover the verifier claim universe"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_accepts_matching_digest_bound_live_approval(tmp_path: Path) -> None:
    approval_path = tmp_path / "approval.json"
    approval = {
        "schema_id": "geode.geo-live-approval@1",
        "schema_version": 1,
        "approval_id": "operator-approval-001",
        "run_id": "geo-live-test",
        "operator": "test-operator",
        "approved_at": "2026-08-22T23:59:00Z",
        "engine": "example-search",
        "model": "example-model",
        "locale": "ko-KR",
        "account_state": "fresh-session-history-disabled",
        "repetitions": 5,
    }
    _write_json(approval_path, approval)

    _validate_live_approval(
        workload_path=tmp_path / "workload.json",
        workload={
            "run_id": "geo-live-test",
            "observation_mode": "live",
            "engine": "example-search",
            "model": "example-model",
            "locale": "ko-KR",
            "account_state": "fresh-session-history-disabled",
            "live_approval_receipt": {
                "path": "approval.json",
                "sha256": _sha256(approval_path),
            },
        },
        preregistration={"operator": "test-operator"},
        repetitions=5,
        frozen_at=datetime(2026, 8, 23, tzinfo=UTC),
    )
