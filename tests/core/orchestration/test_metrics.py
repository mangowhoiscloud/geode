"""Bounds and aggregate accuracy for hook-fed latency metrics."""

from __future__ import annotations

from core.orchestration.metrics import LatencyMetrics


def test_latency_samples_and_model_cardinality_are_bounded() -> None:
    metrics = LatencyMetrics(max_samples=5, max_model_series=3)
    for index in range(20):
        metrics.record_llm_call(
            model=f"model-{index}",
            latency_ms=float(index),
            error="failed" if index % 4 == 0 else None,
        )

    summary = metrics.summary()["llm"]
    assert summary["total_calls"] == 20
    assert summary["total_errors"] == 5
    assert summary["sample_size"] == 5
    assert summary["mean_ms"] == 9.5
    assert len(summary["by_model"]) == 3
    assert "__other__" in summary["by_model"]


def test_invalid_metric_bounds_fail_at_construction() -> None:
    for kwargs in ({"max_samples": 0}, {"max_model_series": 0}):
        try:
            LatencyMetrics(**kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover - assertion detail
            raise AssertionError(f"expected ValueError for {kwargs}")
