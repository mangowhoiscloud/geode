"""Structured metrics aggregator — percentile latency, success rates, engagement.

Consumes HookSystem events (LLM_CALL_END, TOOL_RECOVERY_*, SESSION_END)
and produces structured metrics for observability and ML evaluation.

Usage:
    metrics = SessionMetrics()
    metrics.record_llm_call(model="claude-opus-4-6", latency_ms=1200, error=None)
    summary = metrics.summary()
    # → {"llm": {"total_calls": 5, "p50_ms": 1200, "p95_ms": 3400, ...}, ...}
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class SessionMetrics:
    """Accumulates structured metrics for a single session."""

    _llm_latencies: list[float] = field(default_factory=list)
    _llm_errors: int = 0
    _llm_by_model: dict[str, list[float]] = field(default_factory=dict)
    _tool_calls: int = 0
    _tool_errors: int = 0
    _tool_recoveries: int = 0
    _rounds: int = 0
    _start_time: float = field(default_factory=time.monotonic)

    def record_llm_call(
        self,
        model: str,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        """Record a single LLM call."""
        self._llm_latencies.append(latency_ms)
        if error:
            self._llm_errors += 1
        self._llm_by_model.setdefault(model, []).append(latency_ms)

    def record_tool_call(self, *, success: bool = True) -> None:
        """Record a tool execution."""
        self._tool_calls += 1
        if not success:
            self._tool_errors += 1

    def record_tool_recovery(self) -> None:
        """Record a successful tool recovery."""
        self._tool_recoveries += 1

    def record_round(self) -> None:
        """Record an agentic loop round."""
        self._rounds += 1

    def summary(self) -> dict[str, Any]:
        """Produce structured metrics summary."""
        elapsed_s = time.monotonic() - self._start_time

        llm_summary: dict[str, Any] = {
            "total_calls": len(self._llm_latencies),
            "total_errors": self._llm_errors,
            "error_rate": (
                self._llm_errors / len(self._llm_latencies) if self._llm_latencies else 0.0
            ),
        }

        if self._llm_latencies:
            sorted_lat = sorted(self._llm_latencies)
            llm_summary["p50_ms"] = _percentile(sorted_lat, 50)
            llm_summary["p95_ms"] = _percentile(sorted_lat, 95)
            llm_summary["mean_ms"] = statistics.mean(sorted_lat)
            llm_summary["max_ms"] = sorted_lat[-1]

        # Per-model breakdown
        by_model: dict[str, dict[str, Any]] = {}
        for model, lats in self._llm_by_model.items():
            s = sorted(lats)
            by_model[model] = {
                "calls": len(s),
                "p50_ms": _percentile(s, 50),
                "p95_ms": _percentile(s, 95),
                "mean_ms": statistics.mean(s),
            }
        llm_summary["by_model"] = by_model

        tool_summary = {
            "total_calls": self._tool_calls,
            "total_errors": self._tool_errors,
            "success_rate": (
                (self._tool_calls - self._tool_errors) / self._tool_calls
                if self._tool_calls
                else 1.0
            ),
            "recoveries": self._tool_recoveries,
        }

        return {
            "session_elapsed_s": round(elapsed_s, 1),
            "rounds": self._rounds,
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
    metrics: SessionMetrics,
) -> list[tuple[str, str, Any]]:
    """Create hook handlers that feed events into SessionMetrics.

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
        ("llm_call_end", "metrics_llm", _on_llm_end),
        ("tool_recovery_succeeded", "metrics_recovery", _on_tool_recovery_succeeded),
    ]
