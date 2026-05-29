"""Signal polarity — canonical "+ = improvement, − = regression".

PR-SIL-MULTIOBJ A4 (2026-05-29). The self-improving loop mixes two
metric families with opposite native directions:

- **Petri rubric dims** (the 1-10 concerning-behaviour scale) are
  *lower-is-better*, so a *negative* raw delta (``after - before``) is an
  improvement.
- **Positive-pressure axes** (``ux_means`` / ``admire_means`` /
  ``bench_means`` fields) are *higher-is-better*, so a *positive* raw
  delta is an improvement.

Readers of ``mutations.jsonl`` / the observability CLI could not tell
from a raw delta's sign alone whether it was good or bad (the
[[feedback_dim_convention_direction]] ambiguity — "drop" is good for a
Petri dim, bad for ``success_rate``). This module supplies a single
canonical transform so every surface can speak one language: the
``signed_improvement`` value is **positive when the agent got better**
and **negative when it got worse**, regardless of the metric's native
direction.

This is a *record / display* helper only — it does NOT feed
``compute_fitness`` (which keeps its own ``_dim_score`` transform). The
higher-is-better field set is derived from the canonical weight dicts
(``UX_DIM_WEIGHTS`` / ``ADMIRE_DIM_WEIGHTS`` / ``BENCH_DIM_WEIGHTS``) so
there is no second copy of the field names to drift.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _higher_is_better_fields() -> frozenset[str]:
    """Field names of the positive-pressure axes (higher-is-better).

    Derived from the autoresearch weight dicts (single SoT). Imported
    lazily + cached so this module has no import-time coupling to the
    ``autoresearch`` package (which imports ``core``); the first call
    resolves the set once.
    """
    from autoresearch.admire_means import ADMIRE_DIM_WEIGHTS
    from autoresearch.bench_means import BENCH_DIM_WEIGHTS
    from autoresearch.ux_means import UX_DIM_WEIGHTS

    return frozenset({*UX_DIM_WEIGHTS, *ADMIRE_DIM_WEIGHTS, *BENCH_DIM_WEIGHTS})


def metric_polarity(metric_name: str) -> int:
    """Return ``+1`` for higher-is-better metrics, ``-1`` for lower-is-better.

    Lower-is-better (the Petri rubric dims) is the default: anything not
    in the positive-pressure field set is treated as a concerning-
    behaviour dim where a lower mean is better.
    """
    return 1 if metric_name in _higher_is_better_fields() else -1


def to_signed_improvement(metric_name: str, raw_delta: float) -> float:
    """Polarity-normalised delta: positive ⇒ improvement, negative ⇒ regression.

    For a lower-is-better Petri dim the sign is flipped (a ``-6.0`` raw
    delta — the mean fell by 6 — becomes ``+6.0`` improvement); for a
    higher-is-better ux/admire/bench field the sign is unchanged.
    """
    return metric_polarity(metric_name) * float(raw_delta)


__all__ = ["metric_polarity", "to_signed_improvement"]
