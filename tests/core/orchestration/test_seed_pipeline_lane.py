"""Verify the new ``seed-pipeline`` Lane is wired in ``core.wiring.container``.

The first two tests call the **real** ``build_default_lanes`` (the source of
truth) so the test will drift-detect any future regression in container
wiring. The third checks the constant directly.
"""

from __future__ import annotations

import pytest
from core.wiring.container import DEFAULT_SEED_PIPELINE_CONCURRENCY, build_default_lanes


@pytest.fixture
def real_queue(monkeypatch: pytest.MonkeyPatch) -> object:
    """Call the production ``build_default_lanes`` with a benign settings stub.

    ``build_default_lanes`` reads ``settings.gateway_max_concurrent`` from
    ``core.config``; we monkeypatch that single attribute so the test
    doesn't depend on user env or config TOMLs.
    """
    from core import config as _config

    class _StubSettings:
        gateway_max_concurrent = 0  # → falls back to DEFAULT_GATEWAY_CONCURRENCY

    monkeypatch.setattr(_config, "settings", _StubSettings(), raising=False)
    return build_default_lanes()


def test_seed_pipeline_lane_max_concurrent_is_16() -> None:
    assert DEFAULT_SEED_PIPELINE_CONCURRENCY == 16


def test_seed_pipeline_lane_is_registered_by_real_builder(real_queue: object) -> None:
    lane = real_queue.get_lane("seed-pipeline")  # type: ignore[attr-defined]
    assert lane is not None
    assert lane.max_concurrent == DEFAULT_SEED_PIPELINE_CONCURRENCY


def test_seed_pipeline_lane_sibling_to_global_and_gateway(real_queue: object) -> None:
    names = real_queue.list_lanes()  # type: ignore[attr-defined]
    assert "global" in names
    assert "gateway" in names
    assert "seed-pipeline" in names
