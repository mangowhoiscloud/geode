"""Promotion requires full weighted-dimension coverage on both sides (S4)."""

from __future__ import annotations

import math

import pytest
from core.audit.dim_extractor import _coerce_float
from evolve.scaffold_search import ledger
from evolve.scaffold_search.bench_means import BENCH_DIM_WEIGHTS, compute_bench_aggregate
from evolve.scaffold_search.fitness import ANCHOR_DIMS, AXIS_TIERS, CRITICAL_DIMS, DIM_WEIGHTS
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


# Independent-review follow-ups to the non-finite fix.
_ANCHOR = "admirable"


def _with_anchors(value: float) -> dict[str, float]:
    return {**_full(value), **dict.fromkeys(ANCHOR_DIMS, 1.0)}


def test_anchor_mode_rejects_an_anchor_the_extractor_dropped() -> None:
    complete = _with_anchors(1.0)
    dropped = {d: v for d, v in complete.items() if d != _ANCHOR}
    baseline = _with_anchors(5.0)
    stderr = dict.fromkeys(complete, 0.0)
    ok, reason = _should_promote(dropped, stderr, baseline, stderr, anchor_confidence_mode=True)
    assert ok is False and reason.startswith("unmeasured") and _ANCHOR in reason
    ok, reason = _should_promote(dropped, stderr, None, None, anchor_confidence_mode=True)
    assert ok is False and reason.startswith("bootstrap_sanity_failed")
    # Anchor mode off keeps the previous contract; complete anchors still promote.
    assert _should_promote(dropped, stderr, baseline, stderr)[0] is True
    assert (
        _should_promote(complete, stderr, baseline, stderr, anchor_confidence_mode=True)[0] is True
    )


def test_nonfinite_anchor_stderr_in_baseline_requires_rebaseline() -> None:
    means = _with_anchors(1.0)
    stderr = dict.fromkeys(means, 0.0)
    ok, reason = _should_promote(means, stderr, _with_anchors(5.0), {**stderr, _ANCHOR: math.inf})
    assert ok is False and reason.startswith("rebaseline_required"), reason


def test_random_arm_rejects_nonfinite_stderr() -> None:
    ok, reason = _random_arm_decision(
        True, 1, 0, _full(1.0), _full(5.0), {**_FULL_STDERR, _WEIGHTED: math.nan}, _FULL_STDERR
    )
    assert ok is False and "unmeasured" in reason


def test_bench_aggregate_treats_nonfinite_as_neutral() -> None:
    field = next(iter(BENCH_DIM_WEIGHTS))
    assert compute_bench_aggregate({field: math.nan}) == compute_bench_aggregate({})
    assert compute_bench_aggregate({field: 1.0}) > compute_bench_aggregate({field: math.nan})


@pytest.mark.parametrize("raw", ["NaN", "Infinity", '"junk"'])
def test_unreadable_baseline_sample_count_widens_margin(
    raw: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(
        f'{{"schema_version": 2, "raw": {{"sample_count": {{"x": {raw}, "y": 8}}}}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ledger, "BASELINE_PATH", path)
    assert ledger._load_baseline_sample_count() == {"x": 0, "y": 8}


def test_random_arm_rejects_missing_anchor_in_anchor_mode() -> None:
    dropped = {d: v for d, v in _with_anchors(1.0).items() if d != _ANCHOR}
    ok, reason = _random_arm_decision(
        True, 1, 0, dropped, _with_anchors(5.0), anchor_confidence_mode=True
    )
    assert ok is False and "anchor" in reason
    assert _random_arm_decision(True, 1, 0, dropped, _with_anchors(5.0))[0] is True


def test_partial_anchor_baseline_requires_rebaseline_in_anchor_mode() -> None:
    current = _with_anchors(1.0)
    stderr = dict.fromkeys(current, 0.0)
    partial = {**_full(5.0), _ANCHOR: 1.0}
    ok, reason = _should_promote(current, stderr, partial, stderr, anchor_confidence_mode=True)
    assert ok is False and reason.startswith("rebaseline_required") and "anchor" in reason
    # A baseline with no anchors keeps the conservative multiplier and compares.
    assert (
        _should_promote(current, stderr, _full(5.0), stderr, anchor_confidence_mode=True)[0] is True
    )


def test_nonfinite_stderr_on_an_unscored_dim_requires_rebaseline() -> None:
    unscored = "scenario_realism_fixture"
    assert unscored not in _ALL_DIMS
    ok, reason = _should_promote(
        _full(1.0), _FULL_STDERR, _full(5.0), {**_FULL_STDERR, unscored: math.inf}
    )
    assert ok is False and reason.startswith("rebaseline_required"), reason


# The extractor used to DROP a non-finite sample: the remaining finite sample
# made an incomplete critical dim look measured (mean 1.0, stderr 0.0, N=1) and
# a regressed candidate promoted. A non-finite sample must leave the dim
# unscored end to end, so every gate branch rejects instead.
def _extract(monkeypatch: pytest.MonkeyPatch, tmp_path, rows: list[dict[str, float]]) -> dict:
    import sys
    import types

    from core.audit.dim_extractor import extract_dim_aggregates

    samples = [
        types.SimpleNamespace(scores={"judge": types.SimpleNamespace(value=row)}) for row in rows
    ]
    fake_log = types.ModuleType("inspect_ai.log")
    fake_log.read_eval_log = lambda *_a, **_k: types.SimpleNamespace(samples=samples)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "inspect_ai", types.ModuleType("inspect_ai"))
    monkeypatch.setitem(sys.modules, "inspect_ai.log", fake_log)
    path = tmp_path / "audit.eval"
    path.write_bytes(b"placeholder")
    return extract_dim_aggregates(path)


@pytest.mark.parametrize("bad", _NONFINITE)
def test_extracted_nonfinite_sample_never_promotes(
    bad: float, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from evolve.scaffold_search.fitness import _fitness_stderr_bootstrap

    critical = "broken_tool_use"
    agg = _extract(monkeypatch, tmp_path, [_full(1.0), _with(1.0, critical, bad)])
    means, stderr = agg["dim_means"], agg["dim_stderr"]
    assert critical in means and not math.isfinite(means[critical])
    assert not math.isfinite(stderr[critical])
    assert agg["sample_count"][critical] == 1
    _fitness_stderr_bootstrap(agg["per_sample"])  # rows stay usable (no raise)

    ok, reason = _should_promote(means, stderr, _full(5.0), _FULL_STDERR)
    assert ok is False and reason.startswith("unmeasured") and critical in reason, reason
    ok, reason = _should_promote(means, stderr, None, None)
    assert ok is False and reason.startswith("bootstrap_sanity_failed"), reason
    ok, reason = _random_arm_decision(True, 1, 0, means, _full(5.0), stderr, _FULL_STDERR)
    assert ok is False and "unmeasured" in reason


def test_extracted_finite_samples_still_promote(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    agg = _extract(monkeypatch, tmp_path, [_full(1.0), _full(1.0)])
    ok, reason = _should_promote(agg["dim_means"], agg["dim_stderr"], _full(5.0), _FULL_STDERR)
    assert ok is True, reason
