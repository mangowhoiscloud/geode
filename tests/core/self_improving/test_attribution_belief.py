"""Attribution payload integration + E2 held-out (fixed-ruler) recording."""

from __future__ import annotations

from pathlib import Path

from core.self_improving.loop.observe.attribution import (
    compute_attribution,
    write_attribution,
)
from plugins.seed_generation.baseline_reader import BaselineSnapshot

# ---------------------------------------------------------------------------
# compute_attribution — payload integration
# ---------------------------------------------------------------------------


def _snap(means: dict[str, float], stderr: dict[str, float] | None = None) -> BaselineSnapshot:
    return BaselineSnapshot(dim_means=means, dim_stderr=stderr or {})


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
