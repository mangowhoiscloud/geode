#!/usr/bin/env python3
"""Produce source-aware A/Q verifier receipts for target-cited GEO observations."""

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

from core.llm.adapters.base import AdapterCallRequest, Message
from core.llm.adapters.registry import bootstrap_builtins, get_adapter
from core.tools.web_tools import WebFetchTool
from scripts.eval.contract import _load_json_object, _validate_schema
from scripts.eval.geo_visibility import _is_target, _relative, _sha256, _write_exclusive

_VERDICT_SCHEMA: dict[str, Any] = {
    "title": "geo_source_aware_verdict",
    "type": "object",
    "properties": {
        "absorption": {"type": "boolean"},
        "quality": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "source_url": {"type": "string"},
                    "supported": {"type": "boolean"},
                },
                "required": ["claim_id", "source_url", "supported"],
                "additionalProperties": False,
            },
        },
        "quality_claims_expected": {"type": "integer", "minimum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["absorption", "quality", "quality_claims_expected", "rationale"],
    "additionalProperties": False,
}


async def verify(
    *,
    workload_path: Path,
    native_results_path: Path,
    rubric_path: Path,
    output_path: Path,
    model: str,
    producer_version: str,
    concurrency: int,
) -> dict[str, Any]:
    workload_path = workload_path.resolve()
    native_results_path = native_results_path.resolve()
    rubric_path = rubric_path.resolve()
    output_path = output_path.resolve()
    evidence_dir = output_path.parent / f"{output_path.stem}-evidence"
    if output_path.exists() or evidence_dir.exists():
        raise FileExistsError("GEO verifier output already exists")

    workload = _load_json_object(workload_path)
    native = _load_json_object(native_results_path)
    rubric = _load_json_object(rubric_path)
    _validate_schema(workload, "geo-workload.schema.json", label=str(workload_path))
    _validate_schema(native, "geo-native-results.schema.json", label=str(native_results_path))
    if native["run_id"] != workload["run_id"] or native["workload_sha256"] != _sha256(
        workload_path
    ):
        raise ValueError("GEO verifier inputs do not share one frozen run")
    if rubric.get("schema_id") != "geode.geo-verifier-rubric@1":
        raise ValueError("unsupported GEO verifier rubric")

    prefixes = tuple(str(value) for value in workload["target_prefixes"])
    selected = []
    for observation in native["observations"]:
        target_urls = tuple(
            dict.fromkeys(
                str(row["url"])
                for row in observation["citations"]
                if _is_target(str(row["url"]), prefixes)
            )
        )
        if target_urls:
            selected.append((observation, target_urls))
    if not selected:
        raise ValueError("GEO verifier has no target-cited observations")

    fetcher = WebFetchTool()
    unique_urls = tuple(dict.fromkeys(url for _, urls in selected for url in urls))

    async def fetch(url: str) -> tuple[str, dict[str, Any]]:
        result = await fetcher.aexecute(url=url, max_chars=10_000)
        payload = result.get("result")
        if not isinstance(payload, dict) or payload.get("status_code") != 200:
            raise ValueError(f"GEO verifier source fetch failed: {url}")
        return url, payload

    fetched = dict(await asyncio.gather(*(fetch(url) for url in unique_urls)))
    bootstrap_builtins()
    adapter = get_adapter("codex-oauth")
    semaphore = asyncio.Semaphore(concurrency)

    async def judge(observation: dict[str, Any], target_urls: tuple[str, ...]) -> dict[str, Any]:
        sources = [{"url": url, "content": str(fetched[url]["content"])} for url in target_urls]
        prompt = json.dumps(
            {
                "rubric": rubric,
                "answer": _load_json_object(
                    native_results_path.parent / observation["native_receipt"]["path"]
                )["answer"],
                "target_sources": sources,
            },
            ensure_ascii=False,
        )
        async with semaphore:
            response = await adapter.acomplete(
                AdapterCallRequest(
                    model=model,
                    messages=(Message(role="user", content=prompt),),
                    system_prompt=(
                        "Mode: GEO source-aware verifier. Apply the supplied rubric only. "
                        "Enumerate every target-linked claim; do not reward citation "
                        "presence alone."
                    ),
                    response_schema=_VERDICT_SCHEMA,
                    max_tokens=2048,
                )
            )
        verdict = json.loads(response.text)
        if not isinstance(verdict, dict):
            raise ValueError("GEO verifier response must be an object")
        quality = verdict["quality"]
        if verdict["quality_claims_expected"] != len(quality):
            raise ValueError("GEO verifier did not cover its declared claim universe")
        if len({str(row["claim_id"]) for row in quality}) != len(quality):
            raise ValueError("GEO verifier claim IDs must be unique")
        if any(str(row["source_url"]) not in target_urls for row in quality):
            raise ValueError("GEO verifier referenced a source outside the native target citations")
        return verdict

    verdicts = await asyncio.gather(*(judge(*item) for item in selected))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".geo-verifier-", dir=output_path.parent))
    try:
        source_refs: dict[str, dict[str, str]] = {}
        for url, source in fetched.items():
            filename = f"source-{hashlib.sha256(url.encode()).hexdigest()[:16]}.json"
            path = staging / filename
            path.write_text(
                json.dumps(
                    {
                        "schema_id": "geode.geo-source-receipt@1",
                        "fetched_at": datetime.now(UTC).isoformat(),
                        **source,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            source_refs[url] = {
                "path": f"{evidence_dir.name}/{filename}",
                "sha256": _sha256(path),
            }

        rows = []
        for (observation, target_urls), verdict in zip(selected, verdicts, strict=True):
            observation_id = str(observation["observation_id"])
            receipt = {
                "schema_id": "geode.geo-verifier-receipt@1",
                "observation_id": observation_id,
                "producer": "codex-oauth",
                "model": model,
                "verified_at": datetime.now(UTC).isoformat(),
                "rubric_sha256": _sha256(rubric_path),
                "sources": [source_refs[url] for url in target_urls],
                **verdict,
            }
            filename = f"verdict-{observation_id}.json"
            path = staging / filename
            path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            rows.append(
                {
                    "observation_id": observation_id,
                    **{
                        key: verdict[key]
                        for key in ("absorption", "quality", "quality_claims_expected")
                    },
                    "verifier_receipt": {
                        "path": f"{evidence_dir.name}/{filename}",
                        "sha256": _sha256(path),
                    },
                }
            )
        os.rename(staging, evidence_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    rubric_ref = {
        "path": _relative(rubric_path, output_path.parent, label="GEO verifier rubric"),
        "sha256": _sha256(rubric_path),
    }
    payload = {
        "schema_id": "geode.geo-verifier-results@1",
        "schema_version": 1,
        "run_id": workload["run_id"],
        "native_results_sha256": _sha256(native_results_path),
        "verified_at": datetime.now(UTC).isoformat(),
        "verifier_context": {
            "producer": "codex-oauth",
            "version": producer_version,
            "rubric": rubric_ref,
        },
        "observations": rows,
    }
    try:
        _validate_schema(payload, "geo-verifier-results.schema.json", label=str(output_path))
        _write_exclusive(output_path, payload)
    except Exception:
        shutil.rmtree(evidence_dir, ignore_errors=True)
        raise
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--native-results", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--producer-version", default="gpt-5.5")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args(argv)
    if args.concurrency <= 0:
        parser.error("concurrency must be positive")
    asyncio.run(
        verify(
            workload_path=args.workload,
            native_results_path=args.native_results,
            rubric_path=args.rubric,
            output_path=args.out,
            model=args.model,
            producer_version=args.producer_version,
            concurrency=args.concurrency,
        )
    )
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
