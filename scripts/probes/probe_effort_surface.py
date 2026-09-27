"""Measure every effort level exposed by GEODE's model picker.

The probe uses the production-resolved adapters, appends one JSONL row per
attempt, and stops on the first failed wire or response contract. Re-running
with the same output file skips only matching route/revision passes. Older
rows remain unchanged; a different route or revision is a new measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SCHEMA = "geode.effort-surface-measurement@1"
PROMPT = "Return only this token: EFFORT_OK"
SYSTEM_PROMPT = "Follow the user's output instruction exactly."


def visible_effort_surface(
    model_ids: tuple[str, ...] = (),
    *,
    configured_model_ids: tuple[str, ...] = (),
) -> tuple[tuple[str, str, str], ...]:
    """Return picker order as ``(model, provider, effort)`` rows."""
    from core.cli.commands._state import get_model_profiles
    from core.cli.effort_picker import supported_efforts

    surface = tuple(
        (profile.id, profile.provider, effort)
        for profile in get_model_profiles(configured_model_ids=(*configured_model_ids, *model_ids))
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
    if provider == "anthropic" and source == "payg":
        from core.llm.adapters._anthropic_common import build_create_kwargs

        value = build_create_kwargs(request).get("output_config", {}).get("effort")
        return value if isinstance(value, str) else None

    if provider == "glm" and source in {"payg", "subscription"}:
        from core.llm.providers.glm import build_glm_reasoning_extra_body

        controls = build_glm_reasoning_extra_body(request.model, effort=request.effort)
        return controls.get("reasoning_effort") if controls else None

    if provider != "openai" or source not in {"payg", "subscription"}:
        raise ValueError(f"no wire effort oracle for {provider}/{source}")

    from core.llm.adapters._openai_common import build_responses_kwargs

    value = (
        build_responses_kwargs(
            request,
            backend="codex" if source == "subscription" else "platform",
            adapter_name="effort-surface-measurement",
        )
        .get("reasoning", {})
        .get("effort")
    )
    return value if isinstance(value, str) else None


async def _openrouter_wire_effort(request: Any, adapter: Any) -> str | None:
    """Observe the selected adapter's SDK body without credentials or a network call.

    This checks local serialization only; the later real adapter response owns
    server acceptance. Never project an OpenRouter request through Responses.
    """
    from unittest.mock import patch

    import httpx
    from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter
    from openai import AsyncOpenAI

    if not isinstance(adapter, OpenRouterPaygAdapter) or adapter.source != "payg":
        raise ValueError("no wire effort oracle for this OpenRouter adapter")
    bodies: list[dict[str, Any]] = []

    def capture(wire: httpx.Request) -> httpx.Response:
        if wire.method != "POST" or wire.url.path != "/api/v1/chat/completions":
            raise ValueError("unexpected OpenRouter serialization endpoint")
        bodies.append(json.loads(wire.content))
        return httpx.Response(
            200,
            json={
                "id": "probe-serialization-only",
                "object": "chat.completion",
                "created": 0,
                "model": bodies[-1]["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            },
        )

    async with AsyncOpenAI(
        api_key="serialization-only",
        base_url="https://openrouter.invalid/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(capture)),
    ) as client:
        with patch.object(adapter, "_get_client", return_value=client):
            await adapter.acomplete(request)
    if len(bodies) != 1 or bodies[0].get("model") != request.model.removeprefix("openrouter/"):
        raise ValueError("OpenRouter serialization did not preserve the selected model")
    value = bodies[0].get("reasoning", {}).get("effort")
    return value if isinstance(value, str) else None


def _adapter_base_url(adapter: Any, model: str = "") -> str | None:
    """Read the selected endpoint without constructing a live SDK client."""
    from core import config
    from core.llm.registry import get_provider_spec

    if adapter.name == "openai-payg":
        spec = get_provider_spec("openai")
        if spec is None:
            raise ValueError("OpenAI provider contract is missing")
        raw = os.environ.get("OPENAI_BASE_URL", spec.default_base_url)
    elif adapter.name == "anthropic-payg":
        spec = get_provider_spec("anthropic")
        if spec is None:
            raise ValueError("Anthropic provider contract is missing")
        raw = os.environ.get("ANTHROPIC_BASE_URL", spec.default_base_url)
    elif adapter.name == "codex-oauth":
        raw = config.CODEX_BASE_URL
    elif adapter.name == "glm-payg":
        raw = config.GLM_PAYG_BASE_URL
    elif adapter.name == "glm-coding-plan":
        # Its resolver reads the selected profile/key; no read-only endpoint
        # owner exists. Keep the attempt, but do not reuse an unknown route.
        return None
    elif adapter.name == "openrouter-payg":
        spec = get_provider_spec("openrouter")
        if spec is None:
            raise ValueError("OpenRouter provider contract is missing")
        raw = spec.default_base_url
    else:
        raise ValueError("no endpoint oracle for this adapter")
    if model:
        from core.llm.routing import resolve_routing

        target = resolve_routing(
            model,
            provider=adapter.provider,
            source=adapter.source,
            sources=getattr(adapter, "routing_sources", None),
            base_url=raw,
        )
        if target is not None:
            raw = target.base_url
    parts = urlsplit(raw)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("endpoint identity must be an HTTP URL without credentials/query/fragment")
    return raw.rstrip("/")


def _measurement_key(row: dict[str, Any]) -> tuple[str, ...] | None:
    values = tuple(
        row.get(field)
        for field in (
            "provider",
            "adapter",
            "adapter_source",
            "adapter_base_url",
            "model",
            "requested_effort",
            "producer_revision",
        )
    )
    if row.get("schema") != SCHEMA or not all(isinstance(v, str) and v for v in values):
        return None
    return tuple(str(value) for value in values)


def _passed_keys(output: Path) -> set[tuple[str, ...]]:
    if not output.exists():
        return set()
    passed: set[tuple[str, ...]] = set()
    for line_number, line in enumerate(output.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {output}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"invalid measurement at {output}:{line_number}")
        key = _measurement_key(row)
        if (
            key is not None
            and row.get("status") == "pass"
            and row.get("wire_effort") == row.get("requested_effort")
        ):
            passed.add(key)
    return passed


def _require_producer_revision(revision: str) -> None:
    """Reject a mislabeled or tracked-dirty checkout before resume or dispatch."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("producer revision must be a full commit SHA")
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to validate producer revision")
    head = subprocess.check_output(  # noqa: S603 — fixed argv, resolved git executable
        [git, "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
    ).strip()
    if revision != head:
        raise ValueError("producer revision does not match the current checkout")
    subprocess.run(  # noqa: S603 — fixed argv, resolved git executable
        [git, "diff", "--quiet", "HEAD", "--"], cwd=_REPO_ROOT, check=True
    )


def _append(output: Path, row: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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
    from core.llm.adapters.base import AdapterCallRequest, Message
    from core.llm.adapters.registry import bootstrap_builtins, resolve_for
    from core.llm.routing import infer_source

    _require_producer_revision(producer_revision)
    from core.cli.commands._state import AGENT_ROLES
    from core.cli.commands.model import _current_model_for_role

    bootstrap_builtins()
    surface = visible_effort_surface(
        model_ids,
        configured_model_ids=tuple(_current_model_for_role(role) for role in AGENT_ROLES),
    )
    adapters = {
        (model, provider): resolve_for(provider, infer_source(provider, model=model))
        for model, provider, _ in surface
    }
    passed = _passed_keys(output)

    for ordinal, (model, provider, effort) in enumerate(surface, 1):
        adapter = adapters[(model, provider)]
        identity = {
            "schema": SCHEMA,
            "producer_revision": producer_revision,
            "model": model,
            "provider": provider,
            "adapter": adapter.name,
            "adapter_source": adapter.source,
            "adapter_base_url": _adapter_base_url(adapter, model),
            "requested_effort": effort,
        }
        if _measurement_key(identity) in passed:
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
        wire_effort = (
            await _openrouter_wire_effort(request, adapter)
            if provider == "openrouter"
            else _wire_effort(request, provider, adapter.source)
        )
        common = {
            **identity,
            "ordinal": ordinal,
            "surface_size": len(surface),
            "wire_effort": wire_effort,
            "started_at": started_at,
        }
        if wire_effort != effort:
            row: dict[str, Any] = {
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
                "reasoning_tokens": (
                    result.usage.reasoning_tokens if result.usage.reasoning_tokens_present else None
                ),
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
