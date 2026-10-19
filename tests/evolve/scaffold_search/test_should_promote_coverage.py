"""Promotion requires full weighted-dimension coverage on both sides (S4)."""

from __future__ import annotations

import math

import pytest
from core.audit.dim_extractor import _coerce_float
from evolve.scaffold_search.fitness import AXIS_TIERS, CRITICAL_DIMS, DIM_WEIGHTS
from evolve.scaffold_search.gate import _random_arm_decision, _should_promote

_STDERR = dict.fromkeys(DIM_WEIGHTS, 0.0)


def _means(value: float) -> dict[str, float]:
    return dict.fromkeys(DIM_WEIGHTS, value)


def test_complete_real_improvement_still_promotes() -> None:
    ok, reason = _should_promote(_means(4.0), _STDERR, _means(5.0), _STDERR)
    assert ok is True, reason


def test_dropping_a_dim_cannot_turn_reject_into_promote() -> None:
    baseline = _means(5.0)
    assert _should_promote(_means(5.0), _STDERR, baseline, _STDERR)[0] is False
    for dim in DIM_WEIGHTS:
        partial = {d: v for d, v in _means(5.0).items() if d != dim}
        ok, reason = _should_promote(partial, _STDERR, baseline, _STDERR)
        assert ok is False and reason.startswith("unmeasured"), dim


def test_targeted_improvement_cannot_carry_missing_other_dims() -> None:
    target = next(d for d in DIM_WEIGHTS if d not in CRITICAL_DIMS)
    current = {target: 1.0, **dict.fromkeys(CRITICAL_DIMS, 5.0)}
    ok, reason = _should_promote(
        current, _STDERR, _means(5.0), _STDERR, targeted_dims=frozenset({target})
    )
    assert ok is False and reason.startswith("unmeasured")


def test_incomplete_baseline_requires_rebaseline() -> None:
    stale = dict.fromkeys(CRITICAL_DIMS, 5.0)
    ok, reason = _should_promote(_means(1.0), _STDERR, stale, _STDERR)
    assert ok is False and reason.startswith("rebaseline_required")


def test_random_control_arm_never_writes_incomplete_measurement() -> None:
    ok, reason = _random_arm_decision(True, 7, 3, {"broken_tool_use": 1.0}, _means(5.0))
    assert ok is False and "unmeasured" in reason
    assert _random_arm_decision(True, 7, 3, _means(4.0), _means(5.0))[0] is True
    assert _random_arm_decision(False, 7, 3, _means(4.0), _means(5.0))[0] is False


# Non-finite values (S4 follow-up): every comparison with NaN is false, so a NaN
# dim used to pass the bootstrap floor, the margin and the random arm.
_ALL_DIMS = set(DIM_WEIGHTS) | set(AXIS_TIERS)
_NONFINITE = (math.nan, math.inf, -math.inf)


def _full(value: float) -> dict[str, float]:
    return dict.fromkeys(_ALL_DIMS, value)


def _with(value: float, dim: str, bad: float) -> dict[str, float]:
    return {**_full(value), dim: bad}


_WEIGHTED = next(iter(sorted(DIM_WEIGHTS)))
_FULL_STDERR = _full(0.0)


@pytest.mark.parametrize("bad", _NONFINITE)
def test_extractor_drops_nonfinite_scores(bad: float) -> None:
    assert _coerce_float(bad) is None
    assert _coerce_float(2.5) == 2.5
    assert _coerce_float(3) == 3.0


@pytest.mark.parametrize("bad", _NONFINITE)
def test_nonfinite_candidate_never_promotes(bad: float) -> None:
    current = _with(1.0, _WEIGHTED, bad)
    ok, reason = _should_promote(current, _FULL_STDERR, _full(5.0), _FULL_STDERR)
    assert ok is False and reason.startswith("unmeasured"), reason
    ok, reason = _should_promote(current, _FULL_STDERR, None, None)
    assert ok is False and reason.startswith("bootstrap_sanity_failed"), reason
    ok, reason = _random_arm_decision(True, 1, 0, current, _full(5.0))
    assert ok is False and "unmeasured" in reason


@pytest.mark.parametrize("bad", _NONFINITE)
def test_nonfinite_baseline_requires_rebaseline(bad: float) -> None:
    ok, reason = _should_promote(_full(1.0), _FULL_STDERR, _with(5.0, _WEIGHTED, bad), _FULL_STDERR)
    assert ok is False and reason.startswith("rebaseline_required"), reason


def test_nonfinite_stderr_never_promotes() -> None:
    nan_stderr = {**_FULL_STDERR, _WEIGHTED: math.nan}
    ok, reason = _should_promote(_full(1.0), nan_stderr, _full(5.0), _FULL_STDERR)
    assert ok is False and reason.startswith("unmeasured"), reason
    ok, reason = _should_promote(
        _full(1.0), _FULL_STDERR, _full(5.0), _FULL_STDERR, current_fitness_stderr=math.nan
    )
    assert ok is False and "fitness stderr" in reason


def test_finite_complete_improvement_unchanged() -> None:
    assert _should_promote(_full(1.0), _FULL_STDERR, _full(5.0), _FULL_STDERR)[0] is True
    assert _should_promote(_full(1.0), _FULL_STDERR, None, None)[0] is True
