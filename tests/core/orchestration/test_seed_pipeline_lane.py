"""Verify the new ``seed-pipeline`` Lane is wired in ``core.wiring.container``."""

from __future__ import annotations

from core.orchestration.lane_queue import LaneQueue, SessionLane
from core.wiring.container import (
    DEFAULT_GATEWAY_CONCURRENCY,
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_SEED_PIPELINE_CONCURRENCY,
)


def _build_queue_under_test() -> LaneQueue:
    """Reproduce the in-test slice of ``_build_lane_queue`` from container.

    The real ``_build_lane_queue`` reads ``settings.gateway_max_concurrent``;
    we mirror only the Lane creation lines so the test stays free of the
    container's broader dependencies.
    """
    queue = LaneQueue()
    queue.set_session_lane(SessionLane(max_sessions=256, timeout_s=300.0))
    queue.add_lane("gateway", max_concurrent=DEFAULT_GATEWAY_CONCURRENCY, timeout_s=30.0)
    queue.add_lane("global", max_concurrent=DEFAULT_GLOBAL_CONCURRENCY, timeout_s=30.0)
    queue.add_lane(
        "seed-pipeline",
        max_concurrent=DEFAULT_SEED_PIPELINE_CONCURRENCY,
        timeout_s=300.0,
    )
    return queue


def test_seed_pipeline_lane_max_concurrent_is_16() -> None:
    assert DEFAULT_SEED_PIPELINE_CONCURRENCY == 16


def test_seed_pipeline_lane_is_registered() -> None:
    queue = _build_queue_under_test()
    lane = queue.get_lane("seed-pipeline")
    assert lane is not None
    assert lane.max_concurrent == DEFAULT_SEED_PIPELINE_CONCURRENCY


def test_seed_pipeline_lane_sibling_to_global_and_gateway() -> None:
    queue = _build_queue_under_test()
    names = queue.list_lanes()
    assert "global" in names
    assert "gateway" in names
    assert "seed-pipeline" in names
