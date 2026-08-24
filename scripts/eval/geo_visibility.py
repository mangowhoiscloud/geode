#!/usr/bin/env python3
"""Validate one frozen GEO workload and emit its stage vector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from geode_product.geo_state import GeoEvidence
from scripts.eval.contract import (
    _load_json_object,
    _parse_datetime,
    _resolve_json_pointer,
    _strict_json_loads,
    _validate_evidence_refs,
    _validate_schema,
    validate_run_spec,
)

_ROOT_IDS = tuple(f"GEO-0{number}" for number in range(1, 7))
_WORKLOAD_IDS = tuple(
    f"{root}.{suffix}" for root in _ROOT_IDS for suffix in ("root", "p1", "p2", "p3")
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, base: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the run directory") from exc


def _is_target(url: str, prefixes: tuple[str, ...]) -> bool:
    candidate = urlsplit(url)
    candidate_path = candidate.path.rstrip("/")
    for raw_prefix in prefixes:
        prefix = urlsplit(raw_prefix)
        prefix_path = prefix.path.rstrip("/")
        if candidate.scheme != prefix.scheme or candidate.netloc != prefix.netloc:
            continue
        if candidate_path == prefix_path or candidate_path.startswith(prefix_path + "/"):
            return True
    return False


def _quote_in_source(quote: str, source: str) -> bool:
    normalized_quote = " ".join(quote.split()).casefold()
    normalized_source = " ".join(source.split()).casefold()
    return bool(normalized_quote) and normalized_quote in normalized_source


def _load_bound_receipt(
    results_path: Path,
    ref: dict[str, Any],
    *,
    kind: str,
) -> object:
    _validate_evidence_refs(
        results_path,
        [{"kind": kind, "path": ref["path"], "sha256": ref["sha256"]}],
    )
    path = results_path.parent / str(ref["path"])
    return _strict_json_loads(path.read_text(encoding="utf-8"), label=str(path))


def _assert_ranked_urls(rows: list[dict[str, Any]], *, label: str, rank_key: str = "rank") -> None:
    urls = [str(row["url"]) for row in rows]
    ranks = [int(row[rank_key]) for row in rows]
    if any(
        urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc for url in urls
    ):
        raise ValueError(f"{label} URLs must use http or https")
    if len(urls) != len(set(urls)) or len(ranks) != len(set(ranks)):
        raise ValueError(f"{label} URLs and ranks must be unique")


def _metric(
    stage: str,
    *,
    phase: str,
    numerator: int,
    denominator: int,
    expected_denominator: int,
    finding: str,
    evidence: str | list[str],
) -> dict[str, Any]:
    if denominator == 0:
        payload: dict[str, Any] = {
            "stage": stage,
            "phase": phase,
            "status": "not_measured",
            "numerator": None,
            "denominator": None,
            "finding": finding,
            "evidence": [],
        }
    else:
        payload = {
            "stage": stage,
            "phase": phase,
            "status": "measured" if denominator == expected_denominator else "partial",
            "numerator": numerator,
            "denominator": denominator,
            "finding": finding,
            "evidence": [evidence] if isinstance(evidence, str) else evidence,
        }
    GeoEvidence.from_dict(payload)
    return payload


def _not_measured(stage: str, *, phase: str, finding: str) -> dict[str, Any]:
    return _metric(
        stage,
        phase=phase,
        numerator=0,
        denominator=0,
        expected_denominator=0,
        finding=finding,
        evidence="",
    )


def _validate_host_preflight(host: dict[str, Any], *, label: str) -> int:
    schema_id = str(host.get("schema_id") or "")
    schemas = {
        "geode.geo-host-preflight@1": (1, "geo-host-preflight.schema.json"),
        "geode.geo-host-preflight@2": (2, "geo-host-preflight-v2.schema.json"),
    }
    selected = schemas.get(schema_id)
    if selected is None:
        raise ValueError(f"{label}: unsupported GEO host preflight schema")
    version, filename = selected
    _validate_schema(host, filename, label=label)
    if version == 1:
        return version

    pages = host["pages"]
    page_count = len(pages)
    page_urls = [str(row["url"]) for row in pages]
    if len(page_urls) != len(set(page_urls)):
        raise ValueError(f"{label}: GEO host preflight page URLs must be unique")
    page_urlset_sha256 = hashlib.sha256(
        json.dumps(page_urls, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if page_urlset_sha256 != host["urlset_sha256"]:
        raise ValueError(f"{label}: GEO host URL digest does not match its pages")
    user_agents = set(host["robots"]["user_agents"])
    for row in pages:
        checks = row["checks"]
        base_checks = {name: passed for name, passed in checks.items() if name != "eligible"}
        if checks["eligible"] != all(base_checks.values()):
            raise ValueError(f"{label}: GEO page eligibility is not its check conjunction")
        if set(row["robots_allowed"]) != user_agents:
            raise ValueError(f"{label}: GEO page crawler policy does not match the receipt")
        expected_failures = [
            name for name, passed in checks.items() if name != "eligible" and not passed
        ]
        if row["failures"] != expected_failures:
            raise ValueError(f"{label}: GEO page failure list does not match its checks")
    for name, ratio in host["checks"].items():
        if ratio["denominator"] != page_count or ratio["numerator"] != sum(
            int(row["checks"][name]) for row in pages
        ):
            raise ValueError(f"{label}: GEO host {name} aggregate does not match its pages")
    complete = host["checks"]["eligible"]["numerator"] == page_count and not any(
        host["sitemap_difference"].values()
    )
    if (host["status"] == "pass") != complete:
        raise ValueError(f"{label}: GEO host preflight status does not match eligibility")
    return version


def _validate_live_approval(
    *,
    workload_path: Path,
    workload: dict[str, Any],
    preregistration: dict[str, Any],
    repetitions: int,
    frozen_at: datetime,
) -> None:
    approval_ref = workload["live_approval_receipt"]
    approval = _load_bound_receipt(
        workload_path,
        approval_ref,
        kind="operator-live-approval",
    )
    if not isinstance(approval, dict):
        raise ValueError("GEO live approval receipt must be an object")
    _validate_schema(
        approval,
        "geo-live-approval.schema.json",
        label=str(workload_path.parent / str(approval_ref["path"])),
    )
    expected = {
        "run_id": workload["run_id"],
        "operator": preregistration["operator"],
        "engine": workload["engine"],
        "provider": workload["provider"],
        "credential_source": workload["credential_source"],
        "model": workload["model"],
        "locale": workload["locale"],
        "account_state": workload["account_state"],
        "repetitions": repetitions,
        "requested_result_limit": workload["requested_result_limit"],
    }
    if any(approval[field] != value for field, value in expected.items()):
        raise ValueError("GEO live approval does not match the frozen run surface")
    if _parse_datetime(approval["approved_at"]) > frozen_at:
        raise ValueError("GEO live approval must predate the workload freeze")


def _fetch_metric(results_path: Path, context: dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return _not_measured(
            "F",
            phase="preflight",
            finding="Digest-bound site and internal-link preflight receipts were not supplied.",
        )
    site = _load_bound_receipt(results_path, context["site"], kind="geo-site-preflight")
    links_receipt = _load_bound_receipt(results_path, context["links"], kind="geo-link-audit")
    if not isinstance(site, dict) or not isinstance(links_receipt, dict):
        raise ValueError("GEO preflight receipts must be objects")
    _validate_schema(site, "geo-preflight.schema.json", label="site preflight")
    _validate_schema(links_receipt, "geo-link-audit.schema.json", label="link audit")
    checks = site["checks"]
    if any(row["numerator"] != row["denominator"] for row in checks.values()):
        raise ValueError("GEO site preflight pass receipt contains an incomplete check")
    links = links_receipt["internal_links"]
    if links["numerator"] != links["denominator"] or links["broken"]:
        raise ValueError("GEO link-audit pass receipt contains a broken link")
    pages = int(checks["export"]["denominator"])
    host_ref = context["host"]
    host: dict[str, Any] | None = None
    host_passes = pages
    if host_ref is not None:
        loaded_host = _load_bound_receipt(results_path, host_ref, kind="geo-host-preflight")
        if not isinstance(loaded_host, dict):
            raise ValueError("GEO host preflight receipt must be an object")
        host = loaded_host
        host_version = _validate_host_preflight(host, label="host preflight")
        if host["urlset_sha256"] != site["urlset_sha256"]:
            raise ValueError("GEO local and public host URL sets do not match")
        if int(host["checks"]["http_2xx"]["denominator"]) != pages:
            raise ValueError("GEO local export and public host page counts do not match")
        host_passes = (
            int(host["checks"]["eligible"]["numerator"])
            if host_version == 2
            else min(int(row["numerator"]) for row in host["checks"].values())
        )
    metric = _metric(
        "F",
        phase="preflight",
        numerator=host_passes,
        denominator=pages,
        expected_denominator=pages,
        finding=(
            f"All {pages} exported pages passed sitemap, self-canonical, indexability, "
            f"and LLM-index checks; {links['denominator']} internal link occurrences passed; "
            + (
                (
                    "the public host receipt matched every URL and fetch gate."
                    if host["status"] == "pass"
                    else (
                        "the public host receipt failed with "
                        f"{len(host['sitemap_difference']['missing'])} missing and "
                        f"{len(host['sitemap_difference']['unexpected'])} unexpected sitemap URLs."
                    )
                )
                if host is not None
                else "public-host fetch eligibility was not supplied."
            )
        ),
        evidence=[
            str(ref["path"])
            for ref in (context["site"], context["links"], host_ref)
            if ref is not None
        ],
    )
    if host is None or host["status"] == "fail":
        metric["status"] = "partial"
        GeoEvidence.from_dict(metric)
    return metric


def _outcome_metric(
    outcome_path: Path | None,
    *,
    run_dir: Path,
    run_id: str,
    workload_sha256: str,
    phase: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, str] | None]:
    if outcome_path is None:
        return (
            _not_measured(
                "O",
                phase=phase,
                finding="First-party impressions, referrals, and conversions were not supplied.",
            ),
            None,
            None,
        )
    outcome_path = outcome_path.resolve()
    outcome = _load_json_object(outcome_path)
    _validate_schema(outcome, "geo-outcome.schema.json", label="GEO outcome")
    _validate_evidence_refs(
        outcome_path,
        [
            {
                "kind": "first-party-native-outcome",
                "path": outcome["source_receipt"]["path"],
                "sha256": outcome["source_receipt"]["sha256"],
            }
        ],
    )
    source_path = outcome_path.parent / str(outcome["source_receipt"]["path"])
    source_payload = _strict_json_loads(
        source_path.read_text(encoding="utf-8"), label=str(source_path)
    )
    if outcome["run_id"] != run_id or outcome["workload_sha256"] != workload_sha256:
        raise ValueError("GEO outcome receipt does not bind this run and workload")
    window = outcome["window"]
    if _parse_datetime(window["start"]) >= _parse_datetime(window["end"]):
        raise ValueError("GEO outcome window must have positive duration")
    if _parse_datetime(outcome["collected_at"]) < _parse_datetime(window["end"]):
        raise ValueError("GEO outcome receipt cannot be collected before its window ends")
    primary = outcome["primary_metric"]
    for field in ("numerator", "denominator"):
        observed = _resolve_json_pointer(
            source_payload,
            str(outcome["source_locator"][field]),
            label=str(source_path),
        )
        if observed != primary[field]:
            raise ValueError(f"GEO outcome {field} does not match its native source receipt")
    if int(primary["numerator"]) > int(primary["denominator"]):
        raise ValueError("GEO outcome numerator cannot exceed its denominator")
    context = {
        "path": _relative(outcome_path, run_dir, label="GEO outcome"),
        "sha256": _sha256(outcome_path),
    }
    return (
        _metric(
            "O",
            phase=phase,
            numerator=int(primary["numerator"]),
            denominator=int(primary["denominator"]),
            expected_denominator=int(primary["denominator"]),
            finding=f"First-party {primary['name']} ({primary['unit']}).",
            evidence=context["path"],
        ),
        outcome,
        context,
    )


def _load_verifier_overlay(
    results: dict[str, Any],
    *,
    native_results_path: Path,
    verifier_results_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], str | None]:
    if verifier_results_path is None:
        return None, {}, None
    verifier_results_path = verifier_results_path.resolve()
    overlay = _load_json_object(verifier_results_path)
    _validate_schema(
        overlay,
        "geo-verifier-results.schema.json",
        label=str(verifier_results_path),
    )
    if overlay["run_id"] != results["run_id"] or overlay["native_results_sha256"] != _sha256(
        native_results_path
    ):
        raise ValueError("GEO verifier overlay does not bind the native result")
    _validate_evidence_refs(
        verifier_results_path,
        [
            {
                "kind": "verifier-rubric",
                "path": overlay["verifier_context"]["rubric"]["path"],
                "sha256": overlay["verifier_context"]["rubric"]["sha256"],
            }
        ],
    )
    native_ids = {str(row["observation_id"]) for row in results["observations"]}
    by_id: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for verdict in overlay["observations"]:
        observation_id = str(verdict["observation_id"])
        if observation_id in seen or observation_id not in native_ids:
            raise ValueError("GEO verifier overlay contains duplicate or unknown observations")
        seen.add(observation_id)
        by_id[observation_id] = verdict
    return overlay["verifier_context"], by_id, _sha256(verifier_results_path)


def validate_and_measure(
    *,
    run_spec_path: Path,
    workload_path: Path,
    native_results_path: Path,
    verifier_results_path: Path | None = None,
    outcome_path: Path | None = None,
) -> dict[str, Any]:
    run_spec_path = run_spec_path.resolve()
    workload_path = workload_path.resolve()
    native_results_path = native_results_path.resolve()
    run_dir = run_spec_path.parent

    run_spec = validate_run_spec(run_spec_path)
    workload = _load_json_object(workload_path)
    results = _load_json_object(native_results_path)
    _validate_schema(workload, "geo-workload.schema.json", label=str(workload_path))
    _validate_schema(
        results,
        "geo-native-results.schema.json",
        label=str(native_results_path),
    )
    verifier_context, verifier_by_id, verifier_results_sha256 = _load_verifier_overlay(
        results,
        native_results_path=native_results_path,
        verifier_results_path=verifier_results_path,
    )

    run_id = str(run_spec["run_id"])
    if workload["run_id"] != run_id or results["run_id"] != run_id:
        raise ValueError("run spec, workload, and native results must share one run_id")

    workload_rel = _relative(workload_path, run_dir, label="GEO workload")
    results_rel = _relative(native_results_path, run_dir, label="GEO native results")
    workload_sha256 = _sha256(workload_path)
    expected_initial_ref = f"{workload_rel}#sha256={workload_sha256}"
    reproduction = run_spec["reproduction"]
    if reproduction["environment"]["initial_state_ref"] != expected_initial_ref:
        raise ValueError("run spec initial_state_ref does not bind the frozen GEO workload")
    if run_spec["artifacts"]["native_results"] != results_rel:
        raise ValueError("run spec native_results does not name the supplied GEO receipt")
    if results["workload_sha256"] != workload_sha256:
        raise ValueError("native results do not bind the frozen GEO workload")
    if results["run_spec_sha256"] != _sha256(run_spec_path):
        raise ValueError("native results do not bind the frozen GEO run spec")
    if workload["frozen_at"] != run_spec["preregistration"]["frozen_at"]:
        raise ValueError("GEO workload frozen_at must equal the run-spec freeze")
    if workload["model"] != reproduction["model"]["label"]:
        raise ValueError("GEO workload model does not match the run spec")
    route = str(reproduction["model"]["route"])
    credential_source = {"api": "payg", "subscription": "subscription"}.get(route)
    expected_producer = {
        "adapter": workload["engine"],
        "provider": workload["provider"],
        "credential_source": workload["credential_source"],
        "model": workload["model"],
    }
    if (
        credential_source is None
        or workload["provider"] != reproduction["model"]["provider"]
        or workload["credential_source"] != credential_source
        or results["producer"] != expected_producer
    ):
        raise ValueError("GEO native producer does not match the frozen run route")
    repetitions = int(reproduction["execution"]["repetitions"])
    if workload["repetitions"] != repetitions:
        raise ValueError("GEO workload repetitions do not match the run spec")
    preregistration = run_spec["preregistration"]
    if preregistration["mode"] != "prospective" or not preregistration["live_test_approved"]:
        raise ValueError("live GEO observation requires prospective operator approval")
    frozen_at = _parse_datetime(workload["frozen_at"])
    collected_at = _parse_datetime(results["collected_at"])
    if collected_at < frozen_at:
        raise ValueError("GEO native results cannot predate the frozen workload")
    _validate_live_approval(
        workload_path=workload_path,
        workload=workload,
        preregistration=preregistration,
        repetitions=repetitions,
        frozen_at=frozen_at,
    )

    preflight_context = results["preflight_context"]
    fetch_metric = _fetch_metric(native_results_path, preflight_context)
    evidence_phase = "live_observe"
    outcome_metric, outcome_payload, outcome_context = _outcome_metric(
        outcome_path,
        run_dir=run_dir,
        run_id=run_id,
        workload_sha256=workload_sha256,
        phase=evidence_phase,
    )

    items = workload["items"]
    item_ids = tuple(str(item["id"]) for item in items)
    if item_ids != _WORKLOAD_IDS:
        raise ValueError("GEO workload must keep the canonical 24-item order")
    if reproduction["execution"]["ordered_workload_ids"] != list(_WORKLOAD_IDS):
        raise ValueError("run spec ordered_workload_ids must match the GEO workload")
    queries = [str(item["query"]).strip() for item in items]
    if len(queries) != len(set(queries)):
        raise ValueError("GEO workload queries must be unique")
    for item in items:
        item_id = str(item["id"])
        root_id, suffix = item_id.split(".", 1)
        expected_kind = "root" if suffix == "root" else "paraphrase"
        if item["root_id"] != root_id or item["kind"] != expected_kind:
            raise ValueError(f"GEO workload item metadata does not match {item_id}")
    query_by_id = dict(zip(item_ids, queries, strict=True))

    prefixes = tuple(str(value) for value in workload["target_prefixes"])
    prefix_parts = tuple(urlsplit(value) for value in prefixes)
    if any(
        value.scheme not in {"http", "https"} or not value.netloc or value.query or value.fragment
        for value in prefix_parts
    ):
        raise ValueError("GEO target prefixes must be query-free http or https URLs")

    expected_cells = {
        (workload_id, repetition)
        for workload_id in _WORKLOAD_IDS
        for repetition in range(1, repetitions + 1)
    }
    seen_cells: set[tuple[str, int]] = set()
    observation_ids: set[str] = set()
    search_hits = retrieval_hits = retrieval_denominator = citation_hits = 0
    placement_hits = absorption_hits = absorption_denominator = 0
    quality_supported = quality_expected_total = quality_responses_audited = 0

    for observation in results["observations"]:
        observation_id = str(observation["observation_id"])
        cell = (str(observation["workload_id"]), int(observation["repetition"]))
        if observation_id in observation_ids or cell in seen_cells:
            raise ValueError("GEO observations must have unique IDs and workload cells")
        observation_ids.add(observation_id)
        seen_cells.add(cell)
        if observation["query"] != query_by_id.get(cell[0]):
            raise ValueError(f"{observation_id} query does not match the frozen workload")
        for field in ("engine", "model", "locale", "account_state"):
            if observation[field] != workload[field]:
                raise ValueError(f"{observation_id} {field} does not match the frozen workload")
        observed_at = _parse_datetime(observation["observed_at"])
        if not frozen_at <= observed_at <= collected_at:
            raise ValueError(f"{observation_id} observed_at is outside the frozen run window")

        retrieval = observation["retrieval"]
        citations = observation["citations"]
        if retrieval is not None:
            _assert_ranked_urls(retrieval, label=f"{observation_id} retrieval")
        _assert_ranked_urls(
            citations,
            label=f"{observation_id} citations",
            rank_key="visible_rank",
        )
        if not observation["search_activated"] and (retrieval or citations):
            raise ValueError("inactive search observations cannot contain retrieval or citations")

        native = _load_bound_receipt(
            native_results_path,
            observation["native_receipt"],
            kind="native-result",
        )
        for field in (
            "query",
            "engine",
            "model",
            "locale",
            "account_state",
            "observed_at",
            "search_activated",
            "retrieval",
            "citations",
        ):
            observed = _resolve_json_pointer(
                native,
                str(observation["native_source_locator"][field]),
                label=f"{native_results_path}:{observation_id}",
            )
            if observed != observation[field]:
                raise ValueError(f"{observation_id} {field} does not match its native receipt")

        verdict = verifier_by_id.get(observation_id)
        absorption = None if verdict is None else verdict["absorption"]
        quality = [] if verdict is None else verdict["quality"]
        quality_expected = None if verdict is None else verdict["quality_claims_expected"]
        verifier_ref = None if verdict is None else verdict["verifier_receipt"]
        if verdict is not None:
            if verifier_ref is None or verifier_context is None or verifier_results_path is None:
                raise ValueError("GEO absorption and quality require a verifier receipt")
            verifier = _load_bound_receipt(
                verifier_results_path,
                verifier_ref,
                kind="verifier-receipt",
            )
            if not isinstance(verifier, dict):
                raise ValueError("GEO verifier receipt must be an object")
            _validate_schema(
                verifier,
                "geo-verifier-receipt.schema.json",
                label=f"GEO verifier receipt {observation_id}",
            )
            if (
                verifier["observation_id"] != observation_id
                or verifier["producer"] != verifier_context["producer"]
                or verifier["model"] != verifier_context["model"]
                or verifier["rubric_sha256"] != verifier_context["rubric"]["sha256"]
            ):
                raise ValueError("GEO verifier receipt does not match its overlay context")
            if verifier_ref["sha256"] == observation["native_receipt"]["sha256"]:
                raise ValueError("GEO verifier receipt must remain separate from native outcome")
            for field, value in (
                ("absorption", absorption),
                ("quality", quality),
                ("quality_claims_expected", quality_expected),
            ):
                observed = _resolve_json_pointer(
                    verifier,
                    f"/{field}",
                    label=f"{native_results_path}:{observation_id}",
                )
                if observed != value:
                    raise ValueError(f"{observation_id} {field} does not match its verifier")
            source_content: dict[str, str] = {}
            for source_ref in verifier["sources"]:
                source_receipt = _load_bound_receipt(
                    verifier_results_path,
                    source_ref,
                    kind="verifier-source",
                )
                if not isinstance(source_receipt, dict):
                    raise ValueError("GEO verifier source receipt is malformed")
                _validate_schema(
                    source_receipt,
                    "geo-source-receipt.schema.json",
                    label=f"GEO verifier source receipt {observation_id}",
                )
                source_content[str(source_receipt["url"])] = str(source_receipt["content"])
            for claim in quality:
                source = source_content.get(str(claim["source_url"]))
                quote = str(claim["source_quote"])
                if source is None or (quote and not _quote_in_source(quote, source)):
                    raise ValueError("GEO verifier claim is not bound to its source receipt")
                if claim["supported"] and not quote:
                    raise ValueError("supported GEO claims require an exact source quote")

        target_retrieved = retrieval is not None and any(
            _is_target(str(row["url"]), prefixes) for row in retrieval
        )
        target_citations = [row for row in citations if _is_target(str(row["url"]), prefixes)]
        target_cited = bool(target_citations)
        if (absorption is not None or quality) and not target_cited:
            raise ValueError("target absorption and quality require a target citation")
        if quality_expected is not None and not target_cited:
            raise ValueError("target quality claim coverage requires a target citation")
        if quality_expected is None and quality:
            raise ValueError("GEO quality claims require a complete audited-claim count")
        if quality_expected is not None and len(quality) != quality_expected:
            raise ValueError("GEO quality claims must cover the verifier claim universe")
        claim_ids = [str(row["claim_id"]) for row in quality]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError(f"{observation_id} quality claim IDs must be unique")
        if any(not _is_target(str(row["source_url"]), prefixes) for row in quality):
            raise ValueError("GEO quality claims must reference a target URL")

        search_hits += int(observation["search_activated"])
        if retrieval is not None:
            retrieval_denominator += 1
            retrieval_hits += int(target_retrieved)
        citation_hits += int(target_cited)
        if target_cited:
            placement_hits += int(min(int(row["visible_rank"]) for row in target_citations) <= 3)
            if absorption is not None:
                absorption_denominator += 1
                absorption_hits += int(absorption)
            if quality_expected is not None:
                quality_responses_audited += 1
                quality_expected_total += quality_expected
                quality_supported += sum(int(row["supported"]) for row in quality)

    if seen_cells != expected_cells:
        missing = sorted(expected_cells - seen_cells)[:8]
        extra = sorted(seen_cells - expected_cells)[:8]
        raise ValueError(f"GEO observation matrix drift: missing={missing} extra={extra}")
    total = len(expected_cells)
    phase = "live_observe"
    evidence = f"{results_rel}#/observations"
    verifier_evidence = (
        ""
        if verifier_results_path is None
        else (
            f"{_relative(verifier_results_path, run_dir, label='GEO verifier results')}"
            "#/observations"
        )
    )
    vector = {
        "F": fetch_metric,
        "R": _metric(
            "R",
            phase=phase,
            numerator=retrieval_hits,
            denominator=retrieval_denominator,
            expected_denominator=total,
            finding="Target URL retrieved in observations whose engine exposed retrieval.",
            evidence=evidence,
        ),
        "C": _metric(
            "C",
            phase=phase,
            numerator=citation_hits,
            denominator=total,
            expected_denominator=total,
            finding="Target URL cited across every frozen repeated query.",
            evidence=evidence,
        ),
        "P": _metric(
            "P",
            phase=phase,
            numerator=placement_hits,
            denominator=citation_hits,
            expected_denominator=citation_hits,
            finding="Target citations visible in the first three citation positions.",
            evidence=evidence,
        ),
        "A": _metric(
            "A",
            phase=phase,
            numerator=absorption_hits,
            denominator=absorption_denominator,
            expected_denominator=citation_hits,
            finding="Verifier-marked target contribution among target-cited answers.",
            evidence=verifier_evidence,
        ),
        "Q": _metric(
            "Q",
            phase=phase,
            numerator=quality_supported,
            denominator=quality_expected_total,
            expected_denominator=-1,
            finding=(
                "Supported target-linked claims in separately bound verifier receipts; "
                "other Q dimensions remain unmeasured."
            ),
            evidence=verifier_evidence,
        ),
        "O": outcome_metric,
    }
    payload = {
        "schema_id": "geode.geo-vector@1",
        "schema_version": 1,
        "run_id": run_id,
        "run_spec_sha256": _sha256(run_spec_path),
        "workload_sha256": workload_sha256,
        "native_results_sha256": _sha256(native_results_path),
        "verifier_results_sha256": verifier_results_sha256,
        "native_producer": results["producer"],
        "verifier_context": verifier_context,
        "preflight_context": preflight_context,
        "outcome_context": outcome_context,
        "outcome_primary_metric": (
            None if outcome_payload is None else outcome_payload["primary_metric"]
        ),
        "observations": {"expected": total, "observed": len(seen_cells)},
        "search_activation": {
            "numerator": search_hits,
            "denominator": total,
        },
        "quality_claim_coverage": {
            "audited_claims": quality_expected_total,
            "audited_target_cited_responses": quality_responses_audited,
            "target_cited_responses": citation_hits,
        },
        "vector": vector,
    }
    _validate_schema(payload, "geo-vector.schema.json", label="GEO vector")
    return payload


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--native-results", type=Path, required=True)
    parser.add_argument("--verifier-results", type=Path)
    parser.add_argument("--outcome", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    payload = validate_and_measure(
        run_spec_path=args.run_spec,
        workload_path=args.workload,
        native_results_path=args.native_results,
        verifier_results_path=args.verifier_results,
        outcome_path=args.outcome,
    )
    if args.out is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _write_exclusive(args.out, payload)
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
