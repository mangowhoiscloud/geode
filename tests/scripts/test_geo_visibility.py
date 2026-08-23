from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from core.llm.adapters.base import WebSearchResult
from scripts.eval.geo_collect import collect
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
        "requested_result_limit": 10,
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
            "preflight_context": None,
            "verifier_context": {
                "producer": "example-independent-verifier",
                "version": "1",
                "rubric": {"path": "verifier-rubric.json", "sha256": _sha256(rubric_path)},
            },
            "outcome_context": None,
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


def test_geo_visibility_requires_public_host_for_complete_fetch(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    site_receipt = tmp_path / "site-preflight.json"
    link_receipt = tmp_path / "link-audit.json"
    host_receipt = tmp_path / "host-preflight.json"
    urlset_sha256 = "0" * 64
    _write_json(
        site_receipt,
        {
            "schema": "geode.geo-preflight.v2",
            "status": "pass",
            "checks": {
                name: {"numerator": count, "denominator": count}
                for name, count in {
                    "export": 78,
                    "sitemap": 78,
                    "self_canonical": 78,
                    "indexable": 78,
                    "llm_indexes": 2,
                }.items()
            },
            "noindex": {"count": 0, "audited_pages": 78},
            "urlset_sha256": urlset_sha256,
            "llm_indexes": ["llms.txt", "llms-full.txt"],
            "locators": ["out/sitemap.xml"],
            "unmeasured": ["retrieval"],
        },
    )
    _write_json(
        host_receipt,
        {
            "schema_id": "geode.geo-host-preflight@1",
            "schema_version": 1,
            "generated_at": "2026-08-23T00:02:00Z",
            "base_url": "https://mangowhoiscloud.github.io/geode/",
            "sitemap_url": "https://mangowhoiscloud.github.io/geode/sitemap.xml",
            "urlset_sha256": urlset_sha256,
            "robots": {
                "url": "https://mangowhoiscloud.github.io/robots.txt",
                "status": 404,
                "policy": "allow-by-absence",
            },
            "checks": {
                name: {"numerator": 78, "denominator": 78}
                for name in (
                    "sitemap_parity",
                    "http_2xx",
                    "html",
                    "self_canonical",
                    "indexable",
                    "robots_allowed",
                )
            },
        },
    )
    _write_json(
        link_receipt,
        {
            "schema": "geode.docs-link-audit.v1",
            "generated_at": "2026-08-23T00:01:00Z",
            "status": "pass",
            "internal_links": {"numerator": 577, "denominator": 577, "broken": 0},
            "external_links": {"audited": 0, "broken": 0},
            "unresolved": 4,
        },
    )
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["preflight_context"] = {
        "site": {"path": site_receipt.name, "sha256": _sha256(site_receipt)},
        "links": {"path": link_receipt.name, "sha256": _sha256(link_receipt)},
        "host": None,
    }
    _write_json(results, payload)

    local_only = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )
    assert local_only["vector"]["F"]["status"] == "partial"

    payload["preflight_context"]["host"] = {
        "path": host_receipt.name,
        "sha256": _sha256(host_receipt),
    }
    _write_json(results, payload)
    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )

    assert measured["vector"]["F"]["status"] == "measured"
    assert measured["vector"]["F"]["numerator"] == 78
    assert "577 internal link occurrences" in measured["vector"]["F"]["finding"]


def test_geo_visibility_binds_first_party_outcome_receipt(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    outcome = tmp_path / "outcome.json"
    _write_json(
        outcome,
        {
            "schema_id": "geode.geo-outcome@1",
            "schema_version": 1,
            "run_id": "geo-quality-test",
            "workload_sha256": _sha256(workload),
            "collected_at": "2026-08-24T00:00:01Z",
            "window": {"start": "2026-08-23T00:00:00Z", "end": "2026-08-24T00:00:00Z"},
            "source": {"system": "search-console", "property": "sc-domain:example.com"},
            "primary_metric": {
                "name": "clicks-per-impression",
                "numerator": 4,
                "denominator": 100,
                "unit": "clicks/impressions",
            },
        },
    )
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["outcome_context"] = {"path": outcome.name, "sha256": _sha256(outcome)}
    _write_json(results, payload)

    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )

    assert measured["vector"]["O"] | {"finding": ""} == {
        "stage": "O",
        "phase": "offline_measure",
        "status": "measured",
        "numerator": 4,
        "denominator": 100,
        "finding": "",
        "evidence": ["outcome.json"],
    }


def test_geo_visibility_applies_separate_verifier_overlay(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    native = json.loads(results.read_text(encoding="utf-8"))
    native["verifier_context"] = None
    for row in native["observations"]:
        row["absorption"] = None
        row["quality"] = []
        row["quality_claims_expected"] = None
        row["verifier_receipt"] = None
        row["verifier_source_locator"] = {
            "absorption": None,
            "quality": None,
            "quality_claims_expected": None,
        }
    _write_json(results, native)
    rubric = tmp_path / "rubric.json"
    _write_json(rubric, {"schema_id": "geode.geo-verifier-rubric@1"})
    receipt = tmp_path / "verdict.json"
    target = "https://mangowhoiscloud.github.io/geode/docs/"
    verdict = {
        "absorption": True,
        "quality": [{"claim_id": "claim-1", "source_url": target, "supported": True}],
        "quality_claims_expected": 1,
    }
    _write_json(receipt, verdict)
    overlay = tmp_path / "verifier-results.json"
    _write_json(
        overlay,
        {
            "schema_id": "geode.geo-verifier-results@1",
            "schema_version": 1,
            "run_id": "geo-quality-test",
            "native_results_sha256": _sha256(results),
            "verified_at": "2026-08-23T00:10:00Z",
            "verifier_context": {
                "producer": "test-verifier",
                "version": "v1",
                "rubric": {"path": rubric.name, "sha256": _sha256(rubric)},
            },
            "observations": [
                {
                    "observation_id": "obs-01",
                    **verdict,
                    "verifier_receipt": {
                        "path": receipt.name,
                        "sha256": _sha256(receipt),
                    },
                }
            ],
        },
    )

    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
        verifier_results_path=overlay,
    )

    assert measured["vector"]["A"]["numerator"] == 1
    assert measured["vector"]["A"]["denominator"] == 1
    assert measured["vector"]["A"]["status"] == "partial"
    assert measured["verifier_results_sha256"] == _sha256(overlay)


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
        "requested_result_limit": 10,
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
            "requested_result_limit": 10,
            "live_approval_receipt": {
                "path": "approval.json",
                "sha256": _sha256(approval_path),
            },
        },
        preregistration={"operator": "test-operator"},
        repetitions=5,
        frozen_at=datetime(2026, 8, 23, tzinfo=UTC),
    )


def test_geo_collector_preserves_retrieval_and_citations_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    results.unlink()
    workload_payload = json.loads(workload.read_text(encoding="utf-8"))
    workload_payload["engine"] = "codex-oauth"
    _write_json(workload, workload_payload)
    run_payload = json.loads(run_spec.read_text(encoding="utf-8"))
    run_payload["reproduction"]["model"]["provider"] = "openai"
    run_payload["reproduction"]["model"]["route"] = "subscription"
    run_payload["reproduction"]["environment"]["initial_state_ref"] = (
        f"workload.json#sha256={_sha256(workload)}"
    )
    _write_json(run_spec, run_payload)

    async def fake_search(query: str, **_: Any) -> WebSearchResult:
        return WebSearchResult(
            query=query,
            text="answer",
            source_urls=("https://example.com/retrieved",),
            citation_urls=("https://mangowhoiscloud.github.io/geode/docs/",),
            adapter_name="codex-oauth",
            adapter_provider="openai",
            adapter_source="subscription",
            search_activated=True,
            retrieval_exposed=True,
            model="example-model",
        )

    monkeypatch.setattr("scripts.eval.geo_collect.web_search_via_adapters", fake_search)
    payload = asyncio.run(
        collect(run_spec_path=run_spec, workload_path=workload, output_path=results)
    )

    assert len(payload["observations"]) == 24
    first = payload["observations"][0]
    assert first["retrieval"] == [{"url": "https://example.com/retrieved", "rank": 1}]
    assert first["citations"] == [
        {"url": "https://mangowhoiscloud.github.io/geode/docs/", "visible_rank": 1}
    ]
    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )
    assert measured["vector"]["R"]["numerator"] == 0
    assert measured["vector"]["C"]["numerator"] == 24
