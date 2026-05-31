"""PR-E — attribution × CognitiveState confidence-stability term.

Concern #5 from the post-sprint frontier matrix: PR-5's
``compute_attribution`` ignored the per-round confidence trajectory
the reflection node (PR-3) produced and PR-4's episodic memory
persisted. Two mutations with identical dim deltas but wildly
different belief stability now produce distinct attribution
payloads via the new ``confidence_stability`` term.

PR-E intentionally leaves ``attribution_score`` unchanged so PR-6
policy-mutation aggregators can weight dim-deltas vs belief
stability independently.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.self_improving.loop.attribution import (
    _confidence_stability,
    compute_attribution,
    confidence_trajectory_from_episodes,
    write_attribution,
)
from plugins.seed_generation.baseline_reader import BaselineSnapshot

# ---------------------------------------------------------------------------
# _confidence_stability — variance math
# ---------------------------------------------------------------------------


def test_stability_constant_trajectory_returns_one() -> None:
    """All-equal trajectory → stddev=0 → stability=1.0 (rock-steady)."""
    assert _confidence_stability([0.5, 0.5, 0.5, 0.5]) == pytest.approx(1.0)


def test_stability_extreme_oscillation_clamped_to_zero() -> None:
    """[0, 1, 0, 1] has sample stddev ≈ 0.577 → 1 - 0.577 ≈ 0.42.
    A 0..1-binary alternating series isn't fully clamped; pin the
    expected value so a future formula tweak surfaces here."""
    stability = _confidence_stability([0.0, 1.0, 0.0, 1.0])
    assert stability is not None
    assert stability == pytest.approx(1.0 - math.sqrt(1.0 / 3.0))


def test_stability_below_two_samples_returns_none() -> None:
    """Variance undefined for <2 samples — caller treats None as
    'no signal' rather than fabricating a number."""
    assert _confidence_stability([]) is None
    assert _confidence_stability([0.7]) is None


def test_stability_drops_non_numeric_entries() -> None:
    """``"high"`` / ``True`` / ``None`` are silently dropped, mirrors
    PR-3 reflection's bool-exclusion guard."""
    out = _confidence_stability([0.5, "high", 0.5, True, None, 0.5])  # type: ignore[list-item]
    # Only 3 numerics survived; stddev = 0 → stability = 1.0
    assert out == pytest.approx(1.0)


def test_stability_drops_out_of_range_entries() -> None:
    """Values outside [0,1] are not valid confidence — drop them."""
    out = _confidence_stability([0.5, 1.5, -0.2, 0.5])
    # Two 0.5s survive → stddev=0 → stability=1.0
    assert out == pytest.approx(1.0)


def test_stability_moderate_variance() -> None:
    """Smooth trajectory ``[0.4, 0.5, 0.6]`` — small variance → high
    stability (close to 1.0)."""
    out = _confidence_stability([0.4, 0.5, 0.6])
    assert out is not None
    assert 0.8 < out < 1.0


# ---------------------------------------------------------------------------
# confidence_trajectory_from_episodes — episodic adapter
# ---------------------------------------------------------------------------


def _episode(confidence: float | None | str) -> SimpleNamespace:
    """Build a duck-typed Episode (PR-4 dataclass) just for the
    trajectory extractor — we don't need the full Episode shape."""
    return SimpleNamespace(cognitive_state={"confidence": confidence})


def test_trajectory_extracts_confidence_in_order() -> None:
    """The helper preserves the input order (PR-4 ``recent()`` is
    newest-first; callers reverse if they want chronological)."""
    eps = [_episode(0.8), _episode(0.7), _episode(0.6)]
    assert confidence_trajectory_from_episodes(eps) == [0.8, 0.7, 0.6]


def test_trajectory_skips_missing_or_non_numeric() -> None:
    eps = [
        _episode(0.5),
        _episode(None),
        _episode("high"),
        SimpleNamespace(cognitive_state=None),  # cognitive_state not a dict
        SimpleNamespace(),  # no cognitive_state at all
        _episode(0.6),
    ]
    assert confidence_trajectory_from_episodes(eps) == [0.5, 0.6]


def test_trajectory_drops_out_of_range() -> None:
    eps = [_episode(0.5), _episode(1.5), _episode(-0.2), _episode(0.7)]
    assert confidence_trajectory_from_episodes(eps) == [0.5, 0.7]


def test_trajectory_drops_bool() -> None:
    """``bool`` is an ``int`` subclass — exclude same as PR-5
    expected_dim coercion."""
    eps = [
        _episode(0.5),
        SimpleNamespace(cognitive_state={"confidence": True}),
        SimpleNamespace(cognitive_state={"confidence": False}),
        _episode(0.7),
    ]
    assert confidence_trajectory_from_episodes(eps) == [0.5, 0.7]


# ---------------------------------------------------------------------------
# compute_attribution — payload integration
# ---------------------------------------------------------------------------


def _snap(means: dict[str, float], stderr: dict[str, float] | None = None) -> BaselineSnapshot:
    return BaselineSnapshot(dim_means=means, dim_stderr=stderr or {})


def test_payload_carries_confidence_trajectory_and_stability() -> None:
    """Pin the new payload keys so a downstream consumer (PR-6
    policy-mutation aggregator) can rely on them."""
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=_snap({"safety": 0.5}, {"safety": 0.05}),
        baseline_after=_snap({"safety": 0.8}, {"safety": 0.05}),
        confidence_trajectory=[0.5, 0.5, 0.5],
    )
    assert payload["confidence_trajectory"] == [0.5, 0.5, 0.5]
    assert payload["confidence_stability"] == pytest.approx(1.0)


def test_payload_stability_is_none_without_trajectory() -> None:
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={},
        baseline_before=_snap({"safety": 0.5}),
        baseline_after=_snap({"safety": 0.5}),
    )
    assert payload["confidence_trajectory"] == []
    assert payload["confidence_stability"] is None


def test_payload_stability_is_none_for_single_sample() -> None:
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={},
        baseline_before=_snap({"safety": 0.5}),
        baseline_after=_snap({"safety": 0.5}),
        confidence_trajectory=[0.7],
    )
    assert payload["confidence_trajectory"] == [0.7]
    assert payload["confidence_stability"] is None


def test_attribution_score_unchanged_by_trajectory() -> None:
    """The dim-delta-driven attribution_score must NOT shift just
    because a trajectory was supplied. PR-E keeps the two signals
    orthogonal so PR-6 can weight them independently."""
    before = _snap({"safety": 0.5}, {"safety": 0.05})
    after = _snap({"safety": 0.8}, {"safety": 0.05})
    without = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=before,
        baseline_after=after,
    )
    with_traj = compute_attribution(
        mutation_id="m-1",
        expected_dim={"safety": 0.3},
        baseline_before=before,
        baseline_after=after,
        confidence_trajectory=[0.1, 0.9, 0.1, 0.9],  # wildly unstable
    )
    assert with_traj["attribution_score"] == without["attribution_score"]


def test_payload_with_missing_baseline_still_carries_trajectory() -> None:
    """Even when the dim signal is absent (missing baseline), the
    trajectory + stability should still be recorded so the row
    captures *some* signal about the mutation's belief impact."""
    payload = compute_attribution(
        mutation_id="m-1",
        expected_dim={},
        baseline_before=None,
        baseline_after=_snap({"safety": 0.5}),
        confidence_trajectory=[0.5, 0.5, 0.5],
    )
    assert payload["missing_baseline"] is True
    assert payload["confidence_trajectory"] == [0.5, 0.5, 0.5]
    assert payload["confidence_stability"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# write_attribution — forwarding
# ---------------------------------------------------------------------------


def test_write_attribution_forwards_trajectory(tmp_path: Path) -> None:
    log_path = tmp_path / "mutations.jsonl"
    before = _snap({"safety": 0.5}, {"safety": 0.05})
    after = _snap({"safety": 0.8}, {"safety": 0.05})
    payload = write_attribution(
        mutation_id="m-99",
        expected_dim={"safety": 0.3},
        baseline_before=before,
        baseline_after=after,
        confidence_trajectory=[0.5, 0.5, 0.5],
        log_path=log_path,
    )
    assert payload["confidence_trajectory"] == [0.5, 0.5, 0.5]
    assert payload["confidence_stability"] == pytest.approx(1.0)
    # Row also on disk
    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# __all__ surface
# ---------------------------------------------------------------------------


def test_helper_exported_in_all() -> None:
    """PR-6 policy-mutation aggregator will import this helper —
    pin the public surface."""
    from core.self_improving.loop import attribution

    assert "confidence_trajectory_from_episodes" in attribution.__all__


# ---------------------------------------------------------------------------
# E2 — per-cycle held-out (fixed-ruler) fitness recording
# ---------------------------------------------------------------------------


def test_held_out_fitness_recorded_when_both_fields_present() -> None:
    """E2: when a held-out bench is scored, both fields land in the payload on the
    canonical 0-1 scale (rounded), distinct from the co-evolving fitness_after."""
    payload = compute_attribution(
        mutation_id="m-ho",
        expected_dim={"safety": 0.3},
        baseline_before=_snap({"safety": 0.5}, {"safety": 0.05}),
        baseline_after=_snap({"safety": 0.8}, {"safety": 0.05}),
        fitness_before=0.65,
        fitness_after=0.71,
        held_out_fitness=0.6123456,
        held_out_bench_id="pool-c16d186178e1",
    )
    assert payload["held_out_fitness"] == 0.612346  # rounded to 6 dp
    assert payload["held_out_bench_id"] == "pool-c16d186178e1"
    # The fixed-ruler value is recorded SEPARATELY from the co-evolving fitness —
    # held_out_fitness != fitness_after, the whole point of the second ruler.
    assert payload["fitness_after"] == 0.71
    assert payload["held_out_fitness"] != payload["fitness_after"]


def test_held_out_fields_omitted_when_no_bench_scored() -> None:
    """E2: None bench (no held-out configured) → both fields OMITTED entirely so
    legacy / no-bench rows keep their exact shape (backward-compatible)."""
    payload = compute_attribution(
        mutation_id="m-none",
        expected_dim={"safety": 0.3},
        baseline_before=_snap({"safety": 0.5}),
        baseline_after=_snap({"safety": 0.8}),
        held_out_fitness=None,
        held_out_bench_id=None,
    )
    assert "held_out_fitness" not in payload
    assert "held_out_bench_id" not in payload


def test_held_out_fields_omitted_when_only_one_present() -> None:
    """Both must be present together — a half-populated pair (id without fitness,
    or vice versa) records neither, so a downstream curve never sees a point with
    a fitness but no ruler id (or an id with no value)."""
    only_fitness = compute_attribution(
        mutation_id="m-half",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        held_out_fitness=0.5,
        held_out_bench_id=None,
    )
    assert "held_out_fitness" not in only_fitness
    only_id = compute_attribution(
        mutation_id="m-half2",
        expected_dim={},
        baseline_before=None,
        baseline_after=None,
        held_out_fitness=None,
        held_out_bench_id="pool-x",
    )
    assert "held_out_bench_id" not in only_id


def test_write_attribution_forwards_held_out_to_disk(tmp_path: Path) -> None:
    """E2: write_attribution forwards the held-out pair through to the on-disk
    mutations.jsonl row (per-cycle curve SoT)."""
    import json

    log_path = tmp_path / "mutations.jsonl"
    payload = write_attribution(
        mutation_id="m-disk",
        expected_dim={"safety": 0.3},
        baseline_before=_snap({"safety": 0.5}, {"safety": 0.05}),
        baseline_after=_snap({"safety": 0.8}, {"safety": 0.05}),
        held_out_fitness=0.634,
        held_out_bench_id="pool-c16d186178e1",
        log_path=log_path,
    )
    assert payload["held_out_fitness"] == 0.634
    on_disk = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert on_disk["held_out_fitness"] == 0.634
    assert on_disk["held_out_bench_id"] == "pool-c16d186178e1"
