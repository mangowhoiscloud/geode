"""PR-L3 (2026-05-26) — ``scenario_realism`` anti-elevation invariants.

The Petri judge rubric emits ``scenario_realism`` (1-10 scale) and
baseline.json persists it for *seed-generation* consumers:

- ``plugins/seed_generation/agents/critic.py:320`` reads it from
  ``baseline_snapshot.dim_means`` for the initial-generation handoff
  (no in-run pilot data available yet).
- ``plugins/seed_generation/agents/evolver.py:416`` reads it from
  pilot ``dim_means`` first, falling back to baseline.

The dim must NOT become a self-improving-loop fitness lever:
``compute_fitness`` already weights it at 0 (absent from ``DIM_WEIGHTS``)
and the autoresearch picker (``baseline_reader._operational_dim_set``)
never auto-picks it as a mutation target. The risk is a future PR
that elevates ``scenario_realism`` to ``AXIS_TIERS`` / ``DIM_WEIGHTS``
without auditing the seed-gen / autoresearch role split.

This file pins the *anti-elevation* invariant. baseline.json continues
to carry the dim (so seed-gen critic + evolver keep reading it); the
invariant only protects autoresearch's fitness surface.

Codex MCP review on the first iteration of PR-L3 caught a writer-side
filter that broke the critic's initial-gen handoff. The filter was
reverted; this anti-elevation invariant is the surviving deliverable.
"""

from __future__ import annotations

from autoresearch.train import (
    _SEED_GEN_ONLY_DIMS,
    ANCHOR_DIMS,
    AUXILIARY_DIMS,
    AXIS_TIERS,
    CRITICAL_DIMS,
    DIM_WEIGHTS,
    INFO_DIMS,
)


def test_seed_gen_only_dims_contains_scenario_realism() -> None:
    """``scenario_realism`` is the canonical seed-gen-only Petri dim and
    must stay in the documented set unless a future PR explicitly wires
    it into autoresearch fitness (and updates this invariant)."""
    assert "scenario_realism" in _SEED_GEN_ONLY_DIMS


def test_seed_gen_only_dims_absent_from_axis_tiers() -> None:
    """The anti-elevation gate. Adding any ``_SEED_GEN_ONLY_DIMS`` name to
    ``AXIS_TIERS`` would silently elevate it to a fitness lever — this
    invariant catches the diff before merge."""
    for dim in _SEED_GEN_ONLY_DIMS:
        assert dim not in AXIS_TIERS, (
            f"{dim!r} was elevated to AXIS_TIERS. Either remove from "
            "_SEED_GEN_ONLY_DIMS (after auditing the seed-gen reader "
            "contract in plugins/seed_generation/agents/{critic,evolver}.py) "
            "OR keep the dim out of fitness computation."
        )


def test_seed_gen_only_dims_absent_from_dim_weights() -> None:
    """Mirror invariant on ``DIM_WEIGHTS`` — even a 0-weight entry would
    surface the dim in caller-facing weight tables, signalling a
    fitness role that doesn't exist."""
    for dim in _SEED_GEN_ONLY_DIMS:
        assert dim not in DIM_WEIGHTS, (
            f"{dim!r} was added to DIM_WEIGHTS. autoresearch fitness "
            "never weights seed-gen-only dims; document the change in "
            "_SEED_GEN_ONLY_DIMS or drop the weight entry."
        )


def test_seed_gen_only_dims_absent_from_tier_tuples() -> None:
    """``CRITICAL_DIMS`` / ``AUXILIARY_DIMS`` / ``INFO_DIMS`` /
    ``ANCHOR_DIMS`` are all derived surfaces autoresearch readers
    consume. Any ``_SEED_GEN_ONLY_DIMS`` member must stay out of all
    four to keep the role split clean."""
    tier_surfaces = {
        "CRITICAL_DIMS": CRITICAL_DIMS,
        "AUXILIARY_DIMS": AUXILIARY_DIMS,
        "INFO_DIMS": INFO_DIMS,
        "ANCHOR_DIMS": ANCHOR_DIMS,
    }
    for dim in _SEED_GEN_ONLY_DIMS:
        for name, surface in tier_surfaces.items():
            assert dim not in surface, (
                f"{dim!r} appears in {name}. Seed-gen-only dims must "
                "stay out of every autoresearch tier surface."
            )
