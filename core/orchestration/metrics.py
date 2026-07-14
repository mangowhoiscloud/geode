"""Structured metrics aggregator — percentile latency, success rates, engagement.

Consumes HookSystem events (LLM_CALL_END, TOOL_RECOVERY_*, SESSION_END)
and produces structured metrics for observability and ML evaluation.

Usage:
    metrics = LatencyMetrics()
    metrics.record_llm_call(model="claude-opus-4-6", latency_ms=1200, error=None)
    summary = metrics.summary()
    # → {"llm": {"total_calls": 5, "p50_ms": 1200, "p95_ms": 3400, ...}, ...}
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class _ModelLatency:
    calls: int = 0
    total_ms: float = 0.0
    samples: deque[float] = field(default_factory=deque)


@dataclass
class LatencyMetrics:
    """Accumulates latency/recovery aggregates for a single session.

    Renamed from ``SessionMetrics`` (S-6, 2026-06-11) — it collided with
    ``core.observability.session_metrics.SessionMetrics`` (the hermes-parity
    cost/token tracker). This class is the hook-fed percentile aggregator.
    """

    max_samples: int = 2_048
    max_model_series: int = 64
    _llm_latencies: deque[float] = field(init=False)
    _llm_calls: int = 0
    _llm_errors: int = 0
    _llm_total_ms: float = 0.0
    _llm_max_ms: float = 0.0
    _llm_by_model: dict[str, _ModelLatency] = field(default_factory=dict)
    _tool_calls: int = 0
    _tool_errors: int = 0
    _tool_recoveries: int = 0
    _rounds: int = 0
    _start_time: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.max_samples <= 0:
            raise ValueError("max_samples must be positive")
        if self.max_model_series <= 0:
            raise ValueError("max_model_series must be positive")
        self._llm_latencies = deque(maxlen=self.max_samples)

    def record_llm_call(
        self,
        model: str,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        """Record a single LLM call."""
        latency = max(0.0, float(latency_ms))
        model_key = str(model or "unknown")[:128]
        with self._lock:
            self._llm_calls += 1
            self._llm_total_ms += latency
            self._llm_max_ms = max(self._llm_max_ms, latency)
            self._llm_latencies.append(latency)
            if error:
                self._llm_errors += 1
            model_is_new = model_key not in self._llm_by_model
            named_capacity_reached = (
                "__other__" not in self._llm_by_model
                and len(self._llm_by_model) >= self.max_model_series - 1
            )
            total_capacity_reached = len(self._llm_by_model) >= self.max_model_series
            if model_is_new and (named_capacity_reached or total_capacity_reached):
                model_key = "__other__"
            model_metrics = self._llm_by_model.setdefault(
                model_key,
                _ModelLatency(samples=deque(maxlen=self.max_samples)),
            )
            model_metrics.calls += 1
            model_metrics.total_ms += latency
            model_metrics.samples.append(latency)

    def record_tool_call(self, *, success: bool = True) -> None:
        """Record a tool execution."""
        with self._lock:
            self._tool_calls += 1
            if not success:
                self._tool_errors += 1

    def record_tool_recovery(self) -> None:
        """Record a successful tool recovery."""
        with self._lock:
            self._tool_recoveries += 1

    def record_round(self) -> None:
        """Record an agentic loop round."""
        with self._lock:
            self._rounds += 1

    def summary(self) -> dict[str, Any]:
        """Produce structured metrics summary."""
        elapsed_s = time.monotonic() - self._start_time
        with self._lock:
            llm_calls = self._llm_calls
            llm_errors = self._llm_errors
            llm_total_ms = self._llm_total_ms
            llm_max_ms = self._llm_max_ms
            llm_latencies = list(self._llm_latencies)
            model_snapshots = {
                model: (stats.calls, stats.total_ms, list(stats.samples))
                for model, stats in self._llm_by_model.items()
            }
            tool_calls = self._tool_calls
            tool_errors = self._tool_errors
            tool_recoveries = self._tool_recoveries
            rounds = self._rounds

        llm_summary: dict[str, Any] = {
            "total_calls": llm_calls,
            "total_errors": llm_errors,
            "error_rate": llm_errors / llm_calls if llm_calls else 0.0,
            "sample_size": len(llm_latencies),
        }

        if llm_latencies:
            sorted_lat = sorted(llm_latencies)
            llm_summary["p50_ms"] = _percentile(sorted_lat, 50)
            llm_summary["p95_ms"] = _percentile(sorted_lat, 95)
            llm_summary["mean_ms"] = llm_total_ms / llm_calls
            llm_summary["max_ms"] = llm_max_ms

        # Per-model breakdown
        by_model: dict[str, dict[str, Any]] = {}
        for model, (calls, total_ms, lats) in model_snapshots.items():
            s = sorted(lats)
            by_model[model] = {
                "calls": calls,
                "sample_size": len(s),
                "p50_ms": _percentile(s, 50),
                "p95_ms": _percentile(s, 95),
                "mean_ms": total_ms / calls if calls else 0.0,
            }
        llm_summary["by_model"] = by_model

        tool_summary = {
            "total_calls": tool_calls,
            "total_errors": tool_errors,
            "success_rate": ((tool_calls - tool_errors) / tool_calls if tool_calls else 1.0),
            "recoveries": tool_recoveries,
        }

        return {
            "session_elapsed_s": round(elapsed_s, 1),
            "rounds": rounds,
            "llm": llm_summary,
            "tools": tool_summary,
        }


def _percentile(sorted_data: list[float], pct: int) -> float:
    """Compute percentile from pre-sorted data."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def make_metrics_hook_handler(
    metrics: LatencyMetrics,
) -> list[tuple[str, str, Any]]:
    """Create hook handlers that feed events into LatencyMetrics.

    Returns list of (event_name, handler_name, handler_fn) tuples
    for registration in HookSystem.
    """

    def _on_llm_end(_e: Any, data: dict[str, Any]) -> None:
        metrics.record_llm_call(
            model=data.get("model", "unknown"),
            latency_ms=data.get("latency_ms", 0.0),
            error=data.get("error"),
        )

    def _on_tool_recovery_succeeded(_e: Any, _d: dict[str, Any]) -> None:
        metrics.record_tool_recovery()

    return [
        ("llm_call_ended", "metrics_llm", _on_llm_end),
        ("tool_recovery_succeeded", "metrics_recovery", _on_tool_recovery_succeeded),
    ]
