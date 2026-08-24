from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from core.llm.adapters.base import AdapterCallResult, UsageSummary, WebSearchResult
from scripts.eval.geo_collect import collect
from scripts.eval.geo_verify import _validate_verdict, verify
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
    approval_path = tmp_path / "approval.json"
    _write_json(
        approval_path,
        {
            "schema_id": "geode.geo-live-approval@1",
            "schema_version": 1,
            "approval_id": "operator-approval-001",
            "run_id": "geo-quality-test",
            "operator": "test-operator",
            "approved_at": "2026-08-22T23:59:00Z",
            "engine": "example-search",
            "provider": "example",
            "credential_source": "subscription",
            "model": "example-model",
            "locale": "ko-KR",
            "account_state": "fresh-session-history-disabled",
            "repetitions": 5,
            "requested_result_limit": 10,
        },
    )
    workload_path = tmp_path / "workload.json"
    workload = {
        "schema_id": "geode.geo-workload@1",
        "schema_version": 1,
        "run_id": "geo-quality-test",
        "profile": "geo-visibility-v1",
        "frozen_at": frozen_at,
        "engine": "example-search",
        "provider": "example",
        "credential_source": "subscription",
        "model": "example-model",
        "locale": "ko-KR",
        "account_state": "fresh-session-history-disabled",
        "repetitions": 5,
        "requested_result_limit": 10,
        "live_approval_receipt": {
            "path": approval_path.name,
            "sha256": _sha256(approval_path),
        },
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
    rows: list[dict[str, Any]] = []
    target = "https://mangowhoiscloud.github.io/geode/docs/"
    other = "https://example.com/reference"
    for index, workload_id in enumerate(workload_ids):
        for repetition in range(1, 6):
            observation_id = f"obs-{index + 1:02d}-r{repetition}"
            query = workload["items"][index]["query"]
            retrieval = [{"url": target if index % 2 == 0 else other, "rank": 1}]
            target_cited = index < 8
            citations = (
                [{"url": target, "visible_rank": 1 if index < 4 else 4}] if target_cited else []
            )
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
            rows.append(
                {
                    "observation_id": observation_id,
                    "workload_id": workload_id,
                    "repetition": repetition,
                    **native_observations[observation_id],
                    "native_receipt": {"path": "native.json", "sha256": "pending"},
                    "native_source_locator": {
                        key: f"/observations/{observation_id}/{key}"
                        for key in native_observations[observation_id]
                    },
                }
            )

    native_path = tmp_path / "native.json"
    _write_json(native_path, {"observations": native_observations})
    for row in rows:
        row["native_receipt"]["sha256"] = _sha256(native_path)

    results_path = tmp_path / "native-results.json"
    _write_json(
        results_path,
        {
            "schema_id": "geode.geo-native-results@1",
            "schema_version": 1,
            "run_id": "geo-quality-test",
            "run_spec_sha256": "0" * 64,
            "workload_sha256": _sha256(workload_path),
            "collected_at": "2026-08-23T00:10:00Z",
            "producer": {
                "adapter": "example-search",
                "provider": "example",
                "credential_source": "subscription",
                "model": "example-model",
            },
            "preflight_context": None,
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
                    "denominator": 120,
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
                    "route": "subscription",
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
                    "repetitions": 5,
                    "seed_schedule": [0, 1, 2, 3, 4],
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
                "verifier_receipts": None,
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
    results_payload = json.loads(results_path.read_text(encoding="utf-8"))
    results_payload["run_spec_sha256"] = _sha256(run_spec_path)
    _write_json(results_path, results_payload)
    return run_spec_path, workload_path, results_path


def _verifier_overlay(tmp_path: Path, results: Path, *, expected_claims: int = 1) -> Path:
    rubric = tmp_path / "rubric.json"
    _write_json(rubric, {"schema_id": "geode.geo-verifier-rubric@1"})
    verdict = {
        "absorption": True,
        "quality": [
            {
                "claim_id": "claim-1",
                "claim_text": "GEODE has documentation.",
                "source_url": "https://mangowhoiscloud.github.io/geode/docs/",
                "source_quote": "GEODE documentation",
                "supported": True,
                "reason": "The source explicitly describes the documentation.",
            }
        ],
        "quality_claims_expected": expected_claims,
    }
    source = tmp_path / "source.json"
    _write_json(
        source,
        {
            "schema_id": "geode.geo-source-receipt@1",
            "fetched_at": "2026-08-23T00:09:00Z",
            "url": "https://mangowhoiscloud.github.io/geode/docs/",
            "source": "https://mangowhoiscloud.github.io/geode/docs/",
            "content": "GEODE documentation describes the runtime.",
            "truncated": False,
            "content_type": "text/html; charset=utf-8",
            "status_code": 200,
            "tls_verified": True,
        },
    )
    receipt = tmp_path / "verdict.json"
    _write_json(
        receipt,
        {
            "schema_id": "geode.geo-verifier-receipt@1",
            "observation_id": "obs-01-r1",
            "producer": "test-verifier",
            "model": "test-model",
            "verified_at": "2026-08-23T00:10:00Z",
            "rubric_sha256": _sha256(rubric),
            "sources": [{"path": source.name, "sha256": _sha256(source)}],
            **verdict,
            "rationale": "One target-linked claim was audited.",
        },
    )
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
                "model": "test-model",
                "rubric": {"path": rubric.name, "sha256": _sha256(rubric)},
            },
            "observations": [
                {
                    "observation_id": "obs-01-r1",
                    **verdict,
                    "verifier_receipt": {
                        "path": receipt.name,
                        "sha256": _sha256(receipt),
                    },
                }
            ],
        },
    )
    return overlay


def test_geo_visibility_emits_vector_without_aggregate_score(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)

    payload = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )

    assert payload["observations"] == {"expected": 120, "observed": 120}
    assert payload["search_activation"] == {"numerator": 120, "denominator": 120}
    assert payload["run_spec_sha256"] == _sha256(run_spec)
    assert payload["quality_claim_coverage"] == {
        "audited_claims": 0,
        "audited_target_cited_responses": 0,
        "target_cited_responses": 40,
    }
    assert "aggregate_score" not in payload
    assert {
        stage: (row["numerator"], row["denominator"], row["status"])
        for stage, row in payload["vector"].items()
    } == {
        "F": (None, None, "not_measured"),
        "R": (60, 120, "measured"),
        "C": (40, 120, "measured"),
        "P": (20, 40, "measured"),
        "A": (None, None, "not_measured"),
        "Q": (None, None, "not_measured"),
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
            "status": "pass",
            "generated_at": "2026-08-23T00:02:00Z",
            "base_url": "https://mangowhoiscloud.github.io/geode/",
            "sitemap_url": "https://mangowhoiscloud.github.io/geode/sitemap.xml",
            "urlset_sha256": urlset_sha256,
            "observed_urlset_sha256": urlset_sha256,
            "sitemap_difference": {"missing": [], "unexpected": [], "duplicates": []},
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

    failed_host = json.loads(host_receipt.read_text(encoding="utf-8"))
    failed_host["status"] = "fail"
    failed_host["sitemap_difference"]["missing"] = [
        "https://mangowhoiscloud.github.io/geode/docs/benchmarks/geo/"
    ]
    failed_host["checks"]["sitemap_parity"]["numerator"] = 77
    failed_host["checks"]["http_2xx"]["numerator"] = 77
    _write_json(host_receipt, failed_host)
    payload["preflight_context"]["host"]["sha256"] = _sha256(host_receipt)
    _write_json(results, payload)

    partial = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
    )
    assert partial["vector"]["F"]["status"] == "partial"
    assert partial["vector"]["F"]["numerator"] == 77
    assert "1 missing" in partial["vector"]["F"]["finding"]


def test_geo_visibility_binds_first_party_outcome_receipt(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    outcome = tmp_path / "outcome.json"
    source_receipt = tmp_path / "search-console-export.json"
    _write_json(source_receipt, {"clicks": 4, "impressions": 100})
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
            "source_receipt": {
                "path": source_receipt.name,
                "sha256": _sha256(source_receipt),
            },
            "source_locator": {"numerator": "/clicks", "denominator": "/impressions"},
            "primary_metric": {
                "name": "clicks-per-impression",
                "numerator": 4,
                "denominator": 100,
                "unit": "clicks/impressions",
            },
        },
    )
    native_sha256 = _sha256(results)

    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
        outcome_path=outcome,
    )

    assert _sha256(results) == native_sha256
    assert measured["outcome_context"] == {"path": outcome.name, "sha256": _sha256(outcome)}
    assert measured["vector"]["O"] | {"finding": ""} == {
        "stage": "O",
        "phase": "live_observe",
        "status": "measured",
        "numerator": 4,
        "denominator": 100,
        "finding": "",
        "evidence": ["outcome.json"],
    }

    drifted = json.loads(outcome.read_text(encoding="utf-8"))
    drifted["primary_metric"]["numerator"] = 5
    _write_json(outcome, drifted)
    with pytest.raises(ValueError, match="does not match its native source receipt"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
            outcome_path=outcome,
        )


def test_geo_visibility_applies_separate_verifier_overlay(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    overlay = _verifier_overlay(tmp_path, results)

    measured = validate_and_measure(
        run_spec_path=run_spec,
        workload_path=workload,
        native_results_path=results,
        verifier_results_path=overlay,
    )

    assert measured["vector"]["A"]["numerator"] == 1
    assert measured["vector"]["A"]["denominator"] == 1
    assert measured["vector"]["A"]["status"] == "partial"
    assert measured["vector"]["A"]["evidence"] == ["verifier-results.json#/observations"]
    assert measured["vector"]["Q"]["evidence"] == ["verifier-results.json#/observations"]
    assert measured["verifier_results_sha256"] == _sha256(overlay)


@pytest.mark.parametrize(
    ("source_quote", "message"),
    [
        ("", "require an exact source quote"),
        ("invented source text", "does not occur"),
    ],
)
def test_geo_verifier_rejects_unbound_support_evidence(source_quote: str, message: str) -> None:
    url = "https://example.com/source"
    verdict = {
        "absorption": True,
        "quality": [
            {
                "claim_id": "claim-1",
                "claim_text": "The source supports this claim.",
                "source_url": url,
                "source_quote": source_quote,
                "supported": True,
                "reason": "Source support was checked.",
            }
        ],
        "quality_claims_expected": 1,
        "rationale": "One target-linked claim was audited.",
    }

    with pytest.raises(ValueError, match=message):
        _validate_verdict(
            verdict,
            target_urls=(url,),
            fetched={url: {"content": "The exact source text."}},
        )


def _assert_geo_verifier_resumes_digest_checked_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, workload, native_results = _fixture(tmp_path)
    native = json.loads(native_results.read_text(encoding="utf-8"))
    for observation in native["observations"][2:]:
        observation["citations"] = []
    native_receipt = tmp_path / "native.json"
    receipt_payload = json.loads(native_receipt.read_text(encoding="utf-8"))
    receipt_payload["answer"] = "GEODE documentation describes the runtime."
    _write_json(native_receipt, receipt_payload)
    for observation in native["observations"]:
        observation["native_receipt"]["sha256"] = _sha256(native_receipt)
    _write_json(native_results, native)
    rubric = tmp_path / "rubric.json"
    _write_json(rubric, {"schema_id": "geode.geo-verifier-rubric@1"})
    output = tmp_path / "verifier-results.json"

    fetch_calls = 0

    async def fake_fetch(*_: Any, **__: Any) -> dict[str, Any]:
        nonlocal fetch_calls
        fetch_calls += 1
        return {
            "result": {
                "url": "https://mangowhoiscloud.github.io/geode/docs/",
                "source": "https://mangowhoiscloud.github.io/geode/docs/",
                "content": "GEODE documentation describes the runtime.",
                "truncated": False,
                "content_type": "text/html; charset=utf-8",
                "status_code": 200,
                "tls_verified": True,
            }
        }

    calls = 0

    class FakeAdapter:
        name = "test-verifier"

        async def acomplete(self, _: Any) -> AdapterCallResult:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("connection lost")
            return AdapterCallResult(
                text=json.dumps(
                    {
                        "absorption": True,
                        "quality": [
                            {
                                "claim_id": "claim-1",
                                "claim_text": "GEODE has documentation.",
                                "source_url": ("https://mangowhoiscloud.github.io/geode/docs/"),
                                "source_quote": (
                                    "invented source text" if calls == 1 else "GEODE documentation"
                                ),
                                "supported": True,
                                "reason": "The fetched source supports the claim.",
                            }
                        ],
                        "quality_claims_expected": 1,
                        "rationale": "One target-linked claim was audited.",
                    }
                ),
                usage=UsageSummary(),
                stop_reason="end_turn",
            )

    monkeypatch.setattr("scripts.eval.geo_verify.WebFetchTool.aexecute", fake_fetch)
    monkeypatch.setattr("scripts.eval.geo_verify.bootstrap_builtins", lambda: None)
    monkeypatch.setattr("scripts.eval.geo_verify.get_adapter", lambda _: FakeAdapter())

    with pytest.raises(RuntimeError, match="connection lost"):
        asyncio.run(
            verify(
                workload_path=workload,
                native_results_path=native_results,
                rubric_path=rubric,
                output_path=output,
                model="test-model",
                adapter_name="test-verifier",
                producer_version="test-v1",
                concurrency=1,
            )
        )
    evidence_dir = tmp_path / "verifier-results-evidence"
    assert len(list(evidence_dir.glob("source-*.json"))) == 1
    assert len(list(evidence_dir.glob("verdict-*.json"))) == 1
    assert not output.exists()

    calls = 0
    payload = asyncio.run(
        verify(
            workload_path=workload,
            native_results_path=native_results,
            rubric_path=rubric,
            output_path=output,
            model="test-model",
            adapter_name="test-verifier",
            producer_version="test-v1",
            concurrency=1,
        )
    )
    assert calls == 2
    assert fetch_calls == 1
    assert len(payload["observations"]) == 2


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


def test_geo_visibility_rejects_live_work_without_operator_approval(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    run_payload = json.loads(run_spec.read_text(encoding="utf-8"))
    run_payload["preregistration"]["live_test_approved"] = False
    _write_json(run_spec, run_payload)
    results_payload = json.loads(results.read_text(encoding="utf-8"))
    results_payload["run_spec_sha256"] = _sha256(run_spec)
    _write_json(results, results_payload)

    with pytest.raises(ValueError, match="prospective operator approval"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_retired_offline_mode(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    payload = json.loads(workload.read_text(encoding="utf-8"))
    payload["observation_mode"] = "offline"
    _write_json(workload, payload)

    with pytest.raises(ValueError, match=r"observation_mode.*unexpected"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_native_route_drift(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    payload = json.loads(results.read_text(encoding="utf-8"))
    payload["producer"]["credential_source"] = "payg"
    _write_json(results, payload)

    with pytest.raises(ValueError, match="native producer does not match"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
        )


def test_geo_visibility_rejects_receipt_bound_query_drift(tmp_path: Path) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    native_path = tmp_path / "native.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    native["observations"]["obs-01-r1"]["query"] = "Different executed query"
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
    overlay = _verifier_overlay(tmp_path, results, expected_claims=2)

    with pytest.raises(ValueError, match="cover the verifier claim universe"):
        validate_and_measure(
            run_spec_path=run_spec,
            workload_path=workload,
            native_results_path=results,
            verifier_results_path=overlay,
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
        "provider": "example",
        "credential_source": "subscription",
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
            "engine": "example-search",
            "provider": "example",
            "credential_source": "subscription",
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
    workload_payload["provider"] = "openai"
    approval = tmp_path / str(workload_payload["live_approval_receipt"]["path"])
    approval_payload = json.loads(approval.read_text(encoding="utf-8"))
    approval_payload["engine"] = "codex-oauth"
    approval_payload["provider"] = "openai"
    _write_json(approval, approval_payload)
    workload_payload["live_approval_receipt"]["sha256"] = _sha256(approval)
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

    assert len(payload["observations"]) == 120
    first = payload["observations"][0]
    assert "verifier_context" not in payload
    assert "outcome_context" not in payload
    assert (
        not {
            "absorption",
            "quality",
            "quality_claims_expected",
            "verifier_receipt",
            "verifier_source_locator",
        }
        & first.keys()
    )
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
    assert measured["vector"]["C"]["numerator"] == 120


def test_geo_collector_resumes_digest_checked_cell_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_spec, workload, results = _fixture(tmp_path)
    results.unlink()
    workload_payload = json.loads(workload.read_text(encoding="utf-8"))
    workload_payload["engine"] = "codex-oauth"
    workload_payload["provider"] = "openai"
    approval = tmp_path / str(workload_payload["live_approval_receipt"]["path"])
    approval_payload = json.loads(approval.read_text(encoding="utf-8"))
    approval_payload["engine"] = "codex-oauth"
    approval_payload["provider"] = "openai"
    _write_json(approval, approval_payload)
    workload_payload["live_approval_receipt"]["sha256"] = _sha256(approval)
    _write_json(workload, workload_payload)
    run_payload = json.loads(run_spec.read_text(encoding="utf-8"))
    run_payload["reproduction"]["model"]["provider"] = "openai"
    run_payload["reproduction"]["model"]["route"] = "subscription"
    run_payload["reproduction"]["environment"]["initial_state_ref"] = (
        f"workload.json#sha256={_sha256(workload)}"
    )
    run_payload["reproduction"]["execution"]["max_concurrency"] = 1
    _write_json(run_spec, run_payload)

    calls = 0

    async def flaky_search(query: str, **_: Any) -> WebSearchResult:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("connection lost")
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

    monkeypatch.setattr("scripts.eval.geo_collect.web_search_via_adapters", flaky_search)
    with pytest.raises(RuntimeError, match="connection lost"):
        asyncio.run(collect(run_spec_path=run_spec, workload_path=workload, output_path=results))
    assert len(list((tmp_path / "native").glob("*.json"))) == 119
    assert not results.exists()

    calls = 0
    payload = asyncio.run(
        collect(run_spec_path=run_spec, workload_path=workload, output_path=results)
    )
    assert calls == 1
    assert len(payload["observations"]) == 120
    verifier_path = tmp_path / "verifier-resume"
    verifier_path.mkdir()
    _assert_geo_verifier_resumes_digest_checked_receipts(verifier_path, monkeypatch)
