#!/usr/bin/env python3
"""Collect one frozen GEO query matrix through GEODE's strict adapter route."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.llm.adapters.dispatch import web_search_via_adapters
from core.llm.adapters.registry import bootstrap_builtins
from scripts.eval.contract import (
    _load_json_object,
    _parse_datetime,
    _validate_schema,
    validate_run_spec,
)
from scripts.eval.geo_visibility import (
    _WORKLOAD_IDS,
    _relative,
    _sha256,
    _validate_live_approval,
    _write_exclusive,
)


def _source(route: str) -> str:
    if route == "api":
        return "payg"
    if route == "subscription":
        return route
    raise ValueError("GEO collector requires a concrete api or subscription route")


async def collect(
    *,
    run_spec_path: Path,
    workload_path: Path,
    output_path: Path,
    site_preflight_path: Path | None = None,
    link_audit_path: Path | None = None,
    host_preflight_path: Path | None = None,
) -> dict[str, Any]:
    run_spec_path = run_spec_path.resolve()
    workload_path = workload_path.resolve()
    output_path = output_path.resolve()
    run_dir = run_spec_path.parent
    if output_path.exists() or (output_path.parent / "native").exists():
        raise FileExistsError("GEO native output already exists")
    if (site_preflight_path is None) != (link_audit_path is None):
        raise ValueError("site preflight and link audit receipts must be supplied together")
    if host_preflight_path is not None and site_preflight_path is None:
        raise ValueError("host preflight requires site and link preflight receipts")

    def bound(path: Path, schema: str, label: str) -> dict[str, str]:
        path = path.resolve()
        payload = _load_json_object(path)
        _validate_schema(payload, schema, label=str(path))
        return {
            "path": _relative(path, output_path.parent, label=label),
            "sha256": _sha256(path),
        }

    preflight_context = (
        None
        if site_preflight_path is None or link_audit_path is None
        else {
            "site": bound(site_preflight_path, "geo-preflight.schema.json", "site preflight"),
            "links": bound(link_audit_path, "geo-link-audit.schema.json", "link audit"),
            "host": (
                None
                if host_preflight_path is None
                else bound(
                    host_preflight_path,
                    "geo-host-preflight.schema.json",
                    "host preflight",
                )
            ),
        }
    )
    run_spec = validate_run_spec(run_spec_path)
    workload = _load_json_object(workload_path)
    _validate_schema(workload, "geo-workload.schema.json", label=str(workload_path))
    if workload["run_id"] != run_spec["run_id"]:
        raise ValueError("run spec and GEO workload must share one run_id")
    workload_sha256 = _sha256(workload_path)
    workload_rel = _relative(workload_path, run_dir, label="GEO workload")
    reproduction = run_spec["reproduction"]
    if reproduction["environment"]["initial_state_ref"] != (
        f"{workload_rel}#sha256={workload_sha256}"
    ):
        raise ValueError("run spec initial_state_ref does not bind the frozen GEO workload")
    if run_spec["artifacts"]["native_results"] != _relative(
        output_path, run_dir, label="GEO native results"
    ):
        raise ValueError("run spec native_results does not name the collector output")
    if workload["model"] != reproduction["model"]["label"]:
        raise ValueError("GEO workload model does not match the run spec")
    repetitions = int(reproduction["execution"]["repetitions"])
    if workload["repetitions"] != repetitions:
        raise ValueError("GEO workload repetitions do not match the run spec")
    if reproduction["execution"]["ordered_workload_ids"] != list(_WORKLOAD_IDS):
        raise ValueError("run spec ordered_workload_ids must match the GEO workload")
    frozen_at = _parse_datetime(workload["frozen_at"])
    preregistration = run_spec["preregistration"]
    if preregistration["mode"] != "prospective" or not preregistration["live_test_approved"]:
        raise ValueError("live GEO collection requires prospective operator approval")
    _validate_live_approval(
        workload_path=workload_path,
        workload=workload,
        preregistration=preregistration,
        repetitions=repetitions,
        frozen_at=frozen_at,
    )

    provider = str(reproduction["model"]["provider"])
    source = _source(str(reproduction["model"]["route"]))
    if (workload["provider"], workload["credential_source"]) != (provider, source):
        raise ValueError("GEO workload route does not match the frozen run spec")
    timeout = float(reproduction["execution"]["timeout_seconds"])
    semaphore = asyncio.Semaphore(int(reproduction["execution"]["max_concurrency"]))
    items = {str(item["id"]): str(item["query"]) for item in workload["items"]}
    if tuple(items) != _WORKLOAD_IDS:
        raise ValueError("GEO workload must keep the canonical 24-item order")

    bootstrap_builtins()

    async def run_one(workload_id: str, repetition: int) -> tuple[dict[str, Any], dict[str, Any]]:
        query = items[workload_id]
        async with semaphore, asyncio.timeout(timeout):
            result = await web_search_via_adapters(
                query,
                max_results=int(workload["requested_result_limit"]),
                prefer_provider=provider,
                prefer_source=source,
                model=str(workload["model"]),
            )
        if result.query != query:
            raise ValueError("adapter result query drifted from the frozen workload")
        if result.adapter_name != workload["engine"]:
            raise ValueError("adapter result engine does not match the frozen workload")
        if result.model != workload["model"]:
            raise ValueError("adapter result model does not match the frozen workload")
        if (result.adapter_provider, result.adapter_source) != (provider, source):
            raise ValueError("adapter result route does not match the frozen run spec")

        observation_id = f"{workload_id}-r{repetition:03d}"
        observed_at = datetime.now(UTC).isoformat()
        retrieval = (
            [{"url": url, "rank": rank} for rank, url in enumerate(result.source_urls, 1)]
            if result.retrieval_exposed
            else None
        )
        citations = [
            {"url": url, "visible_rank": rank} for rank, url in enumerate(result.citation_urls, 1)
        ]
        receipt = {
            "schema": "geode.geo-adapter-receipt.v1",
            "observation_id": observation_id,
            "query": query,
            "engine": result.adapter_name,
            "model": result.model,
            "locale": workload["locale"],
            "account_state": workload["account_state"],
            "observed_at": observed_at,
            "search_activated": result.search_activated,
            "retrieval": retrieval,
            "citations": citations,
            "answer": result.text,
            "adapter": {
                "name": result.adapter_name,
                "provider": result.adapter_provider,
                "source": result.adapter_source,
            },
        }
        row = {
            "observation_id": observation_id,
            "workload_id": workload_id,
            "repetition": repetition,
            **{
                key: receipt[key]
                for key in (
                    "query",
                    "engine",
                    "model",
                    "locale",
                    "account_state",
                    "observed_at",
                    "search_activated",
                    "retrieval",
                    "citations",
                )
            },
            "native_source_locator": {
                key: f"/{key}"
                for key in (
                    "query",
                    "engine",
                    "model",
                    "locale",
                    "account_state",
                    "observed_at",
                    "search_activated",
                    "retrieval",
                    "citations",
                )
            },
        }
        return receipt, row

    cells = [
        (workload_id, repetition)
        for workload_id in _WORKLOAD_IDS
        for repetition in range(1, repetitions + 1)
    ]
    collected = await asyncio.gather(*(run_one(*cell) for cell in cells))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".geo-native-", dir=output_path.parent))
    try:
        rows: list[dict[str, Any]] = []
        for (receipt, row), (workload_id, repetition) in zip(collected, cells, strict=True):
            filename = f"{workload_id}-r{repetition:03d}.json"
            receipt_path = staging / filename
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            row["native_receipt"] = {
                "path": f"native/{filename}",
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            }
            rows.append(row)
        os.rename(staging, output_path.parent / "native")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    payload = {
        "schema_id": "geode.geo-native-results@1",
        "schema_version": 1,
        "run_id": workload["run_id"],
        "run_spec_sha256": _sha256(run_spec_path),
        "workload_sha256": workload_sha256,
        "collected_at": datetime.now(UTC).isoformat(),
        "producer": {
            "adapter": workload["engine"],
            "provider": provider,
            "credential_source": source,
            "model": workload["model"],
        },
        "preflight_context": preflight_context,
        "observations": rows,
    }
    try:
        _validate_schema(payload, "geo-native-results.schema.json", label=str(output_path))
        _write_exclusive(output_path, payload)
    except Exception:
        shutil.rmtree(output_path.parent / "native", ignore_errors=True)
        raise
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--site-preflight", type=Path)
    parser.add_argument("--link-audit", type=Path)
    parser.add_argument("--host-preflight", type=Path)
    args = parser.parse_args(argv)
    asyncio.run(
        collect(
            run_spec_path=args.run_spec,
            workload_path=args.workload,
            output_path=args.out,
            site_preflight_path=args.site_preflight,
            link_audit_path=args.link_audit,
            host_preflight_path=args.host_preflight,
        )
    )
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
