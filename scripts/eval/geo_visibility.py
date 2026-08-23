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
    evidence: str,
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
            "evidence": [evidence],
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


def _validate_live_approval(
    *,
    workload_path: Path,
    workload: dict[str, Any],
    preregistration: dict[str, Any],
    repetitions: int,
    frozen_at: datetime,
) -> None:
    approval_ref = workload["live_approval_receipt"]
    if workload["observation_mode"] != "live":
        if approval_ref is not None:
            raise ValueError("offline GEO workloads cannot carry a live approval receipt")
        return
    if approval_ref is None:
        raise ValueError("live GEO observation requires a digest-bound approval receipt")
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
        "model": workload["model"],
        "locale": workload["locale"],
        "account_state": workload["account_state"],
        "repetitions": repetitions,
    }
    if any(approval[field] != value for field, value in expected.items()):
        raise ValueError("GEO live approval does not match the frozen run surface")
    if _parse_datetime(approval["approved_at"]) > frozen_at:
        raise ValueError("GEO live approval must predate the workload freeze")


def validate_and_measure(
    *,
    run_spec_path: Path,
    workload_path: Path,
    native_results_path: Path,
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
    if workload["frozen_at"] != run_spec["preregistration"]["frozen_at"]:
        raise ValueError("GEO workload frozen_at must equal the run-spec freeze")
    if workload["model"] != reproduction["model"]["label"]:
        raise ValueError("GEO workload model does not match the run spec")
    repetitions = int(reproduction["execution"]["repetitions"])
    if workload["repetitions"] != repetitions:
        raise ValueError("GEO workload repetitions do not match the run spec")
    preregistration = run_spec["preregistration"]
    if workload["observation_mode"] == "live" and (
        preregistration["mode"] != "prospective" or not preregistration["live_test_approved"]
    ):
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

    verifier_context = results["verifier_context"]
    if verifier_context is not None:
        _validate_evidence_refs(
            native_results_path,
            [
                {
                    "kind": "verifier-rubric",
                    "path": verifier_context["rubric"]["path"],
                    "sha256": verifier_context["rubric"]["sha256"],
                }
            ],
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
    verifier_used = False

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

        absorption = observation["absorption"]
        quality = observation["quality"]
        quality_expected = observation["quality_claims_expected"]
        verifier_ref = observation["verifier_receipt"]
        verifier_locator = observation["verifier_source_locator"]
        if absorption is not None or quality or quality_expected is not None:
            if verifier_ref is None or verifier_context is None:
                raise ValueError("GEO absorption and quality require a verifier receipt")
            verifier_used = True
            verifier = _load_bound_receipt(
                native_results_path,
                verifier_ref,
                kind="verifier-receipt",
            )
            if verifier_ref["sha256"] == observation["native_receipt"]["sha256"]:
                raise ValueError("GEO verifier receipt must remain separate from native outcome")
            for field, value in (
                ("absorption", absorption),
                ("quality", quality),
                ("quality_claims_expected", quality_expected),
            ):
                locator = verifier_locator[field]
                unused = value is None or (
                    field == "quality" and value == [] and quality_expected is None
                )
                if unused:
                    if locator is not None:
                        raise ValueError(f"unused {field} verifier locator must be null")
                    continue
                if locator is None:
                    raise ValueError(f"{field} verifier locator is required")
                observed = _resolve_json_pointer(
                    verifier,
                    str(locator),
                    label=f"{native_results_path}:{observation_id}",
                )
                if observed != value:
                    raise ValueError(f"{observation_id} {field} does not match its verifier")
        elif verifier_ref is not None or any(
            value is not None for value in verifier_locator.values()
        ):
            raise ValueError("unused GEO verifier receipt and locators must be null")

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
    if verifier_used != (verifier_context is not None):
        raise ValueError("unused GEO verifier context must be null")

    total = len(expected_cells)
    phase = "live_observe" if workload["observation_mode"] == "live" else "offline_measure"
    evidence = f"{results_rel}#/observations"
    vector = {
        "F": _not_measured(
            "F",
            phase="preflight",
            finding="Fetch eligibility is owned by the separate site preflight receipt.",
        ),
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
            evidence=evidence,
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
            evidence=evidence,
        ),
        "O": _not_measured(
            "O",
            phase=phase,
            finding="First-party impressions, referrals, and conversions were not supplied.",
        ),
    }
    return {
        "schema_id": "geode.geo-vector@1",
        "schema_version": 1,
        "run_id": run_id,
        "run_spec_sha256": _sha256(run_spec_path),
        "workload_sha256": workload_sha256,
        "native_results_sha256": _sha256(native_results_path),
        "native_producer": {"engine": workload["engine"], "model": workload["model"]},
        "verifier_context": verifier_context,
        "observation_mode": workload["observation_mode"],
        "observations": {"expected": total, "observed": len(seen_cells)},
        "search_activation": {
            "numerator": search_hits,
            "denominator": total,
        },
        "quality_claim_coverage": {
            "audited_claims": quality_expected_total,
            "expected_claims": quality_expected_total,
            "audited_target_cited_responses": quality_responses_audited,
            "target_cited_responses": citation_hits,
        },
        "vector": vector,
    }


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
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    payload = validate_and_measure(
        run_spec_path=args.run_spec,
        workload_path=args.workload,
        native_results_path=args.native_results,
    )
    if args.out is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _write_exclusive(args.out, payload)
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
