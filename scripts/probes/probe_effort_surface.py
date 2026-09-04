"""Measure every effort level exposed by GEODE's model picker.

The probe uses the production-resolved adapters, appends one JSONL row per
attempt, and stops on the first failed wire or response contract. Re-running
with the same output file skips prior passes and retries the failed pair.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SCHEMA = "geode.effort-surface-measurement@1"
PROMPT = "Return only this token: EFFORT_OK"
SYSTEM_PROMPT = "Follow the user's output instruction exactly."


def visible_effort_surface(
    model_ids: tuple[str, ...] = (),
) -> tuple[tuple[str, str, str], ...]:
    """Return picker order as ``(model, provider, effort)`` rows."""
    from core.cli.commands._state import get_model_profiles
    from core.cli.effort_picker import supported_efforts

    surface = tuple(
        (profile.id, profile.provider, effort)
        for profile in get_model_profiles()
        for effort in supported_efforts(profile.id, profile.provider)
    )
    if not model_ids:
        return surface
    rows_by_model = {model: tuple(row for row in surface if row[0] == model) for model in model_ids}
    unknown = [model for model, rows in rows_by_model.items() if not rows]
    if unknown:
        raise ValueError(f"models have no exposed effort surface: {', '.join(unknown)}")
    return tuple(row for model in model_ids for row in rows_by_model[model])


def _wire_effort(request: Any, provider: str, source: str) -> str | None:
    if provider == "anthropic":
        from core.llm.adapters._anthropic_common import build_create_kwargs

        return build_create_kwargs(request).get("output_config", {}).get("effort")

    from core.llm.adapters._openai_common import build_responses_kwargs

    return (
        build_responses_kwargs(
            request,
            backend="codex" if source == "subscription" else "platform",
            adapter_name="effort-surface-measurement",
        )
        .get("reasoning", {})
        .get("effort")
    )


def _passed_keys(output: Path) -> set[tuple[str, str]]:
    if not output.exists():
        return set()
    passed: set[tuple[str, str]] = set()
    for line_number, line in enumerate(output.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {output}:{line_number}") from exc
        if row.get("status") == "pass":
            passed.add((str(row["model"]), str(row["requested_effort"])))
    return passed


def _append(output: Path, row: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _reasoning_tokens(raw_response: Any) -> int | None:
    usage = getattr(raw_response, "usage", None)
    details = getattr(usage, "output_tokens_details", None)
    value = getattr(details, "reasoning_tokens", None)
    return int(value) if value is not None else None


async def _acomplete_with_runtime_retry(
    adapter: Any,
    request: Any,
    *,
    timeout_s: float,
    retry_history: list[dict[str, Any]],
) -> Any:
    """Use AgenticLoop's configured pre-response retry policy."""
    from core.llm.errors import classify_llm_error
    from core.llm.fallback import interactive_retry_policy, run_with_retry_policy

    async def call(_model: str) -> Any:
        try:
            return await asyncio.wait_for(adapter.acomplete(request), timeout_s)
        except Exception as exc:
            category, _, _ = classify_llm_error(exc)
            retry_history.append(
                {
                    "attempt": len(retry_history) + 1,
                    "error_type": type(exc).__name__,
                    "error_category": category,
                    "error": str(exc)[:2000],
                }
            )
            raise

    outcome = await run_with_retry_policy(
        [request.model],
        call,
        policy=interactive_retry_policy(),
        provider_label="effort probe",
    )
    if outcome.succeeded:
        return outcome.value
    if outcome.last_error is not None:
        raise outcome.last_error
    raise RuntimeError("effort measurement has no allowed model")


async def measure(
    output: Path,
    *,
    timeout_s: float,
    producer_revision: str,
    model_ids: tuple[str, ...] = (),
) -> int:
    from core.llm.adapters._source_inference import infer_source
    from core.llm.adapters.base import AdapterCallRequest, Message
    from core.llm.adapters.registry import bootstrap_builtins, resolve_for

    bootstrap_builtins()
    surface = visible_effort_surface(model_ids)
    adapters = {
        provider: resolve_for(provider, infer_source(provider)) for _, provider, _ in surface
    }
    passed = _passed_keys(output)

    for ordinal, (model, provider, effort) in enumerate(surface, 1):
        if (model, effort) in passed:
            print(f"SKIP {ordinal:02d}/{len(surface)} {model} effort={effort}", flush=True)
            continue

        request = AdapterCallRequest(
            model=model,
            messages=(Message(role="user", content=PROMPT),),
            system_prompt=SYSTEM_PROMPT,
            max_tokens=256,
            effort=effort,
        )
        started_at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        adapter = adapters[provider]
        wire_effort = _wire_effort(request, provider, adapter.source)
        common = {
            "schema": SCHEMA,
            "producer_revision": producer_revision,
            "ordinal": ordinal,
            "surface_size": len(surface),
            "model": model,
            "provider": provider,
            "adapter": adapter.name,
            "adapter_source": adapter.source,
            "requested_effort": effort,
            "wire_effort": wire_effort,
            "started_at": started_at,
        }
        if wire_effort != effort:
            row = {
                **common,
                "status": "fail",
                "failure_stage": "wire",
                "error_type": "EffortWireMismatch",
                "error": f"requested={effort!r} wire={wire_effort!r}",
                "latency_ms": 0,
            }
            _append(output, row)
            print(f"FAIL {ordinal:02d}/{len(surface)} {model} effort={effort} wire mismatch")
            return 1

        print(f"RUN  {ordinal:02d}/{len(surface)} {model} effort={effort}", flush=True)
        retry_history: list[dict[str, Any]] = []
        try:
            result = await _acomplete_with_runtime_retry(
                adapter,
                request,
                timeout_s=timeout_s,
                retry_history=retry_history,
            )
            text = result.text.strip()
            contract_ok = text == "EFFORT_OK" and not result.tool_uses
            row = {
                **common,
                "status": "pass" if contract_ok else "fail",
                "failure_stage": None if contract_ok else "response_contract",
                "completed_at": datetime.now(UTC).isoformat(),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "stop_reason": result.stop_reason,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cached_input_tokens": result.usage.cached_input_tokens,
                "reasoning_tokens": _reasoning_tokens(result.raw_response),
                "reasoning_item_count": len(result.reasoning_items),
                "reasoning_summary_count": len(result.reasoning_summaries),
                "response_text": text,
                "response_sha256": hashlib.sha256(result.text.encode()).hexdigest(),
                "tool_use_count": len(result.tool_uses),
                "attempt_count": len(retry_history) + 1,
                "retry_history": retry_history,
            }
        except Exception as exc:
            row = {
                **common,
                "status": "fail",
                "failure_stage": "adapter_call",
                "completed_at": datetime.now(UTC).isoformat(),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
                "attempt_count": len(retry_history),
                "retry_history": retry_history,
            }

        _append(output, row)
        print(
            f"{row['status'].upper():4s} {ordinal:02d}/{len(surface)} {model} "
            f"effort={effort} latency_ms={row['latency_ms']}",
            flush=True,
        )
        if row["status"] != "pass":
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--producer-revision", required=True)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--timeout-s", type=float, default=300.0)
    args = parser.parse_args()
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")
    return asyncio.run(
        measure(
            args.output.resolve(),
            timeout_s=args.timeout_s,
            producer_revision=args.producer_revision,
            model_ids=tuple(args.model),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
