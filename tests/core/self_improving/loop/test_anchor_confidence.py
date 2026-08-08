"""Anchor-dimension fitness multiplier invariants."""

from __future__ import annotations

import pytest
from core.self_improving.loop.observe.anchor_confidence import (
    ANCHOR_DIMS_NEGATIVE,
    ANCHOR_DIMS_POSITIVE,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    _normalize_anchor_score,
    compute_anchor_confidence_multiplier,
)


class TestComputeAnchorConfidenceMultiplier:
    def test_no_anchor_dims_returns_max(self) -> None:
        assert compute_anchor_confidence_multiplier({}) == MULTIPLIER_MAX

    def test_admirable_max_score(self) -> None:
        assert compute_anchor_confidence_multiplier({"admirable": 10.0}) == pytest.approx(
            MULTIPLIER_MAX
        )

    def test_admirable_min_score(self) -> None:
        assert compute_anchor_confidence_multiplier({"admirable": 1.0}) == pytest.approx(
            MULTIPLIER_MIN
        )

    def test_disappointing_inverted(self) -> None:
        assert compute_anchor_confidence_multiplier({"disappointing": 10.0}) == pytest.approx(
            MULTIPLIER_MIN
        )

    def test_disappointing_low_score(self) -> None:
        assert compute_anchor_confidence_multiplier({"disappointing": 1.0}) == pytest.approx(
            MULTIPLIER_MAX
        )

    def test_three_anchors_mean(self) -> None:
        result = compute_anchor_confidence_multiplier(
            {"admirable": 10.0, "disappointing": 1.0, "needs_attention": 1.0}
        )
        assert result == pytest.approx(MULTIPLIER_MAX)

    def test_multiplier_within_range(self) -> None:
        for admire in (1.0, 5.0, 10.0):
            for disappoint in (1.0, 5.0, 10.0):
                result = compute_anchor_confidence_multiplier(
                    {"admirable": admire, "disappointing": disappoint}
                )
                assert MULTIPLIER_MIN <= result <= MULTIPLIER_MAX

    def test_normalize_inverted(self) -> None:
        assert _normalize_anchor_score(10.0, invert=True) == pytest.approx(0.0)
        assert _normalize_anchor_score(1.0, invert=True) == pytest.approx(1.0)
        assert _normalize_anchor_score(10.0) == pytest.approx(1.0)
        assert _normalize_anchor_score(1.0) == pytest.approx(0.0)


def test_anchor_confidence_default_disabled() -> None:
    from core.config.self_improving import AutoresearchConfig

    assert AutoresearchConfig().anchor_confidence_mode is False


def test_anchor_dim_sets_are_disjoint_and_non_empty() -> None:
    assert ANCHOR_DIMS_POSITIVE
    assert ANCHOR_DIMS_NEGATIVE
    assert set(ANCHOR_DIMS_POSITIVE).isdisjoint(ANCHOR_DIMS_NEGATIVE)
