#!/usr/bin/env python3
"""Measure GEODE's local architecture performance and enforce per-metric limits."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "docs" / "architecture" / "performance-baseline.json"
SCHEMA_VERSION = 1


class PerformanceBaselineError(ValueError):
    """Raised when the committed baseline is incomplete or malformed."""


def _positive_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise PerformanceBaselineError(f"{label} must be a positive number")
    return float(value)


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate the committed independent metric limits."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PerformanceBaselineError(f"cannot read performance baseline: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise PerformanceBaselineError(f"schema_version must be integer {SCHEMA_VERSION}")
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise PerformanceBaselineError("metrics must be a non-empty object")
    parsed: dict[str, dict[str, Any]] = {}
    for name, row in metrics.items():
        if not isinstance(name, str) or not name or not isinstance(row, dict):
            raise PerformanceBaselineError("metric names and rows must be objects")
        if set(row) != {"unit", "observed", "maximum"}:
            raise PerformanceBaselineError(f"{name}: expected unit, observed, maximum")
        unit = row["unit"]
        if not isinstance(unit, str) or not unit:
            raise PerformanceBaselineError(f"{name}: unit must be a non-empty string")
        observed = _positive_number(row["observed"], label=f"{name}.observed")
        maximum = _positive_number(row["maximum"], label=f"{name}.maximum")
        if observed > maximum:
            raise PerformanceBaselineError(f"{name}: observed exceeds maximum")
        parsed[name] = {"unit": unit, "observed": observed, "maximum": maximum}
    return parsed


def compare_measurements(
    measurements: Mapping[str, float],
    baseline: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return one error per missing, unexpected, or over-budget metric."""
    errors: list[str] = []
    missing = sorted(set(baseline) - set(measurements))
    unexpected = sorted(set(measurements) - set(baseline))
    if missing:
        errors.append(f"missing metrics: {', '.join(missing)}")
    if unexpected:
        errors.append(f"unexpected metrics: {', '.join(unexpected)}")
    for name in sorted(set(measurements) & set(baseline)):
        value = measurements[name]
        maximum = float(baseline[name]["maximum"])
        if value > maximum:
            unit = baseline[name]["unit"]
            errors.append(f"{name}: {value:.3f} {unit} exceeds {maximum:.3f} {unit}")
    return errors


def _median_ms(samples: Sequence[float]) -> float:
    return statistics.median(samples) * 1000.0


def _minimal_bound_plan() -> Any:
    from core.tools.plan import ExecutionBinding, ToolSpec, bind_tool_plan, compile_tool_plan

    async def noop(**_kwargs: Any) -> dict[str, bool]:
        return {"ok": True}

    plan = compile_tool_plan(
        ((ToolSpec("architecture_noop", "Local performance probe", {"type": "object"}), "probe"),),
        (ExecutionBinding("architecture_noop", "probe"),),
    )
    return bind_tool_plan(plan, {"architecture_noop": noop})


async def _measure_async(bound: Any) -> dict[str, float]:
    from core.agent.conversation import ConversationContext
    from core.agent.loop import AgenticLoop, AgenticLoopConfig
    from core.agent.tool_executor import ToolExecutor
    from core.llm.adapters.base import AdapterCallResult, UsageSummary
    from core.llm.adapters.registry import bootstrap_builtins
    from core.mcp.tool_runtime import MCPToolInvoker, MCPTraceStore

    executor = ToolExecutor(bound_tool_plan=bound, hitl_level=0)
    dispatch_samples: list[float] = []
    for _ in range(40):
        started = time.perf_counter()
        dispatch_result = await executor.aexecute("architecture_noop", {})
        dispatch_samples.append(time.perf_counter() - started)
        if dispatch_result.get("ok") is not True:
            raise RuntimeError("local tool dispatch probe failed")

    class LocalAdapter:
        name = "architecture-performance"
        provider = "openai"
        source = "subscription"

        async def acomplete(self, _request: Any) -> AdapterCallResult:
            return AdapterCallResult(
                text="ok",
                usage=UsageSummary(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )

    bootstrap_builtins()
    loop = AgenticLoop(
        ConversationContext(),
        ToolExecutor(bound_tool_plan=bound, hitl_level=0),
        config=AgenticLoopConfig(
            source="subscription",
            disable_settings_drift=True,
            session_id="architecture-performance",
        ),
        model="gpt-5.6-luna",
        provider="openai",
        quiet=True,
    )
    loop._new_adapter = LocalAdapter()
    started = time.perf_counter()
    turn_result = await loop.arun("Return ok.")
    first_turn_ms = (time.perf_counter() - started) * 1000.0
    if turn_result.error is not None or turn_result.text != "ok":
        raise RuntimeError(
            f"local first-turn probe failed: {turn_result.error or turn_result.text}"
        )

    class LocalMCPClient:
        def list_tools(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "ping",
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": True},
                }
            ]

        async def acall_tool(self, _name: str, _args: dict[str, Any]) -> dict[str, Any]:
            return {"content": [{"type": "text", "text": "pong"}]}

        def is_connected(self) -> bool:
            return True

    client = LocalMCPClient()
    invoker = MCPToolInvoker(
        MCPTraceStore(lambda _event, _data: None),
        get_client=lambda _server: cast(Any, client),
        respawn=lambda _server: cast(Any, client),
    )
    started = time.perf_counter()
    first = await invoker.call("local", "ping", {})
    mcp_first_ms = (time.perf_counter() - started) * 1000.0
    if first.get("content", [{}])[0].get("text") != "pong":
        raise RuntimeError("local MCP first-call probe failed")
    warm_samples: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        await invoker.call("local", "ping", {})
        warm_samples.append(time.perf_counter() - started)

    return {
        "first_turn_ms": first_turn_ms,
        "tool_dispatch_us": statistics.median(dispatch_samples) * 1_000_000.0,
        "mcp_first_call_ms": mcp_first_ms,
        "mcp_warm_call_ms": _median_ms(warm_samples),
    }


def _measure_probe() -> dict[str, float]:
    """Run every no-network probe inside one isolated child process."""
    import_started = time.perf_counter()
    from core.hooks.catalog import EventRetentionClass
    from core.observability.event_store import HookEventStore, HookEventWrite
    from core.runtime import GeodeRuntime
    from core.tools.plan import thaw_tool_schema
    from geode_product.tool_handlers import compose_tool_plan

    import_ms = (time.perf_counter() - import_started) * 1000.0
    root = Path.cwd()

    tracemalloc.start()
    started = time.perf_counter()
    runtime = GeodeRuntime.create("architecture-performance", log_dir=root / "logs")
    runtime.shutdown()
    runtime_ms = (time.perf_counter() - started) * 1000.0
    _current, runtime_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    started = time.perf_counter()
    bound, transient = compose_tool_plan()
    plan_build_ms = (time.perf_counter() - started) * 1000.0
    _current, plan_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    refresh_samples: list[float] = []
    previous = bound
    for _ in range(10):
        started = time.perf_counter()
        refreshed, _transient = compose_tool_plan(previous=previous)
        refresh_samples.append(time.perf_counter() - started)
        previous = refreshed

    descriptor = [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": thaw_tool_schema(spec.input_schema),
        }
        for spec in bound.ordered_specs
    ]
    descriptor_bytes = len(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    store = HookEventStore(root / "events.db")
    event = HookEventWrite(
        occurred_at=time.time(),
        session_key="architecture-performance",
        run_id="run",
        event="tool.result",
        dispatch_mode="async",
        status="ok",
        retention_class=EventRetentionClass.STANDARD,
        handler_count=1,
        handler_error_count=0,
        blocked=False,
        block_reason="",
        actor_type="agent",
        actor_id="probe",
        action="tool.result",
        entity_type="tool",
        entity_id="architecture_noop",
        task_id=None,
        level="info",
        payload={"duration_ms": 1.0},
    )
    persistence_samples: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        store.append(event)
        persistence_samples.append(time.perf_counter() - started)
    store.close()

    measurements = {
        "import_cold_start_ms": import_ms,
        "runtime_create_shutdown_ms": runtime_ms,
        "runtime_peak_kib": runtime_peak / 1024.0,
        "tool_plan_build_ms": plan_build_ms,
        "tool_plan_refresh_ms": _median_ms(refresh_samples),
        "tool_plan_peak_kib": plan_peak / 1024.0,
        "tool_descriptor_bytes": float(descriptor_bytes),
        "tool_registry_entries": float(len(bound.tool_names) + len(transient)),
        "event_persist_us": statistics.median(persistence_samples) * 1_000_000.0,
    }
    measurements.update(asyncio.run(_measure_async(_minimal_bound_plan())))
    return measurements


def collect_measurements(*, samples: int = 3) -> dict[str, float]:
    """Collect medians from isolated fresh-process probes."""
    if samples < 1:
        raise ValueError("samples must be positive")
    rows: list[dict[str, float]] = []
    with tempfile.TemporaryDirectory(prefix="geode-performance-") as temp:
        root = Path(temp)
        for index in range(samples):
            sample_root = root / f"sample-{index}"
            sample_root.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "CODEX_HOME": str(sample_root / "codex"),
                    "GEODE_COGNITIVE_REFLECTION_ENABLED": "false",
                    "GEODE_HOME": str(sample_root / "home"),
                    "GEODE_STATE_ROOT": str(sample_root / "state"),
                    "GEODE_VERIFY_MODE": "off",
                    "_GEODE_ARCHITECTURE_PERFORMANCE_PROBE": "1",
                }
            )
            completed = subprocess.run(  # noqa: S603 -- current interpreter and fixed script
                [sys.executable, str(Path(__file__).resolve()), "--probe"],
                cwd=sample_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            rows.append(json.loads(completed.stdout))
    names = set(rows[0])
    if any(set(row) != names for row in rows):
        raise RuntimeError("performance probe returned inconsistent metric sets")
    return {name: statistics.median(row[name] for row in rows) for name in sorted(names)}


def _render(measurements: Mapping[str, float], baseline: Mapping[str, Mapping[str, Any]]) -> str:
    lines = []
    for name in sorted(measurements):
        unit = baseline[name]["unit"]
        maximum = float(baseline[name]["maximum"])
        lines.append(f"{name}: {measurements[name]:.3f} {unit} (max {maximum:.3f})")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    args = parser.parse_args(argv)
    if args.probe:
        if os.environ.get("_GEODE_ARCHITECTURE_PERFORMANCE_PROBE") != "1":
            print("--probe is an internal isolated subprocess mode", file=sys.stderr)
            return 2
        print(json.dumps(_measure_probe(), sort_keys=True))
        return 0
    try:
        baseline = load_baseline(args.baseline)
        measurements = collect_measurements(samples=args.samples)
        errors = compare_measurements(measurements, baseline)
    except (PerformanceBaselineError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"architecture performance check failed: {exc}", file=sys.stderr)
        return 1
    print(_render(measurements, baseline))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("architecture performance OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
