"""Verify the new ``seed-generation`` Lane is wired in ``core.wiring.container``.

The first two tests call the **real** ``build_default_lanes`` (the source of
truth) so the test will drift-detect any future regression in container
wiring. The third checks the constant directly.
"""

from __future__ import annotations

import pytest
from core.wiring.container import (
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_SEED_PIPELINE_CONCURRENCY,
    build_default_lanes,
)


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


def test_seed_generation_lane_default_matches_global_safe_share() -> None:
    """PR-LANE-CAP-50 (2026-05-27) — seed-generation cap MUST be <= global.

    History:
    - PR-LQ-Phase1 (2026-05-22): lowered cap 16 → 4 because workload
      cap > global cap (8) advertised slots the leaf semaphore could
      never deliver.
    - PR-LANE-CAP-AGGRESSIVE (2026-05-27): kept global=8, seed-gen=4.
    - PR-LANE-CAP-50 (2026-05-27): operator decision raised both
      global and seed-gen to 50 in lockstep. The OpenClaw invariant
      ``workload_lane <= global_lane`` is preserved at the new
      ceiling (50 == 50)."""
    assert DEFAULT_SEED_PIPELINE_CONCURRENCY == 50
    assert DEFAULT_SEED_PIPELINE_CONCURRENCY <= DEFAULT_GLOBAL_CONCURRENCY


def test_seed_generation_lane_is_registered_by_real_builder(real_queue: object) -> None:
    lane = real_queue.get_lane("seed-generation")  # type: ignore[attr-defined]
    assert lane is not None
    assert lane.max_concurrent == DEFAULT_SEED_PIPELINE_CONCURRENCY


def test_seed_generation_lane_sibling_to_global_and_gateway(real_queue: object) -> None:
    names = real_queue.list_lanes()  # type: ignore[attr-defined]
    assert "global" in names
    assert "gateway" in names
    assert "seed-generation" in names
